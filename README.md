# music-deck

A Smart Tool for curating and controlling music on Spotify from any agent.

## Install

```
uv tool install git+https://github.com/bkrabach/amplifier-smart-tool-music-deck
```

That puts `music-deck` on your PATH. Nothing else is needed to run it: the
deterministic verbs need no model provider and no provider SDK, and `check`
needs no credentials and no network.

## From nothing to ready

```
music-deck setup                            # what is configured, what is missing
music-deck setup --client-id <your id>      # write the client ID (config 0600)
music-deck login                            # authorise, once, in a browser
music-deck check                            # confirm
```

`music-deck setup` never prompts and never reads stdin. Run it with no arguments
and it reports what is missing, carries the whole Spotify-app registration guide,
and names the single next command to run. `login` is the only interactive verb
there is.

Then:

```
music-deck plan "upbeat 90s guitar songs for a Saturday morning" --output plan.json
music-deck apply plan.json
```

`plan` is the only verb that uses a model. Without a usable model substrate it
refuses (exit 3) naming exactly which precondition is missing, and never falls
back to a deterministic answer. Every other verb runs with no provider at all.

## Registering your own Spotify app

music-deck ships **no credentials**. It runs under your own Spotify app, using
your own client ID, and stores only your token. Registering one takes about ten
minutes and needs a Spotify account with **Premium**.

**The steps ship inside the tool.** Run:

```
music-deck setup
```

and read the `spotify_app` block: the Development Mode ceiling, creating the app,
the exact redirect URI (`http://127.0.0.1`, no port, never `localhost`), copying
the client ID (never the client secret), the five-user allowlist, and signing in.
It works offline, from any install, with no checkout anywhere.

The same material is in [`docs/spotify-app.md`](docs/spotify-app.md) for anyone
reading this repository. That file is *not* what any remedy points at:
`cli.v1` Core 4 requires a remedy to name something the reader has, and a reader
who ran `uv tool install` has the package, not the repository.

## Sharp edges

- **Development Mode is the ceiling** — five allowlisted users, an owner who
  holds Premium, and an undisclosed shared quota.
- **Refresh tokens die after six months** and refreshing does not extend them.
  Re-authorising is a normal event, not a fault. `check` reports how long is left.
- **music-deck produces no audio.** It is a remote control for a device that is
  already playing.
- **Nothing Spotify returns ever reaches a model.** `plan` publishes the verbatim
  transcript of every prompt sent, so you can confirm that without reading code.

## Adding a model provider to a tool install

A `uv tool install` owns its own virtualenv, and `uv pip install` cannot reach
inside it. To add a provider SDK:

```
uv tool install --force --with anthropic git+https://github.com/bkrabach/amplifier-smart-tool-music-deck
```

`plan`'s refusal names this command for you, with the right package in it.

## Governance

Governed by `docs/VISION.md` and `contracts/` (Converge protocol).
