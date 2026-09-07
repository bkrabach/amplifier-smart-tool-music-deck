"""`do` -- the loop that runs a search, sees the zero, and corrects itself.

This file exists because of one measured failure. On 2026-09-06, asked for three
90s grunge songs, ``plan`` wrote ``genre:grunge year:1990-1999``; ``apply``
searched it, Spotify returned **zero results**, and ``apply`` created an empty
playlist anyway. ``genre:grunge`` alone returns five. So every test below is
built on that shape: a first search that returns nothing, and the question of
what the tool does next.

What each group proves
----------------------
* **The correction** -- the zero reaches the model, the model searches again,
  and *no playlist is created for the empty result*. Both halves are asserted,
  because either alone would pass while the failure survived.
* **The empty playlist is unreachable** -- not discouraged in a prompt.
  ``create_playlist`` takes its tracks in the same call and refuses an empty
  list, and refuses a URI no search in the run returned. A model that lies about
  what it found cannot write to the caller's account.
* **The refusal** -- every search empty means ``partial_result`` with
  ``completeness``, no playlist, exit 2.
* **The ceilings** -- both are enforced by music-deck and both are reported.
* **The transcript** -- ``boundary.v1`` Core 3, and the fail-closed check over
  it: a brief carrying something shaped like an access token is refused rather
  than answered.

Nothing here reaches ``api.spotify.com`` or a model provider. Spotify is
``FakeTransport``; the model is a double from
``music_deck.testing.intelligence_doubles`` or the reactive one below.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from music_deck import cli
from music_deck.errors import EXIT_NO_PROVIDER, EXIT_REFUSAL, EXIT_SUCCESS, ErrorCode, MusicDeckError
from music_deck.prompt_boundary import check_prompts, machine_credentials
from music_deck.testing.intelligence_doubles import (
    FAKE_ACCESS_TOKEN,
    Recording,
    Scripted,
    Unconfigured,
)
from music_deck.verbs import do as do_module
from music_deck.verbs.do import DEFAULT_MAX_REQUESTS, DEFAULT_MAX_TURNS, TOOLS, do
from spotify_fakes import (
    FakeTransport,
    install_token,
    json_response,
    run_cli,
    token_document,
    use_fake_transport,
)
from verb_fixtures import (
    PLAYLIST_ID,
    artist_item,
    assert_every_item_is_linked,
    page,
    path_of,
    query_of,
    saved,
    search_page,
    sent,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

BRIEF = "three 90s grunge songs in a new playlist called Flannel"

# The two queries the incident turned on, verbatim.
DEAD_QUERY = "genre:grunge year:1990-1999"
LIVE_QUERY = "genre:grunge"


# --------------------------------------------------------------------------- #
# Spotify, stocked per query
# --------------------------------------------------------------------------- #
def grunge_track(index: int) -> dict[str, Any]:
    """A track in Spotify's own shape, carrying no ``external_urls``.

    Deliberately no link: ``cli.v1`` Core 4 says music-deck emits one on every
    item, and a fixture that supplied it would prove nothing about whether
    music-deck does.
    """
    ident = f"{index:022d}".replace("0", "A", 1)
    names = ["Black Hole Sun", "Rusty Cage", "Would?", "Nearly Lost You", "Touch Me I'm Sick"]
    bands = ["Soundgarden", "Soundgarden", "Alice In Chains", "Screaming Trees", "Mudhoney"]
    return {
        "id": ident,
        "uri": f"spotify:track:{ident}",
        "name": names[index % len(names)],
        "type": "track",
        "popularity": 70 - index,
        "artists": [artist_item(f"{index:022d}".replace("0", "B", 1), bands[index % len(bands)])],
    }


GRUNGE = [grunge_track(i) for i in range(5)]


class Spotify:
    """A Spotify that answers by path, and refuses anything a test never stocked.

    Same discipline as ``tests/test_apply.py``'s double: an unstocked query is
    an assertion failure rather than an empty page, so a loop that quietly
    started searching for something else fails here instead of passing.
    """

    def __init__(
        self,
        by_query: dict[str, list[dict[str, Any]]],
        *,
        playlist_id: str = PLAYLIST_ID,
        holds: list[dict[str, Any]] | None = None,
    ) -> None:
        self.by_query = by_query
        self.playlist_id = playlist_id
        self.holds: list[dict[str, Any]] = list(holds) if holds is not None else []
        self.explicit_holds = holds is not None
        self.created: list[str] = []

    def __call__(self, request):
        path = path_of(request.url)
        params = query_of(request.url)

        if path == "/search":
            found = self.by_query.get(params["q"])
            assert found is not None, (
                f"do searched for {params['q']!r}, which this test never stocked. "
                f"Stocked: {sorted(self.by_query)}"
            )
            want = int(params["limit"])
            offset = int(params.get("offset", 0))
            return json_response(
                200, search_page(found[offset : offset + want], kind=params["type"])
            )

        if path == "/me/playlists" and request.method == "POST":
            body = json.loads(request.body.decode("utf-8"))
            self.created.append(body["name"])
            return json_response(
                201,
                {
                    "id": self.playlist_id,
                    "uri": f"spotify:playlist:{self.playlist_id}",
                    "name": body["name"],
                    "type": "playlist",
                    "public": False,
                },
            )

        if path == "/me/playlists":
            return json_response(200, page([]))

        if path.endswith("/items") and request.method == "POST":
            body = json.loads(request.body.decode("utf-8"))
            if not self.explicit_holds:
                for uri in body["uris"]:
                    match = next((t for t in GRUNGE if t["uri"] == uri), None)
                    if match is not None:
                        self.holds.append(match)
            return json_response(200, {"snapshot_id": "snapshot-under-test"})

        if path.endswith("/items"):
            return json_response(200, page([saved(track) for track in self.holds]))

        raise AssertionError(f"do sent an unexpected request: {request.method} {path}")


def connect(monkeypatch, double: Spotify, *, budget: int = 64) -> FakeTransport:
    return use_fake_transport(monkeypatch, FakeTransport([double] * budget))


@pytest.fixture
def signed_in(monkeypatch, tmp_path):
    install_token(monkeypatch, tmp_path, token_document())
    return tmp_path


# --------------------------------------------------------------------------- #
# Scripting the model
# --------------------------------------------------------------------------- #
def call(tool: str, **arguments: Any) -> str:
    """One turn's reply, in the shape the prompt asks the model for."""
    return json.dumps(
        {"thought": f"calling {tool}", "tool": tool, "arguments": arguments}
    )


def uris(count: int) -> list[str]:
    return [track["uri"] for track in GRUNGE[:count]]


class Reactive:
    """A model that answers by *reading the prompt it was given*.

    The scripted doubles prove music-deck's loop runs in the right order. This
    one proves the thing that actually matters: that the zero-result observation
    reaches the model in a form it can act on. It never counts turns -- it looks
    for the sentence music-deck puts in front of it when a search comes back
    empty, and only then widens the query. If the observation stopped reaching
    the prompt, this double would repeat the dead query forever and the test
    would fail on the turn ceiling.
    """

    implementation = "reactive"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def preflight(self, provider: str | None = None) -> str:
        return provider or "reactive"

    def run(self, request):
        import re

        from music_deck.intelligence import ModelResult

        self.prompts.append(request.prompt)
        prompt = request.prompt

        if "## What has happened so far" not in prompt:
            # Nothing observed yet: try the query the incident actually used.
            reply = call("search", query=DEAD_QUERY, type="track", limit=10)
        elif "The tracks are in the playlist" in prompt:
            reply = call("finish", summary="Three grunge songs are in Flannel.")
        else:
            history = prompt.split("## What has happened so far", 1)[1]
            counts = re.findall(r'"returned": (\d+)', history)
            if counts and int(counts[-1]) == 0:
                # The last thing music-deck showed it was a zero. Widen.
                reply = call("search", query=LIVE_QUERY, type="track", limit=10)
            else:
                uris_seen = re.findall(r'"uri": "(spotify:track:[^"]+)"', history)
                reply = call("create_playlist", name="Flannel", tracks=uris_seen[:3])

        return ModelResult(text=reply, provider="reactive", model="reactive-1")


# =========================================================================== #
# The correction -- the whole reason this verb exists
# =========================================================================== #
def test_a_zero_result_search_is_corrected_and_writes_no_empty_playlist(
    monkeypatch, signed_in
):
    """The measured incident, run through `do`, ending the other way.

    Two assertions, and both are load-bearing. That the loop searched again is
    half the claim; that it created **no playlist for the empty result** is the
    other half, and the half `apply` failed.
    """
    spotify = Spotify({DEAD_QUERY: [], LIVE_QUERY: GRUNGE})
    transport = connect(monkeypatch, spotify)
    model = Scripted(
        call("search", query=DEAD_QUERY, type="track", limit=10),
        call("search", query=LIVE_QUERY, type="track", limit=10),
        call("create_playlist", name="Flannel", tracks=uris(3)),
        call("finish", summary="Three grunge songs are in Flannel."),
    )

    result = do(BRIEF, intelligence=model)

    queries = [q["query"] for q in result["searches"]]
    assert queries == [DEAD_QUERY, LIVE_QUERY], queries
    assert result["searches"][0]["returned"] == 0
    assert result["searches"][1]["returned"] == 5

    # The playlist was created exactly once, and *after* the search that found
    # something. Order is the whole point: a POST before the second search
    # would be the empty playlist all over again.
    calls = sent(transport)
    assert calls.count(("POST", "/me/playlists")) == 1
    creation = calls.index(("POST", "/me/playlists"))
    searches = [i for i, entry in enumerate(calls) if entry == ("GET", "/search")]
    assert len(searches) == 2
    assert searches[1] < creation, calls

    assert len(result["tracks"]) >= 3
    assert result["playlist"]["created"] is True
    assert result["stopped_by"] == "finish"


def test_the_zero_is_put_in_front_of_the_model_before_it_searches_again(
    monkeypatch, signed_in
):
    """The observation the correction depends on is really in the next prompt.

    Without this, the test above would pass on a script that happened to search
    twice, whether or not the model was ever told the first search failed.
    """
    connect(monkeypatch, Spotify({DEAD_QUERY: [], LIVE_QUERY: GRUNGE}))
    model = Scripted(
        call("search", query=DEAD_QUERY, type="track", limit=10),
        call("search", query=LIVE_QUERY, type="track", limit=10),
        call("create_playlist", name="Flannel", tracks=uris(3)),
        call("finish", summary="done"),
    )

    do(BRIEF, intelligence=model)

    first, second = model.prompts[0], model.prompts[1]
    # The first turn has no history at all -- the model has been shown nothing.
    # (The dead query itself appears in the shipped instructions, where it is a
    # worked example of the trap; that is not an observation.)
    assert "## What has happened so far" not in first

    history = second.split("## What has happened so far", 1)[1]
    assert DEAD_QUERY in history
    assert '"returned": 0' in history
    assert "returned NOTHING" in history


def test_the_model_corrects_itself_from_what_it_was_shown_not_from_a_script(
    monkeypatch, signed_in
):
    """The same correction, driven by a model that only reads the prompt.

    ``Reactive`` has no turn counter. It widens the query because music-deck
    told it the first one returned nothing. If that observation stopped
    reaching the prompt, this run would spend its whole turn budget repeating
    the dead query and refuse.
    """
    spotify = Spotify({DEAD_QUERY: [], LIVE_QUERY: GRUNGE})
    connect(monkeypatch, spotify)

    result = do(BRIEF, intelligence=Reactive())

    assert [q["query"] for q in result["searches"]] == [DEAD_QUERY, LIVE_QUERY]
    assert result["completeness"]["added"] == 3
    assert len(result["tracks"]) == 3
    assert spotify.created == ["Flannel"]


# =========================================================================== #
# The empty playlist is unreachable, not merely discouraged
# =========================================================================== #
def test_create_playlist_with_no_tracks_creates_nothing_and_says_why(
    monkeypatch, signed_in
):
    """A model that tries the `apply` failure directly is refused, mid-run.

    This is the structural half of the promise: there is no call that creates an
    empty playlist, so the outcome cannot be reached by a model behaving badly,
    only prevented by one behaving well.
    """
    spotify = Spotify({DEAD_QUERY: [], LIVE_QUERY: GRUNGE})
    transport = connect(monkeypatch, spotify)
    model = Scripted(
        call("search", query=DEAD_QUERY, type="track", limit=10),
        call("create_playlist", name="Flannel", tracks=[]),
        call("search", query=LIVE_QUERY, type="track", limit=10),
        call("create_playlist", name="Flannel", tracks=uris(3)),
        call("finish", summary="done"),
    )

    result = do(BRIEF, intelligence=model)

    refused = result["actions"][1]
    assert refused["tool"] == "create_playlist"
    assert refused["observation"]["error"] == "no_tracks"
    assert "will not create an empty playlist" in refused["observation"]["message"]

    calls = sent(transport)
    assert calls.count(("POST", "/me/playlists")) == 1
    assert spotify.created == ["Flannel"]


def test_a_track_uri_no_search_returned_is_refused_by_name(monkeypatch, signed_in):
    """A model cannot answer an empty search by inventing plausible ids.

    The URI below is well-formed -- it would pass every syntax check music-deck
    has -- and it is refused solely because no search in this run returned it.
    """
    invented = "spotify:track:0000000000000000000000"
    spotify = Spotify({DEAD_QUERY: [], LIVE_QUERY: GRUNGE})
    transport = connect(monkeypatch, spotify)
    model = Scripted(
        call("search", query=DEAD_QUERY, type="track", limit=10),
        call("create_playlist", name="Flannel", tracks=[invented, invented]),
        call("search", query=LIVE_QUERY, type="track", limit=10),
        call("create_playlist", name="Flannel", tracks=uris(3)),
        call("finish", summary="done"),
    )

    result = do(BRIEF, intelligence=model)

    refused = result["actions"][1]["observation"]
    assert refused["error"] == "unseen_tracks"
    assert invented in refused["message"]
    assert sent(transport).count(("POST", "/me/playlists")) == 1


# =========================================================================== #
# Every search empty -- partial_result, no playlist, non-zero exit
# =========================================================================== #
def test_every_search_empty_refuses_partial_result_and_creates_no_playlist(
    monkeypatch, signed_in
):
    spotify = Spotify({DEAD_QUERY: [], "genre:seattle year:1991": []})
    transport = connect(monkeypatch, spotify)
    model = Scripted(
        call("search", query=DEAD_QUERY, type="track", limit=10),
        call("search", query="genre:seattle year:1991", type="track", limit=10),
        call("finish", summary="I could not find anything."),
    )

    with pytest.raises(MusicDeckError) as raised:
        do(BRIEF, intelligence=model)

    failure = raised.value
    assert failure.code == ErrorCode.PARTIAL_RESULT
    assert failure.exit_code == EXIT_REFUSAL

    completeness = failure.extra["completeness"]
    assert completeness["searches_run"] == 2
    assert completeness["searches_with_results"] == 0
    assert completeness["fetched"] == 0
    assert completeness["added"] == 0
    assert completeness["under_fulfilled"] == [0, 1]
    assert [s["query"] for s in completeness["searches"]] == [
        DEAD_QUERY,
        "genre:seattle year:1991",
    ]

    assert ("POST", "/me/playlists") not in sent(transport)
    assert spotify.created == []
    assert failure.extra["result"]["playlist"] is None


def test_the_empty_run_refusal_reaches_the_cli_as_exit_two(
    monkeypatch, signed_in, capsys
):
    connect(monkeypatch, Spotify({DEAD_QUERY: []}))
    _use_model(
        monkeypatch,
        Scripted(
            call("search", query=DEAD_QUERY, type="track", limit=10),
            call("finish", summary="nothing found"),
        ),
    )

    code, document, _err = run_cli(capsys, "do", BRIEF)

    assert code == EXIT_REFUSAL
    assert document["error"]["code"] == ErrorCode.PARTIAL_RESULT
    assert document["error"]["completeness"]["searches_with_results"] == 0


# =========================================================================== #
# The read-back -- what Spotify says, not what we asked for
# =========================================================================== #
def test_the_result_reports_what_spotify_says_it_holds_not_what_was_written(
    monkeypatch, signed_in
):
    """Four written, three held: the result reports three.

    A verb that echoed its own write would report four here. That is exactly the
    claim the acceptance criterion refuses to accept, so the double is stocked
    to disagree with the write on purpose.
    """
    spotify = Spotify({LIVE_QUERY: GRUNGE}, holds=GRUNGE[:3])
    transport = connect(monkeypatch, spotify)
    model = Scripted(
        call("search", query=LIVE_QUERY, type="track", limit=10),
        call("create_playlist", name="Flannel", tracks=uris(4)),
        call("finish", summary="done"),
    )

    result = do(BRIEF, intelligence=model)

    assert result["completeness"]["kept"] == 4
    assert result["completeness"]["added"] == 4
    assert result["completeness"]["read_back"] == 3
    assert len(result["tracks"]) == 3
    assert result["read_back"]["asked_for"] == 4
    assert result["read_back"]["returned"] == 3

    reads = [
        entry
        for entry in sent(transport)
        if entry[0] == "GET" and entry[1].endswith("/items")
    ]
    assert reads, sent(transport)


def test_every_spotify_item_in_the_result_carries_its_link(monkeypatch, signed_in):
    """``cli.v1`` Core 4, over the whole emitted document."""
    connect(monkeypatch, Spotify({LIVE_QUERY: GRUNGE}))
    model = Scripted(
        call("search", query=LIVE_QUERY, type="track", limit=10),
        call("create_playlist", name="Flannel", tracks=uris(3)),
        call("finish", summary="done"),
    )

    result = do(BRIEF, intelligence=model)

    # The document is round-tripped through JSON first: what a caller parses is
    # what `cli.v1` Core 4 speaks about, not the Python objects behind it.
    assert_every_item_is_linked(json.loads(json.dumps(result)), at_least=4)


# =========================================================================== #
# boundary.v1 Core 3 -- the transcript, and failing closed over it
# =========================================================================== #
def test_the_result_carries_one_verbatim_prompt_per_turn(monkeypatch, signed_in):
    connect(monkeypatch, Spotify({LIVE_QUERY: GRUNGE}))
    model = Recording(
        call("search", query=LIVE_QUERY, type="track", limit=10),
        call("create_playlist", name="Flannel", tracks=uris(3)),
        call("finish", summary="done"),
    )

    result = do(BRIEF, intelligence=model)

    # Not "a transcript exists" but "it is the strings that crossed the seam",
    # recorded by the double at the moment of sending.
    assert result["transcript"] == model.prompts
    assert len(result["transcript"]) == 3
    assert all(BRIEF in prompt for prompt in result["transcript"])


def test_check_prompts_reports_ok_over_the_transcript_do_returns(
    monkeypatch, signed_in
):
    """``boundary.v1`` Core 2, run over ``do``'s own published output.

    The credentials searched for are this machine's -- which under
    ``signed_in`` is a real stored token file, so the exact-value net has
    something to look for rather than passing vacuously.
    """
    connect(monkeypatch, Spotify({LIVE_QUERY: GRUNGE}))
    model = Scripted(
        call("search", query=LIVE_QUERY, type="track", limit=10),
        call("create_playlist", name="Flannel", tracks=uris(3)),
        call("finish", summary="done"),
    )

    result = do(BRIEF, intelligence=model)

    credentials = machine_credentials()
    assert credentials, "the signed_in fixture should give the exact-value net work to do"
    report = check_prompts(result["transcript"], credentials)
    assert report.ok, report.describe()
    assert report.checked == len(result["transcript"])


def test_a_credential_in_a_prompt_fails_closed_before_anything_is_returned(
    monkeypatch, signed_in
):
    """The BAD half of the pair: a run that would leak refuses instead.

    The credential arrives the only way a caller can put one there -- inside the
    brief, which ``do`` sends verbatim. The token is a fixture: real in shape,
    the value of nothing. ``internal_error`` because ``refusals.v1`` Core 8
    defines that as "a defect in music-deck", which is what this is; the
    vocabulary is closed and ``do`` adds nothing to it.
    """
    spotify = Spotify({LIVE_QUERY: GRUNGE})
    transport = connect(monkeypatch, spotify)
    leaky = f"three grunge songs, and here is my token: {FAKE_ACCESS_TOKEN}"
    model = Scripted(
        call("search", query=LIVE_QUERY, type="track", limit=10),
        call("create_playlist", name="Flannel", tracks=uris(3)),
        call("finish", summary="done"),
    )

    with pytest.raises(MusicDeckError) as raised:
        do(leaky, intelligence=model)

    failure = raised.value
    assert failure.code == "internal_error"
    assert "boundary.v1 Core 2" in failure.message
    assert "the access token" in failure.message
    # The check names what it found and never reprints it.
    assert FAKE_ACCESS_TOKEN not in failure.message
    assert FAKE_ACCESS_TOKEN not in failure.remedy
    # It refused on the way out, so the model did see the prompt -- but the
    # caller sees a refusal, never the result document.
    assert model.prompts
    assert sent(transport)


# =========================================================================== #
# The ceilings -- enforced here, reported always
# =========================================================================== #
def test_the_turn_ceiling_stops_the_loop_and_reports_what_it_completed(
    monkeypatch, signed_in
):
    """A model that never calls `finish` still stops, and still reports.

    It wrote a playlist first, so this is a *success* that names its ceiling --
    the acceptance criterion asks for both the ceiling and what was completed,
    not for a refusal.
    """
    connect(monkeypatch, Spotify({LIVE_QUERY: GRUNGE}))
    model = Scripted(
        call("search", query=LIVE_QUERY, type="track", limit=10),
        call("create_playlist", name="Flannel", tracks=uris(3)),
        call("search", query=LIVE_QUERY, type="track", limit=10),
        call("search", query=LIVE_QUERY, type="track", limit=10),
    )

    result = do(BRIEF, max_turns=3, intelligence=model)

    assert result["stopped_by"] == "turns"
    assert result["ceilings"]["turns"] == {"limit": 3, "used": 3}
    assert result["ceilings"]["spotify_requests"]["limit"] == DEFAULT_MAX_REQUESTS
    assert len(result["transcript"]) == 3
    assert len(result["tracks"]) == 3


def test_the_turn_ceiling_with_nothing_written_refuses_and_names_the_ceiling(
    monkeypatch, signed_in
):
    connect(monkeypatch, Spotify({LIVE_QUERY: GRUNGE}))
    model = Scripted(*[call("search", query=LIVE_QUERY, type="track", limit=10)] * 4)

    with pytest.raises(MusicDeckError) as raised:
        do(BRIEF, max_turns=2, intelligence=model)

    failure = raised.value
    assert failure.code == ErrorCode.PARTIAL_RESULT
    assert failure.extra["stopped_by"] == "turns"
    assert failure.extra["ceilings"]["turns"] == {"limit": 2, "used": 2}
    assert "turns ceiling of 2" in failure.message
    assert "--max-turns" in failure.remedy


def test_the_spotify_request_ceiling_stops_the_loop_and_names_itself(
    monkeypatch, signed_in
):
    """The budget that protects somebody else's quota, proven to bind.

    Two requests is enough for one search and no more, so the second search
    trips the ceiling rather than the turn count -- which is what makes this a
    test of the request ceiling specifically.
    """
    spotify = Spotify({LIVE_QUERY: GRUNGE, DEAD_QUERY: []})
    transport = connect(monkeypatch, spotify)
    model = Scripted(
        call("search", query=LIVE_QUERY, type="track", limit=10),
        call("search", query=DEAD_QUERY, type="track", limit=10),
        call("search", query=DEAD_QUERY, type="track", limit=10),
    )

    with pytest.raises(MusicDeckError) as raised:
        do(BRIEF, max_turns=6, max_requests=1, intelligence=model)

    failure = raised.value
    assert failure.code == ErrorCode.PARTIAL_RESULT
    assert failure.extra["stopped_by"] == "spotify_requests"
    assert failure.extra["ceilings"]["spotify_requests"] == {"limit": 1, "used": 1}
    assert "spotify_requests ceiling of 1" in failure.message
    # The ceiling is enforced by music-deck, so Spotify saw exactly one request.
    assert len(transport.requests) == 1


def test_both_ceilings_are_reported_on_an_ordinary_successful_run(
    monkeypatch, signed_in
):
    connect(monkeypatch, Spotify({LIVE_QUERY: GRUNGE}))
    model = Scripted(
        call("search", query=LIVE_QUERY, type="track", limit=10),
        call("create_playlist", name="Flannel", tracks=uris(3)),
        call("finish", summary="done"),
    )

    result = do(BRIEF, intelligence=model)

    ceilings = result["ceilings"]
    assert ceilings["turns"] == {"limit": DEFAULT_MAX_TURNS, "used": 3}
    assert ceilings["spotify_requests"]["limit"] == DEFAULT_MAX_REQUESTS
    assert 0 < ceilings["spotify_requests"]["used"] <= DEFAULT_MAX_REQUESTS


@pytest.mark.parametrize("flag,value", [("--max-turns", 0), ("--max-requests", 0)])
def test_a_ceiling_below_one_is_refused_before_any_prompt(
    monkeypatch, signed_in, capsys, flag, value
):
    model = Recording()
    _use_model(monkeypatch, model)

    code, document, _err = run_cli(capsys, "do", BRIEF, flag, str(value))

    assert code == EXIT_REFUSAL
    assert document["error"]["code"] == ErrorCode.USAGE
    assert flag in document["error"]["message"]
    assert model.prompts == []


# =========================================================================== #
# cli.v1 Cores 1-3 -- the surface, and the refusal before any prompt
# =========================================================================== #
def test_help_lists_do_and_marks_it_model_backed():
    complete = cli.complete_help()

    assert "music-deck do  (model-backed)" in complete
    assert "--max-turns" in complete
    assert "--max-requests" in complete
    # cli.v1 Core 1: `--help` says which verbs are model-backed. Two now.
    assert complete.count("(model-backed)") == 2
    assert "do   -- a brief is carried out end to end" in complete


def test_do_with_no_provider_exits_three_and_builds_no_prompt(
    monkeypatch, signed_in, capsys
):
    """``cli.v1`` Core 3, with the double that fails loudly if a prompt is built.

    ``Unconfigured.run`` raises an ``AssertionError`` if it is ever reached, so
    a build that assembled a prompt and only then discovered it had no substrate
    would fail here rather than pass quietly.
    """
    unconfigured = Unconfigured()
    _use_model(monkeypatch, unconfigured)

    code, document, _err = run_cli(capsys, "do", BRIEF)

    assert code == EXIT_NO_PROVIDER
    assert document["error"]["code"] == "no_provider_configured"
    assert document["error"]["missing"] == "provider"
    assert unconfigured.run_calls == []
    # And it names the verb the caller actually ran. The seam's own message
    # still says `plan` -- it was written when `plan` was the only model-backed
    # verb -- and a refusal that tells a caller about a verb they did not run
    # is a refusal they cannot act on. Measured against an installed copy
    # before it was corrected; see `do._preflight`.
    assert "`do`" in document["error"]["message"]
    assert "`plan`" not in document["error"]["message"]


def test_an_empty_brief_is_usage_and_never_reaches_a_model(monkeypatch, capsys):
    model = Recording()
    _use_model(monkeypatch, model)

    code, document, _err = run_cli(capsys, "do", "   ")

    assert code == EXIT_REFUSAL
    assert document["error"]["code"] == ErrorCode.USAGE
    assert model.prompts == []


def test_the_cli_returns_one_json_document_on_a_successful_run(
    monkeypatch, signed_in, capsys
):
    """``cli.v1`` Core 4: a parsed result is one JSON document, no `--json` twin."""
    connect(monkeypatch, Spotify({LIVE_QUERY: GRUNGE}))
    _use_model(
        monkeypatch,
        Scripted(
            call("search", query=LIVE_QUERY, type="track", limit=10),
            call("create_playlist", name="Flannel", tracks=uris(3)),
            call("finish", summary="done"),
        ),
    )

    code, document, _err = run_cli(capsys, "do", BRIEF)

    assert code == EXIT_SUCCESS
    assert isinstance(document, dict)
    assert set(document) >= {
        "brief",
        "playlist",
        "tracks",
        "searches",
        "actions",
        "completeness",
        "ceilings",
        "transcript",
    }
    assert document["brief"] == BRIEF


# =========================================================================== #
# The model misbehaving is survivable, not fatal
# =========================================================================== #
def test_an_unreadable_reply_costs_one_turn_and_the_run_carries_on(
    monkeypatch, signed_in
):
    connect(monkeypatch, Spotify({LIVE_QUERY: GRUNGE}))
    model = Scripted(
        "I would love to help you with that!",
        call("search", query=LIVE_QUERY, type="track", limit=10),
        call("create_playlist", name="Flannel", tracks=uris(3)),
        call("finish", summary="done"),
    )

    result = do(BRIEF, intelligence=model)

    first = result["actions"][0]
    assert first["tool"] == "(unreadable)"
    assert "no JSON object" in first["observation"]["error"]
    assert len(result["tracks"]) == 3
    # The correction was shown to the model, not swallowed.
    assert "no JSON object" in model.prompts[1]


def test_an_unknown_tool_name_is_handed_back_with_the_real_vocabulary(
    monkeypatch, signed_in
):
    connect(monkeypatch, Spotify({LIVE_QUERY: GRUNGE}))
    model = Scripted(
        call("spotify_search", query=LIVE_QUERY),
        call("search", query=LIVE_QUERY, type="track", limit=10),
        call("create_playlist", name="Flannel", tracks=uris(3)),
        call("finish", summary="done"),
    )

    result = do(BRIEF, intelligence=model)

    observation = result["actions"][0]["observation"]
    assert observation["error"] == "unknown_tool"
    for tool in TOOLS:
        assert tool in observation["message"]


def test_a_spotify_refusal_that_is_not_the_models_fault_reaches_the_caller(
    monkeypatch, signed_in
):
    """`rate_limited` is Spotify's answer, not a mistake the model can correct.

    A loop that recycled it as an observation would spend its whole budget
    re-provoking the same 429. Only ``usage`` and ``invalid_input`` recycle.
    """
    transport = use_fake_transport(
        monkeypatch,
        FakeTransport(
            [
                json_response(429, {"error": {"status": 429, "reason": "QUOTA_EXCEEDED"}}),
            ]
        ),
    )
    model = Scripted(call("search", query=LIVE_QUERY, type="track", limit=10))

    with pytest.raises(MusicDeckError) as raised:
        do(BRIEF, intelligence=model)

    assert raised.value.code == ErrorCode.QUOTA_EXCEEDED
    assert len(transport.requests) == 1


def test_a_bad_argument_from_the_model_is_recycled_as_an_observation(
    monkeypatch, signed_in
):
    """`usage` is the model's own mistake, so it gets to fix it."""
    connect(monkeypatch, Spotify({LIVE_QUERY: GRUNGE}))
    model = Scripted(
        call("search", query="   ", type="track", limit=10),
        call("search", query=LIVE_QUERY, type="track", limit=10),
        call("create_playlist", name="Flannel", tracks=uris(3)),
        call("finish", summary="done"),
    )

    result = do(BRIEF, intelligence=model)

    assert result["actions"][0]["observation"]["error"] == ErrorCode.USAGE
    assert len(result["tracks"]) == 3


# =========================================================================== #
# refusals.v1 Core 1 -- the vocabulary is closed, and `do` stays inside it
# =========================================================================== #
def test_every_code_do_can_emit_is_named_in_the_refusals_contract():
    """A static sweep of ``do.py`` against ``contracts/refusals.v1.md``.

    ``refusals.v1`` Core 1: "Every code the tool can emit is named here. A code
    in shipped output that this contract does not name is drift." This reads the
    contract rather than a copy of it, so a code added to ``do.py`` without a
    clause to stand on fails here.
    """
    contract = (REPO_ROOT / "contracts" / "refusals.v1.md").read_text(encoding="utf-8")
    source = (REPO_ROOT / "src" / "music_deck" / "verbs" / "do.py").read_text(
        encoding="utf-8"
    )

    emitted = {
        "usage",
        "partial_result",
        "internal_error",
        "spotify_error",
        "no_provider_configured",
    }
    for code in emitted:
        assert f"`{code}`" in contract, (
            f"do.py can emit {code!r} and contracts/refusals.v1.md does not name it"
        )

    # And nothing else: every MusicDeckError raised in do.py uses one of the
    # codes above, or `ErrorCode.<NAME>` which resolves to one of them.
    import re

    literals = set(re.findall(r'MusicDeckError\(\s*\n?\s*"([a-z_]+)"', source))
    assert literals <= emitted, literals


def test_a_partial_result_carries_the_completeness_its_clause_requires(
    monkeypatch, signed_in
):
    """``refusals.v1`` Core 5: requested, fetched, kept, added, under-fulfilled."""
    connect(monkeypatch, Spotify({DEAD_QUERY: []}))
    model = Scripted(
        call("search", query=DEAD_QUERY, type="track", limit=10),
        call("finish", summary="nothing"),
    )

    with pytest.raises(MusicDeckError) as raised:
        do(BRIEF, intelligence=model)

    completeness = raised.value.extra["completeness"]
    for field in ("requested", "fetched", "kept", "added", "under_fulfilled"):
        assert field in completeness, completeness
    assert completeness["requested"] == 10
    assert completeness["under_fulfilled"] == [0]


# =========================================================================== #
# Helpers
# =========================================================================== #
def _use_model(monkeypatch, model) -> None:
    """Put ``model`` behind the CLI's `do`, which takes no intelligence argument.

    ``cli.v1`` Core 7 keeps the CLI a thin adapter, so the seam is where the
    library resolves its substrate -- not an argument the binary can pass.
    """
    monkeypatch.setattr(do_module, "resolve", lambda _given: model)
