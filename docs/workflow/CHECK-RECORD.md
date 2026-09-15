# Manager verification record

Entries record checks rerun by the integrating manager, not worker claims.
Keep raw run output, prompts, account data and machine paths private.

## 2026-09-09 — fresh `do` tools and evaluation fidelity

**Scope:** integration merge `60c27ed32b6a025d83c50d22cad517d7a2c0d007`,
including cumulative implementation `becac65ffeab45487a4c79e605c0feea75228725`
and packaging repair `547abc4261928b431ad5f7a359c88f09ce6b8a79`, followed by
manager corrections to evaluation predicates and documentation/help.

### Installed-artifact checks

The manager rebuilt from the integrated checkout, installed wheel and sdist
into separate Python 3.12 environments, and ran from outside the checkout.
HOME, XDG configuration/cache/state and TMPDIR were private, fresh directories;
provider and Spotify credentials and PYTHONPATH were absent. Directory variables
below stand for those verification-owned locations.

Commands and calls:

```text
uv build --out-dir "$DIST"
uv venv --python /usr/bin/python3 "$V"
uv pip install --python "$V/bin/python" "$WHEEL" pytest
pytest.main(["$REPO/tests", "-m", "not live", "-q", "-ra"])
python "$KIT/conformance/run.py" "$REPO" --json-only
uv pip install --python "$SDIST_V/bin/python" "$SDIST"
```

The pytest invocation ran inside the wheel environment, with import-origin
assertions before and after the suite in the same process.

Observed output:

```text
792 passed, 1 skipped, 3 deselected
INSTALLED_ORIGINS=PASS
Conformance: 15 pass, 0 fail, 0 skip
```

The one ordinary skip is the empty parameter set in the CLI-shape test; the
three deselections are explicitly live tests, not silent passes.

Both installed artifacts passed `-h`, `--help`, `do -h`, `do --help`,
`apply -h`, `apply --help`, `check`, and `manifest`. Installed apply help
explicitly reported track-only execution and the pre-request album-step refusal.
Both installed evaluators returned exit 4 for `--scenario named-session`
without provider confirmation. Neither command contacted a provider.

Both archives contained LICENSE and excluded private/workflow paths and the
verifying machine's home path. Separately, the exact CI build/inspection steps
passed with synthetic workflow files present, including without VCS ignore
rules; the same inspection rejected the earlier archive containing a workflow
brief. That rejected artifact was not published.

### Native runtime pilot

The manager ran four real-provider invocations using Anthropic
`claude-sonnet-5` and the public native engine/binding pinned to
`412cc176cfa5bd219254060ede7f03bbf6578005` (both version `1.0.0a1`).
Spotify and LAN boundaries were closed, stateful fakes; no real account,
playlist, library, receiver or playback operation was performed.

The final three scenarios passed independent effect checks:

- Six unique tracks across three synthetic artists, in the requested order,
  with preserved request bodies and an independent playlist-items readback.
- Saved-library and API-device reads, with the separate API and one subsequent
  LAN observation retained, and no writes.
- A recorded pause refusal under `--no-playback`, actual music-deck exit 2,
  and no player request.

The first playlist invocation performed the correct effects, but the grader
incorrectly rejected canonical `playlist_items` readback held in an action.
The original failure was retained; a failing regression was added, the grader
was corrected, and a new invocation passed. This is a small pilot, not a
reliability benchmark. Raw run records remain private.

Parent-process HTTPX/UDP instrumentation was not a whole-engine egress trace.
Effect isolation rests on reviewed, closed client/observer injection, not on
empty network counters. No global installation was upgraded.

### Contract disposition

**Kept within the checked scope:** installed CLI/help and refusal behavior,
fresh tool dispatch, effect restrictions, request accounting, unknown-write
containment, synthetic-boundary evaluation and publication exclusions.

**Not yet:** named conversation creation/resumption and associated durable
history guarantees need an upstream public content-protection seam; album-plan
execution needs a precise semantic amendment. Safe early album refusal is not
full `plan.v1` conformance.

**Can't check as a complete automated contract ledger:** the clause-by-clause
ledger and per-contract kits are not yet seeded. The baseline Smart Tools kit
and the checks above are not a declaration that every draft promise is kept.

## 2026-09-15 — fresh-only main merge

**Scope:** merge `1cb2497e1c2e87c6c0edd55f1ab769d9d18444aa`, whose tree equals
the reviewed `b2dd611dbede043420cf31692fe04407dab7dc7d` feature head.
No runtime change is introduced by the accompanying candidate documents.

The manager reran the offline suite from outside the checkout against the
previously installed wheel. Before pytest, every source Python file was
byte-compared with its installed counterpart; before and after pytest,
music-deck imports were required to originate in that wheel environment.
Fresh HOME/XDG/TMPDIR locations and an explicit credential-free environment
were used.

```text
pytest.main(["$REPO/tests", "-m", "not live", "-q", "-ra"])
MERGED_SOURCE_MATCHES_INSTALLED_WHEEL=PASS
792 passed, 1 skipped, 3 deselected
INSTALLED_ORIGINS=PASS
```

The kit was rerun with the installed wheel's CLI on PATH:

```text
"$KIT_PYTHON" "$KIT/conformance/run.py" "$REPO" --json-only
{"pass": 15, "fail": 0, "skip": 0}
```

The first kit invocation could not import `pydantic` in the base product
environment and was not a pass. A rerun with the dependency-complete kit
interpreter passed without changing the global installation; the initial
failure remains in private evidence.

The exact-merge push CI also passed, independently building and installing
wheel/sdist artifacts, testing the installed wheel, smoking installed commands,
and running the pinned kit:
https://github.com/bkrabach/amplifier-smart-tool-music-deck/actions/runs/34914933863

**Not yet:** named continuation, credential-safe durable admission, and the
album producer/consumer mismatch remain open. The new plan and transcript
candidates propose decisions; they do not enact them. The full contract ledger
and per-contract kits remain unseeded. No paid-model, real Spotify/LAN, playback,
or global-installation operation was part of this check.

## 2026-09-15 — ratified track plans and application-boundary transcripts

**Scope:** manager integration merge
`5d9a4a59e1a319a31a2bc3f88b4714d7d624f6bf`, with the narrow record-test
correction `0b773dd3581928be1ff30985f89b590ea6ae74e5`. The merge implements
the ratified `plan.v1`, `do.v1`, and `boundary.v1` direction: plan steps are
track-only and transcripts describe the application boundary without claiming
engine or provider wire visibility.

The manager reran the complete non-live suite:

```text
uv run python -m pytest -m 'not live' -q -ra
800 passed, 1 skipped, 3 deselected
```

The sole ordinary skip is the existing empty CLI-shape parameterization; the
three deselections are marked live. A source-independent review also passed:
the shared validator rejects album steps before `apply` obtains a client, and
the public-binding double compares actual submitted `TurnInput` and actual
handler returns with the application-boundary transcript.

The manager built fresh wheel and source-distribution artifacts in isolated
HOME/XDG/TMPDIR locations and ran tests from outside the checkout:

```text
WHEEL_SOURCE_BYTE_MATCH=PASS
800 passed, 1 skipped, 3 deselected
WHEEL_IMPORT_ORIGINS_BEFORE_AFTER=PASS
SDIST_IMPORT_FROM_INSTALLED=PASS
WHEEL_ARCHIVE_PRIVACY_AND_LICENSE=PASS
SDIST_ARCHIVE_PRIVACY_AND_LICENSE=PASS
PINNED_SMART_TOOLS_KIT=15 pass, 0 fail, 0 skip
```

Installed short and long help for `plan`, `do`, and `apply`, plus `check` and
`manifest`, named track-only plans and
`transcript_scope: application_boundary`. No provider, Spotify, LAN, account,
or playback call was made; no global installation was changed.

**Kept in this scope:** track-only producer/schema/native-tool admission,
zero-request album refusal, application-owned transcript capture, immutable
recorded action snapshots, accurate help and packaged guidance.

**Not yet:** whole-album expansion remains deliberately undefined. Saved
session creation/resume and the broad pre-persistence guard for native-generated
content remain blocked on the separate, unratified upstream capability. The
unseeded full contract ledger and per-contract kits remain *Can't check*.