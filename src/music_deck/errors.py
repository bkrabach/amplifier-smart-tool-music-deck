"""The refusal vocabulary, the error envelope, and the exit-code mapping.

This module is the shared vocabulary every other part of music-deck imports.
Nothing here talks to Spotify, to a model, or to the network; it is the one
place that decides *what a failure is called* and *what number the process
exits with*, so those two answers cannot drift apart across verbs.

Three things live here, in the order a caller meets them:

1. ``ErrorCode`` -- the ten frozen codes of ``cli.v1`` Core 6, verbatim, plus
   the two codes that clause does not cover (see "Codes outside the frozen
   vocabulary" below).
2. ``error_envelope`` / ``MusicDeckError`` -- the one failure shape of
   ``cli.v1`` Core 4: ``{"error": {"code", "message", "remedy"}}``.
3. ``exit_code_for`` -- the mapping onto ``cli.v1`` Core 5's four exit codes.

Contracts served: ``cli.v1`` Core 4 (one JSON document per result), Core 5
(exit codes), Core 6 (the frozen refusal vocabulary).

Codes outside the frozen vocabulary
-----------------------------------
``cli.v1`` Core 6 freezes twelve *refusal* codes. Two failures a caller can
actually provoke are not refusals and are therefore not in that list, but Core 4
still requires every failure to carry a code:

* ``usage`` -- a malformed invocation: an unknown verb, a missing argument, a
  bad value. Core 5 names "usage, or invalid input" as its own exit-2 category,
  distinct from a refusal, so this code takes the word Core 5 itself uses.
* ``not_implemented`` -- scaffolding. A verb that ``cli.v1`` Core 2 names but
  whose lane has not landed yet refuses loudly rather than pretending to work.
  Every one of these disappears as its lane lands; none is part of the promised
  surface, and no caller should ever branch on it.

Both are marked in ``FROZEN_CODES`` by their absence: that frozenset is exactly
Core 6's twelve, and it is what a conformance fixture should enumerate.

Two codes that used to sit here have since been ratified into Core 6 itself, on
2026-09-06, and moved up into ``FROZEN_CODES`` where the clause now names them:

* ``port_unavailable`` -- ``login``'s registered loopback port is already in
  use, so it refuses naming the port rather than binding another Spotify would
  reject (added to Core 6 at ``4f4fbf6``).
* ``cancelled`` -- the caller interrupted an interactive wait. Core 6: "A person
  stopping the tool is a refusal, never a traceback" (added at ``fab12dc``).

How the exit codes were derived
-------------------------------
``cli.v1`` Core 5 gives four codes: ``0`` success, ``1`` failure, ``2``
refusal / usage / invalid input, ``3`` no provider configured (model-backed verb
only), and says "all domain richness lives in ``error.code``, not in more exit
codes".

Core 6 calls its twelve codes "the refusal vocabulary". Refusals exit ``2``, so
all map to ``2``; Core 6's own text confirms this for the one code it annotates
(``invalid_plan`` -- "exit 2"). ``usage`` is Core 5's own second exit-2
category. Exit ``1`` is what is left: a genuine failure with no frozen code --
an unreadable file, an upstream fault, an unhandled exception -- and the
scaffolding ``not_implemented``. Exit ``3`` belongs to ``plan`` alone
(``cli.v1`` Core 3) and is reached through ``NoProviderError``, never through a
frozen code.
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
# The refusal vocabulary -- cli.v1 Core 6, verbatim and frozen
# --------------------------------------------------------------------------- #
class ErrorCode:
    """Every code music-deck may put in an error envelope.

    The twelve in ``FROZEN_CODES`` are frozen by ``cli.v1`` Core 6: their
    spelling is part of the promise, and a caller may branch on them. The
    remaining two are not (see the module docstring).
    """

    # -- the frozen twelve, in Core 6's own order --------------------------- #
    NOT_AUTHENTICATED: Final = "not_authenticated"
    REAUTHORIZATION_REQUIRED: Final = "reauthorization_required"
    NOT_ALLOWLISTED: Final = "not_allowlisted"
    PREMIUM_REQUIRED: Final = "premium_required"
    NO_ACTIVE_DEVICE: Final = "no_active_device"
    CANCELLED: Final = "cancelled"
    RATE_LIMITED: Final = "rate_limited"
    QUOTA_EXCEEDED: Final = "quota_exceeded"
    PARTIAL_RESULT: Final = "partial_result"
    PORT_UNAVAILABLE: Final = "port_unavailable"
    PLAYLIST_ITEMS_UNAVAILABLE: Final = "playlist_items_unavailable"
    INVALID_PLAN: Final = "invalid_plan"

    # -- not frozen; see the module docstring ------------------------------- #
    USAGE: Final = "usage"
    NOT_IMPLEMENTED: Final = "not_implemented"


FROZEN_CODES: Final[frozenset[str]] = frozenset(
    {
        ErrorCode.NOT_AUTHENTICATED,
        ErrorCode.REAUTHORIZATION_REQUIRED,
        ErrorCode.NOT_ALLOWLISTED,
        ErrorCode.PREMIUM_REQUIRED,
        ErrorCode.NO_ACTIVE_DEVICE,
        ErrorCode.CANCELLED,
        ErrorCode.RATE_LIMITED,
        ErrorCode.QUOTA_EXCEEDED,
        ErrorCode.PARTIAL_RESULT,
        ErrorCode.PORT_UNAVAILABLE,
        ErrorCode.PLAYLIST_ITEMS_UNAVAILABLE,
        ErrorCode.INVALID_PLAN,
    }
)
"""Exactly the twelve codes ``cli.v1`` Core 6 freezes, in that clause's order."""


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
    ErrorCode.PORT_UNAVAILABLE: (
        "Free the port named in `message`, or pick another with `music-deck setup "
        "--port <n>` and register http://127.0.0.1:<n> as your Spotify app's "
        "redirect URI. Run `music-deck check` to see which port music-deck will use."
    ),
    ErrorCode.NOT_IMPLEMENTED: (
        "This verb is declared by the CLI contract but not built yet. Run "
        "`music-deck check` to confirm the install, and `music-deck --help` to see "
        "what is available."
    ),
}
"""The remedy each code carries when the caller does not supply a better one."""


_EXIT_BY_CODE: Final[dict[str, int]] = {
    **{code: EXIT_REFUSAL for code in FROZEN_CODES},
    ErrorCode.USAGE: EXIT_REFUSAL,
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
        super().__init__(message)
        self.code = code
        self.message = message
        self.remedy = remedy if remedy is not None else remedy_for(code)
        self.extra = extra

    @property
    def exit_code(self) -> int:
        return exit_code_for(self.code)

    def envelope(self) -> dict[str, Any]:
        return error_envelope(self.code, self.message, self.remedy, **self.extra)


class NoProviderError(MusicDeckError):
    """No usable model substrate for a model-backed verb -- ``cli.v1`` Core 3, exit ``3``.

    Kept distinct from the frozen refusal codes because its exit code is the one
    thing Core 5 gives its own number to.
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
