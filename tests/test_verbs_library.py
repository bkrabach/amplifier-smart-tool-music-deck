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
    spotify_error,
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
#
# Where the URIs travel is not a style choice, and it is the thing these tests
# exist to pin. ``/me/library`` reads ``uris`` from the **query string**; the
# same field in a JSON body is not read at all, and the endpoint answers
# ``400 {"error": {"status": 400, "message": "Missing required field: uris"}}``
# -- an error naming the field you did send. Measured live against
# api.spotify.com on 2026-09-06, both verbs, both shapes; see the table in
# ``music_deck.verbs.library``. Until then music-deck sent the body form and
# every write failed for the steward, while these tests passed: a fake that
# records a request without interpreting it will happily accept a shape the
# real endpoint refuses. Hence :func:`_library_endpoint` below, which refuses
# it the way Spotify does.
# --------------------------------------------------------------------------- #
def _library_endpoint(request):
    """``/me/library`` as measured: query ``uris`` or ``400``, never the body.

    Queued in place of a bare 200 so these tests fail the way the live endpoint
    failed, rather than passing on a request Spotify would have rejected.
    """
    if "uris" not in query_of(request.url):
        return json_response(
            400, spotify_error(400, "Missing required field: uris")
        )
    return json_response(200)


def test_saving_mixed_content_types_is_one_request_by_uri(signed_in, monkeypatch, capsys):
    transport = use_fake_transport(monkeypatch, FakeTransport([_library_endpoint]))

    code, document, _ = run_cli(
        capsys, "library", "save", TRACK_URI, ALBUM_URI, ARTIST_URI
    )

    assert code == EXIT_SUCCESS
    assert sent(transport) == [("PUT", "/me/library")]
    # Comma-separated, in the order given: the multi-value form this endpoint
    # takes, and the one `library contains` was already using.
    assert query_of(transport.requests[0].url) == {
        "uris": f"{TRACK_URI},{ALBUM_URI},{ARTIST_URI}"
    }
    assert body_of(transport.requests[0]) is None
    assert document["saved"] == 3
    assert_every_item_is_linked(document, at_least=3)


def test_removing_uses_the_same_endpoint_with_delete(signed_in, monkeypatch, capsys):
    transport = use_fake_transport(monkeypatch, FakeTransport([_library_endpoint]))

    code, document, _ = run_cli(capsys, "library", "remove", ARTIST_URI)

    assert code == EXIT_SUCCESS
    assert sent(transport) == [("DELETE", "/me/library")]
    assert query_of(transport.requests[0].url) == {"uris": ARTIST_URI}
    assert body_of(transport.requests[0]) is None
    assert document["removed"] == 1


def test_removing_a_playlist_is_the_only_way_a_created_playlist_comes_back_off(
    signed_in, monkeypatch, capsys
):
    """``boundary.v1`` Core 7: the follower endpoint is gone; this replaced it.

    ``apply`` can make a playlist, and ``DELETE /playlists/{id}/followers`` --
    the call that used to remove one -- was withdrawn in February 2026 and is
    refused by ``http.py``'s guard. So this request is the whole of the tool's
    ability to undo a playlist it created, which is why the shape of it matters
    more here than anywhere else in the file.
    """
    playlist_uri = "spotify:playlist:0000000000000000000000"
    transport = use_fake_transport(monkeypatch, FakeTransport([_library_endpoint]))

    code, document, _ = run_cli(capsys, "library", "remove", playlist_uri)

    assert code == EXIT_SUCCESS
    assert sent(transport) == [("DELETE", "/me/library")]
    assert query_of(transport.requests[0].url) == {"uris": playlist_uri}
    assert document["removed"] == 1
    with pytest.raises(RemovedEndpointError):
        check_removed("DELETE", "/playlists/0000000000000000000000/followers")


def test_the_body_shape_this_endpoint_refuses_is_refused_here_too(
    signed_in, monkeypatch, capsys
):
    """The regression guard: a body-only write must surface as the live 400.

    Not a test of music-deck's code path -- a test of the *fake*, so that the
    two tests above cannot start passing again by accident if the request drifts
    back into a JSON body. Without this, ``_library_endpoint`` is an assertion
    nobody has ever seen fail.
    """
    request = type(
        "Request", (), {"url": "https://api.spotify.com/v1/me/library"}
    )()

    refused = _library_endpoint(request)

    assert refused.status == 400
    assert refused.json()["error"]["message"] == "Missing required field: uris"


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
    transport = use_fake_transport(monkeypatch, FakeTransport([_library_endpoint]))

    code, _document, _ = run_cli(
        capsys, "library", "save", f"https://open.spotify.com/album/{ALBUM_ID}"
    )

    assert code == EXIT_SUCCESS
    assert query_of(transport.requests[0].url) == {"uris": ALBUM_URI}


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
