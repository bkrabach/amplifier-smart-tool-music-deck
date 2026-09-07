"""`library list|save|remove|contains` and `following` -- the saved library.

Contracts served
----------------
* ``cli.v1`` Core 2 -- deterministic; no model anywhere in this file.
* ``cli.v1`` Core 4 -- one JSON document per result; every emitted Spotify item
  carries ``external_urls.spotify``.
* ``boundary.v1`` Core 7 -- the February 2026 surface, and only it.

Which endpoint does what, after February 2026
---------------------------------------------
This is the family the changelog rearranged most, so it is worth being explicit
about what survived and what did not:

============================ ======== ==========================================
What the caller wants        Endpoint Note
============================ ======== ==========================================
list what is saved           ``GET /me/<type>``    the *reads* survived, one per
                                                   content type, paged
save / follow anything       ``PUT /me/library``    **URIs, not ids**; mixed
                                                   types in one request
remove / unfollow anything   ``DELETE /me/library`` **URIs, not ids**
is it saved / followed?      ``GET /me/library/contains`` **URIs, not ids**
who does the account follow? ``GET /me/following``  read only; the write is gone
============================ ======== ==========================================

The type-specific **writes** (``PUT``/``DELETE /me/<type>``) and the
type-specific **contains** endpoints were withdrawn; ``http.py``'s guard refuses
them, and nothing in this file constructs one. The type-specific *reads* were
not withdrawn, and ``library list`` uses them because they are the only way
Spotify offers to enumerate what is saved -- evidence brief §4.4, whose "User
library" table lists ``GET /me/tracks`` and its siblings as available and gives
``/me/library`` only ``PUT`` and ``DELETE``.

Why saving takes a URI and not an id
------------------------------------
Migration guide, verbatim: "The new ``PUT /me/library`` endpoint accepts Spotify
URIs instead of IDs, allowing you to save or follow any supported content type
in a single request." A bare id carries no type, so music-deck refuses one here
rather than guessing that a 22-character string is a track.

Where the URIs travel: the query string, not a JSON body
--------------------------------------------------------
All three ``/me/library`` calls -- ``PUT``, ``DELETE`` and ``GET .../contains``
-- read ``uris`` from the **query string**. A JSON body carrying the same field
is not read at all, and the endpoint answers ``400 {"error": {"status": 400,
"message": "Missing required field: uris"}}``: an error that names the field you
did send, which reads like a serialization bug and is in fact the wrong
transport.

Measured live against ``api.spotify.com`` on 2026-09-06, one account, one empty
playlist (``spotify:playlist:0000000000000000000000``), four requests:

============================================ ======================================
Request                                      Answer
============================================ ======================================
``DELETE /me/library`` body ``{"uris": [_]}`` ``400 Missing required field: uris``
``DELETE /me/library?uris=<uri>``            ``200``; playlist left ``/me/playlists``
``PUT /me/library`` body ``{"uris": [_]}``   ``400 Missing required field: uris``
``PUT /me/library?uris=<uri>``               ``200``; playlist returned to it
============================================ ======================================

So both writes pass ``uris=`` as a parameter, exactly as ``library contains``
already did -- ``SpotifyClient._url`` renders a list of URIs comma-separated,
which is the multi-value form Spotify takes here. This is the whole reason
``apply`` could create a playlist that nothing in the tool could remove: the
playlist-follower deletion that used to do it is on ``boundary.v1`` Core 7's
withdrawn list (``http.py``'s guard holds the literal, so this file does not),
and ``DELETE /me/library`` is its only replacement.
"""

from __future__ import annotations

from typing import Any, Final, Sequence

from music_deck.errors import ErrorCode, MusicDeckError
from music_deck.http import DEFAULT_PAGE_CAP, SpotifyClient
from music_deck.verbs.auth_verbs import spotify_client
from music_deck.verbs.catalog import to_any_uri, unique, uri_ref

LIBRARY: Final = "/me/library"
"""Save and remove, any content type, by URI. February 2026 replaced the
type-specific writes with this one."""

CONTAINS: Final = f"{LIBRARY}/contains"
"""Ask whether items are saved or followed -- by URI, any content type."""

FOLLOWING: Final = "/me/following"
"""The one part of the follow family that survived, and it is read only."""

SAVED_KINDS: Final[tuple[str, ...]] = (
    "tracks",
    "albums",
    "shows",
    "episodes",
    "audiobooks",
)
"""The content types ``GET /me/<type>`` still enumerates."""


def _client(client: SpotifyClient | None) -> SpotifyClient:
    return client if client is not None else spotify_client()


def _uris(values: Sequence[str], verb: str) -> list[str]:
    if not values:
        raise MusicDeckError(
            ErrorCode.USAGE,
            f"`music-deck library {verb}` was given nothing to act on.",
            "Pass one or more spotify:<kind>:<id> URIs or open.spotify.com links.",
        )
    return unique(to_any_uri(value) for value in values)


def _refs(uris: Sequence[str]) -> list[dict[str, Any]]:
    """Each URI as an item carrying its own link -- ``cli.v1`` Core 4."""
    return [uri_ref(uri) for uri in uris]


# --------------------------------------------------------------------------- #
# reads
# --------------------------------------------------------------------------- #
def library_list(
    *,
    kind: str = "tracks",
    limit: int = 20,
    client: SpotifyClient | None = None,
) -> dict[str, Any]:
    """What the account has saved of one content type -- ``GET /me/<type>``."""
    if kind not in SAVED_KINDS:
        raise MusicDeckError(
            ErrorCode.USAGE,
            f"--type {kind!r} is not a library content type.",
            f"Use one of: {', '.join(SAVED_KINDS)}.",
        )
    found = _client(client).paginate(f"/me/{kind}", limit=limit)
    return {
        "type": kind,
        "requested": limit,
        "returned": len(found),
        "items": found,
    }


def library_contains(
    items: Sequence[str], *, client: SpotifyClient | None = None
) -> dict[str, Any]:
    """Is each item saved or followed? -- ``GET /me/library/contains``.

    Spotify answers with a bare array of booleans, positionally matched to the
    URIs that were asked about. music-deck hands back the pairing rather than the
    array: a list of ``true``/``false`` that the caller has to re-align by index
    is a bug waiting for the first duplicate.
    """
    uris = _uris(items, "contains")
    answer = _client(client).get(CONTAINS, uris=uris)

    if not isinstance(answer, list) or len(answer) != len(uris):
        raise MusicDeckError(
            "spotify_error",
            "Spotify's saved-items answer did not line up with what was asked: "
            f"{len(uris)} item(s) went out, {len(answer) if isinstance(answer, list) else 'a non-list'} came back.",
            "Run `music-deck check`, then try again.",
        )

    return {
        "requested": len(uris),
        "contains": {uri: bool(value) for uri, value in zip(uris, answer)},
        "items": [
            {**reference, "saved": bool(value)}
            for reference, value in zip(_refs(uris), answer)
        ],
    }


def following(
    *, limit: int = 20, client: SpotifyClient | None = None
) -> dict[str, Any]:
    """The artists the account follows -- ``GET /me/following``.

    This endpoint is cursor-paged rather than offset-paged: each page hands back
    ``cursors.after``, which is where the next one starts. That is why it does
    not go through ``SpotifyClient.paginate`` (which walks ``offset``) -- an
    offset here would silently return the same first page over and over.
    """
    api = _client(client)
    collected: list[Any] = []
    after: str | None = None

    while len(collected) < limit:
        want = min(DEFAULT_PAGE_CAP, limit - len(collected))
        params: dict[str, Any] = {"type": "artist", "limit": want}
        if after:
            params["after"] = after
        payload = api.get(FOLLOWING, **params)

        page = payload.get("artists") if isinstance(payload, dict) else None
        found = page.get("items") if isinstance(page, dict) else None
        if not isinstance(found, list) or not found:
            break
        collected.extend(found)

        cursors = page.get("cursors") if isinstance(page, dict) else None
        after = cursors.get("after") if isinstance(cursors, dict) else None
        if not after or len(found) < want:
            break

    return {
        "requested": limit,
        "returned": len(collected),
        "artists": collected[:limit],
    }


# --------------------------------------------------------------------------- #
# writes
# --------------------------------------------------------------------------- #
def library_save(
    items: Sequence[str], *, client: SpotifyClient | None = None
) -> dict[str, Any]:
    """Save (or follow) items -- ``PUT /me/library``, one request, any types.

    ``uris`` goes in the query string. A JSON body is not read: see this
    module's "Where the URIs travel" table for the four live requests that
    settle it.
    """
    uris = _uris(items, "save")
    _client(client).put(LIBRARY, uris=uris)
    return {"saved": len(uris), "items": _refs(uris)}


def library_remove(
    items: Sequence[str], *, client: SpotifyClient | None = None
) -> dict[str, Any]:
    """Remove (or unfollow) items -- ``DELETE /me/library``.

    ``uris`` goes in the query string, for the same measured reason as
    :func:`library_save`. This is also the only way to remove a playlist the
    tool made: the follower endpoint that used to do it is gone.
    """
    uris = _uris(items, "remove")
    _client(client).delete(LIBRARY, uris=uris)
    return {"removed": len(uris), "items": _refs(uris)}
