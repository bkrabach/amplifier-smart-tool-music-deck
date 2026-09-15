target: contracts/plan.v1.md

# Candidate — Plan Format Contract v2

**Date (UTC):** 2026-09-15

## Exact change, sentence by sentence

### Change 1 — Core 3: track-only step schema

Current text:

```
3. **A step names music by search expression only, never by Spotify ID or
   URI.** Its shape is `{"search", "type": "track" | "album", "take": 1..50,
   "why"}`, where `search` may use field filters such as `artist:`, `album:`,
   `year:`.
```

Replacement:

```
3. **A step names tracks by search expression only, never by Spotify ID or
   URI.** Its shape is `{"search", "type": "track", "take": 1..50, "why"}`,
   where `search` may use field filters such as `artist:`, `album:`, `year:`.
   An album title may narrow a track query with `album:`; `type: "album"` is
   reserved for future whole-album semantics and must not be emitted or
   accepted.
```

### Change 2 — Core 7: execution remains track search

Current text:

```
7. **`apply` executes the plan as written, in step order.** Each step
   searches with its `type`, paginating at Spotify's 10-per-page cap until
   `take` results or exhaustion; `rules` apply after fetching; the target is
   created or extended in batches of at most 100. The result names the
   playlist and a per-step `completeness` (`requested`/`fetched`/`kept`); an
   under-fulfilled step is a documented `partial_result`, never a silent
   success.
```

Replacement:

```
7. **`apply` executes the plan as written, in step order.** Each track step
   searches with `type: "track"`, paginating at Spotify's 10-per-page cap
   until `take` results or exhaustion; `rules` apply after fetching; the target
   is created or extended in batches of at most 100. The result names the
   playlist and a per-step `completeness` (`requested`/`fetched`/`kept`); an
   under-fulfilled step is a documented `partial_result`, never a silent
   success.
```

### Change 3 — Conformance kit: producer admission guard

Current text:

```
- `plan`'s own output validates against this contract.
```

Replacement:

```
- `plan`'s own output validates against this contract. The producer admission
  guard refuses a model-generated step whose `type` is `album`, naming its
  path; it never silently coerces that step to `track`.
```

### Change 4 — deliberately unfrozen whole-album work

Current text:

```
- A whole-album step type — promoted when a real plan wants one.
```

Replacement:

```
- Whole-album semantics — a future contract change must define their explicit
  meaning, including how albums become tracks. Until then, no producer or
  validator guesses an expansion; use a track query, optionally narrowed with
  `album:`, instead.
```

## Evidence — producer/consumer mismatch caught

The public tree identified for this review is `main` at `1cb2497` (the same
public tree as `b2dd611`). Its shipped producer instructions permit
`"type": "track" | "album"` in steps at
`src/music_deck/prompts/plan.md:36-46`. The producer copies model `steps` into
the completed document without a type-specific admission guard at
`src/music_deck/verbs/plan.py:191-200`.

The validator permits both `"track"` and `"album"` at
`src/music_deck/plan_schema.py:81-84` and accepts either listed type at
`src/music_deck/plan_schema.py:337-362`. The album fixture names
`"type": "album"` at `tests/fixtures/plans/good-album-step.json:8-15`, and
the good-fixture parameterization accepts every good fixture at
`tests/test_plan_schema.py:147-150`.

The consumer does not share that admission: `apply` validates before any work,
then separately refuses album steps at
`src/music_deck/verbs/apply.py:133-141` and `src/music_deck/verbs/apply.py:219-230`.
The reproduction test constructs a plan containing an album step and asserts
`invalid_plan` at its type path with zero transport requests at
`tests/test_apply.py:342-355`. This is a caught producer/consumer mismatch;
it does not assert real-account damage.

### Tightened-admission migration note

Legacy documents with `type: "album"` already have no executable route:
`apply` refuses them before requests. This proposal tightens producer and
validator admission to match that safe consumer boundary. Re-author such a
step as `type: "track"` with an `album:` filter where appropriate. No component
may guess or perform album-to-track expansion.

## What does NOT change

- `plan_format: 1` remains the only format named by this candidate; “v2” is the
  proposal filename/version, not an automatic wire-format bump or a new frozen
  contract.
- Track-plan behavior remains: search-only naming, no Spotify ID or URI in a
  step, `take` from 1 through 50, ten-per-page pagination, and the existing
  requested/fetched/kept completeness counts.
- Existing rules, budget/size behavior, completeness and `partial_result`
  behavior, target creation/extension, and batches of at most 100 are
  untouched.
- Playback and privacy boundaries, and the absence of general-tool authority,
  are untouched.
- This candidate does not ratify whole-album semantics or implement runtime
  changes; it only proposes the contract direction and its conformance check.

## Steward response

**UNANSWERED**

Choose one: **ratified** · **ratified with edits** · **declined** · **later**
