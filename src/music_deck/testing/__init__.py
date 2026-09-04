"""Stand-ins a caller can drive music-deck with, shipped with the tool.

These live in the package rather than in ``tests/`` on purpose. ``boundary.v1``
promises a check anyone can run -- "so a caller or reviewer can verify clause 2
without reading code" -- and a reviewer who has installed music-deck can, with
``Recording`` plus ``music_deck.prompt_boundary``, run the same good/bad pair
this repository's own suite runs, against their own build, without cloning
anything.

Nothing here imports a provider SDK or the engine.
"""

from __future__ import annotations

from music_deck.testing.intelligence_doubles import Recording, Scripted, Unconfigured

__all__ = ["Recording", "Scripted", "Unconfigured"]
