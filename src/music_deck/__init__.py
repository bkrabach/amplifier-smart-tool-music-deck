"""music-deck -- curate and control music on Spotify from an agent.

``docs/VISION.md`` principle 1 and ``cli.v1`` Core 7 say the same thing: **the
library is the tool.** Every capability the ``music-deck`` binary offers is
reachable from here, and the CLI is a thin adapter over this package -- never a
second implementation. Anything an agent can do from a shell, a Python program
can do by importing this module.

What is reachable today:

* ``manifest()`` -- the SMART_TOOL.md manifest as a dict (``cli.v1`` Core 7)
* ``check()`` -- the deterministic smoke report (``boundary.v1`` Core 6)
* the error vocabulary in ``music_deck.errors`` -- the frozen refusal codes of
  ``cli.v1`` Core 6 and the exit-code mapping of Core 5, which every verb built
  after this one shares

The remaining verbs named by ``cli.v1`` Core 2 are declared by the CLI and
refuse loudly with ``not_implemented`` until their lane lands.

Importing this package configures nothing, reads no credentials, contacts no
network, and requires no model provider.
"""

from __future__ import annotations

from music_deck.check import check
from music_deck.errors import (
    EXIT_FAILURE,
    EXIT_NO_PROVIDER,
    EXIT_REFUSAL,
    EXIT_SUCCESS,
    FROZEN_CODES,
    ErrorCode,
    MusicDeckError,
    NoProviderError,
    NotImplementedVerb,
    error_envelope,
    exit_code_for,
)
from music_deck.manifest import ManifestError, manifest, manifest_body

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # the manifest, as structured data -- cli.v1 Core 7
    "manifest",
    "manifest_body",
    "ManifestError",
    # the deterministic smoke verb -- boundary.v1 Core 6
    "check",
    # the shared error vocabulary -- cli.v1 Core 4, 5, 6
    "ErrorCode",
    "FROZEN_CODES",
    "MusicDeckError",
    "NoProviderError",
    "NotImplementedVerb",
    "error_envelope",
    "exit_code_for",
    "EXIT_SUCCESS",
    "EXIT_FAILURE",
    "EXIT_REFUSAL",
    "EXIT_NO_PROVIDER",
]
