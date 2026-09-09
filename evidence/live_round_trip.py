"""The live round trip: `login` -> `plan` -> `apply` -> the playlist exists.

Everything else in this repository is proven against mocks. This script is the
one thing that is not: it drives the real `music-deck` binary against a real
Spotify account and a real model provider, and it writes down what happened.

    uv run --with "amplifier-agent @ git+https://github.com/microsoft/amplifier-agent@v1#subdirectory=packages/python" --extra anthropic python evidence/live_round_trip.py

**Only the owner can run it.** It needs their own registered Spotify app
(Development Mode), their Premium account, a browser, and a model provider
credential. No lane, no CI job and no mock can stand in -- which is exactly why
`boundary.v1`'s conformance kit lists this one as *owner-only; can't check by
machine*, and why this script refuses to run rather than approximate.

What it proves
--------------
* `boundary.v1` kit assert -- "one live round-trip: `login` -> `plan` ->
  `apply` -> the playlist exists -- run by the owner against their own
  Development Mode app."
* `boundary.v1` Core 2 -- the prompt transcript carries no credential: not the
  access token, the refresh token, or the client ID. Checked here with
  `music_deck.prompt_boundary.check_plan_transcript`, the same check the library
  runs against itself, so this script and the tool agree on what "kept" means.
  Spotify *content* in a prompt is permitted by Core 1 and passes.
* `boundary.v1` Core 3 -- the transcript is an observable output, written into
  the evidence document verbatim.
* `cli.v1` Core 4/5/6 -- one JSON document per result; a `partial_result` is a
  documented outcome carrying its completeness, never a silent truncation.
* `plan.v1` Core 7 -- the per-step `requested`/`fetched`/`kept` completeness.

How it refuses to lie
---------------------
Four honesty gates, each of them a way this script can fail rather than a way
it can pass:

1. **The playlist is verified independently.** `apply` reporting success is
   not the evidence. The playlist is read back with `music-deck playlist
   items`, and fewer than one item is a FAIL -- an empty playlist can never
   pass here.
2. **Nothing is written for a run that did not happen.** Missing preconditions
   exit 2 and write no evidence file at all.
3. **No secret is printed or persisted.** Every provider credential in the
   environment, and the stored token, are scanned for in the document before it
   is written; a hit refuses the write. Only variable *names* are ever printed.
4. **No fetched Spotify content is persisted either.** The document records
   counts, the plan (which by `plan.v1` Core 5 carries no Spotify content), the
   transcript, and the one playlist the run created. Any other Spotify id, URI
   or link found in the document refuses the write. Since 2026-09-06 this is
   **this script's own discipline, not a contract requirement**: `boundary.v1`
   Core 8 now lets an artifact the caller asked for carry Spotify content.
   This record is private local evidence, not a publication-safe report: it can
   still contain account identifiers, personal brief text, and machine paths.
   Never commit or upload it; publish only separately reviewed anonymous outcomes.

`--self-test` exercises all four gates against synthetic inputs, with no
Spotify account, no provider and no network. That is the part a lane can run;
the live round trip itself is the owner's.

Exit codes: `0` the round trip passed - `1` it failed - `2` preconditions are
missing, nothing ran.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Final, Sequence

REPO_ROOT: Final = Path(__file__).resolve().parent.parent
EVIDENCE_DIR: Final = REPO_ROOT / ".private" / "evidence"

EXIT_PASS: Final = 0
EXIT_FAIL: Final = 1
EXIT_PRECONDITION: Final = 2

DEFAULT_BRIEF: Final = (
    "three upbeat 90s guitar songs for a Saturday morning, in a new playlist "
    'called "music-deck live round trip"'
)
"""Deliberately small. Development Mode's quota is shared, undisclosed, and
counted per developer account -- a proof run should cost the owner as little of
it as possible."""

PLAN_TIMEOUT_S: Final = 420.0
LOGIN_TIMEOUT_S: Final = 420.0
DETERMINISTIC_TIMEOUT_S: Final = 120.0
LOGIN_BROWSER_WAIT_S: Final = 300


# --------------------------------------------------------------------------- #
# Running the binary
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Run:
    """One invocation of the binary, and everything it said."""

    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def command(self) -> str:
        return " ".join(_quote(part) for part in self.argv)

    @property
    def document(self) -> Any:
        """The one JSON document on stdout (`cli.v1` Core 4), or None."""
        try:
            return json.loads(self.stdout)
        except ValueError:
            return None

    @property
    def error_code(self) -> str | None:
        document = self.document
        if isinstance(document, dict) and isinstance(document.get("error"), dict):
            code = document["error"].get("code")
            return code if isinstance(code, str) else None
        return None


def _quote(part: str) -> str:
    return f'"{part}"' if " " in part else part


def resolve_cli(explicit: str | None = None) -> list[str]:
    """How to invoke music-deck here, preferring the binary `cli.v1` promises.

    `cli.v1` Core 1 says "one binary, `music-deck`, on PATH", so that is what a
    round trip should exercise. The module fallback exists so a checkout that
    has not been installed can still run the proof -- and the evidence document
    records which of the two was used, because they are not the same claim.
    """
    if explicit:
        return [explicit]
    found = shutil.which("music-deck")
    if found:
        return [found]
    return [sys.executable, "-m", "music_deck.cli"]


def run_cli(
    base: Sequence[str],
    args: Sequence[str],
    *,
    timeout: float = DETERMINISTIC_TIMEOUT_S,
    interactive: bool = False,
) -> Run:
    """Invoke one verb and capture its answer.

    stdin is closed for every verb but `login` -- `cli.v1` Core 1 promises a run
    with stdin closed never hangs, and running that way here means the proof
    exercises the promise rather than assuming it. `login` is the exception on
    purpose: it is the one interactive verb, and when it cannot open a browser
    it prints a URL to paste, which needs a terminal to be worth printing.
    """
    argv = [*base, *args]
    try:
        completed = subprocess.run(  # noqa: S603 - argv is built here, never from input
            argv,
            stdin=None if interactive else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=None if interactive else subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return Run(
            argv=tuple(argv),
            returncode=124,
            stdout="",
            stderr=f"timed out after {timeout:.0f}s",
        )
    except OSError as exc:
        return Run(argv=tuple(argv), returncode=127, stdout="", stderr=str(exc))
    return Run(
        argv=tuple(argv),
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=(
            "(streamed to the terminal)" if interactive else (completed.stderr or "")
        ),
    )


# --------------------------------------------------------------------------- #
# Gate 3 -- no secret is printed or persisted
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Secret:
    """One secret value present on this machine, and where it came from."""

    name: str
    value: str


def secrets_present() -> list[Secret]:
    """Every provider credential in the environment, plus the stored token.

    Values are collected only so they can be *searched for*. Nothing in this
    module prints one, and `render_evidence` is never handed one.
    """
    found: list[Secret] = []
    try:
        from music_deck.intelligence import PROVIDER_CREDENTIAL_ENV

        names = sorted({name for names in PROVIDER_CREDENTIAL_ENV.values() for name in names})
    except Exception:  # noqa: BLE001 - a proof that cannot import the tool has bigger problems
        names = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY", "AZURE_OPENAI_API_KEY"]

    for name in names:
        value = os.environ.get(name, "").strip()
        if len(value) >= 8:
            found.append(Secret(f"environment {name}", value))

    for name, value in _stored_token_secrets():
        found.append(Secret(name, value))
    return found


def _stored_token_secrets() -> list[tuple[str, str]]:
    """The access and refresh tokens on disk, if a token file exists."""
    try:
        from music_deck.check import token_path

        document = json.loads(Path(token_path()).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - no token yet is the ordinary case
        return []
    out: list[tuple[str, str]] = []
    if isinstance(document, dict):
        for key in ("access_token", "refresh_token"):
            value = document.get(key)
            if isinstance(value, str) and len(value) >= 8:
                out.append((f"the stored token's {key}", value))
    return out


def secret_findings(text: str, secrets: Sequence[Secret]) -> list[str]:
    """Which secrets appear in `text`, named. Never carries a value."""
    return [secret.name for secret in secrets if secret.value and secret.value in text]


def redact(text: str, secrets: Sequence[Secret]) -> str:
    """`text` with every known secret value replaced by a marker."""
    out = text
    for secret in secrets:
        if secret.value:
            out = out.replace(secret.value, "<redacted: a credential was here>")
    return out


# --------------------------------------------------------------------------- #
# Gate 4 -- no fetched Spotify content is persisted either
# --------------------------------------------------------------------------- #
_URI_RE: Final = re.compile(
    r"spotify:(?:track|album|artist|episode|show|playlist):([0-9A-Za-z]{22})"
)
_LINK_RE: Final = re.compile(
    r"open\.spotify\.com/(?:\w+/)?(?:track|album|artist|episode|show|playlist)/([0-9A-Za-z]{22})"
)
# 22 base62 characters carrying at least one digit and at least one letter --
# the shape of a Spotify id, without flagging every 22-letter English phrase.
_ID_RE: Final = re.compile(
    r"\b(?=[0-9A-Za-z]{22}\b)(?=[0-9A-Za-z]*[0-9])(?=[0-9A-Za-z]*[A-Za-z])[0-9A-Za-z]{22}\b"
)


def spotify_content_findings(text: str, *, allow_ids: Sequence[str] = ()) -> list[str]:
    """Spotify identities in `text` that this document is not allowed to carry.

    One identity is allowed: the playlist this run created or extended. It is
    the owner's own, and naming it is the whole point -- the acceptance
    criterion is that *that* playlist exists. Everything else -- a track URI, an
    artist link, a bare id from a search result -- is fetched Spotify content
    and has no business being written to disk.

    One identity yields one finding. The patterns run most-specific first, so a
    URI is reported as a URI rather than three times over as a URI, a link and a
    bare id -- the count of findings is a count of leaked identities.
    """
    allowed = {value for value in allow_ids if value}
    findings: list[str] = []
    seen: set[str] = set()
    for pattern, description in (
        (_URI_RE, "a Spotify URI"),
        (_LINK_RE, "an open.spotify.com link"),
        (_ID_RE, "something shaped like a Spotify id"),
    ):
        for identity in pattern.findall(text):
            if identity in allowed or identity in seen:
                continue
            seen.add(identity)
            findings.append(f"{description} ({identity[:4]}...) not in the allowed set")
    return findings


# --------------------------------------------------------------------------- #
# Gate 1 -- the playlist is verified independently
# --------------------------------------------------------------------------- #
def playlist_verdict(items_document: Any) -> tuple[bool, str]:
    """Whether a `playlist items` result proves at least one item is there.

    Deliberately strict about the difference between "zero items" and "I could
    not tell": a document that does not carry a `returned` count fails, because
    a proof that cannot read the answer has not read the answer.
    """
    if not isinstance(items_document, dict):
        return False, "`playlist items` returned no JSON object to read."
    if isinstance(items_document.get("error"), dict):
        code = items_document["error"].get("code", "unknown")
        return False, f"`playlist items` refused `{code}`."
    returned = items_document.get("returned")
    items = items_document.get("items")
    if not isinstance(returned, int) or isinstance(returned, bool):
        return False, "`playlist items` carried no `returned` count, so the playlist could not be verified."
    if isinstance(items, list) and len(items) != returned:
        return False, f"`playlist items` said returned={returned} but carried {len(items)} item(s)."
    if returned < 1:
        return False, "the playlist exists but holds 0 items -- `apply` added nothing."
    return True, f"the playlist holds {returned} item(s)."


def apply_result(run: Run) -> tuple[Any, str | None, str]:
    """The result document `apply` produced, whatever exit code it used.

    Returns `(result, partial_code, note)`. `cli.v1` Core 6 makes
    `partial_result` a documented outcome that carries the whole result
    alongside the refusal -- the playlist was created and the items were added,
    and exit 2 says "read this before you believe it is finished". Any other
    non-zero exit is a failure with no result to read.
    """
    document = run.document
    if run.returncode == 0:
        return document, None, "apply exited 0."
    if isinstance(document, dict) and isinstance(document.get("error"), dict):
        error = document["error"]
        code = error.get("code")
        if code == "partial_result" and isinstance(error.get("result"), dict):
            return (
                error["result"],
                "partial_result",
                "apply exited 2 with a documented `partial_result`: the playlist "
                "was written and the completeness block says what did not land.",
            )
        return None, None, f"apply refused `{code}` (exit {run.returncode})."
    return None, None, f"apply exited {run.returncode} with no readable JSON document."


# --------------------------------------------------------------------------- #
# Preconditions -- gate 2
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Preconditions:
    client_id_source: str | None
    provider: str | None
    provider_credential_var: str | None
    engine_installed: bool
    problems: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.problems


def preconditions() -> Preconditions:
    """What this machine has, and what it is missing, for a live round trip."""
    problems: list[str] = []

    # Asked the way `check` asks it: environment first, then the config file.
    # An env-only look would report "no client id" on every machine whose owner
    # ran `music-deck setup --client-id`, which is the documented way to set one
    # -- a precondition failure for a precondition that is actually met.
    client_id_source: str | None = None
    try:
        from music_deck.auth import resolve_client_id

        _client_id, client_id_source = resolve_client_id()
    except Exception:  # noqa: BLE001 - reported below as "no client id"
        client_id_source = None
    if client_id_source is None:
        problems.append(
            "No Spotify client id in any of the places music-deck reads: "
            "MUSIC_DECK_CLIENT_ID, SPOTIFY_CLIENT_ID, or `client_id` in the "
            "config file. Run `music-deck setup --client-id <your client id>` "
            "to write it, or `music-deck setup --guide` for the steps to "
            "register your own Development Mode app. music-deck ships no "
            "credential of its own."
        )

    provider: str | None = None
    credential_var: str | None = None
    engine = False
    try:
        from music_deck.intelligence import (
            ENGINE_INSTALL_HINT,
            available_providers,
            credential_env_var,
            credentialled_providers,
            engine_installed,
            missing_package,
        )

        usable = available_providers()
        credentialled = credentialled_providers()
        engine = engine_installed()
        if usable:
            provider = usable[0]
            credential_var = credential_env_var(provider)
        elif credentialled:
            provider = credentialled[0]
            credential_var = credential_env_var(provider)
            problems.append(
                f"Provider {provider!r} has a credential here but its SDK "
                f"({missing_package(provider)}) is not installed. Install the extra: "
                f'uv pip install "music-deck[{provider}]".'
            )
        else:
            problems.append(
                "No model provider credential in the environment. `plan` is the one "
                "model-backed verb; set ANTHROPIC_API_KEY (or OPENAI_API_KEY, "
                "GOOGLE_API_KEY, AZURE_OPENAI_API_KEY)."
            )
        if not engine:
            # The library's own hint, never a second copy of it: music-deck is
            # installed with `uv tool install`, and a `uv pip install` line has
            # no way to name the tool's virtualenv, so it is unusable by exactly
            # the reader who needs it. Taking the string from the library also
            # means this script cannot drift to a stale engine ref again.
            problems.append(
                "The amplifier-agent engine is not installed, so `plan` will refuse "
                f"with exit 3 before it builds a prompt. Install it: {ENGINE_INSTALL_HINT}"
            )
    except Exception as exc:  # noqa: BLE001 - report it, never guess past it
        problems.append(f"music_deck could not be imported here: {type(exc).__name__}: {exc}")

    return Preconditions(
        client_id_source=client_id_source,
        provider=provider,
        provider_credential_var=credential_var,
        engine_installed=engine,
        problems=tuple(problems),
    )


# --------------------------------------------------------------------------- #
# The round trip
# --------------------------------------------------------------------------- #
@dataclass
class Step:
    """One step of the round trip, and what it left behind."""

    name: str
    ok: bool
    detail: str
    command: str = ""
    evidence: str = ""


@dataclass
class RoundTrip:
    steps: list[Step] = field(default_factory=list)
    plan_document: Any = None
    transcript: list[str] = field(default_factory=list)
    boundary_verdict: str = ""
    apply_document: Any = None
    partial_code: str | None = None
    playlist: dict[str, Any] = field(default_factory=dict)
    item_count: int | None = None

    @property
    def ok(self) -> bool:
        return bool(self.steps) and all(step.ok for step in self.steps)

    def add(self, step: Step) -> Step:
        self.steps.append(step)
        marker = "PASS" if step.ok else "FAIL"
        print(f"  [{marker}] {step.name}: {step.detail}", flush=True)
        return step


def round_trip(
    base: Sequence[str], *, brief: str, plan_path: Path, force_login: bool
) -> RoundTrip:
    """Drive the whole round trip, stopping at the first step that fails."""
    trip = RoundTrip()

    # -- check: the deterministic smoke test, and the auth facts in one place --
    run = run_cli(base, ["check"])
    trip.add(
        Step(
            "check",
            run.returncode == 0,
            (
                "exited 0 and reported the tool's state"
                if run.returncode == 0
                else f"exited {run.returncode}; `cli.v1` Core 2 says check always exits 0"
            ),
            run.command,
            _fenced(run.stdout or run.stderr, "json"),
        )
    )
    if not trip.ok:
        return trip

    # -- login: the one interactive verb (boundary.v1 Core 5) ------------------
    signed_in = run_cli(base, ["whoami"])
    if signed_in.returncode == 0 and not force_login:
        trip.add(
            Step(
                "login",
                True,
                "already signed in -- `whoami` answered, so no browser round trip "
                "was needed (run with --force-login to authorise again)",
                signed_in.command,
                _fenced(signed_in.stdout, "json"),
            )
        )
    else:
        print(
            "\n  A browser will open for Spotify's authorisation page. "
            "This is the one interactive step.\n",
            flush=True,
        )
        run = run_cli(
            base,
            ["login", "--timeout", str(LOGIN_BROWSER_WAIT_S)],
            timeout=LOGIN_TIMEOUT_S,
            interactive=True,
        )
        ok = run.returncode == 0
        trip.add(
            Step(
                "login",
                ok,
                "authorised via PKCE and wrote the token"
                if ok
                else f"exited {run.returncode} ({run.error_code or 'no error code'})",
                run.command,
                _fenced(run.stdout, "json"),
            )
        )
        if not trip.ok:
            return trip

    # -- plan: a model-backed verb; no Spotify request at all ------------------
    run = run_cli(
        base, ["plan", brief, "--output", str(plan_path)], timeout=PLAN_TIMEOUT_S
    )
    document = run.document
    ok = run.returncode == 0 and isinstance(document, dict) and "plan" in document
    trip.add(
        Step(
            "plan",
            ok,
            "the model returned a plan.v1 document"
            if ok
            else f"exited {run.returncode} ({run.error_code or 'no error code'})",
            run.command,
            _fenced(run.stdout if not ok else "", "json"),
        )
    )
    if not ok:
        return trip

    trip.plan_document = document["plan"]
    raw_transcript = document.get("transcript")
    trip.transcript = [entry for entry in raw_transcript if isinstance(entry, str)] if isinstance(raw_transcript, list) else []

    # -- boundary.v1 Core 2, checked against the tool's own published output ---
    # No `credentials` argument: the check gathers this machine's real client ID
    # and stored tokens itself, which is the whole point of running it here
    # rather than against fixtures.
    ok, verdict = boundary_check(trip.transcript)
    trip.boundary_verdict = verdict
    trip.add(Step("boundary.v1 Core 2", ok, verdict.splitlines()[0]))
    if not ok:
        return trip

    # -- apply: deterministic, no model -----------------------------------------
    run = run_cli(base, ["apply", str(plan_path)], timeout=DETERMINISTIC_TIMEOUT_S)
    result, partial, note = apply_result(run)
    trip.apply_document = result
    trip.partial_code = partial
    playlist = result.get("playlist") if isinstance(result, dict) else None
    ok = isinstance(playlist, dict) and isinstance(playlist.get("id"), str)
    trip.add(
        Step(
            "apply",
            ok,
            note if ok else f"{note} No playlist to verify.",
            run.command,
            _fenced(run.stdout if not ok else "", "json"),
        )
    )
    if not ok:
        return trip
    trip.playlist = dict(playlist)  # type: ignore[arg-type]

    # -- the independent verification: apply's own claim is not the evidence ---
    run = run_cli(base, ["playlist", "items", trip.playlist["id"], "--limit", "50"])
    ok, reason = playlist_verdict(run.document)
    if ok and isinstance(run.document, dict):
        trip.item_count = run.document.get("returned")
    trip.add(Step("the playlist exists, with >= 1 item", ok, reason, run.command))
    return trip


def boundary_check(
    transcript: Sequence[str], *, credentials: Any = None
) -> tuple[bool, str]:
    """Run the library's own credential check over the transcript.

    `boundary.v1` Core 2: no credential ever enters a prompt -- not the access
    token, the refresh token, or the client ID. `music_deck.prompt_boundary`
    looks for all three by exact value (this machine's own, when `credentials`
    is left None) and by shape, so a credential it was never handed is caught
    too. Spotify content in a prompt is Core 1's business and Core 1 permits it:
    a transcript full of search results passes here, deliberately.
    """
    if not transcript:
        return False, (
            "`plan` published no transcript, so `boundary.v1` Core 2 cannot be "
            "checked from its output at all (Core 3 requires the transcript)."
        )
    try:
        from music_deck.prompt_boundary import check_plan_transcript

        report = check_plan_transcript(transcript, credentials=credentials)
    except Exception as exc:  # noqa: BLE001
        return False, f"the boundary check could not run: {type(exc).__name__}: {exc}"
    return report.ok, report.describe()


# --------------------------------------------------------------------------- #
# The evidence document
# --------------------------------------------------------------------------- #
def render_evidence(
    trip: RoundTrip,
    *,
    brief: str,
    base: Sequence[str],
    pre: Preconditions,
    when: str,
    commit: str,
) -> str:
    """The document a reviewer reads. Facts only, and only facts observed."""
    verdict = "PASS" if trip.ok else "FAIL"
    if trip.ok and trip.partial_code:
        verdict = "PASS (with a documented `partial_result`)"

    lines = [
        f"# music-deck live round trip -- {when}",
        "",
        f"**Verdict:** {verdict}",
        "",
        "A `login` -> `plan` -> `apply` -> verify run of the binary named below, "
        "recorded by `evidence/live_round_trip.py`. Run against the owner's own "
        "Spotify Development Mode app and their own model provider, this is the "
        "one `boundary.v1` conformance assert marked *owner-only; can't check by "
        "machine*.",
        "",
        "**What this is evidence of is the binary named under *How this run was "
        "made*.** If that is not a real installed `music-deck` talking to real "
        "Spotify, this document is a rehearsal of the script and nothing more.",
        "",
        "## How this run was made",
        "",
        f"- Produced by `evidence/live_round_trip.py` on {when}.",
        f"- Repository commit: `{commit}`.",
        f"- Binary invoked as: `{' '.join(base)}`.",
        f"- Spotify client id read from: `{pre.client_id_source}`.",
        f"- Model provider: `{pre.provider}`, credential read from "
        f"`{pre.provider_credential_var}` (the value appears nowhere in this file).",
        f"- Brief given to `plan`: `{brief}`",
        "",
        "## Steps",
        "",
        "| Step | Result | What happened |",
        "|---|---|---|",
    ]
    for step in trip.steps:
        lines.append(
            f"| `{step.name}` | {'PASS' if step.ok else 'FAIL'} | "
            f"{step.detail.replace('|', '/')} |"
        )

    lines += ["", "The exact commands, in order:", "", "```"]
    lines += [step.command for step in trip.steps if step.command]
    lines += ["```", ""]

    lines += [
        "## The plan (`plan.v1`)",
        "",
        "By `plan.v1` Core 5 a plan carries no Spotify content other than a "
        "caller-supplied `target.playlist_id`, which is why it can be reproduced "
        "here whole.",
        "",
        _fenced(json.dumps(trip.plan_document, indent=2), "json"),
        "",
        "## The prompt transcript (`boundary.v1` Core 3)",
        "",
        "Every prompt sent to the model, verbatim, exactly as `plan` published "
        "it. Read it and you can confirm `boundary.v1` Core 2 yourself: no "
        "access token, no refresh token, no client ID. Under Core 1 a prompt "
        "*may* carry what Spotify returned -- which is exactly why this section "
        "is here to be read rather than taken on trust.",
        "",
    ]
    for index, prompt in enumerate(trip.transcript):
        lines += [f"Prompt {index}:", "", _fenced(prompt, ""), ""]

    lines += [
        "### The boundary check over that transcript",
        "",
        _fenced(trip.boundary_verdict, ""),
        "",
        "## Per-step completeness (`plan.v1` Core 7)",
        "",
    ]
    lines += _completeness_table(trip.apply_document)

    lines += [
        "",
        "## The playlist",
        "",
        f"- id: `{trip.playlist.get('id', '(none)')}`",
        f"- name: {trip.playlist.get('name', '(not reported -- an existing target)')}",
        f"- link: {_link(trip.playlist)}",
        f"- created by this run: {trip.playlist.get('created', 'unknown')}",
        f"- items read back with `music-deck playlist items`: "
        f"{trip.item_count if trip.item_count is not None else 'not verified'}",
        "",
        "The item count is read back from Spotify after `apply` finished. "
        "`apply`'s own report is not the evidence; this is.",
        "",
        "## What this document deliberately does not contain",
        "",
        "- No provider credential and no Spotify token. Both are searched for "
        "before this file is written, and a hit refuses the write.",
        "- No track, artist or album fetched from Spotify -- not a title, not an "
        "id, not a URI. Only counts, and the one playlist named above. This is "
        "this script's own line, not `boundary.v1` Core 8's: since 2026-09-06 "
        "Core 8 permits an artifact the caller asked for to carry Spotify "
        "content. An evidence file gets held to the stricter rule anyway.",
        "",
    ]
    if trip.partial_code:
        lines += [
            "## About the `partial_result`",
            "",
            "`apply` exited 2 carrying a `partial_result`. Per `cli.v1` Core 6 "
            "that is a documented partial completion, never a silent truncation: "
            "the playlist was created and what did land is in it, and the "
            "completeness block above says which step asked for more than it kept.",
            "",
        ]
    return "\n".join(lines) + "\n"


def _completeness_table(document: Any) -> list[str]:
    if not isinstance(document, dict) or not isinstance(document.get("steps"), list):
        return ["(no completeness block was reported.)"]
    rows = [
        "| Step | type | requested | fetched | kept |",
        "|---|---|---|---|---|",
    ]
    for report in document["steps"]:
        if not isinstance(report, dict):
            continue
        block = report.get("completeness", {})
        rows.append(
            f"| {report.get('step')} | {report.get('type')} | "
            f"{block.get('requested')} | {block.get('fetched')} | {block.get('kept')} |"
        )
    totals = document.get("completeness")
    if isinstance(totals, dict):
        rows += [
            "",
            f"Totals: requested {totals.get('requested')}, fetched "
            f"{totals.get('fetched')}, kept {totals.get('kept')}, added "
            f"{totals.get('added')}. Under-fulfilled steps: "
            f"{totals.get('under_fulfilled')}.",
        ]
    return rows


def _link(playlist: dict[str, Any]) -> str:
    urls = playlist.get("external_urls")
    if isinstance(urls, dict) and isinstance(urls.get("spotify"), str):
        return urls["spotify"]
    return "(none reported)"


def _fenced(text: str, language: str) -> str:
    body = (text or "").rstrip()
    return f"```{language}\n{body}\n```"


def write_evidence(
    text: str, *, path: Path, secrets: Sequence[Secret], allow_ids: Sequence[str]
) -> tuple[bool, str]:
    """Write private local evidence, or refuse and say which gate stopped it.

    Redaction happens first and the scan happens after, so the scan is checking
    what will actually be on disk -- not a copy that was cleaned separately.
    Credential redaction is not a PII audit. The document is not safe to publish.
    """
    cleaned = redact(text, secrets)

    leaked = secret_findings(cleaned, secrets)
    if leaked:
        return False, (
            "REFUSED to write the evidence file: it still carries "
            f"{len(leaked)} secret(s) after redaction ({', '.join(leaked)}). "
            "No credential is ever written to disk by this script."
        )

    content = spotify_content_findings(cleaned, allow_ids=allow_ids)
    if content:
        return False, (
            "REFUSED to write the evidence file: it carries Spotify content it "
            f"is not allowed to persist -- {'; '.join(content[:5])}"
            f"{' and more' if len(content) > 5 else ''}."
        )

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary: str | None = None
    try:
        # NamedTemporaryFile creates mode 0600; atomic replacement also fixes
        # permissions on an existing output without exposing a partial document.
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as output:
            temporary = output.name
            output.write(cleaned)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            os.unlink(temporary)
    return True, f"wrote {path}"


# --------------------------------------------------------------------------- #
# --self-test: the four gates, with no account, no provider and no network
# --------------------------------------------------------------------------- #
def self_test() -> int:
    """Exercise every honesty gate against synthetic inputs.

    This is the part of the script a lane can run and a reviewer can repeat.
    It proves the gates *refuse*: that an empty playlist fails, that a leaked
    credential is caught, that fetched Spotify content is not written to the
    evidence file, and that a transcript carrying a credential fails the
    boundary check while one carrying Spotify content passes it. It proves
    nothing at all about Spotify -- that is what the live run is for.
    """
    cases: list[tuple[str, bool, str]] = []

    def case(name: str, passed: bool, detail: str = "") -> None:
        cases.append((name, passed, detail))

    # -- gate 1: the playlist verdict ---------------------------------------
    ok, reason = playlist_verdict({"returned": 0, "items": []})
    case("an empty playlist FAILS", ok is False and "0 items" in reason, reason)

    ok, reason = playlist_verdict({"returned": 3, "items": [{}, {}, {}]})
    case("a playlist with 3 items PASSES", ok is True, reason)

    ok, reason = playlist_verdict({"items": [{}]})
    case("a result with no `returned` count FAILS", ok is False, reason)

    ok, reason = playlist_verdict({"returned": 2, "items": [{}]})
    case("a count that disagrees with the items FAILS", ok is False, reason)

    ok, reason = playlist_verdict({"error": {"code": "playlist_items_unavailable"}})
    case("a refusal envelope FAILS", ok is False, reason)

    ok, reason = playlist_verdict("not a document")
    case("a non-document FAILS", ok is False, reason)

    # -- apply's two documented outcomes ------------------------------------
    good = Run(("music-deck", "apply"), 0, json.dumps({"playlist": {"id": "x"}}), "")
    result, partial, _ = apply_result(good)
    case("apply exit 0 yields its result", result == {"playlist": {"id": "x"}} and partial is None)

    envelope = {
        "error": {
            "code": "partial_result",
            "message": "under-fulfilled",
            "remedy": "widen the search",
            "result": {"playlist": {"id": "y"}},
        }
    }
    partial_run = Run(("music-deck", "apply"), 2, json.dumps(envelope), "")
    result, partial, note = apply_result(partial_run)
    case(
        "apply exit 2 `partial_result` yields the result it carries",
        result == {"playlist": {"id": "y"}} and partial == "partial_result",
        note,
    )

    bad = Run(("music-deck", "apply"), 2, json.dumps({"error": {"code": "invalid_plan"}}), "")
    result, partial, note = apply_result(bad)
    case("apply exit 2 `invalid_plan` yields no result", result is None and partial is None, note)

    # -- gate 3: secrets -----------------------------------------------------
    fake = [Secret("environment ANTHROPIC_API_KEY", "sk-ant-THIS-IS-NOT-A-REAL-KEY-000")]
    leaky = "the run used sk-ant-THIS-IS-NOT-A-REAL-KEY-000 as its credential"
    found = secret_findings(leaky, fake)
    case(
        "a leaked credential is caught, by name only",
        found == ["environment ANTHROPIC_API_KEY"] and "sk-ant" not in " ".join(found),
        str(found),
    )
    cleaned = redact(leaky, fake)
    case(
        "redact removes the value",
        "sk-ant-THIS-IS-NOT-A-REAL-KEY-000" not in cleaned and secret_findings(cleaned, fake) == [],
        cleaned,
    )
    case("a clean document has no secret findings", secret_findings("nothing to see", fake) == [])

    # -- gate 4: fetched Spotify content -------------------------------------
    allowed = "37i9dQZF1DXcBWIGoYBM5M"
    track = "4cOdK2wGLETKBW3PvgPWqT"
    case(
        "a track URI is caught",
        len(spotify_content_findings(f"spotify:track:{track}", allow_ids=[allowed])) == 1,
    )
    case(
        "a track link is caught",
        len(spotify_content_findings(f"https://open.spotify.com/track/{track}", allow_ids=[allowed])) == 1,
    )
    case(
        "a bare id is caught",
        len(spotify_content_findings(f"the id is {track}", allow_ids=[allowed])) == 1,
    )
    case(
        "two different leaked identities are two findings",
        len(
            spotify_content_findings(
                f"spotify:track:{track} and spotify:artist:1dfeR4HaWDbWqFHLkxsg1d",
                allow_ids=[allowed],
            )
        )
        == 2,
    )
    case(
        "the allowed playlist id and its link pass",
        spotify_content_findings(
            f"playlist `{allowed}` at https://open.spotify.com/playlist/{allowed}",
            allow_ids=[allowed],
        )
        == [],
    )
    case(
        "ordinary prose is not flagged",
        spotify_content_findings(
            "three upbeat 90s guitar songs for a Saturday morning", allow_ids=[allowed]
        )
        == [],
    )

    # -- gate 2 + gate 4 together: the write refuses --------------------------
    with tempfile.TemporaryDirectory() as scratch:
        target = Path(scratch) / "refused.md"
        wrote, message = write_evidence(
            f"a track: spotify:track:{track}",
            path=target,
            secrets=[],
            allow_ids=[allowed],
        )
        case(
            "write_evidence REFUSES a document carrying a track URI",
            wrote is False and not target.exists(),
            message,
        )

        wrote, message = write_evidence(
            "a clean document naming only the playlist "
            f"`{allowed}` and its counts",
            path=target,
            secrets=fake,
            allow_ids=[allowed],
        )
        case("write_evidence writes a clean document", wrote is True and target.exists(), message)

        secret_target = Path(scratch) / "redacted.md"
        wrote, message = write_evidence(
            leaky, path=secret_target, secrets=fake, allow_ids=[allowed]
        )
        case(
            "write_evidence redacts a credential rather than persisting it",
            wrote is True
            and "sk-ant-THIS-IS-NOT-A-REAL-KEY-000" not in secret_target.read_text(encoding="utf-8"),
            message,
        )

    # -- boundary.v1 Core 2, over a real assembled prompt ---------------------
    # The pair, inverted on 2026-09-06 with the clause: Spotify content in a
    # prompt now PASSES (Core 1), a credential in a prompt FAILS (Core 2). The
    # credentials below are shape-real and value-fake, shipped in
    # `music_deck.testing`, so this gate is exercised without a real token.
    try:
        from music_deck.prompt_boundary import ACCESS_TOKEN, CLIENT_ID, REFRESH_TOKEN
        from music_deck.testing import (
            FAKE_ACCESS_TOKEN,
            FAKE_CLIENT_ID,
            FAKE_REFRESH_TOKEN,
            SPOTIFY_SEARCH_RESULTS,
            credential_leak_prompt,
        )
        from music_deck.verbs.plan import assemble_prompt

        brief = "three upbeat 90s guitar songs for a Saturday morning"
        fakes = {
            ACCESS_TOKEN: FAKE_ACCESS_TOKEN,
            REFRESH_TOKEN: FAKE_REFRESH_TOKEN,
            CLIENT_ID: FAKE_CLIENT_ID,
        }
        clean = assemble_prompt(brief)
        ok, verdict = boundary_check([clean], credentials=fakes)
        case("a clean transcript keeps boundary.v1 Core 2", ok is True, verdict.splitlines()[0])

        with_content = clean + "\n\n" + SPOTIFY_SEARCH_RESULTS
        ok, verdict = boundary_check([with_content], credentials=fakes)
        case(
            "a transcript carrying fetched Spotify content PASSES (Core 1)",
            ok is True,
            verdict.splitlines()[0],
        )

        for kind, value in fakes.items():
            ok, verdict = boundary_check(
                [credential_leak_prompt(brief, value)], credentials=fakes
            )
            leaked = value not in verdict
            case(
                f"a transcript carrying {kind} BREAKS it, by name",
                ok is False and kind in verdict and leaked,
                verdict.splitlines()[0],
            )

        ok, verdict = boundary_check(
            [credential_leak_prompt(brief, FAKE_ACCESS_TOKEN)], credentials={}
        )
        case(
            "a credential the check was never given is still caught, by shape",
            ok is False,
            verdict.splitlines()[0],
        )

        ok, verdict = boundary_check([])
        case("an absent transcript FAILS rather than passing vacuously", ok is False, verdict.splitlines()[0])
    except Exception as exc:  # noqa: BLE001
        case("the boundary check is importable", False, f"{type(exc).__name__}: {exc}")

    print("evidence/live_round_trip.py --self-test")
    print("Exercises the honesty gates with no Spotify account, no provider, no network.\n")
    failures = 0
    for name, passed, detail in cases:
        marker = "PASS" if passed else "FAIL"
        line = f"  [{marker}] {name}"
        if detail and not passed:
            line += f"\n         {detail}"
        elif detail:
            line += f"\n         -> {detail}"
        print(line)
        failures += 0 if passed else 1

    print()
    if failures:
        print(f"FAIL: {failures} of {len(cases)} gate checks did not hold.")
        return EXIT_FAIL
    print(
        f"PASS: all {len(cases)} gate checks hold. An empty playlist cannot pass, a "
        "leaked credential cannot be written, fetched Spotify content cannot be "
        "written, and a transcript carrying any of the three credentials fails "
        "boundary.v1 Core 2 by name -- while a transcript carrying Spotify "
        "search results passes, as Core 1 now allows.\n"
        "This says nothing about Spotify: only the owner's live run does that."
    )
    return EXIT_PASS


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def _commit() -> str:
    try:
        out = subprocess.run(  # noqa: S603
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception:  # noqa: BLE001
        return "unknown"
    return (out.stdout or "").strip() or "unknown"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="live_round_trip.py",
        description=(
            "The owner's live round trip: login -> plan -> apply -> the playlist "
            "exists. Writes private .private/evidence/live-round-trip-<date>.md."
        ),
    )
    parser.add_argument(
        "--brief", default=DEFAULT_BRIEF, help="The brief handed to `music-deck plan`."
    )
    parser.add_argument(
        "--out",
        default=None,
        help=(
            "Where to write private evidence. Default: "
            ".private/evidence/live-round-trip-<date>.md. "
            "Custom destinations must also stay out of version control and uploads."
        ),
    )
    parser.add_argument(
        "--music-deck", default=None, help="Path to the music-deck binary to exercise."
    )
    parser.add_argument(
        "--force-login",
        action="store_true",
        help="Authorise again even if a valid token is already stored.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Exercise the honesty gates offline and exit. Needs no account and no provider.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(sys.argv[1:] if argv is None else argv))

    if args.self_test:
        return self_test()

    when = date.today().isoformat()
    destination = Path(args.out) if args.out else EVIDENCE_DIR / f"live-round-trip-{when}.md"

    print("music-deck live round trip -- login -> plan -> apply -> the playlist exists\n")

    pre = preconditions()
    if not pre.ok:
        print("This run needs things this machine does not have:\n")
        for problem in pre.problems:
            print(f"  - {problem}")
        print(
            "\nNothing ran and no evidence file was written. This proof is the "
            "owner's to perform: it needs their own Spotify Development Mode app, "
            "their Premium account, a browser, and a model provider credential.\n"
            "Run `python evidence/live_round_trip.py --self-test` to exercise the "
            "script's own gates without any of that."
        )
        return EXIT_PRECONDITION

    base = resolve_cli(args.music_deck)
    print(f"  binary: {' '.join(base)}")
    print(f"  client id from: {pre.client_id_source}")
    print(f"  provider: {pre.provider} (credential from {pre.provider_credential_var})")
    print(f"  brief: {args.brief}\n")

    # The plan goes to a scratch directory rather than into evidence/: the
    # finished document reproduces it whole, so a copy beside the record would
    # be litter that has to be gitignored. The path is printed, so a run that
    # fails at `apply` leaves something to retry with.
    plan_path = Path(tempfile.mkdtemp(prefix="music-deck-round-trip-")) / "plan.json"
    print(f"  plan will be written to: {plan_path}\n")

    trip = round_trip(
        base, brief=args.brief, plan_path=plan_path, force_login=args.force_login
    )

    document = render_evidence(
        trip, brief=args.brief, base=base, pre=pre, when=when, commit=_commit()
    )
    wrote, message = write_evidence(
        document,
        path=destination,
        secrets=secrets_present(),
        allow_ids=[str(trip.playlist.get("id", ""))],
    )
    print(f"\n  {message}")

    if not trip.ok:
        print(
            "\nFAIL: the round trip did not complete. The step table above names "
            "the step that stopped it."
            + ("" if wrote else " The evidence file was refused as well.")
        )
        return EXIT_FAIL
    if not wrote:
        print(
            "\nFAIL: the round trip completed but its evidence could not be written "
            "safely, so there is no evidence. Treat this as a failure."
        )
        return EXIT_FAIL

    print(
        f"\nPASS: playlist `{trip.playlist.get('id')}` exists and holds "
        f"{trip.item_count} item(s). Evidence: {destination}"
    )
    if trip.partial_code:
        print(
            "      `apply` reported a documented `partial_result`; the completeness "
            "block in the evidence file says which step asked for more than it kept."
        )
    print(
        "      Keep this evidence private; do not commit or upload it. Publish only "
        "a separately reviewed anonymous summary of the checks and counts. "
        "Delete the playlist from Spotify whenever you like."
    )
    return EXIT_PASS


if __name__ == "__main__":
    raise SystemExit(main())
