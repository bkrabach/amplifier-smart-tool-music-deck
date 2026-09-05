# CLI Contract — v1 (DRAFT)

**Who builds against this:** this repo's thin CLI (`music-deck`, the only
implementation); any agent invoking `music-deck` from a shell; scripts and
hosts wrapping it.

## Purpose

The stable invocation surface — what a caller of the binary may rely on, so
wrappers survive library evolution. It says nothing about how music-deck
talks to Spotify; that promise lives in `contracts/boundary.v1.md`, and how a
plan document is shaped lives in `contracts/plan.v1.md`.

## Core (the teeth)

1. **One binary, `music-deck`, on PATH. Non-interactive.** A run with stdin
   closed never hangs. `-h` gives a terse human summary; `--help` gives an agent
   the complete listing — every verb, its arguments, types, return shape, and
   which are model-backed. Help goes to stdout, exits 0, and is the only
   non-JSON stdout the binary ever produces.
2. **Deterministic verbs need no model provider.** Every verb except `plan`
   runs with no provider configured and no provider SDK installed. `check`
   additionally succeeds (exit 0) with no credentials and no network, in a
   fresh working directory — it is the smoke test; reporting problems IS its
   success. A verb added later is covered the day it lands.
3. **`plan` is the only model-backed verb, and refuses before any prompt is
   built.** Without a usable model substrate it exits 3, naming which
   precondition is missing — SDK not installed, no provider configured, or no
   credentials — and how to fix it. Never a silent deterministic fallback.
4. **One JSON document per result.** Failure emits
   `{"error": {"code", "message", "remedy"}}` on stdout and exits non-zero;
   progress and diagnostics go to stderr, never to stdout. Every Spotify item
   the tool emits carries its own `external_urls.spotify` link. A remedy — and
   the manifest's `install` — names what the reader HAS: a command their install
   method takes, or text the installed package carries. Never a source-tree path.
5. **Exit codes are `0` success · `1` failure · `2` refusal, usage, or
   invalid input · `3` no provider configured** (model-backed verb only). All
   domain richness lives in `error.code`, not in more exit codes.
6. **The refusal vocabulary is frozen.** Each code below names its trigger and
   its remedy:
   - `not_authenticated` — no valid token; remedy `music-deck login`.
   - `reauthorization_required` — refresh rejected, or past the 6-month refresh
     wall; remedy `music-deck login`.
   - `not_allowlisted` — not on the app's Development Mode allowlist.
   - `premium_required` — a playback write was attempted without Premium.
   - `no_active_device` — none active; remedy: start playback, or `transfer`.
   - `rate_limited` — 429, no quota reason; honours `Retry-After` for at most
     one bounded retry, then refuses carrying `retry_after_s`. Never unbounded.
   - `quota_exceeded` — 429 reason `QUOTA_EXCEEDED`; not retryable by waiting.
   - `partial_result` — documented partial completion, carrying a `completeness`
     block naming what succeeded and failed. Never a silent truncation.
   - `playlist_items_unavailable` — items of a playlist the caller neither owns
     nor collaborates on.
   - `invalid_plan` **[orchestrator-derived]** — a plan `apply` rejected under
     `plan.v1`, naming the offending path; exit 2.
7. **The library is the tool.** Every CLI capability is reachable from the
   `music_deck` Python library; the manifest is exposed as structured data
   via `music_deck.manifest()` and via `music-deck manifest`.
8. **`setup` gets a new caller from nothing to ready, without prompting.** It
   reports what is configured and what is missing, carries the steps to
   register a Spotify app in plain words, and writes the client ID when given
   one. The browser step stays in `login`, still the only interactive verb.

## What v1 deliberately does NOT freeze

- `diagnose`, reasoning over the tool's own operational evidence — promoted
  when field failures arise that deterministic `check` cannot explain.
- `revise`, second-turn plan refinement — promoted when a real caller needs
  iteration a fresh `plan` cannot serve.
- An MCP server surface — promoted when a consumer host speaks only MCP.
- Progress or streaming for long-running smart calls.
- A field-level success-payload schema per deterministic verb — promoted when
  a real consumer breaks on a field change.

## Conformance kit asserts

- Upstream Smart Tools kit green at the pinned rev — merge gate.
- Every deterministic verb passes with the model library absent and provider
  keys scrubbed; every code in Core 6 is reachable via a fixture.
- Malformed invocations produce the error envelope, non-zero exit, JSON-only
  stdout; an unconfigured substrate refuses before any prompt (exit 3).
- `setup`, stdin closed and nothing configured: exits 0, names what is missing.
- Every path and command a remedy or `install` names resolves in an INSTALLED
  copy — not only in the source tree.

## Reserved / open questions (NOT frozen)

- Write fencing — a `--confirmed` flag on mutating verbs (playlist edits,
  playback writes, library save/remove). Undecided; not negotiated.
- Exact success-payload shapes per deterministic verb.
- Multi-account, or multiple token caches.

## Changelog

- **2026-09-05 — ratified ("lgtm, ratified").** Added Core 8 (`setup`) and
  extended Core 4: a remedy must be executable by its reader. Measured on a real
  `uv tool install` of `b7f7334` — nothing wrote the client ID; `check`'s remedy
  and the manifest's `install` both named `docs/spotify-app.md`, absent from the
  package; the missing-SDK remedy said `uv pip install`, which a tool-installed
  copy cannot use. Core 2's enumerated verb list went too: already stale.
