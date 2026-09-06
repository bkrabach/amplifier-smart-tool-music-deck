"""`setup` speaks to its reader, and never asks a question.

Contracts served: ``cli.v1`` Core 8 as amended 2026-09-06 ("`setup` gets a new
caller from nothing to ready, without prompting. It reports what is configured,
what is missing, and the steps for that gap -- proportional to the gap, not the
whole orientation every run, which is on request"), Core 4 as rewritten the same
day ("Structure what a caller parses; write what a caller reads ... A verb whose
result is guidance writes it for its reader, with ``--json`` for the same content
structured"), Core 1 ("Non-interactive. A run with stdin closed never hangs"),
Core 5 (exit ``2`` for invalid input), and ``boundary.v1`` Core 4 (private file
modes) applied to the config file `setup` writes.

Four claims are asserted the hard way, because each has a plausible-looking way
of being wrong:

* **"never prompts"** is not asserted by reading the source for ``input()``. The
  CLI is run as a real subprocess with stdin closed *and* a wall-clock deadline,
  so a `setup` that waited for a line would fail here as a timeout rather than
  pass quietly on a machine where stdin happened to be a terminal.
* **"config file 0600"** is read back off the filesystem with ``stat`` after the
  write, under a deliberately loose umask -- a write that relied on the caller's
  umask would land 0644 and fail.
* **"the prose and the ``--json`` twin cannot drift"** is not asserted by
  eyeballing a few phrases. Every string the document carries is required to
  reach the prose, whitespace-normalised, over four different shapes of run --
  so a fact added to one form and forgotten in the other fails here.
* **"proportional"** is asserted by *absence*: a caller who already has a model
  provider is checked for never seeing the word. A report that merely reordered
  the same complete orientation would pass a "names the gap" test and fail this
  one.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from music_deck import setup_guide
from music_deck.errors import EXIT_REFUSAL, EXIT_SUCCESS, ErrorCode, MusicDeckError
from music_deck.verbs.setup import (
    normalize_client_id,
    render,
    setup,
    write_client_id,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

GOOD_ID = "0123456789abcdef0123456789abcdef"

# The same regex the upstream conformance kit scrubs the environment with, so a
# provider key in the developer's shell cannot change what these tests observe.
_PROVIDER_ENV_RE = re.compile(
    r"(API_KEY|ACCESS_KEY|SECRET|TOKEN|CREDENTIAL|_KEY)$", re.IGNORECASE
)


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """A fresh config and state directory, and no client ID in the environment."""
    config = tmp_path / "config"
    state = tmp_path / "state"
    monkeypatch.setenv("MUSIC_DECK_CONFIG_DIR", str(config / "music-deck"))
    monkeypatch.setenv("MUSIC_DECK_STATE_DIR", str(state / "music-deck"))
    for name in ("MUSIC_DECK_CLIENT_ID", "SPOTIFY_CLIENT_ID", "MUSIC_DECK_REDIRECT_URI"):
        monkeypatch.delenv(name, raising=False)
    return config, state


def _clean_env(**overrides: str) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not _PROVIDER_ENV_RE.search(key)
    }
    env.pop("MUSIC_DECK_CLIENT_ID", None)
    env.pop("SPOTIFY_CLIENT_ID", None)
    env.update(overrides)
    return env


def run_cli(*args: str, cwd: Path, timeout: float = 20.0, **env: str):
    """Run the real binary with **stdin closed** and a wall-clock deadline.

    ``stdin=DEVNULL`` plus ``timeout`` together are the assertion: a verb that
    waited for input would raise ``TimeoutExpired`` here, which is a failure, not
    a pass.
    """
    return subprocess.run(
        [sys.executable, "-m", "music_deck.cli", *args],
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_clean_env(PYTHONPATH=str(REPO_ROOT / "src"), **env),
    )


# --------------------------------------------------------------------------- #
# Core 8 -- reports what is missing, and carries the registration steps
# --------------------------------------------------------------------------- #
def test_setup_with_nothing_configured_reports_and_exits_zero(isolated):
    """Reporting what is missing IS the success, exactly as `check`'s is."""
    result = setup()

    assert result["action"] == "report"
    assert result["ready"] is False
    assert result["have"] == []  # nothing configured, so nothing to report as such
    assert {gap["what"] for gap in result["missing"]} >= {"client_id", "authorization"}
    assert result["next_command"] == "music-deck setup --client-id <your client id>"


def test_setup_guide_carries_the_registration_steps_on_request(isolated):
    """Core 8: the whole orientation, "which is on request" -- `setup --guide`."""
    guide = setup(guide=True)["spotify_app"]

    assert [entry["step"] for entry in guide["steps"]] == [1, 2, 3, 4, 5, 6, 7]
    text = json.dumps(guide)
    # The four facts the work item names as load-bearing.
    assert "http://127.0.0.1" in text
    assert "localhost" in text  # named, as the thing NOT to use
    assert "allowlist" in text.lower()
    assert "Premium" in text
    assert "client secret" in text  # the thing never to copy


def test_the_guide_ships_inside_the_package_not_in_the_repository():
    """Core 4: the steps must be "text the installed package carries".

    Asserted structurally: the module that holds them is inside the importable
    package, and the package directory is what ``pyproject.toml`` ships.
    """
    module = Path(setup_guide.__file__).resolve()
    package = (REPO_ROOT / "src" / "music_deck").resolve()

    assert module.parent == package
    assert setup_guide.render().strip()


def test_setup_never_reads_stdin_and_never_hangs(tmp_path):
    """Core 1: "A run with stdin closed never hangs."

    A real subprocess, stdin closed, 20-second deadline. A prompt would time out.
    """
    scratch = tmp_path / "elsewhere"
    scratch.mkdir()
    result = run_cli(
        "setup",
        cwd=scratch,
        MUSIC_DECK_CONFIG_DIR=str(tmp_path / "config"),
        MUSIC_DECK_STATE_DIR=str(tmp_path / "state"),
    )

    assert result.returncode == EXIT_SUCCESS
    # Core 4: guidance is written for its reader, so stdout is prose, not JSON.
    assert result.stdout.startswith("music-deck ")
    assert "are missing:" in result.stdout


def test_setup_show_names_the_three_paths(isolated):
    """`setup --show` names where the config, state, and token live."""
    result = setup(show=True)

    assert result["action"] == "paths"
    for key in ("config_file", "config_dir", "state_dir", "token_file"):
        assert result["paths"][key]
    assert result["paths"]["config_file"].endswith("config.json")
    assert result["paths"]["token_file"].endswith("token.json")


# --------------------------------------------------------------------------- #
# Core 8 -- writes the client ID when given one
# --------------------------------------------------------------------------- #
def test_setup_client_id_writes_the_config_and_names_login_next(isolated):
    result = setup(client_id=GOOD_ID)

    written = Path(result["wrote"]["path"])
    assert json.loads(written.read_text(encoding="utf-8"))["client_id"] == GOOD_ID
    assert result["action"] == "configured"
    assert result["next_command"] == "music-deck login"


def test_the_written_config_is_0600_and_its_directory_0700(isolated, monkeypatch):
    """boundary.v1 Core 4's private-file discipline, applied to the config.

    The umask is deliberately loosened first: a write that leaned on the
    caller's umask would land 0644 and fail here.
    """
    previous = os.umask(0o000)
    try:
        result = setup(client_id=GOOD_ID)
    finally:
        os.umask(previous)

    path = Path(result["wrote"]["path"])
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert result["wrote"]["mode"] == "0600"


def test_check_then_sees_the_client_id_and_names_the_config_file(isolated):
    """The acceptance criterion's round trip: setup writes, `check` reports it."""
    from music_deck.check import check, config_path

    setup(client_id=GOOD_ID)
    fact = check()["client_id"]

    assert fact["present"] is True
    assert str(config_path()) in fact["source"]
    assert fact["length"] == setup_guide.CLIENT_ID_LENGTH


def test_writing_the_client_id_keeps_other_config_keys(isolated):
    """A caller who set `redirect_uri` by hand does not lose it."""
    from music_deck.check import config_path

    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"redirect_uri": "http://[::1]"}), encoding="utf-8")

    setup(client_id=GOOD_ID)
    document = json.loads(path.read_text(encoding="utf-8"))

    assert document["redirect_uri"] == "http://[::1]"
    assert document["client_id"] == GOOD_ID


# --------------------------------------------------------------------------- #
# boundary.v1 Core 4 -- `setup --port` writes the ONE redirect URI
# --------------------------------------------------------------------------- #
def test_setup_port_writes_the_redirect_uri_and_names_it_to_register(isolated):
    """The port a caller picks is a fact about their Spotify registration, so it
    is written the same way, to the same file, at the same mode as the client
    ID -- and the prose then names the string they must go and register."""
    from music_deck.check import check, config_path

    document = setup(port=9000)

    assert document["wrote"]["redirect_uri"] == "http://127.0.0.1:9000"
    assert document["wrote"]["mode"] == "0600"
    stored = json.loads(config_path().read_text(encoding="utf-8"))
    assert stored["redirect_uri"] == "http://127.0.0.1:9000"
    assert stat.S_IMODE(config_path().stat().st_mode) == 0o600

    # One value: what was written is what `check` now reports.
    fact = check()["redirect_uri"]
    assert (fact["value"], fact["port"], fact["conforms"]) == (
        "http://127.0.0.1:9000",
        9000,
        True,
    )

    prose = render(document)
    assert "http://127.0.0.1:9000" in prose
    assert not re.search(r"http://127\.0\.0\.1(?![:\d])", prose), prose


def test_setup_port_keeps_the_client_id_already_in_the_file(isolated):
    """Writing one key never drops the other -- they share one config file."""
    setup(client_id=GOOD_ID)
    setup(port=9100)

    from music_deck.check import config_path

    stored = json.loads(config_path().read_text(encoding="utf-8"))
    assert stored == {"client_id": GOOD_ID, "redirect_uri": "http://127.0.0.1:9100"}


def test_setup_writes_both_in_one_run(isolated):
    document = setup(client_id=GOOD_ID, port=9200)

    assert document["wrote"]["client_id"] == GOOD_ID
    assert document["wrote"]["redirect_uri"] == "http://127.0.0.1:9200"
    prose = render(document)
    assert "client ID and redirect URI written" in prose


@pytest.mark.parametrize("bad", ["0", "70000", "-1", "eight thousand", ""])
def test_an_unusable_port_is_invalid_input_and_names_the_shape(isolated, bad):
    """cli.v1 Core 5: invalid input exits 2. Caught here, not inside a browser
    round trip where the reader cannot see what went wrong."""
    with pytest.raises(MusicDeckError) as caught:
        setup(port=bad)

    assert caught.value.code == ErrorCode.USAGE
    assert caught.value.exit_code == EXIT_REFUSAL
    assert "1 and 65535" in caught.value.remedy


def test_setup_with_nothing_configured_names_the_default_registered_uri(isolated):
    """The acceptance criterion's first case, from the library side."""
    document = setup()

    assert document["redirect_uri"]["value"] == "http://127.0.0.1:8888"
    assert document["redirect_uri"]["source"] == "built-in default"
    prose = render(document)
    assert "http://127.0.0.1:8888" in prose


def test_the_port_round_trip_through_the_real_binary(tmp_path):
    """setup --port writes it; check reports it; both are the installed binary."""
    scratch = tmp_path / "elsewhere"
    scratch.mkdir()
    environment = {
        "MUSIC_DECK_CONFIG_DIR": str(tmp_path / "config"),
        "MUSIC_DECK_STATE_DIR": str(tmp_path / "state"),
    }

    written = run_cli("setup", "--port", "9000", cwd=scratch, timeout=10.0, **environment)
    reported = run_cli("check", cwd=scratch, timeout=10.0, **environment)

    assert written.returncode == EXIT_SUCCESS
    assert "http://127.0.0.1:9000" in written.stdout
    fact = json.loads(reported.stdout)["redirect_uri"]
    assert fact["value"] == "http://127.0.0.1:9000"
    assert fact["port"] == 9000
    assert fact["conforms"] is True
    assert "config file" in fact["source"]


def test_an_unwritable_config_directory_refuses_rather_than_crashing(
    isolated, tmp_path, monkeypatch
):
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv("MUSIC_DECK_CONFIG_DIR", str(blocked / "music-deck"))

    with pytest.raises(MusicDeckError) as caught:
        write_client_id(GOOD_ID)

    assert caught.value.exit_code == EXIT_REFUSAL
    assert caught.value.remedy


# --------------------------------------------------------------------------- #
# Core 4 / Core 5 -- an unusable client ID refuses, naming the shape
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "too-short",
        "0123456789abcdef0123456789abcde",  # 31 characters
        "0123456789abcdef0123456789abcdef0",  # 33 characters
        "0123456789abcdef0123456789abcdeZ",  # right length, not hex
        "https://developer.spotify.com/dashboard/0123456789abcdef",
        "Client ID: 0123456789abcdef0123456789abcdef",
    ],
)
def test_an_obviously_invalid_client_id_refuses_naming_the_shape(bad):
    with pytest.raises(MusicDeckError) as caught:
        normalize_client_id(bad)

    error = caught.value
    assert error.code == ErrorCode.USAGE
    assert error.exit_code == EXIT_REFUSAL  # cli.v1 Core 5: invalid input
    # Core 4: the remedy names what a client ID actually looks like.
    assert "32 hexadecimal characters" in error.remedy
    assert "client secret" in error.remedy


def test_a_valid_client_id_is_accepted_case_insensitively():
    assert normalize_client_id("  " + GOOD_ID.upper() + "  ") == GOOD_ID


def test_the_cli_refuses_a_bad_client_id_with_the_envelope_and_exit_two(tmp_path):
    """The whole refusal, through the real binary: envelope on stdout, exit 2."""
    scratch = tmp_path / "elsewhere"
    scratch.mkdir()
    result = run_cli(
        "setup",
        "--client-id",
        "nope",
        cwd=scratch,
        MUSIC_DECK_CONFIG_DIR=str(tmp_path / "config"),
        MUSIC_DECK_STATE_DIR=str(tmp_path / "state"),
    )

    assert result.returncode == EXIT_REFUSAL
    envelope = json.loads(result.stdout)["error"]
    assert envelope["code"] == ErrorCode.USAGE
    assert "32 hexadecimal characters" in envelope["remedy"]
    # Core 4: nothing was written, because nothing was valid.
    assert not (tmp_path / "config" / "config.json").exists()


def test_setup_is_listed_by_both_help_texts(tmp_path):
    """cli.v1 Core 1: `--help` is the complete listing, and `setup` is in it."""
    scratch = tmp_path / "elsewhere"
    scratch.mkdir()

    complete = run_cli("--help", cwd=scratch)
    terse = run_cli("-h", cwd=scratch)

    assert complete.returncode == EXIT_SUCCESS
    assert terse.returncode == EXIT_SUCCESS
    assert "music-deck setup  (deterministic)" in complete.stdout
    assert "--client-id" in complete.stdout
    assert re.search(r"^  setup\s", terse.stdout, re.MULTILINE)


def test_setup_is_reachable_from_the_library(isolated):
    """cli.v1 Core 7: the library is the tool -- every CLI capability is here."""
    import music_deck

    assert music_deck.setup(show=True)["action"] == "paths"


# --------------------------------------------------------------------------- #
# Core 4 -- prose for its reader, `--json` for the same content structured
# --------------------------------------------------------------------------- #
def _normalise(text: str) -> str:
    """Collapse whitespace, so wrapping cannot count as a difference.

    The prose is wrapped to fit a terminal; the JSON is not. Comparing them
    literally would fail on line breaks alone, which is not drift -- so both
    sides are reduced to their words before anything is compared.
    """
    return " ".join(text.split())


# Two keys in the document are machine identifiers rather than sentences: a
# caller branches on them, no reader reads them. Every *other* string has to
# reach the prose. The test below proves these two really are identifiers
# rather than a convenient exemption for prose somebody forgot to render.
IDENTIFIER_KEYS = {"action", "what"}


def _strings(document, key: str | None = None, path: str = ""):
    """Every string leaf in a document, with the key it sat under."""
    if isinstance(document, dict):
        for name, value in document.items():
            yield from _strings(value, name, f"{path}.{name}" if path else name)
    elif isinstance(document, list):
        for index, item in enumerate(document):
            yield from _strings(item, key, f"{path}[{index}]")
    elif isinstance(document, str):
        yield path, key, document


def _documents(monkeypatch) -> dict[str, dict]:
    """One of every shape `setup` can return, including its conditional parts.

    The last two exist because a document key that only appears sometimes is
    exactly the kind that gets added to the structured form and forgotten in the
    prose: ``note`` (the environment variable that wins over the file just
    written) and the redirect-URI gap, which is the one gap with no command to
    run at the end of it.
    """
    documents = {
        "report": setup(),
        "configured": setup(client_id=GOOD_ID),
        "paths": setup(show=True),
        "guide": setup(guide=True),
    }
    with monkeypatch.context() as patch:
        patch.setenv("MUSIC_DECK_CLIENT_ID", GOOD_ID)
        documents["configured-but-env-wins"] = setup(client_id=GOOD_ID)
    with monkeypatch.context() as patch:
        patch.setenv("MUSIC_DECK_REDIRECT_URI", "http://localhost:8080")
        documents["bad-redirect"] = setup()
    documents["configured-port"] = setup(port=9000)
    with monkeypatch.context() as patch:
        patch.setenv("MUSIC_DECK_REDIRECT_URI", "http://127.0.0.1:9500")
        documents["port-written-but-env-wins"] = setup(port=9000)
    return documents


def test_the_prose_carries_every_fact_the_json_twin_carries(isolated, monkeypatch):
    """Core 4: "with `--json` for the same content structured".

    The structural half of the promise is in the code: ``render`` takes the
    document and nothing else, so the prose cannot invent a fact. This is the
    other half -- nothing the document carries may be dropped on the way to the
    reader -- checked over every shape `setup` has.
    """
    shapes = _documents(monkeypatch)
    # A helper that quietly stopped producing the conditional parts would make
    # this test pass by having nothing to check, so it is checked.
    assert "note" in shapes["configured-but-env-wins"]
    assert any(gap["what"] == "redirect_uri" for gap in shapes["bad-redirect"]["missing"])
    assert shapes["configured-port"]["wrote"]["redirect_uri"] == "http://127.0.0.1:9000"
    assert "note" in shapes["port-written-but-env-wins"]

    missed: list[str] = []
    for shape, document in shapes.items():
        prose = _normalise(render(document))
        for path, key, value in _strings(document):
            if key in IDENTIFIER_KEYS or not value.strip():
                continue
            if _normalise(value) not in prose:
                missed.append(f"{shape}: {path} = {value!r} never reaches the prose")

    assert not missed, "\n".join(missed)


def test_the_exempted_keys_really_are_identifiers_and_not_prose(isolated, monkeypatch):
    """The exemption above is only honest if nothing readable hides behind it."""
    for document in _documents(monkeypatch).values():
        for _, key, value in _strings(document):
            if key in IDENTIFIER_KEYS:
                assert re.fullmatch(r"[a-z][a-z_]*", value), (key, value)


def test_the_json_twin_is_one_document_and_the_default_is_prose(tmp_path):
    """Both shapes, through the real binary, for the same run."""
    scratch = tmp_path / "elsewhere"
    scratch.mkdir()
    environment = {
        "MUSIC_DECK_CONFIG_DIR": str(tmp_path / "config"),
        "MUSIC_DECK_STATE_DIR": str(tmp_path / "state"),
    }

    prose = run_cli("setup", cwd=scratch, timeout=5.0, **environment)
    structured = run_cli("setup", "--json", cwd=scratch, timeout=5.0, **environment)

    assert prose.returncode == EXIT_SUCCESS
    assert structured.returncode == EXIT_SUCCESS
    with pytest.raises(json.JSONDecodeError):
        json.loads(prose.stdout)  # prose, deliberately
    document = json.loads(structured.stdout)  # exactly one JSON document
    assert document["action"] == "report"
    assert {gap["what"] for gap in document["missing"]} >= {"client_id"}


def test_the_prose_names_the_two_facts_that_cost_people_an_afternoon(tmp_path):
    """Core 8's "the steps for that gap", for the gap a new caller actually has.

    The redirect URI and the client-ID-not-secret distinction are the two things
    the evidence says people get wrong, so they are asserted on the *default*
    run -- not on `--guide`, which a new caller has no reason to type.
    """
    scratch = tmp_path / "elsewhere"
    scratch.mkdir()
    result = run_cli(
        "setup",
        cwd=scratch,
        timeout=5.0,
        MUSIC_DECK_CONFIG_DIR=str(tmp_path / "config"),
        MUSIC_DECK_STATE_DIR=str(tmp_path / "state"),
    )
    prose = _normalise(result.stdout)

    assert result.returncode == EXIT_SUCCESS
    # boundary.v1 Core 4: the exact string to register, port and all. The
    # dashboard refuses a portless registration, so prose that named one would
    # send a reader to a form that will not accept what they were told to type.
    assert "http://127.0.0.1:8888" in prose
    assert "never http://localhost" in prose
    assert "the client ID, not the client secret" in prose
    # And nowhere does it name the loopback literal WITHOUT a port: every
    # occurrence is followed by a colon (a real port, or the <n> placeholder).
    assert not re.search(r"http://127\.0\.0\.1(?![:\d])", prose), prose
    # And the one command that closes the gap it just described.
    assert "music-deck setup --client-id <your client id>" in prose


def test_the_report_is_proportional_and_never_mentions_a_provider_it_has(
    isolated, monkeypatch
):
    """Core 8: "proportional to the gap, not the whole orientation every run".

    A caller who has already configured a model provider has no gap there. The
    kit assert says `setup` "stays silent about what is not" -- so the word does
    not appear, in either shape. A report that printed everything and merely
    reordered it would pass every other test in this file and fail this one.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")

    document = setup()
    prose = render(document)
    structured = json.dumps(document)

    assert {gap["what"] for gap in document["missing"]} == {"client_id", "authorization"}
    for shape in (prose, structured):
        assert "provider" not in shape.lower()
        assert "ANTHROPIC" not in shape
        assert "plan" not in shape.lower()


def test_the_default_report_leaves_the_whole_orientation_for_the_flag(isolated):
    """The measured defect this item exists to fix, asserted as absence.

    The shipped shape printed the whole guide on every run -- the quota
    politics, the six-month refresh wall, `disconnect` -- for a caller whose
    only gap was the client ID. None of it appears now unless it is asked for.
    """
    report = render(setup())
    orientation = render(setup(guide=True))

    # Four things the orientation says and the default report has no business
    # saying: the refresh wall, removing your data, and both halves of the
    # quota politics a caller registering their first app cannot act on.
    for phrase in ("six months", "disconnect", "quarter of a million", "resubscribe"):
        assert phrase not in report, phrase
        assert phrase in orientation, phrase
    # And the report says where the rest is, rather than dropping it silently.
    assert "music-deck setup --guide" in report


def test_the_prose_is_smaller_than_the_json_twin_for_the_same_gap(isolated):
    """Core 4: "addressability nobody uses is not free" -- measured, not assumed."""
    document = setup()
    prose = render(document)
    structured = json.dumps(document, indent=2)

    assert len(prose.encode("utf-8")) < len(structured.encode("utf-8"))


def test_check_is_still_one_json_document_and_not_prose(tmp_path):
    """`check`'s result is parsed, not read: an agent branches on it.

    This item changed `setup` and deliberately did not change `check`. Asserted
    here rather than assumed, because "make the output friendly" is exactly the
    kind of change that spreads to the verb next door.
    """
    scratch = tmp_path / "elsewhere"
    scratch.mkdir()
    result = run_cli(
        "check",
        cwd=scratch,
        timeout=5.0,
        MUSIC_DECK_CONFIG_DIR=str(tmp_path / "config"),
        MUSIC_DECK_STATE_DIR=str(tmp_path / "state"),
    )

    assert result.returncode == EXIT_SUCCESS
    assert json.loads(result.stdout)["client_id"]["present"] is False


def test_the_short_client_id_steps_and_the_full_guide_agree(isolated):
    """The condensed path may not quietly lose what the long path says."""
    short = _normalise(" ".join(setup_guide.CLIENT_ID_STEPS))
    full = _normalise(setup_guide.render())

    for fact in ("http://127.0.0.1", "localhost", "client secret", "User Management"):
        assert fact in short, fact
        assert fact in full, fact


def test_setup_render_is_reachable_from_the_library(isolated):
    """cli.v1 Core 7: every CLI capability is reachable from the library.

    The prose is a capability of the binary, so a Python caller can produce it
    too -- otherwise the CLI would hold something the library cannot.
    """
    import music_deck

    assert music_deck.setup_render(music_deck.setup(show=True)).startswith("music-deck")
