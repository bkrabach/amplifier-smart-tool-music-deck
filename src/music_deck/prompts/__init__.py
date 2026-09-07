"""The static prompt text music-deck ships -- every non-caller word it sends.

This package holds the words music-deck itself contributes to a prompt: the
instructions and the headings, and nothing generated at run time.

It is no longer the *only* thing a prompt may carry besides the caller's own
text. ``boundary.v1`` Core 1 was inverted on 2026-09-06 -- a model may read what
Spotify returns -- so a prompt may carry search results and the caller's own
playlists too, and ``music_deck.prompt_boundary`` no longer covers a prompt with
an allowed set. What it checks now is Core 2: that no credential is in there.
Keeping music-deck's own words in one directory is still worth doing, because a
reviewer reading the transcript can then tell the tool's words from everything
else at a glance.

The prompt files are Markdown, split into named parts by lines of the form::

    === SECTION: <name> ===

Text above the first such line is a note to the file's maintainer and is never
sent. Splitting one file into parts, rather than shipping one blob, is what lets
the assembler interleave the caller's text between music-deck's own headings
while keeping every non-caller word traceable to this directory.

Files are read through ``importlib.resources`` from the installed package, never
from a path relative to a checkout -- the same discipline ``music_deck.manifest``
follows, and for the same reason: install layouts differ.
"""

from __future__ import annotations

import importlib.resources
import re
from typing import Final

PLAN_PROMPT_FILE: Final = "plan.md"
DO_PROMPT_FILE: Final = "do.md"

_SECTION_RE: Final = re.compile(r"^=== SECTION: ([a-z_]+) ===$", re.MULTILINE)

# The parts `plan.md` must carry. A missing part is a broken install, not a
# reason to send a prompt with a hole in it.
PLAN_PARTS: Final[tuple[str, ...]] = ("instructions", "brief", "context")

# The parts `do.md` must carry. `do` re-sends a whole prompt every turn -- the
# instructions, the tool vocabulary, the caller's brief, everything observed so
# far, and what is left of the budget -- so each transcript entry is a complete
# record of one turn rather than a fragment a reader has to reassemble.
DO_PARTS: Final[tuple[str, ...]] = (
    "instructions",
    "tools",
    "brief",
    "history",
    "ceilings",
)


class PromptError(RuntimeError):
    """A prompt file is missing, or does not carry the parts it must."""


def _read(filename: str) -> str:
    resource = importlib.resources.files("music_deck.prompts").joinpath(filename)
    if not resource.is_file():
        raise PromptError(
            f"the prompt file music_deck/prompts/{filename} is not reachable. "
            "It must ship inside the installed package."
        )
    return resource.read_text(encoding="utf-8")


def split_parts(text: str) -> dict[str, str]:
    """Split a prompt file into its named parts.

    Text before the first marker is dropped: it is documentation for a person
    maintaining the file, and sending it to a model would be sending words no
    caller asked for.
    """
    matches = list(_SECTION_RE.finditer(text))
    if not matches:
        raise PromptError(
            "a prompt file carries no '=== SECTION: <name> ===' marker, so none of "
            "its text can be attributed to a named part."
        )
    parts: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        parts[match.group(1)] = text[match.end() : end].strip()
    return parts


def plan_prompt_parts() -> dict[str, str]:
    """The parts of ``plan.md``: ``instructions``, ``brief``, ``context``."""
    parts = split_parts(_read(PLAN_PROMPT_FILE))
    missing = [name for name in PLAN_PARTS if not parts.get(name, "").strip()]
    if missing:
        raise PromptError(
            f"{PLAN_PROMPT_FILE} is missing prompt parts: {missing}. "
            f"It must carry all of: {list(PLAN_PARTS)}."
        )
    return parts


def do_prompt_parts() -> dict[str, str]:
    """The parts of ``do.md``: every section :data:`DO_PARTS` names."""
    parts = split_parts(_read(DO_PROMPT_FILE))
    missing = [name for name in DO_PARTS if not parts.get(name, "").strip()]
    if missing:
        raise PromptError(
            f"{DO_PROMPT_FILE} is missing prompt parts: {missing}. "
            f"It must carry all of: {list(DO_PARTS)}."
        )
    return parts


def static_prompt_texts() -> tuple[str, ...]:
    """Every static text music-deck ships for a prompt, longest first.

    music-deck's own words, so a reviewer holding a transcript can tell them
    from the caller's text and from anything fetched. It is no longer an
    *allowed set*: ``music_deck.prompt_boundary`` stopped covering prompts when
    ``boundary.v1`` Core 1 was inverted, and now looks for credentials instead.
    Longest first is kept because a stable, deterministic order is worth more
    than an arbitrary one.
    """
    texts = set(plan_prompt_parts().values()) | set(do_prompt_parts().values())
    return tuple(sorted(texts, key=len, reverse=True))


__all__ = [
    "DO_PARTS",
    "DO_PROMPT_FILE",
    "PLAN_PARTS",
    "PLAN_PROMPT_FILE",
    "PromptError",
    "do_prompt_parts",
    "plan_prompt_parts",
    "split_parts",
    "static_prompt_texts",
]
