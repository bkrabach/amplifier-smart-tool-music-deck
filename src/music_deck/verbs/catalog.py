"""`search`, `track`, `album`, `artist`, `show`, `episode` -- reading the catalogue.

Contracts served
----------------
* ``cli.v1`` Core 2 -- these six are deterministic verbs: no model, no provider
  SDK, nothing here imports one.
* ``cli.v1`` Core 4 -- each returns exactly one JSON document, and every Spotify
  item in it carries its own ``external_urls.spotify`` (surfaced by
  ``http.surface_links`` on the way out of the client).
* ``boundary.v1`` Core 7 -- **single-item GETs only**. Spotify withdrew the batch
  fetch endpoints in February 2026, so a lookup of five tracks is five requests,
  not one. This module never builds a path from a *family* alone: every path it
  constructs is ``/<family>/<id>`` with an id the caller supplied, which is what
  makes "we never call the batch endpoint" structural rather than a promise.

Where the identity helpers live
-------------------------------
:func:`to_id`, :func:`to_uri` and :func:`item_ref` are here rather than in a
module of their own because catalogue identity *is* what they are about, and
every other verb module in this lane needs them: a playlist is added to with
track URIs, the library is saved to with URIs, playback starts from a URI.

Search paging
-------------
February 2026 cut search's ``limit`` from 50 to 10 per request (default 5). A
caller asking for 25 results is therefore not an error and not a truncation --
it is three requests, walked by ``SpotifyClient.paginate``, which knows the cap
belongs to ``/search`` alone. The result document reports ``requested`` beside
``returned`` so a short answer is visible rather than silent.
"""

from __future__ import annotations

import re
from typing import Any, Final, Iterable, Sequence

from music_deck.errors import ErrorCode, MusicDeckError
from music_deck.http import SEARCH_PAGE_CAP, SpotifyClient, link_for_uri
from music_deck.verbs.auth_verbs import spotify_client

SEARCH_KINDS: Final[tuple[str, ...]] = ("track", "album", "artist", "show", "episode")
"""What ``music-deck search --type`` accepts, per ``cli.v1``'s verb listing."""

_FAMILY: Final[dict[str, str]] = {
    "track": "tracks",
    "album": "albums",
    "artist": "artists",
    "show": "shows",
    "episode": "episodes",
    "playlist": "playlists",
    "audiobook": "audiobooks",
    "chapter": "chapters",
}
"""Singular kind -> the path segment its *single-item* endpoint lives under.

Only ever used as ``/<family>/<id>``. There is no code path in music-deck that
turns one of these into a bare ``/<family>`` request, which is the withdrawn
batch endpoint.
"""

_BARE_ID = re.compile(r"^[0-9A-Za-z]+$")
"""A Spotify id as it appears in a URI or a URL.

Deliberately not length-checked: Spotify decides what one of its ids looks like,
and a client-side rule invented here would refuse a valid id the day that
changes. What music-deck *does* enforce is that an id carries no ``:`` and no
``/`` -- so a URI can never be silently pasted into an id slot, or the reverse.
"""

_URL_HOSTS: Final = ("open.spotify.com", "play.spotify.com")


def _usage(message: str, remedy: str) -> MusicDeckError:
    return MusicDeckError(ErrorCode.USAGE, message, remedy)


def split_reference(value: str) -> tuple[str, str]:
    """``(kind, id)`` for a Spotify URI, an open.spotify.com URL, or raise.

    A bare id has no kind in it, so it cannot be answered here -- see
    :func:`to_id`, which takes the kind from the verb the caller invoked.
    """
    text = (value or "").strip()
    if not text:
        raise _usage(
            "An empty string is not a Spotify reference.",
            "Pass a Spotify id, a spotify:<kind>:<id> URI, or an "
            "open.spotify.com link.",
        )

    if text.startswith("spotify:"):
        parts = text.split(":")
        if len(parts) == 3 and parts[1] in _FAMILY and _BARE_ID.match(parts[2]):
            return parts[1], parts[2]
        raise _usage(
            f"{text!r} is not a Spotify URI music-deck understands.",
            "A Spotify URI looks like spotify:track:4iV5W9uYEdYUVa79Axb7Rh.",
        )

    if "://" in text or text.startswith("open.spotify.com"):
        without_scheme = text.split("://", 1)[-1]
        host, _, rest = without_scheme.partition("/")
        if host not in _URL_HOSTS:
            raise _usage(
                f"{text!r} is not an open.spotify.com link.",
                "Pass a link copied from Spotify, a spotify:<kind>:<id> URI, or "
                "a bare Spotify id.",
            )
        segments = [part for part in rest.split("?", 1)[0].split("/") if part]
        # A localised link carries the locale first: /intl-de/track/<id>.
        segments = [part for part in segments if not part.startswith("intl-")]
        if len(segments) >= 2 and segments[0] in _FAMILY and _BARE_ID.match(segments[1]):
            return segments[0], segments[1]
        raise _usage(
            f"{text!r} does not name a Spotify item music-deck understands.",
            "A Spotify link looks like https://open.spotify.com/track/"
            "4iV5W9uYEdYUVa79Axb7Rh.",
        )

    raise _usage(
        f"{text!r} carries no Spotify item kind.",
        "Pass a spotify:<kind>:<id> URI or an open.spotify.com link when the "
        "kind is not implied by the verb.",
    )


def to_id(value: str, kind: str) -> str:
    """The Spotify id in ``value``, which must be of ``kind``.

    Accepts the three forms a caller actually has to hand: the bare id, the
    ``spotify:<kind>:<id>`` URI, and the ``open.spotify.com`` link. A reference
    to the *wrong* kind is refused by name rather than sent to Spotify to fail
    there -- ``music-deck album spotify:track:...`` is a mistake worth catching
    before a request is spent on it.
    """
    text = (value or "").strip()
    if _BARE_ID.match(text):
        return text
    found_kind, found_id = split_reference(text)
    if found_kind != kind:
        raise _usage(
            f"{text!r} is a Spotify {found_kind}, but this verb takes a {kind}.",
            f"Pass a {kind} id, a spotify:{kind}:<id> URI, or the matching "
            f"open.spotify.com link.",
        )
    return found_id


def to_uri(value: str, kind: str) -> str:
    """``spotify:<kind>:<id>`` for any of the three reference forms."""
    return f"spotify:{kind}:{to_id(value, kind)}"


def to_any_uri(value: str) -> str:
    """``spotify:<kind>:<id>`` where the *caller* names the kind.

    Used where Spotify itself takes URIs of any type in one call -- ``PUT
    /me/library`` since February 2026, and starting playback from a list. A bare
    id is refused here on purpose: nothing in the request would say whether it
    is a track or an album, and guessing would save the caller one word at the
    cost of doing the wrong thing silently.
    """
    text = (value or "").strip()
    if _BARE_ID.match(text):
        raise _usage(
            f"{text!r} is a bare Spotify id, and this verb needs to know what "
            "kind of thing it is.",
            "Pass the full URI -- spotify:track:<id>, spotify:album:<id>, "
            "spotify:show:<id> -- or an open.spotify.com link.",
        )
    kind, ident = split_reference(text)
    return f"spotify:{kind}:{ident}"


def item_ref(kind: str, value: str) -> dict[str, Any]:
    """The smallest honest description of an item: its id, URI, and link.

    ``cli.v1`` Core 4 -- "Every Spotify item the tool emits carries its own
    ``external_urls.spotify`` link" -- has to hold for the write verbs too, and
    a write's response from Spotify is a ``snapshot_id`` or nothing at all. So
    the verbs that emit *what they just acted on* emit it in this shape, built
    from the reference the caller themselves passed in. No request is needed for
    it and no Spotify content is in it.
    """
    ident = to_id(value, kind)
    uri = f"spotify:{kind}:{ident}"
    link = link_for_uri(uri)
    reference: dict[str, Any] = {"id": ident, "uri": uri}
    if link:
        reference["external_urls"] = {"spotify": link}
    return reference


def uri_ref(uri: str) -> dict[str, Any]:
    """:func:`item_ref` for an already-resolved ``spotify:<kind>:<id>`` URI."""
    kind, ident = split_reference(uri)
    return item_ref(kind, ident)


def _client(client: SpotifyClient | None) -> SpotifyClient:
    return client if client is not None else spotify_client()


def _positive(limit: int, what: str) -> int:
    if limit < 1:
        raise _usage(
            f"--limit must be at least 1; got {limit}.",
            f"Ask for one or more {what}.",
        )
    return limit


# --------------------------------------------------------------------------- #
# search
# --------------------------------------------------------------------------- #
def search(
    query: str,
    *,
    kind: str = "track",
    limit: int = SEARCH_PAGE_CAP,
    client: SpotifyClient | None = None,
) -> dict[str, Any]:
    """Search the catalogue -- ``GET /search``, paged at Spotify's 10-per-request cap.

    ``requested`` and ``returned`` are both reported: Spotify runs out of matches
    long before most callers run out of appetite, and a list that is shorter than
    asked for should say so rather than look complete.
    """
    if kind not in SEARCH_KINDS:
        raise _usage(
            f"--type {kind!r} is not something music-deck can search for.",
            f"Use one of: {', '.join(SEARCH_KINDS)}.",
        )
    text = (query or "").strip()
    if not text:
        raise _usage(
            "An empty query matches nothing.",
            'Pass what to search for, e.g. music-deck search "aphex twin".',
        )
    _positive(limit, "results")

    results = _client(client).paginate(
        "/search", limit=limit, params={"q": text, "type": kind}
    )
    return {
        "query": text,
        "type": kind,
        "requested": limit,
        "returned": len(results),
        "page_size": SEARCH_PAGE_CAP,
        "results": results,
    }


# --------------------------------------------------------------------------- #
# the single-item lookups
# --------------------------------------------------------------------------- #
def _one(kind: str, value: str, client: SpotifyClient | None) -> Any:
    family = _FAMILY[kind]
    ident = to_id(value, kind)
    return _client(client).get(f"/{family}/{ident}")


def track(value: str, *, client: SpotifyClient | None = None) -> Any:
    """One track -- ``GET /tracks/{id}``. Never the withdrawn batch endpoint."""
    return _one("track", value, client)


def album(value: str, *, client: SpotifyClient | None = None) -> Any:
    """One album -- ``GET /albums/{id}``."""
    return _one("album", value, client)


def artist(value: str, *, client: SpotifyClient | None = None) -> Any:
    """One artist -- ``GET /artists/{id}``."""
    return _one("artist", value, client)


def show(value: str, *, client: SpotifyClient | None = None) -> Any:
    """One podcast show -- ``GET /shows/{id}``."""
    return _one("show", value, client)


def episode(value: str, *, client: SpotifyClient | None = None) -> Any:
    """One podcast episode -- ``GET /episodes/{id}``."""
    return _one("episode", value, client)


# --------------------------------------------------------------------------- #
# shared by the other verb modules
# --------------------------------------------------------------------------- #
def batches(values: Sequence[Any], size: int) -> list[list[Any]]:
    """``values`` cut into runs of at most ``size``.

    Spotify caps playlist writes at 100 items per request, verbatim: "A maximum
    of 100 items can be added in one request." A caller with 250 URIs gets three
    requests -- not one refusal, and not a silent first hundred.
    """
    if size < 1:
        raise ValueError("batch size must be at least 1")
    return [list(values[start : start + size]) for start in range(0, len(values), size)]


def unique(values: Iterable[str]) -> list[str]:
    """``values`` with duplicates dropped, first occurrence order kept."""
    seen: set[str] = set()
    kept: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            kept.append(value)
    return kept
