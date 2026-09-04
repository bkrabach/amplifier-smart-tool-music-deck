"""`playlists` and the six `playlist` sub-verbs.

Contracts under test: ``cli.v1`` Core 4 (one document; linked items), Core 6
(``playlist_items_unavailable``; ``partial_result`` with a ``completeness``
block), ``boundary.v1`` Core 7 (``/playlists/{id}/items`` and
``POST /me/playlists``, and nothing withdrawn).
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
    PLAYLIST_ID,
    TRACK_ID,
    body_of,
    page,
    path_of,
    playlist_item,
    query_of,
    saved,
    sent,
    state_files,
    track_item,
)

from music_deck.errors import EXIT_REFUSAL, EXIT_SUCCESS, ErrorCode
from music_deck.verbs.playlists import ITEMS_PER_REQUEST


@pytest.fixture
def signed_in(monkeypatch, tmp_path):
    install_token(monkeypatch, tmp_path, token_document())
    return tmp_path


def _uris(count: int) -> list[str]:
    """``count`` distinct, valid-looking track URIs."""
    return [f"spotify:track:{index:022d}" for index in range(count)]


# --------------------------------------------------------------------------- #
# The 100-per-request cap
# --------------------------------------------------------------------------- #
def test_adding_250_tracks_sends_three_requests_of_at_most_a_hundred(
    signed_in, monkeypatch, capsys
):
    """The acceptance criterion, verbatim: 250 URIs -> 3 requests of <= 100."""
    uris = _uris(250)
    transport = use_fake_transport(
        monkeypatch,
        FakeTransport([json_response(200, {"snapshot_id": f"snap-{n}"}) for n in range(3)]),
    )

    code, document, _ = run_cli(capsys, "playlist", "add", PLAYLIST_ID, *uris)

    assert code == EXIT_SUCCESS
    assert document["added"] == 250
    assert document["requests_sent"] == 3

    assert sent(transport) == [("POST", f"/playlists/{PLAYLIST_ID}/items")] * 3
    batches = [body_of(request)["uris"] for request in transport.requests]
    assert [len(batch) for batch in batches] == [100, 100, 50]
    assert max(len(batch) for batch in batches) <= ITEMS_PER_REQUEST
    assert [uri for batch in batches for uri in batch] == uris, "order must survive"
    assert document["snapshot_id"] == "snap-2", "the last snapshot is the current one"


def test_removing_250_tracks_batches_the_same_way_with_the_renamed_parameter(
    signed_in, monkeypatch, capsys
):
    """February 2026 renamed the removal body's parameter from `tracks` to `items`."""
    uris = _uris(250)
    transport = use_fake_transport(
        monkeypatch,
        FakeTransport([json_response(200, {"snapshot_id": f"snap-{n}"}) for n in range(3)]),
    )

    code, document, _ = run_cli(capsys, "playlist", "remove", PLAYLIST_ID, *uris)

    assert code == EXIT_SUCCESS
    assert document["removed"] == 250
    assert sent(transport) == [("DELETE", f"/playlists/{PLAYLIST_ID}/items")] * 3

    bodies = [body_of(request) for request in transport.requests]
    assert [len(body["items"]) for body in bodies] == [100, 100, 50]
    assert bodies[0]["items"][0] == {"uri": uris[0]}
    assert all("tracks" not in body for body in bodies)


def test_a_single_track_is_one_request_not_a_batch_endpoint(signed_in, monkeypatch, capsys):
    transport = use_fake_transport(
        monkeypatch, FakeTransport([json_response(200, {"snapshot_id": "snap"})])
    )

    code, _document, _ = run_cli(capsys, "playlist", "add", PLAYLIST_ID, TRACK_ID)

    assert code == EXIT_SUCCESS
    assert sent(transport) == [("POST", f"/playlists/{PLAYLIST_ID}/items")]
    assert body_of(transport.requests[0]) == {"uris": [f"spotify:track:{TRACK_ID}"]}


def test_the_same_track_twice_is_added_once_and_the_count_says_so(
    signed_in, monkeypatch, capsys
):
    transport = use_fake_transport(
        monkeypatch, FakeTransport([json_response(200, {"snapshot_id": "snap"})])
    )

    code, document, _ = run_cli(capsys, "playlist", "add", PLAYLIST_ID, TRACK_ID, TRACK_ID)

    assert code == EXIT_SUCCESS
    assert document["added"] == 1
    assert body_of(transport.requests[0])["uris"] == [f"spotify:track:{TRACK_ID}"]


# --------------------------------------------------------------------------- #
# cli.v1 Core 6 -- partial_result, never a silently truncated success
# --------------------------------------------------------------------------- #
def test_a_batched_write_that_gets_part_way_refuses_partial_result(
    signed_in, monkeypatch, capsys
):
    """Two hundred tracks are already in the playlist. Saying "done" would lie."""
    transport = use_fake_transport(
        monkeypatch,
        FakeTransport(
            [
                json_response(200, {"snapshot_id": "snap-0"}),
                json_response(200, {"snapshot_id": "snap-1"}),
                json_response(
                    429,
                    spotify_error(429, "quota exhausted", reason="QUOTA_EXCEEDED"),
                ),
            ]
        ),
    )

    code, document, _ = run_cli(capsys, "playlist", "add", PLAYLIST_ID, *_uris(250))

    assert code == EXIT_REFUSAL
    error = document["error"]
    assert error["code"] == ErrorCode.PARTIAL_RESULT
    assert error["completeness"] == {
        "requested": 250,
        "succeeded": 200,
        "failed": 50,
        "requests_sent": 2,
        "underlying_code": "quota_exceeded",
    }
    assert error["playlist"]["external_urls"]["spotify"].endswith(f"/playlist/{PLAYLIST_ID}")
    assert len(transport.requests) == 3, "it stops at the failure, it does not carry on"


def test_a_write_that_fails_on_its_first_request_reports_the_real_refusal(
    signed_in, monkeypatch, capsys
):
    """Nothing landed, so `partial_result` would be the wrong word for it."""
    use_fake_transport(
        monkeypatch,
        FakeTransport(
            [json_response(429, spotify_error(429, "quota", reason="QUOTA_EXCEEDED"))]
        ),
    )

    code, document, _ = run_cli(capsys, "playlist", "add", PLAYLIST_ID, *_uris(150))

    assert code == EXIT_REFUSAL
    assert document["error"]["code"] == ErrorCode.QUOTA_EXCEEDED


# --------------------------------------------------------------------------- #
# cli.v1 Core 6 -- playlist_items_unavailable
# --------------------------------------------------------------------------- #
def test_items_of_a_playlist_the_caller_does_not_own_refuse_by_name(
    signed_in, monkeypatch, capsys
):
    """The acceptance criterion: a mocked 403 becomes playlist_items_unavailable."""
    transport = use_fake_transport(
        monkeypatch,
        FakeTransport(
            [
                json_response(
                    403,
                    spotify_error(403, "You cannot view this playlist's items."),
                )
            ]
        ),
    )

    code, document, _ = run_cli(capsys, "playlist", "items", PLAYLIST_ID)

    assert code == EXIT_REFUSAL
    assert document["error"]["code"] == ErrorCode.PLAYLIST_ITEMS_UNAVAILABLE
    assert document["error"]["remedy"].strip()
    assert sent(transport) == [("GET", f"/playlists/{PLAYLIST_ID}/items")]
    assert state_files(signed_in / "state") == {"token.json"}, (
        "a refusal is not a reason to write Spotify content to disk"
    )


def test_playlist_items_pages_and_reports_what_it_got(signed_in, monkeypatch, capsys):
    transport = use_fake_transport(
        monkeypatch,
        FakeTransport([json_response(200, page([saved(track_item())] * 2))]),
    )

    code, document, _ = run_cli(capsys, "playlist", "items", PLAYLIST_ID, "--limit", "5")

    assert code == EXIT_SUCCESS
    assert document["requested"] == 5
    assert document["returned"] == 2
    assert document["playlist"]["uri"] == f"spotify:playlist:{PLAYLIST_ID}"
    assert int(query_of(transport.requests[0].url)["limit"]) == 5


# --------------------------------------------------------------------------- #
# The other writes -- what goes on the wire
# --------------------------------------------------------------------------- #
def test_creating_a_playlist_is_private_unless_asked_otherwise(
    signed_in, monkeypatch, capsys
):
    transport = use_fake_transport(
        monkeypatch, FakeTransport([json_response(200, playlist_item())])
    )

    code, document, _ = run_cli(capsys, "playlist", "create", "Late night")

    assert code == EXIT_SUCCESS
    assert sent(transport) == [("POST", "/me/playlists")]
    assert body_of(transport.requests[0]) == {"name": "Late night", "public": False}
    assert document["external_urls"]["spotify"].endswith(f"/playlist/{PLAYLIST_ID}")


def test_creating_a_public_playlist_says_so_and_carries_the_description(
    signed_in, monkeypatch, capsys
):
    transport = use_fake_transport(
        monkeypatch, FakeTransport([json_response(200, playlist_item())])
    )

    code, _document, _ = run_cli(
        capsys, "playlist", "create", "Loud", "--public", "--description", "for the car"
    )

    assert code == EXIT_SUCCESS
    assert body_of(transport.requests[0]) == {
        "name": "Loud",
        "public": True,
        "description": "for the car",
    }


def test_reordering_sends_spotify_s_own_three_fields(signed_in, monkeypatch, capsys):
    transport = use_fake_transport(
        monkeypatch, FakeTransport([json_response(200, {"snapshot_id": "snap"})])
    )

    code, document, _ = run_cli(
        capsys,
        "playlist",
        "reorder",
        PLAYLIST_ID,
        "--range-start",
        "5",
        "--insert-before",
        "0",
        "--range-length",
        "3",
    )

    assert code == EXIT_SUCCESS
    assert path_of(transport.requests[0].url) == f"/playlists/{PLAYLIST_ID}/items"
    assert body_of(transport.requests[0]) == {
        "range_start": 5,
        "insert_before": 0,
        "range_length": 3,
    }
    assert document["moved"] == 3


def test_a_negative_position_refuses_before_a_request(signed_in, monkeypatch, capsys):
    transport = use_fake_transport(monkeypatch, FakeTransport())

    code, document, _ = run_cli(
        capsys,
        "playlist",
        "reorder",
        PLAYLIST_ID,
        "--range-start",
        "-1",
        "--insert-before",
        "0",
    )

    assert code == EXIT_REFUSAL
    assert document["error"]["code"] == ErrorCode.USAGE
    assert transport.requests == []


def test_renaming_puts_the_new_name_on_the_playlist_itself(signed_in, monkeypatch, capsys):
    transport = use_fake_transport(monkeypatch, FakeTransport([json_response(200)]))

    code, document, _ = run_cli(capsys, "playlist", "rename", PLAYLIST_ID, "Later")

    assert code == EXIT_SUCCESS
    assert sent(transport) == [("PUT", f"/playlists/{PLAYLIST_ID}")]
    assert body_of(transport.requests[0]) == {"name": "Later"}
    assert document["playlist"]["external_urls"]["spotify"].endswith(
        f"/playlist/{PLAYLIST_ID}"
    )
