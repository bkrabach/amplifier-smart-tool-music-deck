"""No credential in a prompt, proven by a pair that actually discriminates.

Contracts served: ``boundary.v1`` Core 1 (a model **may** read what Spotify
returns -- so Spotify content in a prompt passes here, deliberately), Core 2 (no
credential ever enters a prompt: not the access token, the refresh token, or the
client ID), Core 3 (the transcript is an observable output of `plan`, and every
prompt the substrate captured appears in it verbatim).

The pair is the point. A check that only ever sees good input proves nothing
about bad input, so every claim here comes in two halves run through the *same*
check function and the *same* recording double:

* GOOD -- a plan built from the brief alone, and a prompt carrying fetched
  Spotify search results. Both pass. Content is allowed now.
* BAD  -- the same run with a credential spliced into the prompt. The same check
  fails, naming ``boundary.v1 Core 2`` and naming *which* credential.

``test_the_pair_discriminates`` asserts both halves in one test, because two
passing tests in separate functions can both be vacuous in ways one test
comparing them cannot. ``test_each_of_the_three_credentials_fails_on_its_own``
does the three separately, because a BAD half that only ever catches one of
three is a check with two holes in it.

What changed on 2026-09-06: this file used to prove the *one-way boundary* --
that nothing Spotify returned could reach a prompt, checked by covering each
prompt with its allowed sources. That clause was removed by ratification
(``contracts/boundary.v1.md``'s Changelog). The tests below prove the inverted
rule, and the old GOOD/BAD fixtures have swapped sides.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys

import pytest

from music_deck import BoundaryReport, check_plan_transcript, check_prompts
from music_deck.intelligence import ModelRequest
from music_deck.prompt_boundary import (
    ACCESS_TOKEN,
    BY_SHAPE,
    BY_VALUE,
    CLAUSE,
    CLIENT_ID,
    REFRESH_TOKEN,
    Credential,
    credentials_in,
    machine_credentials,
)
from music_deck.testing import (
    FAKE_ACCESS_TOKEN,
    FAKE_CLIENT_ID,
    FAKE_REFRESH_TOKEN,
    SPOTIFY_SEARCH_RESULTS,
    Recording,
    credential_leak_prompt,
)
from music_deck.verbs.plan import assemble_prompt, plan

BRIEF = "upbeat 90s guitar songs for a Saturday morning"

# The three credentials, as a caller hands them to the check.
FAKE_CREDENTIALS = {
    ACCESS_TOKEN: FAKE_ACCESS_TOKEN,
    REFRESH_TOKEN: FAKE_REFRESH_TOKEN,
    CLIENT_ID: FAKE_CLIENT_ID,
}


def record_good() -> Recording:
    """A real `plan` run. The double records each prompt as it is sent."""
    recorder = Recording()
    plan(BRIEF, intelligence=recorder)
    return recorder


def record_bad(credential: str = FAKE_ACCESS_TOKEN) -> Recording:
    """The same double, driven by the credential-leaking assembler."""
    recorder = Recording()
    recorder.run(ModelRequest(prompt=credential_leak_prompt(BRIEF, credential)))
    return recorder


# --------------------------------------------------------------------------- #
# Core 2 -- the discriminating pair
# --------------------------------------------------------------------------- #
def test_good_a_plan_built_from_the_brief_alone_passes():
    report = check_plan_transcript(record_good().prompts, credentials=FAKE_CREDENTIALS)
    assert report.ok, report.describe()
    assert report.checked == 1
    assert report.known == 3  # it really was looking for all three
    assert CLAUSE in report.describe()


def test_good_a_prompt_carrying_spotify_search_results_passes():
    """boundary.v1 Core 1: a model may read what Spotify returns.

    This is the fixture that used to be the BAD half. Ids, URIs, links,
    popularity, duration -- all of it in front of a model, and the check says
    kept, because the removed clause is removed.
    """
    prompt = assemble_prompt(BRIEF) + "\n\n" + SPOTIFY_SEARCH_RESULTS
    recorder = Recording()
    recorder.run(ModelRequest(prompt=prompt))

    report = check_plan_transcript(recorder.prompts, credentials=FAKE_CREDENTIALS)

    assert "spotify:track:" in recorder.prompts[0]
    assert "open.spotify.com" in recorder.prompts[0]
    assert report.ok, report.describe()


def test_bad_the_same_run_with_the_access_token_spliced_in_fails():
    report = check_plan_transcript(record_bad().prompts, credentials=FAKE_CREDENTIALS)
    assert not report.ok
    assert report.violations
    described = report.describe()
    assert CLAUSE in described
    assert ACCESS_TOKEN in described  # it names which credential


def test_each_of_the_three_credentials_fails_on_its_own():
    """Core 2 names three. All three must fail, each naming itself."""
    for kind, value in FAKE_CREDENTIALS.items():
        report = check_plan_transcript(
            record_bad(value).prompts, credentials=FAKE_CREDENTIALS
        )
        described = report.describe()
        assert not report.ok, f"{kind} did not fail the check: {described}"
        assert kind in described, f"the failure did not name {kind}: {described}"
        assert CLAUSE in described


def test_the_pair_discriminates():
    """One test, both halves, one check function. The bar the kit asserts.

    boundary.v1's conformance kit: "A recording model substrate captures every
    prompt sent: GOOD = no credential appears in any prompt; BAD = a run with
    the access token spliced into the prompt fails."
    """
    good = check_prompts(record_good().prompts, FAKE_CREDENTIALS)
    bad = check_prompts(record_bad().prompts, FAKE_CREDENTIALS)

    assert good.ok is True, good.describe()
    assert bad.ok is False, "the BAD fixture did not fail -- the check is not real"
    assert CLAUSE in bad.describe()
    assert ACCESS_TOKEN in bad.describe()


def test_the_shape_net_catches_a_credential_the_check_was_never_given():
    """The hole a value-only check would leave: nothing to look for.

    On a machine with nothing signed in the exact-value net is empty. A check
    that then passed every prompt would be reporting a pass it never earned, so
    the shape net runs regardless.
    """
    report = check_prompts(record_bad().prompts)  # no credentials at all

    assert report.known == 0
    assert not report.ok, report.describe()
    assert ACCESS_TOKEN in report.describe()
    assert BY_SHAPE in report.describe()


def test_the_value_net_catches_a_credential_with_no_recognisable_shape():
    """And the hole the shape net would leave: a credential that looks like prose."""
    odd = "correct-horse-battery-staple-not-token-shaped"
    prompt = assemble_prompt(BRIEF) + f"\n\nthe client id is {odd}"

    assert check_prompts([prompt]).ok, "the shape net should not see this at all"

    report = check_prompts([prompt], {CLIENT_ID: odd})
    assert not report.ok
    assert CLIENT_ID in report.describe()
    assert BY_VALUE in report.describe()


def test_a_failure_never_prints_the_credential_it_caught():
    """A check whose message leaks the credential is a worse leak than the one
    it reported."""
    described = check_prompts(record_bad().prompts, FAKE_CREDENTIALS).describe()

    for value in FAKE_CREDENTIALS.values():
        assert value not in described
    # not even a recognisable prefix of it
    assert FAKE_ACCESS_TOKEN[:16] not in described
    assert "character" in described  # it says where, not what


def test_the_old_allowed_set_call_shape_is_refused_loudly():
    """A caller written against the removed cover-based check gets told so.

    Silently treating the old `allowed` list of source texts as credentials
    would turn a boundary check into a random string search that passes.
    """
    with pytest.raises(TypeError) as raised:
        check_prompts(record_bad().prompts, ["some allowed source text"])
    assert "credentials" in str(raised.value).lower()


def test_the_check_is_pure():
    """Same arguments, same answer -- no file, no environment, no clock."""
    prompts = record_good().prompts
    first = check_prompts(prompts, FAKE_CREDENTIALS)
    second = check_prompts(list(prompts), dict(FAKE_CREDENTIALS))
    assert (first.ok, first.checked, len(first.violations)) == (
        second.ok,
        second.checked,
        len(second.violations),
    )


def test_an_empty_transcript_is_not_reported_as_a_pass():
    """AGENTS.md: a check that cannot run reports "can't check", never a pass."""
    report = check_prompts([], FAKE_CREDENTIALS)
    assert report.checked == 0
    assert "not checked" in report.describe()
    assert "nothing was proven" in report.describe()


def test_a_pass_against_no_known_credential_says_so():
    """A pass over an empty credential set is a weaker claim, and reads as one."""
    described = check_prompts(record_good().prompts).describe()
    assert "No credential value was supplied" in described


def test_credentials_in_reports_one_finding_per_leaked_credential():
    """The exact-value and shape nets agree on one token; it is not double-counted."""
    prompt = credential_leak_prompt(BRIEF, FAKE_ACCESS_TOKEN)
    findings = credentials_in(prompt, [Credential(ACCESS_TOKEN, FAKE_ACCESS_TOKEN)])
    assert len(findings) == 1
    assert findings[0].credential == ACCESS_TOKEN
    assert findings[0].found_by == BY_VALUE
    assert prompt[findings[0].at : findings[0].at + findings[0].length] == FAKE_ACCESS_TOKEN


# --------------------------------------------------------------------------- #
# machine_credentials -- what the tool checks itself against
# --------------------------------------------------------------------------- #
def test_machine_credentials_reads_the_config_file_and_the_token_file(
    monkeypatch, tmp_path
):
    """The client ID comes from where `check` reads it -- env OR the config file.

    Env-only would miss every caller who ran `music-deck setup --client-id`,
    which is the documented way to supply one.
    """
    config, state = tmp_path / "config", tmp_path / "state"
    config.mkdir()
    state.mkdir()
    monkeypatch.setenv("MUSIC_DECK_CONFIG_DIR", str(config))
    monkeypatch.setenv("MUSIC_DECK_STATE_DIR", str(state))
    monkeypatch.delenv("MUSIC_DECK_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)

    from music_deck.check import config_path, token_path

    config_path().write_text(json.dumps({"client_id": FAKE_CLIENT_ID}), encoding="utf-8")
    token_path().write_text(
        json.dumps(
            {"access_token": FAKE_ACCESS_TOKEN, "refresh_token": FAKE_REFRESH_TOKEN}
        ),
        encoding="utf-8",
    )

    found = {credential.kind: credential.value for credential in machine_credentials()}
    assert found == {
        CLIENT_ID: FAKE_CLIENT_ID,
        ACCESS_TOKEN: FAKE_ACCESS_TOKEN,
        REFRESH_TOKEN: FAKE_REFRESH_TOKEN,
    }


def test_machine_credentials_on_a_machine_with_nothing_signed_in(monkeypatch, tmp_path):
    """Nothing configured is not an error: there is nothing to leak."""
    monkeypatch.setenv("MUSIC_DECK_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MUSIC_DECK_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("MUSIC_DECK_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)

    assert machine_credentials() == ()


def test_plan_refuses_to_hand_back_a_plan_whose_prompt_carried_a_credential(
    monkeypatch, tmp_path
):
    """The tool's own self-check, proven to have teeth.

    `plan` calls `check_plan_transcript` before it returns. This replaces the
    assembler with the leaking one and asserts the verb refuses rather than
    publishing a plan whose prompt held the keys.
    """
    from music_deck.errors import MusicDeckError
    from music_deck.verbs import plan as plan_module

    monkeypatch.setenv("MUSIC_DECK_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MUSIC_DECK_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(
        plan_module,
        "assemble_prompt",
        lambda brief, context=None: credential_leak_prompt(brief),
    )

    with pytest.raises(MusicDeckError) as raised:
        plan(BRIEF, intelligence=Recording())

    assert raised.value.code == "boundary_violation"
    assert ACCESS_TOKEN in str(raised.value)
    assert FAKE_ACCESS_TOKEN not in str(raised.value)


# --------------------------------------------------------------------------- #
# Public API -- these three names are exported and stay exported
# --------------------------------------------------------------------------- #
def test_the_public_boundary_api_is_still_public():
    """music_deck-kwo inverted what these check. It did not rename them."""
    import music_deck

    for name in ("check_plan_transcript", "check_prompts", "BoundaryReport"):
        assert hasattr(music_deck, name), f"music_deck.{name} disappeared"
        assert name in music_deck.__all__, f"{name} left music_deck.__all__"

    assert isinstance(check_prompts([], {}), BoundaryReport)
    assert callable(check_plan_transcript)


# --------------------------------------------------------------------------- #
# Core 3 -- every prompt the substrate captured appears verbatim in transcript
# --------------------------------------------------------------------------- #
def prompts_missing_from(captured: list[str], transcript: list[str]) -> list[str]:
    """Which captured prompts the transcript does not carry verbatim.

    The kit assert, as a function, so the same comparison can be pointed at a
    deliberately broken transcript below. Counts matter as well as membership:
    two identical prompts sent and one published is a dropped prompt.
    """
    remaining = list(transcript)
    missing: list[str] = []
    for prompt in captured:
        if prompt in remaining:
            remaining.remove(prompt)
        else:
            missing.append(prompt)
    return missing


def test_every_prompt_the_substrate_captured_appears_verbatim_in_the_transcript():
    """boundary.v1 kit assert: what crossed is what the caller can read back."""
    recorder = Recording()
    result = plan(BRIEF, intelligence=recorder)

    assert recorder.prompts, "the substrate captured nothing to compare against"
    assert prompts_missing_from(recorder.prompts, result["transcript"]) == []
    assert result["transcript"] == recorder.prompts  # verbatim, and in order


def test_the_transcript_assert_would_catch_a_dropped_prompt():
    """The negative control. Without it the assert above could be vacuous.

    Same comparison, same captured prompts, one prompt missing from the
    published transcript -- and it must fail. A check that cannot fail is not a
    check.
    """
    recorder = Recording()
    recorder.run(ModelRequest(prompt=assemble_prompt(BRIEF)))
    recorder.run(ModelRequest(prompt=assemble_prompt("a second, different brief")))

    full = list(recorder.prompts)
    dropped = full[:1]

    assert prompts_missing_from(recorder.prompts, full) == []
    missing = prompts_missing_from(recorder.prompts, dropped)
    assert missing == [full[1]], "a dropped prompt slipped past the assert"


def test_a_summarised_transcript_is_not_a_verbatim_one():
    """"Verbatim" means verbatim: a truncated prompt is a missing prompt."""
    recorder = record_good()
    summarised = [prompt[:80] + " ..." for prompt in recorder.prompts]
    assert prompts_missing_from(recorder.prompts, summarised) == recorder.prompts


def test_the_result_carries_every_prompt_sent_verbatim():
    recorder = Recording()
    result = plan(BRIEF, intelligence=recorder)

    assert list(result) == ["plan", "transcript"]
    assert result["transcript"] == recorder.prompts
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
    assert check_plan_transcript(result["transcript"], credentials=FAKE_CREDENTIALS).ok


def test_a_caller_who_pastes_spotify_content_into_context_is_fine():
    """Core 1 settles what used to be a provenance question.

    Under the one-way boundary, Spotify content in a prompt passed only because
    the caller had supplied it. Now it passes because it is Spotify content and
    Spotify content is allowed -- so this passes whether or not the context is
    declared to the check at all.
    """
    context = "I already have spotify:track:3n3Ppam7vgaVa1iaRUc9Lp in there."
    recorder = Recording()
    result = plan(BRIEF, context=context, intelligence=recorder)

    assert context in recorder.prompts[0]
    assert check_plan_transcript(result["transcript"], credentials=FAKE_CREDENTIALS).ok


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
# What `plan` does today: it fetches nothing
#
# NOT a contract clause. boundary.v1 Core 1 was "`plan` performs no Spotify Web
# API request" until 2026-09-06; it now *permits* the fetch. These tests record
# what this build actually does, so that wiring a fetch in is a deliberate act
# that turns a test red rather than something that drifts in unnoticed.
# --------------------------------------------------------------------------- #
@pytest.fixture
def network_tripwire(monkeypatch):
    """Every outbound attempt is recorded and refused. Returns the record."""
    attempts: list[object] = []

    class Guarded(socket.socket):
        def connect(self, address):  # noqa: D102
            attempts.append(address)
            raise AssertionError(f"plan attempted a socket connect to {address!r}")

        def connect_ex(self, address):  # noqa: D102
            attempts.append(address)
            raise AssertionError(f"plan attempted a socket connect to {address!r}")

    def guarded_getaddrinfo(host, *args, **kwargs):
        attempts.append(host)
        raise AssertionError(f"plan attempted a DNS lookup for {host!r}")

    def guarded_create_connection(address, *args, **kwargs):
        attempts.append(address)
        raise AssertionError(f"plan attempted a connection to {address!r}")

    monkeypatch.setattr(socket, "socket", Guarded)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    monkeypatch.setattr(socket, "create_connection", guarded_create_connection)
    return attempts


def test_plan_makes_no_network_request_in_this_build(
    network_tripwire, monkeypatch, tmp_path
):
    """Today `plan` fetches nothing. Core 1 would allow it to; it does not."""
    monkeypatch.setenv("MUSIC_DECK_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("MUSIC_DECK_CONFIG_DIR", str(tmp_path / "config"))

    result = plan(BRIEF, intelligence=Recording())

    assert result["plan"]["plan_format"] == 1
    assert network_tripwire == [], f"plan attempted network access: {network_tripwire}"


def test_plan_needs_no_token_and_no_client_id(monkeypatch, tmp_path):
    """From the caller's side: nothing is signed in and `plan` still works."""
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("MUSIC_DECK_STATE_DIR", str(state))
    monkeypatch.setenv("MUSIC_DECK_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.delenv("MUSIC_DECK_CLIENT_ID", raising=False)

    result = plan(BRIEF, intelligence=Recording())

    assert result["plan"]["target"]["kind"] == "new"
    assert not list(state.iterdir()), "plan wrote into the state directory"


def test_the_plan_path_pulls_in_no_http_client(tmp_path):
    """Nothing that could speak to Spotify loads on the `plan` path today."""
    probe = (
        "import sys, json;"
        "from music_deck.verbs.plan import plan;"
        "from music_deck.testing import Recording;"
        "plan('a brief', intelligence=Recording());"
        "print(json.dumps([m for m in sys.modules if m.split('.')[0] in "
        "{'httpx','requests','urllib3','aiohttp','amplifier_agent','amplifier_agent_lib',"
        "'anthropic','openai'}]))"
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
    assert check_plan_transcript(recorder.prompts, credentials=FAKE_CREDENTIALS).ok


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
