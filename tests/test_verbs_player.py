"""The player verbs: reads, transport controls, `top`, `recently-played`.

Contracts under test: ``cli.v1`` Core 6 -- ``premium_required`` on a playback
write and ``no_active_device`` on a playback read with nothing playing, both
decided in ``http.py`` and provoked here through the real verbs; ``cli.v1``
Core 4 -- what a write returns is one document naming what it did, with the item
it acted on carrying its link, because Spotify answers a write with 204 and no
body at all.
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
    DEVICE_ID,
    EPISODE_ID,
    TRACK_ID,
    assert_every_item_is_linked,
    body_of,
    device_item,
    page,
    query_of,
    saved,
    sent,
    state_files,
    track_item,
)

from music_deck.errors import EXIT_REFUSAL, EXIT_SUCCESS, ErrorCode

TRACK_URI = f"spotify:track:{TRACK_ID}"
ALBUM_URI = f"spotify:album:{ALBUM_ID}"
EPISODE_URI = f"spotify:episode:{EPISODE_ID}"


@pytest.fixture
def signed_in(monkeypatch, tmp_path):
    install_token(monkeypatch, tmp_path, token_document())
    return tmp_path


# --------------------------------------------------------------------------- #
# cli.v1 Core 6 -- premium_required
# --------------------------------------------------------------------------- #
WRITES = [
    (["pause"], "PUT", "/me/player/pause"),
    (["play"], "PUT", "/me/player/play"),
    (["next"], "POST", "/me/player/next"),
    (["previous"], "POST", "/me/player/previous"),
    (["seek", "1000"], "PUT", "/me/player/seek"),
    (["volume", "10"], "PUT", "/me/player/volume"),
    (["shuffle", "off"], "PUT", "/me/player/shuffle"),
    (["repeat", "off"], "PUT", "/me/player/repeat"),
    (["transfer", DEVICE_ID], "PUT", "/me/player"),
    (["queue-add", TRACK_URI], "POST", "/me/player/queue"),
]


@pytest.mark.parametrize(
    "argv,method,path", WRITES, ids=[" ".join(argv) for argv, _, _ in WRITES]
)
def test_every_playback_write_refuses_premium_required_on_a_403(
    signed_in, monkeypatch, capsys, argv, method, path
):
    """February 2026 removed `product` from GET /me, so 403 is the only signal."""
    transport = use_fake_transport(
        monkeypatch,
        FakeTransport(
            [json_response(403, spotify_error(403, "Player command failed: Premium required"))]
        ),
    )

    code, document, _ = run_cli(capsys, *argv)

    assert code == EXIT_REFUSAL
    assert document["error"]["code"] == ErrorCode.PREMIUM_REQUIRED
    assert document["error"]["remedy"].strip()
    assert sent(transport) == [(method, path)]
    assert state_files(signed_in / "state") == {"token.json"}


# --------------------------------------------------------------------------- #
# cli.v1 Core 6 -- no_active_device
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "argv,path",
    [
        (["now-playing"], "/me/player"),
        (["queue"], "/me/player/queue"),
    ],
    ids=["now-playing", "queue"],
)
def test_a_playback_read_with_nothing_playing_refuses_no_active_device(
    signed_in, monkeypatch, capsys, argv, path
):
    """204 No Content means "nothing is active" -- not an empty success."""
    transport = use_fake_transport(monkeypatch, FakeTransport([json_response(204)]))

    code, document, _ = run_cli(capsys, *argv)

    assert code == EXIT_REFUSAL
    assert document["error"]["code"] == ErrorCode.NO_ACTIVE_DEVICE
    assert "transfer" in document["error"]["remedy"]
    assert sent(transport) == [("GET", path)]


def test_devices_answers_an_empty_list_rather_than_refusing(signed_in, monkeypatch, capsys):
    """No devices is a real answer, and the one to read before `transfer`."""
    use_fake_transport(monkeypatch, FakeTransport([json_response(200, {"devices": []})]))

    code, document, _ = run_cli(capsys, "devices")

    assert code == EXIT_SUCCESS
    assert document == {"devices": [], "count": 0, "active": None}


def test_devices_names_the_active_one(signed_in, monkeypatch, capsys):
    use_fake_transport(
        monkeypatch,
        FakeTransport(
            [
                json_response(
                    200,
                    {"devices": [device_item("aaa", active=False), device_item()]},
                )
            ]
        ),
    )

    code, document, _ = run_cli(capsys, "devices")

    assert code == EXIT_SUCCESS
    assert document["count"] == 2
    assert document["active"]["id"] == DEVICE_ID


# --------------------------------------------------------------------------- #
# What goes on the wire for a playback write
# --------------------------------------------------------------------------- #
def test_an_album_plays_as_a_context_and_a_track_plays_as_a_uri_list(
    signed_in, monkeypatch, capsys
):
    """Spotify takes a context_uri for an album/artist/playlist and `uris` for a
    track or episode. Sending the wrong one is a 400 discovered at Spotify."""
    transport = use_fake_transport(
        monkeypatch, FakeTransport([json_response(204), json_response(204)])
    )

    code, album_result, _ = run_cli(capsys, "play", "--uri", ALBUM_URI)
    assert code == EXIT_SUCCESS
    assert body_of(transport.requests[0]) == {"context_uri": ALBUM_URI}
    assert album_result["playing"]["kind"] == "album"

    code, track_result, _ = run_cli(capsys, "play", "--uri", TRACK_URI)
    assert code == EXIT_SUCCESS
    assert body_of(transport.requests[1]) == {"uris": [TRACK_URI]}
    assert track_result["playing"]["kind"] == "track"
    assert_every_item_is_linked(track_result, at_least=1)


def test_play_with_no_uri_resumes_and_sends_no_body(signed_in, monkeypatch, capsys):
    transport = use_fake_transport(monkeypatch, FakeTransport([json_response(204)]))

    code, document, _ = run_cli(capsys, "play")

    assert code == EXIT_SUCCESS
    assert body_of(transport.requests[0]) is None
    assert document["resumed"] is True
    assert document["playing"] is None


def test_an_episode_plays_as_a_uri_list_too(signed_in, monkeypatch, capsys):
    transport = use_fake_transport(monkeypatch, FakeTransport([json_response(204)]))

    code, _document, _ = run_cli(capsys, "play", "--uri", EPISODE_URI)

    assert code == EXIT_SUCCESS
    assert body_of(transport.requests[0]) == {"uris": [EPISODE_URI]}


def test_a_named_device_travels_as_a_query_parameter(signed_in, monkeypatch, capsys):
    transport = use_fake_transport(monkeypatch, FakeTransport([json_response(204)]))

    code, document, _ = run_cli(capsys, "pause", "--device", DEVICE_ID)

    assert code == EXIT_SUCCESS
    assert query_of(transport.requests[0].url) == {"device_id": DEVICE_ID}
    assert document["device"] == DEVICE_ID


def test_no_named_device_means_whatever_is_active(signed_in, monkeypatch, capsys):
    transport = use_fake_transport(monkeypatch, FakeTransport([json_response(204)]))

    run_cli(capsys, "pause")

    assert query_of(transport.requests[0].url) == {}


def test_transfer_sends_exactly_one_device_id(signed_in, monkeypatch, capsys):
    """Spotify: "only a single device_id is currently supported"."""
    transport = use_fake_transport(monkeypatch, FakeTransport([json_response(204)]))

    code, document, _ = run_cli(capsys, "transfer", DEVICE_ID, "--play")

    assert code == EXIT_SUCCESS
    assert sent(transport) == [("PUT", "/me/player")]
    assert body_of(transport.requests[0]) == {"device_ids": [DEVICE_ID], "play": True}
    assert document["playing_after_transfer"] is True


def test_shuffle_sends_a_boolean_and_repeat_sends_spotifys_word(
    signed_in, monkeypatch, capsys
):
    transport = use_fake_transport(
        monkeypatch, FakeTransport([json_response(204), json_response(204)])
    )

    run_cli(capsys, "shuffle", "on")
    run_cli(capsys, "repeat", "track")

    assert query_of(transport.requests[0].url) == {"state": "true"}
    assert query_of(transport.requests[1].url) == {"state": "track"}


def test_queue_add_resolves_the_reference_before_sending_it(
    signed_in, monkeypatch, capsys
):
    transport = use_fake_transport(monkeypatch, FakeTransport([json_response(204)]))

    code, document, _ = run_cli(
        capsys, "queue-add", f"https://open.spotify.com/track/{TRACK_ID}"
    )

    assert code == EXIT_SUCCESS
    assert query_of(transport.requests[0].url) == {"uri": TRACK_URI}
    assert document["queued"]["external_urls"]["spotify"].endswith(f"/track/{TRACK_ID}")


@pytest.mark.parametrize("percent", ["-1", "101"])
def test_a_volume_outside_zero_to_a_hundred_refuses_before_a_request(
    signed_in, monkeypatch, capsys, percent
):
    transport = use_fake_transport(monkeypatch, FakeTransport())

    code, document, _ = run_cli(capsys, "volume", percent)

    assert code == EXIT_REFUSAL
    assert document["error"]["code"] == ErrorCode.USAGE
    assert transport.requests == []


def test_a_negative_seek_refuses_before_a_request(signed_in, monkeypatch, capsys):
    transport = use_fake_transport(monkeypatch, FakeTransport())

    code, document, _ = run_cli(capsys, "seek", "-5")

    assert code == EXIT_REFUSAL
    assert document["error"]["code"] == ErrorCode.USAGE
    assert transport.requests == []


# --------------------------------------------------------------------------- #
# top and recently-played
# --------------------------------------------------------------------------- #
def test_top_asks_for_the_type_and_window_the_caller_named(signed_in, monkeypatch, capsys):
    transport = use_fake_transport(
        monkeypatch, FakeTransport([json_response(200, page([track_item()]))])
    )

    code, document, _ = run_cli(
        capsys, "top", "--type", "artists", "--time-range", "short_term"
    )

    assert code == EXIT_SUCCESS
    assert sent(transport) == [("GET", "/me/top/artists")]
    assert query_of(transport.requests[0].url)["time_range"] == "short_term"
    assert document["type"] == "artists"


def test_recently_played_walks_the_before_cursor(signed_in, monkeypatch, capsys):
    """Cursor-paged, and `after`/`before` are mutually exclusive: only `before`."""
    first = page([saved(track_item())] * 50, cursors={"before": "1700000000000"})
    second = page([saved(track_item())] * 5, cursors={"before": None})
    transport = use_fake_transport(
        monkeypatch,
        FakeTransport([json_response(200, first), json_response(200, second)]),
    )

    code, document, _ = run_cli(capsys, "recently-played", "--limit", "55")

    assert code == EXIT_SUCCESS
    assert document["returned"] == 55
    queries = [query_of(request.url) for request in transport.requests]
    assert [query.get("before") for query in queries] == [None, "1700000000000"]
    assert all("after" not in query for query in queries)
    assert [int(query["limit"]) for query in queries] == [50, 5]
