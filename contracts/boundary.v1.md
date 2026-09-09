# Spotify Boundary Contract — v1 (DRAFT)

**Who builds against this:** the owner, who runs music-deck under their own
Spotify developer app and is the party in breach if this contract lapses; the
`music_deck` library's model, HTTP, and filesystem layers; anyone reviewing
whether music-deck is safe to point at a real account.

## Purpose

Spotify's Developer Policy §III says: *"Do not ... otherwise ingest Spotify
Content into a machine learning or AI model."* **music-deck does that,
knowingly** — its model reads what Spotify returns, and the owner accepts the
revocation risk §VII names. This contract no longer prevents that; it makes
what crosses into a prompt checkable, and holds what is still promised.

## Core (the teeth)

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
2. **No credential ever enters a prompt.** Not the access token, the refresh
   token, or the client ID — not in text, not in a tool result, not in a
   retry. A model that can read Spotify still never reads the keys to it.
3. **The prompt transcript is an observable output.** The result document
   carries `transcript` — every prompt sent, verbatim — so a reviewer sees what
   crossed without reading code. Clause 1 makes this load-bearing.
4. **Auth is PKCE only, with the caller's own client ID.** The redirect URI is
   a loopback IP literal on a **fixed, registered port** — `http://127.0.0.1:8888`
   by default, never `localhost` — and `login` binds exactly the port the caller
   registered. One value, reported by `check` and used by `login`: a redirect URI
   a caller can read but the tool does not honour is worse than none. Plain HTTP
   only because the host is loopback. The token lives at
   `$XDG_STATE_HOME/music-deck/token.json`, mode `0600`. No client secret
   anywhere, and no credential ships with the tool.
5. **`login` is the only interactive verb.** Every other verb fails
   `not_authenticated`, naming `music-deck login` as the remedy.
6. **`disconnect` deletes the token, every locally cached byte of Spotify
   content, and managed conversation history and native checkpoints or journals,
   and reports what it deleted** (Developer Terms §V's disconnect mechanism).
   It prevents concurrent writers from recreating that managed history while
   deletion is in progress; incomplete cleanup is reported as `partial_result`.
   **`check` reports the auth facts and exits 0 always** — it never fails just
   because the account is not connected.
7. **No removed endpoint is ever constructed.** The tool uses
   `/playlists/{id}/items`, `/me/library`, `/me/library/contains`, and
   `POST /me/playlists`; it never issues a request to an endpoint Spotify has
   withdrawn.
   <details><summary>Details</summary>
   Withdrawn families it never calls: batch `GET /tracks|/albums|/artists`,
   `/users/{id}*`, `/browse/*`, `/markets`, `/recommendations`,
   `/audio-features`, `/audio-analysis`, `related-artists`, `top-tracks`, and
   the type-specific `/me/<type>` library and follow/contains endpoints.
   </details>
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

## What v1 deliberately does NOT freeze

- A `diagnose` verb over the tool's own operational evidence — when field
  failures arise that `check` cannot explain. · Client-credentials flow for
  catalog-only calls — promoted if a caller needs catalog with no user account.
- A dynamically chosen port, registered without one. Spotify's documentation
  describes this for loopback literals; its dashboard refused a portless
  registration on 2026-09-06. Promoted the day the dashboard accepts one.

## Conformance kit asserts

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

## Reserved / open questions (NOT frozen)

- The `user-personalized` scope.
- Whether a plan may carry a Spotify ID the caller typed in themselves.

## Changelog

- **2026-09-09 — ratified direction adopted.** The steward ratified the v2
  candidate alongside `do.v1` and the Vision amendment. Core 1 now names the
  bounded `do` music-domain projections; Core 6 adds managed-history cleanup;
  and Core 8 permits only caller-created managed conversations with
  pre-ingress credential rejection and private permissions. This records the
  accepted direction, not implementation or a conformance pass.
- **2026-09-06 — ratified ("2" · full removal, labelled).** The one-way
  boundary is gone: a model may read what Spotify returns, breaching §III, and
  the Purpose says so rather than hiding it. What survives is the half that was
  never about content — no credential in a prompt — plus the transcript, now
  load-bearing. Removed because a model that cannot see its results cannot
  correct them: measured that day, `genre:grunge` returns 5 and `year:` works
  with other genres, but the conjunction returns 0, and only running it reveals
  that.
- **2026-09-06 — ratified ("take it all the way live").** Core 4 moves from an
  ephemeral port to a fixed, registered one: Spotify's dashboard refused a
  portless registration that day, and the old clause let `login` bind a random
  port while `check` reported a configured one.
