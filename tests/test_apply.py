"""`apply` -- executing a plan as written, against a Spotify that never answers twice the same way by accident.

Contracts under test: ``plan.v1`` Core 6 (validated before a request is sent;
``invalid_plan`` naming the path), Core 7 (step order; 10-per-page search
pagination; rules after fetching; batches of at most 100; per-step
``completeness``; ``partial_result`` on under-fulfilment), Core 8
(determinism); ``cli.v1`` Core 4 (one document, every playlist object linked),
Core 5 (exit 2), Core 6 (``invalid_plan``, ``partial_result``); ``boundary.v1``
Core 7 (no withdrawn endpoint) and Core 8 (nothing cached to disk).

Why the fake answers instead of replaying
-----------------------------------------
The Spotify double below is a *responder*, not a queue of canned pages: it reads
each request's own ``limit`` and ``offset`` and serves that slice of a
catalogue, which is what a real search does. A queue of fixed pages would let
this file pass while ``apply`` asked for the wrong page size, the wrong offset,
or the wrong number of pages -- the exact three things ``plan.v1`` Core 7's
pagination clause is about. The honesty gate on this work item names the same
trap from the other side: "an apply test where the mock returns exactly ``take``
results so pagination and ``partial_result`` are never exercised". Every
pagination test here therefore asks for more than one page holds, and the
under-fulfilment tests hand back a catalogue that genuinely runs out.
"""

from __future__ import annotations

import json
from pathlib import Path

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
    PLAYLIST_ID,
    assert_every_item_is_linked,
    body_of,
    path_of,
    query_of,
    search_page,
    state_files,
)

from music_deck import cli
from music_deck.errors import EXIT_REFUSAL, EXIT_SUCCESS, ErrorCode
from music_deck.http import SEARCH_PAGE_CAP
from music_deck.verbs.playlists import ITEMS_PER_REQUEST

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "plans"

# The refusal table lives in test_plan_schema.py, which owns the validator. This
# file re-imports it rather than retyping it so the two can never disagree about
# what a given fixture is wrong about.
from test_plan_schema import REFUSALS  # noqa: E402


# --------------------------------------------------------------------------- #
# A catalogue, and a Spotify that serves it the way Spotify does
# --------------------------------------------------------------------------- #
def track(index: int, *, title: str | None = None, artist: str = "Aphex Twin") -> dict:
    """One search result, in Spotify's own shape and carrying no link.

    No ``external_urls`` on purpose: ``cli.v1`` Core 4 says music-deck supplies
    the link, and a fixture that supplied one would prove nothing about whether
    it does.
    """
    ident = f"{index:022d}"
    artist_id = f"{9_000_000 + abs(hash(artist)) % 1_000_000:022d}"
    return {
        "id": ident,
        "uri": f"spotify:track:{ident}",
        "name": title if title is not None else f"Track {index}",
        "type": "track",
        "duration_ms": 200_000,
        "artists": [
            {
                "id": artist_id,
                "uri": f"spotify:artist:{artist_id}",
                "name": artist,
                "type": "artist",
            }
        ],
    }


def catalogue(count: int, *, start: int = 0, **kwargs) -> list[dict]:
    return [track(start + n, **kwargs) for n in range(count)]


class Spotify:
    """A Spotify double that answers by path, and by the request's own paging.

    Queued into :class:`FakeTransport` many times over (it is stateless, so one
    instance answers every request); an unexpected path raises rather than
    returning something bland, so a verb that started calling a fourth endpoint
    fails here instead of passing quietly.
    """

    def __init__(
        self,
        by_query: dict[str, list[dict]],
        *,
        playlist_id: str = PLAYLIST_ID,
        created_name: str = "Saturday Morning Guitar",
    ) -> None:
        self.by_query = by_query
        self.playlist_id = playlist_id
        self.created_name = created_name

    def __call__(self, request):
        path = path_of(request.url)
        params = query_of(request.url)

        if path == "/search":
            found = self.by_query.get(params["q"])
            assert found is not None, (
                f"apply searched for {params['q']!r}, which this test never "
                f"stocked. Stocked: {sorted(self.by_query)}"
            )
            want = int(params["limit"])
            offset = int(params.get("offset", 0))
            assert want <= SEARCH_PAGE_CAP, (
                f"plan.v1 Core 7: search pages at {SEARCH_PAGE_CAP}; apply asked "
                f"for limit={want}"
            )
            page = found[offset : offset + want]
            return json_response(200, search_page(page, kind=params["type"]))

        if path == "/me/playlists":
            return json_response(
                201,
                {
                    "id": self.playlist_id,
                    "uri": f"spotify:playlist:{self.playlist_id}",
                    "name": self.created_name,
                    "type": "playlist",
                    "public": False,
                },
            )

        if path.startswith("/playlists/"):
            return json_response(200, {"snapshot_id": "snapshot-under-test"})

        raise AssertionError(f"apply sent an unexpected request: {request.method} {path}")


def connect(monkeypatch, double: Spotify, *, budget: int = 96) -> FakeTransport:
    """Point music-deck at ``double``. ``budget`` caps a runaway loop."""
    return use_fake_transport(monkeypatch, FakeTransport([double] * budget))


def requests_to(transport: FakeTransport, path: str) -> list:
    return [r for r in transport.requests if path_of(r.url) == path]


def searched_for(transport: FakeTransport) -> list[str]:
    """The ``q`` of every search sent, in the order sent."""
    return [query_of(r.url)["q"] for r in requests_to(transport, "/search")]


@pytest.fixture
def signed_in(monkeypatch, tmp_path):
    install_token(monkeypatch, tmp_path, token_document())
    return tmp_path


# --------------------------------------------------------------------------- #
# Plans, built here so a test can say what it is testing in one line
# --------------------------------------------------------------------------- #
def plan_document(
    *,
    steps,
    target=None,
    rules=None,
    brief: str = "upbeat 90s guitar songs for a Saturday morning",
) -> dict:
    return {
        "plan_format": 1,
        "brief": brief,
        "target": target or {"kind": "new", "name": "Saturday Morning Guitar"},
        "steps": steps,
        "rules": rules
        or {
            "exclude_artists": [],
            "exclude_title_terms": [],
            "dedupe": "none",
            "order": "as_planned",
        },
    }


def step(search: str, take: int, *, kind: str = "track") -> dict:
    return {"search": search, "type": kind, "take": take, "why": f"because {search}"}


def write_plan(tmp_path: Path, plan: dict, name: str = "plan.json") -> Path:
    destination = tmp_path / name
    destination.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    return destination


def run_apply(capsys, path) -> tuple[int, object, str]:
    return run_cli(capsys, "apply", str(path))


def raw_apply(capsys, path) -> tuple[int, str]:
    """``(exit code, stdout verbatim)`` -- for the byte-identical comparison."""
    code = cli.main(["apply", str(path)])
    return code, capsys.readouterr().out


# --------------------------------------------------------------------------- #
# plan.v1 Core 6 -- a bad plan is refused before a socket is opened
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", sorted(REFUSALS))
def test_a_bad_plan_refuses_with_invalid_plan_and_sends_no_request(
    name, signed_in, monkeypatch, capsys
):
    """The acceptance criterion, over every bad fixture on disk.

    The transport is queued **empty**: ``FakeTransport`` raises on any request it
    was not given a response for, so "no HTTP request is made" is proved twice
    over -- by the empty ``requests`` list, and by the fact that a single request
    would have failed the test with an error rather than a comparison.
    """
    transport = use_fake_transport(monkeypatch, FakeTransport())

    code, document, stderr = run_apply(capsys, FIXTURES / name)

    assert code == EXIT_REFUSAL, document
    assert document["error"]["code"] == ErrorCode.INVALID_PLAN
    assert document["error"]["path"] == REFUSALS[name]
    assert REFUSALS[name] in document["error"]["message"]
    assert document["error"]["remedy"].strip()
    assert stderr.strip()  # cli.v1 Core 4 -- diagnostics on stderr
    assert transport.requests == [], (
        f"a refused plan cost {len(transport.requests)} Spotify request(s): "
        f"{[path_of(r.url) for r in transport.requests]}"
    )


def test_a_bad_plan_leaves_nothing_on_disk(signed_in, monkeypatch, capsys):
    """boundary.v1 Core 8, on the path most likely to scribble something."""
    use_fake_transport(monkeypatch, FakeTransport())
    run_apply(capsys, FIXTURES / "bad-take-zero.json")
    assert state_files(signed_in / "state") == {"token.json"}


# --------------------------------------------------------------------------- #
# plan.v1 Core 7 -- step order and 10-per-page pagination
# --------------------------------------------------------------------------- #
def test_a_step_asking_for_25_pages_at_ten_until_it_has_them(
    signed_in, monkeypatch, capsys, tmp_path
):
    """The acceptance criterion: take 25 -> 3 search requests, 25 fetched.

    The catalogue holds 40, so running out is not what stops the paging -- the
    ``take`` is. That is the half a short catalogue would hide.
    """
    plan = plan_document(steps=[step("genre:alternative year:1990-1999", 25)])
    double = Spotify({"genre:alternative year:1990-1999": catalogue(40)})
    transport = connect(monkeypatch, double)

    code, document, _stderr = run_apply(capsys, write_plan(tmp_path, plan))

    assert code == EXIT_SUCCESS, document
    searches = requests_to(transport, "/search")
    assert len(searches) == 3, [r.url for r in searches]
    assert [int(query_of(r.url)["limit"]) for r in searches] == [10, 10, 5]
    assert [int(query_of(r.url)["offset"]) for r in searches] == [0, 10, 20]
    assert document["steps"][0]["completeness"] == {
        "requested": 25,
        "fetched": 25,
        "kept": 25,
    }


def test_every_step_runs_in_the_order_the_plan_lists_them(
    signed_in, monkeypatch, capsys, tmp_path
):
    """Core 7: "``apply`` executes the plan as written, in step order.\""""
    plan = plan_document(
        steps=[step("first", 12), step("second", 3), step("third", 20)]
    )
    double = Spotify(
        {
            "first": catalogue(20, start=0),
            "second": catalogue(20, start=100),
            "third": catalogue(20, start=200),
        }
    )
    transport = connect(monkeypatch, double)

    code, document, _stderr = run_apply(capsys, write_plan(tmp_path, plan))

    assert code == EXIT_SUCCESS, document
    # 12 -> pages of 10 + 2; 3 -> one page; 20 -> two pages of 10.
    assert searched_for(transport) == [
        "first",
        "first",
        "second",
        "third",
        "third",
    ]
    assert [report["search"] for report in document["steps"]] == [
        "first",
        "second",
        "third",
    ]
    # The playlist gets them in step order too, not merely fetched in it.
    added = body_of(requests_to(transport, f"/playlists/{PLAYLIST_ID}/items")[0])
    assert added["uris"][:12] == [f"spotify:track:{n:022d}" for n in range(12)]
    assert added["uris"][12:15] == [f"spotify:track:{n:022d}" for n in range(100, 103)]
    assert added["uris"][15:] == [f"spotify:track:{n:022d}" for n in range(200, 220)]


def test_a_step_stops_paging_when_spotify_runs_out(
    signed_in, monkeypatch, capsys, tmp_path
):
    """Core 7: "until ``take`` results **or exhaustion**"."""
    plan = plan_document(steps=[step("obscure", 50)])
    double = Spotify({"obscure": catalogue(14)})
    transport = connect(monkeypatch, double)

    code, document, _stderr = run_apply(capsys, write_plan(tmp_path, plan))

    # Two pages: 10 items, then 4 -- short of the 10 asked for, so it stops.
    assert len(requests_to(transport, "/search")) == 2
    assert document["error"]["completeness"]["steps"][0]["completeness"] == {
        "requested": 50,
        "fetched": 14,
        "kept": 14,
    }
    assert code == EXIT_REFUSAL  # under-fulfilled -- see the partial_result tests


def test_an_album_step_refuses_before_any_read_or_write(signed_in, monkeypatch, capsys, tmp_path):
    """Album expansion is not built, so it cannot first create a target."""
    plan = plan_document(
        steps=[step("some tracks", 3), step("some albums", 2, kind="album")]
    )
    double = Spotify({"some tracks": catalogue(5), "some albums": catalogue(5, start=50)})
    transport = connect(monkeypatch, double)

    code, document, _stderr = run_apply(capsys, write_plan(tmp_path, plan))

    assert code == EXIT_REFUSAL
    assert document["error"]["code"] == ErrorCode.INVALID_PLAN
    assert document["error"]["path"] == "$.steps[1].type"
    assert transport.requests == []


def test_a_wrong_kind_existing_target_refuses_before_any_search_or_write(
    signed_in, monkeypatch, capsys, tmp_path
):
    plan = plan_document(
        steps=[step("some tracks", 1)],
        target={"kind": "existing", "playlist_id": "spotify:album:0000000000000000000000"},
    )
    transport = connect(monkeypatch, Spotify({"some tracks": catalogue(1)}))

    code, document, _stderr = run_apply(capsys, write_plan(tmp_path, plan))

    assert code == EXIT_REFUSAL
    assert document["error"]["code"] == ErrorCode.INVALID_PLAN
    assert document["error"]["path"] == "$.target.playlist_id"
    assert transport.requests == []


# --------------------------------------------------------------------------- #
# plan.v1 Core 7 -- batches of at most 100
# --------------------------------------------------------------------------- #
def test_250_surviving_items_are_added_in_three_requests_of_at_most_a_hundred(
    signed_in, monkeypatch, capsys, tmp_path
):
    """The acceptance criterion, verbatim: 250 items -> 3 adds of <= 100."""
    plan = plan_document(steps=[step(f"step-{n}", 50) for n in range(5)])
    double = Spotify(
        {f"step-{n}": catalogue(50, start=n * 1000) for n in range(5)}
    )
    transport = connect(monkeypatch, double, budget=64)

    code, document, _stderr = run_apply(capsys, write_plan(tmp_path, plan))

    assert code == EXIT_SUCCESS, document
    assert document["completeness"]["kept"] == 250
    assert document["completeness"]["added"] == 250

    adds = requests_to(transport, f"/playlists/{PLAYLIST_ID}/items")
    assert len(adds) == 3
    sizes = [len(body_of(request)["uris"]) for request in adds]
    assert sizes == [100, 100, 50]
    assert all(size <= ITEMS_PER_REQUEST for size in sizes)
    assert document["add_requests"] == 3
    assert document["items_per_request"] == ITEMS_PER_REQUEST

    # And in order across the batch boundary, not merely 250 of the right items.
    sent_uris = [uri for request in adds for uri in body_of(request)["uris"]]
    assert sent_uris == [item["uri"] for item in document["items"]]


# --------------------------------------------------------------------------- #
# plan.v1 Core 7 -- rules apply after fetching
# --------------------------------------------------------------------------- #
def test_an_excluded_title_term_drops_a_fetched_item(
    signed_in, monkeypatch, capsys, tmp_path
):
    """The acceptance criterion: with "live" excluded, "Song (Live)" is not kept.

    Case-insensitive substring: the fixture's title says ``(Live)`` and the rule
    says ``live``.
    """
    found = [
        track(1, title="Song"),
        track(2, title="Song (Live)"),
        track(3, title="Another"),
        track(4, title="LIVE at Wembley"),
    ]
    plan = plan_document(
        steps=[step("anything", 4)],
        rules={
            "exclude_artists": [],
            "exclude_title_terms": ["live"],
            "dedupe": "none",
            "order": "as_planned",
        },
    )
    connect(monkeypatch, Spotify({"anything": found}))

    code, document, _stderr = run_apply(capsys, write_plan(tmp_path, plan))

    envelope = document["error"]
    kept = [item["uri"] for item in envelope["result"]["items"]]
    assert kept == [f"spotify:track:{1:022d}", f"spotify:track:{3:022d}"]
    assert envelope["result"]["steps"][0]["completeness"] == {
        "requested": 4,
        "fetched": 4,
        "kept": 2,
    }
    # Fetched all four and *then* filtered -- the rule is not folded into the query.
    assert code == EXIT_REFUSAL  # 2 kept of 4 requested is under-fulfilment


def test_an_excluded_artist_drops_a_fetched_item(
    signed_in, monkeypatch, capsys, tmp_path
):
    found = [
        track(1, artist="Radiohead"),
        track(2, artist="Blur"),
        track(3, artist="RADIOHEAD"),
    ]
    plan = plan_document(
        steps=[step("anything", 3)],
        rules={
            "exclude_artists": ["radiohead"],
            "exclude_title_terms": [],
            "dedupe": "none",
            "order": "as_planned",
        },
    )
    connect(monkeypatch, Spotify({"anything": found}))

    _code, document, _stderr = run_apply(capsys, write_plan(tmp_path, plan))

    kept = [item["uri"] for item in document["error"]["result"]["items"]]
    assert kept == [f"spotify:track:{2:022d}"]


def test_an_excluded_artist_is_a_whole_name_not_a_fragment(
    signed_in, monkeypatch, capsys, tmp_path
):
    """Excluding "Air" must not also exclude "Air Supply".

    ``exclude_title_terms`` is a substring rule and ``exclude_artists`` is not;
    a single implementation shared between them would silently over-exclude, and
    a plan's author would have no way to see it happen.
    """
    found = [track(1, artist="Air"), track(2, artist="Air Supply")]
    plan = plan_document(
        steps=[step("anything", 2)],
        rules={
            "exclude_artists": ["Air"],
            "exclude_title_terms": [],
            "dedupe": "none",
            "order": "as_planned",
        },
    )
    connect(monkeypatch, Spotify({"anything": found}))

    _code, document, _stderr = run_apply(capsys, write_plan(tmp_path, plan))

    kept = [item["uri"] for item in document["error"]["result"]["items"]]
    assert kept == [f"spotify:track:{2:022d}"]


def test_dedupe_by_track_id_spans_steps(signed_in, monkeypatch, capsys, tmp_path):
    """Two steps that both find the same track put it in the playlist once.

    Per-step de-duplication would pass a naive test and still let the duplicate
    through, which is the one outcome a caller asking for dedupe is asking to
    avoid.
    """
    shared = catalogue(3)
    plan = plan_document(
        steps=[step("first", 3), step("second", 3)],
        rules={
            "exclude_artists": [],
            "exclude_title_terms": [],
            "dedupe": "by_track_id",
            "order": "as_planned",
        },
    )
    connect(monkeypatch, Spotify({"first": shared, "second": shared}))

    _code, document, _stderr = run_apply(capsys, write_plan(tmp_path, plan))

    result = document["error"]["result"]
    assert [report["completeness"] for report in result["steps"]] == [
        {"requested": 3, "fetched": 3, "kept": 3},
        {"requested": 3, "fetched": 3, "kept": 0},
    ]
    assert len(result["items"]) == 3


def test_dedupe_by_title_and_primary_artist_catches_a_different_id(
    signed_in, monkeypatch, capsys, tmp_path
):
    """The re-release case: same song, same artist, different Spotify id."""
    found = [
        track(1, title="Xtal", artist="Aphex Twin"),
        track(2, title="XTAL", artist="Aphex Twin"),
        track(3, title="Xtal", artist="Someone Else"),
    ]
    plan = plan_document(
        steps=[step("anything", 3)],
        rules={
            "exclude_artists": [],
            "exclude_title_terms": [],
            "dedupe": "by_title_and_primary_artist",
            "order": "as_planned",
        },
    )
    connect(monkeypatch, Spotify({"anything": found}))

    _code, document, _stderr = run_apply(capsys, write_plan(tmp_path, plan))

    kept = [item["uri"] for item in document["error"]["result"]["items"]]
    assert kept == [f"spotify:track:{1:022d}", f"spotify:track:{3:022d}"]


def test_dedupe_none_keeps_the_duplicate(signed_in, monkeypatch, capsys, tmp_path):
    """The rule has to be capable of being off, or it is not a rule."""
    shared = catalogue(2)
    plan = plan_document(steps=[step("first", 2), step("second", 2)])
    connect(monkeypatch, Spotify({"first": shared, "second": shared}))

    code, document, _stderr = run_apply(capsys, write_plan(tmp_path, plan))

    assert code == EXIT_SUCCESS, document
    assert len(document["items"]) == 4


# --------------------------------------------------------------------------- #
# cli.v1 Core 6 -- partial_result, never a silent success
# --------------------------------------------------------------------------- #
def test_a_step_that_fetches_four_of_ten_reports_partial_result(
    signed_in, monkeypatch, capsys, tmp_path
):
    """The acceptance criterion, verbatim.

    ``{requested: 10, fetched: 4, kept: <= 4}`` and the run reports
    ``partial_result`` -- exit 2, carrying the completeness block ``cli.v1``
    Core 6 requires.
    """
    plan = plan_document(steps=[step("thin", 10)])
    connect(monkeypatch, Spotify({"thin": catalogue(4)}))

    code, document, stderr = run_apply(capsys, write_plan(tmp_path, plan))

    assert code == EXIT_REFUSAL
    envelope = document["error"]
    assert envelope["code"] == ErrorCode.PARTIAL_RESULT

    block = envelope["completeness"]
    assert block["steps"][0]["completeness"]["requested"] == 10
    assert block["steps"][0]["completeness"]["fetched"] == 4
    assert block["steps"][0]["completeness"]["kept"] <= 4
    assert block["under_fulfilled"] == [0]
    assert envelope["message"].strip() and envelope["remedy"].strip()
    assert stderr.strip()

    # "never a silent success": the work that *did* land is reported, not lost.
    assert envelope["result"]["completeness"]["added"] == 4
    assert len(envelope["result"]["items"]) == 4


def test_the_items_that_did_land_were_really_added(
    signed_in, monkeypatch, capsys, tmp_path
):
    """A partial_result is a partial *completion*, not an abandoned run."""
    plan = plan_document(steps=[step("thin", 10)])
    transport = connect(monkeypatch, Spotify({"thin": catalogue(4)}))

    run_apply(capsys, write_plan(tmp_path, plan))

    adds = requests_to(transport, f"/playlists/{PLAYLIST_ID}/items")
    assert len(adds) == 1
    assert len(body_of(adds[0])["uris"]) == 4


def test_a_fully_fulfilled_plan_is_a_plain_success(
    signed_in, monkeypatch, capsys, tmp_path
):
    """The other side of the gate: a plan that filled up must exit 0.

    Without this, a partial_result that fired on every run would still pass
    every test above.
    """
    plan = plan_document(steps=[step("plenty", 25)])
    connect(monkeypatch, Spotify({"plenty": catalogue(60)}))

    code, document, _stderr = run_apply(capsys, write_plan(tmp_path, plan))

    assert code == EXIT_SUCCESS, document
    assert "error" not in document
    assert document["completeness"] == {
        "requested": 25,
        "fetched": 25,
        "kept": 25,
        "added": 25,
        "under_fulfilled": [],
    }


def test_rules_that_empty_a_step_are_under_fulfilment_not_a_clean_run(
    signed_in, monkeypatch, capsys, tmp_path
):
    """A playlist of nothing must not exit 0 with an empty items list.

    Nothing is added -- so nothing was sent to ``/items`` at all -- and the
    refusal is what tells the caller their rules ate the whole step.
    """
    plan = plan_document(
        steps=[step("anything", 3)],
        rules={
            "exclude_artists": [],
            "exclude_title_terms": ["track"],
            "dedupe": "none",
            "order": "as_planned",
        },
    )
    transport = connect(monkeypatch, Spotify({"anything": catalogue(3)}))

    code, document, _stderr = run_apply(capsys, write_plan(tmp_path, plan))

    assert code == EXIT_REFUSAL
    assert document["error"]["code"] == ErrorCode.PARTIAL_RESULT
    assert document["error"]["completeness"]["kept"] == 0
    assert requests_to(transport, f"/playlists/{PLAYLIST_ID}/items") == []


# --------------------------------------------------------------------------- #
# plan.v1 Core 8 -- determinism, except order: shuffle
# --------------------------------------------------------------------------- #
def test_the_same_plan_twice_against_the_same_spotify_is_byte_identical(
    signed_in, monkeypatch, capsys, tmp_path
):
    """The acceptance criterion, compared as **bytes** rather than as objects.

    Two documents that differ only in key order parse equal and serialise
    differently; ``plan.v1`` Core 8 promises the same *result*, and stdout is
    what a caller actually diffs.
    """
    plan = plan_document(
        steps=[step("first", 12), step("second", 25)],
        rules={
            "exclude_artists": ["Nobody"],
            "exclude_title_terms": ["nothing"],
            "dedupe": "by_track_id",
            "order": "as_planned",
        },
    )
    path = write_plan(tmp_path, plan)
    stock = {"first": catalogue(30), "second": catalogue(30, start=500)}

    connect(monkeypatch, Spotify(stock))
    first_code, first_out = raw_apply(capsys, path)

    connect(monkeypatch, Spotify(stock))
    second_code, second_out = raw_apply(capsys, path)

    assert (first_code, second_code) == (EXIT_SUCCESS, EXIT_SUCCESS), first_out
    assert first_out == second_out
    assert first_out.strip()


def test_a_shuffled_plan_still_adds_exactly_the_same_items(
    signed_in, monkeypatch, capsys, tmp_path
):
    """Core 8 excepts the *order*, and nothing else.

    Asserting that two shuffles differ would be a coin flip; asserting that the
    membership never does is the invariant that actually holds.
    """
    plan = plan_document(
        steps=[step("wide", 30)],
        rules={
            "exclude_artists": [],
            "exclude_title_terms": [],
            "dedupe": "none",
            "order": "shuffle",
        },
    )
    path = write_plan(tmp_path, plan)
    stock = {"wide": catalogue(40)}

    seen = []
    for _ in range(3):
        connect(monkeypatch, Spotify(stock))
        code, document, _stderr = run_apply(capsys, path)
        assert code == EXIT_SUCCESS, document
        assert document["order"] == "shuffle"
        seen.append(sorted(item["uri"] for item in document["items"]))

    assert seen[0] == seen[1] == seen[2]
    assert len(seen[0]) == 30


# --------------------------------------------------------------------------- #
# plan.v1 Core 7 -- the target is created or extended
# --------------------------------------------------------------------------- #
def test_an_existing_target_is_never_created(
    signed_in, monkeypatch, capsys, tmp_path
):
    """The acceptance criterion: kind "existing" makes no POST /me/playlists."""
    plan = plan_document(
        steps=[step("anything", 5)],
        target={"kind": "existing", "playlist_id": PLAYLIST_ID},
    )
    transport = connect(monkeypatch, Spotify({"anything": catalogue(10)}))

    code, document, _stderr = run_apply(capsys, write_plan(tmp_path, plan))

    assert code == EXIT_SUCCESS, document
    assert requests_to(transport, "/me/playlists") == []
    assert [path_of(r.url) for r in transport.requests] == [
        "/search",
        f"/playlists/{PLAYLIST_ID}/items",
    ]
    assert document["playlist"]["id"] == PLAYLIST_ID
    assert document["playlist"]["created"] is False


def test_a_new_target_is_created_once_with_its_name_and_description(
    signed_in, monkeypatch, capsys, tmp_path
):
    plan = plan_document(
        steps=[step("anything", 5)],
        target={
            "kind": "new",
            "name": "Saturday Morning Guitar",
            "description": "Upbeat 90s guitar songs",
        },
    )
    transport = connect(monkeypatch, Spotify({"anything": catalogue(10)}))

    code, document, _stderr = run_apply(capsys, write_plan(tmp_path, plan))

    assert code == EXIT_SUCCESS, document
    created = requests_to(transport, "/me/playlists")
    assert len(created) == 1
    assert created[0].method == "POST"
    body = body_of(created[0])
    assert body["name"] == "Saturday Morning Guitar"
    assert body["description"] == "Upbeat 90s guitar songs"
    assert body["public"] is False  # an agent does not publish to a profile
    assert document["playlist"]["created"] is True
    assert document["playlist"]["name"] == "Saturday Morning Guitar"


def test_the_playlist_is_created_before_anything_is_added(
    signed_in, monkeypatch, capsys, tmp_path
):
    plan = plan_document(steps=[step("anything", 5)])
    transport = connect(monkeypatch, Spotify({"anything": catalogue(10)}))

    run_apply(capsys, write_plan(tmp_path, plan))

    paths = [path_of(r.url) for r in transport.requests]
    assert paths.index("/me/playlists") < paths.index(
        f"/playlists/{PLAYLIST_ID}/items"
    )


# --------------------------------------------------------------------------- #
# cli.v1 Core 4 -- one document, and every playlist object carries its link
# --------------------------------------------------------------------------- #
def test_every_emitted_playlist_object_carries_its_own_link(
    signed_in, monkeypatch, capsys, tmp_path
):
    """The acceptance criterion. Checked over the whole document, at any depth."""
    plan = plan_document(steps=[step("anything", 5)])
    connect(monkeypatch, Spotify({"anything": catalogue(10)}))

    code, document, _stderr = run_apply(capsys, write_plan(tmp_path, plan))

    assert code == EXIT_SUCCESS, document
    assert document["playlist"]["external_urls"]["spotify"] == (
        f"https://open.spotify.com/playlist/{PLAYLIST_ID}"
    )
    # 1 playlist + 5 added items, each of which must be linked too.
    assert assert_every_item_is_linked(document, at_least=6) == 6


def test_a_partial_result_envelope_is_linked_too(
    signed_in, monkeypatch, capsys, tmp_path
):
    """The refusal path emits items as well, so Core 4 has to hold there."""
    plan = plan_document(steps=[step("thin", 10)])
    connect(monkeypatch, Spotify({"thin": catalogue(4)}))

    _code, document, _stderr = run_apply(capsys, write_plan(tmp_path, plan))

    assert_every_item_is_linked(document, at_least=5)


def test_apply_writes_no_spotify_content_to_the_state_directory(
    signed_in, monkeypatch, capsys, tmp_path
):
    """boundary.v1 Core 8, over a full successful run."""
    plan = plan_document(steps=[step("anything", 5)])
    connect(monkeypatch, Spotify({"anything": catalogue(10)}))

    run_apply(capsys, write_plan(tmp_path, plan))

    assert state_files(signed_in / "state") == {"token.json"}


# --------------------------------------------------------------------------- #
# The invocation surface
# --------------------------------------------------------------------------- #
def test_apply_is_no_longer_an_unbuilt_verb(signed_in, monkeypatch, capsys, tmp_path):
    plan = plan_document(steps=[step("anything", 5)])
    connect(monkeypatch, Spotify({"anything": catalogue(10)}))

    code, document, _stderr = run_apply(capsys, write_plan(tmp_path, plan))

    assert code == EXIT_SUCCESS
    assert document.get("plan_format") == 1


def test_the_plan_may_be_named_with_the_flag_or_as_the_argument(
    signed_in, monkeypatch, capsys, tmp_path
):
    """`music-deck plan --output` has told callers ``--plan`` since MD-1.

    Both spellings have to reach the same place, or a documented invocation
    stops working the day this lane lands.
    """
    plan = plan_document(steps=[step("anything", 5)])
    path = write_plan(tmp_path, plan)

    connect(monkeypatch, Spotify({"anything": catalogue(10)}))
    positional_code, positional, _e = run_cli(capsys, "apply", str(path))

    connect(monkeypatch, Spotify({"anything": catalogue(10)}))
    flag_code, flagged, _e = run_cli(capsys, "apply", "--plan", str(path))

    assert positional_code == flag_code == EXIT_SUCCESS
    assert positional == flagged


def test_naming_no_plan_is_a_usage_refusal(signed_in, monkeypatch, capsys):
    use_fake_transport(monkeypatch, FakeTransport())
    code, document, _stderr = run_cli(capsys, "apply")
    assert code == EXIT_REFUSAL
    assert document["error"]["code"] == ErrorCode.USAGE


def test_naming_two_different_plans_is_a_usage_refusal(
    signed_in, monkeypatch, capsys, tmp_path
):
    """Silently preferring one of them would apply a plan nobody asked for."""
    use_fake_transport(monkeypatch, FakeTransport())
    code, document, _stderr = run_cli(
        capsys, "apply", str(tmp_path / "a.json"), "--plan", str(tmp_path / "b.json")
    )
    assert code == EXIT_REFUSAL
    assert document["error"]["code"] == ErrorCode.USAGE


def test_a_missing_plan_file_is_a_usage_refusal(signed_in, monkeypatch, capsys, tmp_path):
    use_fake_transport(monkeypatch, FakeTransport())
    code, document, _stderr = run_apply(capsys, tmp_path / "no-such-plan.json")
    assert code == EXIT_REFUSAL
    assert document["error"]["code"] == ErrorCode.USAGE


def test_a_file_that_is_not_json_is_an_invalid_plan(
    signed_in, monkeypatch, capsys, tmp_path
):
    """Pointing at the right file and finding rubbish is a plan problem."""
    use_fake_transport(monkeypatch, FakeTransport())
    broken = tmp_path / "broken.json"
    broken.write_text("{ this is not json", encoding="utf-8")

    code, document, _stderr = run_apply(capsys, broken)

    assert code == EXIT_REFUSAL
    assert document["error"]["code"] == ErrorCode.INVALID_PLAN
    assert document["error"]["path"] == "$"


def test_apply_needs_no_model_provider(monkeypatch, tmp_path, signed_in, capsys):
    """cli.v1 Core 2: `apply` is deterministic -- it must run with none.

    Scrubbing the environment is not enough on its own; the stronger claim is
    that nothing in ``apply``'s import graph reaches a provider at all, which
    ``tests/test_plan_refusal.py`` proves for the whole CLI. This is the
    verb-level half: with every provider variable removed, `apply` still works.
    """
    for name in (
        "MUSIC_DECK_PROVIDER",
        "MUSIC_DECK_MODEL",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "AZURE_OPENAI_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    plan = plan_document(steps=[step("anything", 5)])
    connect(monkeypatch, Spotify({"anything": catalogue(10)}))

    code, document, _stderr = run_apply(capsys, write_plan(tmp_path, plan))
    assert code == EXIT_SUCCESS, document


# --------------------------------------------------------------------------- #
# The good fixtures, end to end
# --------------------------------------------------------------------------- #
def test_the_worked_example_fixture_runs_end_to_end(
    signed_in, monkeypatch, capsys
):
    """`tests/fixtures/plans/good-new-playlist.json`, applied for real.

    The same file ``test_plan_schema.py`` accepts, driven through the binary
    against a stocked Spotify -- which is what makes the fixture directory a
    shared artefact rather than two unrelated piles of JSON.
    """
    plan = json.loads((FIXTURES / "good-new-playlist.json").read_text())
    stock = {
        plan["steps"][0]["search"]: catalogue(40, start=0),
        plan["steps"][1]["search"]: catalogue(40, start=1000),
    }
    transport = connect(monkeypatch, Spotify(stock))

    code, document, _stderr = run_apply(capsys, FIXTURES / "good-new-playlist.json")

    assert code == EXIT_SUCCESS, document
    assert document["brief"] == plan["brief"]
    assert document["completeness"]["kept"] == 35  # take 25 + take 10
    assert len(requests_to(transport, "/search")) == 4  # 3 pages + 1 page
    assert len(requests_to(transport, f"/playlists/{PLAYLIST_ID}/items")) == 1
