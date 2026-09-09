# music-deck — Vision (DRAFT)

*Written for amplified information workers. Terms of art are defined where they
first appear; the specific promises live in `contracts/`.*

---

## Where this is going

music-deck is the instrument an agent reaches for when its owner wants music handled on Spotify without opening the app. The owner may use the optional, reviewable **plan** and deterministic `apply` path: a plan is a readable, editable document naming the searches to run, the rules to apply, and where the results land. Or the owner may give a **brief** to bounded, model-backed `do`, which uses the library's supported music operations natively, sees their projected results, and can act while it corrects its aim. `do` has enforced turn and Spotify-request ceilings; its actions and projected tool results are returned for review.

A fresh `do` has no saved conversation. Only an explicit, named new or resumed conversation remembers the history the owner chose; music-deck never selects the most recent conversation automatically. `do` may use all currently supported library music operations: catalog and playlist reads and changes, saved-library and follow operations, listening-history and now-playing reads, devices and queue, and Spotify API playback controls. It does not gain auth, configuration, administration, runtime built-ins, shell, files, browsing or network tools, delegation, or recursive `plan` or `do`. Local discovery stays an explicit opt-in observation, not a hidden receiver or a claim of playback support. The plan/apply path remains available alongside `do`.

It is a personal tool. It runs inside **Development Mode**, the tier Spotify
grants a developer's own app before wider review — capped at a handful of
allowed users, gated behind the owner's own Spotify Premium account, and
subject to Spotify's own quota. Its model **reads projected current results** from supported music operations so it can correct its own aim rather than guess blind. Spotify's Developer Policy §III forbids ingesting Spotify Content into a model, and music-deck does that knowingly: `contracts/boundary.v1.md` states the breach in its Purpose rather than hiding it, and anyone who installs this inherits that Developer Policy risk. No credential enters a prompt, stored conversation, or replayed history. A result exposes the exact prompts, including replay, and the projected tool results that crossed to the model rather than presenting an empty transcript.

A named conversation may retain its prompts, replies, and projected tool results on the caller's host until the caller explicitly deletes it or disconnects. Those records may contain Spotify library, playlist, account profile, or device information and, only after explicit opt-in, local-network observations. They are continuation history only: not an implicit Spotify collection database, listening analytics, taste profile, or cross-session learning.

Every capability lives in the `music_deck` library first. The command line is
a thin adapter over that library, never a second implementation: anything an
agent can do from a shell, a Python program can do by importing the library
directly. This repository conforms to the Smart Tools specification at
`microsoft/amplifier-smart-tools` @ `fd3c634`, and its own promises are
written down in `contracts/`.

---

## Principles

1. **The library is the tool.** No capability exists only in the CLI.
2. **What crosses is visible.** A model may read what Spotify returns; it may
   never read a credential, and every prompt sent is in the `transcript`.
3. **Deterministic paths need nothing.** No provider, no credentials, and for
   the smoke-test verb, no network at all.
4. **Failures name the remedy.** An agent acts on the error directly; a human
   never reads documentation to decode what to do about it.
5. **Structured output for anything a caller parses.** A fact a caller acts on
   is a JSON document, never a sentence of prose standing in for it. Guidance
   a reader simply reads is written for that reader — structure it addresses
   nothing and costs everyone.
6. **The caller owns the credentials and chosen history.** music-deck ships no client secret; its credential token and configuration remain restricted to the caller. Separately, it may store only the explicitly named conversation record the caller chose to keep, on that caller's host until explicit deletion or disconnect.
7. **Honest about the ceiling.** A handful of users, a Premium account, a
   shared quota — the tool lives inside Development Mode and never pretends
   it is something larger.

---

## What this is not

- **A credential in a model prompt** — the token and client ID never cross,
  even though Spotify content now does.
- **A bundled client ID** — credentials come from the caller's own registered
  app; the tool ships none and stores none beyond the caller's token.
- **An implicit local database of Spotify content** — caching is temporary and strictly necessary. The sole exception is an explicitly named conversation's retained prompts, replies, and projected tool results, kept only for that opted-in continuation and never accumulated or analyzed as a collection.
- **Listening analytics or user profiling** — no "year in review," no derived
  taste metrics, no profile built from listening history.
- **Voice control** — not permitted for this kind of integration, and not a
  direction this grows toward.
- **Producing audio** — a remote control for an eligible Spotify API device, never an embedded player. Discovering a local receiver does not establish account access or control; the tool reports accepted requests separately from verified playback.
- **Riding a grandfathered identity, or calling a retired endpoint** — the
  tool stays inside today's real surface.
- **Prose answers from the planning verb** — a plan is structured data, not a
  paragraph describing one.
- **A capability that exists only in the command line** — see Principle 1.
- **Being a product** — a handful of users is the ceiling by design.

---

## How you can tell it is working

- A person can use an optional plan before deterministic `apply`, or inspect the bounded `do` result to see what it did to their Spotify account.
- Every run that fails tells the caller what to do next, in words.
- A `do` result shows the exact prompts (including a chosen-history replay) and projected tool results that reached the model; no credential appears in any of them, while the known Developer Policy §III risk remains labelled.
- Deterministic-only operations need no provider or provider SDK; `check` also succeeds with no credentials and no network. Spotify operations still require the caller's configured credential and token.
- A fresh `do` leaves no continuation history. A retained record exists only when the owner explicitly names it, is visible as that record rather than a fabricated empty transcript, and remains on the caller's host until explicit deletion or disconnect.

---

## Changelog

- **2026-09-09 — bounded `do` and named continuation adopted.** The steward
  ratified the v2 amendment with `contracts/do.v1.md` and the boundary v2
  candidate. It records the accepted direction and retention boundary, not an
  implementation or conformance pass.
- **2026-09-06 — the one-way boundary removed, knowingly.** Principle 2 was
  "nothing that came back from Spotify ever reaches a model." A model that
  cannot see its own results cannot correct them: asked for 90s grunge, it
  wrote `genre:grunge year:1990-1999`, got nothing, and had no way to learn
  that — `genre:grunge` returns 5 tracks and `year:` works with other genres,
  but that conjunction returns 0. The steward accepted the Developer Policy
  §III breach with it labelled in the contract and the README, over a
  counts-only loop that would have kept the tool distributable. Ratified
  ("2").
- **2026-09-04** — First draft, from negotiated decisions. Ratified by the intent steward (word: "ratified").
- **2026-09-06** — Principle 5 restored to its own reasoning. It said
  "Structured output or it did not happen"; read literally that made every byte
  of stdout JSON, including a ten-minute setup guide nobody parses. Measured on
  `music-deck setup`: 8,096 characters, of which 36% was scaffolding around
  prose — ~2,188 tokens where the same words read ~1,398. Structure earns its
  place when a caller addresses a field; it is pure cost when the caller reads
  the whole thing. Ratified by the intent steward (word: "ok, perfect, do it
  all").
