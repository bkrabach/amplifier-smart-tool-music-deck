"""The one-way boundary, as a function anyone can run.

``boundary.v1`` Core 2 is the promise this module makes checkable:

    Every prompt sent to a model consists solely of the caller's own text and
    music-deck's own static schema and prompt text. No Spotify response, no
    cache, no token, and no data from a prior run ever enters a prompt.

``boundary.v1`` Core 3 is what makes it checkable *from outside*: ``plan``
returns the verbatim text of every prompt it sent, so a reviewer runs this check
over the tool's own published output rather than over its source.

How the check works
-------------------
Not by looking for bad words -- a denylist only ever catches the leaks somebody
already thought of. By **cover**: every allowed source text is removed from the
prompt, and whatever is left over is a violation. The allowed set is exactly the
two kinds of text Core 2 names -- the parts of ``music_deck/prompts/`` and the
caller's own arguments -- so a prompt built from anything else cannot come out
clean, whatever it happens to contain.

That direction matters. A denylist asks "does this prompt contain something I
recognise as Spotify content?" and answers no for the leak nobody predicted.
This asks "is every word of this prompt accounted for?" and answers no for every
leak, including the ones that do not look like Spotify content at all.

Purity
------
``check_prompts`` is a pure function of its two arguments. It reads no file,
touches no environment, and calls nothing -- so ``boundary.v1``'s conformance
kit can call it against a transcript captured anywhere, and a caller can call it
against a transcript music-deck printed on a machine they do not have.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Sequence

CLAUSE: Final = "boundary.v1 Core 2"
"""The clause a failure of this check breaks, named in every message."""

CLAUSE_TEXT: Final = (
    "Every prompt sent to a model consists solely of the caller's own text and "
    "music-deck's own static schema and prompt text. No Spotify response, no "
    "cache, no token, and no data from a prior run ever enters a prompt."
)

# A second, independent signal. It never decides the verdict -- the cover does
# that -- but when residue looks like Spotify content the message says so, which
# is the difference between "something leaked" and "the catalogue leaked".
_SPOTIFY_MARKERS: Final[tuple[tuple[str, str], ...]] = (
    (r"spotify:(?:track|album|artist|playlist|episode|show):[0-9A-Za-z]{22}", "a Spotify URI"),
    (r"open\.spotify\.com/", "an open.spotify.com link"),
    (r"api\.spotify\.com", "an api.spotify.com reference"),
    (r'"(?:uri|href|external_urls|snapshot_id|popularity|duration_ms)"', "a Spotify API field"),
    (r"\b[0-9A-Za-z]{22}\b", "something shaped like a Spotify id"),
    (r"\bBQ[A-Za-z0-9_\-]{20,}", "something shaped like an access token"),
)


@dataclass(frozen=True)
class Violation:
    """One prompt carrying text from neither allowed source."""

    prompt_index: int
    residue: str
    clause: str = CLAUSE

    @property
    def looks_like(self) -> tuple[str, ...]:
        """What the residue resembles, if anything recognisable."""
        found: list[str] = []
        for pattern, description in _SPOTIFY_MARKERS:
            if re.search(pattern, self.residue) and description not in found:
                found.append(description)
        return tuple(found)

    def describe(self) -> str:
        head = (
            f"{self.clause} broken by prompt {self.prompt_index}: "
            f"{len(self.residue)} characters came from neither the caller's own "
            f"arguments nor music-deck's static prompt text"
        )
        recognised = self.looks_like
        if recognised:
            head += f" (it carries {', '.join(recognised)})"
        return f"{head}.\n    unaccounted-for text: {_snippet(self.residue)}"


@dataclass(frozen=True)
class BoundaryReport:
    """The verdict over a whole transcript."""

    ok: bool
    checked: int
    violations: tuple[Violation, ...] = ()

    def describe(self) -> str:
        if self.ok:
            return (
                f"{CLAUSE} kept: every one of {self.checked} prompt(s) is covered "
                "by the caller's own arguments and music-deck's static prompt text, "
                "with nothing left over."
            )
        lines = [
            f"{CLAUSE} BROKEN in {len(self.violations)} of {self.checked} prompt(s).",
            f"  the clause: {CLAUSE_TEXT}",
        ]
        lines += [f"  {violation.describe()}" for violation in self.violations]
        return "\n".join(lines)

    def raise_if_broken(self) -> None:
        if not self.ok:
            raise BoundaryViolation(self.describe())


class BoundaryViolation(AssertionError):
    """Raised when a transcript fails the check. An AssertionError on purpose:
    a broken one-way boundary is a fact about the program, not a user error."""


def uncovered(prompt: str, allowed: Sequence[str]) -> str:
    """The text of ``prompt`` that no allowed source accounts for.

    Removes every occurrence of every allowed text, longest first -- longest
    first so a short fragment cannot chew a hole in a longer one before it is
    matched -- then discards whitespace, which is all the assembler adds when it
    joins its segments together.

    Returns "" when the prompt is fully accounted for.
    """
    segments = [prompt]
    for text in sorted({t for t in allowed if t and t.strip()}, key=len, reverse=True):
        split: list[str] = []
        for segment in segments:
            split.extend(segment.split(text))
        segments = split
    return " ".join(segment.strip() for segment in segments if segment.strip())


def check_prompts(prompts: Sequence[str], allowed: Sequence[str]) -> BoundaryReport:
    """Check every prompt against the two kinds of text Core 2 allows.

    ``allowed`` is music-deck's own static prompt text plus the caller's own
    arguments -- nothing else, ever. Pure: same arguments, same answer,
    anywhere.
    """
    violations = tuple(
        Violation(prompt_index=index, residue=residue)
        for index, prompt in enumerate(prompts)
        if (residue := uncovered(prompt, allowed))
    )
    return BoundaryReport(
        ok=not violations, checked=len(prompts), violations=violations
    )


def check_plan_transcript(
    transcript: Sequence[str],
    *,
    brief: str,
    context: str | None = None,
    static_texts: Sequence[str] | None = None,
) -> BoundaryReport:
    """Check a ``plan`` result's transcript against the inputs that produced it.

    The convenience wrapper a reviewer reaches for: hand it what ``plan``
    printed and the arguments you gave, and it assembles the allowed set for
    you. ``static_texts`` defaults to ``music_deck.prompts.static_prompt_texts()``
    -- passed in only when checking a transcript from a different build than the
    one running the check.
    """
    if static_texts is None:
        from music_deck.prompts import static_prompt_texts

        static_texts = static_prompt_texts()
    allowed = [*static_texts, brief]
    if context:
        allowed.append(context)
    return check_prompts(transcript, allowed)


def _snippet(text: str, limit: int = 240) -> str:
    flattened = " ".join(text.split())
    if len(flattened) <= limit:
        return repr(flattened)
    return repr(flattened[:limit] + f"... [{len(flattened) - limit} more characters]")


__all__ = [
    "CLAUSE",
    "CLAUSE_TEXT",
    "BoundaryReport",
    "BoundaryViolation",
    "Violation",
    "check_plan_transcript",
    "check_prompts",
    "uncovered",
]
