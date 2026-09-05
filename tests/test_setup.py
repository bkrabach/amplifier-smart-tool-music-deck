"""`setup` gets a new caller from nothing to ready, and never asks a question.

Contracts served: ``cli.v1`` Core 8 ("`setup` gets a new caller from nothing to
ready, without prompting. It reports what is configured and what is missing,
carries the steps to register a Spotify app in plain words, and writes the
client ID when given one"), Core 1 ("Non-interactive. A run with stdin closed
never hangs"), Core 4 (one JSON document per result; the error envelope), Core 5
(exit ``2`` for invalid input), and ``boundary.v1`` Core 4 (private file modes)
applied to the config file `setup` writes.

The two claims worth being careful about are asserted the hard way:

* **"never prompts"** is not asserted by reading the source for ``input()``. The
  CLI is run as a real subprocess with stdin closed *and* a wall-clock deadline,
  so a `setup` that waited for a line would fail here as a timeout rather than
  pass quietly on a machine where stdin happened to be a terminal.
* **"config file 0600"** is read back off the filesystem with ``stat`` after the
  write, under a deliberately loose umask -- a write that relied on the caller's
  umask would land 0644 and fail.
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
from music_deck.verbs.setup import normalize_client_id, setup, write_client_id

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
    assert result["configured"]["client_id"]["present"] is False
    assert {gap["what"] for gap in result["missing"]} >= {"client_id", "authorization"}
    assert result["next_command"] == "music-deck setup --client-id <your client id>"


def test_setup_carries_the_registration_steps_in_the_document(isolated):
    """Core 8: it "carries the steps to register a Spotify app in plain words"."""
    guide = setup()["spotify_app"]

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
    document = json.loads(result.stdout)  # Core 4: exactly one JSON document
    assert document["action"] == "report"
    assert document["missing"]


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
