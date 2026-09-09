# Pins — hard facts for this repository

Read this before your first command. Every line is a fact you may rely on.

## Where things are

| Thing | Exact location |
|---|---|
| Vision | `docs/VISION.md` |
| Contracts | `contracts/cli.v1.md`, `contracts/boundary.v1.md`, `contracts/plan.v1.md`, `contracts/refusals.v1.md`, `contracts/do.v1.md` |
| Contracts README | `docs/CONTRACTS-README.md` |
| Standing rules for sessions | `AGENTS.md` |
| Conformance ledger | `ledger/rows.yaml` — not seeded yet |
| Conformance kits | `conformance/<contract>/run.py` — not built yet |
| Integration branch | `main` |

## Naming

- A proposal to change a contract is `<contract>.vN-candidate.md`, in the same
  folder as the contract it changes.
- A locked contract carries `(FROZEN <date>)` in its first heading line. A
  draft carries `(DRAFT)`. Status appears nowhere else in the file. All five
  contracts are `(DRAFT)` today.

## The pre-push guard

- The hook lives at `.githooks/pre-push`. Enable it once per clone:

  ```
  git config core.hooksPath .githooks
  ```

- It refuses any push whose diff touches a file whose first heading contains
  `(FROZEN`, unless the same push also contains a sibling `*-candidate.md`.
- Run it by hand against a base: `./.githooks/pre-push <base-ref>`.

## The Smart Tools spec pin

- `music-deck` conforms to the Smart Tools specification at
  `microsoft/amplifier-smart-tools` @
  `fd3c63416d1c9b0eb6e55981b248d1b2b5c64452`.
- Run the kit from this repo root:
  `uv run <path-to-amplifier-smart-tools>/conformance/run.py .`
- Green is the merge gate.
- `.github/workflows/ci.yml` checks out that exact revision and fails unless
  the kit reports 15 pass, 0 fail, and 0 skip.

## Continuous integration

- CI builds wheel and source-distribution artifacts, then tests and smokes
  installed copies from an isolated temporary environment. It runs
  `pytest -m 'not live'`; ordinary pytest skips remain reported separately from
  the conformance kit's zero-skip requirement.
- CI has no configured secrets and makes no Spotify, account, or model calls.

## Identity facts

- Tool name `music-deck`; CLI argv `music-deck`; Python package `music_deck`.
- Manifest at `src/music_deck/SMART_TOOL.md`.
- `smart-tool.json` `deterministic_smoke`: `["check"]`.
- Version `0.1.0` in both `pyproject.toml` and the manifest.
- Env prefix `MUSIC_DECK_*`; config `~/.config/music-deck/`; state
  `~/.local/state/music-deck/`.

## Work tracking

- Work-tracker project: `music_deck` (underscore — the tracker rejects hyphens). Items MD-1..MD-6 = music_deck-5xp, -2rj, -uyf, -dws, -v0b, -wju.
- Every work item names the contract it serves.

## Handoffs to other lanes

- None yet.
