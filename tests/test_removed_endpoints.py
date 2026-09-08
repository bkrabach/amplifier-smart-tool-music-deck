"""boundary.v1 Core 7: no removed endpoint is ever constructed.

The contract's own conformance section asks for both halves, and they catch
different mistakes:

* **Static** -- no withdrawn path literal appears anywhere in ``src/``. Catches
  code that would build such a URL from a constant, including in a branch no
  test happens to walk.
* **Runtime** -- the guard refuses each withdrawn family *before* a request is
  sent. Catches a path assembled at runtime from pieces, which no grep can see.

Neither is sufficient alone. A grep-only check is exactly the "not proven" shape
the work item names; a runtime-only check misses the literal nobody called yet.

Why the source scan can pass at all
-----------------------------------
``src/music_deck/http.py`` necessarily contains every withdrawn path -- it is the
table of things to refuse. That table is fenced between two marker comments, and
this file excises exactly that region before scanning. The fence is asserted to
exist, so deleting it breaks the test rather than silently disabling it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from spotify_fakes import FakeTransport, install_token, token_document, use_fake_transport

from music_deck.errors import EXIT_FAILURE, ErrorCode
from music_deck.http import REMOVED_ENDPOINTS, RemovedEndpointError, check_removed
from music_deck.verbs.auth_verbs import spotify_client

SRC = Path(__file__).resolve().parents[1] / "src"
TABLE_START = "# --- BEGIN REMOVED ENDPOINT TABLE"
TABLE_END = "# --- END REMOVED ENDPOINT TABLE"

# Each entry: (a regex that would spot the withdrawn path in source, what it is).
# The regexes are written to spot a *literal path*, not a mention in prose.
WITHDRAWN_LITERALS = [
    (r'["\']/tracks["\']', "batch GET /tracks"),
    (r'["\']/albums["\']', "batch GET /albums"),
    (r'["\']/artists["\']', "batch GET /artists"),
    (r'["\']/episodes["\']', "batch GET /episodes"),
    (r'["\']/shows["\']', "batch GET /shows"),
    (r'["\']/audiobooks["\']', "batch GET /audiobooks"),
    (r'["\']/chapters["\']', "batch GET /chapters"),
    (r"/users/", "/users/{id} and everything under it"),
    (r"/browse/", "/browse/*"),
    (r'["\']/markets', "/markets"),
    (r"/recommendations", "/recommendations"),
    (r"/audio-features", "/audio-features"),
    (r"/audio-analysis", "/audio-analysis"),
    (r"related-artists", "/artists/{id}/related-artists"),
    (r"top-tracks", "/artists/{id}/top-tracks"),
    (r"/playlists/[^\"']*/tracks", "/playlists/{id}/tracks"),
    (r"/playlists/[^\"']*/followers", "/playlists/{id}/followers"),
    (
        r"/me/(tracks|albums|episodes|shows|audiobooks|following)/contains",
        "type-specific /me/<type>/contains",
    ),
]


def _scannable_source() -> list[tuple[Path, str]]:
    """Every ``src`` file, with the removed-endpoint table excised."""
    files: list[tuple[Path, str]] = []
    fenced = 0
    for path in sorted(SRC.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if TABLE_START in text:
            fenced += 1
            before, rest = text.split(TABLE_START, 1)
            assert TABLE_END in rest, f"{path} opens the table fence but never closes it"
            after = rest.split(TABLE_END, 1)[1]
            text = before + after
        files.append((path, text))
    assert fenced == 1, (
        "exactly one file may carry the removed-endpoint table; found "
        f"{fenced}. If it moved, this test's fence markers must move with it."
    )
    return files


# --------------------------------------------------------------------------- #
# Static
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("pattern,what", WITHDRAWN_LITERALS, ids=[w for _, w in WITHDRAWN_LITERALS])
def test_no_withdrawn_path_literal_appears_in_src(pattern, what):
    offenders = [
        f"{path.relative_to(SRC)}:{text[:match.start()].count(chr(10)) + 1}"
        for path, text in _scannable_source()
        for match in [re.search(pattern, text)]
        if match
    ]
    assert not offenders, f"{what} appears as a literal in: {offenders}"


def test_the_source_scan_is_actually_looking_at_something():
    """A scan of an empty corpus passes vacuously; this is the tripwire."""
    files = _scannable_source()
    assert len(files) >= 6, files
    assert any("def check_removed" in text for _, text in files)


def test_no_client_secret_appears_anywhere_in_src():
    """boundary.v1 Core 4: "No client secret anywhere". PKCE has none to store."""
    offenders = [
        str(path.relative_to(SRC))
        for path, text in _scannable_source()
        if re.search(r"client_secret", text)
    ]
    assert not offenders, offenders


# --------------------------------------------------------------------------- #
# Runtime -- the guard refuses before a socket is opened
# --------------------------------------------------------------------------- #
WITHDRAWN_CALLS = [
    ("GET", "/tracks"),
    ("GET", "/albums"),
    ("GET", "/artists"),
    ("GET", "/episodes"),
    ("GET", "/shows"),
    ("GET", "/audiobooks"),
    ("GET", "/chapters"),
    ("GET", "/users/deckuser"),
    ("GET", "/users/deckuser/playlists"),
    ("POST", "/users/deckuser/playlists"),
    ("GET", "/browse/new-releases"),
    ("GET", "/browse/categories"),
    ("GET", "/browse/categories/party"),
    ("GET", "/markets"),
    ("GET", "/recommendations"),
    ("GET", "/audio-features/4iV5W9uYEdYUVa79Axb7Rh"),
    ("GET", "/audio-analysis/4iV5W9uYEdYUVa79Axb7Rh"),
    ("GET", "/artists/0TnOYISbd1XYRBk9myaseg/related-artists"),
    ("GET", "/artists/0TnOYISbd1XYRBk9myaseg/top-tracks"),
    ("GET", "/playlists/37i9dQZF1DXcBWIGoYBM5M/tracks"),
    ("POST", "/playlists/37i9dQZF1DXcBWIGoYBM5M/tracks"),
    ("PUT", "/playlists/37i9dQZF1DXcBWIGoYBM5M/tracks"),
    ("DELETE", "/playlists/37i9dQZF1DXcBWIGoYBM5M/tracks"),
    ("PUT", "/playlists/37i9dQZF1DXcBWIGoYBM5M/followers"),
    ("PUT", "/me/tracks"),
    ("DELETE", "/me/albums"),
    ("PUT", "/me/following"),
    ("GET", "/me/tracks/contains"),
    ("GET", "/me/following/contains"),
]


@pytest.mark.parametrize(
    "method,path", WITHDRAWN_CALLS, ids=[f"{m} {p}" for m, p in WITHDRAWN_CALLS]
)
def test_the_guard_refuses_a_withdrawn_endpoint_before_any_request(
    monkeypatch, tmp_path, method, path
):
    install_token(monkeypatch, tmp_path, token_document())
    transport = use_fake_transport(monkeypatch, FakeTransport())

    with pytest.raises(RemovedEndpointError) as raised:
        spotify_client().request(method, path)

    assert transport.requests == [], "the guard must run before the request is built"
    assert raised.value.code == ErrorCode.INTERNAL_ERROR
    assert raised.value.exit_code == EXIT_FAILURE
    assert raised.value.envelope()["error"]["code"] == ErrorCode.INTERNAL_ERROR
    assert raised.value.extra["diagnostic_code"] == "removed_endpoint"
    assert raised.value.extra["replacement"]
    assert raised.value.extra["withdrawn"] in {"November 2024", "February 2026"}


SURVIVING_CALLS = [
    ("GET", "/me"),
    ("GET", "/search"),
    ("GET", "/tracks/4iV5W9uYEdYUVa79Axb7Rh"),
    ("GET", "/albums/4aawyAB9vmqN3uQ7FjRGTy"),
    ("GET", "/artists/0TnOYISbd1XYRBk9myaseg"),
    ("GET", "/playlists/37i9dQZF1DXcBWIGoYBM5M/items"),
    ("POST", "/playlists/37i9dQZF1DXcBWIGoYBM5M/items"),
    ("DELETE", "/playlists/37i9dQZF1DXcBWIGoYBM5M/items"),
    ("POST", "/me/playlists"),
    ("GET", "/me/playlists"),
    ("PUT", "/me/library"),
    ("DELETE", "/me/library"),
    ("GET", "/me/library/contains"),
    ("GET", "/me/tracks"),  # the *read* survived; only the write and contains went
    ("GET", "/me/following"),
    ("GET", "/me/top/tracks"),
    ("GET", "/me/player"),
    ("PUT", "/me/player/play"),
]


@pytest.mark.parametrize(
    "method,path", SURVIVING_CALLS, ids=[f"{m} {p}" for m, p in SURVIVING_CALLS]
)
def test_the_guard_lets_the_surviving_surface_through(method, path):
    """The other half of a guard: it must not refuse what still works.

    boundary.v1 Core 7 names four of these explicitly -- `/playlists/{id}/items`,
    `/me/library`, `/me/library/contains`, `POST /me/playlists` -- which is
    exactly the set a too-eager pattern would swallow.
    """
    check_removed(method, path)  # raises if the guard is wrong


def test_every_entry_in_the_table_names_when_it_went_and_what_replaced_it():
    """A table row with no provenance is a rule nobody can check later."""
    for removed in REMOVED_ENDPOINTS:
        assert removed.name
        assert removed.withdrawn in {"November 2024", "February 2026"}
        assert removed.replacement


def test_a_removed_endpoint_keeps_only_redacted_registry_context():
    marker = "fixture-query-secret-must-not-escape"

    with pytest.raises(RemovedEndpointError) as raised:
        check_removed("GET", f"/tracks?access_token={marker}")

    error = raised.value
    envelope = error.envelope()["error"]
    assert envelope["code"] == ErrorCode.INTERNAL_ERROR
    assert envelope["method"] == "GET"
    assert envelope["path"] == "/tracks"
    assert envelope["withdrawn"] == "February 2026"
    assert envelope["replacement"] == "/tracks/{id}, one request per item"
    assert marker not in str(error)
    assert marker not in str(envelope)


def test_the_guard_covers_every_family_the_contract_lists():
    """boundary.v1 Core 7's <details> block, item by item."""
    families = {
        "batch GET /tracks": ("GET", "/tracks"),
        "batch GET /albums": ("GET", "/albums"),
        "batch GET /artists": ("GET", "/artists"),
        "/users/{id}*": ("GET", "/users/someone"),
        "/browse/*": ("GET", "/browse/new-releases"),
        "/markets": ("GET", "/markets"),
        "/recommendations": ("GET", "/recommendations"),
        "/audio-features": ("GET", "/audio-features/x"),
        "/audio-analysis": ("GET", "/audio-analysis/x"),
        "related-artists": ("GET", "/artists/x/related-artists"),
        "top-tracks": ("GET", "/artists/x/top-tracks"),
        "type-specific /me/<type> library": ("PUT", "/me/tracks"),
        "type-specific follow/contains": ("GET", "/me/following/contains"),
    }
    uncovered = []
    for label, (method, path) in families.items():
        try:
            check_removed(method, path)
        except RemovedEndpointError:
            continue
        uncovered.append(label)
    assert not uncovered, f"the guard does not cover: {uncovered}"
