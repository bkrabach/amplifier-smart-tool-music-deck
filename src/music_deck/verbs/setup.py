"""`setup` -- nothing to ready, without ever asking a question.

``cli.v1`` Core 8: "``setup`` gets a new caller from nothing to ready, without
prompting. It reports what is configured and what is missing, carries the steps
to register a Spotify app in plain words, and writes the client ID when given
one. The browser step stays in ``login``, still the only interactive verb."

Three shapes, one JSON document each (``cli.v1`` Core 4):

* ``music-deck setup`` -- reports what is configured, what is missing, and what
  to do about it, and carries the whole registration guide. Exit 0 always: like
  ``check``, reporting a problem is its success, not a failure.
* ``music-deck setup --client-id <id>`` -- validates the shape, writes the
  config file, and names the next command.
* ``music-deck setup --show`` -- names the config, state, and token paths.

**It never reads stdin.** ``cli.v1`` Core 1 promises "a run with stdin closed
never hangs", and ``boundary.v1`` Core 5 keeps ``login`` as the only interactive
verb. A `setup` that prompted would be a second one, so this module contains no
``input()``, no ``getpass``, and no read of ``sys.stdin`` -- there is nothing
here that could block.

**It does not fork the client-ID resolver.** Every fact this verb reports about
the current state comes from ``music_deck.check.check()``, which already answers
"is there a client ID, and where did it come from" -- so `setup` and `check`
cannot disagree about whether a caller is configured.

Writing the config is the one thing this verb does that ``check`` does not, and
it is done the way ``boundary.v1`` Core 4 has the token written: the directory
is ``0700``, the file is ``0600``, and the write is atomic -- a temporary file
in the same directory, chmod'd before it is put in place, so the config is never
briefly world-readable and never half-written.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any, Final

from music_deck import setup_guide
from music_deck.check import check as run_check
from music_deck.check import config_path, state_dir, token_path
from music_deck.errors import ErrorCode, MusicDeckError

CONFIG_DIR_MODE: Final = 0o700
CONFIG_FILE_MODE: Final = 0o600
"""The config file holds nothing secret today -- a client ID is public by PKCE's
design -- but it sits beside the token in the same private tree, and a caller
who later adds a field is not made to notice the difference."""

_HEX: Final = frozenset("0123456789abcdef")


# --------------------------------------------------------------------------- #
# The client ID's shape
# --------------------------------------------------------------------------- #
def normalize_client_id(value: str) -> str:
    """A client ID in its canonical form, or a loud refusal.

    Exit ``2``: ``cli.v1`` Core 5 puts "invalid input" there, and the refusal
    names the shape (Core 4) rather than saying only "that is wrong" -- a reader
    who pasted the client *secret*, a dashboard URL, or half an id needs to be
    told what the right thing looks like.
    """
    candidate = (value or "").strip()
    if not candidate:
        raise MusicDeckError(
            ErrorCode.USAGE,
            "`music-deck setup --client-id` was given an empty value.",
            setup_guide.CLIENT_ID_SHAPE,
        )
    folded = candidate.lower()
    wrong_length = len(folded) != setup_guide.CLIENT_ID_LENGTH
    non_hex = sorted({character for character in folded if character not in _HEX})
    if wrong_length or non_hex:
        problems = []
        if wrong_length:
            problems.append(
                f"it is {len(candidate)} characters, not "
                f"{setup_guide.CLIENT_ID_LENGTH}"
            )
        if non_hex:
            shown = "".join(non_hex[:8])
            problems.append(f"it contains non-hexadecimal characters ({shown})")
        raise MusicDeckError(
            ErrorCode.USAGE,
            f"{candidate!r} is not a Spotify client ID: " + "; ".join(problems) + ".",
            setup_guide.CLIENT_ID_SHAPE,
        )
    return folded


# --------------------------------------------------------------------------- #
# Writing the config
# --------------------------------------------------------------------------- #
def _read_existing_config(path: Path) -> dict[str, Any]:
    """Whatever is already in the config file, or an empty document.

    Anything unreadable is treated as absent rather than fatal, but the keys of
    a readable file are kept: a caller who set ``redirect_uri`` by hand does not
    lose it because they later ran `setup --client-id`.
    """
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - an unreadable config is "nothing yet"
        return {}
    return document if isinstance(document, dict) else {}


def write_client_id(client_id: str) -> dict[str, Any]:
    """Write ``client_id`` into the config file. Returns what was written.

    The directory is created ``0700`` and the file lands ``0600``, both enforced
    after the fact with ``chmod`` so an inherited umask cannot loosen them.
    """
    path = config_path()
    directory = path.parent
    try:
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, CONFIG_DIR_MODE)
    except OSError as exc:
        raise MusicDeckError(
            ErrorCode.USAGE,
            f"The config directory {str(directory)!r} could not be created: "
            f"{exc.strerror or exc}.",
            "Point MUSIC_DECK_CONFIG_DIR (or XDG_CONFIG_HOME) at a directory "
            "you can write to, then run `music-deck setup --client-id <id>` "
            "again.",
        ) from exc

    document = _read_existing_config(path)
    previous = document.get("client_id")
    document["client_id"] = client_id

    try:
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(directory),
            prefix=".config-",
            suffix=".json",
            delete=False,
        )
        try:
            with handle:
                json.dump(document, handle, indent=2, sort_keys=True)
                handle.write("\n")
            os.chmod(handle.name, CONFIG_FILE_MODE)
            os.replace(handle.name, path)
        except BaseException:
            Path(handle.name).unlink(missing_ok=True)
            raise
    except OSError as exc:
        raise MusicDeckError(
            ErrorCode.USAGE,
            f"The config file {str(path)!r} could not be written: "
            f"{exc.strerror or exc}.",
            "Point MUSIC_DECK_CONFIG_DIR (or XDG_CONFIG_HOME) at a directory "
            "you can write to, then run `music-deck setup --client-id <id>` "
            "again.",
        ) from exc

    return {
        "path": str(path),
        "mode": format(stat.S_IMODE(path.stat().st_mode), "04o"),
        "client_id": client_id,
        "replaced_previous": bool(previous) and previous != client_id,
        "keys": sorted(document),
    }


# --------------------------------------------------------------------------- #
# Where everything lives
# --------------------------------------------------------------------------- #
def paths() -> dict[str, Any]:
    """The three locations a caller ever needs to know about."""
    config = config_path()
    token = token_path()
    return {
        "config_file": str(config),
        "config_dir": str(config.parent),
        "state_dir": str(state_dir()),
        "token_file": str(token),
        "overrides": {
            "config_dir": "MUSIC_DECK_CONFIG_DIR, else XDG_CONFIG_HOME",
            "state_dir": "MUSIC_DECK_STATE_DIR, else XDG_STATE_HOME",
            "client_id": "MUSIC_DECK_CLIENT_ID wins over the config file",
        },
    }


# --------------------------------------------------------------------------- #
# What is missing, and what to run next
# --------------------------------------------------------------------------- #
def _missing(facts: dict[str, Any]) -> list[dict[str, Any]]:
    """The gaps between here and a working `music-deck login`, in order.

    Read off ``check()``'s own facts so the two verbs cannot disagree.
    """
    gaps: list[dict[str, Any]] = []

    client_id = facts.get("client_id") or {}
    if not client_id.get("present"):
        gaps.append(
            {
                "what": "client_id",
                "detail": (
                    "No Spotify client ID is configured. music-deck ships none "
                    "by design: it runs against your own app, under your own "
                    "quota."
                ),
                "remedy": (
                    "Follow the steps in `spotify_app` below, then run: "
                    "music-deck setup --client-id <your client id>"
                ),
            }
        )

    redirect = facts.get("redirect_uri") or {}
    if redirect.get("conforms") is False:
        gaps.append(
            {
                "what": "redirect_uri",
                "detail": f"Redirect URI {redirect.get('value')!r}: "
                f"{redirect.get('detail')}",
                "remedy": (
                    "Register http://127.0.0.1 (no port) as the app's redirect "
                    "URI, and unset MUSIC_DECK_REDIRECT_URI unless it names a "
                    "loopback IP literal."
                ),
            }
        )

    token_file = facts.get("token_file") or {}
    if not token_file.get("present"):
        gaps.append(
            {
                "what": "authorization",
                "detail": "Not signed in to Spotify -- there is no token yet.",
                "remedy": "Run: music-deck login",
            }
        )

    provider = facts.get("provider") or {}
    if not provider.get("configured"):
        gaps.append(
            {
                "what": "model_provider",
                "detail": (
                    "No model provider is configured. Every verb except `plan` "
                    "runs without one, so this is optional."
                ),
                "remedy": (
                    "Only if you want `plan`: set ANTHROPIC_API_KEY (or "
                    "OPENAI_API_KEY, GOOGLE_API_KEY, AZURE_OPENAI_API_KEY) and "
                    "install the matching SDK with: "
                    f"{setup_guide.install_with('anthropic')}"
                ),
                "optional": True,
            }
        )

    return gaps


def _next_command(facts: dict[str, Any]) -> str:
    """The single next thing to run. Never a list -- one step at a time."""
    if not (facts.get("client_id") or {}).get("present"):
        return "music-deck setup --client-id <your client id>"
    if not (facts.get("token_file") or {}).get("present"):
        return "music-deck login"
    return "music-deck check"


# --------------------------------------------------------------------------- #
# The verb
# --------------------------------------------------------------------------- #
def setup(client_id: str | None = None, show: bool = False) -> dict[str, Any]:
    """Report, configure, or locate -- one JSON document, and never a prompt.

    ``client_id`` writes the config file; ``show`` reports the paths; neither
    reports the state and carries the registration guide. Exit is always 0
    except for an invalid ``client_id``, which is invalid input (exit 2).
    """
    if show:
        return {
            "tool": "music-deck",
            "action": "paths",
            "paths": paths(),
        }

    written: dict[str, Any] | None = None
    if client_id is not None:
        written = write_client_id(normalize_client_id(client_id))

    facts = run_check()
    gaps = _missing(facts)

    document: dict[str, Any] = {
        "tool": "music-deck",
        "version": facts.get("version", "unknown"),
        "action": "configured" if written is not None else "report",
        "install_command": setup_guide.INSTALL_COMMAND,
        "paths": paths(),
        "configured": {
            "client_id": facts.get("client_id"),
            "redirect_uri": facts.get("redirect_uri"),
            "signed_in": bool((facts.get("token_file") or {}).get("present")),
            "model_provider": facts.get("provider"),
        },
        "ready": facts.get("ready"),
        "missing": gaps,
        "next_command": _next_command(facts),
        "spotify_app": setup_guide.guide(),
    }
    if written is not None:
        document["wrote"] = written
        source = (facts.get("client_id") or {}).get("source") or ""
        if source.startswith("environment"):
            document["note"] = (
                "MUSIC_DECK_CLIENT_ID is set in this environment and wins over "
                "the config file, so `check` reports the environment's value, "
                "not the one just written."
            )
    return document
