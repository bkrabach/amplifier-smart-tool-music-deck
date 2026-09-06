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
   closed never hangs. `-h` summarises for a person; `--help` gives an agent
   every verb, its arguments, types, return shape, and which are model-backed.
2. **Deterministic verbs need no model provider.** Every verb except `plan` —
   including any added later — runs with no provider configured and no provider
   SDK installed. `check` additionally succeeds (exit 0) with no credentials, no
   network, in a fresh directory: the smoke test, where reporting problems IS
   success.
3. **`plan` is the only model-backed verb, and refuses before any prompt is
   built.** Without a usable model substrate it exits 3, naming the missing
   precondition — SDK, provider, or credentials — and the fix. Never a silent
   deterministic fallback.
4. **Structure what a caller parses; write what a caller reads.** A result a
   caller acts on is one JSON document, each Spotify item carrying its
   `external_urls.spotify` link; failure emits `{"error": {"code", "message",
   "remedy"}}` with a non-zero exit; diagnostics go to stderr. Guidance is
   written for its reader, with `--json` for the same content structured:
   addressability nobody uses is not free. A remedy — and the manifest's
   `install` — names what the reader HAS, never a source-tree path.
5. **Exit codes are `0` success · `1` failure · `2` refusal, usage, or
   invalid input · `3` no provider configured** (model-backed verb only). All
   domain richness lives in `error.code`, not in more exit codes.
6. **The refusal vocabulary is frozen.** Each code below names its trigger and
   its remedy:
   - `not_authenticated` — no valid token; remedy `music-deck login`.
   - `reauthorization_required` — refresh rejected, or past the 6-month wall.
     Remedy `music-deck login`. · `not_allowlisted` — not on the allowlist. ·
     `premium_required` — a playback write without Premium. · `no_active_device`
     — none active; remedy: start playback, or `transfer`.
   - `cancelled` — the caller interrupted an interactive wait (Ctrl-C during
     `login`). A person stopping the tool is a refusal, never a traceback.
   - `rate_limited` — 429, no quota reason; honours `Retry-After` for one
     bounded retry, then refuses carrying `retry_after_s`. Never unbounded.
   - `quota_exceeded` — 429 reason `QUOTA_EXCEEDED`; waiting does not help. ·
     `partial_result` — partial completion, carrying `completeness`.
   - `port_unavailable` — `login`'s registered port is taken; it names the port
     rather than bind another Spotify would reject. Remedy: free it, or
     `music-deck setup --port <n>` and re-register.
   - `playlist_items_unavailable` — a playlist the caller neither owns nor
     collaborates on. · `invalid_plan` — rejected under `plan.v1`; exit 2.
7. **The library is the tool.** Every CLI capability is reachable from the
   `music_deck` Python library; the manifest is exposed as structured data
   via `music_deck.manifest()` and via `music-deck manifest`.
8. **`setup` gets a new caller from nothing to ready, without prompting.** It
   reports what is configured, what is missing, and the steps for that gap —
   proportional to the gap, not the whole orientation every run, which is on
   request. It writes the client ID when given one. The browser step stays in
   `login`, still the only interactive verb.

## What v1 deliberately does NOT freeze

- `diagnose`, reasoning over the tool's own operational evidence — when field
  failures arise that `check` cannot explain. · `revise`, second-turn plan
  refinement. · An MCP surface — when a host speaks only MCP.
- Progress or streaming for long-running smart calls. · A field-level
  success-payload schema — promoted when a consumer breaks on a field change.

## Conformance kit asserts

- Upstream Smart Tools kit green at the pinned rev — merge gate. Every
  deterministic verb passes with the model library absent and provider keys
  scrubbed; every code in Core 6 is reachable via a fixture.
- Malformed invocations, and an interrupted interactive wait, produce the error
  envelope and a non-zero exit — never a traceback; an unconfigured substrate
  refuses before any prompt (exit 3).
- Every parsed result is one JSON document; guidance prose has a `--json` twin.
- `setup`, stdin closed and nothing configured: exits 0, names what is missing,
  stays silent about what is not.
- Every path and command a remedy or `install` names resolves in an INSTALLED
  copy.

## Reserved / open questions (NOT frozen)

- Write fencing — a `--confirmed` flag on mutating verbs (playlist edits,
  playback writes, library save/remove). Undecided; not negotiated.
- Exact success-payload shapes per verb. · Multi-account, or multiple tokens.

## Changelog

- **2026-09-06 — ratified ("do it all" · "take it all the way live").** Core 4
  turns on what the output is FOR; Core 1 handed it the stdout rule; Core 8
  became proportional; Core 6 gained `port_unavailable`, then `cancelled` when a
  Ctrl-C during `login` surfaced as a traceback.
- **2026-09-05 — ratified ("lgtm, ratified").** Added Core 8 (`setup`); extended
  Core 4 to executable remedies; dropped Core 2's stale verb list.
