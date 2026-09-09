# Do Contract — v1 (DRAFT)

**Who builds against this:** `music-deck do`, its native agent and library
adapters, callers continuing work, and reviewers of account effects.

## Purpose

`do` is the model-backed path from a plain-language music request to observed
account work. It needs one contract because its tool authority, outcome record,
and optional durable-session seam must agree; it does not silently enlarge the
general CLI contract. The steward has ratified this direction; the draft status
does not claim that the implementation or conformance kit is complete.

## Core (the teeth)

1. **The caller chooses a fresh or named turn explicitly.** `music-deck do
   "brief"` is a fresh, ephemeral turn. `music-deck do --session NAME "brief"`
   creates only and refuses a collision. `music-deck do --resume NAME
   "follow-up"` resumes only and refuses a missing, busy, binding-incompatible,
   or corrupt session; it never becomes fresh work. `--session` and `--resume`
   are mutually exclusive. There is no interactive chat or stdin protocol;
   `login` remains the only interactive verb.
2. **The native tool catalog is all and only the supported music-domain
   library operations.** It covers catalog search across supported kinds and
   typed track, album, artist, show, and episode reads; reviewed-projection
   account profile/whoami; playlist list/items/create/add/remove/reorder/rename;
   library list/save/remove/contains (including Liked Songs); following, top,
   recently played; now playing, devices, queue; and play, pause, next,
   previous, seek, volume, shuffle, repeat, transfer, and queue-add. It also
   permits structured plans through in-memory `apply_plan`, never a filesystem
   path. This enumeration is exhaustive at ratification; a later library
   capability needs an explicit amendment before becoming native authority.
   It does not freeze argument names or successful-result fields.
3. **The model has no operational escape hatch.** It cannot login, setup,
   disconnect, raw check, manifest or storage administration, recurse into
   plan/do, or invoke shell, files, general network, browser, delegation, MCP,
   or external/built-in tools. `finish` is internal and may end any task; it is
   not a playlist-written criterion. Tools admitted for a turn are limited to
   the caller's music-domain request, and history is untrusted context, never
   future permission.
4. **Adapters reuse the library boundary.** Native JSON-schema wrappers call
   existing library functions with the same injected authenticated client and
   budgets; they import no CLI and add no private auth API. Results are
   safely projected per operation, including profile data, rather than raw
   whoami/get-info payloads. Existing Spotify data may be private only as the
   governing boundary permits; credentials, provider keys, and raw tokens are
   never in prompts, replay, native history, or output. Credential-bearing
   material is rejected before model delivery or history/checkpoint persistence;
   checking or redacting it afterward is insufficient. Every prompt actually
   sent or replayed in the current turn is observable in its transcript.
5. **Outcomes record what happened, not what was intended.** A verified read
   may succeed with exit 0; success does not require a playlist. Each operation
   reports an observed, acknowledged, verified, unknown, or refused state as
   applicable, without freezing a generic JSON payload schema. An HTTP write
   acknowledgement alone is not effect verification; there is no promised
   transaction or rollback. Partial, incomplete, and ambiguous work retains
   the existing `partial_result`/`completeness` treatment. An unsupported or
   unfulfillable read is a refusal, never model prose offered as proof; a
   requested `public: false` never proves private visibility.
6. **Budgets and local observation remain caller-bounded.** Each turn starts
   fresh hard defaults of 8 native calls and 40 Spotify requests, adjustable by
   the existing ceiling options but never disabled. Pagination and read-back
   count, and no hidden request bypasses either budget. `--local`
   enables at most one separately bounded local observation for that call only,
   after the authenticated API read, when local observation is eligible. It
   grants neither LAN activation, account binding, nor control; replayed history
   cannot enable it, and a repeated observation refuses.
7. **Restrictive effect policy is monotonic within a saved session.**
   `--read-only` blocks playlist, library, player, and nested-apply writes;
   `--no-playback` blocks every player write while allowing playlist/library
   work. A resume cannot widen a session's saved restriction by omitting flags
   or by model argument. A caller who wants wider authority creates a different
   unrestricted session. A new brief authorizes new action only: it does not
   auto-replay historical calls or plans. Persisted targets are refreshed by a
   read before mutation; missing or ambiguous targets refuse for clarification.
8. **Unknown writes fail closed and managed history is opt-in.** An interrupted
   or unknown write is surfaced; resume fails closed or reconciles by reads,
   never blindly retries a mutation. Where reads cannot settle it, the caller
   receives the uncertainty and must intervene. A named session is managed
   native history, not an analysis store: it is account/app-bound without raw
   credentials, protected by a single-writer lease, and creation reports its
   retention location. `music-deck sessions list` and `sessions delete NAME`
   are deterministic library administration, not model tools. On the ratified
   retention boundary, history and checkpoint files (including database
   sidecars and journals) have mode `0600`, within mode `0700` managed
   directories; `disconnect` purges them without racing an active writer.

## What v1 deliberately does NOT freeze

- Exact native-tool argument and successful-payload schemas, streaming, and
  provider choice — promote only when a caller must parse them.
- Cross-account sessions, automatic reconciliation, or stronger write
  idempotency — Spotify does not provide enough guarantees today.

## Conformance kit asserts

- A fixture proves create-only, resume-only follow-up, and fresh control have
  the stated history behavior; session collision, missing/busy/corrupt or
  account/app mismatch refuse without fresh work.
- The complete catalog above is positively reachable through wrappers; excluded
  operational and general-purpose tools are negatively rejected. A read-only
  device/library request exits successfully without a write.
- Mocked player control distinguishes acknowledged from verified effect;
  `--no-playback`, saved-policy omission, apply nesting, pagination/read-back,
  and per-turn budgets are enforced.
- Offline fixtures cover crash uncertainty, full current-turn transcript, no
  historical mutation replay, `0700` directory and `0600` file/sidecar modes,
  lease-safe purge, and one-call `--local` observation. Model and storage spies
  prove injected credentials are rejected before either receives them.
- Before calling the implementation verified, bounded real-provider runs
  against fake Spotify and LAN implementations exercise native tool calls and
  cross-process continuation. Offline tests alone cannot prove that integration;
  no real playback is required.

## Reserved / open questions (NOT frozen)

- The retention, projection, and disconnect direction in
  `boundary.v2-candidate.md` and the accompanying Vision candidate was ratified
  with this contract; adoption must precede runtime implementation.
- The credential barrier follows the governing boundary, unavailable-provider
  handling and the closed error vocabulary follow `refusals.v1`; this contract
  adds no session-specific error codes.

## Changelog

- **2026-09-09 — ratified.** The steward ratified this contract and the
  accompanying boundary and Vision proposals, and required README, docs,
  `-h`, and `--help` to remain accurate for their respective audiences.
  This records direction, not a conformance pass or a freeze.