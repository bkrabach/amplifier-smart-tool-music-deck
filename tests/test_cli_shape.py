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

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from music_deck.errors import (
    EXIT_FAILURE,
    EXIT_NO_PROVIDER,
    EXIT_REFUSAL,
    EXIT_SUCCESS,
    FROZEN_CODES,
    ErrorCode,
    exit_code_for,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

# cli.v1 Core 2's <details> block, verbatim, plus the two verbs named elsewhere
# in the contract: `plan` (Core 3, model-backed) and `manifest` (Core 7).
DETERMINISTIC_VERBS = (
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
MODEL_BACKED_VERBS = ("plan",)
ALL_VERBS = DETERMINISTIC_VERBS + MODEL_BACKED_VERBS

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


def test_complete_help_marks_plan_as_model_backed(scratch):
    """cli.v1 Core 1: --help says "which verbs are model-backed"."""
    complete = run("--help", cwd=scratch).stdout
    assert "music-deck plan  (model-backed)" in complete
    assert complete.count("(model-backed)") == len(MODEL_BACKED_VERBS)


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


@pytest.mark.parametrize("verb", [v for v in ALL_VERBS if v not in ("check", "manifest")])
def test_every_unbuilt_verb_refuses_loudly_rather_than_exiting_zero(verb, scratch):
    """A stub that exits 0 would hide the gap from every caller.

    Invoked bare, a verb either refuses `not_implemented` (it needs no
    arguments) or refuses `usage` (it does). Both are loud and both are
    non-zero, which is the promise; neither is a silent success.
    """
    result = run(*verb.split(), cwd=scratch)
    assert result.returncode != EXIT_SUCCESS
    code = json.loads(result.stdout)["error"]["code"]
    assert code in {ErrorCode.NOT_IMPLEMENTED, ErrorCode.USAGE}


def test_an_unbuilt_verb_reports_not_implemented_when_its_arguments_are_valid(scratch):
    result = run("whoami", cwd=scratch)
    assert result.returncode == EXIT_FAILURE
    envelope = json.loads(result.stdout)["error"]
    assert envelope["code"] == ErrorCode.NOT_IMPLEMENTED
    assert envelope["verb"] == "whoami"


# --------------------------------------------------------------------------- #
# Core 6 -- the frozen refusal vocabulary
# --------------------------------------------------------------------------- #
def test_the_frozen_vocabulary_is_exactly_the_ten_codes_the_contract_names():
    assert FROZEN_CODES == {
        "not_authenticated",
        "reauthorization_required",
        "not_allowlisted",
        "premium_required",
        "no_active_device",
        "rate_limited",
        "quota_exceeded",
        "partial_result",
        "playlist_items_unavailable",
        "invalid_plan",
    }


def test_every_frozen_code_maps_to_the_refusal_exit_code():
    """Core 6 calls these refusals; Core 5 gives a refusal exit 2."""
    for code in FROZEN_CODES:
        assert exit_code_for(code) == EXIT_REFUSAL


def test_the_scaffolding_codes_are_not_part_of_the_frozen_vocabulary():
    assert ErrorCode.NOT_IMPLEMENTED not in FROZEN_CODES
    assert ErrorCode.USAGE not in FROZEN_CODES
    assert exit_code_for(ErrorCode.NOT_IMPLEMENTED) == EXIT_FAILURE
    assert exit_code_for(ErrorCode.USAGE) == EXIT_REFUSAL


def test_every_code_carries_a_remedy():
    """docs/VISION.md principle 4: failures name the remedy."""
    from music_deck.errors import error_envelope, remedy_for

    for code in sorted(FROZEN_CODES) + [ErrorCode.USAGE, ErrorCode.NOT_IMPLEMENTED]:
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
