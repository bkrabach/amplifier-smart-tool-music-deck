# Contributing to music-deck

Thank you for improving this independent community project. Keep changes small, trace behavior changes to the relevant contract, and do not edit a frozen contract in place. Start with `AGENTS.md`, `PINS.md`, and the relevant file in `contracts/`.

## Development environment

Use Python 3.12 or later and install the development environment from a clone:

```sh
uv sync --extra dev
uv run python -m pytest -m 'not live' -q
```

The offline suite is the normal local verification command. Do not run a blanket test suite on an authorization-ready host: tests marked `live` require explicit human intent, a dedicated test account, a real provider, and can mutate real Spotify playlists.

## Before proposing a change

- Use synthetic fixtures and sanitized diagnostics. Never commit tokens, client IDs, account data, device details, private playlist data, raw live output, home paths, or hostnames.
- Preserve the public CLI and error-envelope contracts unless the change is explicitly governed by the corresponding contract process.
- If public docs, fixtures, or another new public content class are introduced, ask a fresh-context reviewer to read the diff as an outsider for identity or private-process disclosures.
- Prefer GitHub's noreply address for commit attribution rather than publishing a personal email address.

## Verification and packaging

CI at `.github/workflows/ci.yml` builds both wheel and source-distribution artifacts, tests an installed wheel from an isolated environment, smokes installed commands, and runs the pinned Smart Tools conformance kit. The pin and expected conformance result are recorded in `PINS.md`.

Before opening a pull request, run the offline test command above. For packaging, installed-artifact, or conformance-sensitive changes, provide the corresponding evidence from the CI workflow or an equivalent isolated local run. Do not claim a live Spotify or model result unless a person deliberately performed it with a test account.

## Pull requests and issues

Use the pull-request template and explain the user outcome, contract impact, verification, and privacy review. Report ordinary bugs through GitHub Issues: https://github.com/bkrabach/amplifier-smart-tool-music-deck/issues

Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md). Do not include sensitive data in any public report.
