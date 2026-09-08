"""The refusal vocabulary, the error envelope, and the exit-code mapping.

This module is the shared vocabulary every other part of music-deck imports.
Nothing here talks to Spotify, to a model, or to the network; it is the one
place that decides *what a failure is called* and *what number the process
exits with*, so those two answers cannot drift apart across verbs.

Three things live here, in the order a caller meets them:

1. ``ErrorCode`` -- every code in the closed vocabulary in
   ``refusals.v1`` Core 2 through Core 8.
2. ``error_envelope`` / ``MusicDeckError`` -- the one failure shape of
   ``cli.v1`` Core 4: ``{"error": {"code", "message", "remedy"}}``.
3. ``exit_code_for`` -- the mapping onto ``cli.v1`` Core 5's four exit codes.

Contracts served: ``cli.v1`` Core 4 (one JSON document per result), Core 5
(exit codes), and ``refusals.v1`` Core 1 (the closed public vocabulary).

``FROZEN_CODES`` keeps its established public name for compatibility. It is the
complete public registry, rather than the old twelve-code subset from before the
vocabulary moved into ``refusals.v1``. Adapter-only diagnostics are projected
here, at construction time, so a ``MusicDeckError`` a library caller catches is
already public-safe. Only fixed labels named in this module can survive as
diagnostics; an arbitrary code, message, remedy, or nested payload never becomes
part of an envelope, an exception string, or stderr.

How the exit codes were derived
-------------------------------
``cli.v1`` Core 5 gives four codes: ``0`` success, ``1`` failure, ``2``
refusal / usage / invalid input, ``3`` no provider configured (model-backed verb
only), and says "all domain richness lives in ``error.code``, not in more exit
codes". The explicit table below preserves that distinction: ``spotify_error``,
``internal_error``, and ``not_implemented`` are failures (1);
``no_provider_configured`` is 3; every other contracted code is a refusal (2).
"""

from __future__ import annotations

import json
import sys
from typing import Any, Final, TextIO

# --------------------------------------------------------------------------- #
# Exit codes -- cli.v1 Core 5
# --------------------------------------------------------------------------- #
EXIT_SUCCESS: Final = 0
"""The verb did what it was asked."""

EXIT_FAILURE: Final = 1
"""A failure with no frozen code: an upstream fault, an unreadable file."""

EXIT_REFUSAL: Final = 2
"""A refusal (the frozen vocabulary), a usage error, or invalid input."""

EXIT_NO_PROVIDER: Final = 3
"""No usable model substrate for a model-backed verb -- cli.v1 Core 3."""


# --------------------------------------------------------------------------- #
# The public vocabulary -- refusals.v1, closed and frozen
# --------------------------------------------------------------------------- #
class ErrorCode:
    """Every code music-deck may put in an error envelope."""

    # -- authorization ------------------------------------------------------- #
    NOT_AUTHENTICATED: Final = "not_authenticated"
    REAUTHORIZATION_REQUIRED: Final = "reauthorization_required"
    NOT_ALLOWLISTED: Final = "not_allowlisted"

    # -- account and device -------------------------------------------------- #
    PREMIUM_REQUIRED: Final = "premium_required"
    NO_ACTIVE_DEVICE: Final = "no_active_device"

    # -- quota and partial work --------------------------------------------- #
    RATE_LIMITED: Final = "rate_limited"
    QUOTA_EXCEEDED: Final = "quota_exceeded"
    PARTIAL_RESULT: Final = "partial_result"

    # -- caller input -------------------------------------------------------- #
    USAGE: Final = "usage"
    INVALID_INPUT: Final = "invalid_input"
    INVALID_PLAN: Final = "invalid_plan"

    # -- tool preconditions -------------------------------------------------- #
    NO_PROVIDER_CONFIGURED: Final = "no_provider_configured"
    PORT_UNAVAILABLE: Final = "port_unavailable"
    NO_BROWSER: Final = "no_browser"
    CANCELLED: Final = "cancelled"

    # -- upstream and tool failures ----------------------------------------- #
    SPOTIFY_ERROR: Final = "spotify_error"
    PLAYLIST_ITEMS_UNAVAILABLE: Final = "playlist_items_unavailable"
    INTERNAL_ERROR: Final = "internal_error"
    NOT_IMPLEMENTED: Final = "not_implemented"


FROZEN_CODES: Final[frozenset[str]] = frozenset(
    {
        ErrorCode.NOT_AUTHENTICATED,
        ErrorCode.REAUTHORIZATION_REQUIRED,
        ErrorCode.NOT_ALLOWLISTED,
        ErrorCode.PREMIUM_REQUIRED,
        ErrorCode.NO_ACTIVE_DEVICE,
        ErrorCode.RATE_LIMITED,
        ErrorCode.QUOTA_EXCEEDED,
        ErrorCode.PARTIAL_RESULT,
        ErrorCode.USAGE,
        ErrorCode.INVALID_INPUT,
        ErrorCode.INVALID_PLAN,
        ErrorCode.NO_PROVIDER_CONFIGURED,
        ErrorCode.PORT_UNAVAILABLE,
        ErrorCode.NO_BROWSER,
        ErrorCode.CANCELLED,
        ErrorCode.SPOTIFY_ERROR,
        ErrorCode.PLAYLIST_ITEMS_UNAVAILABLE,
        ErrorCode.INTERNAL_ERROR,
        ErrorCode.NOT_IMPLEMENTED,
    }
)
"""Exactly the closed public vocabulary in ``contracts/refusals.v1.md``."""


REMEDIES: Final[dict[str, str]] = {
    # cli.v1 Core 6 names the remedy for these three itself.
    ErrorCode.NOT_AUTHENTICATED: "Run `music-deck login`.",
    ErrorCode.REAUTHORIZATION_REQUIRED: "Run `music-deck login`.",
    ErrorCode.NO_ACTIVE_DEVICE: (
        "Start playback on a Spotify device, or run `music-deck transfer` to move "
        "playback to one."
    ),
    # The rest carry the remedy their clause implies, in words a caller can act on.
    ErrorCode.CANCELLED: (
        "Nothing was written. Run `music-deck login` again when you are ready to "
        "finish authorising in a browser."
    ),
    ErrorCode.NOT_ALLOWLISTED: (
        "Add this Spotify account to your app's allowlist under User Management in "
        "the Spotify developer dashboard. Run `music-deck setup` for the steps."
    ),
    ErrorCode.PREMIUM_REQUIRED: (
        "Playback writes need Spotify Premium on the account being controlled."
    ),
    ErrorCode.RATE_LIMITED: (
        "Wait the number of seconds in `retry_after_s` and run the command again."
    ),
    ErrorCode.QUOTA_EXCEEDED: (
        "Your Spotify developer quota is exhausted; waiting will not clear it. Reduce "
        "how much this app requests, or try again later in the quota window."
    ),
    ErrorCode.PARTIAL_RESULT: (
        "Read the `completeness` block to see what succeeded and what did not, then "
        "re-run only the part that failed."
    ),
    ErrorCode.PLAYLIST_ITEMS_UNAVAILABLE: (
        "Spotify only returns items for a playlist you own or collaborate on. Use one "
        "you own."
    ),
    ErrorCode.INVALID_PLAN: (
        "Fix the plan at the path named in `message`, then run `music-deck apply` again."
    ),
    ErrorCode.USAGE: "Run `music-deck --help` for the complete listing of verbs.",
    ErrorCode.INVALID_INPUT: (
        "Correct the value named in `message`, then run the command again."
    ),
    ErrorCode.NO_PROVIDER_CONFIGURED: (
        "Run `music-deck check` to identify the missing model provider, SDK, or "
        "credential, then follow its setup guidance."
    ),
    ErrorCode.PORT_UNAVAILABLE: (
        "Free the port named in `message`, or pick another with `music-deck setup "
        "--port <n>` and register http://127.0.0.1:<n> as your Spotify app's "
        "redirect URI. Run `music-deck check` to see which port music-deck will use."
    ),
    ErrorCode.NO_BROWSER: (
        "Run `music-deck login --no-browser` and open the URL it prints from a "
        "machine with a browser, or run it from an interactive terminal."
    ),
    ErrorCode.SPOTIFY_ERROR: (
        "Run `music-deck check` to report the tool's state, then try again."
    ),
    ErrorCode.INTERNAL_ERROR: (
        "Run `music-deck check` to report the tool's state, then report this error."
    ),
    ErrorCode.NOT_IMPLEMENTED: (
        "This verb is declared by the CLI contract but not built yet. Run "
        "`music-deck check` to confirm the install, and `music-deck --help` to see "
        "what is available."
    ),
}
"""The remedy each code carries when the caller does not supply a better one."""


# These labels are implementation details, not codes a caller may branch on.
# They are an allow-list rather than a pass-through: engine and transport errors
# can carry arbitrary strings (including credentials), and a valid-looking
# *public* code does not make their accompanying data trustworthy.
INTERNAL_DIAGNOSTIC_CODES: Final[frozenset[str]] = frozenset(
    {
        "approval_denied",
        "approval_timeout",
        "approval_unavailable",
        "engine_failed",
        "model_did_not_run",
        "model_not_selected",
        "network_unreachable",
        "provider_failed",
        "provider_unavailable",
        "removed_endpoint",
        "selector_rejected",
        "tool_failed",
    }
)

_ENGINE_SUBSTRATE_DIAGNOSTICS: Final[frozenset[str]] = frozenset(
    {"model_not_selected", "provider_unavailable", "selector_rejected"}
)

_INTERNAL_EXPLANATIONS: Final[dict[str, tuple[str, str]]] = {
    "network_unreachable": (
        "music-deck could not reach Spotify.",
        "Check the network connection and run the command again.",
    ),
    "removed_endpoint": (
        "music-deck refused to construct a Spotify endpoint that Spotify has withdrawn.",
        "This is a defect in music-deck, not something you did. Run `music-deck check` "
        "and report this error.",
    ),
    "model_did_not_run": (
        "music-deck's model engine did not return a usable response.",
        "Run `music-deck check` to confirm the model setup, then run the command again.",
    ),
}

_GENERIC_INTERNAL: Final[tuple[str, str]] = (
    "music-deck encountered an internal error.",
    "Run `music-deck check` to report the tool's state, then report this error.",
)


_EXIT_BY_CODE: Final[dict[str, int]] = {
    **{
        code: EXIT_REFUSAL
        for code in FROZEN_CODES
        - {
            ErrorCode.NO_PROVIDER_CONFIGURED,
            ErrorCode.SPOTIFY_ERROR,
            ErrorCode.INTERNAL_ERROR,
            ErrorCode.NOT_IMPLEMENTED,
        }
    },
    ErrorCode.NO_PROVIDER_CONFIGURED: EXIT_NO_PROVIDER,
    ErrorCode.SPOTIFY_ERROR: EXIT_FAILURE,
    ErrorCode.INTERNAL_ERROR: EXIT_FAILURE,
    ErrorCode.NOT_IMPLEMENTED: EXIT_FAILURE,
}


def exit_code_for(code: str) -> int:
    """The process exit code for an error code -- ``cli.v1`` Core 5.

    An unrecognised code is a failure (``1``) rather than a crash: a caller
    still gets a loud, non-zero exit and a readable envelope.
    """
    return _EXIT_BY_CODE.get(code, EXIT_FAILURE)


def remedy_for(code: str) -> str:
    """The default remedy for a code. Never empty -- Core 4 requires the field."""
    return REMEDIES.get(
        code, "Run `music-deck check` to report the tool's current state."
    )


def _public_error_parts(
    code: str, message: str, remedy: str | None, extra: dict[str, Any]
) -> tuple[str, str, str | None, dict[str, Any]]:
    """Keep unreviewed adapter input out of every public error surface."""
    if code in FROZEN_CODES:
        return code, message, remedy, extra
    diagnostic = code if code in INTERNAL_DIAGNOSTIC_CODES else None
    public_message, public_remedy = _INTERNAL_EXPLANATIONS.get(
        diagnostic or "", _GENERIC_INTERNAL
    )
    public_extra = {"diagnostic_code": diagnostic} if diagnostic is not None else {}
    return (
        ErrorCode.INTERNAL_ERROR,
        public_message,
        public_remedy,
        public_extra,
    )


def internal_error(
    diagnostic_code: str | None = None, **safe_extra: Any
) -> "MusicDeckError":
    """Construct an internal error from a reviewed diagnostic and safe context.

    ``safe_extra`` is deliberately restricted to the removed-endpoint facts,
    whose values come from the local endpoint registry. Other diagnostics retain
    only their fixed label. This is the sole way an adapter diagnostic gets
    contextual fields into a public envelope.
    """
    message, remedy = _INTERNAL_EXPLANATIONS.get(
        diagnostic_code or "", _GENERIC_INTERNAL
    )
    extra: dict[str, Any] = {}
    if diagnostic_code in INTERNAL_DIAGNOSTIC_CODES:
        extra["diagnostic_code"] = diagnostic_code
    if diagnostic_code in {
        "approval_denied",
        "approval_timeout",
        "approval_unavailable",
        "engine_failed",
        "provider_failed",
        "tool_failed",
    }:
        extra["engine_code"] = diagnostic_code
    if diagnostic_code == "removed_endpoint":
        method = safe_extra.get("method")
        path = safe_extra.get("path")
        withdrawn = safe_extra.get("withdrawn")
        replacement = safe_extra.get("replacement")
        if isinstance(method, str) and method in {"GET", "POST", "PUT", "DELETE"}:
            extra["method"] = method
        if (
            isinstance(path, str)
            and "?" not in path
            and len(path) <= 200
            and all(character.isalnum() or character in "/_-.{}" for character in path)
        ):
            extra["path"] = path
        if isinstance(withdrawn, str) and withdrawn in {"November 2024", "February 2026"}:
            extra["withdrawn"] = withdrawn
        if (
            isinstance(replacement, str)
            and len(replacement) <= 200
            and "`" not in replacement
        ):
            extra["replacement"] = replacement
    return MusicDeckError(ErrorCode.INTERNAL_ERROR, message, remedy, **extra)


def project_engine_error(error: "MusicDeckError") -> "MusicDeckError":
    """Project an engine-originated error through the same safe boundary.

    The engine's message/remedy/extras are never reused. The original private
    code was normalised when ``MusicDeckError`` was built; a recognised label is
    retained in ``diagnostic_code`` solely so substrate failures can still map
    to the contracted ``no_provider_configured`` refusal.
    """
    diagnostic = getattr(error, "diagnostic_code", None)
    if diagnostic in _ENGINE_SUBSTRATE_DIAGNOSTICS:
        return NoProviderError(
            "music-deck could not use the configured model provider.",
            "Run `music-deck check` to identify the missing model provider, SDK, or "
            "credential, then follow its setup guidance.",
        )
    if error.code in FROZEN_CODES and error.code != ErrorCode.INTERNAL_ERROR:
        return MusicDeckError(
            error.code,
            "The model engine stopped before music-deck could complete the request.",
            remedy_for(error.code),
        )
    return internal_error(diagnostic)


# --------------------------------------------------------------------------- #
# The envelope -- cli.v1 Core 4
# --------------------------------------------------------------------------- #
def error_envelope(
    code: str, message: str, remedy: str | None = None, **extra: Any
) -> dict[str, Any]:
    """Build the one failure shape: ``{"error": {"code", "message", "remedy"}}``.

    ``extra`` carries the fields a particular code documents -- ``retry_after_s``
    for ``rate_limited``, ``completeness`` for ``partial_result``, ``path`` for
    ``invalid_plan`` -- alongside the three required keys, never instead of them.
    """
    code, message, remedy, extra = _public_error_parts(code, message, remedy, dict(extra))
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "remedy": remedy if remedy is not None else remedy_for(code),
    }
    error.update(extra)
    return {"error": error}


class MusicDeckError(Exception):
    """A failure that already knows its code, its remedy, and its exit code.

    Raise this anywhere in the library. The CLI catches it, prints
    ``envelope()`` as one JSON document on stdout, and exits ``exit_code``.
    """

    def __init__(
        self,
        code: str,
        message: str,
        remedy: str | None = None,
        **extra: Any,
    ) -> None:
        public_code, public_message, public_remedy, public_extra = _public_error_parts(
            code, message, remedy, dict(extra)
        )
        super().__init__(public_message)
        self.code = public_code
        self.message = public_message
        self.remedy = (
            public_remedy if public_remedy is not None else remedy_for(public_code)
        )
        self.extra = public_extra
        self.diagnostic_code = public_extra.get("diagnostic_code")

    @property
    def exit_code(self) -> int:
        return exit_code_for(self.code)

    def envelope(self) -> dict[str, Any]:
        return error_envelope(self.code, self.message, self.remedy, **self.extra)


class NoProviderError(MusicDeckError):
    """No usable model substrate for a model-backed verb -- ``cli.v1`` Core 3, exit ``3``.

    Kept as a class so callers can catch the model-preflight condition directly;
    its code is also a member of the closed public registry.
    """

    def __init__(self, message: str, remedy: str) -> None:
        super().__init__("no_provider_configured", message, remedy)

    @property
    def exit_code(self) -> int:
        return EXIT_NO_PROVIDER


class NotImplementedVerb(MusicDeckError):
    """A verb ``cli.v1`` Core 2 names whose lane has not landed yet."""

    def __init__(self, verb: str) -> None:
        super().__init__(
            ErrorCode.NOT_IMPLEMENTED,
            f"`music-deck {verb}` is declared by the CLI contract but is not "
            f"implemented in this build.",
            verb=verb,
        )


# --------------------------------------------------------------------------- #
# Emitting -- stdout carries JSON, stderr carries prose (cli.v1 Core 4)
# --------------------------------------------------------------------------- #
def emit_json(document: Any, stream: TextIO | None = None) -> None:
    """Write exactly one JSON document to stdout, newline-terminated."""
    out = sys.stdout if stream is None else stream
    json.dump(document, out, indent=2, sort_keys=False)
    out.write("\n")


def emit_error(error: MusicDeckError, stream: TextIO | None = None) -> int:
    """Print an error's envelope on stdout and return the exit code to use."""
    emit_json(error.envelope(), stream)
    return error.exit_code
