"""The model seam: one protocol, one shipped implementation, one refusal.

``plan`` is the only verb that reaches a model (``cli.v1`` Core 3), and it
reaches it only through the ``Intelligence`` protocol below. A capability
depends on this protocol, never on a provider SDK, so swapping the model layer
-- or standing in for it in a test -- means supplying a different object with
these three members and passing it in. Nothing else changes.

Three properties this module is responsible for, each of them load-bearing:

**Nothing is imported until a turn actually runs.** Importing
``amplifier_agent_lib`` rewrites ``os.environ["AMPLIFIER_HOME"]``, and
``cli.v1`` Core 2 promises the other forty verbs run "with no provider
configured and no provider SDK installed". So every engine and provider import
in this file sits inside a function body, and ``preflight`` establishes what is
installed with ``importlib.util.find_spec``, which answers without importing.
``import music_deck`` therefore pulls in no provider stack at all.

**A refusal happens before any prompt is built.** ``preflight`` is a separate
method from ``run`` for exactly that reason: ``plan`` calls it first, and a
caller with nothing configured gets a precise refusal (exit 3) naming the
missing precondition -- rather than an authentication error thrown from deep
inside a provider module after a prompt was assembled, or worse, a quiet
fallback to a deterministic answer.

**A turn is text in, text out.** The shipped implementation strips the vendored
bundle's tools, sub-agents and hooks before booting the engine and declines
approval for anything that somehow asks. That makes "the model cannot read,
write, or fetch anything" a property of the engine rather than a promise in a
prompt -- which matters here more than in most tools, because
``boundary.v1`` Core 2 forbids Spotify content reaching a model at all. A model
that could call a tool could fetch what this contract forbids handing it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final, Protocol

from music_deck.errors import MusicDeckError, NoProviderError

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

ENGINE_PACKAGE: Final = "amplifier_agent_lib"
ENGINE_INSTALL_HINT: Final = (
    'uv pip install "amplifier-agent @ git+https://github.com/microsoft/amplifier-agent@main"'
)
"""How to install the engine. It is deliberately *not* a music-deck extra: it is
not on PyPI, and it requires Python >= 3.12 where music-deck supports >= 3.11 --
declaring it here would make `uv sync` unsatisfiable for a 3.11 caller who only
ever wanted the deterministic verbs."""

WORKSPACE: Final = "music-deck"


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
            raise NoModelSubstrate(
                MISSING_PROVIDER_SDK,
                f"Model provider {chosen!r} has a credential here but its Python "
                f"SDK ({absent}) is not installed.",
                f'Install the matching extra: uv pip install "music-deck[{extra}]". '
                "It is an extra and not a base dependency because every verb except "
                "`plan` runs without it.",
            )

        if not engine_installed():
            raise NoModelSubstrate(
                MISSING_ENGINE,
                f"The amplifier-agent engine library ({ENGINE_PACKAGE}) is not "
                f"installed, so there is nothing to run the turn.",
                f"Install it alongside music-deck: {ENGINE_INSTALL_HINT} "
                f"(it needs Python >= 3.12).",
            )

        return chosen

    def run(self, request: ModelRequest) -> ModelResult:
        """Run one turn. Call from synchronous code; each call owns its loop."""
        import asyncio

        return asyncio.run(self.run_async(request))

    async def run_async(self, request: ModelRequest) -> ModelResult:
        import sys
        import uuid

        provider = self.preflight(request.provider)
        model = request.model or os.environ.get(MODEL_ENV_VAR) or None

        # Every engine import lives here, not at module level: importing
        # amplifier_agent_lib rewrites os.environ["AMPLIFIER_HOME"], and forty
        # deterministic verbs must never pay for that.
        from amplifier_agent_cli.provider_sources import inject_provider, inject_routing_matrix
        from amplifier_agent_lib import __version__
        from amplifier_agent_lib._runtime import make_turn_handler
        from amplifier_agent_lib.bundle.cache import load_and_prepare_cached
        from amplifier_agent_lib.engine import Engine
        from amplifier_agent_lib.protocol import PROTOCOL_VERSION, server_default_capabilities
        from amplifier_agent_lib.protocol_points.defaults_cli import (
            ApprovalOverride,
            CliApprovalSystem,
            CliDisplaySystem,
        )

        prepared = await load_and_prepare_cached(aaa_version=__version__)

        # The vendored bundle declares provider stubs, and injection is a no-op
        # while any provider is mounted; without this clear, the injection below
        # is silently discarded.
        prepared.mount_plan["providers"] = []
        # Text in, text out. Unmounting the tools and sub-agents makes that a
        # property of the engine rather than a promise in a prompt -- and here
        # that is the difference between a contract and a hope, because a model
        # holding a fetch tool could pull in exactly the Spotify content
        # boundary.v1 Core 2 forbids putting in front of it. The hooks go too:
        # each is a third-party module observing a session this tool has not
        # got, whose failure to load would fail the turn.
        prepared.mount_plan["tools"] = []
        prepared.mount_plan["agents"] = {}
        prepared.mount_plan["hooks"] = []
        inject_provider(prepared, provider, model_override=model)
        inject_routing_matrix(prepared, provider)

        handler = make_turn_handler(
            prepared, cwd=None, is_resumed=False, workspace=WORKSPACE
        )
        engine = Engine(
            turn_handler=handler,
            protocol_points={
                # Nothing that could ask for approval is mounted. Declining
                # anything that somehow does keeps the unmounting from being the
                # only defence.
                "approval": CliApprovalSystem(override=ApprovalOverride.NO),
                # cli.v1 Core 4: diagnostics go to stderr, never to stdout --
                # stdout carries one JSON document and nothing else.
                "display": CliDisplaySystem(stream=sys.stderr, verbosity="quiet"),
            },
        )
        await engine.boot(
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": dict(server_default_capabilities()),
                "sessionId": "",
                "resume": False,
            },
            bundle_override=prepared,
        )
        try:
            result: dict[str, Any] = await engine.submit_turn(
                {
                    "sessionId": "",
                    "turnId": f"turn-{uuid.uuid4().hex}",
                    "prompt": request.prompt,
                }
            )
        finally:
            await engine.shutdown()

        tokens_in = int(result.get("tokensIn") or 0)
        tokens_out = int(result.get("tokensOut") or 0)
        reply = result.get("reply") or ""
        if tokens_in == 0 and tokens_out == 0:
            # The engine reports a mount failure as a reply rather than raising.
            # Passing that on as an answer would present a tool that never ran
            # as a model that answered badly.
            raise MusicDeckError(
                "model_did_not_run",
                f"The agent engine returned without reaching a model: "
                f"{reply or 'no reply'}",
                "Check that the chosen provider's credential and client library "
                "are both present, then run `music-deck check`.",
            )

        cost = result.get("costUsd")
        return ModelResult(
            text=reply,
            provider=provider,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost if isinstance(cost, Decimal) or cost is None else Decimal(str(cost)),
        )


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
