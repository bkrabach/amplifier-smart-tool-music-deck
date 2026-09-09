# music-deck

A Spotify Smart Tool for agents and scripts. It can build playlists from a plain-language brief, inspect Spotify data deterministically, and control eligible Spotify API devices.

## Install and set up

Requires Python 3.12 or later and `uv`: https://docs.astral.sh/uv/getting-started/installation/

Install deterministic commands:

```sh
uv tool install git+https://github.com/bkrabach/amplifier-smart-tool-music-deck
```

To use model-backed `plan` and `do` with Anthropic, install the complete runtime into the tool environment, then provide the provider key:

```sh
uv tool install --force --with anthropic --with "amplifier-agent @ git+https://github.com/microsoft/amplifier-agent@v1#subdirectory=packages/python" git+https://github.com/bkrabach/amplifier-smart-tool-music-deck
export ANTHROPIC_API_KEY="<your-provider-key>"
```

### Registering your own Spotify app

Use your own Spotify Development Mode app and Premium account. Register
`http://127.0.0.1:8888` as the default redirect URI, not `localhost`.
Configure the app's client ID (not its client secret), authorize once, then
inspect readiness:

```sh
music-deck setup --client-id "<your-client-id>"
music-deck login
music-deck check
```

`music-deck setup --guide` prints the complete app-registration guidance, including the redirect URI. See [docs/spotify-app.md](docs/spotify-app.md) for the repository version.

Over SSH, use `music-deck login --no-browser` on the tool host and follow the
printed tunnel instructions from the browser machine before opening the
authorization URL.

## Choose the right interface

| Need | Use | Important boundary |
|---|---|---|
| Interpret a brief with bounded Spotify music operations | `music-deck do` | Model-backed; it offers the closed catalog, playlist, library, account/listening, and player surface—not general tools. |
| Review a model-produced playlist plan before a write | `music-deck plan` then `music-deck apply plan.json` | `apply` is deterministic and currently executes track steps only; review before writing. |
| Get a read-only answer from `do` | `music-deck do "…" --read-only` | Blocks every mutation before Spotify is contacted; a successful read exits 0. |
| List account devices or observe local receivers | `music-deck devices` / `music-deck devices --local` | Local advertisements are observations, not authenticated controllable devices. |
| Avoid playback effects during a mixed request | `music-deck do "…" --no-playback` | Blocks player writes while allowing playlist and library work. |

## Privacy and external-service limits

> **Verify playlist visibility before adding sensitive listening data.** Playlist creation requests `public: false`, but acceptance of that request is not proof that later Spotify metadata will report the playlist as non-public. Spotify documents `public` as profile publication, not access control, and its Web API does not manage access control. Check visibility in the Spotify app before adding sensitive content. See https://developer.spotify.com/documentation/web-api/concepts/playlists and https://developer.spotify.com/documentation/web-api/reference/change-playlist-details.

`do` sends real Spotify and provider requests, and can read account, library, listening, device, queue, and playback state; it can also change playlists and saved library items or issue eligible Spotify API playback controls. `--local` adds only a bounded LAN observation. `do` deliberately allows the model to read projected Spotify results so it can correct its searches. This knowingly conflicts with Spotify Developer Policy §III: “Do not ... otherwise ingest Spotify Content into a machine learning or AI model.” Spotify may revoke platform access under §VII. Credentials are excluded from prompts, but Spotify results and raw output may contain personal data. Use synthetic examples in public material and keep live evidence private.

`do` and the deterministic playback commands can request controls only for eligible Spotify Web API devices. An already-playing receiver is not necessarily API-controllable; an HTTP acknowledgement is not verified playback.

## Create and extend a playlist

For a bounded creation request, make the target explicit and budget native calls:

```sh
music-deck do "Create a playlist named Weekend Guitar with these songs in this order: Smells Like Teen Spirit by Nirvana; Today by The Smashing Pumpkins; Loser by Beck; Cannonball by The Breeders; Connection by Elastica; Song 2 by Blur." --max-turns 14 --max-requests 30
```

For an inventory without effects, use `--read-only`; `--no-playback` permits playlist or library work but blocks player writes. `--local` is a separate per-invocation opt-in for one bounded, read-only local observation after an authenticated API device read. Each `do` call is currently fresh and ephemeral: named create/resume sessions are not implemented, and there is no implicit “latest” session. Name the target again rather than relying on “that playlist from the previous message.” See [docs/usage.md](docs/usage.md) for result handling, Python use, and safe testing.

## Documentation

- [Usage guide](docs/usage.md) — `do`, deterministic reads, Python, and limitations.
- [Spotify app setup](docs/spotify-app.md) — register and authorize your own app.
- [Contracts overview](docs/CONTRACTS-README.md) and [vision](docs/VISION.md) — project direction and boundaries.
- [Contributing](CONTRIBUTING.md), [security reporting](SECURITY.md), and [support](SUPPORT.md).
- [MIT license](LICENSE) and [Code of Conduct](CODE_OF_CONDUCT.md).

## Contributing

Contributions should preserve the project contracts, use synthetic fixtures instead of live account data, and include focused offline verification. Read [CONTRIBUTING.md](CONTRIBUTING.md), `AGENTS.md`, and `PINS.md` before starting.

## Trademarks

music-deck is an independent community project owned by its contributors, not by Microsoft or Spotify. “Spotify” is a trademark of Spotify AB; other names, marks, and logos belong to their respective owners. Use of a name in this repository does not imply endorsement, affiliation, or sponsorship. Third-party rights remain with their respective owners.
