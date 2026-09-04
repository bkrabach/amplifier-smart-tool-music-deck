"""The strict ``plan.v1`` validator: is this document a plan, and if not, where?

``apply`` never executes a document this module has not accepted, and ``plan``
never hands one back. That is the whole job: one place decides what a plan *is*,
so a plan written by one party is never misread by another (``plan.v1``
Purpose).

Contracts served
----------------
* ``plan.v1`` Core 1 -- ``plan_format`` is the **integer** 1. Not ``"1"``, not
  ``2``, not ``True``. The refusal names the version found.
* ``plan.v1`` Core 2 -- required top-level fields are ``plan_format``,
  ``brief``, ``target``, ``steps`` and ``rules``; ``size`` is optional.
  ``steps`` is an ordered list of at least one step.
* ``plan.v1`` Core 3 -- a step names music by **search expression only**, never
  by Spotify ID or URI.
* ``plan.v1`` Core 4 -- ``rules`` always carries all four of its keys, even
  when empty.
* ``plan.v1`` Core 5 -- a plan carries no Spotify content other than a
  caller-supplied ``target.playlist_id``.
* ``plan.v1`` Core 6 -- **strict validation**: "An unknown field at any level, a
  wrong type, or an out-of-range value makes ``apply`` refuse with
  ``invalid_plan``, naming the offending path. Nothing is silently ignored or
  coerced."
* ``cli.v1`` Core 6 -- the refusal is ``invalid_plan``, exit 2, carrying the
  offending path.

Why refusal is a raise and not a report
---------------------------------------
:func:`validate_plan` returns ``None`` or raises :class:`InvalidPlan`. It never
returns a list of findings, because a caller who forgets to read a returned list
gets a silently-accepted bad plan -- exactly the failure Core 6 exists to
prevent. The pure predicate underneath, :func:`plan_problem`, is available for
anything that wants to *ask* rather than be *stopped*; it is what the tests
enumerate the bad fixtures against.

Why the first problem, and not all of them
------------------------------------------
A document that is wrong in six places is wrong; enumerating all six invites a
caller to fix them one at a time and re-run six times. The refusal names the
first offending path in document order, which is the one to fix first. Order is
stable and derived from the contract's own clause order, so the same bad plan
always names the same path -- a refusal that moved between runs would not be
something a caller could write a test against.

Why nothing here is coerced
---------------------------
``plan_format: "1"`` is refused rather than read as ``1``; ``take: "20"`` is
refused rather than parsed. Core 6 says so in as many words, and the reason is
the boundary: a plan is the document a caller reads and *trusts* before anything
touches their account. A validator that quietly repairs a plan hands back
something the caller never read.
"""

from __future__ import annotations

import re
from typing import Any, Final

from music_deck.errors import ErrorCode, MusicDeckError

PLAN_FORMAT: Final = 1
"""``plan.v1`` Core 1: "A plan is one JSON document with integer ``plan_format: 1``." """

# -- the vocabulary, verbatim from the contract ------------------------------ #
PLAN_REQUIRED: Final[tuple[str, ...]] = (
    "plan_format",
    "brief",
    "target",
    "steps",
    "rules",
)
PLAN_OPTIONAL: Final[tuple[str, ...]] = ("size",)

TARGET_KINDS: Final[tuple[str, ...]] = ("new", "existing")
TARGET_FIELDS: Final[dict[str, tuple[str, ...]]] = {
    "new": ("kind", "name", "description"),
    "existing": ("kind", "playlist_id"),
}

STEP_FIELDS: Final[tuple[str, ...]] = ("search", "type", "take", "why")
STEP_TYPES: Final[tuple[str, ...]] = ("track", "album")
TAKE_MIN: Final = 1
TAKE_MAX: Final = 50

RULES_FIELDS: Final[tuple[str, ...]] = (
    "exclude_artists",
    "exclude_title_terms",
    "dedupe",
    "order",
)
DEDUPE_VALUES: Final[tuple[str, ...]] = (
    "none",
    "by_track_id",
    "by_title_and_primary_artist",
)
ORDER_VALUES: Final[tuple[str, ...]] = ("as_planned", "shuffle")

SIZE_FIELDS: Final[tuple[str, ...]] = ("minutes", "tracks", "tolerance_pct")

# -- Core 3 / Core 5: what "names music by identity" looks like -------------- #
_SPOTIFY_URI_RE: Final = re.compile(r"spotify:[a-z]+:[0-9A-Za-z]+")
_SPOTIFY_URL_RE: Final = re.compile(r"(?:open|play)\.spotify\.com/")
_SPOTIFY_ID_RE: Final = re.compile(r"\b[0-9A-Za-z]{22}\b")
"""A bare Spotify id: 22 base62 characters standing alone as a word.

Deliberately anchored on word boundaries rather than searched loose, so an
ordinary search expression -- ``genre:rock year:1990-1999`` -- is not mistaken
for an identity. What it catches is the thing Core 3 forbids: a step that names
one specific track instead of describing what to look for.
"""


class InvalidPlan(MusicDeckError):
    """A document ``plan.v1`` rejects, naming the offending path.

    ``cli.v1`` Core 6 gives this the frozen code ``invalid_plan`` and exit 2;
    both come from :class:`~music_deck.errors.MusicDeckError` rather than being
    restated here, so the vocabulary cannot fork.

    ``path`` is a JSONPath-ish pointer into the document the caller handed in --
    ``$.steps[2].take``, ``$.rules.dedupe`` -- which is what makes the refusal
    something a caller can act on rather than a verdict on the whole file.
    """

    def __init__(self, path: str, detail: str) -> None:
        super().__init__(
            ErrorCode.INVALID_PLAN,
            f"The plan is not valid under plan.v1 at {path}: {detail}.",
            f"Fix {path} in the plan document, then run `music-deck apply` again.",
            path=path,
        )
        self.path = path
        self.detail = detail


Problem = tuple[str, str]
"""``(path, detail)`` -- where the plan is wrong, and how."""


# --------------------------------------------------------------------------- #
# The public surface
# --------------------------------------------------------------------------- #
def validate_plan(plan: Any) -> None:
    """Accept a ``plan.v1`` document, or raise :class:`InvalidPlan`.

    Returns ``None`` on success. Raises on anything else -- an unknown field at
    any level, a wrong type, a value out of range, or a step that names Spotify
    content by identity.

    This is the signature ``music_deck.verbs.plan`` imports and the one
    ``apply`` calls before it opens a single connection.
    """
    problem = plan_problem(plan)
    if problem is not None:
        raise InvalidPlan(*problem)


def plan_problem(plan: Any) -> Problem | None:
    """The first way ``plan`` is not a ``plan.v1`` document, or ``None``.

    Pure: reads nothing, writes nothing, raises nothing. The clause order below
    is the contract's own -- shape, then Core 1, Core 2, Core 3, Core 4 -- so
    the path a caller is handed is the first thing worth fixing.
    """
    if not isinstance(plan, dict):
        return "$", f"a plan is one JSON object, got {_typename(plan)}"

    # Core 6 -- unknown fields are refused before anything else is looked at, so
    # a plan carrying a field this version does not know is never half-executed.
    problem = _unknown_field(plan, "$", PLAN_REQUIRED + PLAN_OPTIONAL)
    if problem is not None:
        return problem

    missing = [name for name in PLAN_REQUIRED if name not in plan]
    if missing:
        return (
            f"$.{missing[0]}",
            f"plan.v1 Core 2 requires {list(PLAN_REQUIRED)}; missing {missing}",
        )

    # Core 1 -- the integer 1, and nothing that merely looks like it.
    version = plan["plan_format"]
    if not _is_int(version):
        return (
            "$.plan_format",
            f"plan_format must be the integer {PLAN_FORMAT}, got "
            f"{version!r} ({_typename(version)}); nothing is coerced",
        )
    if version != PLAN_FORMAT:
        return (
            "$.plan_format",
            f"this build reads plan_format {PLAN_FORMAT}; the plan says {version}",
        )

    # Core 2 -- "`brief` is the caller's text, verbatim."
    brief = plan["brief"]
    if not isinstance(brief, str):
        return "$.brief", f"brief must be the caller's own text, got {_typename(brief)}"
    if not brief.strip():
        return "$.brief", "brief must be the caller's own text, and it is empty"

    problem = _target_problem(plan["target"])
    if problem is not None:
        return problem

    problem = _steps_problem(plan["steps"])
    if problem is not None:
        return problem

    problem = _rules_problem(plan["rules"])
    if problem is not None:
        return problem

    if "size" in plan:
        return _size_problem(plan["size"])
    return None


def names_spotify_content(text: str) -> bool:
    """Whether ``text`` names Spotify content by identity rather than describing it.

    ``plan.v1`` Core 3: "A step names music by search expression only, never by
    Spotify ID or URI." Core 5 gives the reason -- a plan free of Spotify
    identity is a plan that can cross the model boundary in either direction.
    """
    if not isinstance(text, str):
        return False
    return bool(
        _SPOTIFY_URI_RE.search(text)
        or _SPOTIFY_URL_RE.search(text)
        or _SPOTIFY_ID_RE.search(text)
    )


# --------------------------------------------------------------------------- #
# Core 2 -- target
# --------------------------------------------------------------------------- #
def _target_problem(target: Any) -> Problem | None:
    if not isinstance(target, dict):
        return "$.target", f"target must be an object, got {_typename(target)}"

    kind = target.get("kind")
    if "kind" not in target:
        return "$.target.kind", f"target needs a kind, one of {list(TARGET_KINDS)}"
    if kind not in TARGET_KINDS:
        return (
            "$.target.kind",
            f"kind must be one of {list(TARGET_KINDS)}, got {kind!r}",
        )

    allowed = TARGET_FIELDS[kind]
    problem = _unknown_field(target, "$.target", allowed)
    if problem is not None:
        return problem

    if kind == "new":
        name = target.get("name")
        if "name" not in target:
            return "$.target.name", "a new target needs the playlist's name"
        if not isinstance(name, str):
            return "$.target.name", f"name must be a string, got {_typename(name)}"
        if not name.strip():
            return "$.target.name", "name is empty; a new playlist needs a name"
        if "description" in target and not isinstance(target["description"], str):
            return (
                "$.target.description",
                f"description must be a string, got {_typename(target['description'])}",
            )
        return None

    playlist_id = target.get("playlist_id")
    if "playlist_id" not in target:
        return (
            "$.target.playlist_id",
            "an existing target needs the playlist_id to extend",
        )
    if not isinstance(playlist_id, str):
        return (
            "$.target.playlist_id",
            f"playlist_id must be a string, got {_typename(playlist_id)}",
        )
    if not playlist_id.strip():
        return "$.target.playlist_id", "playlist_id is empty"
    return None


# --------------------------------------------------------------------------- #
# Core 2 / Core 3 -- steps
# --------------------------------------------------------------------------- #
def _steps_problem(steps: Any) -> Problem | None:
    if not isinstance(steps, list):
        return (
            "$.steps",
            f"steps must be an ordered list of at least one step, got "
            f"{_typename(steps)}",
        )
    if not steps:
        return "$.steps", "steps is empty; plan.v1 Core 2 requires at least one step"
    for index, step in enumerate(steps):
        problem = _step_problem(step, index)
        if problem is not None:
            return problem
    return None


def _step_problem(step: Any, index: int) -> Problem | None:
    where = f"$.steps[{index}]"
    if not isinstance(step, dict):
        return where, f"a step must be an object, got {_typename(step)}"

    problem = _unknown_field(step, where, STEP_FIELDS)
    if problem is not None:
        return problem
    missing = [name for name in STEP_FIELDS if name not in step]
    if missing:
        return (
            f"{where}.{missing[0]}",
            f"plan.v1 Core 3 shapes a step as {list(STEP_FIELDS)}; missing {missing}",
        )

    search = step["search"]
    if not isinstance(search, str):
        return (
            f"{where}.search",
            f"search must be a search expression, got {_typename(search)}",
        )
    if not search.strip():
        return f"{where}.search", "search is empty; it must be a search expression"
    if names_spotify_content(search):
        return (
            f"{where}.search",
            "plan.v1 Core 3 -- a step names music by search expression only, "
            f"never by Spotify ID or URI; got {search!r}",
        )

    kind = step["type"]
    if kind not in STEP_TYPES:
        return (
            f"{where}.type",
            f"type must be one of {list(STEP_TYPES)}, got {kind!r}",
        )

    take = step["take"]
    if not _is_int(take):
        return (
            f"{where}.take",
            f"take must be an integer {TAKE_MIN}..{TAKE_MAX}, got {take!r} "
            f"({_typename(take)}); nothing is coerced",
        )
    if not TAKE_MIN <= take <= TAKE_MAX:
        return (
            f"{where}.take",
            f"take must be {TAKE_MIN}..{TAKE_MAX}, got {take}",
        )

    why = step["why"]
    if not isinstance(why, str):
        return f"{where}.why", f"why must be a string, got {_typename(why)}"
    if not why.strip():
        return f"{where}.why", "why is empty; say in one line why this step is here"
    return None


# --------------------------------------------------------------------------- #
# Core 4 -- rules
# --------------------------------------------------------------------------- #
def _rules_problem(rules: Any) -> Problem | None:
    if not isinstance(rules, dict):
        return "$.rules", f"rules must be an object, got {_typename(rules)}"

    problem = _unknown_field(rules, "$.rules", RULES_FIELDS)
    if problem is not None:
        return problem
    missing = [name for name in RULES_FIELDS if name not in rules]
    if missing:
        return (
            f"$.rules.{missing[0]}",
            f"plan.v1 Core 4 -- rules always carries all four of "
            f"{list(RULES_FIELDS)}, even when empty; missing {missing}",
        )

    for name in ("exclude_artists", "exclude_title_terms"):
        value = rules[name]
        if not isinstance(value, list):
            return (
                f"$.rules.{name}",
                f"{name} must be a list of strings (possibly empty), got "
                f"{_typename(value)}",
            )
        for position, item in enumerate(value):
            if not isinstance(item, str):
                return (
                    f"$.rules.{name}[{position}]",
                    f"{name} holds strings; got {_typename(item)}",
                )

    if rules["dedupe"] not in DEDUPE_VALUES:
        return (
            "$.rules.dedupe",
            f"dedupe must be one of {list(DEDUPE_VALUES)}, got {rules['dedupe']!r}",
        )
    if rules["order"] not in ORDER_VALUES:
        return (
            "$.rules.order",
            f"order must be one of {list(ORDER_VALUES)}, got {rules['order']!r}",
        )
    return None


# --------------------------------------------------------------------------- #
# Core 2 -- size (optional, and advisory: plan.v1 does not freeze it as a limit)
# --------------------------------------------------------------------------- #
def _size_problem(size: Any) -> Problem | None:
    if not isinstance(size, dict):
        return "$.size", f"size must be an object, got {_typename(size)}"

    problem = _unknown_field(size, "$.size", SIZE_FIELDS)
    if problem is not None:
        return problem

    named = [name for name in ("minutes", "tracks") if name in size]
    if len(named) != 1:
        return (
            "$.size",
            f"size names exactly one of minutes or tracks; got {named or 'neither'}",
        )
    if "tolerance_pct" not in size:
        return "$.size.tolerance_pct", "size needs a tolerance_pct"
    for name in named + ["tolerance_pct"]:
        value = size[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return (
                f"$.size.{name}",
                f"{name} must be a number, got {value!r} ({_typename(value)})",
            )
        if value < 0:
            return f"$.size.{name}", f"{name} must not be negative, got {value}"
    return None


# --------------------------------------------------------------------------- #
# Shared
# --------------------------------------------------------------------------- #
def _unknown_field(node: dict[str, Any], where: str, allowed: tuple[str, ...]) -> Problem | None:
    """``plan.v1`` Core 6 -- an unknown field at *any* level, named by its path."""
    unknown = sorted(set(node) - set(allowed))
    if not unknown:
        return None
    first = unknown[0]
    return (
        f"{where}.{first}" if where != "$" else f"$.{first}",
        f"unknown field(s) {unknown}; plan.v1 Core 6 ignores nothing silently. "
        f"This level accepts {list(allowed)}",
    )


def _is_int(value: Any) -> bool:
    """A real integer. ``True`` is not one, however much Python disagrees."""
    return isinstance(value, int) and not isinstance(value, bool)


def _typename(value: Any) -> str:
    """The JSON name for a Python value's type, for a message a caller reads."""
    return {
        type(None): "null",
        bool: "boolean",
        int: "number",
        float: "number",
        str: "string",
        list: "array",
        dict: "object",
    }.get(type(value), type(value).__name__)


__all__ = [
    "DEDUPE_VALUES",
    "InvalidPlan",
    "ORDER_VALUES",
    "PLAN_FORMAT",
    "PLAN_OPTIONAL",
    "PLAN_REQUIRED",
    "RULES_FIELDS",
    "STEP_FIELDS",
    "STEP_TYPES",
    "TAKE_MAX",
    "TAKE_MIN",
    "TARGET_KINDS",
    "names_spotify_content",
    "plan_problem",
    "validate_plan",
]
