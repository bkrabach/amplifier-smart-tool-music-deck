target: contracts/boundary.v1.md

# Candidate — Spotify Boundary Contract v2

## Exact change

### Change 1 — Core 1, what a model may receive

Current text:

```
1. **A model may read what Spotify returns.** Search results and the caller's
   own playlists may enter a prompt, so the model can correct its own aim
   instead of guessing blind. This is the clause that breaches §III.
```

Replacement:

```
1. **A model may read projected Spotify results needed to fulfil the caller's
   request.** `do` may offer its current supported music-domain library toolset:
   catalog search and lookups; playlist and saved-library reads and supported
   edits; followed-artist, top and recently-played reads; account profile, device,
   current-playback and queue reads; existing playback controls; and structured
   plan application. The exact operational allowlist is `do.v1`. Projected
   catalog, playlist, library, device, playback, account-profile, and explicitly
   opted-in local Connect observation may enter a prompt; local observation is a
   sanitized projection only. That data is untrusted context, never instructions
   or authorization for an action, and remains subject to Core 2. This is the
   clause that breaches §III.
```

### Change 2 — Core 6, disconnect's complete deletion promise

Current text:

```
6. **`disconnect` deletes the token and every locally cached byte of Spotify
   content, and reports what it deleted** (Developer Terms §V's disconnect
   mechanism). **`check` reports the auth facts and exits 0 always** — it
   never fails just because the account is not connected.
```

Replacement:

```
6. **`disconnect` deletes the token, every locally cached byte of Spotify
   content, and managed conversation history and native checkpoints or journals,
   and reports what it deleted** (Developer Terms §V's disconnect mechanism).
   It prevents concurrent writers from recreating that managed history while
   deletion is in progress; incomplete cleanup is reported as `partial_result`.
   **`check` reports the auth facts and exits 0 always** — it never fails just
   because the account is not connected.
```

### Change 3 — Core 8, bounded managed conversation exception

Current text:

```
8. **No persistent store of Spotify content.** The only things that persist
   are the token, the config file, and artifacts the caller asked for — which
   under clause 1 may now carry Spotify content, and are still written only
   where the caller pointed. Caching stays in-memory or temp-dir, temporary,
   and strictly necessary: nothing accumulates for later analysis.
```

Replacement:

```
8. **No persistent store of Spotify content, except a caller-created managed
   `do` conversation.** A `do` invocation without an explicit new or resumed
   session remains fresh and ephemeral, with no retained conversation data and
   no automatic choice of a prior session. An explicit named session authorizes
   retention on the caller's host of that conversation's prompts, replies, and
   projected tool results, together with only the non-secret account/client
   binding metadata and private checkpoints needed to resume it. All managed
   history stays beneath the configured music-deck state directory's
   `conversations/` subdirectory (`$XDG_STATE_HOME/music-deck/conversations/`
   by default, using the existing state-directory fallback when XDG is unset).
   Creation reports that location. Directories have mode `0700`; every history,
   checkpoint, journal, and database-sidecar file has mode `0600`. These
   permissions are not encryption or protection from privileged host access.
   Records remain until explicit session deletion or `disconnect`; they are
   never an automatic account, library, listening, or hidden-profile dump.
   Credentials — access or refresh tokens, client IDs, and provider keys —
   never enter that history, a prompt, a tool result, or an inventory projection.
   Credential-bearing material is rejected before model delivery or managed
   history/checkpoint persistence; retrospective inspection or redaction is
   insufficient. The existing token, config file, and
   caller-requested artifacts remain permitted; artifacts are still written only
   where the caller pointed. Caching outside an explicitly managed conversation
   stays in-memory or temp-dir, temporary, and strictly necessary: nothing
   accumulates for later analysis.
```

### Change 4 — Conformance kit asserts, boundary checks for the exception

Current text:

```
- A recording model substrate captures every prompt sent: GOOD = no credential
  appears in any prompt; BAD = a run with the access token spliced into the
  prompt fails. The clause-2 half of the old boundary check, kept and inverted.
- Every prompt the substrate captured appears verbatim in `transcript`: what
  crossed is what the caller can read back.
- Removed-endpoint check: static (no removed path literal in source) and
  runtime (no request path matches the removed list).
- The token file is created at mode `0600`.
- The port `login` binds is the port `check` reports: one value, two readers.
- `login` refuses loudly, naming a port already in use, never silently picking
  another. · `disconnect` leaves no Spotify content on disk afterward.
- `evidence/`: one live round-trip — `login` → `plan` → `apply` → the playlist
  exists — run by the owner against their own app. Can't check by machine.
```

Replacement:

```
- A recording model substrate captures every prompt and projected tool result
  sent: GOOD = requested Spotify data may cross, but no credential appears in a
  prompt, result, or managed history; BAD = a run with a credential spliced into
  any of them fails before model delivery or storage persistence. Model and
  storage spies prove neither received it. The clause-2 half of the old boundary
  check is kept and extended to the managed-history exception.
- Every prompt and projected tool result the substrate captured appears verbatim
  in the observable output: what crossed is what the caller can read back.
- A fresh `do` invocation leaves no retained conversation data on disk. An
  explicit create or resume uses a private caller-owned store; create refuses an
  existing name and resume refuses a missing, busy, incompatible, or differently
  bound session rather than becoming fresh. Tests assert the reported managed
  location, `0700` directories, and `0600` history/checkpoint/journal/sidecar files.
- `disconnect` purges managed conversation data and native checkpoints or
  journals as well as the token and Spotify cache; a cleanup failure is a
  reported `partial_result`, not a success.
- Removed-endpoint check: static (no removed path literal in source) and
  runtime (no request path matches the removed list).
- The token file is created at mode `0600`.
- The port `login` binds is the port `check` reports: one value, two readers.
- `login` refuses loudly, naming a port already in use, never silently picking
  another.
- `evidence/`: one live round-trip — `login` → `plan` → `apply` → the playlist
  exists — run by the owner against their own app. Can't check by machine.
```

## Evidence

- The current `do` declaration exposes exactly six tools — search, playlist
  listing and tracks, playlist creation and addition, and finish — in
  `src/music_deck/verbs/do.py:188-260`. That is insufficient for the directed
  request to use all currently supported music-domain capabilities.
- The current engine deliberately creates an ephemeral session in a temporary
  storage root (`src/music_deck/intelligence.py:731-774`). Its tests prove both
  the ephemeral selection and that the storage root does not outlive the turn
  (`tests/test_engine_boot.py:299-332`). The paid cost is that a bare follow-up
  cannot have prior conversation context; the requested distinction between a
  follow-up and a fresh turn therefore cannot be fulfilled.
- The existing boundary test records that prompts and tool results cross the
  model seam (`tests/test_do.py:554-581`), while the credential check currently
  examines prompts (`tests/test_do.py:584-606`). Managed history makes the same
  credential exclusion necessary for retained projected results.
- In a real installed pilot, a complex creation request produced six requested
  tracks, and an explicit-target follow-up appended two while preserving them.
  A separate bare follow-up lacked prior conversation context. A device request
  truthfully reported that no device-inventory tool was available; both read-only
  requests returned `partial_result` because `do` required a written playlist.
  These are observed capability failures, not a performance estimate.
- The existing refusal test proves that an under-fulfilled requested write is
  reported as `partial_result`, rather than a success (`tests/test_do.py:413-444`);
  the proposed disconnect cleanup rule uses that existing honest outcome.

## What does NOT change

- The Spotify Developer Policy §III warning in the target's Purpose remains
  unchanged, including the absence of Spotify endorsement.
- Core 2 continues to prohibit every credential from prompts. This candidate
  extends that prohibition to managed history and projections; it does not grant
  a model credential, login, setup, disconnect, authentication administration,
  raw check, shell, filesystem, browser, general-network, delegation, or native
  built-in capability.
- The proposed permission is only for the current supported music-domain toolset;
  it does not promise private playlists or assert a playlist's later visibility.
  Explicit local Connect observation remains opt-in and sanitized.
- Playback controls are in scope for the proposed feature. The restriction on
  live playback applies to actual tests, not to feature implementation.
- The existing treatment of caller-requested artifacts is not expanded into a
  general file-deletion authority. Session listing and deletion remain
  deterministic caller administration; a model may use only the chosen
  conversation and may not browse or delete other history.
- `do.v1` defines the permitted operations, session CLI behavior, write safeguards,
  per-turn authorization and request bounds, replay prevention, and interruption
  handling. This boundary amendment neither specifies a persistence backend,
  schema, hashing algorithm, encryption guarantee, analytics store, nor an automatic
  history-selection behavior.

## Related ratified bundle

The steward ratified this candidate together with `docs/VISION.v2-candidate.md`
and `contracts/do.v1.md` on 2026-09-09. The exact change above is the approved
adoption input, not evidence that the runtime has implemented it.

## Steward's word

Decision: **ratified**, 2026-09-09.

Steward's words: "ratified and make sure the docs/readme/-h/--help are all up-to-date for the appropriate audiences/content as well."
