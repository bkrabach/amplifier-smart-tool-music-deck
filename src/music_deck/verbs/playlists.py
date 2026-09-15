"""`playlists`, `playlist items|create|add|remove|reorder|rename`.

Contracts served
----------------
* ``cli.v1`` Core 2 -- deterministic; no model anywhere in this file.
* ``cli.v1`` Core 4 -- one JSON document per result; every emitted item carries
  ``external_urls.spotify`` (Spotify's own for items it returns, and
  :func:`catalog.item_ref`'s for the things a *write* acted on, which Spotify
  answers with a ``snapshot_id`` and nothing else).
* ``cli.v1`` Core 6 -- ``playlist_items_unavailable`` for a playlist the caller
  neither owns nor collaborates on. The mapping itself lives in ``http.py``,
  where every 403 is named exactly once; this module's job is to request the
  path that provokes it and let the client speak.
* ``cli.v1`` Core 6 -- ``partial_result`` when a multi-request write gets part
  way. Adding 250 items is three requests; if the third refuses, two hundred
  items are already in the playlist, and saying so is the only honest answer.
* ``boundary.v1`` Core 7 -- ``/playlists/{id}/items``, which is what February
  2026 renamed the old ``tracks`` sub-resource to, and ``POST /me/playlists``,
  which is what it renamed the old per-user creation endpoint to. Neither old
  name appears in this file; the guard in ``http.py`` refuses both.

What Spotify caps, and what music-deck does about it
----------------------------------------------------
======================================= ==================================
Spotify                                 music-deck
======================================= ==================================
``GET /me/playlists`` limit max 50      pages until ``--limit`` or exhaustion
``POST /playlists/{id}/items`` max 100  one request per 100, in order
"no endpoint for deleting a playlist"   there is no ``playlist delete`` verb
======================================= ==================================
"""

from __future__ import annotations

from typing import Any, Final, Sequence

from music_deck.errors import ErrorCode, MusicDeckError
from music_deck.http import SpotifyClient
from music_deck.verbs.auth_verbs import spotify_client
from music_deck.verbs.catalog import batches, item_ref, to_id, to_uri, unique

ITEMS_PER_REQUEST: Final = 100
"""Verbatim from Spotify's reference: "A maximum of 100 items can be added in
one request." Applies to adding and to removing."""

MINE: Final = "/me/playlists"
"""The caller's own playlists: listed with GET, created with POST. February 2026
withdrew every per-user path, including the old creation endpoint, so this is
the only way to make a playlist."""


def _client(client: SpotifyClient | None) -> SpotifyClient:
    return client if client is not None else spotify_client()


def _items_path(playlist_id: str) -> str:
    """``/playlists/{id}/items`` -- the February 2026 name for the sub-resource."""
    return f"/playlists/{to_id(playlist_id, 'playlist')}/items"


def _playlist_path(playlist_id: str) -> str:
    return f"/playlists/{to_id(playlist_id, 'playlist')}"


def _track_uris(values: Sequence[str]) -> list[str]:
    """Caller references -> ``spotify:track:<id>`` URIs, de-duplicated.

    De-duplication is deliberate and reported: Spotify happily stores the same
    track twice, and a caller who passed it twice by accident would otherwise
    have no way to notice.
    """
    if not values:
        raise MusicDeckError(
            ErrorCode.USAGE,
            "No tracks were named.",
            "Pass one or more track ids, spotify:track:<id> URIs, or "
            "open.spotify.com links.",
        )
    return unique(to_uri(value, "track") for value in values)


def _partial(
    action: str,
    playlist_id: str,
    done: int,
    requested: int,
    sent: int,
    failure: MusicDeckError,
) -> MusicDeckError:
    """The refusal for a batched write that got part way.

    ``cli.v1`` Core 6: ``partial_result`` carries "a ``completeness`` block
    naming what succeeded and failed -- never a silently truncated success".
    """
    unknown_write = failure.diagnostic_code == "network_unreachable"
    if unknown_write:
        message = (
            f"{done} of {requested} items were {action}, then the next Spotify "
            "write had an unknown outcome."
        )
        remedy = (
            "Do not retry the unresolved write automatically. Read the playlist "
            "state, then repeat only work you can confirm did not complete."
        )
    else:
        message = (
            f"{done} of {requested} items were {action}, then Spotify refused "
            f"`{failure.code}`: {failure.message}"
        )
        remedy = (
            "Re-run with only the items that did not land; the ones already "
            f"{action} are in the playlist. Then read the remedy for "
            f"`{failure.code}`: {failure.remedy}"
        )
    completeness = {
        "requested": requested,
        "succeeded": done,
        "failed": requested - done,
        "requests_sent": sent,
        "underlying_code": failure.code,
    }
    if unknown_write:
        completeness["unknown_write"] = True
    return MusicDeckError(
        ErrorCode.PARTIAL_RESULT,
        message,
        remedy,
        completeness=completeness,
        playlist=item_ref("playlist", playlist_id),
    )


# --------------------------------------------------------------------------- #
# reads
# --------------------------------------------------------------------------- #
def playlists(
    *, limit: int = 20, client: SpotifyClient | None = None
) -> dict[str, Any]:
    """The signed-in account's playlists -- ``GET /me/playlists``."""
    found = _client(client).paginate(MINE, limit=limit)
    return {"requested": limit, "returned": len(found), "playlists": found}


def playlist_items(
    playlist_id: str, *, limit: int = 20, client: SpotifyClient | None = None
) -> dict[str, Any]:
    """The items of one playlist -- ``GET /playlists/{id}/items``.

    Spotify returns these only to an account that owns or collaborates on the
    playlist; anything else answers 403, which the client turns into
    ``playlist_items_unavailable`` (``cli.v1`` Core 6). Nothing is caught here:
    a refusal is the answer, and the caller gets it whole.
    """
    found = _client(client).paginate(_items_path(playlist_id), limit=limit)
    return {
        "playlist": item_ref("playlist", playlist_id),
        "requested": limit,
        "returned": len(found),
        "items": found,
    }


# --------------------------------------------------------------------------- #
# writes
# --------------------------------------------------------------------------- #
def playlist_create(
    name: str,
    *,
    description: str | None = None,
    public: bool = False,
    client: SpotifyClient | None = None,
) -> Any:
    """Create a playlist -- ``POST /me/playlists``.

    Private by default. ``cli.v1`` leaves write fencing an open question, so the
    conservative default is the one that cannot embarrass anybody: a playlist an
    agent made is not published to a profile unless the caller says ``--public``.
    """
    label = (name or "").strip()
    if not label:
        raise MusicDeckError(
            ErrorCode.USAGE,
            "A playlist needs a name.",
            'Pass one, e.g. music-deck playlist create "Late night".',
        )
    body: dict[str, Any] = {"name": label, "public": bool(public)}
    if description:
        body["description"] = description
    return _client(client).post(MINE, body)


def playlist_add(
    playlist_id: str,
    tracks: Sequence[str],
    *,
    client: SpotifyClient | None = None,
) -> dict[str, Any]:
    """Add tracks -- ``POST /playlists/{id}/items``, 100 per request.

    250 URIs is three requests of 100, 100 and 50, sent in order so the playlist
    ends up in the order the caller asked for.
    """
    uris = _track_uris(tracks)
    api = _client(client)
    path = _items_path(playlist_id)

    snapshots: list[str] = []
    added = 0
    for index, chunk in enumerate(batches(uris, ITEMS_PER_REQUEST)):
        try:
            payload = api.post(path, {"uris": chunk})
        except MusicDeckError as failure:
            if added == 0:
                raise
            raise _partial(
                "added", playlist_id, added, len(uris), index, failure
            ) from failure
        added += len(chunk)
        if isinstance(payload, dict) and payload.get("snapshot_id"):
            snapshots.append(str(payload["snapshot_id"]))

    return {
        "playlist": item_ref("playlist", playlist_id),
        "added": added,
        "requests_sent": len(batches(uris, ITEMS_PER_REQUEST)),
        "items_per_request": ITEMS_PER_REQUEST,
        "snapshot_id": snapshots[-1] if snapshots else None,
        "snapshot_ids": snapshots,
        "uris": uris,
    }


def playlist_remove(
    playlist_id: str,
    tracks: Sequence[str],
    *,
    client: SpotifyClient | None = None,
) -> dict[str, Any]:
    """Remove tracks -- ``DELETE /playlists/{id}/items``, 100 per request.

    February 2026 renamed the request body's parameter from ``tracks`` to
    ``items``; each entry is an object carrying the URI, as it always was.
    """
    uris = _track_uris(tracks)
    api = _client(client)
    path = _items_path(playlist_id)

    snapshots: list[str] = []
    removed = 0
    for index, chunk in enumerate(batches(uris, ITEMS_PER_REQUEST)):
        body = {"items": [{"uri": uri} for uri in chunk]}
        try:
            payload = api.delete(path, body)
        except MusicDeckError as failure:
            if removed == 0:
                raise
            raise _partial(
                "removed", playlist_id, removed, len(uris), index, failure
            ) from failure
        removed += len(chunk)
        if isinstance(payload, dict) and payload.get("snapshot_id"):
            snapshots.append(str(payload["snapshot_id"]))

    return {
        "playlist": item_ref("playlist", playlist_id),
        "removed": removed,
        "requests_sent": len(batches(uris, ITEMS_PER_REQUEST)),
        "items_per_request": ITEMS_PER_REQUEST,
        "snapshot_id": snapshots[-1] if snapshots else None,
        "snapshot_ids": snapshots,
        "uris": uris,
    }


def playlist_reorder(
    playlist_id: str,
    *,
    range_start: int,
    insert_before: int,
    range_length: int = 1,
    client: SpotifyClient | None = None,
) -> dict[str, Any]:
    """Move a run of items -- ``PUT /playlists/{id}/items``.

    Indices are zero-based and Spotify's own: ``range_start`` is where the run
    begins, ``insert_before`` is the position it should land in front of.
    """
    if range_start < 0 or insert_before < 0:
        raise MusicDeckError(
            ErrorCode.USAGE,
            "Playlist positions are zero-based and cannot be negative "
            f"(--range-start {range_start}, --insert-before {insert_before}).",
            "Count from 0: the first item is position 0.",
        )
    if range_length < 1:
        raise MusicDeckError(
            ErrorCode.USAGE,
            f"--range-length must be at least 1; got {range_length}.",
            "Move one or more items.",
        )

    payload = _client(client).put(
        _items_path(playlist_id),
        {
            "range_start": range_start,
            "insert_before": insert_before,
            "range_length": range_length,
        },
    )
    return {
        "playlist": item_ref("playlist", playlist_id),
        "moved": range_length,
        "range_start": range_start,
        "insert_before": insert_before,
        "snapshot_id": (payload or {}).get("snapshot_id")
        if isinstance(payload, dict)
        else None,
    }


def playlist_rename(
    playlist_id: str, name: str, *, client: SpotifyClient | None = None
) -> dict[str, Any]:
    """Rename a playlist -- ``PUT /playlists/{id}``.

    Spotify answers this one with an empty body, so the document music-deck
    returns is its own: what was renamed, and what to.
    """
    label = (name or "").strip()
    if not label:
        raise MusicDeckError(
            ErrorCode.USAGE,
            "A playlist needs a name.",
            'Pass the new name, e.g. music-deck playlist rename <id> "Late night".',
        )
    _client(client).put(_playlist_path(playlist_id), {"name": label})
    return {
        "playlist": item_ref("playlist", playlist_id),
        "renamed": True,
        "name": label,
    }
