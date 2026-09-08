"""How music-deck boots the engine -- the public API, and nothing under it.

Contracts served: ``boundary.v1`` Core 2 (no Spotify content reaches a model --
here, by giving the model nothing it could fetch content *with*), Core 8 (no
persistent store), ``cli.v1`` Core 2 (a deterministic verb pays for no part of
the model stack), Core 4 (a failure is one envelope with an actionable remedy).

Why a fake module rather than a real turn
-----------------------------------------
The properties this file exists to hold are all decided *at the call*: which
options the agent is built with, and which options the session is created with.
A live turn would prove the call works; it would not prove the call was made
with ``persistence="ephemeral"`` rather than the library's durable default,
because both produce a plausible-looking answer. So ``amplifier_agent`` is
replaced in ``sys.modules`` by a stand-in that records exactly what it was
handed, and the assertions are about the record.

That substitution only works because every engine import in
``music_deck.intelligence`` sits inside a function body -- the same lazy-import
discipline ``cli.v1`` Core 2 requires for its own reasons.
:func:`test_the_engine_is_imported_inside_a_function_never_at_module_scope`
holds that structurally, over the module's syntax tree, so this file cannot
quietly stop testing what it claims to.

The live counterpart is in DONE.md: a real ``music-deck plan`` against a real
provider from a real ``uv tool install``. Neither proof is sufficient alone.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from music_deck import intelligence as intel
from music_deck.errors import EXIT_FAILURE, MusicDeckError

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPO_ROOT / "src" / "music_deck"

PROMPT = "a brief, assembled elsewhere and sent verbatim"


# --------------------------------------------------------------------------- #
# The stand-in engine
# --------------------------------------------------------------------------- #
class FakeAgentError(Exception):
    """The library's ``AgentError`` shape: a code, a message, a remedy."""

    def __init__(self, code: str, message: str, remedy: str) -> None:
        super().__init__(message)
        self.code = code
        self.category = "test"
        self.message = message
        self.remedy = remedy


@dataclass
class FakeTextPart:
    text: str
    type: str = "text"


@dataclass
class FakeTurnInput:
    content: list[Any]
    model: str | None = None
    history: list[Any] | None = None


@dataclass
class FakeAgentOptions:
    provider: str | None = None
    model: str | None = None
    instructions: str | None = None
    tools: list[Any] | None = None
    skills: list[str] | None = None
    mcp_servers: list[Any] | None = None
    storage: Any = None
    approvals: Any = None
    tool_error_policy: str = "stop"


@dataclass
class FakeSessionOptions:
    session_id: str | None = None
    persistence: str = "durable"
    model: str | None = None


@dataclass
class FakeUsageEntry:
    provider: str
    model: str
    tokens_in: int | None = None
    tokens_out: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    cost: dict[str, Decimal] | None = None


@dataclass
class FakeUsage:
    entries: list[FakeUsageEntry]


@dataclass
class FakeTurnResult:
    state: str
    content: list[Any] | None = None
    error: Any = None
    usage: Any = None


@dataclass
class Ledger:
    """Everything the stand-in was handed, and what the filesystem looked like."""

    agent_options: list[FakeAgentOptions] = field(default_factory=list)
    session_options: list[FakeSessionOptions] = field(default_factory=list)
    turn_inputs: list[FakeTurnInput] = field(default_factory=list)
    storage_existed: list[bool] = field(default_factory=list)
    storage_contents: list[list[str]] = field(default_factory=list)
    closed_agents: int = 0
    closed_sessions: int = 0
    #: ``os.environ`` as the engine would have read it, once per call that reads
    #: it. The real engine resolves its configuration from the *process*
    #: environment rather than from the options it is handed, so what was in
    #: there at that instant is the whole input to that decision -- and the only
    #: place a host setting could have reached it.
    host_settings_seen: list[dict[str, str]] = field(default_factory=list)


class FakeSession:
    def __init__(self, ledger: Ledger, result: Any, raise_on_run: Exception | None) -> None:
        self._ledger = ledger
        self._result = result
        self._raise = raise_on_run

    async def run(self, turn_input: FakeTurnInput) -> Any:
        self._ledger.turn_inputs.append(turn_input)
        self._ledger.host_settings_seen.append(_host_settings_now())
        if self._raise is not None:
            raise self._raise
        return self._result

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        self._ledger.closed_sessions += 1


class FakeAgent:
    def __init__(self, ledger: Ledger, result: Any, raise_on_run: Exception | None) -> None:
        self._ledger = ledger
        self._result = result
        self._raise = raise_on_run

    async def create_session(self, options: FakeSessionOptions) -> FakeSession:
        self._ledger.session_options.append(options)
        return FakeSession(self._ledger, self._result, self._raise)

    async def __aenter__(self) -> "FakeAgent":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        self._ledger.closed_agents += 1


# --------------------------------------------------------------------------- #
# The host-settings namespace, as the real engine treats it
# --------------------------------------------------------------------------- #
HOST_PREFIX = intel.HOST_SETTING_PREFIX

#: The suffixes the engine registers. Read out of the installed engine's own
#: ``_engine/configuration.py`` on 2026-09-06; anything else under the prefix is
#: refused before a turn starts, which is the whole defect.
REGISTERED_SUFFIXES = frozenset({"PROVIDER", "MODEL", "STORAGE", "WORKSPACE", "CONFIG"})
REGISTERED_PREFIXES = ("FACE_", "ENGINE_", "NODE_")


def _host_settings_now() -> dict[str, str]:
    """Every ``AMPLIFIER_AGENT_*`` variable visible in this process right now."""
    return {
        name: value
        for name, value in os.environ.items()
        if name.startswith(HOST_PREFIX)
    }


def _refuse_unregistered_host_settings() -> None:
    """Refuse a turn exactly as the installed engine does, and for its reasons.

    Two of the three measured refusals, reproduced from the engine's own
    ``configuration.resolve``:

    * ``AMPLIFIER_AGENT_CONFIG`` naming a file that does not exist -- ``config:
      the configured file does not exist.``
    * any variable under the prefix whose suffix is unregistered --
      ``unregistered host environment setting.``

    Reproduced rather than imported because the engine is not installed in the
    development environment at all (``cli.v1`` Core 2 -- the deterministic verbs
    pay for no part of the model stack), so there is nothing to import. The
    price of that is a copy that can date; the guard against it is
    :func:`test_the_refusal_this_file_reproduces_is_the_engines_own`, which
    checks the copy against the installed engine wherever one exists.
    """
    settings = _host_settings_now()
    config = settings.get(f"{HOST_PREFIX}CONFIG")
    if config is not None and not Path(config).expanduser().exists():
        raise FakeAgentError(
            "invalid_input",
            "config: the configured file does not exist.",
            f"Create the configuration file or remove {HOST_PREFIX}CONFIG.",
        )
    for name in settings:
        suffix = name.removeprefix(HOST_PREFIX)
        if suffix in REGISTERED_SUFFIXES or suffix.startswith(REGISTERED_PREFIXES):
            continue
        raise FakeAgentError(
            "invalid_input",
            f"{name}: unregistered host environment setting.",
            f"Remove {name}.",
        )


def install_fake_engine(
    monkeypatch,
    *,
    result: Any | None = None,
    raise_on_create: Exception | None = None,
    raise_on_run: Exception | None = None,
    refuse_host_settings: bool = False,
) -> Ledger:
    """Put a recording stand-in at ``sys.modules["amplifier_agent"]``.

    Returns the ledger the assertions read. The environment is rigged so
    ``preflight`` -- which is the real one, not a stand-in -- resolves
    ``anthropic`` and passes.
    """
    ledger = Ledger()
    if result is None:
        result = FakeTurnResult(
            state="success",
            content=[FakeTextPart("a reply")],
            usage=FakeUsage([FakeUsageEntry(provider="anthropic", model="claude-sonnet-5")]),
        )

    async def create_agent(options: FakeAgentOptions) -> FakeAgent:
        ledger.agent_options.append(options)
        ledger.host_settings_seen.append(_host_settings_now())
        if refuse_host_settings:
            _refuse_unregistered_host_settings()
        storage = Path(str(options.storage)) if options.storage is not None else None
        ledger.storage_existed.append(bool(storage and storage.is_dir()))
        ledger.storage_contents.append(
            sorted(str(p) for p in storage.rglob("*")) if storage and storage.is_dir() else []
        )
        if raise_on_create is not None:
            raise raise_on_create
        return FakeAgent(ledger, result, raise_on_run)

    module = type(sys)("amplifier_agent")
    module.AgentError = FakeAgentError  # type: ignore[attr-defined]
    module.AgentOptions = FakeAgentOptions  # type: ignore[attr-defined]
    module.SessionOptions = FakeSessionOptions  # type: ignore[attr-defined]
    module.TextPart = FakeTextPart  # type: ignore[attr-defined]
    module.TurnInput = FakeTurnInput  # type: ignore[attr-defined]
    module.create_agent = create_agent  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "amplifier_agent", module)

    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    monkeypatch.delenv(intel.PROVIDER_ENV_VAR, raising=False)
    monkeypatch.delenv(intel.MODEL_ENV_VAR, raising=False)
    monkeypatch.setattr(intel, "missing_package", lambda provider: None)
    monkeypatch.setattr(intel, "engine_installed", lambda: True)
    return ledger


# --------------------------------------------------------------------------- #
# boundary.v1 Core 8 -- ephemeral, and nothing left behind
# --------------------------------------------------------------------------- #
def test_the_session_is_created_ephemeral(monkeypatch):
    """Core 8: durable is the library's default, so this must be said out loud.

    Said out loud *and* checked here, because the difference between an
    ephemeral session and a durable one is invisible in the answer: both return
    the same text, and only one of them leaves a resumable transcript on disk.
    """
    ledger = install_fake_engine(monkeypatch)

    intel.AmplifierIntelligence().run(intel.ModelRequest(prompt=PROMPT))

    assert [options.persistence for options in ledger.session_options] == ["ephemeral"]
    assert [options.session_id for options in ledger.session_options] == [None]


def test_the_storage_root_is_a_temporary_directory_that_does_not_outlive_the_turn(
    monkeypatch,
):
    """Core 8, belt to the ephemeral session's braces.

    The library writes durable transcripts under a storage root it picks --
    ``~/.amplifier-agent`` by default. music-deck names its own, in a temporary
    directory, so "nothing persists" is a fact about the filesystem after the
    turn rather than a claim about what the library chose to write.
    """
    ledger = install_fake_engine(monkeypatch)

    intel.AmplifierIntelligence().run(intel.ModelRequest(prompt=PROMPT))

    [storage] = [options.storage for options in ledger.agent_options]
    assert storage, "no storage root was named, so the library's default was used"
    assert ledger.storage_existed == [True], "the storage root did not exist during the turn"
    assert ledger.storage_contents == [[]]
    assert not Path(str(storage)).exists(), "the storage root outlived the turn"


def test_the_agent_and_the_session_are_both_closed(monkeypatch):
    ledger = install_fake_engine(monkeypatch)

    intel.AmplifierIntelligence().run(intel.ModelRequest(prompt=PROMPT))

    assert ledger.closed_agents == 1
    assert ledger.closed_sessions == 1


# --------------------------------------------------------------------------- #
# The caller's shell does not get a vote -- MD-14 defect 1
#
# Measured on the steward's machine on 2026-09-06: their shell sets
# ``AMPLIFIER_AGENT_CONFIG`` for Amplifier, and every ``music-deck plan`` run in
# it exited 1 with ``invalid_input`` and "unregistered host setting"; the same
# command under ``env -u AMPLIFIER_AGENT_CONFIG`` exited 0. The variable is not
# music-deck's, is named nowhere in its manifest, and was breaking a verb.
#
# Every test below sets the variable for real (``monkeypatch.setenv``) and lets
# the stand-in refuse exactly as the installed engine does. Asserting the scrub
# by reading the boot code would prove only that a line exists.
# --------------------------------------------------------------------------- #
CONFIG_VAR = f"{HOST_PREFIX}CONFIG"


def test_a_host_config_setting_pointing_nowhere_does_not_fail_the_turn(
    monkeypatch, tmp_path
):
    """The steward's exact case: the turn runs, and the engine never sees it."""
    ledger = install_fake_engine(monkeypatch, refuse_host_settings=True)
    missing = tmp_path / "no-such-config.json"
    monkeypatch.setenv(CONFIG_VAR, str(missing))
    assert not missing.exists()

    answer = intel.AmplifierIntelligence().run(intel.ModelRequest(prompt=PROMPT))

    assert answer.text == "a reply"
    assert ledger.host_settings_seen == [{}, {}], (
        "a host setting reached the engine: it reads the process environment, "
        f"and saw {ledger.host_settings_seen}"
    )


def test_the_turn_runs_the_same_way_with_no_host_setting_at_all(monkeypatch):
    """The fix does not depend on the variable being there to be removed."""
    ledger = install_fake_engine(monkeypatch, refuse_host_settings=True)
    monkeypatch.delenv(CONFIG_VAR, raising=False)

    answer = intel.AmplifierIntelligence().run(intel.ModelRequest(prompt=PROMPT))

    assert answer.text == "a reply"
    assert ledger.host_settings_seen == [{}, {}]


def test_the_whole_namespace_is_withheld_not_only_the_one_that_bit(monkeypatch):
    """Registered and unregistered alike -- music-deck honours none of them.

    ``AMPLIFIER_AGENT_STORAGE`` is the one that matters beyond tidiness: it moves
    the engine's storage root, and ``boundary.v1`` Core 8 forbids a persistent
    store. Left standing, a variable in the caller's shell would decide where
    the transcript lands, and the temporary directory this file checks
    elsewhere would stop meaning anything.
    """
    ledger = install_fake_engine(monkeypatch, refuse_host_settings=True)
    for name, value in {
        CONFIG_VAR: "/nowhere/at/all.json",
        f"{HOST_PREFIX}STORAGE": "/tmp/somewhere-durable",
        f"{HOST_PREFIX}WORKSPACE": "NOT A VALID SLUG",
        f"{HOST_PREFIX}PROVIDER": "some-other-provider",
        f"{HOST_PREFIX}TELEMETRY": "1",
    }.items():
        monkeypatch.setenv(name, value)

    answer = intel.AmplifierIntelligence().run(intel.ModelRequest(prompt=PROMPT))

    assert answer.text == "a reply"
    assert ledger.host_settings_seen == [{}, {}]
    # The storage root the engine was handed is still music-deck's own.
    [storage] = [options.storage for options in ledger.agent_options]
    assert "/tmp/somewhere-durable" not in str(storage)
    assert "music-deck-agent-" in str(storage)


def test_the_callers_environment_is_exactly_as_it_was_found_afterwards(monkeypatch):
    """Withheld for the turn, not taken away: the caller's shell is untouched."""
    install_fake_engine(monkeypatch, refuse_host_settings=True)
    monkeypatch.setenv(CONFIG_VAR, "/nowhere/at/all.json")
    monkeypatch.setenv(f"{HOST_PREFIX}TELEMETRY", "1")
    before = _host_settings_now()

    intel.AmplifierIntelligence().run(intel.ModelRequest(prompt=PROMPT))

    assert _host_settings_now() == before


def test_a_turn_that_fails_still_puts_the_environment_back(monkeypatch):
    """A refusal must not be paid for twice, once in the answer and once in the shell."""
    install_fake_engine(
        monkeypatch,
        raise_on_run=FakeAgentError("provider_error", "the provider said no.", "Try again."),
    )
    monkeypatch.setenv(CONFIG_VAR, "/nowhere/at/all.json")
    before = _host_settings_now()

    with pytest.raises(MusicDeckError):
        intel.AmplifierIntelligence().run(intel.ModelRequest(prompt=PROMPT))

    assert _host_settings_now() == before


def test_the_stand_in_engine_refuses_what_the_real_one_refuses(monkeypatch, tmp_path):
    """The regression guard on the guard.

    Without this, ``refuse_host_settings`` is an assertion nobody has seen fail,
    and the tests above could go green because the stand-in stopped refusing
    rather than because music-deck kept scrubbing. Both refusals the installed
    engine raises are provoked here directly.
    """
    monkeypatch.setenv(CONFIG_VAR, str(tmp_path / "absent.json"))
    with pytest.raises(FakeAgentError) as missing_config:
        _refuse_unregistered_host_settings()
    assert "does not exist" in missing_config.value.message

    present = tmp_path / "present.json"
    present.write_text("{}")
    monkeypatch.setenv(CONFIG_VAR, str(present))
    monkeypatch.setenv(f"{HOST_PREFIX}TELEMETRY", "1")
    with pytest.raises(FakeAgentError) as unregistered:
        _refuse_unregistered_host_settings()
    assert "unregistered host environment setting" in unregistered.value.message

    # A registered suffix on its own is not refused -- the rule is about what is
    # unregistered, not about the prefix existing.
    monkeypatch.delenv(f"{HOST_PREFIX}TELEMETRY")
    monkeypatch.setenv(f"{HOST_PREFIX}MODEL", "some-model")
    _refuse_unregistered_host_settings()


# --------------------------------------------------------------------------- #
# boundary.v1 Core 2 -- the model has nothing to fetch with
# --------------------------------------------------------------------------- #
def test_the_agent_is_built_with_no_tools_no_skills_and_no_mcp_servers(monkeypatch):
    """Core 2's structural half: a model that cannot fetch cannot leak.

    Before MD-10 this was four lines of hand-clearing inside the library's
    prepared mount plan. Now it is the absence of three arguments, which is the
    library's own default -- there is nothing to forget to strip.
    """
    ledger = install_fake_engine(monkeypatch)

    intel.AmplifierIntelligence().run(intel.ModelRequest(prompt=PROMPT))

    [options] = ledger.agent_options
    assert options.tools is None
    assert options.skills is None
    assert options.mcp_servers is None
    assert options.instructions is None


def test_no_approvals_channel_is_supplied(monkeypatch):
    """The fail-closed default, stated as an assertion rather than a hope.

    The library's ``docs/concepts/approvals.md``: "approvals absent -> there is
    no channel", and a consequential action then fails ``approval_unavailable``
    rather than proceeding. Passing a handler -- or even ``"allow"`` -- is the
    only way to make a tool call possible, so the assertion that matters is that
    music-deck passes neither.
    """
    ledger = install_fake_engine(monkeypatch)

    intel.AmplifierIntelligence().run(intel.ModelRequest(prompt=PROMPT))

    [options] = ledger.agent_options
    assert options.approvals is None


def test_the_prompt_crosses_the_seam_verbatim(monkeypatch):
    """boundary.v1 Core 3: the transcript is the whole truth about what was sent."""
    ledger = install_fake_engine(monkeypatch)

    intel.AmplifierIntelligence().run(intel.ModelRequest(prompt=PROMPT))

    [turn] = ledger.turn_inputs
    assert [part.text for part in turn.content] == [PROMPT]
    assert turn.history is None


# --------------------------------------------------------------------------- #
# cli.v1 Core 4 -- a failure is loud, coded, and carries the library's remedy
# --------------------------------------------------------------------------- #
def test_a_failed_turn_is_a_refusal_carrying_the_librarys_code_and_remedy(monkeypatch):
    """A turn that failed is never composed into a plan.

    Observed live: a rejected model selection came back ``state="failure"``
    carrying *both* an error and plausible-looking content. Reading the content
    and ignoring the state would have handed that on as an answer.
    """
    install_fake_engine(
        monkeypatch,
        result=FakeTurnResult(
            state="failure",
            content=[FakeTextPart("pong")],
            error=FakeAgentError(
                "selector_rejected",
                "The requested model selection cannot be honored.",
                "Name a model the account can reach.",
            ),
        ),
    )

    with pytest.raises(MusicDeckError) as raised:
        intel.AmplifierIntelligence().run(intel.ModelRequest(prompt=PROMPT))

    error = raised.value
    assert error.code == "selector_rejected"
    assert "cannot be honored" in error.message
    assert "Name a model the account can reach." in error.remedy
    assert intel.MODEL_ENV_VAR in error.remedy
    assert error.exit_code == EXIT_FAILURE
    assert error.envelope()["error"]["remedy"].strip()


def test_a_turn_that_fails_without_saying_why_still_refuses(monkeypatch):
    install_fake_engine(monkeypatch, result=FakeTurnResult(state="cancelled"))

    with pytest.raises(MusicDeckError) as raised:
        intel.AmplifierIntelligence().run(intel.ModelRequest(prompt=PROMPT))

    assert raised.value.code == "model_did_not_run"
    assert "cancelled" in raised.value.message


def test_an_agent_that_cannot_be_built_refuses_with_its_own_remedy(monkeypatch):
    """Measured on this host: a stray ``AMPLIFIER_AGENT_CONFIG`` refuses the build.

    The engine reads its own ``AMPLIFIER_AGENT_*`` host settings and refuses an
    unregistered key before a turn exists. music-deck does not scrub the
    caller's environment to hide that -- it reports it, and names where the
    setting comes from, because a silently ignored host setting is worse than a
    loud one.
    """
    install_fake_engine(
        monkeypatch,
        raise_on_create=FakeAgentError(
            "invalid_input", "debug: unregistered host setting.", "Use model."
        ),
    )

    with pytest.raises(MusicDeckError) as raised:
        intel.AmplifierIntelligence().run(intel.ModelRequest(prompt=PROMPT))

    error = raised.value
    assert error.code == "invalid_input"
    assert "unregistered host setting" in error.message
    assert "AMPLIFIER_AGENT_" in error.remedy


def test_a_turn_that_raises_is_the_same_refusal(monkeypatch):
    install_fake_engine(
        monkeypatch,
        raise_on_run=FakeAgentError("closed", "The session is closed.", "Open one."),
    )

    with pytest.raises(MusicDeckError) as raised:
        intel.AmplifierIntelligence().run(intel.ModelRequest(prompt=PROMPT))

    assert raised.value.code == "closed"


def test_a_successful_turn_with_no_words_is_not_an_answer(monkeypatch):
    install_fake_engine(
        monkeypatch, result=FakeTurnResult(state="success", content=[FakeTextPart("   ")])
    )

    with pytest.raises(MusicDeckError) as raised:
        intel.AmplifierIntelligence().run(intel.ModelRequest(prompt=PROMPT))

    assert raised.value.code == "model_did_not_run"


# --------------------------------------------------------------------------- #
# What the caller is told it cost
# --------------------------------------------------------------------------- #
def test_usage_is_totalled_across_entries_and_the_real_model_is_reported(monkeypatch):
    """The provider's own answer to "what did you run?" beats what was asked for.

    Observed live: asking ``openai`` for ``gpt-5`` reported
    ``gpt-5-2025-08-07``. Reporting the request rather than the answer would
    make the usage block a record of the intention, not of the spend.
    """
    install_fake_engine(
        monkeypatch,
        result=FakeTurnResult(
            state="success",
            content=[FakeTextPart("half "), FakeTextPart("a reply")],
            usage=FakeUsage(
                [
                    FakeUsageEntry(
                        provider="openai",
                        model="gpt-5-2025-08-07",
                        tokens_in=100,
                        tokens_out=7,
                        cost={"USD": Decimal("0.0001")},
                    ),
                    FakeUsageEntry(
                        provider="openai",
                        model="gpt-5-2025-08-07",
                        tokens_in=5,
                        tokens_out=None,
                        cost={"USD": Decimal("0.0002")},
                    ),
                ]
            ),
        ),
    )

    result = intel.AmplifierIntelligence().run(intel.ModelRequest(prompt=PROMPT))

    assert result.text == "half a reply"
    assert result.provider == "anthropic"  # what preflight chose, not the entry's
    assert result.model == "gpt-5-2025-08-07"
    assert result.tokens_in == 105
    assert result.tokens_out == 7
    assert result.cost_usd == Decimal("0.0003")
    assert result.usage()["cost_usd"] == "0.0003"


def test_a_provider_that_reports_no_usage_is_ordinary_not_an_error(monkeypatch):
    """Measured: a failed Anthropic call reported every usage field as ``None``."""
    install_fake_engine(
        monkeypatch,
        result=FakeTurnResult(
            state="success", content=[FakeTextPart("a reply")], usage=None
        ),
    )

    result = intel.AmplifierIntelligence().run(intel.ModelRequest(prompt=PROMPT))

    assert result.tokens_in == 0
    assert result.tokens_out == 0
    assert result.cost_usd is None
    assert result.model == "claude-sonnet-5"


# --------------------------------------------------------------------------- #
# Which model gets asked for
# --------------------------------------------------------------------------- #
def test_the_default_model_is_the_chosen_providers_own(monkeypatch):
    ledger = install_fake_engine(monkeypatch)

    intel.AmplifierIntelligence().run(intel.ModelRequest(prompt=PROMPT))

    [options] = ledger.agent_options
    assert options.provider == "anthropic"
    assert options.model == intel.PROVIDER_DEFAULT_MODEL["anthropic"]


def test_the_environment_and_the_argument_both_beat_the_default(monkeypatch):
    ledger = install_fake_engine(monkeypatch)
    engine = intel.AmplifierIntelligence()

    monkeypatch.setenv(intel.MODEL_ENV_VAR, "from-the-environment")
    engine.run(intel.ModelRequest(prompt=PROMPT))
    engine.run(intel.ModelRequest(prompt=PROMPT, model="from-the-argument"))

    assert [options.model for options in ledger.agent_options] == [
        "from-the-environment",
        "from-the-argument",
    ]


def test_every_provider_music_deck_offers_resolves_a_model_or_says_why_not(monkeypatch):
    """No provider may silently resolve somebody else's default.

    The library's own default is ``anthropic``/``claude-sonnet-5`` *together*, so
    a provider with no model of its own would quietly ask an OpenAI or Azure
    account for an Anthropic model. Either music-deck knows a model for a
    provider, or it refuses naming ``MUSIC_DECK_MODEL``. There is no third case.
    """
    monkeypatch.delenv(intel.MODEL_ENV_VAR, raising=False)
    engine = intel.AmplifierIntelligence()

    for provider in intel.PROVIDER_ORDER:
        if provider in intel.PROVIDER_DEFAULT_MODEL:
            assert engine.model_for(provider) == intel.PROVIDER_DEFAULT_MODEL[provider]
            continue
        with pytest.raises(MusicDeckError) as raised:
            engine.model_for(provider)
        assert intel.MODEL_ENV_VAR in raised.value.remedy
        assert provider in raised.value.message


def test_azure_openai_is_the_provider_with_no_default(monkeypatch):
    """Named explicitly, so adding a fifth provider cannot pass by omission."""
    monkeypatch.delenv(intel.MODEL_ENV_VAR, raising=False)

    assert set(intel.PROVIDER_ORDER) - set(intel.PROVIDER_DEFAULT_MODEL) == {"azure-openai"}


# --------------------------------------------------------------------------- #
# The structural promises MD-10 exists to keep
# --------------------------------------------------------------------------- #
def test_the_engine_is_imported_inside_a_function_never_at_module_scope():
    """cli.v1 Core 2, held over the syntax tree rather than over a subprocess.

    The subprocess probes in ``test_plan_refusal.py`` prove the consequence:
    importing music_deck loads no engine. This proves the cause, which is what
    a future edit would break first.
    """
    tree = ast.parse((PACKAGE_ROOT / "intelligence.py").read_text(encoding="utf-8"))

    def names_the_engine(node: ast.stmt) -> bool:
        if isinstance(node, ast.ImportFrom):
            return (node.module or "").startswith("amplifier_agent")
        if isinstance(node, ast.Import):
            return any(alias.name.startswith("amplifier_agent") for alias in node.names)
        return False

    offences = [
        f"line {node.lineno}: {ast.unparse(node)}"
        for node in tree.body
        if names_the_engine(node)
    ]

    assert offences == [], f"engine imported at module scope: {offences}"
    # And the import that does exist is inside a function body, not merely absent.
    assert any(
        names_the_engine(node)
        for function in ast.walk(tree)
        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
        for node in ast.walk(function)
    ), "no engine import anywhere -- this test would pass on a file that boots nothing"


def test_no_private_engine_internals_survive_anywhere_in_the_package():
    """The whole point of MD-10, as a grep the acceptance criteria name.

    Each of these was a real import before the migration. A module named
    ``_runtime``, a cached bundle loader, a hand-edited mount plan -- none of
    them is part of the library's documented surface, and all of them were free
    to change under music-deck without notice.
    """
    banned = re.compile(
        r"amplifier_agent_lib|amplifier_agent_cli|mount_plan|make_turn_handler|"
        r"load_and_prepare_cached"
    )

    offences = [
        f"{path.relative_to(REPO_ROOT)}:{number}: {line.strip()}"
        for path in sorted(PACKAGE_ROOT.rglob("*.py"))
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if banned.search(line)
    ]

    assert offences == [], f"private engine internals still referenced: {offences}"


def test_the_package_name_the_preflight_looks_for_is_the_one_that_installs():
    """``ENGINE_PACKAGE`` is what ``find_spec`` asks for; the requirement installs it.

    They are different spellings of the same thing -- an import name and a
    distribution name -- and a mismatch is invisible until somebody follows the
    remedy and the refusal does not go away.
    """
    assert intel.ENGINE_PACKAGE == "amplifier_agent"
    assert intel.ENGINE_REQUIREMENT.startswith("amplifier-agent @ git+")
    assert "@v1" in intel.ENGINE_REQUIREMENT
    assert "#subdirectory=packages/python" in intel.ENGINE_REQUIREMENT
    assert intel.ENGINE_REQUIREMENT in intel.ENGINE_INSTALL_HINT
    assert intel.ENGINE_INSTALL_HINT.startswith("uv tool install")


def test_the_python_floor_matches_the_engine_the_tool_runs_on():
    """The library requires 3.12; a floor that admits 3.11 admits a broken install."""
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert 'requires-python = ">=3.12"' in pyproject
    assert sys.version_info >= (3, 12)


def test_the_engine_is_not_a_dependency_of_a_deterministic_install():
    """cli.v1 Core 2: the forty other verbs install without any of this.

    Read as parsed TOML rather than as text, so the prose explaining *why* the
    engine is absent cannot be mistaken for the engine being present.
    """
    import tomllib

    metadata = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    base = metadata["project"]["dependencies"]

    assert base == ["pyyaml>=6.0"], f"a model-stack dependency crept into base: {base}"
    assert "amplifier-agent" not in metadata["project"].get("optional-dependencies", {})


def test_an_installed_copy_imports_no_engine_and_no_provider_sdk(tmp_path):
    """The consequence, in a subprocess, from a directory with no checkout in it."""
    probe = (
        "import music_deck, sys, json;"
        "print(json.dumps(sorted(m for m in sys.modules if m.split('.')[0] in "
        "{'amplifier_agent','amplifier_agent_lib','amplifier_agent_cli','anthropic',"
        "'openai','google','httpx'})))"
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
