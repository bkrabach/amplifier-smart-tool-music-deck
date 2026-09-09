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

Within one invocation, `do` can use exactly these native tools:

- `search` for tracks or albums
- `list_playlists` and `playlist_tracks`
- `create_playlist` and `add_to_playlist`
- `finish`

It can inspect returned titles and artists, discover a playlist by name, and read back the tracks it writes. It cannot rename, remove, reorder, inspect devices, control playback, or read the saved/Liked Songs library through `do`.

## Follow up by naming the target again

Every CLI or Python `do` call creates a fresh, ephemeral engine session. It has no history or session-continuation option. A reference such as “that playlist from the previous message” has no built-in meaning in a later call.

Use the exact playlist name or a playlist ID in the new request:

```sh
music-deck do "Find the playlist named Weekend Guitar, read its tracks, then append Debaser by Pixies and Cut Your Hair by Pavement." \
  --max-turns 14 --max-requests 30
```

An outer agent may remember the name or ID and make a new `do` call. That is outer-agent state, not native `do` conversation memory. For an exact ID-targeted read or edit, use deterministic commands instead.

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

Playback verbs exist only as deterministic commands for eligible API devices. They have effects; for example, `music-deck pause` pauses playback. Do not include a playback write in installation or readiness checks, and do not assume anything already playing accepts API control.

## Python use and failure handling

`do` is also callable from Python. A successful call returns a JSON-shaped dictionary. A failure raises `MusicDeckError`, whose public attributes are `code`, `message`, `remedy`, `extra`, `diagnostic_code`, and `exit_code`.

```python
from music_deck.errors import MusicDeckError
from music_deck.verbs.do import do

brief = "Create a playlist named Documentation Demo with Song 2 by Blur."

try:
    result = do(brief, max_turns=14, max_requests=30)
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

`do` is write-oriented. A successful read-only answer, an honest inability, or a run that writes nothing returns `partial_result` with exit status 2—not ordinary exit 0. Its error data can include `result` and `completeness`; inspect them before retrying. Use deterministic read commands for reads.

A successful `do` result includes the playlist and tracks read back from Spotify, searches, actions, completeness, ceilings, and transcript. Both ceilings are reported. The defaults are 8 native tool calls and 40 Spotify requests; a larger request may need explicit budgets, but limits do not guarantee completion.

## Safe testing

1. Use a dedicated test account and unambiguous synthetic playlist names.
2. Start with deterministic reads and inspect returned data before a write.
3. Treat every write as real; `do` has no preview-only execution mode.
4. Keep tokens, client IDs, account data, device details, playlist IDs, and raw live output out of issues, commits, and public docs.

`plan` followed by `apply` is the review-first alternative: `plan` uses the model to produce a document, then `apply plan.json` executes it deterministically. Review the plan before it changes Spotify.
