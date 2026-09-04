"""The verbs, one module each.

``docs/VISION.md`` principle 1 and ``cli.v1`` Core 7: the library is the tool.
A verb's whole implementation lives here and the CLI is a thin adapter over it,
so anything an agent can do from a shell a Python program can do by importing
``music_deck``.
"""

from __future__ import annotations
