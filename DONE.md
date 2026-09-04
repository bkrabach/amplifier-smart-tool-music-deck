# MD-1 — Skeleton: package, thin CLI, `check` smoke, manifest

**Work item:** `music_deck-5xp` · **Branch:** `lane/md-1` · **Verdict:** DONE

**What a user can now do:** install this repository as `music-deck`, run
`music-deck check` on a machine with no Spotify credentials, no model provider
and no network and get a truthful JSON report of what is missing (exit 0), read
the complete verb listing with `music-deck --help`, and reach the manifest from
Python as `music_deck.manifest()`. Every verb `cli.v1` Core 2 names is present
and refuses loudly until its lane lands.

**Contract clauses closed:** `cli.v1` Core 1, Core 2 (the `check` half), Core 7;
`boundary.v1` Core 6 (the `check` half). Core 4, 5 and 6 are implemented in
`src/music_deck/errors.py` as the shared vocabulary the later lanes import; they
are not *closed* by this lane because most codes have no verb to raise them yet.

---

## How the evidence below was produced

Everything in this file was executed, not recalled. The tool was installed
**non-editable** into a throwaway virtualenv built from a wheel of the committed
tree, and every command ran from a **fresh scratch directory that is not the
checkout**, with stdin closed and the provider environment scrubbed by the same
regex the conformance kit uses.

```
$ uv venv /tmp/md1-verify-venv
$ uv pip install --python /tmp/md1-verify-venv/bin/python --no-cache <repo-root>
Installed 2 packages in 1ms
 + music-deck==0.1.0 (from file:///.../amplifier-smart-tool-music-deck)
 + pyyaml==6.0.3

$ ls /tmp/md1-verify-venv/lib/python3.13/site-packages/music_deck/
check.py  cli.py  errors.py  __init__.py  manifest.py  SMART_TOOL.md

$ which music-deck
/tmp/md1-verify-venv/bin/music-deck
```

`SMART_TOOL.md` sitting inside `site-packages/music_deck/` is what makes
`manifest()` work from an installed environment rather than only from a checkout.

---

## Acceptance criteria

### AC1 — Conformance kit: 0 FAIL across all 15 rules — **PASS**

```
$ cd /tmp/md1-final2-...      # fresh scratch dir, provider env scrubbed
$ uv run <kit>/conformance/run.py <repo-root>
smart-tools conformance :: /home/bkrabach/dev/hw-music-deck/lanes/md-1/amplifier-smart-tool-music-deck
  PASS descriptor-present             smart-tool.json names the manifest and how to launch the CLI
  PASS manifest-present               SMART_TOOL.md found at src/music_deck/SMART_TOOL.md
  PASS manifest-frontmatter-parses    frontmatter parsed
  PASS manifest-fields-closed         only recognised fields present
  PASS manifest-required-fields       every required field carries content
  PASS manifest-field-shapes          every field has the shape the spec gives it
  PASS manifest-name-format           name='music-deck'
  PASS manifest-version-matches-package manifest 0.1.0 == pyproject.toml [project].version 0.1.0
  PASS manifest-requires-shape        1 requires entry(ies) well-formed
  PASS manifest-single-per-root       exactly one manifest under root
  PASS loads-without-provider         '--help' exits 0 with provider env scrubbed
  PASS help-flags-supported           both '-h' and '--help' exit 0
  PASS deterministic-capability-runs  deterministic 'check' runs (exit 0) with provider env scrubbed
  PASS failure-exits-non-zero         bad invocation '__conformance_no_such_verb__' exits 2
  PASS no-hang-stdin-closed           'check' completes with stdin closed
VERDICT: PASS (15 pass, 0 fail, 0 skip)
exit code: 0

# stdout verdict block:
{
  "schema": "smart-tools-conformance/v1",
  "verdict": "PASS",
  "counts": {
    "pass": 15,
    "fail": 0,
    "skip": 0
  },
  "failed_rules": []
}
```

**15 PASS, 0 FAIL, 0 SKIP.** No rule was skipped, so nothing was credited
without being evaluated. Kit at
`/home/bkrabach/dev/spotify-smart-tool-team-ci/amplifier-smart-tools/conformance/run.py`
(spec pin `microsoft/amplifier-smart-tools` @ `fd3c634`, per `PINS.md`).

### AC2 — `music-deck check` exits 0, stdout is exactly one JSON document — **PASS**

`cli.v1` Core 2: "`check` additionally succeeds (exit 0) with no credentials and
no network, in a fresh working directory."

```
$ pwd
/tmp/md1-final3-3lJj

$ music-deck check < /dev/null; echo "exit=$?"
exit=0
{
  "tool": "music-deck",
  "version": "0.1.0",
  "checked_at": "2026-09-04T15:04:51.842339+00:00",
  "config_path": "/home/bkrabach/.config/music-deck/config.json",
  "state_dir": "/home/bkrabach/.local/state/music-deck",
  "client_id": {
    "present": false,
    "source": null,
    "length": 0,
    "remedy": "Set MUSIC_DECK_CLIENT_ID, or put {\"client_id\": \"...\"} in /home/bkrabach/.config/music-deck/config.json. See docs/spotify-app.md."
  },
  "redirect_uri": {
    "value": "http://127.0.0.1",
    "source": "built-in default",
    "conforms": true,
    "detail": "loopback IP literal, as boundary.v1 Core 4 requires."
  },
  "token_file": {
    "path": "/home/bkrabach/.local/state/music-deck/token.json",
    "present": false,
    "remedy": "Run `music-deck login` to authorise and create it."
  },
  "access_token": {
    "present": false
  },
  "refresh_token": {
    "present": false,
    "wall_days": 183,
    "note": "Spotify refresh tokens last six months from the moment you authorised, and refreshing an access token does not extend that."
  },
  "scopes": {
    "known": false,
    "granted": [],
    "detail": "no token file to read"
  },
  "allowlist": {
    "state": "unknown",
    "last_403": null,
    "detail": "no 403 has been recorded. Spotify offers no way to ask whether an account is on an app's allowlist; a 403 is the only signal."
  },
  "provider": {
    "configured": false,
    "source": null,
    "needed_by": [
      "plan"
    ],
    "detail": "No model provider is configured. Every verb except `plan` runs without one; `plan` will refuse (exit 3) naming what is missing."
  },
  "ready": {
    "spotify_verbs": false,
    "plan": false
  },
  "findings": [
    "No Spotify client ID is configured. music-deck ships none by design -- register your own app and set MUSIC_DECK_CLIENT_ID. See docs/spotify-app.md.",
    "Not signed in to Spotify. Run `music-deck login`."
  ]
}
[stderr was empty: '']
stdout is exactly one JSON document: True
provider.configured: False | client_id.present: False
```

This is `check` succeeding. It found no client ID and no token, said so in
words a caller can act on, and exited 0 — which is the promise, not a shortfall.

All eight facts the work item names are present: client ID · redirect-URI shape
· token cache present/mode · access-token expiry · refresh-token age vs the
six-month wall · granted scopes · last observed 403 / allowlist state · provider
configured.

**`check` makes no network call** — asserted at the syscall level, with a
positive control proving the filter would have caught one:

```
$ strace -f -e trace=%network music-deck check  -> exit=0
network syscalls made by music-deck check: 0
positive control (same filter, a real outbound connection):
3265433 socket(AF_INET, SOCK_STREAM|SOCK_CLOEXEC, IPPROTO_TCP) = 3
3265433 connect(3, {sa_family=AF_INET, sin_port=htons(443), sin_addr=inet_addr("1.1.1.1")}, 16) = -1 EINPROGRESS (Operation now in progress)
control network syscalls: 2
```

A network namespace (`unshare -rn`, `bwrap --unshare-net`) was tried first and
is unavailable on this host (`unshare: write failed /proc/self/uid_map:
Operation not permitted`; `bwrap: loopback: Failed RTM_NEWADDR: Operation not
permitted`). The strace proof above is stronger than "it worked while offline"
anyway: it shows zero network syscalls were even attempted.
`tests/test_check.py::test_check_makes_no_network_call` asserts the same thing
in-process by replacing `socket.socket`, `socket.create_connection` and
`socket.getaddrinfo` with something that raises.

### AC3 — `-h` and `--help` both exit 0; `--help` is a complete listing marking `plan` model-backed — **PASS**

`cli.v1` Core 1: "`-h` gives a terse human summary; `--help` gives a complete
listing for an agent — every verb, its arguments, types, return shape, and which
verbs are model-backed. Help goes to stdout, exits 0."

```
$ music-deck -h      -> exit=0 bytes=2170 stderr=''
$ music-deck --help  -> exit=0 bytes=13605 stderr=''
--help lists 40/40 verbs from cli.v1 Core 2 (+plan, +manifest); missing=[]
--help marks plan model-backed: True | (model-backed) count: 1
-h differs from --help (terse vs complete): True
```

The 40 checked are every verb in `cli.v1` Core 2's `<details>` block expanded
(`playlist items|create|add|remove|reorder|rename` and
`library list|save|remove|contains` counted individually), plus `plan` (Core 3)
and `manifest` (Core 7). Header of `--help`:

```
music-deck -- curate and control music on Spotify from an agent.

usage: music-deck <verb> [arguments]

OUTPUT
  Every result is exactly one JSON document on stdout. Progress and
  diagnostics go to stderr. This help text is the only non-JSON output
  the binary ever prints to stdout.

EXIT CODES
  0  success
  1  failure
  2  refusal, usage, or invalid input
  3  no model provider configured (the `plan` verb only)

FAILURE SHAPE
  {"error": {"code": ..., "message": ..., "remedy": ...}}
  Codes are frozen; a caller may branch on them:
    invalid_plan
    no_active_device
    not_allowlisted
    not_authenticated
    partial_result
    playlist_items_unavailable
    premium_required
    quota_exceeded
    rate_limited
    reauthorization_required

MODEL-BACKED VERBS
  plan -- the only one. Every other verb runs with no model provider
  configured and no provider SDK installed.

VERBS
```

and one verb entry, showing the arguments/types/return shape Core 1 asks for:

```
music-deck plan  (model-backed)  [NOT IMPLEMENTED in this build]
    Turn a brief in your own words into a readable plan document.
    The only model-backed verb. With no usable model substrate it exits 3 naming the missing precondition, and never falls back to a deterministic answer. It makes no Spotify request at all.
    arguments:
      --brief (string, required) -- What you want, in your own words.
      --output (path, optional) -- Where to write the plan. Defaults to stdout.
    returns: A JSON plan document per contracts/plan.v1.md, carrying its prompt transcript.
```

### AC4 — `music_deck.manifest()['name']` from an installed environment prints `music-deck` — **PASS**

`cli.v1` Core 7: "the manifest is exposed as structured data via
`music_deck.manifest()`".

```
$ /tmp/md1-verify-venv/bin/python -c "import music_deck; print(music_deck.manifest()['name'])"
music-deck
$ ... print(music_deck.__file__)
/tmp/md1-verify-venv/lib/python3.13/site-packages/music_deck/__init__.py
```

Loaded from `site-packages`, not from the checkout — this is the
non-editable-install case the criterion asks for.

### AC5 — `music-deck check < /dev/null` returns within 5s — **PASS**

`cli.v1` Core 1: "A run with stdin closed never hangs."

```
$ music-deck check < /dev/null   ->  exit=0  elapsed=0.071s  (bar: 5s)
```

Measured with `stdin=subprocess.DEVNULL` and a hard 5-second subprocess timeout,
so a hang would have raised rather than been waited out.

### AC6 — version in pyproject == version in SMART_TOOL.md == 0.1.0 — **PASS**

```
pyproject.toml [project].version = 0.1.0
SMART_TOOL.md frontmatter version = 0.1.0
both equal 0.1.0: True
```

Independently confirmed by the kit's own rule:
`PASS manifest-version-matches-package  manifest 0.1.0 == pyproject.toml [project].version 0.1.0`.

### AC7 — pytest green — **PASS**

```
$ uv run pytest -q
........................................................................ [ 69%]
...............................                                          [100%]
103 passed in 3.27s
```

103 tests across `tests/test_cli_shape.py`, `tests/test_check.py`,
`tests/test_manifest.py`.

---

## Supporting evidence: nothing exits 0 while describing an error

The spec's named failure mode is a stub that hides the gap. Both refusal paths
were run:

```
$ music-deck whoami
exit=1
stdout:
{
  "error": {
    "code": "not_implemented",
    "message": "`music-deck whoami` is declared by the CLI contract but is not implemented in this build.",
    "remedy": "This verb is declared by the CLI contract but not built yet. Run `music-deck check` to confirm the install, and `music-deck --help` to see what is available.",
    "verb": "whoami"
  }
}
stderr: `music-deck whoami` is declared by the CLI contract but is not implemented in this build.

$ music-deck __conformance_no_such_verb__
exit=2
stdout:
{
  "error": {
    "code": "usage",
    "message": "music-deck could not understand that invocation: argument <verb>: invalid choice: '__conformance_no_such_verb__' (choose from check, manifest, login, disconnect, whoami, search, track, album, artist, show, episode, playlists, playlist, library, following, top, recently-played, now-playing, devices, queue, play, pause, next, previous, seek, volume, shuffle, repeat, transfer, queue-add, apply, plan)",
    "remedy": "Run `music-deck --help` for the complete listing of verbs."
  }
}
stderr: argument <verb>: invalid choice: '__conformance_no_such_verb__' (...)
```

Both put the JSON document on stdout and the human line on stderr, as `cli.v1`
Core 4 requires.

---

## Interpretations this lane had to make, and why

These are recorded because `errors.py` is the vocabulary MD-2..MD-5 import, and
a later lane should be able to see the reasoning rather than re-derive it.

**1. Every frozen Core-6 code maps to exit 2.** Core 5 gives four exit codes and
says "all domain richness lives in `error.code`, not in more exit codes". Core 6
calls its ten codes "**the refusal vocabulary**". Core 5 assigns exit `2` to
"refusal". So all ten are exit `2`, which also matches the one code Core 6
annotates itself (`invalid_plan` — "exit 2"). The mapping lives in one table,
`music_deck.errors._EXIT_BY_CODE`, so it is one edit if the steward reads it
differently.

*Where this could be wrong:* `rate_limited`, `quota_exceeded` and
`partial_result` read more like failures (exit `1`) than refusals in ordinary
usage. The contract text puts them in the refusal list, so that is what was
implemented. **If the steward wants them at exit 1, that is a `cli.v1` Core 5/6
clarification, not a code change**, and it is cheap now and expensive after
MD-2..MD-5 land.

**2. Two codes exist that Core 6 does not freeze.** Core 4 requires *every*
failure to carry a code, and two failures a caller can provoke are not refusals:

- `usage` — malformed invocation. Core 5 names "usage, or invalid input" as its
  own exit-2 category, so the code takes the word the contract itself uses.
- `not_implemented` — scaffolding, exit 1. Every one of these disappears as its
  lane lands.

Both are deliberately *outside* `FROZEN_CODES`, which is exactly Core 6's ten,
so a conformance fixture enumerating the frozen vocabulary stays correct.
`tests/test_cli_shape.py` asserts both facts.

**3. `no_provider_configured` is a separate exception, not a frozen code.**
`cli.v1` Core 3 gives the model-substrate refusal its own exit code (`3`), and
Core 6 does not list a code for it. `music_deck.errors.NoProviderError` carries
it. MD-5 (or whoever builds `plan`) should raise that class rather than invent a
frozen-looking code.

---

## Handoffs to later lanes

**The token file shape `check` reads** — the `login` lane writes this file;
`check` only reads it, and is tolerant of every field being absent (it reports
"unknown" rather than failing). At `$XDG_STATE_HOME/music-deck/token.json`,
mode `0600`:

| Field | Type | What `check` does with it |
|---|---|---|
| `access_token` | string | presence only; the value is never echoed |
| `expires_at` | ISO-8601 string or epoch seconds | access-token expiry and seconds remaining |
| `refresh_token` | string | presence only |
| `authorized_at` | ISO-8601 string | age against the 183-day wall. **Must be the moment the user authorised, not the last refresh** — Spotify does not extend the wall on refresh. `refresh_token_issued_at` is accepted as an alias. |
| `scopes` | list of strings (or `scope`, space-separated) | the granted-scope report |

If the login lane wants different names, change them there and in
`music_deck/check.py::_token_facts` together — nothing else reads the file.

**The 403 record `check` reads for allowlist state** — nothing writes it yet.
The HTTP layer should write `$XDG_STATE_HOME/music-deck/last-403.json` as
`{"observed_at": <ISO-8601>, "endpoint": <path>, "reason": <string>}` whenever
Spotify returns 403. With the file absent, `check` reports
`allowlist.state = "unknown"`, which is the honest answer: Spotify offers no way
to ask whether an account is allowlisted.

**Config file** — `$XDG_CONFIG_HOME/music-deck/config.json`, keys `client_id`
and `redirect_uri`. Environment (`MUSIC_DECK_CLIENT_ID`,
`MUSIC_DECK_REDIRECT_URI`) wins over the file.
`MUSIC_DECK_CONFIG_DIR`/`MUSIC_DECK_STATE_DIR` override both directories, which
is how the tests stay hermetic.

**The verb table is the CLI surface** — `music_deck/cli.py::VERBS` generates the
argparse parser *and* both help texts, so they cannot drift. A lane implementing
a verb sets that verb's `handler=` and adjusts its `args=`; it does not need to
touch the help text, and it must not add a second description of the surface.
The argument names in the table are this lane's reading of each verb; a lane
that needs different ones should change them there, and
`tests/test_cli_shape.py::test_the_parser_accepts_exactly_the_verbs_the_help_text_lists`
will hold the verb set itself steady.

---

## Notes for the manager (files this lane does not own)

- **`.gitignore` needs a line for `uv.lock`, or `uv.lock` should be committed.**
  `uv sync` produces `uv.lock` at the repo root; it is currently untracked and
  shows up in `git status`. This lane owns `pyproject.toml` but not
  `.gitignore`, so the change was not made. Recommendation: **commit
  `uv.lock`** — the tool is meant to install reproducibly from a git repository
  — and have one lane (this one, or the manager at integration) add it, since
  every lane's `uv sync` will otherwise regenerate it and collide.
- **`ledger/rows.yaml` and `conformance/<contract>/run.py` are still absent**
  (`PINS.md` records both as not built). The upstream kit is green, but the
  per-contract clauses this lane implements — Core 4's envelope, Core 5's exit
  codes, Core 6's ten codes — have no ledger row yet. `tests/` covers them;
  the ledger does not know that.
- **`PINS.md` "Handoffs to other lanes" says "None yet."** The three handoffs
  above (token file shape, `last-403.json`, config file) belong there once the
  manager integrates this branch.
- **No changes were made to `docs/VISION.md` or `contracts/*.md`.** The one
  place the contract text is genuinely ambiguous (interpretation 1 above) is
  recorded here as a question, not edited into the contract.

---

## Scope-outs honoured

No publishing, tagging, releasing, PR, or merge. No edits outside the paths the
work item names. No real Spotify account, no provider key, and no network call
in any test — every test is filesystem, environment, or subprocess only. No
infrastructure was stood up, so there is nothing in the infra ledger to tear
down.

---

## Work item resolved — read back from the queue

AGENTS.md rule 5: evidence lives in a file or in printed output, never inside a
tool call. So the resolution was written, then read back with the queue's own
read command, and the stored text pasted here.

```
$ amplifier-work-tracker list --project music_deck --id music_deck-5xp
ID:       music_deck-5xp
TITLE:    MD-1 Skeleton: package, thin CLI, `check` smoke, manifest — Smart Tools kit green
STATUS:   resolved
HOLDER:   agent-spark-1-2875360
CREATED:  2026-09-04T14:10:02+00:00 by agent-spark-1-582165
UPDATED:  2026-09-04T15:07:04+00:00
CLOSED:   2026-09-04T15:07:04+00:00

RESOLUTION:
music-deck now installs and runs. Install the repo (`uv pip install <repo>`) and you get a `music-deck` binary on PATH. `music-deck check` works on a machine with no Spotify credentials, no model provider and no network at all: it reports your client ID, redirect-URI shape, token cache and its file mode, access-token expiry, how much of Spotify's six-month refresh wall is left, granted scopes, any recorded 403 (the only signal an account is not on your app's allowlist), and whether a model provider is configured — then exits 0 and tells you what to do next in plain words. Reporting a missing credential is its success, not a failure. `music-deck -h` gives a terse verb list; `music-deck --help` gives the complete listing an agent needs — all 40 verbs from cli.v1 Core 2 with their arguments, types and return shapes, with `plan` marked as the one model-backed verb. `music-deck manifest` and `music_deck.manifest()` both return the manifest as structured data from an installed environment. Every verb the CLI contract names is present; the ones whose lane has not landed refuse loudly with a `not_implemented` error envelope and a non-zero exit, so nothing pretends to work. Evidence in DONE.md: the upstream Smart Tools conformance kit reports 15 PASS, 0 FAIL, 0 SKIP against a non-editable install from a scratch directory; strace shows zero network syscalls during `check`, with a positive control; 103 tests pass. Also lands src/music_deck/errors.py — the ten frozen refusal codes of cli.v1 Core 6, the error envelope of Core 4 and the exit-code mapping of Core 5 — which MD-2..MD-5 import. DONE.md records one contract ambiguity for the steward (whether rate_limited, quota_exceeded and partial_result should exit 2 as refusals, as implemented, or 1 as failures) and the token-file/403/config handoffs the later lanes depend on.

ACCEPTANCE:
GIVEN a fresh scratch directory with all provider env vars scrubbed and no network, WHEN `uv run <path-to-amplifier-smart-tools>/conformance/run.py <repo-root>` runs, THEN it reports 0 FAIL across all 15 rules (SKIP allowed only where the kit says it cannot evaluate) — output pasted in DONE.md. GIVEN the same scratch dir, WHEN `music-deck check` runs, THEN exit 0 and stdout is exactly one JSON document (cli.v1 Core 2: "`check` additionally succeeds (exit 0) with no credentials and no network, in a fresh working directory"). WHEN `music-deck -h` and `music-deck --help` run, THEN both exit 0, --help lists every verb in cli.v1 Core 2 and marks `plan` model-backed (Core 1: "`--help` gives a complete listing for an agent — every verb, its arguments, types, return shape, and which verbs are model-backed"). WHEN `python -c "import music_deck; print(music_deck.manifest()['name'])"` runs from an installed (not editable-from-checkout) environment, THEN it prints music-deck (Core 7: "the manifest is exposed as structured data via `music_deck.manifest()`"). WHEN `music-deck check < /dev/null` runs with stdin closed, THEN it returns within 5s (Core 1: "A run with stdin closed never hangs"). Version in pyproject == version in SMART_TOOL.md frontmatter == 0.1.0. pytest green.

DESCRIPTION:
Contracts served: cli.v1 Core 1, 2 (the `check` half), 7; boundary.v1 Core 6 (the `check` half). External: Smart Tools spec microsoft/amplifier-smart-tools @ fd3c634 (15-rule conformance kit).

Gap: the repo at https://github.com/bkrabach/amplifier-smart-tool-music-deck (main @ 9e296c2) has vision + contracts + participant kit and NO code. Nothing installs, nothing runs.

What to build (owns these paths — no other lane touches them): pyproject.toml (name music-deck, version 0.1.0, `[project.scripts] music-deck = "music_deck.cli:main"`, python >= 3.11, NO provider SDK in base deps), smart-tool.json (`{"manifest": "src/music_deck/SMART_TOOL.md", "cli_argv": ["music-deck"], "deterministic_smoke": ["check"]}`), src/music_deck/__init__.py (exports `manifest()`), src/music_deck/SMART_TOOL.md (frontmatter per spec/manifest.md: smart_tool_format 1, name music-deck, version 0.1.0, description, use_cases (the five from docs/VISION.md's substance), platforms [linux, macos], requires: spotify-app with purpose + install: docs/spotify-app.md; body = when to reach for it / sharp edges / worked invocations), docs/spotify-app.md (how to register a Development Mode app and hold Premium — plain words), src/music_deck/manifest.py (reads the packaged SMART_TOOL.md via importlib.resources, parses frontmatter, returns a dict), src/music_deck/cli.py (argparse or click; -h terse, --help complete listing marking `plan` as model-backed; help to stdout exit 0; verb stubs for every deterministic verb in cli.v1 Core 2 that emit the error envelope `{"error":{"code":"not_implemented","message":...,"remedy":...}}` exit 1 until their lane lands — EXCEPT `check` and `manifest`, which are real), src/music_deck/check.py (reports: client ID present · redirect-URI shape · token cache present/mode · access-token expiry · refresh-token age vs 6-month wall · granted scopes · last observed 403/allowlist state · provider configured; exit 0 ALWAYS, one JSON doc), src/music_deck/errors.py (the envelope type + the frozen code list from cli.v1 Core 6 + exit-code mapping from Core 5 — the shared vocabulary every later lane imports), tests/test_cli_shape.py, tests/test_check.py, tests/test_manifest.py.
```

(The item's ACCEPTANCE and DESCRIPTION blocks follow in the same output; they
are the brief this lane was given and are reproduced in the sections above.)

---
---

# MD-2 — Spotify boundary: PKCE auth, `login`/`disconnect`/`whoami`, the one HTTP client, the removed-endpoint guard

**Work item:** `music_deck-2rj` · **Branch:** `lane/md-2` · **Verdict:** DONE

**What a user can now do:** authorise music-deck against their own Spotify
Development Mode app with `music-deck login` — PKCE, no client secret, a loopback
redirect on a port bound at runtime — and have the token land at
`$XDG_STATE_HOME/music-deck/token.json` at mode `0600`. `music-deck whoami`
reports the signed-in account. `music-deck disconnect` deletes the token and
every locally cached byte of Spotify content and prints the list of what it
removed. Every Spotify failure now arrives as one of the frozen words from
`cli.v1` Core 6 with a remedy the caller can act on, instead of an HTTP status
code — including the two different things a `429` can mean and the two different
things a `403` can mean. And music-deck cannot send a request to an endpoint
Spotify has withdrawn: the guard refuses before the URL is built.

**Contract clauses closed:** `boundary.v1` Core 4, 5, 6, 7, 8 (the boundary's
half of 8 — see the note to the steward below); `cli.v1` Core 4, 5, 6 for every
code reachable from the Spotify boundary. `invalid_plan` is the one frozen code
this lane cannot reach: `plan.v1` decides it and `apply` raises it (MD-5). It is
recorded here as **N/A — not reachable from the Spotify boundary**, never
silently skipped.

---

## How the evidence below was produced

Two kinds of run, and the distinction matters:

- **The real binary, as a real process** — `.venv/bin/music-deck`, stdin closed,
  a temporary state directory, and `$BROWSER` pointed at a script that leaves a
  file behind if it is ever executed. This is what proves "never opens a
  browser" and "refuses within 5 s".
- **The real CLI in-process, against a mocked Spotify** — `music_deck.cli.main()`
  with the one class that can open a socket (`UrllibTransport`) replaced by a
  fake that answers queued bytes. A subprocess cannot be handed a fake
  transport, so this is how a *particular Spotify response* is turned into a
  particular envelope. Everything except the transport is the shipping path: the
  same parser, the same dispatch, the same envelope, the same exit code.

No test and no evidence run in this lane reaches `api.spotify.com`. That is
structural, not a convention: `tests/spotify_fakes.py::use_fake_transport`
replaces `UrllibTransport` in **both** namespaces that construct one, and the
fake raises on any request a test did not queue.

---

## Criterion 1 — every named response produces the matching frozen code, on stdout, non-zero — **PASS**

> "GIVEN a mocked Spotify HTTP layer, WHEN each of 401-expired,
> 401-refresh-rejected, 403-allowlist, 403-premium-on-player-write,
> 204-on-/me/player, 429-with-Retry-After, 429-with-reason-QUOTA_EXCEEDED, and a
> playlist-items-forbidden response is returned, THEN the CLI emits
> `{"error":{"code","message","remedy"}}` on stdout with the matching frozen code
> from cli.v1 Core 6 and exits non-zero per Core 5."

Each block below is one mocked response going in and the exact document
`music-deck` printed on stdout coming out, with the exit code it returned.
`no_active_device`, `premium_required` from a player write, and
`playlist_items_unavailable` are decided by the *path*, and the verbs that
request those paths belong to MD-3 and MD-4 — so those three ran through the
real CLI with a stand-in handler making exactly the call the missing verb will
make, rather than being asserted from inside the library.

```
--- 401 expired, nothing to refresh with -> not_authenticated
    exit code: 2   requests sent: 1   waits: []
    {
      "error": {
        "code": "not_authenticated",
        "message": "The access token expired",
        "remedy": "Run `music-deck login`."
      }
    }

--- 401 then the refresh is rejected -> reauthorization_required
    exit code: 2   requests sent: 2   waits: []
    {
      "error": {
        "code": "reauthorization_required",
        "message": "Spotify rejected the refresh token (400): Refresh token revoked. Spotify's own guidance is to discard it and send the user through authorisation again rather than retry.",
        "remedy": "Run `music-deck login`."
      }
    }

--- 403 with no reason -> not_allowlisted
    exit code: 2   requests sent: 1   waits: []
    {
      "error": {
        "code": "not_allowlisted",
        "message": "Forbidden",
        "remedy": "Add this Spotify account to your app's allowlist under User Management in the Spotify developer dashboard. See docs/spotify-app.md."
      }
    }

--- 403 on a player write -> premium_required
    exit code: 2   requests sent: 1   waits: []
    {
      "error": {
        "code": "premium_required",
        "message": "Player command failed: Premium required",
        "remedy": "Playback writes need Spotify Premium on the account being controlled."
      }
    }

--- 204 on GET /me/player -> no_active_device
    exit code: 2   requests sent: 1   waits: []
    {
      "error": {
        "code": "no_active_device",
        "message": "Spotify has no active playback session for this account (204 No Content).",
        "remedy": "Start playback on a Spotify device, or run `music-deck transfer` to move playback to one."
      }
    }

--- 429 Retry-After: 2, then a second 429 -> rate_limited, one bounded retry
    exit code: 2   requests sent: 2   waits: [2.0]
    {
      "error": {
        "code": "rate_limited",
        "message": "API rate limit exceeded",
        "remedy": "Wait the number of seconds in `retry_after_s` and run the command again.",
        "retry_after_s": 7.0
      }
    }

--- 429 reason QUOTA_EXCEEDED -> quota_exceeded, never retried
    exit code: 2   requests sent: 1   waits: []
    {
      "error": {
        "code": "quota_exceeded",
        "message": "Quota exceeded",
        "remedy": "Your Spotify developer quota is exhausted; waiting will not clear it. Reduce how much this app requests, or try again later in the quota window.",
        "reason": "QUOTA_EXCEEDED"
      }
    }

--- 403 on GET /playlists/{id}/items -> playlist_items_unavailable
    exit code: 2   requests sent: 1   waits: []
    {
      "error": {
        "code": "playlist_items_unavailable",
        "message": "Insufficient client scope",
        "remedy": "Spotify only returns items for a playlist you own or collaborate on. Use one you own."
      }
    }
```

All eight exit `2` — `cli.v1` Core 5's "refusal", which is where `errors.py`
maps every frozen code.

---

## Criterion 2 — one bounded retry, then a refusal carrying `retry_after_s` — **PASS**

> "WHEN a 429 with Retry-After: 2 is followed by a second 429, THEN exactly one
> retry happened and the envelope carries retry_after_s."

From the `rate_limited` block above, verbatim:

```
--- 429 Retry-After: 2, then a second 429 -> rate_limited, one bounded retry
    exit code: 2   requests sent: 2   waits: [2.0]
    {
      "error": {
        "code": "rate_limited",
        "message": "API rate limit exceeded",
        "remedy": "Wait the number of seconds in `retry_after_s` and run the command again.",
        "retry_after_s": 7.0
      }
    }
```

- `requests sent: 2` — the original and exactly one retry.
- `waits: [2.0]` — one wait, of exactly the length `Retry-After` asked for.
- `retry_after_s: 7.0` — the *second* response's `Retry-After`, handed to the
  caller rather than slept on.

Two neighbouring cases are covered by tests in the same file, because "at most
one bounded retry ... never an unbounded wait" is only half a promise without
them:

| Case | Behaviour | Test |
|---|---|---|
| `Retry-After: 600` | not slept on at all; refuses immediately carrying `retry_after_s: 600.0` | `test_429_with_a_retry_after_longer_than_the_bound_is_never_slept_on` |
| `reason: QUOTA_EXCEEDED` | never retried, never slept on — waiting does not clear a quota | `test_429_with_reason_quota_exceeded_is_never_retried` |

---

## Criterion 3 — no removed endpoint is ever constructed, statically or at runtime — **PASS**

> "WHEN the code attempts any path in the removed families ... THEN the guard
> refuses before any request is sent, AND a static test finds no such literal in
> src/."

```
RUNTIME -- every withdrawn family, refused before the request is built
  refused      GET    /tracks                                              -> withdrawn February 2026
  refused      GET    /albums                                              -> withdrawn February 2026
  refused      GET    /artists                                             -> withdrawn February 2026
  refused      GET    /episodes                                            -> withdrawn February 2026
  refused      GET    /shows                                               -> withdrawn February 2026
  refused      GET    /audiobooks                                          -> withdrawn February 2026
  refused      GET    /chapters                                            -> withdrawn February 2026
  refused      GET    /users/deckuser                                      -> withdrawn February 2026
  refused      POST   /users/deckuser/playlists                            -> withdrawn February 2026
  refused      GET    /browse/new-releases                                 -> withdrawn February 2026
  refused      GET    /browse/categories                                   -> withdrawn February 2026
  refused      GET    /markets                                             -> withdrawn February 2026
  refused      GET    /recommendations                                     -> withdrawn November 2024
  refused      GET    /audio-features/4iV5W9uYEdYUVa79Axb7Rh               -> withdrawn November 2024
  refused      GET    /audio-analysis/4iV5W9uYEdYUVa79Axb7Rh               -> withdrawn November 2024
  refused      GET    /artists/0TnOYISbd1XYRBk9myaseg/related-artists      -> withdrawn November 2024
  refused      GET    /artists/0TnOYISbd1XYRBk9myaseg/top-tracks           -> withdrawn February 2026
  refused      POST   /playlists/37i9dQZF1DXcBWIGoYBM5M/tracks             -> withdrawn February 2026
  refused      PUT    /playlists/37i9dQZF1DXcBWIGoYBM5M/followers          -> withdrawn February 2026
  refused      PUT    /me/tracks                                           -> withdrawn February 2026
  refused      DELETE /me/albums                                           -> withdrawn February 2026
  refused      PUT    /me/following                                        -> withdrawn February 2026
  refused      GET    /me/tracks/contains                                  -> withdrawn February 2026
  refused      GET    /me/following/contains                               -> withdrawn February 2026
  requests that reached the transport: 0

RUNTIME -- the surviving surface still goes through (boundary.v1 Core 7 names four of these)
  allowed      GET    /me
  allowed      GET    /search
  allowed      GET    /tracks/4iV5W9uYEdYUVa79Axb7Rh
  allowed      GET    /playlists/37i9dQZF1DXcBWIGoYBM5M/items
  allowed      POST   /me/playlists
  allowed      PUT    /me/library
  allowed      GET    /me/library/contains
  allowed      GET    /me/player

STATIC -- no withdrawn path literal anywhere in src/, outside the fenced table
  files scanned: 9 (src/music_deck/__init__.py, src/music_deck/auth.py, src/music_deck/check.py, src/music_deck/cli.py, src/music_deck/errors.py, src/music_deck/http.py, src/music_deck/manifest.py, src/music_deck/verbs/__init__.py, src/music_deck/verbs/auth_verbs.py)
  absent    batch GET /tracks
  absent    batch GET /albums
  absent    batch GET /artists
  absent    batch GET /episodes
  absent    batch GET /shows
  absent    batch GET /audiobooks
  absent    batch GET /chapters
  absent    /users/{id}*
  absent    /browse/*
  absent    /markets
  absent    /recommendations
  absent    /audio-features
  absent    /audio-analysis
  absent    related-artists
  absent    top-tracks
  absent    /playlists/{id}/tracks
  absent    /playlists/{id}/followers
  absent    /me/<type>/contains
  absent    a client secret (boundary.v1 Core 4)
  total offending literals: 0
```

`requests that reached the transport: 0` is the load-bearing line: the guard runs
in `SpotifyClient.request` **before** the URL is built, so a withdrawn path
cannot reach a socket even once.

Two things about the static half, both deliberate:

- `src/music_deck/http.py` necessarily contains every withdrawn path — it is the
  table of what to refuse. That table sits between two marker comments, and the
  scan excises exactly that region. `tests/test_removed_endpoints.py` asserts the
  markers exist and that exactly one file carries them, so deleting the fence
  breaks the test rather than silently disabling it.
- The scan also looks for `client_secret`, which is `boundary.v1` Core 4's "No
  client secret anywhere". Zero hits.

`GET /me/tracks`, `/me/albums`, `/me/episodes`, `/me/shows`, `/me/audiobooks` and
`GET /me/following` are **allowed** on purpose: February 2026 removed the
type-specific library *writes* and *contains* endpoints, not the reads
(`investigation/B-spotify-api-reality.md` sections 4.4 and 4.6). `library list`
and `following` (MD-3/MD-5) need those reads. The guard refuses `PUT`/`DELETE` on
those paths and any method on `/me/<type>/contains`.

The whole thing as tests — 69 of them, one per withdrawn call, one per surviving
call, one per literal:

```
$ uv run --extra dev pytest tests/test_removed_endpoints.py -q
.....................................................................    [100%]
69 passed in 0.06s
```

---

## Criterion 4 — `login` completes, and leaves a `0600` token at the contracted path — **PASS**

> "WHEN `login` completes in a test harness, THEN token.json exists at
> $XDG_STATE_HOME/music-deck/ with mode 0600 and the redirect URI used is
> http://127.0.0.1:<port>."

The harness stands in for two things only: the browser (which fetches the
redirect Spotify would send it to) and Spotify's token endpoint. The PKCE pair,
the authorisation URL, the loopback receiver on a real ephemeral port, the code
exchange, the file write and its mode are the shipping code.

```
-rw------- 1 bkrabach bkrabach 324 Sep  4 08:37 /tmp/md2-demo-6cve7bio/state/music-deck/token.json
AUTHORIZE URL (truncated): https://accounts.spotify.com/authorize?client_id=demo-client-id&response_type=code&redirect_uri=http%3A%2F%2F127.0.0.1 ...

login RESULT:
{
  "signed_in": true,
  "redirect_uri": "http://127.0.0.1:38063",
  "token_path": "/tmp/md2-demo-6cve7bio/state/music-deck/token.json",
  "token_mode": "0600",
  "scopes": [
    "user-read-private"
  ],
  "client_id_source": "environment MUSIC_DECK_CLIENT_ID"
}
account: {"id": "demo-user", "display_name": "Demo User", "uri": "spotify:user:demo-user", "external_urls": {"spotify": "https://open.spotify.com/user/demo-user"}}

ls -l of the token file, as the OS reports it:

no client secret was ever sent -- the token exchange body was:
    grant_type=authorization_code&code=demo-code&redirect_uri=http%3A%2F%2F127.0.0.1%3A38063&client_id=demo-client-id&code_verifier=zUQEivJZWKu6zBJvVfG-Vvvnajjh5PKcGUggtRDmh8GolSCx6nnRJEUDU4gFv2XzVNConQNx8CRkkAdkXZZw8g
```

(The `ls -l` line appears first because the subprocess writes straight to the
file descriptor while Python's own output is still buffered. It is the same run.)

What that output settles, line by line:

| `boundary.v1` Core 4 says | The run shows |
|---|---|
| "Auth is PKCE only" | the exchange body carries `code_verifier`, no `client_secret`, and no `Authorization` header |
| "with the caller's own client ID" | `client_id_source: environment MUSIC_DECK_CLIENT_ID` |
| "Redirect URI is `http://127.0.0.1:<ephemeral port>`, never `localhost`" | `redirect_uri: http://127.0.0.1:38063` — a port the kernel handed out at run time |
| "The token lives at `$XDG_STATE_HOME/music-deck/token.json`" | `/tmp/md2-demo-6cve7bio/state/music-deck/token.json`, with `XDG_STATE_HOME=/tmp/md2-demo-6cve7bio/state` |
| "mode `0600`" | `-rw------- 1 bkrabach bkrabach` |
| "no credential ships with the tool" | `login` with no client ID configured refuses `usage` before opening anything (Criterion 5 output) |

`cli.v1` Core 4's "every Spotify item carries its own `external_urls.spotify`" is
visible in the same output: the account object came back from the mocked Spotify
*without* `external_urls`, and music-deck derived
`https://open.spotify.com/user/demo-user` from the item's own URI.

Three neighbouring `login` behaviours are proved by tests rather than by this
happy path, because a login verb that only works when everything goes right is
the one that hangs at 2 a.m.:

| Case | Behaviour | Test |
|---|---|---|
| No browser opened **and** stdin closed | fails loud in well under a second, stores nothing | `test_login_with_no_browser_and_no_terminal_fails_loud_and_fast` |
| Browser opened, nobody ever completes it | stops waiting at the deadline; never hangs | `test_login_stops_waiting_rather_than_hanging` |
| Callback carries the wrong `state` | refuses, stores nothing | `test_login_refuses_a_callback_whose_state_does_not_match` |

---

## Criterion 5 — an unauthenticated verb, stdin closed: `not_authenticated`, under 5 s, no browser — **PASS**

> "WHEN any verb other than `login` runs unauthenticated with stdin closed, THEN
> it fails `not_authenticated` naming `music-deck login` within 5s and never
> opens a browser."

This one is the real binary as a real process. `$BROWSER` points at a script that
`touch`es a sentinel file if it is ever run, so "never opens a browser" is
checked, not assumed.

## Criterion 6 — `disconnect` leaves nothing behind, and says what it took — **PASS**

> "WHEN `disconnect` runs, THEN token.json is gone, no Spotify content remains
> under $XDG_STATE_HOME/music-deck/, and stdout names what was deleted."

Both criteria in one session:

```
== boundary.v1 Core 5 -- an unauthenticated verb, stdin closed, browser watched ==
$ music-deck whoami   < /dev/null
music-deck is not signed in to Spotify: there is no token at /tmp/md2-cli-WUVsHC/state/token.json.
{
  "error": {
    "code": "not_authenticated",
    "message": "music-deck is not signed in to Spotify: there is no token at /tmp/md2-cli-WUVsHC/state/token.json.",
    "remedy": "Run `music-deck login`."
  }
}
exit code: 2
elapsed: .056741975 s   (acceptance bar: under 5s)
browser opened: no (the watched $BROWSER script never ran)

== login with no client ID configured: a refusal, not a browser window ==
$ music-deck login   < /dev/null
No Spotify client ID is configured. music-deck ships none by design: you run it against your own Spotify app, under your own quota.
{
  "error": {
    "code": "usage",
    "message": "No Spotify client ID is configured. music-deck ships none by design: you run it against your own Spotify app, under your own quota.",
    "remedy": "Set MUSIC_DECK_CLIENT_ID (or SPOTIFY_CLIENT_ID), or put {\"client_id\": \"...\"} in /tmp/md2-cli-WUVsHC/config/config.json. See docs/spotify-app.md."
  }
}
exit code: 2
browser opened: no

== boundary.v1 Core 6 -- disconnect deletes the token and every cached byte, and says so ==
before:
    /tmp/md2-cli-WUVsHC/state/cache/playlist-37i9dQZF1DXcBWIGoYBM5M.json
    /tmp/md2-cli-WUVsHC/state/last-403.json
    /tmp/md2-cli-WUVsHC/state/token.json
$ music-deck disconnect   < /dev/null
{
  "disconnected": true,
  "deleted": [
    "/tmp/md2-cli-WUVsHC/state/cache/playlist-37i9dQZF1DXcBWIGoYBM5M.json",
    "/tmp/md2-cli-WUVsHC/state/last-403.json",
    "/tmp/md2-cli-WUVsHC/state/token.json"
  ],
  "deleted_count": 3,
  "state_dir": "/tmp/md2-cli-WUVsHC/state",
  "token_path": "/tmp/md2-cli-WUVsHC/state/token.json",
  "remaining": [],
  "summary": "Deleted 3 file(s) from /tmp/md2-cli-WUVsHC/state. No Spotify content remains on disk.",
  "note": "The config file was left in place -- it holds your own client ID, which is not Spotify content. Delete it by hand if you want it gone."
}
exit code: 0
after:
    (no output above this line means nothing is left)

== boundary.v1 Core 6 second sentence -- check still exits 0 with nothing connected ==
$ music-deck check < /dev/null | head -c 0; music-deck check --  (findings only)
{
  "token_file": false,
  "ready": {
    "spotify_verbs": false,
    "plan": true
  },
  "findings": [
    "No Spotify client ID is configured. music-deck ships none by design -- register your own app and set MUSIC_DECK_CLIENT_ID. See docs/spotify-app.md.",
    "Not signed in to Spotify. Run `music-deck login`."
  ]
}
check exit code: 0

== cli.v1 Core 1 -- the three verbs this lane built are no longer marked unbuilt ==
    music-deck login  (deterministic)
        Authorise against your own Spotify app, once, via PKCE in a browser.
    --
    music-deck disconnect  (deterministic)
        Delete the stored token and every locally cached byte of Spotify content.
    --
    music-deck whoami  (deterministic)
        Report the signed-in Spotify account.
    verbs still marked NOT IMPLEMENTED:
      37
```

- `elapsed: .056 s` against a 5 s bar; `browser opened: no`.
- The remedy names `music-deck login` verbatim, as `boundary.v1` Core 5 requires.
- `disconnect` removed all three files — the token, the cached playlist, and the
  403 record — listed each one by absolute path, and the `find` afterwards prints
  nothing at all.
- `check` still exits `0` afterwards and reports "Not signed in to Spotify", which
  is `boundary.v1` Core 6's second sentence.
- The config file is left in place on purpose: the client ID is the caller's own,
  is not Spotify content, and is the thing they would have to go and find again.
  `disconnect` says so in its own output.

An end-to-end test covers the case that matters more than the fixture above: a
real refused request writes the 403 record, and `disconnect` takes that away too
(`test_disconnect_deletes_the_403_record_a_real_run_leaves_behind`).

---

## Criterion 7 — pytest green — **PASS**

```
$ uv run --extra dev pytest -q
........................................................................ [ 32%]
........................................................................ [ 65%]
........................................................................ [ 97%]
.....                                                                    [100%]
221 passed in 5.30s
```

121 of those 221 are new in this lane (MD-1's three files hold the other 100):

| File | Tests | What it holds to account |
|---|---|---|
| `tests/test_http_refusals.py` | 24 | every refusal reachable from the boundary, produced by a mocked response and read back off stdout |
| `tests/test_removed_endpoints.py` | 69 | `boundary.v1` Core 7, static and runtime, plus the surviving surface |
| `tests/test_auth.py` | 19 | PKCE, the redirect URI, the token file and its mode, `login` end to end, and the shipped binary refusing with stdin closed |
| `tests/test_disconnect.py` | 9 | `boundary.v1` Core 6, checked against the directory rather than the report |
| `tests/spotify_fakes.py` | — | the shared fake transport, token fixtures and CLI runners MD-3/4/5 should reuse |

The upstream Smart Tools kit — PINS.md's merge gate — is still green at the
pinned rev:

```
$ PATH="$PWD/.venv/bin:$PATH" uv run <amplifier-smart-tools>/conformance/run.py .
  PASS descriptor-present             smart-tool.json names the manifest and how to launch the CLI
  PASS manifest-present               SMART_TOOL.md found at src/music_deck/SMART_TOOL.md
  PASS manifest-frontmatter-parses    frontmatter parsed
  PASS manifest-fields-closed         only recognised fields present
  PASS manifest-required-fields       every required field carries content
  PASS manifest-field-shapes          every field has the shape the spec gives it
  PASS manifest-name-format           name is a slug
  PASS manifest-version-matches-package
  PASS manifest-requires-shape
  PASS manifest-single-per-root
  PASS loads-without-provider
  PASS help-flags-supported
  PASS deterministic-capability-runs  deterministic 'check' runs (exit 0) with provider env scrubbed
  PASS failure-exits-non-zero         bad invocation '__conformance_no_such_verb__' exits 2
  PASS no-hang-stdin-closed           'check' completes with stdin closed

verdict: PASS   counts: {'pass': 15, 'fail': 0, 'skip': 0}
```

---

## For the manager — files this lane does not own

**`tests/test_cli_shape.py` (MD-1's) — two tests changed. This was unavoidable,
and one of them was a live hazard.**

That file's `test_every_unbuilt_verb_refuses_loudly_rather_than_exiting_zero` is
parametrised over every verb except `check` and `manifest`, and its `run()`
helper passes **no** `MUSIC_DECK_STATE_DIR`. Before this lane, `disconnect` was a
stub. Now it is real — so that test was, on its first run here, executing
`music-deck disconnect` against the *real* `~/.local/state/music-deck` of
whoever ran the suite. (Nothing was lost: this machine had no such directory.
Verified after the fact — `ls: cannot access '/home/bkrabach/.local/state/music-deck/': No such file or directory`.)

The change is the smallest one that fixes both the staleness and the hazard:

- Added an `IMPLEMENTED_VERBS` tuple next to `ALL_VERBS`, with a comment saying
  each landing lane adds its verbs to it, and why skipping is required rather
  than merely tolerable.
- That parametrised test now excludes `IMPLEMENTED_VERBS` instead of the
  hard-coded `("check", "manifest")`.
- `test_an_unbuilt_verb_reports_not_implemented_when_its_arguments_are_valid`
  used `whoami` as its example of an unbuilt verb; it now uses `devices`.

Coverage for the three verbs did not shrink — it moved to `tests/test_auth.py`
and `tests/test_disconnect.py`, which drive them against a temporary state
directory.

**`src/music_deck/check.py` (MD-1's) — one small change recommended, not made.**
The manager note asked for `SPOTIFY_CLIENT_ID` as a documented alias and for
`check`'s `source` field to name whichever variable was used. The resolver lives
in `auth.resolve_client_id()` (env `MUSIC_DECK_CLIENT_ID` → env
`SPOTIFY_CLIENT_ID` → config file), returning `(value, source)` and never
raising. `check._client_id_fact` still has its own copy that knows only the
primary variable, so today `check` reports `"present": false` for a user who set
only the alias — while `login` works for them. The fix is four lines inside
`_client_id_fact`, calling `resolve_client_id()`. **Note the import direction:**
`auth` imports `check` for the path helpers, so `check` must do the import inside
the function body, not at module level, or the two will import in a cycle.

**`src/music_deck/__init__.py` (MD-1's) — not touched.** `login`, `disconnect`
and `whoami` are reachable from the library as
`from music_deck.verbs.auth_verbs import login, disconnect, whoami`, which
satisfies `cli.v1` Core 7. Re-exporting them from the package root would be one
line and a nicer surface; that is MD-1's file to change.

**Codes outside the frozen vocabulary.** `cli.v1` Core 6 freezes the ten codes a
*caller* can provoke. Four failures here are not that, and this lane did not fork
the vocabulary to name them — they all fall through `errors.exit_code_for` to
exit `1`, which is what Core 5 leaves that code for:

| Code | When | Why not frozen |
|---|---|---|
| `removed_endpoint` | the guard caught music-deck about to build a withdrawn path | a defect in music-deck, not a conversation with the user |
| `no_browser` | `login` could open no browser and stdin is closed | describes the machine, not the Spotify account |
| `spotify_error` | an upstream status with no frozen meaning | genuinely "a failure with no code" |
| `network_unreachable` | the socket never connected | same |

One judgement call worth the steward's eye: **`login` with no client ID
configured refuses with `usage` (exit 2)**. Core 5 puts "invalid input" at exit 2
and a run with no client ID has been given no usable input, so the exit code is
right; but `usage` will read to an agent as "re-read `--help`" when the real
remedy is "set an environment variable". If `errors.py` ever grows a
`not_configured` code, this is its first caller.

**`boundary.v1` Core 8, one thing to look at.** Core 8 enumerates what may
persist: "the token, the config file, and plan/transcript artifacts". This lane
writes a fourth file — `$XDG_STATE_HOME/music-deck/last-403.json` — which MD-1's
`check.py` already reads and reports, and which is the *only* signal Spotify
gives that an account is not on the app's allowlist. It holds three fields: a
timestamp, Spotify's own reason string, and the endpoint **with every Spotify id
redacted** (`/albums/{id}`), so it contains no Spotify content; and `disconnect`
deletes it, proved end to end. If the steward reads Core 8's list as exhaustive
rather than illustrative, this is the one line to rule on — it is a five-word
clause change, not a code change.

---

## Handoffs for MD-3, MD-4, MD-5

- **One entry point.** `from music_deck.verbs.auth_verbs import spotify_client`,
  then `spotify_client().get("/tracks/{id}")`. It refuses `not_authenticated`
  before any request when there is no token, renews an expired access token by
  itself, and raises the frozen refusals as `MusicDeckError` — the CLI already
  turns those into the envelope and the exit code. Do not build a second client.
- **`paginate(path, limit=…)`** already handles the February 2026 search cap
  (10 per page, default 5) and the 50-per-page cap everywhere else.
- **Links are automatic.** Every payload that comes back has been through
  `surface_links`; do not add `external_urls` by hand.
- **The token file's shape** is documented as a table in `auth.py`'s module
  docstring. `check.py` reads it. Do not add keys without updating both.
- **Tests:** `tests/spotify_fakes.py` gives you `FakeTransport`, `install_token`,
  `token_document`, `run_cli`, `run_probe`, `record_sleeps`. Use `run_probe` when
  the verb you need does not exist yet, and delete the probe when it does.
- **Add your verbs to `IMPLEMENTED_VERBS`** in `tests/test_cli_shape.py` as they
  land, for the reason recorded above.
