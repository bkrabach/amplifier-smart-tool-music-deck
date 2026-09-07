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

**A turn carries exactly the tools the caller declared, and nothing else.**
``ModelRequest.tools`` decides the shape of the turn. Empty -- what ``plan``
sends -- builds an agent with no tools, no skills, no MCP servers and **no
approvals channel**, which is text in and text out by construction: the
library's own rule (its ``docs/concepts/approvals.md``: "approvals absent ->
there is no channel") is that a tool effect then fails ``approval_unavailable``
rather than proceeding, so nothing is ever inferred to be allowed.

Non-empty -- what ``do`` sends -- turns each :class:`ToolSpec` into an engine
``Tool`` whose handler runs *here*, against music-deck's own library functions.
That is not decoration: on 2026-09-06 a real model, handed a prompt that merely
*described* tools, made a native tool call, and the engine refused the turn --
``provider_failed``, "The provider requested an undeclared tool". A tool a model
is told about must be a tool the engine was told about.

Declaring one forces the approvals question, because the engine asks its
authority before every call and answers ``"unavailable"`` when there is none.
:func:`_static_approval_policy` is the answer and carries the reasoning,
including the measured reason a bare ``approvals="allow"`` is unsafe: the engine
registers its own built-ins -- ``bash``, ``write``, ``web_fetch`` and the rest --
alongside the caller's, so "allow" is far wider than "allow music-deck's tools".

**A turn is decided here, not by the caller's shell.** The engine resolves its
configuration from the process environment and refuses a turn over anything it
does not recognise there -- so a variable music-deck neither documents nor uses
could fail ``plan`` outright, and one of them (``AMPLIFIER_AGENT_STORAGE``)
could move the transcript somewhere durable that ``boundary.v1`` Core 8
forbids. music-deck honours none of that namespace and withholds all of it for
the length of the turn; :data:`HOST_SETTING_PREFIX` carries the decision, the
measurements behind it, and why nothing is exempted.

An explicit ``approvals="deny"`` was considered for the no-tools shape as a
second line of defence and deliberately not used: it is not equivalent (it ends
a turn at its first tool request with ``approval_denied`` rather than
``approval_unavailable``), so it would change observable behaviour while adding
no safety the absent channel does not already give. Fewer moving parts, one
documented guarantee.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final, Iterator, Protocol

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
# Host settings -- music-deck honours none of them
# --------------------------------------------------------------------------- #
HOST_SETTING_PREFIX: Final = "AMPLIFIER_AGENT_"
"""The engine library's own environment namespace. music-deck reads none of it,
and -- since :func:`without_host_settings` -- lets none of it reach the engine.

The engine resolves its configuration from the *process* environment, not from
the ``AgentOptions`` it is handed, and refuses a turn over what it finds there.
Measured on 2026-09-06 against the installed engine, three separate refusals a
caller can trip without ever naming music-deck:

* ``AMPLIFIER_AGENT_CONFIG`` pointing at a file that does not exist -- refused
  ``invalid_input``: "config: the configured file does not exist."
* ``AMPLIFIER_AGENT_CONFIG`` pointing at a file that *does* exist and holds a
  key the engine does not register -- refused ``invalid_input``: "unregistered
  host setting." (The steward's own case: their shell sets this variable for
  Amplifier, and every ``music-deck plan`` in that shell failed.)
* Any ``AMPLIFIER_AGENT_*`` variable whose suffix is not one of ``PROVIDER``,
  ``MODEL``, ``STORAGE``, ``WORKSPACE``, ``CONFIG`` (or a ``FACE_``/``ENGINE_``
  /``NODE_`` prefix) -- refused ``invalid_input``: "unregistered host
  environment setting."

**Which of these does music-deck honour? None, deliberately.** Two reasons, and
the second is a contract:

1. music-deck already names everything it needs at the call -- ``provider``,
   ``model`` and ``storage`` are passed in ``AgentOptions``, from
   ``MUSIC_DECK_PROVIDER``/``MUSIC_DECK_MODEL`` and a temporary directory. A
   host setting could only override or contradict a decision music-deck has
   already made and documented. ``cli.v1`` Core 4's remedies name the
   ``MUSIC_DECK_*`` variables; a second, undocumented set of knobs that can
   silently win is not a feature.
2. ``AMPLIFIER_AGENT_STORAGE`` sets the engine's storage root, and
   ``boundary.v1`` Core 8 forbids a persistent store. The temporary directory
   below is how that clause is kept; a variable in the caller's shell able to
   move the transcript somewhere durable would quietly break it. Scrubbing is
   not only about the refusal -- it is how Core 8 stays true in an environment
   music-deck does not control.

A variable music-deck neither documents nor uses must not be able to fail a
verb, so the whole namespace is withheld for the duration of the turn and put
back afterwards."""


def _host_settings() -> dict[str, str]:
    """Every ``AMPLIFIER_AGENT_*`` variable currently in the environment."""
    return {
        name: value
        for name, value in os.environ.items()
        if name.startswith(HOST_SETTING_PREFIX)
    }


@contextmanager
def without_host_settings() -> Iterator[tuple[str, ...]]:
    """Run the block with the engine's whole environment namespace withheld.

    Yields the names that were withheld, in order, so a caller can say what it
    did. The variables are restored in a ``finally``, so an exception inside the
    turn -- a refusal from the engine, a keyboard interrupt -- leaves the
    caller's environment exactly as it was found.

    Narrow on purpose. It withholds one prefix, for the length of one turn, in a
    process that runs exactly one turn: ``run`` owns its own event loop and
    ``plan`` is the only verb that gets here. It does not touch provider
    credentials (``ANTHROPIC_API_KEY`` and its siblings do not carry this
    prefix), which the engine reads from this same environment at the same
    moment and must still find.
    """
    withheld = _host_settings()
    for name in withheld:
        del os.environ[name]
    try:
        yield tuple(sorted(withheld))
    finally:
        os.environ.update(withheld)



# --------------------------------------------------------------------------- #
# What crosses the seam
# --------------------------------------------------------------------------- #
class ToolStop(Exception):
    """A caller's tool asking for the turn to end now, with no further calls.

    The seam's own vocabulary, not the engine's, so a verb can end a turn --
    a ceiling reached, a refusal that is not the model's to correct -- without
    importing ``amplifier_agent``. ``cli.v1`` Core 2 keeps that import inside
    :meth:`AmplifierIntelligence.run_async`; a sentinel declared here is what
    lets ``music_deck.verbs.do`` raise one from a handler anyway.

    :meth:`AmplifierIntelligence.run_async` translates it into the library's
    ``ToolFailed``, which with ``tool_error_policy="stop"`` ends the turn
    instead of handing the model something to correct. The verb that raised it
    already recorded *why*, and publishes that reason rather than the engine's.
    """


@dataclass(frozen=True)
class ToolSpec:
    """One tool a verb offers the model, in music-deck's own terms.

    Deliberately not ``amplifier_agent.Tool``: a capability declares what it can
    do without importing the engine (``cli.v1`` Core 2), and a test double can
    drive these handlers directly without one either.
    :meth:`AmplifierIntelligence.run_async` is the single place this becomes an
    engine ``Tool``.

    ``handler`` is **synchronous** and returns the string the model will see.
    music-deck's library functions are synchronous and one tool runs at a time,
    so there is nothing for an async handler to overlap with; the adapter awaits
    a thin wrapper around this. It may raise :class:`ToolStop` to end the turn.

    ``input_schema`` is JSON Schema draft 2020-12 with ``additionalProperties:
    False`` -- the engine validates it when the agent is built, so a malformed
    schema fails loudly at boot rather than as a confusing provider error.
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Any


@dataclass(frozen=True)
class ModelRequest:
    """One fully assembled prompt, and how the caller wants it answered.

    The prompt arrives assembled. Nothing below this line adds a word to it --
    which is what lets ``boundary.v1`` Core 3's transcript be the whole truth
    about what was sent.

    ``tools``, when non-empty, is what makes the turn agentic: the engine offers
    them to the provider, the provider calls them **natively**, and the handlers
    run here in music-deck's own process. Empty (the default, and what ``plan``
    sends) leaves the turn exactly what it always was -- text in, text out, no
    tools, no approvals channel.
    """

    prompt: str
    provider: str | None = None
    model: str | None = None
    tools: tuple[ToolSpec, ...] = ()


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
# Tools -- the caller's, translated once, here
# --------------------------------------------------------------------------- #
def _engine_tools(specs: tuple[ToolSpec, ...]) -> list[Any]:
    """Every :class:`ToolSpec` as the engine's own ``Tool``.

    The one place ``amplifier_agent.Tool`` is constructed. A verb declares what
    it can do in music-deck's terms and never learns the engine's, which is what
    keeps ``cli.v1`` Core 2's lazy-import promise honest for the other forty
    verbs and what lets a test double drive the same handlers with no engine
    installed at all.

    The handler is wrapped rather than passed through for one reason:
    :class:`ToolStop` has to become the library's ``ToolFailed``, which under
    ``tool_error_policy="stop"`` ends the turn instead of handing the model
    something to work around. Every other outcome -- including a refusal the
    model *should* correct -- comes back as the handler's own returned string.
    """
    from amplifier_agent import Tool, ToolFailed

    def adapt(spec: ToolSpec) -> Any:
        async def handler(arguments: dict[str, Any], context: Any) -> str:
            try:
                return spec.handler(dict(arguments))
            except ToolStop as stop:
                raise ToolFailed(str(stop)) from None

        return Tool(
            name=spec.name,
            description=spec.description,
            input_schema=dict(spec.input_schema),
            handler=handler,
        )

    return [adapt(spec) for spec in specs]


# --------------------------------------------------------------------------- #
# Approvals -- static, deterministic, and an allow-list rather than "allow"
# --------------------------------------------------------------------------- #
def _static_approval_policy(declared: tuple[str, ...]) -> Any:
    """Allow exactly the tools music-deck declared; deny everything else.

    **Why a policy is required at all.** The engine asks its approvals authority
    before every tool call, and with none configured the decision is
    ``"unavailable"`` -- the effect fails ``approval_unavailable`` and the turn
    stops. That is the right default for ``plan``, which offers no tools. The
    moment ``do`` declares one, a policy has to be chosen or nothing can run.

    **Why static.** ``do`` is non-interactive: there is no human at the other
    end of a prompt, so there is nobody an approval could be put to. This
    handler asks nothing, reads nothing, and does no I/O -- it is a pure
    function of the tool's name, and the same call always gets the same answer.
    A "static policy" in every sense that matters; it is spelled as a handler
    only because the two literals the library offers are both wrong here.

    **Why not the literal ``approvals="allow"``.** Because it would not mean
    "allow music-deck's six tools". Measured against the installed engine on
    2026-09-06: ``prepare_tools`` registers music-deck's caller tools **and its
    own built-ins** -- ``read``, ``write``, ``edit``, ``glob``, ``grep``,
    ``web_fetch``, ``web_search``, ``bash`` and ``delegate`` -- and offers all of
    them to the provider. A blanket ``"allow"`` therefore hands a shell and a
    filesystem on the caller's machine to a model that was asked to make a
    playlist. Until ``do`` declared its first tool, none of that was reachable:
    with no approvals channel every one of those built-ins failed closed, which
    is the property this repository has been describing all along. An allow-list
    is what keeps that property true now that a channel exists.

    **Why not ``"deny"``.** It denies music-deck's own tools too, so ``do``
    could never run a search.

    A denial ends the turn with the library's ``approval_denied``; the caller
    sees a named refusal (``music_deck.verbs.do`` maps it onto
    ``refusals.v1``'s closed vocabulary), never a traceback and never a silent
    execution.
    """
    allowed = frozenset(declared)

    async def decide(request: Any) -> Any:
        from amplifier_agent import ApprovalResponse

        if request.name in allowed:
            return ApprovalResponse("allow")
        return ApprovalResponse(
            "deny",
            reason=(
                f"music-deck declared {sorted(allowed)} and allows nothing else. "
                f"{request.name!r} is not one of them."
            ),
        )

    return decide


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

        Two shapes, and which one runs is decided by ``request.tools``.

        **No tools** -- what ``plan`` sends, and what this method did until
        2026-09-06. No ``tools``, no ``skills``, no ``mcp_servers`` and no
        ``approvals``. Those are the library's defaults, and its approvals rule
        makes them fail-closed: with no channel, a tool effect fails
        ``approval_unavailable`` instead of proceeding. music-deck strips
        nothing and overrides nothing to get that; it asks for an agent that has
        nothing to reach with.

        **With tools** -- what ``do`` sends. The engine offers them to the
        provider, the provider calls them natively, and each handler runs here
        in this process against music-deck's own library functions. This exists
        because the alternative *did not work*: describing tools in the prompt
        and asking for JSON text back was refused on the first live invocation
        with ``provider_failed`` -- "The provider requested an undeclared tool"
        -- because a real model, handed a prompt describing tools, makes a
        native tool call. 655 tests passed over that defect, every one of them
        through a double that answered in the JSON the loop expected.

        Declaring tools forces the approvals question, and the answer is
        :func:`_static_approval_policy`. Read its docstring before changing
        anything here: a bare ``approvals="allow"`` is **not** equivalent, and
        is not safe.
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

        # Narrower still, and deliberately: a turn with no tools imports exactly
        # the six names it always did. `plan` is unchanged down to its imports.
        tools = _engine_tools(request.tools) if request.tools else None
        approvals = (
            _static_approval_policy(tuple(spec.name for spec in request.tools))
            if request.tools
            else None
        )

        # boundary.v1 Core 8 forbids a persistent store, and the library writes
        # durable transcripts under a storage root it picks (`~/.amplifier-agent`
        # by default). An ephemeral session writes nothing there -- measured --
        # but "nothing was written to a directory that does not outlive the
        # turn" is a stronger sentence than "nothing was written", and it is the
        # one a reviewer can check without trusting either of us.
        # The engine reads its configuration from this process's environment,
        # not from the options below, and refuses a turn over anything it does
        # not recognise there. music-deck honours no AMPLIFIER_AGENT_* setting
        # (see HOST_SETTING_PREFIX for the decision and its two reasons), so the
        # whole namespace is withheld across every call that reads it -- the
        # build *and* the turn -- and restored the moment this block ends.
        with (
            tempfile.TemporaryDirectory(prefix="music-deck-agent-") as storage,
            without_host_settings(),
        ):
            options = AgentOptions(
                provider=provider,
                model=model,
                storage=storage,
                tools=tools,
                approvals=approvals,
                # Explicit although it is the default. A recoverable mistake --
                # a bad argument, an empty result -- is handed back to the model
                # by a handler *returning* an observation, never by raising; the
                # only thing that raises is ToolStop, and that must end the turn
                # rather than be worked around. "continue" would let a model
                # loop forever against a ceiling it has already hit, on an
                # engine whose own iteration cap is -1.
                tool_error_policy="stop",
            )
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
            f"Settings named {HOST_SETTING_PREFIX}* in your shell are not "
            f"involved: music-deck withholds that whole namespace for the turn, "
            f"so this failure is about the provider or the model, not about them."
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
    "HOST_SETTING_PREFIX",
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
    "ToolSpec",
    "ToolStop",
    "resolve",
    "without_host_settings",
]
