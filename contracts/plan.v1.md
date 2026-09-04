# Plan Format Contract — v1 (DRAFT)

**Who builds against this:** `music-deck plan` (the producer), `music-deck
apply` (the consumer), and any agent or person who writes or hand-edits a
plan — the owner has said yes, they will.

## Purpose

A plan is the document that crosses the one-way boundary from a model back
into the world: it is what lets a caller read, edit, and trust what is about
to happen to their Spotify account before anything runs. This contract fixes
its shape so a plan written by one party is never misread by another.

## Core (the teeth)

1. **A plan is one JSON document with integer `plan_format: 1`.** `apply`
   refuses any other value with `invalid_plan`, naming the version found.
2. **Required top-level fields are `plan_format`, `brief`, `target`, `steps`,
   and `rules`; `size` is optional.** `brief` is the caller's text, verbatim.
   `steps` is an ordered list of at least one step.
   <details><summary>Details</summary>
   `target` is `{"kind": "new", "name", "description"?}` or
   `{"kind": "existing", "playlist_id"}`. `size` is
   `{"minutes" | "tracks", "tolerance_pct"}`.
   </details>
3. **A step names music by search expression only, never by Spotify ID or
   URI.** Its shape is `{"search", "type": "track" | "album", "take": 1..50,
   "why"}`, where `search` may use field filters such as `artist:`, `album:`,
   `year:`.
4. **`rules` always carries all four of its keys, even when empty.**
   `exclude_artists`, `exclude_title_terms`, `dedupe`
   (`none` | `by_track_id` | `by_title_and_primary_artist`), and `order`
   (`as_planned` | `shuffle`).
5. **A plan carries no Spotify content other than a caller-supplied
   `target.playlist_id`.** No fetched metadata, no IDs inside steps — this is
   what lets a plan cross the boundary in either direction.
6. **Strict validation.** An unknown field at any level, a wrong type, or an
   out-of-range value makes `apply` refuse with `invalid_plan`, naming the
   offending path. Nothing is silently ignored or coerced.
7. **`apply` executes the plan as written, in step order.** Each step
   searches with its `type`, paginating at Spotify's 10-per-page cap until
   `take` results or exhaustion; `rules` apply after fetching; the target is
   created or extended in batches of at most 100. The result names the
   playlist and a per-step `completeness` (`requested`/`fetched`/`kept`); an
   under-fulfilled step is a documented `partial_result`, never a silent
   success.
8. **Determinism, except order: shuffle.** The same plan against the same
   Spotify state produces the same result, unless `rules.order` is `shuffle`.

## What v1 deliberately does NOT freeze

- `revise`, producing a new plan from a brief, a prior plan, and caller words
  — promoted under the same trigger as `cli.v1`.
- `size` as a hard constraint rather than advisory — promoted when a real
  caller needs it enforced.
- A whole-album step type — promoted when a real plan wants one.
- `exclude_explicit` and `market` fields — promoted when a real plan needs
  them.

## Conformance kit asserts

- Schema fixtures: a good plan is accepted; bad plans (a missing field, a
  wrong type, an unknown field, `plan_format: 2`, a step carrying a Spotify
  ID or URI, `take: 0`) are refused with `invalid_plan` naming the path.
- `plan`'s own output validates against this contract.
- `apply` against a mocked Spotify honours step order, 10-per-page
  pagination, `rules`, batches of at most 100, and accurate `completeness`,
  including `partial_result` on under-fulfilment.

## Reserved / open questions (NOT frozen)

- Multi-target plans.
- Plan provenance or signing.
- A `plan_format` migration story.

## Example

A short brief turned into a plan `apply` can execute as written:

```json
{
  "plan_format": 1,
  "brief": "upbeat 90s guitar songs for a Saturday morning",
  "target": {"kind": "new", "name": "Saturday Morning Guitar"},
  "steps": [
    {"search": "genre:rock year:1990-1999", "type": "track", "take": 20,
     "why": "core 90s guitar-rock sound"}
  ],
  "rules": {"exclude_artists": [], "exclude_title_terms": ["remix"],
            "dedupe": "by_track_id", "order": "shuffle"}
}
```

A plan naming `"steps": [{"search": "spotify:track:abc123", ...}]` is bad: a
step may never carry a Spotify ID, only a search expression (clause 3).
