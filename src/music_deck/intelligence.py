"""The model seam: one protocol, one shipped implementation, one refusal.

``plan`` is the only verb that reaches a model (``cli.v1`` Core 3), and it
reaches it only through the ``Intelligence`` protocol below. A capability
depends on this protocol, never on a provider SDK, so swapping the model layer
-- or standing in for it in a test -- means supplying a different object with
these three members and passing it in. Nothing else changes.

Three properties this module is responsible for, each of them load-bearing:

**Nothing is imported until a turn actually runs.** ``cli.v1`` Core 2 promises
the other forty verbs run "with no provider configured and no provider SDK
installed", so every engine and provider import in this file sits inside a
function body, and ``preflight`` establishes what is installed with
``importlib.util.find_spec``, which answers without importing. ``import
music_deck`` therefore pulls in no part of the model stack at all. (Measured on
2026-09-06: ``import amplifier_agent`` adds 50 modules in ~30 ms and mutates no
environment variable. Cheap is not free, and a deterministic verb should pay
neither -- the promise is about what a caller is charged for, not about how
large the charge happens to be this week.)

**A refusal happens before any prompt is built.** ``preflight`` is a separate
method from ``run`` for exactly that reason: ``plan`` calls it first, and a
caller with nothing configured gets a precise refusal (exit 3) naming the
missing precondition -- rather than an authentication error thrown from deep
inside a provider module after a prompt was assembled, or worse, a quiet
fallback to a deterministic answer.

**A turn is text in, text out -- by construction, not by housekeeping.** The
shipped implementation builds an agent with no tools, no skills, no MCP servers
and **no approvals channel**. The library's own rule (its
``docs/concepts/approvals.md``: "approvals absent -> there is no channel") is
that a consequential action then fails ``approval_unavailable`` rather than
proceeding; nothing is ever inferred to be allowed. So "the model cannot read,
write, or fetch anything" is the library's documented default rather than a
list of things music-deck remembered to switch off -- which matters here more
than in most tools, because ``boundary.v1`` Core 2 forbids Spotify content
reaching a model at all, and a model holding a fetch tool could pull in exactly
what that clause forbids handing it.

An explicit ``approvals="deny"`` was considered as a second line of defence and
deliberately not used: it is not equivalent (it ends a turn at its first tool
request with ``approval_denied`` rather than ``approval_unavailable``), so it
would change observable behaviour while adding no safety the absent channel does
not already give. Fewer moving parts, one documented guarantee.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final, Protocol

from music_deck.errors import MusicDeckError, NoProviderError
from music_deck.setup_guide import install_with

# --------------------------------------------------------------------------- #
# Providers -- names, credentials, packages, extras
# --------------------------------------------------------------------------- #
PROVIDER_ENV_VAR: Final = "MUSIC_DECK_PROVIDER"
"""Pin a provider instead of auto-selecting one."""

MODEL_ENV_VAR: Final = "MUSIC_DECK_MODEL"
"""Pin a model within the chosen provider."""

PROVIDER_ORDER: Final[tuple[str, ...]] = ("anthropic", "openai", "gemini", "azure-openai")
"""Auto-selection order: the first whose credential is set in the environment."""

PROVIDER_CREDENTIAL_ENV: Final[dict[str, tuple[str, ...]]] = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "gemini": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    "azure-openai": ("AZURE_OPENAI_API_KEY",),
}

# A provider counts as usable only when its client library is importable too.
# A credential alone resolves a provider the engine then fails to mount, which
# reads to a caller as a model that answered badly rather than one that never
# ran -- and a plan nobody can trust is worse than a refusal anybody can fix.
PROVIDER_PACKAGES: Final[dict[str, tuple[str, ...]]] = {
    "anthropic": ("anthropic",),
    "openai": ("openai",),
    "gemini": ("google.genai", "google.generativeai"),
    "azure-openai": ("openai",),
}

PROVIDER_EXTRA: Final[dict[str, str]] = {
    "anthropic": "anthropic",
    "openai": "openai",
    "gemini": "gemini",
    "azure-openai": "azure-openai",
}
"""The ``music-deck[<extra>]`` that installs a provider's stack. Never a base
dependency: ``cli.v1`` Core 2 promises the deterministic verbs need none."""

PROVIDER_SDK_PACKAGE: Final[dict[str, str]] = {
    "anthropic": "anthropic",
    "openai": "openai",
    "gemini": "google-genai",
    "azure-openai": "openai",
}
"""The distribution name to add to the tool environment for each provider. The
extra above is the right answer for a ``pip``/``uv sync`` install; a uv **tool**
install has no extras to add after the fact, so the package is named directly
in ``uv tool install --force --with <package>``."""

PROVIDER_DEFAULT_MODEL: Final[dict[str, str]] = {
    "anthropic": "claude-sonnet-5",
    "openai": "gpt-5.6-luna",
    "gemini": "gemini-2.5-flash",
}
"""The model music-deck asks for when the caller pins none.

The engine library needs a provider **and** a model: its own defaults are
``anthropic``/``claude-sonnet-5`` together, so naming a provider without a model
resolves an Anthropic model that a non-Anthropic account cannot serve. Each id
here was run live against its provider on 2026-09-06 and answered.

``azure-openai`` is deliberately absent: an Azure selection is a *deployment*
name the account owner chose, so there is no value music-deck could guess that
would be right for anybody. That caller sets ``MUSIC_DECK_MODEL``, and
:meth:`AmplifierIntelligence.model_for` says so rather than sending a guess.

These ids date. When one does, the turn fails loudly with the library's
``selector_rejected`` and the remedy names ``MUSIC_DECK_MODEL`` -- a caller can
fix it themselves, without waiting for this table to be updated."""

ENGINE_PACKAGE: Final = "amplifier_agent"
ENGINE_REQUIREMENT: Final = (
    "amplifier-agent @ git+https://github.com/microsoft/amplifier-agent@v1"
    "#subdirectory=packages/python"
)
ENGINE_INSTALL_HINT: Final = install_with(f'"{ENGINE_REQUIREMENT}"')
"""How to install the engine, in the form the documented install method takes.

``cli.v1`` Core 4: a remedy "names what the reader HAS: a command their install
method takes". music-deck is installed with ``uv tool install``, and a tool
install owns a virtualenv ``uv pip install`` has no way to name -- so a remedy
saying ``uv pip install`` is unusable by exactly the reader who needs it. The
``uv tool install --force --with`` form adds a package to that environment,
which is why every install remedy here is built from ``setup_guide.install_with``.

The requirement pins the ``v1`` branch and the ``packages/python`` subdirectory:
the repository root is not a Python distribution, so the plain git URL does not
resolve. This exact spelling was installed from scratch on 2026-09-06 before it
was written down here.

The engine is deliberately *not* a music-deck extra. It is not on PyPI, so
declaring it would put a git URL in this package's own metadata and make every
``uv sync`` -- including the forty deterministic verbs' -- fetch a moving branch
over the network before it could resolve. ``cli.v1`` Core 2 promises those verbs
need no part of the model stack; an unconditional dependency on a git ref is
exactly the quiet cost that promise exists to prevent."""

ENGINE_INSTALL_HINT_PIP: Final = f'uv pip install "{ENGINE_REQUIREMENT}"'
"""The same thing for a copy installed into a virtualenv with pip rather than as
a uv tool. Offered second: the tool install is the documented method."""



# --------------------------------------------------------------------------- #
# What crosses the seam
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ModelRequest:
    """One fully assembled prompt, and how the caller wants it answered.

    The prompt arrives assembled. Nothing below this line adds a word to it --
    which is what lets ``boundary.v1`` Core 3's transcript be the whole truth
    about what was sent.
    """

    prompt: str
    provider: str | None = None
    model: str | None = None


@dataclass(frozen=True)
class ModelResult:
    """One completed turn: the reply, and what it cost."""

    text: str
    provider: str = ""
    model: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: Decimal | None = None

    def usage(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": None if self.cost_usd is None else str(self.cost_usd),
        }


class Intelligence(Protocol):
    """Turns an assembled prompt into text, and says up front when it cannot."""

    implementation: str

    def preflight(self, provider: str | None = None) -> str:
        """Name the provider that will serve a request, or refuse.

        Called before any prompt is built, so a caller with nothing configured
        gets a precise refusal instead of a failure from inside a provider
        module. Raises ``NoProviderError`` (exit 3) naming the missing
        precondition and how to fix it.
        """
        ...

    def run(self, request: ModelRequest) -> ModelResult:
        """Run one turn to completion. The prompt is sent exactly as given."""
        ...


# --------------------------------------------------------------------------- #
# The refusal -- cli.v1 Core 3, exit 3
# --------------------------------------------------------------------------- #
MISSING_ENGINE: Final = "engine"
MISSING_PROVIDER: Final = "provider"
MISSING_CREDENTIALS: Final = "credentials"
MISSING_PROVIDER_SDK: Final = "provider_sdk"

PRECONDITIONS: Final[tuple[str, ...]] = (
    MISSING_PROVIDER,
    MISSING_CREDENTIALS,
    MISSING_PROVIDER_SDK,
    MISSING_ENGINE,
)
"""Every precondition a refusal may name. ``cli.v1`` Core 3 names the first
three; ``engine`` is the substrate itself, the fourth way to have no usable
model, and it refuses the same way for the same reason."""


class NoModelSubstrate(NoProviderError):
    """No usable model substrate -- ``cli.v1`` Core 3, exit ``3``.

    Carries ``missing``: which of ``PRECONDITIONS`` is absent, so a caller can
    branch on the cause without parsing prose, and the envelope says which one
    out loud.
    """

    def __init__(self, missing: str, message: str, remedy: str) -> None:
        super().__init__(message, remedy)
        self.missing = missing
        self.extra = {"missing": missing}


# --------------------------------------------------------------------------- #
# Deterministic environment questions -- asked without importing anything
# --------------------------------------------------------------------------- #
def credential_env_var(provider: str) -> str | None:
    """The environment variable holding this provider's credential, if set."""
    for name in PROVIDER_CREDENTIAL_ENV.get(provider, ()):
        if os.environ.get(name, "").strip():
            return name
    return None


def credentialled_providers() -> list[str]:
    """Providers whose credential is set here, in auto-selection order."""
    return [name for name in PROVIDER_ORDER if credential_env_var(name) is not None]


def missing_package(provider: str) -> str | None:
    """The client library this provider needs and this environment lacks.

    Uses ``find_spec``: it answers "is it installed?" without importing it, so
    asking the question costs nothing and mutates nothing.
    """
    from importlib.util import find_spec

    candidates = PROVIDER_PACKAGES.get(provider)
    if not candidates:
        return None
    for candidate in candidates:
        try:
            if find_spec(candidate) is not None:
                return None
        except (ImportError, ValueError):
            continue
    return candidates[0].split(".")[0]


def engine_installed() -> bool:
    """Whether the amplifier-agent engine library is importable here."""
    from importlib.util import find_spec

    try:
        return find_spec(ENGINE_PACKAGE) is not None
    except (ImportError, ValueError):
        return False


def available_providers() -> list[str]:
    """Providers this host could actually run: credential and client both."""
    return [name for name in credentialled_providers() if missing_package(name) is None]


# --------------------------------------------------------------------------- #
# The shipped implementation
# --------------------------------------------------------------------------- #
class AmplifierIntelligence:
    """Runs a prompt through the amplifier-agent engine, embedded in-process.

    In-process, not a subprocess: a CLI shelled out to would be a second place
    prompts are assembled and a second place they could be logged, and
    ``boundary.v1`` Core 3 promises the transcript music-deck prints is the
    whole of what was sent.
    """

    implementation = "amplifier-agent"

    def preflight(self, provider: str | None = None) -> str:
        """The provider that will serve a request, or ``NoModelSubstrate``.

        Order of questions is deliberate: which provider, then its credential,
        then its client library, then the engine. Each answer is the thing the
        caller must fix before the next question is even meaningful.
        """
        pinned = (provider or os.environ.get(PROVIDER_ENV_VAR) or "").strip() or None

        if pinned is not None and pinned not in PROVIDER_ORDER:
            raise NoModelSubstrate(
                MISSING_PROVIDER,
                f"Model provider {pinned!r} is not one music-deck knows.",
                f"Set {PROVIDER_ENV_VAR} to one of: {', '.join(PROVIDER_ORDER)}; "
                f"or unset it and music-deck picks the first provider whose "
                f"credential is set.",
            )

        if pinned is not None:
            if credential_env_var(pinned) is None:
                names = " or ".join(PROVIDER_CREDENTIAL_ENV[pinned])
                raise NoModelSubstrate(
                    MISSING_CREDENTIALS,
                    f"Model provider {pinned!r} is pinned by {PROVIDER_ENV_VAR} but "
                    f"has no credential in this environment.",
                    f"Set {names}, or pin a different provider with "
                    f"{PROVIDER_ENV_VAR}. music-deck stores no credential of its own.",
                )
            chosen = pinned
        else:
            credentialled = credentialled_providers()
            if not credentialled:
                raise NoModelSubstrate(
                    MISSING_PROVIDER,
                    "`plan` is model-backed and no model provider is configured.",
                    "Set ANTHROPIC_API_KEY (or OPENAI_API_KEY, GOOGLE_API_KEY, "
                    f"AZURE_OPENAI_API_KEY), or pin one with {PROVIDER_ENV_VAR}. "
                    "Every other verb runs with no provider at all.",
                )
            chosen = credentialled[0]

        absent = missing_package(chosen)
        if absent is not None:
            extra = PROVIDER_EXTRA.get(chosen, chosen)
            package = PROVIDER_SDK_PACKAGE.get(chosen, absent)
            raise NoModelSubstrate(
                MISSING_PROVIDER_SDK,
                f"Model provider {chosen!r} has a credential here but its Python "
                f"SDK ({absent}) is not installed.",
                f"Add it to music-deck's own environment: {install_with(package)}"
                f" -- that is the form a `uv tool install` takes, and the only one "
                f"that reaches the tool's virtualenv. If you installed music-deck "
                f"into a virtualenv instead, the extra works there: "
                f'uv pip install "music-deck[{extra}]". '
                "It is an extra and not a base dependency because every verb except "
                "`plan` runs without it.",
            )

        if not engine_installed():
            raise NoModelSubstrate(
                MISSING_ENGINE,
                f"The amplifier-agent engine library ({ENGINE_PACKAGE}) is not "
                f"installed, so there is nothing to run the turn.",
                f"Add it to music-deck's own environment: {ENGINE_INSTALL_HINT}. "
                f"In a virtualenv install instead: {ENGINE_INSTALL_HINT_PIP}.",
            )

        return chosen

    def model_for(self, provider: str, requested: str | None = None) -> str:
        """The model id this turn will ask for, or a refusal naming how to set one.

        Three sources, in the order a caller expects: the argument, the
        ``MUSIC_DECK_MODEL`` environment variable, then
        :data:`PROVIDER_DEFAULT_MODEL`. When none of them answers -- today only
        ``azure-openai``, whose selection is a deployment name its owner chose --
        this refuses rather than letting the engine's own default resolve an
        Anthropic model against somebody else's account, which fails several
        layers down as an opaque provider error.
        """
        pinned = (requested or os.environ.get(MODEL_ENV_VAR) or "").strip() or None
        if pinned is not None:
            return pinned

        default = PROVIDER_DEFAULT_MODEL.get(provider)
        if default is not None:
            return default

        raise MusicDeckError(
            "model_not_selected",
            f"Model provider {provider!r} has no model music-deck can pick for "
            f"you: an Azure OpenAI selection is the deployment name you chose "
            f"when you created it, so only you know it.",
            f"Set {MODEL_ENV_VAR} to that deployment's model id and run again.",
            provider=provider,
        )

    def run(self, request: ModelRequest) -> ModelResult:
        """Run one turn. Call from synchronous code; each call owns its loop."""
        import asyncio

        return asyncio.run(self.run_async(request))

    async def run_async(self, request: ModelRequest) -> ModelResult:
        """One turn through the engine library's documented public API.

        Everything the boundary depends on is visible in the ``AgentOptions``
        below: no ``tools``, no ``skills``, no ``mcp_servers``, and no
        ``approvals``. Those are the library's defaults, and its approvals rule
        makes them fail-closed -- with no channel, a consequential action fails
        ``approval_unavailable`` instead of proceeding. music-deck strips
        nothing and overrides nothing to get that; it simply asks for an agent
        that has nothing to reach with.
        """
        import tempfile

        provider = self.preflight(request.provider)
        model = self.model_for(provider, request.model)

        # The engine import lives here, not at module level: cli.v1 Core 2
        # promises the forty deterministic verbs pay for no part of the model
        # stack, and `tests/test_plan_refusal.py` holds that promise to a
        # subprocess that imports music_deck and lists what came with it.
        from amplifier_agent import (
            AgentError,
            AgentOptions,
            SessionOptions,
            TextPart,
            TurnInput,
            create_agent,
        )

        # boundary.v1 Core 8 forbids a persistent store, and the library writes
        # durable transcripts under a storage root it picks (`~/.amplifier-agent`
        # by default). An ephemeral session writes nothing there -- measured --
        # but "nothing was written to a directory that does not outlive the
        # turn" is a stronger sentence than "nothing was written", and it is the
        # one a reviewer can check without trusting either of us.
        with tempfile.TemporaryDirectory(prefix="music-deck-agent-") as storage:
            options = AgentOptions(provider=provider, model=model, storage=storage)
            try:
                agent = await create_agent(options)
            except AgentError as failure:
                raise _engine_failure(failure, provider, model) from failure

            try:
                async with agent:
                    # Ephemeral, not durable: boundary.v1 Core 8 again. Durable is
                    # this library's default, so this argument is not decoration --
                    # omitting it would leave a resumable transcript on disk.
                    session = await agent.create_session(
                        SessionOptions(persistence="ephemeral")
                    )
                    async with session:
                        result = await session.run(
                            TurnInput(content=[TextPart(request.prompt)])
                        )
            except AgentError as failure:
                raise _engine_failure(failure, provider, model) from failure

        if result.error is not None or result.state != "success":
            raise _turn_failure(result, provider, model)

        reply = "".join(part.text for part in (result.content or []))
        if not reply.strip():
            # A turn that succeeded and said nothing is not an answer. Handing
            # the empty string on would present a model that never spoke as one
            # that answered badly, three layers down in the plan validator.
            raise MusicDeckError(
                "model_did_not_run",
                f"The agent engine reported a successful turn with no reply "
                f"from {provider}.",
                "Run `music-deck check` to confirm the provider is configured, "
                "then run `music-deck plan` again.",
            )

        tokens_in, tokens_out, cost, actual_model = _read_usage(result.usage)
        return ModelResult(
            text=reply,
            provider=provider,
            model=actual_model or model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
        )


# --------------------------------------------------------------------------- #
# Reading what the engine gave back
# --------------------------------------------------------------------------- #
def _read_usage(usage: Any) -> tuple[int, int, Decimal | None, str | None]:
    """Totals across every usage entry, plus the model the engine really used.

    Every field here is optional in the library's records -- a provider that
    reports no token counts is ordinary, not an error -- so absent means zero
    for the counts and ``None`` for the cost, never a crash and never a
    fabricated number. The model is taken from the first entry because that is
    the provider's own answer to "what did you actually run?", which may be more
    specific than what was asked for (``gpt-5`` came back as
    ``gpt-5-2025-08-07``).
    """
    entries = list(getattr(usage, "entries", None) or ())
    tokens_in = sum(int(getattr(entry, "tokens_in", 0) or 0) for entry in entries)
    tokens_out = sum(int(getattr(entry, "tokens_out", 0) or 0) for entry in entries)

    total: Decimal | None = None
    for entry in entries:
        for amount in (getattr(entry, "cost", None) or {}).values():
            total = (total or Decimal(0)) + Decimal(str(amount))

    actual = next((getattr(entry, "model", None) for entry in entries), None)
    return tokens_in, tokens_out, total, actual


def _engine_failure(failure: Any, provider: str, model: str) -> MusicDeckError:
    """An ``AgentError`` from the library, in music-deck's envelope.

    The library's own ``code`` and ``remedy`` are carried through rather than
    replaced: ``cli.v1`` Core 4 wants a remedy its reader can act on, and the
    layer that knows why an agent could not be built is the layer that failed to
    build it. music-deck adds only what the library cannot know -- which
    provider and model it was asked for, and where the caller sets them.
    """
    code = str(getattr(failure, "code", "") or "engine_failed")
    message = str(getattr(failure, "message", "") or failure)
    remedy = str(getattr(failure, "remedy", "") or "").strip()
    return MusicDeckError(
        code,
        f"The agent engine refused to run a turn on {provider}/{model}: {message}",
        (
            f"{remedy} music-deck asked for provider {provider!r} and model "
            f"{model!r}; pin either with {PROVIDER_ENV_VAR} and {MODEL_ENV_VAR}. "
            f"Host settings named AMPLIFIER_AGENT_* are read by the engine "
            f"itself and can refuse a turn before music-deck sees it."
        ).strip(),
        provider=provider,
        model=model,
    )


def _turn_failure(result: Any, provider: str, model: str) -> MusicDeckError:
    """A turn that reached a terminal state other than success.

    ``state`` alone is not enough and neither is ``error`` alone: a rejected
    turn carries a reason, and a failed selection was observed carrying *both*
    an error and plausible-looking content. Refusing on either is what stops a
    half-answer being composed into a plan.
    """
    failure = getattr(result, "error", None)
    state = str(getattr(result, "state", "unknown"))
    if failure is None:
        return MusicDeckError(
            "model_did_not_run",
            f"The agent engine ended the turn {state!r} on {provider}/{model} "
            f"without saying why.",
            "Run `music-deck check`, then run `music-deck plan` again.",
            provider=provider,
            model=model,
        )
    return _engine_failure(failure, provider, model)


def default_intelligence() -> Intelligence:
    """The implementation music-deck ships with."""
    return AmplifierIntelligence()


def resolve(intelligence: Intelligence | None) -> Intelligence:
    """The caller's implementation, or the shipped one."""
    return intelligence if intelligence is not None else default_intelligence()


__all__ = [
    "AmplifierIntelligence",
    "ENGINE_INSTALL_HINT",
    "ENGINE_PACKAGE",
    "ENGINE_REQUIREMENT",
    "Intelligence",
    "MISSING_CREDENTIALS",
    "MISSING_ENGINE",
    "MISSING_PROVIDER",
    "MISSING_PROVIDER_SDK",
    "MODEL_ENV_VAR",
    "ModelRequest",
    "ModelResult",
    "NoModelSubstrate",
    "PRECONDITIONS",
    "PROVIDER_CREDENTIAL_ENV",
    "PROVIDER_DEFAULT_MODEL",
    "PROVIDER_ENV_VAR",
    "PROVIDER_EXTRA",
    "PROVIDER_ORDER",
    "PROVIDER_PACKAGES",
    "available_providers",
    "credential_env_var",
    "credentialled_providers",
    "default_intelligence",
    "engine_installed",
    "missing_package",
    "resolve",
]
