"""`plan` refuses before it builds anything -- cli.v1 Core 3, exit 3.

Contracts served: ``cli.v1`` Core 3 ("`plan` is the only model-backed verb, and
refuses before any prompt is built. Invoked without a usable model substrate, it
exits 3 naming exactly which precondition is missing ... and how to fix it.
Never a silent fallback to a deterministic answer"), Core 2 (deterministic verbs
need no provider SDK installed), Core 5 (exit 3 is its own code).

"Before any prompt is built" is the hard half, because a tool that assembles a
prompt and *then* refuses looks identical from outside. Two independent proofs
here: ``Unconfigured.run`` records and raises if it is ever reached, and
``assemble_prompt`` is replaced by a tripwire that fails the test if it is ever
called.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys

import pytest

from music_deck import intelligence as intel
from music_deck.errors import EXIT_NO_PROVIDER, EXIT_REFUSAL, EXIT_SUCCESS, NoProviderError
from music_deck.testing import Unconfigured
from music_deck.verbs import plan as plan_module
from music_deck.verbs.plan import plan

BRIEF = "upbeat 90s guitar songs for a Saturday morning"

_PROVIDER_ENV_RE = re.compile(
    r"(API_KEY|ACCESS_KEY|SECRET|_TOKEN$|^ANTHROPIC|^OPENAI|^AZURE_OPENAI|^GOOGLE_API"
    r"|^GEMINI|^MISTRAL|^COHERE|^GROQ|^TOGETHER|^PERPLEXITY|^AMPLIFIER|^LLM|_LLM$"
    r"|^MODEL|_MODEL$|PROVIDER)",
    re.IGNORECASE,
)

_RUNNER = "import sys; from music_deck.cli import main; sys.exit(main())"


def _argv() -> list[str]:
    installed = shutil.which("music-deck")
    return [installed] if installed else [sys.executable, "-c", _RUNNER]


def run_cli(*args, cwd=None, timeout=20.0, env_extra=None):
    """The CLI as the conformance kit runs it: scrubbed env, stdin closed."""
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
def scrubbed(monkeypatch):
    """No provider credential and no pin, in-process."""
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


# --------------------------------------------------------------------------- #
# Core 3 -- the refusal happens before the prompt exists
# --------------------------------------------------------------------------- #
def test_an_unconfigured_substrate_refuses_with_exit_three():
    engine = Unconfigured()

    with pytest.raises(NoProviderError) as raised:
        plan(BRIEF, intelligence=engine)

    error = raised.value
    assert error.exit_code == EXIT_NO_PROVIDER
    assert error.message.strip()
    assert error.remedy.strip()
    assert engine.preflight_calls == [None]


def test_unconfigured_run_is_never_reached():
    engine = Unconfigured()
    with pytest.raises(NoProviderError):
        plan(BRIEF, intelligence=engine)
    assert engine.run_calls == [], "a prompt was submitted despite no substrate"


def test_no_prompt_is_ever_assembled(monkeypatch):
    """The structural proof: the assembler itself is a tripwire."""
    assembled: list[str] = []

    def tripwire(brief, context=None):
        assembled.append(brief)
        raise AssertionError(
            "cli.v1 Core 3: a prompt was assembled before the substrate refused"
        )

    monkeypatch.setattr(plan_module, "assemble_prompt", tripwire)

    with pytest.raises(NoProviderError):
        plan(BRIEF, intelligence=Unconfigured())

    assert assembled == []


def test_it_refuses_rather_than_falling_back_to_a_deterministic_answer():
    """Core 3: "Never a silent fallback to a deterministic answer.\""""
    with pytest.raises(NoProviderError):
        result = plan(BRIEF, intelligence=Unconfigured())
        pytest.fail(f"plan returned {result!r} instead of refusing")


# --------------------------------------------------------------------------- #
# Core 3 -- the message names exactly which precondition is missing
# --------------------------------------------------------------------------- #
def test_nothing_configured_names_the_provider_as_the_missing_precondition(scrubbed):
    with pytest.raises(intel.NoModelSubstrate) as raised:
        intel.AmplifierIntelligence().preflight()

    error = raised.value
    assert error.missing == intel.MISSING_PROVIDER
    assert error.envelope()["error"]["missing"] == intel.MISSING_PROVIDER
    assert "ANTHROPIC_API_KEY" in error.remedy


def test_a_pinned_provider_with_no_credential_names_the_credentials(scrubbed, monkeypatch):
    monkeypatch.setenv(intel.PROVIDER_ENV_VAR, "openai")

    with pytest.raises(intel.NoModelSubstrate) as raised:
        intel.AmplifierIntelligence().preflight()

    assert raised.value.missing == intel.MISSING_CREDENTIALS
    assert "OPENAI_API_KEY" in raised.value.remedy


def test_a_provider_name_music_deck_does_not_know_says_so(scrubbed, monkeypatch):
    monkeypatch.setenv(intel.PROVIDER_ENV_VAR, "llamas")

    with pytest.raises(intel.NoModelSubstrate) as raised:
        intel.AmplifierIntelligence().preflight()

    assert raised.value.missing == intel.MISSING_PROVIDER
    assert "anthropic" in raised.value.remedy


def test_a_credential_without_its_sdk_names_the_extra(scrubbed, monkeypatch):
    """The case a credential alone would hide.

    A credential that resolves a provider the engine then cannot mount reads to
    a caller as a model that answered badly rather than one that never ran. The
    absence is forced rather than read off this machine, so the branch is tested
    whether or not the extra happens to be installed here.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    monkeypatch.setattr(intel, "missing_package", lambda provider: "anthropic")

    with pytest.raises(intel.NoModelSubstrate) as raised:
        intel.AmplifierIntelligence().preflight()

    error = raised.value
    assert error.missing == intel.MISSING_PROVIDER_SDK
    assert intel.runtime_install_command("anthropic") in error.remedy


def test_a_missing_engine_names_the_engine(scrubbed, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    monkeypatch.setattr(intel, "missing_package", lambda provider: None)
    monkeypatch.setattr(intel, "engine_installed", lambda: False)

    with pytest.raises(intel.NoModelSubstrate) as raised:
        intel.AmplifierIntelligence().preflight()

    assert raised.value.missing == intel.MISSING_ENGINE
    assert intel.ENGINE_PACKAGE in raised.value.message


def test_azure_without_a_model_refuses_before_a_prompt_or_engine_run(scrubbed, monkeypatch):
    """An Azure deployment name is a model precondition, not a late engine error."""
    monkeypatch.setenv(intel.PROVIDER_ENV_VAR, "azure-openai")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "fixture-not-a-real-key")
    monkeypatch.setattr(intel, "missing_package", lambda provider: None)
    monkeypatch.setattr(intel, "engine_installed", lambda: True)
    assembled: list[str] = []
    monkeypatch.setattr(
        plan_module, "assemble_prompt", lambda *args, **kwargs: assembled.append("called")
    )
    engine = intel.AmplifierIntelligence()
    monkeypatch.setattr(engine, "run", lambda request: pytest.fail("engine run was reached"))

    with pytest.raises(intel.NoModelSubstrate) as raised:
        plan(BRIEF, intelligence=engine)

    assert raised.value.missing == "model"
    assert raised.value.exit_code == EXIT_NO_PROVIDER
    assert "MUSIC_DECK_MODEL" in raised.value.remedy
    assert assembled == []


def test_an_explicit_azure_model_satisfies_preflight(scrubbed, monkeypatch):
    monkeypatch.setenv(intel.PROVIDER_ENV_VAR, "azure-openai")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "fixture-not-a-real-key")
    monkeypatch.setattr(intel, "missing_package", lambda provider: None)
    monkeypatch.setattr(intel, "engine_installed", lambda: True)

    assert intel.AmplifierIntelligence().preflight("azure-openai", "my-deployment") == "azure-openai"


def test_every_refusal_names_one_of_the_declared_preconditions(scrubbed):
    with pytest.raises(intel.NoModelSubstrate) as raised:
        intel.AmplifierIntelligence().preflight()
    assert raised.value.missing in intel.PRECONDITIONS


def test_the_auto_selection_order_is_the_one_the_brief_pins(scrubbed, monkeypatch):
    """ANTHROPIC_API_KEY -> OPENAI_API_KEY -> GOOGLE_API_KEY -> AZURE_OPENAI_API_KEY."""
    assert intel.PROVIDER_ORDER == ("anthropic", "openai", "gemini", "azure-openai")

    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "k")
    assert intel.credentialled_providers() == ["azure-openai"]
    monkeypatch.setenv("GOOGLE_API_KEY", "k")
    assert intel.credentialled_providers() == ["gemini", "azure-openai"]
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    assert intel.credentialled_providers() == ["openai", "gemini", "azure-openai"]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    assert intel.credentialled_providers()[0] == "anthropic"


# --------------------------------------------------------------------------- #
# The same refusal, at the binary
# --------------------------------------------------------------------------- #
def test_the_cli_exits_three_with_the_environment_scrubbed(tmp_path):
    result = run_cli(
        "plan",
        BRIEF,
        cwd=tmp_path,
        env_extra={
            "MUSIC_DECK_CONFIG_DIR": str(tmp_path / "config"),
            "MUSIC_DECK_STATE_DIR": str(tmp_path / "state"),
        },
    )

    assert result.returncode == EXIT_NO_PROVIDER, result.stdout + result.stderr
    envelope = json.loads(result.stdout)["error"]
    assert envelope["code"] == "no_provider_configured"
    assert envelope["missing"] in intel.PRECONDITIONS
    assert envelope["message"].strip() and envelope["remedy"].strip()
    assert result.stderr.strip()  # diagnostics on stderr -- cli.v1 Core 4


def test_the_cli_refusal_is_one_json_document_on_stdout(tmp_path):
    result = run_cli("plan", BRIEF, cwd=tmp_path)
    json.loads(result.stdout)  # raises unless stdout is exactly one document


def test_plan_with_no_brief_is_a_usage_refusal(tmp_path):
    result = run_cli("plan", cwd=tmp_path)
    assert result.returncode == EXIT_REFUSAL
    assert json.loads(result.stdout)["error"]["code"] == "usage"


def test_an_empty_brief_is_a_usage_refusal_not_a_model_call(tmp_path):
    result = run_cli("plan", "   ", cwd=tmp_path)
    assert result.returncode == EXIT_REFUSAL
    assert json.loads(result.stdout)["error"]["code"] == "usage"


def test_the_help_still_lists_plan_as_the_model_backed_verb(tmp_path):
    result = run_cli("--help", cwd=tmp_path)
    assert result.returncode == EXIT_SUCCESS
    assert "music-deck plan  (model-backed)" in result.stdout
    assert "transcript" in result.stdout


# --------------------------------------------------------------------------- #
# Core 2 -- a base install imports no provider SDK
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "probe_import",
    [
        "import music_deck",
        "import music_deck.intelligence",
        "import music_deck.verbs.plan",
        "from music_deck.cli import main",
    ],
)
def test_a_base_install_imports_no_provider_sdk_and_no_engine(probe_import, tmp_path):
    """cli.v1 Core 2, and the lazy-import discipline that keeps it true.

    ``amplifier_agent`` counts here as much as the SDKs do. It is the engine
    library ``plan`` runs on, and Core 2's promise is that the other forty verbs
    run "with no provider configured and no provider SDK installed" -- a promise
    about what a caller is charged for, which an import at module scope quietly
    breaks whether or not the import happens to be cheap this week.

    The two private-internals module names music-deck used before MD-10 are
    listed too. If either ever reappears in ``sys.modules`` after importing
    music-deck, something has gone back to booting the engine by its insides.
    """
    probe = (
        f"{probe_import}; import sys, json;"
        "print(json.dumps(sorted(m for m in sys.modules if m.split('.')[0] in "
        "{'anthropic','openai','google','cohere','mistralai','amplifier_agent',"
        "'amplifier_agent_lib','amplifier_agent_cli'})))"
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


def test_preflight_answers_without_importing_anything(scrubbed, tmp_path):
    """Even asking the question must not pull in a provider stack."""
    probe = (
        "import sys, json;"
        "from music_deck.intelligence import AmplifierIntelligence, NoModelSubstrate;"
        "engine = AmplifierIntelligence();"
        "\ntry:\n    engine.preflight()\nexcept NoModelSubstrate:\n    pass\n"
        "print(json.dumps(sorted(m for m in sys.modules if m.split('.')[0] in "
        "{'anthropic','openai','google','amplifier_agent','amplifier_agent_lib',"
        "'amplifier_agent_cli'})))"
    )
    env = {k: v for k, v in os.environ.items() if not _PROVIDER_ENV_RE.search(k)}
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []
