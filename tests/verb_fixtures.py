"""Fixtures for the deterministic Spotify verbs: items, ids, and two assertions.

The item builders here are deliberately *shaped like Spotify's answers and no
more*: an id, a URI, a name, and the nested objects Spotify actually nests. They
carry no ``external_urls`` -- that is the point. ``cli.v1`` Core 4 says every
item music-deck emits carries its own link, and a fixture that supplied one
would prove nothing about whether music-deck does.

Two helpers do the checking that would otherwise be repeated in every test:

* :func:`spotify_items` walks an emitted document and finds every object that
  carries a Spotify URI, however deeply nested.
* :func:`assert_every_item_is_linked` asserts each of them carries the right
  ``external_urls.spotify``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from music_deck.http import API_BASE, link_for_uri

# Real-looking ids: 22 base62 characters, the shape Spotify issues.
TRACK_ID = "4iV5W9uYEdYUVa79Axb7Rh"
OTHER_TRACK_ID = "1301WleyT98MSxVHPZCA6M"
ALBUM_ID = "4aawyAB9vmqN3uQ7FjRGTy"
ARTIST_ID = "0TnOYISbd1XYRBk9myaseg"
PLAYLIST_ID = "37i9dQZF1DXcBWIGoYBM5M"
SHOW_ID = "38bS44xjbVVZ3No3ByF1dJ"
EPISODE_ID = "512ojhOuo1ktJprKbVcKyQ"
DEVICE_ID = "5fbb3ba6aa454b5534c4ba43a8c7e8e45a63ad0e"


# --------------------------------------------------------------------------- #
# Items, in Spotify's own shape -- and without external_urls, on purpose
# --------------------------------------------------------------------------- #
def artist_item(ident: str = ARTIST_ID, name: str = "Aphex Twin") -> dict[str, Any]:
    return {"id": ident, "uri": f"spotify:artist:{ident}", "name": name, "type": "artist"}


def album_item(ident: str = ALBUM_ID, name: str = "Selected Ambient Works") -> dict[str, Any]:
    return {
        "id": ident,
        "uri": f"spotify:album:{ident}",
        "name": name,
        "type": "album",
        "artists": [artist_item()],
    }


def track_item(ident: str = TRACK_ID, name: str = "Xtal") -> dict[str, Any]:
    return {
        "id": ident,
        "uri": f"spotify:track:{ident}",
        "name": name,
        "type": "track",
        "duration_ms": 293_000,
        "album": album_item(),
        "artists": [artist_item()],
    }


def playlist_item(ident: str = PLAYLIST_ID, name: str = "Late night") -> dict[str, Any]:
    return {
        "id": ident,
        "uri": f"spotify:playlist:{ident}",
        "name": name,
        "type": "playlist",
        "public": False,
        "tracks": {"total": 2},
    }


def show_item(ident: str = SHOW_ID, name: str = "A show") -> dict[str, Any]:
    return {"id": ident, "uri": f"spotify:show:{ident}", "name": name, "type": "show"}


def episode_item(ident: str = EPISODE_ID, name: str = "An episode") -> dict[str, Any]:
    return {
        "id": ident,
        "uri": f"spotify:episode:{ident}",
        "name": name,
        "type": "episode",
        "show": show_item(),
    }


def device_item(ident: str = DEVICE_ID, active: bool = True) -> dict[str, Any]:
    """A Connect device. Note it has no ``uri`` -- devices are not Spotify items."""
    return {
        "id": ident,
        "is_active": active,
        "name": "Kitchen speaker",
        "type": "Speaker",
        "supports_volume": True,
        "volume_percent": 35,
    }


def saved(item: dict[str, Any], key: str = "track") -> dict[str, Any]:
    """A library or playlist entry: the item, wrapped with when it was added."""
    return {"added_at": "2026-02-01T00:00:00Z", key: item}


def page(items: list[Any], **extra: Any) -> dict[str, Any]:
    """A Spotify paging object carrying ``items``."""
    return {"items": items, "limit": len(items), "offset": 0, **extra}


def search_page(items: list[Any], kind: str = "track") -> dict[str, Any]:
    """Search nests one paging object per requested type: ``{"tracks": {...}}``."""
    return {f"{kind}s": page(items)}


# --------------------------------------------------------------------------- #
# Reading what the tool sent
# --------------------------------------------------------------------------- #
def path_of(url: str) -> str:
    """The API path of a request URL, without the query string."""
    assert url.startswith(API_BASE), url
    return url[len(API_BASE) :].split("?", 1)[0]


def query_of(url: str) -> dict[str, str]:
    from urllib.parse import parse_qsl, urlsplit

    return dict(parse_qsl(urlsplit(url).query))


def sent(transport) -> list[tuple[str, str]]:
    """``[(method, path), ...]`` for everything the tool actually sent."""
    return [(request.method, path_of(request.url)) for request in transport.requests]


def body_of(request) -> Any:
    return json.loads(request.body.decode("utf-8")) if request.body else None


# --------------------------------------------------------------------------- #
# cli.v1 Core 4 -- every emitted Spotify item carries its own link
# --------------------------------------------------------------------------- #
def spotify_items(document: Any) -> Iterator[dict[str, Any]]:
    """Every object anywhere in ``document`` that carries a Spotify URI."""
    stack: list[Any] = [document]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            uri = node.get("uri")
            if isinstance(uri, str) and link_for_uri(uri):
                yield node
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)


def assert_every_item_is_linked(document: Any, *, at_least: int = 0) -> int:
    """Assert Core 4 over a whole emitted document; return how many items it held.

    ``at_least`` guards against the assertion passing vacuously: a document with
    no items in it satisfies "every item carries a link" trivially, which is not
    the thing worth proving.
    """
    counted = 0
    for item in spotify_items(document):
        counted += 1
        external = item.get("external_urls")
        assert isinstance(external, dict), (
            f"{item.get('uri')} was emitted with no external_urls at all: {item}"
        )
        assert external.get("spotify") == link_for_uri(item["uri"]), (
            f"{item.get('uri')} carries {external.get('spotify')!r}, expected "
            f"{link_for_uri(item['uri'])!r}"
        )
    assert counted >= at_least, (
        f"expected at least {at_least} Spotify item(s) in the document, found "
        f"{counted}: {document}"
    )
    return counted


# --------------------------------------------------------------------------- #
# boundary.v1 Core 8 -- no persistent store of Spotify content
# --------------------------------------------------------------------------- #
ALLOWED_STATE_FILES = {"token.json"}
"""The only thing a verb may leave behind. ``boundary.v1`` Core 8: "The only
things that persist are the token, the config file, and plan/transcript
artifacts." The config file lives in the config directory, not this one."""


def state_files(state: Path) -> set[str]:
    return {path.name for path in state.rglob("*") if path.is_file()}
