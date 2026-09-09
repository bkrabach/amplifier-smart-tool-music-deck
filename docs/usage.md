# Using music-deck

This guide separates the model-backed `do` workflow from deterministic Spotify commands. It uses invented playlist names and public song names; do not publish output from a real account.

## Before the first playlist

`do` sends real Spotify and provider requests and can write playlists. It requires an authorized Spotify app and a model runtime; start with `music-deck check` and the app setup guide in [spotify-app.md](spotify-app.md).

> **Visibility warning:** creation requests `public: false`, but that request is not a guarantee that a later metadata read will report the playlist as non-public. Spotify documents `public` as profile publication, not access control; its Web API cannot manage access control. Verify visibility in the Spotify app before adding sensitive listening data. https://developer.spotify.com/documentation/web-api/concepts/playlists https://developer.spotify.com/documentation/web-api/reference/change-playlist-details

## One complex `do` request

Make the intended target and ordering explicit. `--max-turns` limits native tool calls, not the number of future messages; `--max-requests` limits Spotify requests.

```sh
music-deck do "Create a playlist named Weekend Guitar with these songs in this order: Smells Like Teen Spirit by Nirvana; Today by The Smashing Pumpkins; Loser by Beck; Cannonball by The Breeders; Connection by Elastica; Song 2 by Blur." \
  --max-turns 14 --max-requests 30
```

Within one invocation, `do` can use the closed supported music-domain tool catalog: all supported catalog search kinds and typed reads; a projected account profile; playlist list/items/create/add/remove/reorder/rename; library list/save/remove/contains including Liked Songs; following, top, recently played, now playing, devices, and queue; Spotify API playback controls; and a structured in-memory plan application. `finish` only ends the native run; it is not a music operation or a playlist-written criterion.

The model cannot use login, setup, disconnect, raw check, manifest or session administration, recursive `plan`/`do`, shell, files, web, general network, browser, delegation, MCP, or engine built-ins. Each exposed tool has a closed JSON schema; results are projections rather than raw account payloads.

## Effects and a later fresh request

`--read-only` blocks every playlist, library, player, and nested-plan write before Spotify is contacted. `--no-playback` blocks player writes while allowing playlist and library work. `--local` is required for one bounded, read-only local Connect observation, only after the authenticated API device read; it does not activate a receiver or grant playback control.

```sh
music-deck do "List my saved tracks and current queue." --read-only
music-deck do "Add Debaser by Pixies to Weekend Guitar, but do not control playback." --no-playback
```

Every CLI or Python `do` call in this build is fresh and ephemeral. Named create/resume sessions and session list/delete commands are not implemented; there is no implicit selection of a latest session. A reference such as “that playlist from the previous message” has no built-in meaning in a later call, so name the playlist or ID again. For an exact ID-targeted read or edit, use deterministic commands.

## Deterministic reads and controls

Use the non-model CLI for read-only work and explicit controls:

```sh
music-deck search "Debaser Pixies" --type track --limit 5
music-deck playlists --limit 20
music-deck playlist items "<playlist-id>" --limit 50
music-deck library list --type tracks --limit 20
music-deck now-playing
music-deck devices
```

`music-deck devices` lists authenticated Spotify Web API devices. `music-deck devices --local` additionally performs a bounded Linux-only mDNS observation of `_spotify-connect._tcp.local.` across eligible physical private-IPv4 multicast interfaces and reads credential-free receiver metadata. Its local observations remain separate from the cloud device list: an advertised receiver is not proven account-bound, API-controllable, or logged in. No local activation or playback is implemented.

Both `do` and deterministic commands can request playback controls for eligible API devices. They have effects; for example, `music-deck pause` requests that Spotify pause playback. Do not include a playback write in installation or readiness checks, do not assume anything already playing accepts API control, and treat an HTTP acknowledgement as acknowledged rather than independently verified playback.

## Python use and failure handling

`do` is also callable from Python. A successful call returns a JSON-shaped dictionary. A failure raises `MusicDeckError`, whose public attributes are `code`, `message`, `remedy`, `extra`, `diagnostic_code`, and `exit_code`.

```python
from music_deck.errors import MusicDeckError
from music_deck.verbs.do import do

brief = "Create a playlist named Documentation Demo with Song 2 by Blur."

try:
    result = do(brief, max_turns=14, max_requests=30, no_playback=True)
except MusicDeckError as exc:
    print(exc.code)       # e.g. "partial_result"
    print(exc.message)
    print(exc.remedy)
    print(exc.exit_code)  # CLI-equivalent exit status
    partial = exc.extra.get("result")
    completeness = exc.extra.get("completeness")
else:
    print(result["playlist"])
    print(result["tracks"])
```

The CLI prints a failure envelope on stdout:

```json
{"error": {"code": "…", "message": "…", "remedy": "…"}}
```

## Read results before treating work as complete

A successful projected read exits 0 without requiring a playlist. `do` records each operation's effect as observed, acknowledged, verified, unknown, or refused as applicable. An HTTP acknowledgement alone is not proof that Spotify made the requested change; inspect a relevant readback before treating an effect as verified. Incomplete or unknown work returns `partial_result` with `result` and `completeness`; do not blindly replay an uncertain write.

A successful `do` result includes the playlist and tracks when playlist readback applies, projected tool results, searches, actions, per-operation completed/refused/unknown states, completeness, ceilings, and transcript. Both ceilings are reported. The defaults are 8 native tool calls and 40 actual outbound Spotify requests, including retries and refresh traffic; a larger request may need explicit budgets, but limits do not guarantee completion.

## Safe testing

1. Use a dedicated test account and unambiguous synthetic playlist names.
2. Start with deterministic reads and inspect returned data before a write.
3. Treat every write as real; `do` has no preview-only execution mode.
4. Keep tokens, client IDs, account data, device details, playlist IDs, and raw live output out of issues, commits, and public docs.

`plan` followed by `apply` is the review-first alternative: `plan` uses the model to produce a document, then `apply plan.json` executes it deterministically. Review the plan before it changes Spotify.
