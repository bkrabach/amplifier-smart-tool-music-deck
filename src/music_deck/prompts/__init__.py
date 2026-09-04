"""The static prompt text -- the only non-caller words music-deck may send.

``boundary.v1`` Core 2 splits every prompt into exactly two kinds of text: the
caller's own, and music-deck's own static schema and prompt text. This package
is the whole of the second kind. Nothing else in the source may contribute a
word to a prompt, and ``music_deck.prompt_boundary`` is what makes that
checkable: the allowed set it covers a prompt with is ``static_prompt_texts()``
plus the caller's own arguments, so any sentence assembled from anywhere else
shows up as residue and fails the check.

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

_SECTION_RE: Final = re.compile(r"^=== SECTION: ([a-z_]+) ===$", re.MULTILINE)

# The parts `plan.md` must carry. A missing part is a broken install, not a
# reason to send a prompt with a hole in it.
PLAN_PARTS: Final[tuple[str, ...]] = ("instructions", "brief", "context")


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


def static_prompt_texts() -> tuple[str, ...]:
    """Every static text music-deck may put in a prompt, longest first.

    This is the allowed set for ``music_deck.prompt_boundary.check_prompts``.
    Longest first because the cover is greedy: a shorter fragment that happens
    to sit inside a longer one must not eat it first.
    """
    texts = set(plan_prompt_parts().values())
    return tuple(sorted(texts, key=len, reverse=True))


__all__ = [
    "PLAN_PARTS",
    "PLAN_PROMPT_FILE",
    "PromptError",
    "plan_prompt_parts",
    "split_parts",
    "static_prompt_texts",
]
