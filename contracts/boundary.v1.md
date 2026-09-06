# Spotify Boundary Contract — v1 (DRAFT)

**Who builds against this:** the owner, who runs music-deck under their own
Spotify developer app and is the party in breach if this contract lapses; the
`music_deck` library's model, HTTP, and filesystem layers; anyone reviewing
whether music-deck is safe to point at a real account.

## Purpose

Spotify's Developer Policy §III and Developer Terms §IV forbid ingesting
Spotify content into an AI model. This contract is how music-deck keeps its
owner on the right side of that line — not by trusting good intentions, but
by making the boundary something a reviewer can check.

## Core (the teeth)

1. **`plan` performs no Spotify Web API request.** It succeeds with no
   network reachability to `api.spotify.com` at all.
2. **Every prompt sent to a model consists solely of the caller's own text and
   music-deck's own static schema and prompt text.** No Spotify response, no
   cache, no token, and no data from a prior run ever enters a prompt.
3. **The prompt transcript is an observable output of `plan`.** The result
   document carries `transcript` — the verbatim text of every prompt sent —
   so a caller or reviewer can verify clause 2 without reading code.
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
6. **`disconnect` deletes the token and every locally cached byte of Spotify
   content, and reports what it deleted** (Developer Terms §V's disconnect
   mechanism). **`check` reports the auth facts and exits 0 always** — it
   never fails just because the account is not connected.
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
8. **No persistent store of Spotify content.** The only things that persist
   are the token, the config file, and plan/transcript artifacts — which, by
   clause 2, contain no Spotify content. Any response caching is in-memory or
   temp-dir, temporary, and strictly necessary.

## What v1 deliberately does NOT freeze

- A `diagnose` verb over the tool's own operational evidence — promoted when
  real field failures arise that `check` cannot explain.
- Client-credentials flow for catalog-only calls — decided no for v1;
  promoted if a real caller needs catalog access with no user account at all.
- A dynamically chosen port, registered without one. Spotify's documentation
  describes this for loopback literals; its dashboard refused a portless
  registration on 2026-09-06. Promoted the day the dashboard accepts one.

## Conformance kit asserts

- A recording model substrate captures every prompt sent by `plan`: GOOD = a
  plan built from the brief alone passes; BAD = the same run with fetched
  track metadata appended to the prompt fails.
- `plan` run offline makes zero requests to `api.spotify.com`.
- Removed-endpoint check: static (no removed path literal in source) and
  runtime (no request path matches the removed list).
- The token file is created at mode `0600`.
- The port `login` binds is the port `check` reports: one value, two readers.
- `login` refuses loudly, naming the port, when that port is already in use --
  it never silently picks another.
- `disconnect` leaves no Spotify content on disk afterward.
- `evidence/`: one live round-trip — `login` → `plan` → `apply` → the
  playlist exists — run by the owner against their own Development Mode app.
  Owner-only; can't check by machine.

## Reserved / open questions (NOT frozen)

- The `user-personalized` scope.
- Whether a plan may carry a Spotify ID the caller typed in themselves.

## Changelog

- **2026-09-06 — ratified ("Yep, do it all, consider it ratified and take it all
  the way live").** Core 4 moves from an ephemeral port to a fixed, registered
  one. Spotify's dashboard refused a portless registration that day, while its
  documentation still described exactly that; the dashboard is the reality a
  caller meets. The old clause also let `login` bind a random port while `check`
  reported a configured one, so the tool contradicted its own report.
