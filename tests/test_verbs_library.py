"""`library list|save|remove|contains` and `following`.

Contracts under test: ``boundary.v1`` Core 7 -- after February 2026 there is one
write endpoint for every content type (``/me/library``, by URI) and one
membership endpoint (``/me/library/contains``, by URI). The type-specific writes
and the type-specific ``contains`` endpoints are withdrawn; the type-specific
*reads* are not, and are the only way to enumerate what is saved.
"""

from __future__ import annotations

import pytest
from spotify_fakes import (
    FakeTransport,
    install_token,
    json_response,
    run_cli,
    token_document,
    use_fake_transport,
)
from verb_fixtures import (
    ALBUM_ID,
    ARTIST_ID,
    TRACK_ID,
    artist_item,
    assert_every_item_is_linked,
    body_of,
    page,
    query_of,
    saved,
    sent,
    track_item,
)

from music_deck.errors import EXIT_REFUSAL, EXIT_SUCCESS, ErrorCode
from music_deck.http import RemovedEndpointError, check_removed

TRACK_URI = f"spotify:track:{TRACK_ID}"
ALBUM_URI = f"spotify:album:{ALBUM_ID}"
ARTIST_URI = f"spotify:artist:{ARTIST_ID}"


@pytest.fixture
def signed_in(monkeypatch, tmp_path):
    install_token(monkeypatch, tmp_path, token_document())
    return tmp_path


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "kind", ["tracks", "albums", "shows", "episodes", "audiobooks"]
)
def test_listing_a_saved_content_type_uses_its_surviving_read(
    signed_in, monkeypatch, capsys, kind
):
    transport = use_fake_transport(
        monkeypatch, FakeTransport([json_response(200, page([saved(track_item())]))])
    )

    code, document, _ = run_cli(capsys, "library", "list", "--type", kind)

    assert code == EXIT_SUCCESS
    assert sent(transport) == [("GET", f"/me/{kind}")]
    assert document["type"] == kind
    check_removed("GET", f"/me/{kind}")  # the read survived; the write did not


def test_an_unknown_library_type_refuses_before_a_request(signed_in, monkeypatch, capsys):
    transport = use_fake_transport(monkeypatch, FakeTransport())

    code, document, _ = run_cli(capsys, "library", "list", "--type", "playlists")

    assert code == EXIT_REFUSAL
    assert document["error"]["code"] == ErrorCode.USAGE
    assert transport.requests == []


def test_asking_whether_items_are_saved_pairs_each_answer_with_its_uri(
    signed_in, monkeypatch, capsys
):
    """Spotify answers a bare ``[true, false]``; realigning it by index is the bug."""
    transport = use_fake_transport(
        monkeypatch, FakeTransport([json_response(200, [True, False])])
    )

    code, document, _ = run_cli(capsys, "library", "contains", TRACK_URI, ALBUM_URI)

    assert code == EXIT_SUCCESS
    assert sent(transport) == [("GET", "/me/library/contains")]
    assert query_of(transport.requests[0].url)["uris"] == f"{TRACK_URI},{ALBUM_URI}"
    assert document["contains"] == {TRACK_URI: True, ALBUM_URI: False}
    assert [item["saved"] for item in document["items"]] == [True, False]
    assert_every_item_is_linked(document, at_least=2)


def test_an_answer_that_does_not_line_up_is_a_loud_failure(signed_in, monkeypatch, capsys):
    """Two questions and one answer cannot be paired; guessing would be worse."""
    use_fake_transport(monkeypatch, FakeTransport([json_response(200, [True])]))

    code, document, _ = run_cli(capsys, "library", "contains", TRACK_URI, ALBUM_URI)

    assert code != EXIT_SUCCESS
    assert document["error"]["code"] == "spotify_error"


def test_following_walks_the_after_cursor_rather_than_an_offset(
    signed_in, monkeypatch, capsys
):
    """``/me/following`` is cursor-paged: an offset would re-fetch page one forever."""
    first = {
        "artists": page(
            [artist_item(f"{index:022d}", f"artist {index}") for index in range(50)],
            cursors={"after": "cursor-50"},
        )
    }
    second = {
        "artists": page(
            [artist_item(f"{50 + index:022d}", f"artist {50 + index}") for index in range(10)],
            cursors={"after": None},
        )
    }
    transport = use_fake_transport(
        monkeypatch,
        FakeTransport([json_response(200, first), json_response(200, second)]),
    )

    code, document, _ = run_cli(capsys, "following", "--limit", "60")

    assert code == EXIT_SUCCESS
    assert document["returned"] == 60
    queries = [query_of(request.url) for request in transport.requests]
    assert [query.get("after") for query in queries] == [None, "cursor-50"]
    assert all(query["type"] == "artist" for query in queries)
    assert all("offset" not in query for query in queries)


# --------------------------------------------------------------------------- #
# Writes -- one endpoint, every content type, by URI
# --------------------------------------------------------------------------- #
def test_saving_mixed_content_types_is_one_request_by_uri(signed_in, monkeypatch, capsys):
    transport = use_fake_transport(monkeypatch, FakeTransport([json_response(200)]))

    code, document, _ = run_cli(
        capsys, "library", "save", TRACK_URI, ALBUM_URI, ARTIST_URI
    )

    assert code == EXIT_SUCCESS
    assert sent(transport) == [("PUT", "/me/library")]
    assert body_of(transport.requests[0]) == {"uris": [TRACK_URI, ALBUM_URI, ARTIST_URI]}
    assert document["saved"] == 3
    assert_every_item_is_linked(document, at_least=3)


def test_removing_uses_the_same_endpoint_with_delete(signed_in, monkeypatch, capsys):
    transport = use_fake_transport(monkeypatch, FakeTransport([json_response(200)]))

    code, document, _ = run_cli(capsys, "library", "remove", ARTIST_URI)

    assert code == EXIT_SUCCESS
    assert sent(transport) == [("DELETE", "/me/library")]
    assert body_of(transport.requests[0]) == {"uris": [ARTIST_URI]}
    assert document["removed"] == 1


def test_a_bare_id_is_refused_because_it_does_not_say_what_it_is(
    signed_in, monkeypatch, capsys
):
    """One endpoint for every type means the URI is the only thing naming the type."""
    transport = use_fake_transport(monkeypatch, FakeTransport())

    code, document, _ = run_cli(capsys, "library", "save", TRACK_ID)

    assert code == EXIT_REFUSAL
    assert document["error"]["code"] == ErrorCode.USAGE
    assert "spotify:track" in document["error"]["remedy"]
    assert transport.requests == []


def test_an_open_spotify_link_is_accepted_where_a_uri_is(signed_in, monkeypatch, capsys):
    transport = use_fake_transport(monkeypatch, FakeTransport([json_response(200)]))

    code, _document, _ = run_cli(
        capsys, "library", "save", f"https://open.spotify.com/album/{ALBUM_ID}"
    )

    assert code == EXIT_SUCCESS
    assert body_of(transport.requests[0]) == {"uris": [ALBUM_URI]}


# --------------------------------------------------------------------------- #
# boundary.v1 Core 7, from the other side
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "method,path",
    [
        ("PUT", "/me/tracks"),
        ("DELETE", "/me/albums"),
        ("PUT", "/me/following"),
        ("GET", "/me/tracks/contains"),
        ("GET", "/me/following/contains"),
    ],
)
def test_the_endpoints_this_lane_deliberately_does_not_use_are_still_refused(
    method, path
):
    """The withdrawn library surface. If a future edit reaches for one of these,
    the guard raises before a socket -- this asserts the guard still covers them.
    """
    with pytest.raises(RemovedEndpointError):
        check_removed(method, path)
