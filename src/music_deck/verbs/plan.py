"""`plan` -- a brief in the caller's words becomes a plan document.

The only model-backed verb (``cli.v1`` Core 3), and the one place in music-deck
where a prompt is assembled. Four promises are kept here, in this order:

1. **It refuses before it builds anything.** ``preflight`` runs first, on the
   line after the argument check and before a single character of prompt is
   assembled. With no usable model substrate the caller gets exit 3 naming the
   missing precondition (``cli.v1`` Core 3) -- never a silent fallback to a
   deterministic answer, and never a prompt built for a turn that cannot run.
2. **It makes no Spotify request** (``boundary.v1`` Core 1). Nothing in this
   module's import graph can: it reaches the network only through the model
   seam, and it needs no token, no client ID, and no reachable
   ``api.spotify.com``.
3. **Every word of the prompt comes from one of two places** (``boundary.v1``
   Core 2): ``music_deck/prompts/plan.md``, or the caller's own arguments.
   ``assemble_prompt`` is the whole of the assembly and it interleaves nothing
   else -- see the note on why there is no repair round.
4. **It publishes the transcript** (``boundary.v1`` Core 3), so clause 2 is
   something a reviewer confirms from the tool's own output rather than from
   its source.

Why there is no draft-and-repair round
--------------------------------------
The obvious way to make a model's JSON reliable is to hand a rejected draft
back with the validator's findings and ask again. music-deck does not, and the
reason is clause 2: a repair prompt would carry the model's own previous
output, which is neither the caller's text nor music-deck's static prompt text.
It would fail this tool's own boundary check -- correctly. One turn, one prompt,
one transcript entry; a draft that does not validate is a refusal naming the
offending path, which the caller can act on.
"""

from __future__ import annotations

import json
import re
from typing import Any, Final, Sequence

from music_deck.errors import ErrorCode, MusicDeckError
from music_deck.intelligence import Intelligence, ModelRequest, resolve
from music_deck.prompt_boundary import check_plan_transcript
from music_deck.prompts import plan_prompt_parts, static_prompt_texts

PLAN_FORMAT: Final = 1

_JSON_FENCE_RE: Final = re.compile(r"```(?:json)?\s*\n(.*?)```", re.DOTALL)

# plan.v1 Core 3 and Core 5: a step names music by search expression only.
_SPOTIFY_URI_RE: Final = re.compile(r"spotify:[a-z]+:[0-9A-Za-z]{22}")
_SPOTIFY_URL_RE: Final = re.compile(r"open\.spotify\.com/")
_SPOTIFY_ID_RE: Final = re.compile(r"\b[0-9A-Za-z]{22}\b")

_TARGET_KINDS: Final = ("new", "existing")
_STEP_TYPES: Final = ("track", "album")
_DEDUPE: Final = ("none", "by_track_id", "by_title_and_primary_artist")
_ORDER: Final = ("as_planned", "shuffle")

_PLAN_REQUIRED: Final = ("plan_format", "brief", "target", "steps", "rules")
_PLAN_OPTIONAL: Final = ("size",)
# What the model is asked for. `plan_format` and `brief` are music-deck's to
# fill in, so that plan.v1 Core 2's "the caller's text, verbatim" is true by
# construction rather than by the model's good behaviour.
_DRAFT_REQUIRED: Final = ("target", "steps", "rules")
_DRAFT_OPTIONAL: Final = ("size", "plan_format", "brief")


# --------------------------------------------------------------------------- #
# The prompt -- the whole of it
# --------------------------------------------------------------------------- #
def assemble_prompt(brief: str, context: str | None = None) -> str:
    """Build the one prompt ``plan`` sends.

    Segments, in order: music-deck's static instructions, its static heading for
    the brief, the caller's brief **verbatim**, and -- when the caller attached
    context -- its static heading for that, then the caller's payload verbatim.
    Joined with blank lines, which are whitespace and so cost nothing at the
    boundary check.

    Verbatim matters twice over: ``plan.v1`` Core 2 wants the caller's exact
    words in the plan, and the boundary check covers a prompt by removing its
    allowed sources from it -- a brief that was trimmed on the way in would no
    longer match the brief the reviewer checks against, and would read as a
    leak.
    """
    parts = plan_prompt_parts()
    segments = [parts["instructions"], parts["brief"], brief]
    if context is not None and context.strip():
        segments += [parts["context"], context]
    return "\n\n".join(segments)


# --------------------------------------------------------------------------- #
# The verb
# --------------------------------------------------------------------------- #
def plan(
    brief: str,
    *,
    context: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    intelligence: Intelligence | None = None,
) -> dict[str, Any]:
    """Turn a brief into a plan document, and publish what was sent to get it.

    Model-backed: it spends tokens and may answer differently on a second run.
    Makes no Spotify request, needs no token, and works with no network
    reachability to ``api.spotify.com`` at all.

    ``context`` is material the caller already holds, passed as **data**. The
    CLI may read it out of a file; the library takes the content, because a
    library that reads paths on a caller's behalf is a library that decides what
    a caller may read.

    Returns ``{"plan": <plan.v1 document>, "transcript": [<every prompt sent>]}``.
    """
    if not brief or not brief.strip():
        raise MusicDeckError(
            ErrorCode.USAGE,
            "`music-deck plan` needs a brief: what you want, in your own words.",
            'Run: music-deck plan "upbeat 90s guitar songs for a Saturday morning"',
        )

    engine = resolve(intelligence)

    # cli.v1 Core 3, and the whole reason preflight is a separate method: the
    # refusal happens here, before any prompt exists. Nothing above this line
    # has assembled a character of prompt, and nothing below it runs if this
    # raises.
    engine.preflight(provider)

    prompt = assemble_prompt(brief, context)
    transcript = [prompt]

    result = engine.run(ModelRequest(prompt=prompt, provider=provider, model=model))

    # boundary.v1 Core 2, checked by the tool against itself before the caller
    # ever sees the answer. The transcript is published either way (Core 3), but
    # a build that leaked would fail loudly here rather than shipping a plan
    # whose provenance nobody looked at.
    _assert_boundary_kept(transcript, brief=brief, context=context)

    draft = extract_json_object(result.text)
    if draft is None:
        raise MusicDeckError(
            ErrorCode.INVALID_PLAN,
            "The model returned no JSON object, so there is no plan to hand back. "
            f"It replied: {_snippet(result.text)}",
            "Run `music-deck plan` again, or rephrase the brief. music-deck never "
            "invents a plan the model did not produce.",
            path="$",
        )

    document = compose_plan(brief, draft)
    validate_plan_document(document)
    return {"plan": document, "transcript": transcript}


def compose_plan(brief: str, draft: dict[str, Any]) -> dict[str, Any]:
    """Build the finished plan from the caller's brief and the model's draft.

    ``plan_format`` and ``brief`` are music-deck's to write. The draft may echo
    them, and they must then agree -- an echoed brief that differs from the
    caller's words is refused rather than quietly replaced, because a plan whose
    ``brief`` is a paraphrase is a plan the caller cannot check themselves.
    """
    unknown = sorted(set(draft) - set(_DRAFT_REQUIRED) - set(_DRAFT_OPTIONAL))
    if unknown:
        raise _invalid(f"$.{unknown[0]}", f"the model returned unknown field(s): {unknown}")
    missing = [name for name in _DRAFT_REQUIRED if name not in draft]
    if missing:
        raise _invalid(f"$.{missing[0]}", f"the model's draft is missing: {missing}")

    if "plan_format" in draft and draft["plan_format"] != PLAN_FORMAT:
        raise _invalid(
            "$.plan_format",
            f"the model returned plan_format {draft['plan_format']!r}; this build "
            f"writes plan_format {PLAN_FORMAT}",
        )
    if "brief" in draft and draft["brief"] != brief:
        raise _invalid(
            "$.brief",
            "the model rewrote the brief. plan.v1 Core 2 requires the caller's "
            "text verbatim",
        )

    document: dict[str, Any] = {
        "plan_format": PLAN_FORMAT,
        "brief": brief,
        "target": draft["target"],
        "steps": draft["steps"],
        "rules": draft["rules"],
    }
    if "size" in draft:
        document["size"] = draft["size"]
    return document


# --------------------------------------------------------------------------- #
# Validation -- MD-5's validator when it lands, a minimal check until then
# --------------------------------------------------------------------------- #
def validate_plan_document(document: dict[str, Any]) -> None:
    """Refuse a document that is not a ``plan.v1`` plan, naming the path.

    Prefers ``music_deck.plan_schema.validate_plan`` -- MD-5 (music_deck-v0b)
    owns the real validator and the fixtures behind it. Until that lands, the
    local check below stands in: it enforces plan.v1 Core 1-6 as written but is
    deliberately the smaller thing, and MD-5 replaces it wholesale.
    """
    try:
        from music_deck.plan_schema import validate_plan  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - not landed yet is the ordinary case
        validate_plan = None  # type: ignore[assignment]

    if validate_plan is not None:
        problems = validate_plan(document)
        # A validator that raises has already refused; one that returns findings
        # hands them here. Both shapes are honoured so MD-5 can pick either.
        if problems:
            first = problems[0] if isinstance(problems, (list, tuple)) else problems
            raise _invalid(str(getattr(first, "path", "$")), str(first))
        return

    problem = _first_problem(document)
    if problem is not None:
        path, detail = problem
        raise _invalid(path, detail)


def _first_problem(document: Any) -> tuple[str, str] | None:
    """The first way ``document`` is not a plan.v1 plan, or None. Pure."""
    if not isinstance(document, dict):
        return "$", f"a plan is one JSON object, got {type(document).__name__}"

    unknown = sorted(set(document) - set(_PLAN_REQUIRED) - set(_PLAN_OPTIONAL))
    if unknown:
        return f"$.{unknown[0]}", f"unknown field(s) at the top level: {unknown}"
    missing = [name for name in _PLAN_REQUIRED if name not in document]
    if missing:
        return f"$.{missing[0]}", f"required field(s) missing: {missing}"

    version = document["plan_format"]
    if isinstance(version, bool) or not isinstance(version, int) or version != PLAN_FORMAT:
        return "$.plan_format", f"plan_format must be the integer {PLAN_FORMAT}, got {version!r}"
    if not isinstance(document["brief"], str) or not document["brief"].strip():
        return "$.brief", "brief must be the caller's own text, and not empty"

    problem = _target_problem(document["target"])
    if problem is not None:
        return problem

    steps = document["steps"]
    if not isinstance(steps, list) or not steps:
        return "$.steps", "steps must be an ordered list of at least one step"
    for index, step in enumerate(steps):
        problem = _step_problem(step, index)
        if problem is not None:
            return problem

    problem = _rules_problem(document["rules"])
    if problem is not None:
        return problem

    if "size" in document:
        return _size_problem(document["size"])
    return None


def _target_problem(target: Any) -> tuple[str, str] | None:
    if not isinstance(target, dict):
        return "$.target", f"target must be an object, got {type(target).__name__}"
    kind = target.get("kind")
    if kind not in _TARGET_KINDS:
        return "$.target.kind", f"kind must be one of {list(_TARGET_KINDS)}, got {kind!r}"
    allowed = ("kind", "name", "description") if kind == "new" else ("kind", "playlist_id")
    unknown = sorted(set(target) - set(allowed))
    if unknown:
        return f"$.target.{unknown[0]}", f"unknown field(s) for kind {kind!r}: {unknown}"
    if kind == "new":
        if not isinstance(target.get("name"), str) or not target["name"].strip():
            return "$.target.name", "a new target needs a non-empty name"
        if "description" in target and not isinstance(target["description"], str):
            return "$.target.description", "description must be a string"
    else:
        if not isinstance(target.get("playlist_id"), str) or not target["playlist_id"].strip():
            return "$.target.playlist_id", "an existing target needs a playlist_id"
    return None


def _step_problem(step: Any, index: int) -> tuple[str, str] | None:
    where = f"$.steps[{index}]"
    if not isinstance(step, dict):
        return where, f"a step must be an object, got {type(step).__name__}"
    allowed = ("search", "type", "take", "why")
    unknown = sorted(set(step) - set(allowed))
    if unknown:
        return f"{where}.{unknown[0]}", f"unknown field(s) in a step: {unknown}"
    missing = [name for name in allowed if name not in step]
    if missing:
        return f"{where}.{missing[0]}", f"a step needs all of {list(allowed)}; missing {missing}"

    search = step["search"]
    if not isinstance(search, str) or not search.strip():
        return f"{where}.search", "search must be a non-empty search expression"
    if _names_spotify_content(search):
        return (
            f"{where}.search",
            "plan.v1 Core 3: a step names music by search expression only, never by "
            f"Spotify ID or URI -- got {search!r}",
        )
    if step["type"] not in _STEP_TYPES:
        return f"{where}.type", f"type must be one of {list(_STEP_TYPES)}, got {step['type']!r}"
    take = step["take"]
    if isinstance(take, bool) or not isinstance(take, int) or not 1 <= take <= 50:
        return f"{where}.take", f"take must be an integer 1..50, got {take!r}"
    if not isinstance(step["why"], str) or not step["why"].strip():
        return f"{where}.why", "why must say, in one line, why this step is here"
    return None


def _rules_problem(rules: Any) -> tuple[str, str] | None:
    if not isinstance(rules, dict):
        return "$.rules", f"rules must be an object, got {type(rules).__name__}"
    required = ("exclude_artists", "exclude_title_terms", "dedupe", "order")
    unknown = sorted(set(rules) - set(required))
    if unknown:
        return f"$.rules.{unknown[0]}", f"unknown field(s) in rules: {unknown}"
    missing = [name for name in required if name not in rules]
    if missing:
        return (
            f"$.rules.{missing[0]}",
            f"plan.v1 Core 4: rules always carries all four keys, even when empty; "
            f"missing {missing}",
        )
    for name in ("exclude_artists", "exclude_title_terms"):
        value = rules[name]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            return f"$.rules.{name}", f"{name} must be a list of strings (possibly empty)"
    if rules["dedupe"] not in _DEDUPE:
        return "$.rules.dedupe", f"dedupe must be one of {list(_DEDUPE)}, got {rules['dedupe']!r}"
    if rules["order"] not in _ORDER:
        return "$.rules.order", f"order must be one of {list(_ORDER)}, got {rules['order']!r}"
    return None


def _size_problem(size: Any) -> tuple[str, str] | None:
    if not isinstance(size, dict):
        return "$.size", f"size must be an object, got {type(size).__name__}"
    unknown = sorted(set(size) - {"minutes", "tracks", "tolerance_pct"})
    if unknown:
        return f"$.size.{unknown[0]}", f"unknown field(s) in size: {unknown}"
    named = [name for name in ("minutes", "tracks") if name in size]
    if len(named) != 1:
        return "$.size", "size names exactly one of minutes or tracks"
    for name in named + ["tolerance_pct"]:
        value = size.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            return f"$.size.{name}", f"{name} must be a non-negative number, got {value!r}"
    return None


def _names_spotify_content(text: str) -> bool:
    """Whether a search expression carries an identity rather than a description."""
    return bool(
        _SPOTIFY_URI_RE.search(text)
        or _SPOTIFY_URL_RE.search(text)
        or _SPOTIFY_ID_RE.search(text)
    )


# --------------------------------------------------------------------------- #
# Reading the model's reply
# --------------------------------------------------------------------------- #
def extract_json_object(reply: str) -> dict[str, Any] | None:
    """The JSON object in a reply, or None when nothing parses as one.

    Fenced blocks last-first, then the widest brace-delimited span, so a model
    that narrates around its answer still yields the answer. Deterministic: a
    reply carrying no recoverable object is a failure, never a prompt to guess
    at the prose around it.
    """
    for candidate in reversed(_JSON_FENCE_RE.findall(reply or "")):
        parsed = _load_object(candidate)
        if parsed is not None:
            return parsed
    start = (reply or "").find("{")
    end = (reply or "").rfind("}")
    if start != -1 and end > start:
        return _load_object(reply[start : end + 1])
    return None


def _load_object(text: str) -> dict[str, Any] | None:
    try:
        loaded = json.loads(text)
    except ValueError:
        return None
    return loaded if isinstance(loaded, dict) else None


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _assert_boundary_kept(
    transcript: Sequence[str], *, brief: str, context: str | None
) -> None:
    report = check_plan_transcript(
        transcript, brief=brief, context=context, static_texts=static_prompt_texts()
    )
    if not report.ok:
        raise MusicDeckError(
            "boundary_violation",
            "music-deck refused to hand back a plan whose prompt broke its own "
            f"one-way boundary.\n{report.describe()}",
            "This is a defect in music-deck, not in your invocation. Report it "
            "with the message above; no Spotify content should ever be able to "
            "reach a prompt.",
        )


def _invalid(path: str, detail: str) -> MusicDeckError:
    return MusicDeckError(
        ErrorCode.INVALID_PLAN,
        f"The plan is not valid under plan.v1 at {path}: {detail}.",
        f"Fix {path} in the plan, or run `music-deck plan` again.",
        path=path,
    )


def _snippet(text: str, limit: int = 200) -> str:
    flattened = " ".join((text or "").split())
    if len(flattened) <= limit:
        return repr(flattened)
    return repr(flattened[:limit] + "...")


__all__ = [
    "PLAN_FORMAT",
    "assemble_prompt",
    "compose_plan",
    "extract_json_object",
    "plan",
    "validate_plan_document",
]
