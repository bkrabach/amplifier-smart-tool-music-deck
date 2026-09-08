# music-deck

A Smart Tool for curating and controlling music on Spotify from any agent.

## Install

```
uv tool install git+https://github.com/bkrabach/amplifier-smart-tool-music-deck
```

That puts `music-deck` on your PATH. Nothing else is needed to run it: the
deterministic verbs need no model provider and no provider SDK, and `check`
needs no credentials and no network.

To use the model-backed `plan` and `do` verbs with Anthropic, install their
complete runtime in the tool's own environment, then set your key:

```
uv tool install --force --with anthropic --with "amplifier-agent @ git+https://github.com/microsoft/amplifier-agent@v1#subdirectory=packages/python" git+https://github.com/bkrabach/amplifier-smart-tool-music-deck
export ANTHROPIC_API_KEY=<your key>
```

## From nothing to ready

```
music-deck setup                            # the gap you have, and how to close it
music-deck setup --client-id <your id>      # write the client ID (config 0600)
music-deck login                            # authorise, once, in a browser
music-deck check                            # confirm
```

`music-deck setup` never prompts and never reads stdin. Run it with no arguments
and it writes prose a person reads: what is missing, the steps that close *that*
gap, and the single next command to run — not the whole orientation every time,
which is `music-deck setup --guide`. `--json` returns the same content structured
for anything that parses. `login` is the only interactive verb there is.

Over SSH, run `music-deck login --no-browser` on the tool host. Before opening
the authorisation URL it prints, run the exact `ssh -L` command `login` prints
from the browser machine. The browser callback then reaches the loopback
listener on the tool host.

Then, if you just want the thing done:

```
music-deck do "three 90s grunge songs in a new playlist called Flannel"
```

`do` runs a bounded loop against your account: it proposes a search, runs it,
**reads what Spotify actually returned**, corrects its aim if the search came
back empty, then writes — and reports the playlist as read back from Spotify,
not as it intended it. Both ceilings (turns, Spotify requests) are in the
result, along with every query it tried and what each returned.

Or, if you want to check the middle before anything touches your account:

```
music-deck plan "upbeat 90s guitar songs for a Saturday morning" --output plan.json
music-deck apply plan.json
```

`plan` writes a document a person reads; `apply` carries it out deterministically
and makes no model call at all.

**Why both exist.** Asked for three 90s grunge songs, `plan` wrote
`genre:grunge year:1990-1999`. That search returns **zero** results —
`genre:grunge` on its own returns five, and `genre:alternative year:1990-1999`
returns five — and nothing but running it reveals that. `apply` then created an
empty playlist. `do` sees the zero and searches again, and there is no call in it
that can create a playlist from an empty result set.

`plan` and `do` are the model-backed verbs, and `music-deck --help` says which
verbs are. Without a usable model substrate either one refuses (exit 3) naming
exactly which precondition is missing, and never falls back to a deterministic
answer. Every other verb runs with no provider at all.

## Registering your own Spotify app

music-deck ships **no credentials**. It runs under your own Spotify app, using
your own client ID, and stores only your token. Registering one takes about ten
minutes and needs a Spotify account with **Premium**.

**The steps ship inside the tool.** Run:

```
music-deck setup --guide
```

and read it: the Development Mode ceiling, creating the app, the exact redirect
URI (`http://127.0.0.1:8888`, port included, never `localhost`), copying the client ID
(never the client secret), the five-user allowlist, and signing in. It works
offline, from any install, with no checkout anywhere. Plain `music-deck setup`
gives you the shorter version — only the steps for the gap you actually have.

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
- **This tool breaches Spotify's Developer Policy §III, knowingly.** That policy
  says *"Do not ... otherwise ingest Spotify Content into a machine learning or
  AI model."* music-deck's model reads what Spotify returns, so it can correct
  its own aim rather than guess blind. §VII lets Spotify revoke platform access
  over a breach. **If you install this, that risk is yours too** — it applies to
  your own registered app and your own account. `contracts/boundary.v1.md`
  states it in its Purpose; `docs/VISION.md` records why it was accepted.
- **No credential ever reaches a model**, and every prompt sent is published
  verbatim in the result's `transcript`, so you can check both without reading
  code. Both model-backed verbs run that check over their own transcript before
  handing anything back, and refuse rather than answer if it fails.
- **`do` spends your Spotify quota, and is bounded so it cannot run away.**
  Default ceilings are 8 model turns and 40 Spotify requests; `--max-turns` and
  `--max-requests` move them. Development Mode's quota is shared and Spotify
  does not tell you what is left of it, which is why the ceilings are not
  optional.

## Model runtime for a tool install

A `uv tool install` owns its own virtualenv, and `uv pip install` cannot reach
inside it. `plan` and `do` need both a provider SDK and the amplifier-agent
engine; install both at once:

```
uv tool install --force --with anthropic --with "amplifier-agent @ git+https://github.com/microsoft/amplifier-agent@v1#subdirectory=packages/python" git+https://github.com/bkrabach/amplifier-smart-tool-music-deck
export ANTHROPIC_API_KEY=<your key>
```

`music-deck check` reports whether the complete local runtime is ready. The
refusal from `plan` or `do` names the matching command when it is not.

## Governance

Governed by `docs/VISION.md` and `contracts/` (Converge protocol).
