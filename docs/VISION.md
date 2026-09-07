# music-deck — Vision (DRAFT)

*Written for amplified information workers. Terms of art are defined where they
first appear; the specific promises live in `contracts/`.*

---

## Where this is going

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

It is a personal tool. It runs inside **Development Mode**, the tier Spotify
grants a developer's own app before wider review — capped at a handful of
allowed users, gated behind the owner's own Spotify Premium account, and
subject to Spotify's own quota. Its model **reads what Spotify returns** — the
searches it ran, the playlists it built — so it can correct its own aim rather
than guess blind. Spotify's Developer Policy §III forbids that, and music-deck
does it knowingly: `contracts/boundary.v1.md` states the breach in its Purpose
rather than hiding it, and anyone who installs this inherits it. What stays
true is that no credential ever enters a prompt, nothing accumulates on disk,
and every prompt sent is readable afterward in the result's `transcript`.

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
6. **The caller owns the credentials.** music-deck ships no client secret and
   stores only the caller's own access token, locked to the caller alone.
7. **Honest about the ceiling.** A handful of users, a Premium account, a
   shared quota — the tool lives inside Development Mode and never pretends
   it is something larger.

---

## What this is not

- **A credential in a model prompt** — the token and client ID never cross,
  even though Spotify content now does.
- **A bundled client ID** — credentials come from the caller's own registered
  app; the tool ships none and stores none beyond the caller's token.
- **A local database of Spotify content** — caching is temporary and strictly
  necessary, never a store that accumulates or gets analyzed later.
- **Listening analytics or user profiling** — no "year in review," no derived
  taste metrics, no profile built from listening history.
- **Voice control** — not permitted for this kind of integration, and not a
  direction this grows toward.
- **Producing audio** — a remote control for a device already playing, never
  an embedded player of its own.
- **Riding a grandfathered identity, or calling a retired endpoint** — the
  tool stays inside today's real surface.
- **Prose answers from the planning verb** — a plan is structured data, not a
  paragraph describing one.
- **A capability that exists only in the command line** — see Principle 1.
- **Being a product** — a handful of users is the ceiling by design.

---

## How you can tell it is working

- A person reads a plan before anything runs and understands exactly what it
  does to their Spotify account.
- Every run that fails tells the caller what to do next, in words.
- Nothing music-deck ever fetched from Spotify shows up inside a model's
  context — checkable by reading the transcript a plan carries with it.
- Everything works with no credentials configured, except the one verb that
  talks to a model.
- The owner never worries about a copy of their playlists or listening
  history piling up somewhere they didn't expect.

---

## Changelog

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
