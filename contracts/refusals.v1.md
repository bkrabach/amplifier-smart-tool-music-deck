# Refusal Vocabulary Contract — v1 (DRAFT)

**Who builds against this:** any agent, script, or person branching on
`error.code` from `music-deck`; the `music_deck` library's `errors` module,
which is the single place a code is defined.

## Purpose

A caller decides what to do next by reading `error.code`, so the set of codes
is a surface someone outside this repo depends on. It was `cli.v1` Core 6
until 2026-09-06, and it kept forcing that contract over its one-screen bar —
a list that grows on its own schedule does not belong inside one that does
not. Splitting it out is what let the drift below be named rather than golfed.

## Core (the teeth)

1. **The vocabulary is closed.** Every code the tool can emit is named here.
   A code in shipped output that this contract does not name is drift, and is
   fixed by amending this contract or by not emitting it — never by leaving
   the two out of step.
2. **Authorization.** `not_authenticated` — no valid token; remedy
   `music-deck login`. · `reauthorization_required` — refresh rejected, or
   past the six-month wall; same remedy. · `not_allowlisted` — the account is
   not on the app's Development Mode allowlist; a 403 is the only signal
   Spotify gives.
3. **Account and device.** `premium_required` — a playback write without
   Premium; Spotify removed the field that would let this be checked in
   advance. · `no_active_device` — nothing is playing; remedy: start playback,
   or `transfer`.
4. **Quota.** `rate_limited` — 429 with no quota reason; honours `Retry-After`
   for one bounded retry, then refuses carrying `retry_after_s`. Never
   unbounded. · `quota_exceeded` — 429 reason `QUOTA_EXCEEDED`; waiting does
   not help, so it does not retry.
5. **Partial work is reported, never hidden.** `partial_result` — a documented
   partial completion carrying `completeness`: requested, fetched, kept, added,
   and which steps under-fulfilled. Never a silent truncation.
6. **The caller's own input.** `usage` — a malformed invocation. ·
   `invalid_input` — a value the tool can read but cannot use. · `invalid_plan`
   — a plan rejected under `plan.v1`, naming the offending path. All exit 2.
7. **The tool's own preconditions.** `no_provider_configured` — a model-backed
   verb without a usable substrate, naming which of SDK, provider, or
   credentials is missing; exit 3. · `port_unavailable` — `login`'s registered
   port is taken; it names the port rather than bind another Spotify would
   reject. · `no_browser` — no browser opened and no way to hand the URL over.
   · `cancelled` — the caller interrupted an interactive wait. A person
   stopping the tool is a refusal, never a traceback.
8. **What is not ours.** `spotify_error` — Spotify answered with a status this
   contract does not otherwise name; it carries `status` and `endpoint` so the
   caller sees whose failure it is. · `playlist_items_unavailable` — a playlist
   the caller neither owns nor collaborates on. · `internal_error` — a defect
   in music-deck; it says so plainly rather than blaming the caller. ·
   `not_implemented` — a surface named but not built.

## What v1 deliberately does NOT freeze

- The `message` and `remedy` text of any code — only the code itself is the
  contract. · Whether a given Spotify status maps to `spotify_error` or earns
  its own code — promoted when a caller needs to branch on one.
- Sub-codes or a hierarchy. One flat set until a real consumer needs more.

## Conformance kit asserts

- Every code this contract names is reachable via a fixture.
- Every code string the source can emit is named here: a static sweep of
  `errors.py` and of bare-string codes elsewhere, failing on any it cannot
  find in this file. The drift below is what this assert exists to catch.
- Exit codes follow `cli.v1` Core 5: a refusal is 2, a failure 1, a missing
  provider 3.

## Reserved / open questions (NOT frozen)

- Whether `internal_error` should carry a report-this link.
- Whether `spotify_error` should distinguish 5xx (retryable) from 4xx.

## Changelog

- **2026-09-06 — split out of `cli.v1` Core 6, and completed.** The move is
  verbatim; no promise changed by relocating. Completing it did: `usage`,
  `invalid_input`, `no_provider_configured`, `no_browser`, `spotify_error`,
  `internal_error` and `not_implemented` are all emitted by shipped code and
  were named by no contract. Found while trying to delete an empty playlist —
  `library remove` returned `spotify_error`, a code Core 6 never listed.
