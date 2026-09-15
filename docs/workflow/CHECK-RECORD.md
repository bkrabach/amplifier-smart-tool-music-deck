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