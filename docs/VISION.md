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
subject to Spotify's own quota. The center of the design is the **one-way
boundary**: caller words go in, a plan comes out, and nothing Spotify ever
returns — no track, no playlist, no listening history — crosses back into a
model prompt. A model composes the plan; it never sees what Spotify says.

Every capability lives in the `music_deck` library first. The command line is
a thin adapter over that library, never a second implementation: anything an
agent can do from a shell, a Python program can do by importing the library
directly. This repository conforms to the Smart Tools specification at
`microsoft/amplifier-smart-tools` @ `fd3c634`, and its own promises are
written down in `contracts/`.

---

## Principles

1. **The library is the tool.** No capability exists only in the CLI.
2. **The boundary is one-way.** Caller words in, plan out; nothing that came
   back from Spotify ever reaches a model, on any turn.
3. **Deterministic paths need nothing.** No provider, no credentials, and for
   the smoke-test verb, no network at all.
4. **Failures name the remedy.** An agent acts on the error directly; a human
   never reads documentation to decode what to do about it.
5. **Structured output or it did not happen.** One JSON document per result,
   never a sentence of prose standing in for a fact a caller needs to parse.
6. **The caller owns the credentials.** music-deck ships no client secret and
   stores only the caller's own access token, locked to the caller alone.
7. **Honest about the ceiling.** A handful of users, a Premium account, a
   shared quota — the tool lives inside Development Mode and never pretends
   it is something larger.

---

## What this is not

- **Spotify content in a model prompt** — a model sees only the caller's own
  brief and the tool's own static instructions, never anything Spotify returned.
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

- **2026-09-04** — First draft, from negotiated decisions. Ratified by the intent steward (word: "ratified").
