"""Every deterministic Spotify verb, end to end, against a mocked Spotify.

This is the acceptance sweep for MD-3. One table drives it, and each row is one
verb invoked exactly the way a caller would invoke it -- through the real parser,
the real dispatch, the real envelope, the real exit code -- with the transport
replaced so nothing reaches ``api.spotify.com``.

What each row proves, all at once:

* ``cli.v1`` Core 2 -- the verb runs with no model provider and no provider SDK.
* ``cli.v1`` Core 4 -- **exactly one** JSON document on stdout (``json.loads``
  refuses two), and every Spotify item in it carries its own
  ``external_urls.spotify``.
* ``cli.v1`` Core 5 -- exit 0.
* ``boundary.v1`` Core 7 -- the requests the verb actually sent are exactly the
  surviving endpoints named in the row, method and path, in order. This is the
  half a grep cannot do: a path assembled at runtime is visible here.
* ``boundary.v1`` Core 8 -- the state directory afterwards holds the token and
  nothing else.

``check``, ``login``, ``disconnect``, ``whoami`` and ``apply`` are not here:
the first four belong to MD-2 and are covered by ``tests/test_auth.py``,
``tests/test_check.py`` and ``tests/test_disconnect.py``; ``apply`` is MD-5's
and still answers ``not_implemented``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

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
    ALLOWED_STATE_FILES,
    ARTIST_ID,
    DEVICE_ID,
    EPISODE_ID,
    OTHER_TRACK_ID,
    PLAYLIST_ID,
    SHOW_ID,
    TRACK_ID,
    album_item,
    artist_item,
    assert_every_item_is_linked,
    device_item,
    episode_item,
    page,
    playlist_item,
    saved,
    search_page,
    sent,
    show_item,
    state_files,
    track_item,
)

from music_deck.errors import EXIT_SUCCESS


@dataclass(frozen=True)
class Case:
    """One verb: how it is invoked, what Spotify answers, what it must send."""

    name: str
    argv: Sequence[str]
    answers: Sequence[Any]
    expects: Sequence[tuple[str, str]]
    items: int = 0  # the fewest Spotify items the result must carry
    check: Any = None  # an extra assertion over the emitted document


def _no_content() -> Any:
    """Spotify's answer to every Player write: 204, no body."""
    return json_response(204)


CASES: list[Case] = [
    # -- catalogue ----------------------------------------------------------- #
    Case(
        "search",
        ["search", "aphex twin"],
        [json_response(200, search_page([track_item()]))],
        [("GET", "/search")],
        items=3,
        check=lambda doc: (doc["type"] == "track" and doc["returned"] == 1),
    ),
    Case(
        "track",
        ["track", TRACK_ID],
        [json_response(200, track_item())],
        [("GET", f"/tracks/{TRACK_ID}")],
        items=3,
    ),
    Case(
        "album",
        ["album", ALBUM_ID],
        [json_response(200, album_item())],
        [("GET", f"/albums/{ALBUM_ID}")],
        items=2,
    ),
    Case(
        "artist",
        ["artist", ARTIST_ID],
        [json_response(200, artist_item())],
        [("GET", f"/artists/{ARTIST_ID}")],
        items=1,
    ),
    Case(
        "show",
        ["show", SHOW_ID],
        [json_response(200, show_item())],
        [("GET", f"/shows/{SHOW_ID}")],
        items=1,
    ),
    Case(
        "episode",
        ["episode", EPISODE_ID],
        [json_response(200, episode_item())],
        [("GET", f"/episodes/{EPISODE_ID}")],
        items=2,
    ),
    # -- playlists ----------------------------------------------------------- #
    Case(
        "playlists",
        ["playlists"],
        [json_response(200, page([playlist_item()]))],
        [("GET", "/me/playlists")],
        items=1,
    ),
    Case(
        "playlist items",
        ["playlist", "items", PLAYLIST_ID],
        [json_response(200, page([saved(track_item())]))],
        [("GET", f"/playlists/{PLAYLIST_ID}/items")],
        items=4,
    ),
    Case(
        "playlist create",
        ["playlist", "create", "Late night"],
        [json_response(200, playlist_item())],
        [("POST", "/me/playlists")],
        items=1,
    ),
    Case(
        "playlist add",
        ["playlist", "add", PLAYLIST_ID, TRACK_ID],
        [json_response(200, {"snapshot_id": "snap-1"})],
        [("POST", f"/playlists/{PLAYLIST_ID}/items")],
        items=1,
        check=lambda doc: doc["added"] == 1 and doc["snapshot_id"] == "snap-1",
    ),
    Case(
        "playlist remove",
        ["playlist", "remove", PLAYLIST_ID, TRACK_ID],
        [json_response(200, {"snapshot_id": "snap-2"})],
        [("DELETE", f"/playlists/{PLAYLIST_ID}/items")],
        items=1,
        check=lambda doc: doc["removed"] == 1,
    ),
    Case(
        "playlist reorder",
        ["playlist", "reorder", PLAYLIST_ID, "--range-start", "0", "--insert-before", "3"],
        [json_response(200, {"snapshot_id": "snap-3"})],
        [("PUT", f"/playlists/{PLAYLIST_ID}/items")],
        items=1,
        check=lambda doc: doc["moved"] == 1 and doc["snapshot_id"] == "snap-3",
    ),
    Case(
        "playlist rename",
        ["playlist", "rename", PLAYLIST_ID, "Later"],
        [json_response(200)],
        [("PUT", f"/playlists/{PLAYLIST_ID}")],
        items=1,
        check=lambda doc: doc["renamed"] is True and doc["name"] == "Later",
    ),
    # -- library ------------------------------------------------------------- #
    Case(
        "library list",
        ["library", "list"],
        [json_response(200, page([saved(track_item())]))],
        [("GET", "/me/tracks")],
        items=3,
        check=lambda doc: doc["type"] == "tracks",
    ),
    Case(
        "library save",
        ["library", "save", f"spotify:track:{TRACK_ID}"],
        [json_response(200)],
        [("PUT", "/me/library")],
        items=1,
        check=lambda doc: doc["saved"] == 1,
    ),
    Case(
        "library remove",
        ["library", "remove", f"spotify:album:{ALBUM_ID}"],
        [json_response(200)],
        [("DELETE", "/me/library")],
        items=1,
        check=lambda doc: doc["removed"] == 1,
    ),
    Case(
        "library contains",
        ["library", "contains", f"spotify:track:{TRACK_ID}"],
        [json_response(200, [True])],
        [("GET", "/me/library/contains")],
        items=1,
        check=lambda doc: doc["contains"][f"spotify:track:{TRACK_ID}"] is True,
    ),
    Case(
        "following",
        ["following"],
        [json_response(200, {"artists": page([artist_item()], cursors={"after": None})})],
        [("GET", "/me/following")],
        items=1,
    ),
    # -- personalisation ----------------------------------------------------- #
    Case(
        "top",
        ["top"],
        [json_response(200, page([track_item()]))],
        [("GET", "/me/top/tracks")],
        items=3,
        check=lambda doc: doc["time_range"] == "medium_term",
    ),
    Case(
        "recently-played",
        ["recently-played"],
        [json_response(200, page([saved(track_item())], cursors={"before": None}))],
        [("GET", "/me/player/recently-played")],
        items=3,
    ),
    # -- player reads -------------------------------------------------------- #
    Case(
        "now-playing",
        ["now-playing"],
        [json_response(200, {"is_playing": True, "item": track_item(), "device": device_item()})],
        [("GET", "/me/player")],
        items=3,
    ),
    Case(
        "devices",
        ["devices"],
        [json_response(200, {"devices": [device_item()]})],
        [("GET", "/me/player/devices")],
        check=lambda doc: doc["count"] == 1 and doc["active"]["id"] == DEVICE_ID,
    ),
    Case(
        "queue",
        ["queue"],
        [
            json_response(
                200,
                {
                    "currently_playing": track_item(),
                    "queue": [track_item(OTHER_TRACK_ID, "Tha")],
                },
            )
        ],
        [("GET", "/me/player/queue")],
        items=6,
        check=lambda doc: doc["count"] == 1,
    ),
    # -- player writes ------------------------------------------------------- #
    Case(
        "play",
        ["play", "--uri", f"spotify:album:{ALBUM_ID}"],
        [_no_content()],
        [("PUT", "/me/player/play")],
        items=1,
        check=lambda doc: doc["playing"]["kind"] == "album" and doc["resumed"] is False,
    ),
    Case("pause", ["pause"], [_no_content()], [("PUT", "/me/player/pause")]),
    Case("next", ["next"], [_no_content()], [("POST", "/me/player/next")]),
    Case("previous", ["previous"], [_no_content()], [("POST", "/me/player/previous")]),
    Case(
        "seek",
        ["seek", "12000"],
        [_no_content()],
        [("PUT", "/me/player/seek")],
        check=lambda doc: doc["position_ms"] == 12000,
    ),
    Case(
        "volume",
        ["volume", "40"],
        [_no_content()],
        [("PUT", "/me/player/volume")],
        check=lambda doc: doc["volume_percent"] == 40,
    ),
    Case(
        "shuffle",
        ["shuffle", "on"],
        [_no_content()],
        [("PUT", "/me/player/shuffle")],
        check=lambda doc: doc["shuffle"] is True,
    ),
    Case(
        "repeat",
        ["repeat", "context"],
        [_no_content()],
        [("PUT", "/me/player/repeat")],
        check=lambda doc: doc["repeat"] == "context",
    ),
    Case(
        "transfer",
        ["transfer", DEVICE_ID],
        [_no_content()],
        [("PUT", "/me/player")],
        check=lambda doc: doc["device"] == DEVICE_ID,
    ),
    Case(
        "queue-add",
        ["queue-add", f"spotify:track:{TRACK_ID}"],
        [_no_content()],
        [("POST", "/me/player/queue")],
        items=1,
    ),
]

CASES_BY_NAME = {case.name: case for case in CASES}


@pytest.mark.parametrize("case", CASES, ids=[case.name for case in CASES])
def test_every_deterministic_spotify_verb_answers_one_json_document(
    case, monkeypatch, tmp_path, capsys
):
    install_token(monkeypatch, tmp_path, token_document())
    transport = use_fake_transport(monkeypatch, FakeTransport(list(case.answers)))

    code, document, stderr = run_cli(capsys, *case.argv)

    assert code == EXIT_SUCCESS, f"{case.name} exited {code}: {document} / {stderr}"
    assert document is not None, f"{case.name} printed nothing to stdout"
    assert sent(transport) == list(case.expects), (
        f"{case.name} sent {sent(transport)}, expected {list(case.expects)}"
    )
    assert_every_item_is_linked(document, at_least=case.items)
    if case.check is not None:
        assert case.check(document), f"{case.name} returned {document}"
    assert state_files(tmp_path / "state") <= ALLOWED_STATE_FILES


def test_the_sweep_covers_every_verb_this_lane_owns():
    """A table with a row quietly missing would pass without proving anything.

    ``cli.v1`` Core 2's deterministic list, minus the five verbs other lanes own,
    is exactly what this file must exercise -- so it is derived from the CLI's
    own verb table rather than retyped here.
    """
    from music_deck.cli import VERBS

    owned_elsewhere = {"check", "manifest", "login", "disconnect", "whoami", "apply", "plan"}
    surface: set[str] = set()
    for verb in VERBS:
        if verb.subverbs:
            surface |= {f"{verb.name} {sub.name}" for sub in verb.subverbs}
        else:
            surface.add(verb.name)

    assert set(CASES_BY_NAME) == surface - owned_elsewhere


def test_no_verb_writes_spotify_content_into_the_state_directory(
    monkeypatch, tmp_path, capsys
):
    """boundary.v1 Core 8, over the whole surface in one run.

    Each verb above is checked individually; this runs all of them against one
    state directory, because "no file appeared" is a weaker claim than "no file
    appeared after thirty-two verbs in a row".
    """
    install_token(monkeypatch, tmp_path, token_document())
    state = tmp_path / "state"

    for case in CASES:
        use_fake_transport(monkeypatch, FakeTransport(list(case.answers)))
        code, _document, _stderr = run_cli(capsys, *case.argv)
        assert code == EXIT_SUCCESS, case.name

    assert state_files(state) == {"token.json"}, sorted(state_files(state))


def test_the_complete_listing_does_not_call_a_built_verb_unbuilt():
    """cli.v1 Core 1: a complete listing that lies is worse than none.

    `playlist` and `library` group sub-verbs and have no handler of their own, so
    they used to render as "[NOT IMPLEMENTED in this build]" -- which was true
    while their sub-verbs were stubs and became a lie the moment they were not.
    `apply` was the last verb still carrying the marker honestly; MD-5
    (music_deck-v0b) built it, so nothing carries it now.

    The assertion is deliberately "none", not "at most one": an agent reading
    the complete listing has to be able to trust that an unmarked verb works,
    and the day a lane adds a stub without building it, this fails.
    """
    from music_deck.cli import complete_help

    marker = "[NOT IMPLEMENTED in this build]"
    unbuilt = [line for line in complete_help().splitlines() if marker in line]

    assert unbuilt == [], unbuilt


def test_the_complete_listing_still_carries_the_marker_when_a_verb_is_unbuilt():
    """The other half: a listing that *never* marks anything proves nothing.

    With no stub left in the table, "no line carries the marker" would also pass
    for a build that had quietly stopped rendering the marker at all. This puts
    a stub back, in a copy of the table, and checks the rendering still says so.
    """
    import dataclasses

    from music_deck.cli import VERBS_BY_NAME, _render_verb

    stub = dataclasses.replace(VERBS_BY_NAME["apply"], handler=None)
    rendered = "\n".join(_render_verb(stub))

    assert "[NOT IMPLEMENTED in this build]" in rendered
