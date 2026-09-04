# evidence/

Everything else in this repository is proven against mocks. This folder holds
the one proof that cannot be: a real `login` -> `plan` -> `apply` -> the
playlist exists, run against a real Spotify account.

| File | What it is |
|---|---|
| `live_round_trip.py` | The script that performs the round trip and writes the record. |
| `live-round-trip-<date>.md` | The record of one run. Produced by the script, committed by the owner. |

## Why only the owner can run this

`contracts/boundary.v1.md` lists this assert and marks it *owner-only; can't
check by machine*. That is not a shortcut. The run needs four things no lane,
no CI job and no mock has:

1. A **registered Spotify app in Development Mode**, with its client id in the
   environment. music-deck ships no credential of its own — see
   `docs/spotify-app.md`.
2. A **Spotify Premium account** that owns that app and is on its allowlist.
3. A **browser**, for the one interactive step (`login`, PKCE).
4. A **model provider credential**, because `plan` is the one model-backed verb.

The script refuses to run when any of these is missing, and writes nothing. A
proof that quietly downgrades itself into a mock is worse than no proof, because
the file it leaves behind looks the same either way.

## Running it

```
uv run --extra anthropic python evidence/live_round_trip.py
```

Substitute the extra for whichever provider you use (`openai`, `gemini`,
`azure-openai`). `plan` also needs the amplifier-agent engine:

```
uv pip install "amplifier-agent @ git+https://github.com/microsoft/amplifier-agent@main"
```

Then set your own Spotify app's client id and run:

```
export MUSIC_DECK_CLIENT_ID=<your client id>     # SPOTIFY_CLIENT_ID also works
uv run --extra anthropic python evidence/live_round_trip.py
```

What happens: `check` reports the tool's state, `login` opens a browser once (it
is skipped if a valid token is already stored — pass `--force-login` to
authorise again), `plan` turns a small brief into a plan document, `apply`
carries it out, and then the playlist is **read back from Spotify** to confirm
it holds at least one item. The record lands at
`evidence/live-round-trip-<date>.md`. Commit it.

Useful flags: `--brief "<your own words>"`, `--out <path>`, `--force-login`,
`--music-deck <path to the binary>`, `--self-test`.

Exit codes: `0` the round trip passed · `1` it failed · `2` preconditions are
missing and nothing ran.

The default brief is deliberately tiny (three tracks). Development Mode's quota
is shared, undisclosed, and counted per developer account: a proof run should
cost you as little of it as possible. The playlist it creates is yours to delete
whenever you like — the evidence is the record, not the playlist.

## What the script refuses to do

Four honesty gates. Each one is a way the script can **fail**, not a way it can
pass:

1. **It never takes `apply`'s word for it.** The playlist is read back with
   `music-deck playlist items` and fewer than one item is a FAIL. An empty
   playlist cannot produce a passing record.
2. **It writes nothing for a run that did not happen.** Missing preconditions
   exit 2 with no file written.
3. **It never prints or persists a credential.** Every provider credential in
   the environment and the stored token are searched for in the document before
   it is written; a hit refuses the write. Only variable *names* are printed.
4. **It never persists fetched Spotify content.** The record carries counts, the
   plan (which by `plan.v1` Core 5 holds no Spotify content), the prompt
   transcript, and the one playlist the run created. Any other Spotify id, URI
   or link found in the document refuses the write — `boundary.v1` Core 8's line
   applied to this script's own output.

## Checking the gates without an account

```
uv run python evidence/live_round_trip.py --self-test
```

This exercises all four gates against synthetic inputs — no Spotify account, no
provider, no network. It proves the gates *refuse*: that an empty playlist
fails, that a leaked credential is caught by name and redacted, that a track URI
in the document refuses the write, and that a transcript carrying fetched
Spotify content fails `boundary.v1` Core 2 while a clean one passes.

It proves nothing whatsoever about Spotify. Only the owner's live run does that.

## What a completed record proves

- `boundary.v1` kit assert — the live round trip itself.
- `boundary.v1` Core 2 — the transcript carries no Spotify content, checked with
  `music_deck.prompt_boundary`, the same cover-based check the library runs
  against itself.
- `boundary.v1` Core 3 — the transcript is an observable output, reproduced
  verbatim.
- `cli.v1` Core 4/5/6 — one JSON document per result, and a `partial_result`
  recorded as the documented outcome it is rather than a silent truncation.
- `plan.v1` Core 7 — the per-step `requested`/`fetched`/`kept` completeness.

A record whose "How this run was made" section names something other than a real
installed `music-deck` is a rehearsal of the script, not a live round trip. The
document says so itself, at the top.
