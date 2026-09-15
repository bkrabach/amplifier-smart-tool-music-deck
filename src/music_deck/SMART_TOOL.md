---
smart_tool_format: 1
name: music-deck
version: 0.1.0
description: >
  Works with Spotify through a bounded model-backed `do` workflow, a reviewable
  `plan` then deterministic `apply` workflow, and deterministic catalogue,
  playlist, library, device, and playback commands. `do` exposes the closed,
  supported music-domain library surface (not general tools), with `--read-only`,
  `--no-playback`, and one-observation `--local` effect boundaries. Each invocation
  is currently fresh and ephemeral; named create/resume sessions are not yet
  implemented, and no latest session is selected. Use deterministic commands
  for exact ID-targeted work.
use_cases:
  - Carry out one explicit playlist brief, with bounded search, read-back, and playlist writes
  - Turn a brief into a readable plan that a person can review before deterministic application
  - Search Spotify, inspect playlists or saved items, and explicitly edit playlists through deterministic commands
  - List authenticated Spotify API devices and separately observe local Spotify Connect advertisements on Linux
  - Control playback only on an eligible Spotify API device through deterministic commands
platforms:
  - linux
  - macos
requires:
  - name: spotify-app
    purpose: >
      music-deck ships no credentials. It runs under the caller's own Spotify
      Development Mode app, which supplies the client ID it authorises with, and
      whose owner must hold Spotify Premium for the app to function at all. The
      tool carries the registration steps itself: run `music-deck setup`.
    install: https://github.com/bkrabach/amplifier-smart-tool-music-deck#registering-your-own-spotify-app
---

# music-deck

A Spotify tool for agents and scripts. It offers bounded model-backed music operations alongside a reviewable plan/apply path and deterministic Spotify commands.

## Choose the workflow

**`do`** interprets one plain-language brief within a bounded native tool loop. It can use the closed supported music-domain library catalog: all supported catalog search kinds and typed reads; projected account profile; playlist and saved-library reads and supported edits; following, top, and recently played; projected playback, devices, and queue; existing Spotify API playback controls; and in-memory structured plan application. It reads projected results before deciding its next step.

`do` is not the general CLI or an escape hatch. It cannot use auth, setup, disconnect, raw check, manifest or session administration, recursive `plan`/`do`, shell, files, web, general network, browser, delegation, MCP, or engine built-ins. `--read-only` blocks every mutation; `--no-playback` blocks player writes; `--local` permits at most one read-only local observation after the authenticated API device read. Each invocation is fresh and ephemeral; named create/resume sessions are not implemented and no latest session is selected, so name a target again for a follow-up.

**`plan` then `apply`** separates interpretation from an account write. `plan` turns the brief into a readable document for a person to review. `apply plan.json` carries that document out deterministically and does not make a model call.

Plan execution currently supports track steps only. Album-typed steps refuse
before any Spotify request, also through `do`'s in-memory `apply`; album catalog
searches remain supported. Do not treat this limitation as full plan.v1 conformance.

**Deterministic commands** handle exact reads and controls: catalogue search, playlist and saved-library inspection, playlist rename/remove/reorder, account-device listing, and eligible-device playback commands. Use them when you need a read-only answer or an exact ID target.

## Boundaries and cautions

- `plan` and `do` need a configured model runtime. Other commands do not need a provider; `check` needs neither credentials nor network.
- `do` uses real provider and Spotify requests, can make supported music effects, and has default ceilings of 8 native tool calls and 40 Spotify requests. `--max-turns` budgets native calls, not future user messages; pagination and readback consume the request budget.
- A verified read may succeed with exit 0 and no playlist. A write acknowledgement is reported as `acknowledged`, not verified until a relevant read confirms it. Incomplete, refused-effect, or unknown-write work returns the existing `partial_result` envelope with its `completeness` record; unknown writes are never blindly retried.
- Credentials do not enter prompts, but Spotify results may reach the model and raw output may contain personal data. This knowingly conflicts with Spotify Developer Policy §III's AI-ingestion prohibition. Use synthetic public examples and keep live evidence private.
- Playlist creation requests `public: false`, but acceptance is not proof that later Spotify metadata will report the playlist as non-public. Spotify describes `public` as profile publication, not access control, and its Web API cannot manage access control. Verify playlist visibility in the Spotify app before adding sensitive content. https://developer.spotify.com/documentation/web-api/concepts/playlists https://developer.spotify.com/documentation/web-api/reference/change-playlist-details

## Devices and playback

`music-deck devices` lists Spotify Web API devices authenticated to the account. Those are distinct from `music-deck devices --local`, which on Linux performs bounded mDNS observation of `_spotify-connect._tcp.local.` over eligible physical private-IPv4 multicast interfaces and reads credential-free receiver metadata.

A locally advertised receiver is not proof that it belongs to the account, is logged in, can be activated, or accepts Spotify API playback control. No local activation or playback occurs. Deterministic playback commands target eligible Spotify API devices; an already-playing receiver can still reject a write.

## Examples

Install the deterministic tool, then configure your own Spotify app with
`music-deck setup --guide` and `music-deck login`:

```sh
uv tool install git+https://github.com/bkrabach/amplifier-smart-tool-music-deck
```

For model-backed `plan` and `do`, install the provider SDK and engine together
in the tool environment, then set `ANTHROPIC_API_KEY` in your environment:

```sh
uv tool install --force --with anthropic --with "amplifier-agent @ git+https://github.com/microsoft/amplifier-agent@v1#subdirectory=packages/python" git+https://github.com/bkrabach/amplifier-smart-tool-music-deck
```

```sh
# Inspect local readiness; this makes no Spotify or model call.
music-deck check

# Make a bounded, real playlist request.
music-deck do "Create a playlist named Weekend Guitar with Song 2 by Blur and Debaser by Pixies in that order." \
  --max-turns 14 --max-requests 30

# Review before a deterministic write.
music-deck plan "Upbeat guitar songs for a morning" --output plan.json
music-deck apply plan.json

# Read exact Spotify state instead of invoking do.
music-deck playlists --limit 20
music-deck playlist items "<playlist-id>" --limit 50
music-deck devices
music-deck devices --local
```

See `docs/usage.md` in the repository for follow-ups, Python error handling, and safe testing guidance. This body is free-form guidance; the frontmatter above is the manifest data.

For an opt-in real-provider evaluation against fake Spotify and LAN state, run
`python -m music_deck.evaluation --help` from an installed artifact. It never
uses account or LAN state, but requires an explicit confirmation before it calls
the configured model provider. Named-session evaluation is reported blocked
until named create/resume is implemented.
