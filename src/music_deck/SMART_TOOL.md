---
smart_tool_format: 1
name: music-deck
version: 0.1.0
description: >
  Turns a plain-words brief about music into a readable plan, then carries that
  plan out against Spotify and drives whatever device is already playing. Reach
  for it when an agent needs to build or edit a Spotify playlist, look something
  up in the catalogue, or control playback without opening the Spotify app.
use_cases:
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
      whose owner must hold Spotify Premium for the app to function at all.
    install: docs/spotify-app.md
---

# music-deck

A deck of controls for Spotify, built to be driven by an agent.

## When to reach for it

Reach for music-deck when the job is *music on Spotify* and the caller would
otherwise be opening the app by hand: building a playlist from a description,
tidying one that already exists, looking something up in the catalogue, or
pausing and skipping whatever is currently playing.

The shape of the work is always the same. A **brief** -- the caller's own words
-- becomes a **plan**: a JSON document naming the searches to run, the rules to
apply, and where the results land. A person reads the plan. Then `apply` carries
it out deterministically and reports what was found, what was kept, what was
skipped, and why.

## Sharp edges

- **`plan` is the only verb that touches a model.** Every other verb runs with
  no provider configured and no provider SDK installed. Invoked with no usable
  model substrate, `plan` refuses (exit 3) naming the missing precondition; it
  never falls back to a deterministic answer.
- **Nothing Spotify returns ever reaches a model.** A prompt is built from the
  caller's own text and music-deck's own static schema, and the plan carries the
  verbatim prompt transcript so a reviewer can confirm that without reading code.
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

Turn a brief into a plan, read it, then carry it out:

```
music-deck plan --brief "upbeat 90s guitar songs for a Saturday morning" > plan.json
music-deck apply --plan plan.json
```

Drive whatever is already playing:

```
music-deck devices
music-deck pause
```

This body is free-form guidance. Nothing depends on a particular sentence in it.
