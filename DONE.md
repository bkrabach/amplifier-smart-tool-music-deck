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

# MD-4 — Intelligence protocol + `plan` verb + the discriminating good/bad pair

**Work item:** `music_deck-dws` · **Branch:** `lane/md-4` · **Date:** 2026-09-04

`music-deck plan "<brief>"` now turns a brief in the caller's own words into a
plan document, and prints the verbatim text of every prompt it sent to get it.
Contracts closed: `boundary.v1` Core 1, 2, 3 and `cli.v1` Core 3, 5 (exit 3).

The load-bearing part is not the verb. It is that `boundary.v1` Core 2 — *no
Spotify content ever enters a prompt* — stopped being a promise and became a
function anyone can run: `music_deck.check_plan_transcript(transcript,
brief=...)`. It is proven by a pair that discriminates, both halves run through
the same check and the same recording double: a plan built from the brief alone
passes; the same run with fetched track metadata appended to the prompt fails,
naming `boundary.v1 Core 2` and quoting what leaked.

## How the evidence below was produced

Unless a block says otherwise, every command ran from the worktree root
`/home/bkrabach/dev/hw-music-deck/lanes/md-4/amplifier-smart-tool-music-deck`
on branch `lane/md-4`, and every block is pasted output, not a description of it.

The conformance-kit run and the real-model runs used **non-editable installs**
into throwaway virtualenvs (`/tmp/md4-kit`, `/tmp/md4-real`), so nothing depended
on the checkout being on `sys.path`.

## Acceptance criteria

### AC1 — the discriminating good/bad pair — **PASS**

> GIVEN the Recording intelligence, WHEN `plan "<brief>"` runs, THEN the boundary
> check over the recorded prompts passes, AND WHEN the same run has fetched track
> metadata appended to the prompt, THEN the same check FAILS naming
> `boundary.v1` Core 2 — both outcomes pasted in DONE.md.

Run as one script so both halves are visibly the same check over the same
double. `Recording.run` appends `request.prompt` on its first line, *at send
time* — not reconstructed afterwards from the reply, which would make the
transcript evidence about the double rather than about the tool.

```
$ uv run --extra dev python /tmp/md4_pair_demo.py

==============================================================================
GOOD -- a plan built from the brief alone
==============================================================================
plan.brief          : "upbeat 90s guitar songs for a Saturday morning"
plan.plan_format    : 1
plan.steps          : ['genre:alternative year:1990-1999', 'genre:britpop year:1993-1998']
transcript entries  : 1
transcript == what the double recorded at send time: True
prompt characters   : 4031

boundary.v1 Core 2 kept: every one of 1 prompt(s) is covered by the caller's own arguments and music-deck's static prompt text, with nothing left over.

==============================================================================
BAD -- the same run, with fetched track metadata appended to the prompt
==============================================================================
boundary.v1 Core 2 BROKEN in 1 of 1 prompt(s).
  the clause: Every prompt sent to a model consists solely of the caller's own text and music-deck's own static schema and prompt text. No Spotify response, no cache, no token, and no data from a prior run ever enters a prompt.
  boundary.v1 Core 2 broken by prompt 0: 197 characters came from neither the caller's own arguments nor music-deck's static prompt text (it carries a Spotify URI, a Spotify API field, something shaped like a Spotify id).
    unaccounted-for text: '## Tracks I found on Spotify for this brief [{"id": "3n3Ppam7vgaVa1iaRUc9Lp", "name": "Mr. Brightside", "uri": "spotify:track:3n3Ppam7vgaVa1iaRUc9Lp", "popularity": 84, "duration_ms": 222075}]'

==============================================================================
Both halves through ONE call of the same pure function
==============================================================================
check_prompts(GOOD, allowed).ok = True
check_prompts(BAD,  allowed).ok = False

==============================================================================
Cover, not denylist: a leak that looks like nothing in particular
==============================================================================
ok = False | recognisable as Spotify content: ()
boundary.v1 Core 2 broken by prompt 0: 66 characters came from neither the caller's own arguments nor music-deck's static prompt text.
    unaccounted-for text: 'For reference, the last playlist this user built was called Beach.'
```

**Why the BAD half really fails, rather than being arranged to.** The check works
by *cover*, not by denylist: every allowed source text is removed from the
prompt and whatever remains is the violation. The allowed set is exactly the two
kinds of text Core 2 names — the parts of `src/music_deck/prompts/` and the
caller's own arguments. A prompt assembled from anything else cannot come out
clean, whatever it happens to contain. The fourth block above is the proof that
this is not a Spotify-word-scanner wearing a disguise: a leak with nothing
Spotify-shaped in it fails identically.

Sensitivity, measured — a single character fails, whitespace does not:

```
  leak=''           -> ok=True
  leak=' '          -> ok=True
  leak='\n\n\n'     -> ok=True
  leak='Beach'      -> ok=False
  leak='x'          -> ok=False
```

The BAD fixture is not a doctored string either. `leaky_assemble_prompt` in
`tests/test_plan_boundary.py` is the same static parts, the same caller brief, in
the same order, joined the same way, with one fetched-metadata block added —
the plausible mistake written out, so the check catches the thing it exists to
catch rather than a strawman.

The pair also lives in the suite as `test_the_pair_discriminates`, which asserts
both halves in one test — two separately-passing tests can both be vacuous in a
way one test comparing them cannot.

### AC2 — offline: exit 0, zero requests to `api.spotify.com`, transcript verbatim — **PASS**

> GIVEN no network and no token, WHEN `plan` runs with Scripted, THEN it exits 0,
> issues zero requests to api.spotify.com, and the result carries `transcript`
> with every prompt string sent, verbatim.

`plan` under `strace`, network syscalls only, with a positive control proving the
tracer was live (the network *is* reachable from this lane — the control really
connected, so "zero" is a property of `plan`, not of the host):

```
$ strace -f -e trace=network -o /tmp/md4-plan.strace .venv/bin/python /tmp/md4_offline.py
plan produced, steps: 2 | transcript entries: 1
--- network syscall lines during plan: 0

$ strace -f -e trace=network -o /tmp/md4-control.strace .venv/bin/python /tmp/md4_control.py
control: connected
--- network syscall lines during control: 14
4147766 connect(3, {sa_family=AF_UNIX, sun_path="/var/run/nscd/socket"}, 110) = -1 ENOENT (No such file or directory)
4147766 connect(3, {sa_family=AF_INET, sin_port=htons(53), sin_addr=inet_addr("127.0.0.53")}, 16) = 0

# the connect the tracer WOULD have caught, from the control:
4147766 connect(3, {sa_family=AF_INET, sin_port=htons(443), sin_addr=inet_addr("35.186.224.24")}, 16) = 0
```

Zero network syscalls of any kind — a stronger statement than "none to
api.spotify.com", and an easier one to trust: a request cannot hide behind a
redirect, a proxy, or a different hostname.

In the suite the same claim is enforced two more ways:
`test_plan_makes_no_network_request_at_all` installs a socket/DNS tripwire that
records and refuses every attempt (`network_tripwire == []`), and
`test_the_plan_path_pulls_in_no_http_client` asserts a fresh subprocess that runs
`plan` end to end has imported no `httpx`, `requests`, `urllib3`, or `aiohttp`.

No token, no client ID, nothing signed in — and it works
(`test_plan_needs_no_token_and_no_client_id`, which also asserts `plan` wrote
nothing into the state directory).

Transcript verbatim: `test_the_result_carries_every_prompt_sent_verbatim`
asserts `result["transcript"] == recorder.prompts` and
`result["transcript"][0] == assemble_prompt(BRIEF)`, and
`test_the_brief_reaches_the_plan_verbatim` runs a brief with awkward whitespace,
an em dash, quotes and a newline through and asserts it survives byte-for-byte
into both the prompt and `plan["brief"]` (`plan.v1` Core 2).

### AC3 — Unconfigured: exit 3, the envelope names the precondition, `run` never invoked — **PASS**

> GIVEN the Unconfigured intelligence with provider env scrubbed, WHEN `plan`
> runs, THEN exit 3, the envelope names which precondition is missing and how to
> fix it, and Unconfigured.run was never invoked.

```
$ .venv/bin/python   # Unconfigured, with assemble_prompt wrapped to count calls
refused      : `plan` is model-backed and no model provider is configured.
remedy       : Set ANTHROPIC_API_KEY (or OPENAI_API_KEY, GOOGLE_API_KEY, AZURE_OPENAI_API_KEY) and run again.
exit code    : 3
envelope     : {'error': {'code': 'no_provider_configured', 'message': '`plan` is model-backed and no model provider is configured.', 'remedy': 'Set ANTHROPIC_API_KEY (or OPENAI_API_KEY, GOOGLE_API_KEY, AZURE_OPENAI_API_KEY) and run again.', 'missing': 'provider'}}
prompts assembled before the refusal : 0
Unconfigured.run invocations         : 0
```

The same refusal at the binary, environment scrubbed the way the conformance kit
scrubs it, stdin closed:

```
$ env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY -u GOOGLE_API_KEY -u GEMINI_API_KEY \
      -u AZURE_OPENAI_API_KEY -u MUSIC_DECK_PROVIDER \
      music-deck plan "upbeat 90s guitar songs for a Saturday morning" < /dev/null
{
  "error": {
    "code": "no_provider_configured",
    "message": "`plan` is model-backed and no model provider is configured.",
    "remedy": "Set ANTHROPIC_API_KEY (or OPENAI_API_KEY, GOOGLE_API_KEY, AZURE_OPENAI_API_KEY), or pin one with MUSIC_DECK_PROVIDER. Every other verb runs with no provider at all.",
    "missing": "provider"
  }
}
EXIT=3
# stderr: `plan` is model-backed and no model provider is configured.
```

**"Before any prompt is built" is proven twice, independently**, because a tool
that assembles a prompt and *then* refuses looks identical from outside:

1. `Unconfigured.run` records the call in `run_calls` **and** raises
   `AssertionError` if it is ever reached — so a caller that swallowed the
   exception would still leave the evidence behind (`run_calls == []` above).
2. `test_no_prompt_is_ever_assembled` replaces
   `music_deck.verbs.plan.assemble_prompt` with a tripwire that fails the test if
   called at all. It is not called.

In `verbs/plan.py` the ordering is one line of code apart and commented as such:
the argument check, then `engine.preflight(provider)`, then — only then —
`assemble_prompt`.

The precondition vocabulary is closed (`PRECONDITIONS`) and every branch is
tested (`tests/test_plan_refusal.py`), each naming its own fix:

| `missing` | when | the remedy names |
|---|---|---|
| `provider` | nothing credentialled, nothing pinned | the four credential env vars, and `MUSIC_DECK_PROVIDER` |
| `provider` | `MUSIC_DECK_PROVIDER` names something unknown | the providers music-deck knows |
| `credentials` | a provider is pinned but has no credential here | that provider's own env var |
| `provider_sdk` | credential resolves, client library absent | `uv pip install "music-deck[anthropic]"` |
| `engine` | credential and SDK both present, engine absent | the `amplifier-agent` install line |

`cli.v1` Core 3 names three preconditions; `engine` is a fourth of the same kind
(the substrate itself), refusing the same way with the same exit code. Recorded
under "Interpretations" below.

### AC4 — a base install imports no provider SDK — **PASS**

> GIVEN base install without any provider extra, WHEN `import music_deck` runs,
> THEN no provider SDK is imported.

Checked for four entry points, and extended to the engine library as well —
importing `amplifier_agent_lib` rewrites `AMPLIFIER_HOME` in the caller's own
environment, which is not something forty deterministic verbs should be able to
do by being imported:

```
  import music_deck                ->  []
  import music_deck.intelligence   ->  []
  import music_deck.verbs.plan     ->  []
  from music_deck.cli import main  ->  []
```

(The probe lists any loaded module whose top-level package is one of
`anthropic`, `openai`, `google`, `cohere`, `mistralai`, `amplifier_agent_lib`,
`amplifier_agent_cli`, `httpx`, `requests`. Empty list = none of them loaded.)

`test_preflight_answers_without_importing_anything` goes one further: even
*asking* whether a provider is available imports nothing, because `preflight`
uses `importlib.util.find_spec`, which answers without importing.

Provider SDKs are extras in `pyproject.toml` (`anthropic`, `openai`, `gemini`,
`azure-openai`), never base dependencies. Base dependencies are unchanged:
`pyyaml` only.

### AC5 — every prompt string is from `src/music_deck/prompts/` or the caller's own arguments — **PASS**

> Every prompt string is either from src/music_deck/prompts/ or from the caller's
> own arguments — asserted by the boundary check.

This is what the cover check asserts, so it is AC1's mechanism seen from the
other side. `test_every_prompt_is_covered_by_prompts_directory_plus_caller_arguments`
asserts `uncovered(prompt, [*static_prompt_texts(), BRIEF]) == ""`.

The design that makes it true rather than lucky: `prompts/plan.md` is split into
named parts (`instructions`, `brief`, `context`) by `=== SECTION: ===` markers,
and `assemble_prompt` interleaves *only* those parts with the caller's verbatim
text. There is no format string, no f-string, no heading defined in Python. A
sentence added to `prompts/plan.md` is allowed in a prompt; a sentence added
anywhere else in the source is not, and the check will say so.

Two deliberate consequences, both tested:

- **A caller who pastes Spotify content into `--context` is not a leak.** Core 2
  allows "the caller's own text", all of it, whatever it contains, and
  `boundary.v1`'s own reserved question ("whether a plan may carry a Spotify ID
  the caller typed in themselves") is open.
  `test_a_caller_who_pastes_spotify_content_into_context_is_not_a_leak` records
  the decided behaviour, and asserts the *same* transcript checked without
  declaring that context **fails** — which is what makes the pass a statement
  about provenance rather than about the characters.
- **There is no draft-and-repair round.** The obvious way to make a model's JSON
  reliable is to hand a rejected draft back with the findings. `plan` does not,
  because a repair prompt would carry the model's own previous output — neither
  the caller's text nor music-deck's static prompt text. It would fail this
  tool's own check, correctly. One turn, one prompt, one transcript entry; a
  draft that does not validate is a refusal naming the offending path.

`plan` also runs the check against itself before returning, so a future change
that leaks fails loudly at the point of the leak instead of shipping a plan
nobody looked at.

### AC6 — pytest green — **PASS**

```
$ uv run --extra dev pytest -q
........................................................................ [ 51%]
.....................................................................    [100%]
141 passed in 4.18s
```

103 of those are MD-1's and still pass unchanged; 38 are new
(`tests/test_plan_boundary.py`, `tests/test_plan_refusal.py`).

The upstream Smart Tools kit is still green against a non-editable install —
the merge gate:

```
$ PATH=/tmp/md4-kit/.venv/bin:$PATH uv run .../amplifier-smart-tools/conformance/run.py <repo-root>
smart-tools conformance :: .../amplifier-smart-tool-music-deck
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
```

## Beyond the bar: a real model turn through the production `Intelligence`

The acceptance criteria are met with the doubles and need no model. A provider
key *was* present in this lane's environment, so the optional smoke was
attempted — and it works. `amplifier-agent` and `anthropic` were installed into
a throwaway venv (`/tmp/md4-real`); neither is in this repo's base dependencies.

A brief deliberately unlike the worked example in `prompts/plan.md`, so the
result cannot be the model copying the example back:

```
$ AMPLIFIER_AGENT_HOME=/tmp/md4-real/agent-home .venv/bin/python smoke2.py
{
  "plan_format": 1,
  "brief": "moody Ethiopian jazz and desert blues for writing on a rainy afternoon, about an hour, nothing with vocals in English",
  "target": {"kind": "new", "name": "Rainy Afternoon Writing", ...},
  "steps": [
    {"search": "genre:ethio-jazz", "type": "track", "take": 15,
     "why": "the core moody Ethiopian jazz sound the brief asks for"},
    {"search": "artist:Mulatu Astatke", "type": "track", "take": 10,
     "why": "the genre's defining voice, instrumental and atmospheric"},
    {"search": "genre:desert blues", "type": "track", "take": 15,
     "why": "the hypnotic, rainy-day desert blues side of the brief"},
    {"search": "artist:Tinariwen", "type": "track", "take": 10,
     "why": "a desert blues touchstone, sung in Tamashek not English"},
    {"search": "artist:Ali Farka Toure", "type": "track", "take": 10,
     "why": "more desert blues warmth, vocals in Songhay/Bambara"}
  ],
  "rules": {"exclude_artists": [], "exclude_title_terms": ["remix", "live", "radio edit"],
            "dedupe": "by_title_and_primary_artist", "order": "shuffle"},
  "size": {"minutes": 60, "tolerance_pct": 10}
}

transcript entries: 1
boundary.v1 Core 2 kept: every one of 1 prompt(s) is covered by the caller's own arguments and music-deck's static prompt text, with nothing left over.
```

It honoured "about an hour" as `size.minutes: 60`, and "nothing with vocals in
English" in its reasoning rather than only in prose — and every step names music
by search expression, never by ID, which is `plan.v1` Core 3.

The whole thing through the binary, including `--output`:

```
$ music-deck plan "three or four Nick Drake-adjacent folk songs for a quiet evening" \
      --output /tmp/md4-real/plan.json < /dev/null
EXIT=0
top-level keys : ['plan', 'transcript']
transcript     : 1 entry; 4049 chars
plan.steps     : ['artist:"Nick Drake"', 'genre:"folk" year:1968-1974',
                  'artist:"John Martyn" OR artist:"Vashti Bunyan" OR artist:"Bert Jansch"']
plan.brief     : "three or four Nick Drake-adjacent folk songs for a quiet evening"

# --output writes a bare plan `apply` can read:
keys: ['plan_format', 'brief', 'target', 'steps', 'rules', 'size']
has transcript: False

# stderr lines: 0   (cli.v1 Core 4 -- stdout carries exactly one JSON document)

# the boundary check, run over what the CLI printed, by a reader who never saw the source:
boundary.v1 Core 2 kept: every one of 1 prompt(s) is covered by the caller's own arguments and music-deck's static prompt text, with nothing left over.
```

That last block is the point of Core 3 in one command: the transcript is an
output, so the boundary is checkable by whoever holds the output.

## Interpretations this lane had to make, and why

1. **`plan` takes its brief as a positional argument, not `--brief`.** The item
   and GOAL both spell it `plan <brief>` / `music-deck plan "<brief>"`; MD-1's
   stub had `--brief`. The positional won. **This makes one line of
   `SMART_TOOL.md` stale** — see "Notes for the manager" below.

2. **The result is `{plan, transcript}`, and `--output` writes the plan alone.**
   `boundary.v1` Core 3 makes the transcript part of the answer, so stdout
   carries both; but `apply` needs a bare `plan.v1` document, so `--output`
   writes that. This also makes one line of `SMART_TOOL.md` stale (same note).

3. **A fourth precondition, `engine`.** `cli.v1` Core 3 names three (SDK, no
   provider, no credentials). A missing engine library is a fourth way to have
   "no usable model substrate" — Core 3's own opening words — and refuses
   identically (exit 3, named, with a remedy). No contract change proposed: the
   clause's list reads as examples of the same condition, not as a closed set.
   Flagging it in case the steward reads it as closed.

4. **The engine is not a music-deck extra.** It was tried and it does not work:
   `amplifier-agent` is not on PyPI (needs a git direct reference and
   `allow-direct-references`) and requires Python >= 3.12, while music-deck
   declares >= 3.11. Measured:

   ```
   $ uv sync --extra dev   # with amplifier-agent added to the anthropic extra
   ... conclude that amplifier-agent==0.17.0 cannot be used.
   ... your project's requirements are unsatisfiable.
   hint: The `requires-python` value (>=3.11) includes Python versions that are not
   supported by your dependencies (e.g., amplifier-agent==0.17.0 only supports >=3.12).
   ```

   Declaring it would break `uv sync` for a 3.11 caller who only ever wanted the
   deterministic verbs. So provider *SDKs* are extras (`music-deck[anthropic]`
   etc.) and the engine is installed alongside, which the `engine` refusal names
   explicitly. Raising `requires-python` to `>=3.12` is a steward call, not a
   lane call — see "Notes for the manager".

5. **No repair round, deliberately** (reasoning under AC5). It costs some
   robustness against a model that returns malformed JSON. It buys an airtight
   Core 2: every prompt is caller text plus static text, with no exception that
   would have to be argued about later.

6. **`plan_format` and `brief` are music-deck's to write, not the model's.** The
   prompt asks for `target`, `steps`, `rules` and optional `size`; `compose_plan`
   adds `plan_format: 1` and the caller's `brief` verbatim. `plan.v1` Core 2's
   "the caller's text, verbatim" is then true by construction. If the model
   echoes either field it must agree, or the plan is refused — a paraphrased
   brief is a plan the caller cannot check against what they asked for.

7. **The plan validator here is the minimal stand-in the brief allows.**
   `music_deck.plan_schema.validate_plan` (MD-5, `music_deck-v0b`) had not landed
   when this branched from `main` @ `ee01a5f`. `validate_plan_document` imports it
   if present and falls back to a local check of `plan.v1` Core 1–6 otherwise, so
   **MD-5 replaces the local check by landing — no edit to this lane's files is
   needed.** The local check accepts either shape from MD-5 (raising, or
   returning findings).

## Notes for the manager (files this lane does not own)

1. **`src/music_deck/SMART_TOOL.md` — two stale lines** (MD-1 owns this file, so
   this lane did not edit it). Its "Worked invocations" block says:

   ```
   music-deck plan --brief "upbeat 90s guitar songs for a Saturday morning" > plan.json
   music-deck apply --plan plan.json
   ```

   Both lines are now wrong: the brief is positional, and stdout carries
   `{plan, transcript}` rather than a bare plan. The working equivalent is:

   ```
   music-deck plan "upbeat 90s guitar songs for a Saturday morning" --output plan.json
   music-deck apply --plan plan.json
   ```

   Nothing in the manifest's *frontmatter* changed, so the conformance kit is
   unaffected — this is body prose only, and the body carries no compatibility
   guarantee. Still worth fixing before anyone follows it.

2. **`pyproject.toml` — this lane edited it** (adding four provider extras). It
   is MD-1's file. Base dependencies were **not** touched; the change is
   additive, under `[project.optional-dependencies]`, and is required for the
   `provider_sdk` refusal's remedy (`uv pip install "music-deck[anthropic]"`) to
   name something that exists. Flagged in case it collides with another lane.

3. **`src/music_deck/cli.py` and `src/music_deck/__init__.py` — edited within the
   item's grant.** In `cli.py`, only the `plan` verb entry, its handler, and two
   imports (`json`, `pathlib.Path`). In `__init__.py`, three exports added
   (`plan`, `check_plan_transcript`, `check_prompts`) because `cli.v1` Core 7
   requires every CLI capability to be reachable from the library. No shared
   helper's behaviour was changed.

4. **A steward-level question, not urgent:** should `requires-python` rise to
   `>=3.12` so the engine can be a declared extra (interpretation 4)? Today a
   3.11 user gets every deterministic verb and a clean refusal from `plan`, which
   seems the right trade — but it means `plan`'s substrate is installed by a
   second command rather than by an extra.

5. **For MD-5 (`apply`):** `music_deck.verbs.plan.validate_plan_document` is the
   seam to replace; `_first_problem` is a pure function returning
   `(path, detail)` and can be lifted wholesale into `plan_schema` if useful. The
   refusal it raises is `invalid_plan` with `path` in the envelope, exit 2, per
   `cli.v1` Core 6.

6. **For `boundary.v1`'s conformance kit (unbuilt):** the assert it needs is
   already a pure function — `music_deck.prompt_boundary.check_prompts(prompts,
   allowed)`. It reads no file, touches no environment, and calls nothing, so it
   can run against a transcript captured on a machine the kit does not have.
   `music_deck.testing` ships `Recording`/`Scripted`/`Unconfigured` inside the
   package precisely so a reviewer can run this pair against their own install
   without cloning the repo.

## Scope-outs honoured

No publishing, tagging, releasing, PR, or merge. No work on `http.py` or the
Spotify verbs (MD-2/MD-3) — neither exists yet and this lane did not create
them. No changes to `docs/VISION.md` or `contracts/*.md`. No real Spotify
account and no Spotify request anywhere, in tests or out. No infrastructure
stood up, so nothing to register in the infra ledger and nothing to tear down.
The one file outside the item's named paths that was edited (`pyproject.toml`)
is flagged above.

## Files this lane added or changed

| Path | What |
|---|---|
| `src/music_deck/intelligence.py` | the `Intelligence` protocol, `AmplifierIntelligence` (engine in-process, tools/agents/hooks unmounted, approval declined), the preflight taxonomy and `NoModelSubstrate` |
| `src/music_deck/prompts/plan.md` | the only non-caller text a prompt may carry |
| `src/music_deck/prompts/__init__.py` | the part-splitting loader and `static_prompt_texts()` |
| `src/music_deck/prompt_boundary.py` | `boundary.v1` Core 2 as a pure cover check over prompt strings |
| `src/music_deck/verbs/plan.py` | the verb: preflight, assemble, one turn, validate, publish the transcript |
| `src/music_deck/testing/intelligence_doubles.py` | `Recording`, `Scripted`, `Unconfigured` |
| `tests/test_plan_boundary.py` | the discriminating pair, the offline proofs, the CLI adapter |
| `tests/test_plan_refusal.py` | exit 3, the precondition taxonomy, the no-prompt-built tripwire, the import probes |
| `src/music_deck/cli.py` | the `plan` verb entry and handler (replacing MD-1's stub) |
| `src/music_deck/__init__.py` | three exports (`cli.v1` Core 7) |
| `pyproject.toml` | four provider extras (see note 2) |
