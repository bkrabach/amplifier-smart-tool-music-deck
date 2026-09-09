---
smart_tool_format: 1
name: music-deck
version: 0.1.0
description: >
  Carries out a plain-words brief about music against Spotify -- either in one
  conversational verb that searches, reads what came back, corrects itself and
  writes, or as a readable plan a person checks before anything runs. Also
  searches the catalogue and drives whatever device is already playing. Reach
  for it when an agent needs to build or edit a Spotify playlist, look something
  up in the catalogue, or control playback without opening the Spotify app.
use_cases:
  - Carry out a plain-words brief end to end, correcting a search that returns nothing before writing anything
  - Turn a plain-words brief into a readable playlist plan a person can check before anything runs
  - Apply an approved plan against Spotify and get back what was found, kept, and skipped
  - Search the Spotify catalogue and inspect tracks, albums, artists, shows, and episodes
  - Read and edit playlists and the saved library from a script or an agent
  - Drive playback on a device that is already playing -- pause, skip, seek, volume, transfer
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

A deck of controls for Spotify, built to be driven by an agent.

## When to reach for it

Reach for music-deck when the job is *music on Spotify* and the caller would
otherwise be opening the app by hand: building a playlist from a description,
tidying one that already exists, looking something up in the catalogue, or
pausing and skipping whatever is currently playing.

There are two shapes of work, and the difference is who reads the middle.

**`do`** is the conversational one. A **brief** -- the caller's own words -- goes
in, and music-deck runs a bounded loop: propose a search, run it, *read what
Spotify actually returned*, correct the aim if it was wrong, then write. It
reports the playlist as **read back from Spotify**, every query it tried, and
what each returned. Reach for this when the caller wants the thing done.

**`plan`** then **`apply`** is the reviewable one. The brief becomes a **plan**:
a JSON document naming the searches to run, the rules to apply, and where the
results land. A person reads the plan. Then `apply` carries it out
deterministically and reports what was found, kept, and skipped. Reach for this
when a person wants to check the middle before anything touches their account.

The measured difference: asked for three 90s grunge songs, a plan wrote
`genre:grunge year:1990-1999`, which returns **zero** results -- `genre:grunge`
alone returns five -- and `apply` created an empty playlist anyway. `do` sees the
zero and searches again, and cannot create a playlist from an empty result set at
all.

## Sharp edges

- **`plan` and `do` are the model-backed verbs; `--help` says which.** Every
  other verb runs with no provider configured and no provider SDK installed.
  Invoked with no usable model substrate, either one refuses (exit 3) naming the
  missing precondition; neither falls back to a deterministic answer.
- **`do` is bounded, and says so.** A turn ceiling and a Spotify-request
  ceiling, both reported in the result. It never creates a playlist for an empty
  result set, and never writes a track URI no search in the run returned. A run
  that ends with nothing written refuses `partial_result` carrying
  `completeness` -- it does not report a success it did not have.
- **No credential ever reaches a model -- Spotify content may.** The access
  token, the refresh token and the client ID never enter a prompt, and both
  model-backed verbs check their own transcript for all three before handing
  back anything. What
  Spotify *returns* is a different matter: music-deck lets a model read search
  results so it can correct its own aim, which knowingly breaches Spotify
  Developer Policy §III. Every result carries the verbatim prompt transcript, so
  a reviewer can see exactly what crossed without reading code.
- **You bring the credentials.** No client ID and no client secret ship with the
  tool. Auth is PKCE against the caller's own app, and the token is stored under
  the caller's own state directory, readable only by them.
- **Development Mode is the ceiling.** A handful of allowlisted users, an owner
  who holds Premium, and a shared quota. A user who is not on the allowlist can
  sign in and still get 403 on every request.
- **Refresh tokens die after six months** and refreshing does not extend them.
  Re-authorisation is a normal event, not a fault.
- **music-deck produces no audio.** It is a remote control for a device that is
  already playing. Every playback write needs Premium and an active device.
- **`check` never fails.** It reports what it found and exits 0 -- including
  "no client ID" and "no token". Reporting a problem is its success.

## Worked invocations

Install it:

```
uv tool install git+https://github.com/bkrabach/amplifier-smart-tool-music-deck
```

The deterministic verbs need no provider or model runtime. To use model-backed
`plan` or `do` with Anthropic, add both runtime packages to the tool environment:

```
uv tool install --force --with anthropic --with "amplifier-agent @ git+https://github.com/microsoft/amplifier-agent@v1#subdirectory=packages/python" git+https://github.com/bkrabach/amplifier-smart-tool-music-deck
export ANTHROPIC_API_KEY=<your key>
```

Then get from a fresh install to ready. `setup` writes prose a person reads: the
gap you actually have, the steps that close it, and the one command to run next.
`--json` returns the same content structured, and `--guide` prints the whole
Spotify-app orientation on request. It never prompts:

```
music-deck setup
music-deck setup --json
music-deck setup --guide
music-deck setup --client-id <your client id>
music-deck login
```

Confirm the install and read the current auth facts. Works with no credentials,
no provider, and no network:

```
music-deck check
```

Read the tool's own manifest as structured data:

```
music-deck manifest
```

Authorise against your own Spotify app, once:

```
MUSIC_DECK_CLIENT_ID=<your client id> music-deck login
```

Over SSH, run `music-deck login --no-browser` on the tool host. Before opening
the authorisation URL it prints, run the exact `ssh -L` command `login` prints
from the browser machine.

Carry out a brief end to end -- searching, correcting, writing, reading back:

```
music-deck do "three 90s grunge songs in a new playlist called Flannel"
music-deck do "an hour of ambient for focus" --max-turns 12 --max-requests 60
```

Or take the reviewable route: turn a brief into a plan, read it, then apply it:

```
music-deck plan "upbeat 90s guitar songs for a Saturday morning" --output plan.json
music-deck apply --plan plan.json
```

Drive whatever is already playing:

```
music-deck devices
music-deck devices --local
music-deck pause
```

`devices --local` is a bounded, Linux-only, UP-multicast physical IPv4,
read-only observation of local Spotify Connect
advertisements. Its `local` result stays separate from Spotify's account device
list and does not establish playback support, control, or login on a receiver.

This body is free-form guidance. Nothing depends on a particular sentence in it.
