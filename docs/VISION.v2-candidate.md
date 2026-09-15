target: docs/VISION.md
# Proposed Vision v2 amendment — bounded `do` and named continuation
## Exact change
### Change 1 — “Where this is going,” paragraphs 10–21
Current text:
```
music-deck is the instrument an agent reaches for when its owner wants music
handled on Spotify without opening the app. The owner describes what they
want in their own words — a **brief** — and music-deck turns that brief into a
**plan**: a readable, editable document naming the searches to run, the rules
to apply, and where the results land. Nothing runs against Spotify until the
plan exists, and the plan is legible to a person before it touches an account.

Once a plan reads right, `apply` carries it out against Spotify
deterministically — no model runs during execution, only during planning —
and reports what was found, what was kept, what was skipped, and why.
music-deck also drives whatever device is already playing: pause it, skip it,
move it to another speaker, without ever producing audio itself.
```
Replacement:
```
music-deck is the instrument an agent reaches for when its owner wants music handled on Spotify without opening the app. The owner may use the optional, reviewable **plan** and deterministic `apply` path: a plan is a readable, editable document naming the searches to run, the rules to apply, and where the results land. Or the owner may give a **brief** to bounded, model-backed `do`, which uses the library's supported music operations natively, sees their projected results, and can act while it corrects its aim. `do` has enforced turn and Spotify-request ceilings; its actions and projected tool results are returned for review.

A fresh `do` has no saved conversation. Only an explicit, named new or resumed conversation remembers the history the owner chose; music-deck never selects the most recent conversation automatically. `do` may use all currently supported library music operations: catalog and playlist reads and changes, saved-library and follow operations, listening-history and now-playing reads, devices and queue, and Spotify API playback controls. It does not gain auth, configuration, administration, runtime built-ins, shell, files, browsing or network tools, delegation, or recursive `plan` or `do`. Local discovery stays an explicit opt-in observation, not a hidden receiver or a claim of playback support. The plan/apply path remains available alongside `do`.
```
### Change 2 — “Where this is going,” paragraph 26–32
Current text:
```
subject to Spotify's own quota. Its model **reads what Spotify returns** — the
searches it ran, the playlists it built — so it can correct its own aim rather
than guess blind. Spotify's Developer Policy §III forbids that, and music-deck
does it knowingly: `contracts/boundary.v1.md` states the breach in its Purpose
rather than hiding it, and anyone who installs this inherits it. What stays
true is that no credential ever enters a prompt, nothing accumulates on disk,
and every prompt sent is readable afterward in the result's `transcript`.
```
Replacement:
```
subject to Spotify's own quota. Its model **reads projected current results** from supported music operations so it can correct its own aim rather than guess blind. Spotify's Developer Policy §III forbids ingesting Spotify Content into a model, and music-deck does that knowingly: `contracts/boundary.v1.md` states the breach in its Purpose rather than hiding it, and anyone who installs this inherits that Developer Policy risk. No credential enters a prompt, stored conversation, or replayed history. A result exposes the exact prompts, including replay, and the projected tool results that crossed to the model rather than presenting an empty transcript.

A named conversation may retain its prompts, replies, and projected tool results on the caller's host until the caller explicitly deletes it or disconnects. Those records may contain Spotify library, playlist, account profile, or device information and, only after explicit opt-in, local-network observations. They are continuation history only: not an implicit Spotify collection database, listening analytics, taste profile, or cross-session learning.
```
### Change 3 — Principle 6
Current text:
```
6. **The caller owns the credentials.** music-deck ships no client secret and
   stores only the caller's own access token, locked to the caller alone.
```
Replacement:
```
6. **The caller owns the credentials and chosen history.** music-deck ships no client secret; its credential token and configuration remain restricted to the caller. Separately, it may store only the explicitly named conversation record the caller chose to keep, on that caller's host until explicit deletion or disconnect.
```
### Change 4 — “What this is not,” local Spotify database claim
Current text:
```
- **A local database of Spotify content** — caching is temporary and strictly
  necessary, never a store that accumulates or gets analyzed later.
```
Replacement:
```
- **An implicit local database of Spotify content** — caching is temporary and strictly necessary. The sole exception is an explicitly named conversation's retained prompts, replies, and projected tool results, kept only for that opted-in continuation and never accumulated or analyzed as a collection.
```
### Change 5 — “What this is not,” producing audio
Current text:
```
- **Producing audio** — a remote control for a device already playing, never
  an embedded player of its own.
```
Replacement:
```
- **Producing audio** — a remote control for an eligible Spotify API device, never an embedded player. Discovering a local receiver does not establish account access or control; the tool reports accepted requests separately from verified playback.
```
### Change 6 — “How you can tell it is working,” paragraphs 89–97
Current text:
```
- A person reads a plan before anything runs and understands exactly what it
  does to their Spotify account.
- Every run that fails tells the caller what to do next, in words.
- Nothing music-deck ever fetched from Spotify shows up inside a model's
  context — checkable by reading the transcript a plan carries with it.
- Everything works with no credentials configured, except the one verb that
  talks to a model.
- The owner never worries about a copy of their playlists or listening
  history piling up somewhere they didn't expect.
```
Replacement:
```
- A person can use an optional plan before deterministic `apply`, or inspect the bounded `do` result to see what it did to their Spotify account.
- Every run that fails tells the caller what to do next, in words.
- A `do` result shows the exact prompts (including a chosen-history replay) and projected tool results that reached the model; no credential appears in any of them, while the known Developer Policy §III risk remains labelled.
- Deterministic-only operations need no provider or provider SDK; `check` also succeeds with no credentials and no network. Spotify operations still require the caller's configured credential and token.
- A fresh `do` leaves no continuation history. A retained record exists only when the owner explicitly names it, is visible as that record rather than a fabricated empty transcript, and remains on the caller's host until explicit deletion or disconnect.
```
## Evidence
`do` already contradicts the plan-only model: it declares native tools for the model and returns Spotify results to it, while its handlers use the same catalog and playlist library operations as `apply` (`src/music_deck/verbs/do.py:11-15,42-44`). Its present vocabulary is limited to declared operations (`src/music_deck/verbs/do.py:188-260`), whereas the thin CLI already adapts the wider deterministic catalog, playlist, library, history, device, queue, and playback surface (`src/music_deck/cli.py:262-412`).

The engine currently creates an ephemeral session in a temporary storage directory (`src/music_deck/intelligence.py:743-778`), confirming that fresh `do` has no durable continuation; it cannot support an owner-selected follow-up turn. In an observed pilot, requested playlist contents and an explicit-target append were verified, but a bare follow-up reported no history and a device request had no available function. Both read-only requests returned `partial_result` because the implementation required a written playlist, although neither request called for a playlist write. This paid cost supports explicit named continuation, the full existing music surface, and success criteria based on the requested task rather than a required playlist mutation.

The vision already records the steward's knowing acceptance of the Developer Policy §III breach (`docs/VISION.md:103-111`). This proposal keeps that warning and makes the additional model-visible content classes explicit; it does not claim unchanged data exposure or policy compliance. Privacy retention for chosen conversations has not been ratified.
## What does NOT change
- `docs/VISION.md` remains the governing draft unless and until the steward ratifies this candidate; no status is asserted here.
- The library-first, thin-CLI direction remains intact (`docs/VISION.md:34-39`).
- `plan` plus deterministic `apply` remain an optional, reviewable path; this proposal does not require a plan for `do` or claim that a model never runs during `do` execution.
- The existing credential, token, configuration, PKCE, API eligibility, and Developer Policy §III labelling remain governed by the current boundary. No credentials enter prompts, stored history, tool projections, or replay.
- Local discovery remains explicit opt-in observation only. No password, cookie, desktop-client credential flow, hidden LAN receiver, or automatic playback write is introduced. Existing private-playlist visibility behavior is not changed by this proposal.
## Related proposal bundle
The steward ratified this proposal with `contracts/boundary.v2-candidate.md` and `contracts/do.v1.md` on 2026-09-09. The exact changes remain the approved adoption input; this record does not claim implementation or conformance.
## Steward decision
**Ratified**, 2026-09-09. Steward's words: "ratified and make sure the docs/readme/-h/--help are all up-to-date for the appropriate audiences/content as well."
