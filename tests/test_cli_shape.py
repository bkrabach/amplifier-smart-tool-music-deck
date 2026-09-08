"""The shape of the `music-deck` binary: help, output, exit codes, refusals.

Contracts served: ``cli.v1`` Core 1 (one non-interactive binary; `-h` terse,
`--help` complete, both to stdout, exit 0, the only non-JSON stdout), Core 2
(every verb present; deterministic verbs need no provider), Core 4 (one JSON
document per result; the error envelope), Core 5 (exit codes), Core 6 (the
frozen refusal vocabulary), Core 7 (`manifest` reachable from the CLI too).

Every test here runs the CLI as a real subprocess with **stdin closed**, from a
directory that is not the checkout, with provider environment variables removed
-- the same conditions the upstream conformance kit uses, so a break shows up
here first.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from music_deck import cli
from music_deck.errors import (
    EXIT_FAILURE,
    EXIT_NO_PROVIDER,
    EXIT_REFUSAL,
    EXIT_SUCCESS,
    FROZEN_CODES,
    ErrorCode,
    MusicDeckError,
    exit_code_for,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

# cli.v1 Core 2's deterministic verbs, plus the three named elsewhere in the
# contract: `setup` (Core 8), `plan` (Core 3, model-backed), `manifest` (Core 7).
DETERMINISTIC_VERBS = (
    "setup",
    "check",
    "login",
    "disconnect",
    "whoami",
    "search",
    "track",
    "album",
    "artist",
    "show",
    "episode",
    "playlists",
    "playlist items",
    "playlist create",
    "playlist add",
    "playlist remove",
    "playlist reorder",
    "playlist rename",
    "library list",
    "library save",
    "library remove",
    "library contains",
    "following",
    "top",
    "recently-played",
    "now-playing",
    "devices",
    "queue",
    "play",
    "pause",
    "next",
    "previous",
    "seek",
    "volume",
    "shuffle",
    "repeat",
    "transfer",
    "queue-add",
    "apply",
    "manifest",
)
MODEL_BACKED_VERBS = ("plan", "do")
ALL_VERBS = DETERMINISTIC_VERBS + MODEL_BACKED_VERBS

# Verbs whose lane has landed. A built verb no longer answers `not_implemented`,
# so the two "unbuilt verb" tests below skip these -- and must skip them, not
# merely tolerate them: `disconnect` deletes files, and running it here (this
# file's `run()` passes no MUSIC_DECK_STATE_DIR) would point it at the real
# ~/.local/state/music-deck of whoever runs the suite. Each landing lane adds its
# verbs here; MD-2 added login, disconnect, whoami; MD-3 added the deterministic
# Spotify verbs below; MD-4 added plan; MD-5 added apply; MD-7 added `setup`
# (cli.v1 Core 8); MD-13 added `do`. Coverage for them lives in tests/test_setup.py,
# tests/test_do.py, tests/test_auth.py,
# tests/test_http_refusals.py, tests/test_disconnect.py, tests/test_apply.py and
# tests/test_verbs_*.py, which drive them against a temporary state directory and
# a fake transport.
IMPLEMENTED_VERBS = (
    "setup",
    "check",
    "manifest",
    "login",
    "disconnect",
    "whoami",
    "plan",
    "do",
    "search",
    "track",
    "album",
    "artist",
    "show",
    "episode",
    "playlists",
    "playlist items",
    "playlist create",
    "playlist add",
    "playlist remove",
    "playlist reorder",
    "playlist rename",
    "library list",
    "library save",
    "library remove",
    "library contains",
    "following",
    "top",
    "recently-played",
    "now-playing",
    "devices",
    "queue",
    "play",
    "pause",
    "next",
    "previous",
    "seek",
    "volume",
    "shuffle",
    "repeat",
    "transfer",
    "queue-add",
    "apply",
)

# The same regex the upstream conformance kit scrubs the environment with.
_PROVIDER_ENV_RE = re.compile(
    r"(API_KEY|ACCESS_KEY|SECRET|_TOKEN$|^ANTHROPIC|^OPENAI|^AZURE_OPENAI|^GOOGLE_API"
    r"|^GEMINI|^MISTRAL|^COHERE|^GROQ|^TOGETHER|^PERPLEXITY|^AMPLIFIER|^LLM|_LLM$"
    r"|^MODEL|_MODEL$|PROVIDER)",
    re.IGNORECASE,
)

_RUNNER = "import sys; from music_deck.cli import main; sys.exit(main())"


def _argv() -> list[str]:
    """The installed console script when there is one, else the module directly."""
    installed = shutil.which("music-deck")
    return [installed] if installed else [sys.executable, "-c", _RUNNER]


def run(*args, cwd=None, timeout=20.0, env_extra=None):
    """Run the CLI the way the conformance kit does: scrubbed env, stdin closed."""
    env = {k: v for k, v in os.environ.items() if not _PROVIDER_ENV_RE.search(k)}
    env.update(env_extra or {})
    return subprocess.run(
        _argv() + list(args),
        cwd=str(cwd) if cwd else None,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )


@pytest.fixture
def scratch(tmp_path):
    """A working directory that is not the checkout, and empty state."""
    work = tmp_path / "work"
    work.mkdir()
    return work


@pytest.fixture
def scratch_env(tmp_path):
    return {
        "MUSIC_DECK_CONFIG_DIR": str(tmp_path / "config"),
        "MUSIC_DECK_STATE_DIR": str(tmp_path / "state"),
    }


# --------------------------------------------------------------------------- #
# Core 1 -- help
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_both_help_flags_exit_zero_on_stdout(flag, scratch):
    result = run(flag, cwd=scratch)
    assert result.returncode == EXIT_SUCCESS
    assert result.stdout.strip()


def test_short_help_is_terse_and_long_help_is_complete(scratch):
    terse = run("-h", cwd=scratch).stdout
    complete = run("--help", cwd=scratch).stdout
    assert terse != complete
    assert len(complete) > len(terse)


def test_complete_help_lists_every_verb_the_contract_names(scratch):
    complete = run("--help", cwd=scratch).stdout
    missing = [verb for verb in ALL_VERBS if f"music-deck {verb}" not in complete]
    assert not missing, f"--help does not list: {missing}"


def test_complete_help_marks_the_model_backed_verbs(scratch):
    """cli.v1 Core 1: --help says "which verbs are model-backed".

    Two of them since MD-13 (2026-09-06): `plan` writes a document without ever
    reaching Spotify, and `do` runs a bounded loop that reads what Spotify
    returned. Core 2 turns on whether a verb IS model-backed, not on which one
    it is, so this asserts the marker on each and the count over the whole
    listing -- a third one added without a marker fails here.
    """
    complete = run("--help", cwd=scratch).stdout
    for verb in MODEL_BACKED_VERBS:
        assert f"music-deck {verb}  (model-backed)" in complete
    assert complete.count("(model-backed)") == len(MODEL_BACKED_VERBS)


def test_complete_help_lists_the_no_browser_flag_on_login(scratch):
    """cli.v1 Core 1: --help is the complete listing an agent decides from, so a
    flag that is not in it does not exist as far as a caller is concerned."""
    complete = run("--help", cwd=scratch).stdout
    assert "--no-browser" in complete
    # `-h` stays the terse summary for a person: the verb, not its flags.
    terse = run("-h", cwd=scratch).stdout
    assert "login" in terse
    assert "--no-browser" not in terse


def test_complete_help_gives_arguments_types_and_return_shapes(scratch):
    complete = run("--help", cwd=scratch).stdout
    assert "arguments:" in complete
    assert "returns:" in complete
    # A type appears beside each argument, not just its name.
    assert "(string, required)" in complete
    assert "(integer, optional" in complete


def test_complete_help_states_the_exit_codes_and_the_frozen_codes(scratch):
    complete = run("--help", cwd=scratch).stdout
    for code in FROZEN_CODES:
        assert code in complete
    assert "no model provider configured" in complete


def test_help_is_not_json_and_every_other_stdout_is(scratch, scratch_env):
    """Core 1: help is the only non-JSON output the binary prints to stdout."""
    with pytest.raises(json.JSONDecodeError):
        json.loads(run("--help", cwd=scratch).stdout)
    for args in (["check"], ["manifest"], ["login"], ["__no_such_verb__"]):
        out = run(*args, cwd=scratch, env_extra=scratch_env).stdout
        json.loads(out)  # raises if stdout is not exactly one JSON document


def test_a_run_with_stdin_closed_never_hangs(scratch, scratch_env):
    """cli.v1 Core 1. Five seconds is the acceptance bar; the kit allows twenty."""
    result = run("check", cwd=scratch, timeout=5.0, env_extra=scratch_env)
    assert result.returncode == EXIT_SUCCESS


# --------------------------------------------------------------------------- #
# Core 2 -- the deterministic smoke verb
# --------------------------------------------------------------------------- #
def test_check_exits_zero_with_no_credentials_and_no_provider(scratch, scratch_env):
    result = run("check", cwd=scratch, env_extra=scratch_env)
    assert result.returncode == EXIT_SUCCESS
    report = json.loads(result.stdout)
    assert report["client_id"]["present"] is False
    assert report["provider"]["configured"] is False


def test_check_writes_nothing_into_the_working_directory(scratch, scratch_env):
    """invocation.md: a tool never writes beside the directory it was invoked from."""
    before = set(scratch.iterdir())
    run("check", cwd=scratch, env_extra=scratch_env)
    assert set(scratch.iterdir()) == before


def test_manifest_verb_returns_the_same_document_as_the_library(scratch):
    """cli.v1 Core 7: reachable via `music_deck.manifest()` and `music-deck manifest`."""
    from music_deck import manifest

    result = run("manifest", cwd=scratch)
    assert result.returncode == EXIT_SUCCESS
    assert json.loads(result.stdout) == manifest()


def test_no_provider_sdk_is_imported_by_the_library():
    """cli.v1 Core 2: deterministic verbs run with no provider SDK installed."""
    probe = (
        "import sys, json; import music_deck; "
        "print(json.dumps([m for m in sys.modules "
        "if m.split('.')[0] in {'anthropic','openai','google','cohere','mistralai'}]))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []


# --------------------------------------------------------------------------- #
# Core 4 / Core 5 -- one JSON document, the envelope, the exit codes
# --------------------------------------------------------------------------- #
def test_a_bad_invocation_fails_loudly_with_the_envelope(scratch):
    """Core 4 and invocation.md: never an error described while exiting 0."""
    result = run("__conformance_no_such_verb__", cwd=scratch)
    assert result.returncode != EXIT_SUCCESS
    assert result.returncode == EXIT_REFUSAL
    envelope = json.loads(result.stdout)["error"]
    assert envelope["code"] == ErrorCode.USAGE
    assert envelope["message"] and envelope["remedy"]


def test_an_adapter_local_model_code_is_normalised_without_its_sensitive_detail(
    monkeypatch, capsys
):
    """The CLI never emits an engine-only code or its unreviewed payload."""
    fixture_credential = "fixture-credential-must-not-be-emitted"
    monkeypatch.setenv("ANTHROPIC_API_KEY", fixture_credential)
    probe = dataclasses.replace(
        cli.VERBS_BY_NAME["check"],
        handler=lambda _args: (_ for _ in ()).throw(
            MusicDeckError(
                "model_error",
                f"The model returned {fixture_credential}.",
                f"Retry with {fixture_credential}.",
                provider="anthropic",
            )
        ),
    )
    monkeypatch.setattr(
        cli, "VERBS", tuple(probe if verb.name == "check" else verb for verb in cli.VERBS)
    )

    code = cli.main(["check"])
    captured = capsys.readouterr()
    envelope = json.loads(captured.out)["error"]

    assert code == EXIT_FAILURE
    assert envelope["code"] == ErrorCode.INTERNAL_ERROR
    assert "diagnostic_code" not in envelope
    assert "model_error" not in envelope["message"]
    assert envelope["message"].startswith("music-deck encountered an internal error")
    assert fixture_credential not in captured.out
    assert fixture_credential not in captured.err


def test_unknown_error_input_is_absent_from_every_public_surface():
    marker = "fixture-secret-must-not-escape"
    error = MusicDeckError(
        f"unknown_{marker}",
        f"message {marker}",
        f"remedy {marker}",
        nested={"secret": marker},
    )

    envelope = error.envelope()

    assert error.code == ErrorCode.INTERNAL_ERROR
    assert marker not in json.dumps(envelope)
    assert marker not in str(error)
    assert marker not in error.message
    assert marker not in error.remedy


def test_a_missing_required_argument_is_a_usage_refusal(scratch):
    result = run("search", cwd=scratch)
    assert result.returncode == EXIT_REFUSAL
    assert json.loads(result.stdout)["error"]["code"] == ErrorCode.USAGE


def test_a_bare_invocation_refuses_rather_than_doing_something(scratch):
    result = run(cwd=scratch)
    assert result.returncode == EXIT_REFUSAL
    assert json.loads(result.stdout)["error"]["code"] == ErrorCode.USAGE


def test_diagnostics_go_to_stderr_and_the_document_to_stdout(scratch):
    """Core 4: progress and diagnostics go to stderr, never to stdout."""
    result = run("__conformance_no_such_verb__", cwd=scratch)
    assert result.stderr.strip()
    json.loads(result.stdout)


UNBUILT_VERBS = tuple(v for v in ALL_VERBS if v not in IMPLEMENTED_VERBS)
"""Every verb `cli.v1` Core 2 names whose lane has not landed. Empty since MD-5."""


def test_every_verb_the_contract_names_is_built():
    """The guard the two tests below rest on, stated once as its own claim.

    While a verb was a stub, `test_every_unbuilt_verb_refuses_loudly...` did the
    work; with MD-5's `apply` landed there is nothing left for it to iterate, so
    the thing worth asserting is that the list is empty *on purpose*. A lane that
    adds a new stub verb without building it fails here, which is where the
    parametrised check below picks the job back up.
    """
    assert UNBUILT_VERBS == (), UNBUILT_VERBS
    assert set(ALL_VERBS) == set(IMPLEMENTED_VERBS)


@pytest.mark.parametrize("verb", UNBUILT_VERBS)
def test_every_unbuilt_verb_refuses_loudly_rather_than_exiting_zero(verb, scratch):
    """A stub that exits 0 would hide the gap from every caller.

    Invoked bare, a verb either refuses `not_implemented` (it needs no
    arguments) or refuses `usage` (it does). Both are loud and both are
    non-zero, which is the promise; neither is a silent success.

    Nothing is unbuilt today, so this parametrises to nothing -- and the test
    above is what proves that is the reason.
    """
    result = run(*verb.split(), cwd=scratch)
    assert result.returncode != EXIT_SUCCESS
    code = json.loads(result.stdout)["error"]["code"]
    assert code in {ErrorCode.NOT_IMPLEMENTED, ErrorCode.USAGE}


def test_apply_reads_its_plan_rather_than_refusing_as_a_stub(scratch):
    """`apply` was the last unbuilt verb until MD-5 (music_deck-v0b) landed.

    Pointed at a path that does not exist, it now refuses `usage` -- having
    *tried to read the file* -- where it used to refuse `not_implemented` from
    the verb table without looking at the argument at all. That difference is
    the whole of "the stub is gone", and it is visible from outside the process.
    """
    result = run("apply", "--plan", str(scratch / "no-such-plan.json"), cwd=scratch)
    assert result.returncode == EXIT_REFUSAL
    envelope = json.loads(result.stdout)["error"]
    assert envelope["code"] == ErrorCode.USAGE
    assert "no-such-plan.json" in envelope["message"]


def test_apply_refuses_a_bad_plan_with_invalid_plan_naming_the_path(scratch):
    """cli.v1 Core 6 and plan.v1 Core 6, at the binary, from a scrubbed shell.

    The in-process suite covers the whole refusal table; this is the one that
    proves the code and the path survive the trip through argparse, the
    envelope, and the exit code -- as a real subprocess with stdin closed.
    """
    plan = scratch / "bad-plan.json"
    plan.write_text(
        json.dumps(
            {
                "plan_format": 1,
                "brief": "a brief",
                "target": {"kind": "new", "name": "Nope"},
                "steps": [
                    {"search": "rock", "type": "track", "take": 0, "why": "none"}
                ],
                "rules": {
                    "exclude_artists": [],
                    "exclude_title_terms": [],
                    "dedupe": "none",
                    "order": "as_planned",
                },
            }
        ),
        encoding="utf-8",
    )

    result = run("apply", str(plan), cwd=scratch)

    assert result.returncode == EXIT_REFUSAL
    envelope = json.loads(result.stdout)["error"]
    assert envelope["code"] == ErrorCode.INVALID_PLAN
    assert envelope["path"] == "$.steps[0].take"


# --------------------------------------------------------------------------- #
# Core 6 -- the frozen refusal vocabulary
# --------------------------------------------------------------------------- #
def test_the_frozen_vocabulary_is_exactly_the_codes_the_contract_names():
    """The central registry exactly matches the code definitions in refusals.v1."""
    contract = (REPO_ROOT / "contracts" / "refusals.v1.md").read_text(encoding="utf-8")
    contract_codes = set(re.findall(r"`([a-z_]+)`\s+—", contract))

    assert FROZEN_CODES == contract_codes
    assert {
        value
        for name, value in vars(ErrorCode).items()
        if name.isupper() and isinstance(value, str)
    } == contract_codes


def test_every_frozen_code_maps_to_the_refusal_exit_code():
    """Core 5's four exits remain explicit across the complete vocabulary."""
    assert {code: exit_code_for(code) for code in FROZEN_CODES} == {
        ErrorCode.NOT_AUTHENTICATED: EXIT_REFUSAL,
        ErrorCode.REAUTHORIZATION_REQUIRED: EXIT_REFUSAL,
        ErrorCode.NOT_ALLOWLISTED: EXIT_REFUSAL,
        ErrorCode.PREMIUM_REQUIRED: EXIT_REFUSAL,
        ErrorCode.NO_ACTIVE_DEVICE: EXIT_REFUSAL,
        ErrorCode.RATE_LIMITED: EXIT_REFUSAL,
        ErrorCode.QUOTA_EXCEEDED: EXIT_REFUSAL,
        ErrorCode.PARTIAL_RESULT: EXIT_REFUSAL,
        ErrorCode.USAGE: EXIT_REFUSAL,
        ErrorCode.INVALID_INPUT: EXIT_REFUSAL,
        ErrorCode.INVALID_PLAN: EXIT_REFUSAL,
        ErrorCode.NO_PROVIDER_CONFIGURED: EXIT_NO_PROVIDER,
        ErrorCode.PORT_UNAVAILABLE: EXIT_REFUSAL,
        ErrorCode.NO_BROWSER: EXIT_REFUSAL,
        ErrorCode.CANCELLED: EXIT_REFUSAL,
        ErrorCode.SPOTIFY_ERROR: EXIT_FAILURE,
        ErrorCode.PLAYLIST_ITEMS_UNAVAILABLE: EXIT_REFUSAL,
        ErrorCode.INTERNAL_ERROR: EXIT_FAILURE,
        ErrorCode.NOT_IMPLEMENTED: EXIT_FAILURE,
    }


def test_every_code_carries_a_remedy():
    """docs/VISION.md principle 4: failures name the remedy."""
    from music_deck.errors import error_envelope, remedy_for

    for code in sorted(FROZEN_CODES):
        assert remedy_for(code).strip()
        envelope = error_envelope(code, "something went wrong")["error"]
        assert set(envelope) >= {"code", "message", "remedy"}
        assert all(envelope[field].strip() for field in ("code", "message", "remedy"))


def test_the_exit_codes_are_the_four_the_contract_names():
    assert (EXIT_SUCCESS, EXIT_FAILURE, EXIT_REFUSAL, EXIT_NO_PROVIDER) == (0, 1, 2, 3)


def test_the_no_provider_error_carries_exit_three():
    """cli.v1 Core 3: a model-backed verb with no substrate exits 3."""
    from music_deck.errors import NoProviderError

    error = NoProviderError("no provider configured", "Configure one.")
    assert error.exit_code == EXIT_NO_PROVIDER
    assert error.envelope()["error"]["remedy"] == "Configure one."


# --------------------------------------------------------------------------- #
# The parser and the help text cannot drift apart
# --------------------------------------------------------------------------- #
def test_the_parser_accepts_exactly_the_verbs_the_help_text_lists():
    from music_deck.cli import VERBS, build_parser

    build_parser()  # must build without error from the same table help renders from
    listed = set()
    for verb in VERBS:
        if verb.subverbs:
            listed |= {f"{verb.name} {sub.name}" for sub in verb.subverbs}
        else:
            listed.add(verb.name)
    assert listed == set(ALL_VERBS)
