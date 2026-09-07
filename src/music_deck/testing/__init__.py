"""Stand-ins a caller can drive music-deck with, shipped with the tool.

These live in the package rather than in ``tests/`` on purpose. ``boundary.v1``
promises a check anyone can run, so a reviewer who has installed music-deck can,
with ``Recording`` plus ``music_deck.prompt_boundary``, run the same good/bad
pair this repository's own suite runs, against their own build, without cloning
anything.

The pair is about **credentials** now, not about Spotify content. Core 1 was
inverted on 2026-09-06 -- a model may read what Spotify returns -- so:

* GOOD -- no credential appears in any prompt. A real ``plan`` run driven by
  ``Recording`` is one; a prompt carrying ``SPOTIFY_SEARCH_RESULTS`` is another,
  and it passes, because content is allowed.
* BAD -- ``credential_leak_prompt(brief)`` splices the access token into the
  prompt. The same check over the same double must fail, naming which credential
  it found. A BAD half that does not fail is a check that is not real.

``FAKE_ACCESS_TOKEN``, ``FAKE_REFRESH_TOKEN`` and ``FAKE_CLIENT_ID`` are the
shape of the three credentials Core 2 names and the value of none of them, so
the pair can be run without a real token anywhere near it.

Nothing here imports a provider SDK or the engine.
"""

from __future__ import annotations

from music_deck.testing.intelligence_doubles import (
    CANNED_PLAN_JSON,
    FAKE_ACCESS_TOKEN,
    FAKE_CLIENT_ID,
    FAKE_REFRESH_TOKEN,
    SPOTIFY_SEARCH_RESULTS,
    Recording,
    Scripted,
    Unconfigured,
    credential_leak_prompt,
)

__all__ = [
    "CANNED_PLAN_JSON",
    "FAKE_ACCESS_TOKEN",
    "FAKE_CLIENT_ID",
    "FAKE_REFRESH_TOKEN",
    "SPOTIFY_SEARCH_RESULTS",
    "Recording",
    "Scripted",
    "Unconfigured",
    "credential_leak_prompt",
]
