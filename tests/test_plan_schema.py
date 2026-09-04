"""The strict `plan.v1` validator: what is a plan, and where is a bad one wrong?

Contracts under test: ``plan.v1`` Core 1 (integer ``plan_format: 1``), Core 2
(required top-level fields; ``steps`` ordered and non-empty), Core 3 (a step
names music by search expression only), Core 4 (``rules`` carries all four
keys), Core 5 (no Spotify content beyond ``target.playlist_id``), Core 6
(strict validation naming the offending path, nothing coerced); ``cli.v1``
Core 6 (``invalid_plan``) and Core 5 (exit 2).

Two things make this file more than a restatement of the validator.

**The fixtures are files, not literals.** Every case below is a real JSON
document in ``tests/fixtures/plans/``, which is also what
``tests/test_apply.py`` points the binary at. A validator and a test that agree
because they were written from the same paragraph prove less than a validator
and a *document a caller could actually hand over*.

**The expected path is asserted, not just the refusal.** ``plan.v1`` Core 6
promises the refusal names "the offending path". A test that only checked
``invalid_plan`` would pass for a validator that named ``$`` every time, which
is the failure mode worth catching: a path that does not point at the problem
is no better than no path at all.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from music_deck.errors import EXIT_REFUSAL, ErrorCode
from music_deck.plan_schema import (
    DEDUPE_VALUES,
    ORDER_VALUES,
    PLAN_FORMAT,
    PLAN_REQUIRED,
    RULES_FIELDS,
    STEP_FIELDS,
    STEP_TYPES,
    TAKE_MAX,
    TAKE_MIN,
    InvalidPlan,
    names_spotify_content,
    plan_problem,
    validate_plan,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "plans"


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def fixture_names(prefix: str) -> list[str]:
    return sorted(path.name for path in FIXTURES.glob(f"{prefix}-*.json"))


# --------------------------------------------------------------------------- #
# The bad fixtures, and the path each must name
# --------------------------------------------------------------------------- #
# The first twelve rows are the cases music_deck-v0b's acceptance criteria
# enumerate, in its own order. The rest are the neighbouring cases Core 6 also
# covers -- kept here rather than left to the validator's own confidence,
# because "unknown field at ANY level" is a claim about levels this file has to
# visit one at a time.
REFUSALS: dict[str, str] = {
    # -- the enumerated twelve ---------------------------------------------- #
    "bad-missing-required-field.json": "$.rules",
    "bad-wrong-type.json": "$.steps",
    "bad-unknown-field-top-level.json": "$.market",
    "bad-unknown-field-in-step.json": "$.steps[0].exclude_explicit",
    "bad-plan-format-2.json": "$.plan_format",
    "bad-plan-format-string.json": "$.plan_format",
    "bad-step-search-is-a-uri.json": "$.steps[0].search",
    "bad-step-search-is-an-id.json": "$.steps[1].search",
    "bad-take-zero.json": "$.steps[0].take",
    "bad-take-fifty-one.json": "$.steps[1].take",
    "bad-dedupe-fuzzy.json": "$.rules.dedupe",
    "bad-rules-missing-a-key.json": "$.rules.order",
    # -- the rest of Core 6 -------------------------------------------------- #
    "bad-not-an-object.json": "$",
    "bad-plan-format-boolean.json": "$.plan_format",
    "bad-take-is-a-string.json": "$.steps[0].take",
    "bad-unknown-field-in-rules.json": "$.rules.exclude_explicit",
    "bad-unknown-field-in-target.json": "$.target.public",
    "bad-unknown-field-in-size.json": "$.size.hard",
    "bad-target-kind.json": "$.target.kind",
    "bad-existing-target-has-a-name.json": "$.target.name",
    "bad-steps-empty.json": "$.steps",
    "bad-step-type.json": "$.steps[0].type",
    "bad-order-value.json": "$.rules.order",
    "bad-exclude-artists-not-strings.json": "$.rules.exclude_artists[0]",
    "bad-brief-missing.json": "$.brief",
    "bad-brief-empty.json": "$.brief",
}


def test_the_refusal_table_covers_every_bad_fixture_on_disk():
    """A fixture with no expectation would sit there proving nothing.

    Derived from the directory rather than retyped, so adding a bad plan
    without saying what it should refuse *fails* instead of passing quietly.
    """
    assert set(REFUSALS) == set(fixture_names("bad"))


def test_there_are_good_fixtures_to_accept():
    """Guards the whole file against passing vacuously on an empty directory."""
    assert len(fixture_names("good")) >= 4
    assert len(fixture_names("bad")) >= 12


# --------------------------------------------------------------------------- #
# Core 6 -- every bad plan is refused, naming its path
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", sorted(REFUSALS))
def test_a_bad_plan_is_refused_naming_the_offending_path(name):
    with pytest.raises(InvalidPlan) as raised:
        validate_plan(load(name))

    error = raised.value
    assert error.code == ErrorCode.INVALID_PLAN
    assert error.exit_code == EXIT_REFUSAL  # cli.v1 Core 5 / Core 6: "exit 2"
    assert error.path == REFUSALS[name]
    assert error.envelope()["error"]["path"] == REFUSALS[name]
    # The path has to be *in the message* too: a caller reading the one-line
    # message should not have to know there is a separate field to look at.
    assert REFUSALS[name] in error.message
    assert error.remedy.strip()


@pytest.mark.parametrize("name", sorted(REFUSALS))
def test_the_pure_predicate_agrees_with_the_raising_one(name):
    """`plan_problem` is what anything that wants to *ask* rather than be
    *stopped* uses; the two must never disagree about the same document."""
    problem = plan_problem(load(name))
    assert problem is not None
    assert problem[0] == REFUSALS[name]
    assert problem[1].strip()


# --------------------------------------------------------------------------- #
# The good fixtures
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", fixture_names("good"))
def test_a_good_plan_is_accepted(name):
    assert validate_plan(load(name)) is None
    assert plan_problem(load(name)) is None


def test_the_contracts_own_worked_example_validates():
    """`plan.v1`'s Example block, verbatim.

    The contract prints a plan and says ``apply`` can execute it as written. If
    this build's validator refuses that document, one of the two is wrong -- and
    a copy of it here is the only way that shows up as a failing test rather
    than as a surprise the first time somebody pastes the example.
    """
    example = {
        "plan_format": 1,
        "brief": "upbeat 90s guitar songs for a Saturday morning",
        "target": {"kind": "new", "name": "Saturday Morning Guitar"},
        "steps": [
            {
                "search": "genre:rock year:1990-1999",
                "type": "track",
                "take": 20,
                "why": "core 90s guitar-rock sound",
            }
        ],
        "rules": {
            "exclude_artists": [],
            "exclude_title_terms": ["remix"],
            "dedupe": "by_track_id",
            "order": "shuffle",
        },
    }
    assert validate_plan(example) is None


def test_the_contracts_own_bad_example_is_refused():
    """`plan.v1`'s closing line: a step naming ``spotify:track:abc123`` is bad."""
    plan = load("good-minimal.json")
    plan["steps"][0]["search"] = "spotify:track:abc123"
    with pytest.raises(InvalidPlan) as raised:
        validate_plan(plan)
    assert raised.value.path == "$.steps[0].search"


# --------------------------------------------------------------------------- #
# Core 6 -- "Nothing is silently ignored or coerced"
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "value",
    [1.0, "1", True, [1], {"v": 1}, None],
    ids=["float", "string", "boolean", "array", "object", "null"],
)
def test_plan_format_accepts_the_integer_and_nothing_that_resembles_it(value):
    """Core 1 says *integer* 1. ``1.0`` and ``True`` both equal 1 in Python."""
    plan = load("good-minimal.json")
    plan["plan_format"] = value
    with pytest.raises(InvalidPlan) as raised:
        validate_plan(plan)
    assert raised.value.path == "$.plan_format"


@pytest.mark.parametrize("value", ["25", 25.0, True, None], ids=["str", "float", "bool", "null"])
def test_take_is_not_coerced_from_something_that_looks_like_a_number(value):
    plan = load("good-minimal.json")
    plan["steps"][0]["take"] = value
    with pytest.raises(InvalidPlan) as raised:
        validate_plan(plan)
    assert raised.value.path == "$.steps[0].take"


@pytest.mark.parametrize("take", [0, -1, 51, 1000])
def test_take_out_of_range_is_refused(take):
    plan = load("good-minimal.json")
    plan["steps"][0]["take"] = take
    with pytest.raises(InvalidPlan):
        validate_plan(plan)


@pytest.mark.parametrize("take", [TAKE_MIN, 10, TAKE_MAX])
def test_take_at_and_inside_the_bounds_is_accepted(take):
    """The bounds themselves, which an off-by-one would quietly move."""
    plan = load("good-minimal.json")
    plan["steps"][0]["take"] = take
    assert validate_plan(plan) is None


# --------------------------------------------------------------------------- #
# Core 6 -- "an unknown field at ANY level"
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("where", "expected"),
    [
        ((), "$.surprise"),
        (("target",), "$.target.surprise"),
        (("rules",), "$.rules.surprise"),
        (("steps", 0), "$.steps[0].surprise"),
    ],
    ids=["top-level", "target", "rules", "step"],
)
def test_an_unknown_field_at_any_level_is_refused_by_its_own_path(where, expected):
    plan = load("good-minimal.json")
    node = plan
    for key in where:
        node = node[key]
    node["surprise"] = "hello"

    with pytest.raises(InvalidPlan) as raised:
        validate_plan(plan)
    assert raised.value.path == expected


def test_an_unknown_field_in_the_optional_size_block_is_refused_too():
    plan = load("good-with-size.json")
    plan["size"]["surprise"] = 1
    with pytest.raises(InvalidPlan) as raised:
        validate_plan(plan)
    assert raised.value.path == "$.size.surprise"


def test_a_field_that_belongs_to_the_other_target_kind_is_unknown_here():
    """`{"kind": "new"}` does not accept ``playlist_id``, and vice versa.

    Core 2 shapes the two kinds separately. A validator that merged their field
    lists would accept ``{"kind": "new", "playlist_id": ...}`` -- a plan that
    reads as if it will extend something and in fact creates something.
    """
    plan = load("good-minimal.json")
    plan["target"]["playlist_id"] = "37i9dQZF1DXcBWIGoYBM5M"
    with pytest.raises(InvalidPlan) as raised:
        validate_plan(plan)
    assert raised.value.path == "$.target.playlist_id"


# --------------------------------------------------------------------------- #
# Core 2 -- the required fields, one at a time
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("field", PLAN_REQUIRED)
def test_each_required_top_level_field_is_required(field):
    plan = load("good-minimal.json")
    del plan[field]
    with pytest.raises(InvalidPlan) as raised:
        validate_plan(plan)
    assert raised.value.path == f"$.{field}"


def test_size_is_the_only_optional_top_level_field():
    plan = load("good-with-size.json")
    del plan["size"]
    assert validate_plan(plan) is None


# --------------------------------------------------------------------------- #
# Core 4 -- rules carries all four keys, even when empty
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("field", RULES_FIELDS)
def test_each_rules_key_is_required_even_when_it_would_be_empty(field):
    plan = load("good-minimal.json")
    del plan["rules"][field]
    with pytest.raises(InvalidPlan) as raised:
        validate_plan(plan)
    assert raised.value.path == f"$.rules.{field}"


def test_empty_rules_are_valid_rules():
    """"even when empty" is the clause, so this must pass, not merely not crash."""
    plan = load("good-minimal.json")
    plan["rules"] = {
        "exclude_artists": [],
        "exclude_title_terms": [],
        "dedupe": "none",
        "order": "as_planned",
    }
    assert validate_plan(plan) is None


@pytest.mark.parametrize("value", DEDUPE_VALUES)
def test_every_enumerated_dedupe_value_is_accepted(value):
    plan = load("good-minimal.json")
    plan["rules"]["dedupe"] = value
    assert validate_plan(plan) is None


@pytest.mark.parametrize("value", ORDER_VALUES)
def test_every_enumerated_order_value_is_accepted(value):
    plan = load("good-minimal.json")
    plan["rules"]["order"] = value
    assert validate_plan(plan) is None


@pytest.mark.parametrize("value", STEP_TYPES)
def test_every_enumerated_step_type_is_accepted(value):
    plan = load("good-minimal.json")
    plan["steps"][0]["type"] = value
    assert validate_plan(plan) is None


def test_the_enumerations_are_exactly_what_the_contract_lists():
    """Guards the vocabulary itself, which the tests above take on trust."""
    assert DEDUPE_VALUES == ("none", "by_track_id", "by_title_and_primary_artist")
    assert ORDER_VALUES == ("as_planned", "shuffle")
    assert STEP_TYPES == ("track", "album")
    assert STEP_FIELDS == ("search", "type", "take", "why")
    assert RULES_FIELDS == (
        "exclude_artists",
        "exclude_title_terms",
        "dedupe",
        "order",
    )
    assert PLAN_REQUIRED == ("plan_format", "brief", "target", "steps", "rules")
    assert (PLAN_FORMAT, TAKE_MIN, TAKE_MAX) == (1, 1, 50)


# --------------------------------------------------------------------------- #
# Core 3 / Core 5 -- a step never names Spotify content by identity
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "search",
    [
        "spotify:track:4iV5W9uYEdYUVa79Axb7Rh",
        "spotify:album:4aawyAB9vmqN3uQ7FjRGTy",
        "https://open.spotify.com/track/4iV5W9uYEdYUVa79Axb7Rh",
        "open.spotify.com/artist/0TnOYISbd1XYRBk9myaseg",
        "4iV5W9uYEdYUVa79Axb7Rh",
        "like 4iV5W9uYEdYUVa79Axb7Rh but faster",
    ],
)
def test_a_step_naming_spotify_content_by_identity_is_refused(search):
    plan = load("good-minimal.json")
    plan["steps"][0]["search"] = search
    with pytest.raises(InvalidPlan) as raised:
        validate_plan(plan)
    assert raised.value.path == "$.steps[0].search"
    assert names_spotify_content(search)


@pytest.mark.parametrize(
    "search",
    [
        "genre:rock year:1990-1999",
        "artist:Radiohead album:OK Computer",
        "upbeat guitar songs",
        "year:2020",
        "artist:!!! ",
        "shoegaze",
    ],
)
def test_an_ordinary_search_expression_is_not_mistaken_for_an_identity(search):
    """The other half, and the one that would make the rule useless if wrong.

    A detector that flagged ordinary text would refuse every real plan, which is
    a failure no test of the *bad* cases can see.
    """
    assert not names_spotify_content(search)
    plan = load("good-minimal.json")
    plan["steps"][0]["search"] = search
    assert validate_plan(plan) is None


def test_a_caller_supplied_playlist_id_is_the_one_spotify_id_a_plan_may_carry():
    """Core 5's single exception, stated as a passing case rather than assumed."""
    plan = load("good-existing-playlist.json")
    assert plan["target"]["playlist_id"] == "37i9dQZF1DXcBWIGoYBM5M"
    assert validate_plan(plan) is None


# --------------------------------------------------------------------------- #
# The conformance kit's assert: `plan`'s own output validates
# --------------------------------------------------------------------------- #
def test_the_plan_verb_produces_a_document_this_validator_accepts():
    """`plan.v1`'s conformance kit: "``plan``'s own output validates".

    The producer and the consumer of a plan are different lanes; this is the
    join. It runs the real ``plan`` verb against a scripted model and hands the
    document straight to the real validator.
    """
    from music_deck.testing import Recording
    from music_deck.verbs.plan import plan as run_plan

    result = run_plan("upbeat 90s guitar songs", intelligence=Recording())
    assert validate_plan(result["plan"]) is None


def test_the_plan_verb_refuses_a_draft_this_validator_rejects():
    """The join in the other direction: a bad draft must not reach the caller.

    ``verbs.plan.validate_plan_document`` prefers this module once it exists, so
    a model that returns ``take: 99`` has to be refused with ``invalid_plan``
    naming the path -- not repaired, and not passed through.
    """
    from music_deck.errors import MusicDeckError
    from music_deck.testing import Recording
    from music_deck.verbs.plan import plan as run_plan

    reply = json.dumps(
        {
            "target": {"kind": "new", "name": "Too much"},
            "steps": [
                {"search": "genre:rock", "type": "track", "take": 99, "why": "greedy"}
            ],
            "rules": {
                "exclude_artists": [],
                "exclude_title_terms": [],
                "dedupe": "none",
                "order": "as_planned",
            },
        }
    )

    with pytest.raises(MusicDeckError) as raised:
        run_plan("a brief", intelligence=Recording(reply))

    assert raised.value.code == ErrorCode.INVALID_PLAN
    assert raised.value.envelope()["error"]["path"] == "$.steps[0].take"
