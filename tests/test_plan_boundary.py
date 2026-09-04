"""The one-way boundary, proven by a pair that actually discriminates.

Contracts served: ``boundary.v1`` Core 1 (`plan` performs no Spotify Web API
request), Core 2 (every prompt is the caller's own text plus music-deck's own
static prompt text, and nothing else), Core 3 (the transcript is an observable
output of `plan`).

The pair is the point. A check that only ever sees good input proves nothing
about bad input, so every claim here comes in two halves run through the *same*
check function and the *same* recording double:

* GOOD -- a plan built from the brief alone. The check passes.
* BAD  -- the same run with fetched track metadata appended to the prompt by a
  deliberately leaky assembler. The same check fails, naming ``boundary.v1
  Core 2``.

``test_the_pair_discriminates`` asserts both halves in one test, because two
passing tests in separate functions can both be vacuous in ways one test
comparing them cannot.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from music_deck import check_plan_transcript
from music_deck.intelligence import ModelRequest
from music_deck.prompt_boundary import CLAUSE, check_prompts, uncovered
from music_deck.prompts import plan_prompt_parts, static_prompt_texts
from music_deck.testing import Recording
from music_deck.verbs.plan import assemble_prompt, plan

BRIEF = "upbeat 90s guitar songs for a Saturday morning"

# What a Spotify search response looks like once it has been fetched: exactly
# the material boundary.v1 Core 2 forbids putting in front of a model.
FETCHED_TRACK_METADATA = """## Tracks I found on Spotify for this brief

[
  {"id": "3n3Ppam7vgaVa1iaRUc9Lp", "name": "Mr. Brightside",
   "uri": "spotify:track:3n3Ppam7vgaVa1iaRUc9Lp", "popularity": 84,
   "duration_ms": 222075,
   "external_urls": {"spotify": "https://open.spotify.com/track/3n3Ppam7vgaVa1iaRUc9Lp"}},
  {"id": "1301WleyT98MSxVHPZCA6M", "name": "Bittersweet Symphony",
   "uri": "spotify:track:1301WleyT98MSxVHPZCA6M", "popularity": 79,
   "duration_ms": 348893}
]"""


def leaky_assemble_prompt(brief: str, fetched: str = FETCHED_TRACK_METADATA) -> str:
    """What `plan` would look like if somebody "helpfully" fetched first.

    Not a doctored string: the same static parts, the same caller brief, in the
    same order, assembled the same way -- with one fetched-metadata block added.
    It is the plausible mistake, written out, so the check gets to catch the
    thing it exists to catch rather than a strawman.
    """
    parts = plan_prompt_parts()
    return "\n\n".join([parts["instructions"], parts["brief"], brief, fetched])


def record_good() -> Recording:
    """A real `plan` run. The double records each prompt as it is sent."""
    recorder = Recording()
    plan(BRIEF, intelligence=recorder)
    return recorder


def record_bad() -> Recording:
    """The same double, driven by the leaky assembler."""
    recorder = Recording()
    recorder.run(ModelRequest(prompt=leaky_assemble_prompt(BRIEF)))
    return recorder


# --------------------------------------------------------------------------- #
# Core 2 -- the discriminating pair
# --------------------------------------------------------------------------- #
def test_good_a_plan_built_from_the_brief_alone_passes():
    report = check_plan_transcript(record_good().prompts, brief=BRIEF)
    assert report.ok, report.describe()
    assert report.checked == 1
    assert CLAUSE in report.describe()


def test_bad_the_same_run_with_fetched_track_metadata_appended_fails():
    report = check_plan_transcript(record_bad().prompts, brief=BRIEF)
    assert not report.ok
    assert report.violations
    described = report.describe()
    assert CLAUSE in described
    assert "3n3Ppam7vgaVa1iaRUc9Lp" in described  # it names what leaked
    assert "a Spotify URI" in described


def test_the_pair_discriminates():
    """One test, both halves, one check function. The bar the kit asserts.

    boundary.v1's conformance kit: "GOOD = a plan built from the brief alone
    passes; BAD = the same run with fetched track metadata appended to the
    prompt fails."
    """
    allowed = [*static_prompt_texts(), BRIEF]

    good = check_prompts(record_good().prompts, allowed)
    bad = check_prompts(record_bad().prompts, allowed)

    assert good.ok is True, good.describe()
    assert bad.ok is False, "the BAD fixture did not fail -- the check is not real"
    assert CLAUSE in bad.describe()


def test_the_check_catches_a_leak_that_looks_like_nothing_in_particular():
    """Cover, not denylist: the leak nobody predicted fails too.

    A check that scanned for Spotify-shaped strings would pass this prompt. It
    still carries a sentence from neither allowed source, which is the whole of
    what Core 2 forbids.
    """
    innocuous = "For reference, the last playlist this user built was called Beach."
    recorder = Recording()
    recorder.run(ModelRequest(prompt=leaky_assemble_prompt(BRIEF, innocuous)))

    report = check_plan_transcript(recorder.prompts, brief=BRIEF)
    assert not report.ok
    assert "Beach" in report.describe()
    assert report.violations[0].looks_like == ()  # nothing recognisable, still a leak


def test_a_caller_who_pastes_spotify_content_into_context_is_not_a_leak():
    """Core 2 allows "the caller's own text" -- all of it, whatever it contains.

    boundary.v1's own reserved question ("whether a plan may carry a Spotify ID
    the caller typed in themselves") is open, so this test records the decided
    behaviour rather than leaving it to accident: text the caller supplied is
    covered, because the caller supplied it.
    """
    context = 'I already have spotify:track:3n3Ppam7vgaVa1iaRUc9Lp in there.'
    recorder = Recording()
    result = plan(BRIEF, context=context, intelligence=recorder)

    assert context in recorder.prompts[0]
    report = check_plan_transcript(result["transcript"], brief=BRIEF, context=context)
    assert report.ok, report.describe()

    # ...and the same transcript checked WITHOUT declaring that context fails,
    # which is what makes the pass above a statement about provenance rather
    # than about the characters themselves.
    assert not check_plan_transcript(result["transcript"], brief=BRIEF).ok


def test_every_prompt_is_covered_by_prompts_directory_plus_caller_arguments():
    """The acceptance criterion, stated as the check states it."""
    recorder = record_good()
    residue = uncovered(recorder.prompts[0], [*static_prompt_texts(), BRIEF])
    assert residue == "", f"unaccounted-for prompt text: {residue!r}"


def test_the_check_is_pure():
    """Same arguments, same answer -- no file, no environment, no clock."""
    prompts = record_good().prompts
    allowed = [*static_prompt_texts(), BRIEF]
    first = check_prompts(prompts, allowed)
    second = check_prompts(list(prompts), list(allowed))
    assert (first.ok, first.checked, len(first.violations)) == (
        second.ok,
        second.checked,
        len(second.violations),
    )
    assert check_prompts([], allowed).ok is True
    assert check_prompts(["anything at all"], []).ok is False


# --------------------------------------------------------------------------- #
# Core 3 -- the transcript is an observable output
# --------------------------------------------------------------------------- #
def test_the_result_carries_every_prompt_sent_verbatim():
    recorder = Recording()
    result = plan(BRIEF, intelligence=recorder)

    assert list(result) == ["plan", "transcript"]
    assert result["transcript"] == recorder.prompts  # verbatim, not a summary
    assert len(result["transcript"]) == 1
    assert BRIEF in result["transcript"][0]
    assert result["transcript"][0] == assemble_prompt(BRIEF)


def test_the_brief_reaches_the_plan_verbatim():
    """plan.v1 Core 2: `brief` is the caller's text, verbatim."""
    awkward = "  90s guitar — \"upbeat\", NOT sad\n(no remixes)  "
    recorder = Recording()
    result = plan(awkward, intelligence=recorder)

    assert result["plan"]["brief"] == awkward
    assert awkward in recorder.prompts[0]
    assert check_plan_transcript(result["transcript"], brief=awkward).ok


def test_the_plan_is_a_plan_v1_document():
    result = plan(BRIEF, intelligence=Recording())
    document = result["plan"]

    assert document["plan_format"] == 1
    assert set(document) >= {"plan_format", "brief", "target", "steps", "rules"}
    assert set(document["rules"]) == {
        "exclude_artists",
        "exclude_title_terms",
        "dedupe",
        "order",
    }
    assert document["steps"]
    for step in document["steps"]:
        assert set(step) == {"search", "type", "take", "why"}
        assert "spotify:" not in step["search"]


# --------------------------------------------------------------------------- #
# Core 1 -- no Spotify Web API request, no token needed
# --------------------------------------------------------------------------- #
@pytest.fixture
def network_tripwire(monkeypatch):
    """Every outbound attempt is recorded and refused. Returns the record."""
    attempts: list[object] = []

    class Guarded(socket.socket):
        def connect(self, address):  # noqa: D102
            attempts.append(address)
            raise AssertionError(f"boundary.v1 Core 1: a socket connect to {address!r}")

        def connect_ex(self, address):  # noqa: D102
            attempts.append(address)
            raise AssertionError(f"boundary.v1 Core 1: a socket connect to {address!r}")

    def guarded_getaddrinfo(host, *args, **kwargs):
        attempts.append(host)
        raise AssertionError(f"boundary.v1 Core 1: a DNS lookup for {host!r}")

    def guarded_create_connection(address, *args, **kwargs):
        attempts.append(address)
        raise AssertionError(f"boundary.v1 Core 1: a connection to {address!r}")

    monkeypatch.setattr(socket, "socket", Guarded)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    monkeypatch.setattr(socket, "create_connection", guarded_create_connection)
    return attempts


def test_plan_makes_no_network_request_at_all(network_tripwire, monkeypatch, tmp_path):
    """Core 1: zero requests to api.spotify.com -- here, zero requests anywhere.

    The stronger statement is the easier one to trust: rather than filtering
    attempts by host, nothing may leave at all, so a request to api.spotify.com
    cannot hide behind a redirect, a proxy, or a different hostname.
    """
    monkeypatch.setenv("MUSIC_DECK_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("MUSIC_DECK_CONFIG_DIR", str(tmp_path / "config"))

    result = plan(BRIEF, intelligence=Recording())

    assert result["plan"]["plan_format"] == 1
    assert network_tripwire == [], f"plan attempted network access: {network_tripwire}"


def test_plan_needs_no_token_and_no_client_id(monkeypatch, tmp_path):
    """Core 1 again, from the caller's side: nothing is signed in and it works."""
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("MUSIC_DECK_STATE_DIR", str(state))
    monkeypatch.setenv("MUSIC_DECK_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.delenv("MUSIC_DECK_CLIENT_ID", raising=False)

    result = plan(BRIEF, intelligence=Recording())

    assert result["plan"]["target"]["kind"] == "new"
    assert not list(state.iterdir()), "plan wrote into the state directory"


def test_the_plan_path_pulls_in_no_http_client(tmp_path):
    """A structural echo of Core 1: nothing that could speak to Spotify loads."""
    probe = (
        "import sys, json;"
        "from music_deck.verbs.plan import plan;"
        "from music_deck.testing import Recording;"
        "plan('a brief', intelligence=Recording());"
        "print(json.dumps([m for m in sys.modules if m.split('.')[0] in "
        "{'httpx','requests','urllib3','aiohttp','amplifier_agent_lib','anthropic','openai'}]))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []


# --------------------------------------------------------------------------- #
# The CLI adapter -- cli.v1 Core 7, the library is the tool
# --------------------------------------------------------------------------- #
def test_the_cli_hands_back_what_the_library_returned(monkeypatch, tmp_path):
    from music_deck import cli

    recorder = Recording()
    monkeypatch.setattr(
        cli, "run_plan", lambda brief, **kwargs: plan(brief, intelligence=recorder, **kwargs)
    )

    args = _namespace(brief=BRIEF, context=None, output=None)
    result = cli._handle_plan(args)

    assert result["transcript"] == recorder.prompts
    assert result["plan"]["brief"] == BRIEF


def test_output_writes_a_plan_apply_can_read(monkeypatch, tmp_path):
    from music_deck import cli

    monkeypatch.setattr(
        cli, "run_plan", lambda brief, **kwargs: plan(brief, intelligence=Recording(), **kwargs)
    )
    destination = tmp_path / "plan.json"

    result = cli._handle_plan(_namespace(brief=BRIEF, context=None, output=str(destination)))

    written = json.loads(destination.read_text(encoding="utf-8"))
    assert written == result["plan"]
    assert "transcript" not in written  # the file is a plan, not a result


def test_context_is_read_from_disk_and_passed_as_data(monkeypatch, tmp_path):
    from music_deck import cli

    payload = "Please avoid anything with a saxophone."
    source = tmp_path / "notes.txt"
    source.write_text(payload, encoding="utf-8")
    recorder = Recording()
    monkeypatch.setattr(
        cli, "run_plan", lambda brief, **kwargs: plan(brief, intelligence=recorder, **kwargs)
    )

    cli._handle_plan(_namespace(brief=BRIEF, context=str(source), output=None))

    assert payload in recorder.prompts[0]
    assert check_plan_transcript(recorder.prompts, brief=BRIEF, context=payload).ok


def test_an_unreadable_context_file_is_a_usage_refusal(monkeypatch, tmp_path):
    from music_deck import cli
    from music_deck.errors import EXIT_REFUSAL, ErrorCode, MusicDeckError

    with pytest.raises(MusicDeckError) as raised:
        cli._handle_plan(
            _namespace(brief=BRIEF, context=str(tmp_path / "absent.txt"), output=None)
        )
    assert raised.value.code == ErrorCode.USAGE
    assert raised.value.exit_code == EXIT_REFUSAL
    assert raised.value.remedy


def _namespace(**fields):
    import argparse

    return argparse.Namespace(**fields)
