"""The verbs of ``cli.v1`` Core 2, one module per family.

Each module here is a library function first and a CLI verb second -- ``cli.v1``
Core 7: "The library is the tool. Every CLI capability is reachable from the
``music_deck`` Python library." ``src/music_deck/cli.py`` binds these functions
to argv and prints their return value; it holds no domain logic of its own.
"""

from __future__ import annotations
