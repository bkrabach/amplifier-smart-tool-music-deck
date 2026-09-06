"""`setup` -- nothing to ready, without ever asking a question.

``cli.v1`` Core 8: "``setup`` gets a new caller from nothing to ready, without
prompting. It reports what is configured, what is missing, and the steps for that
gap -- proportional to the gap, not the whole orientation every run, which is on
request. It writes the client ID when given one. The browser step stays in
``login``, still the only interactive verb."

``cli.v1`` Core 4, rewritten the same day: "**Structure what a caller parses;
write what a caller reads.** ... A verb whose result is guidance writes it for
its reader, with ``--json`` for the same content structured: addressability
nobody uses is not free."

`setup`'s result is guidance -- a person reads it and then does something. So
**prose is its default shape** and ``--json`` is the twin. `check`'s result is
the opposite: an agent reads ``client_id.present`` and branches on it. That is a
parsed result, so `check` stays one JSON document and is not touched here.

One document, two renderings
----------------------------
:func:`setup` builds the document. :func:`render` turns *that document* into the
prose -- it takes no other argument, reads nothing else, and decides nothing on
its own. The prose therefore **cannot** carry a fact the ``--json`` twin lacks:
there is nowhere else for one to come from. ``tests/test_setup.py`` asserts the
other direction -- every string the document carries reaches the prose -- so the
two cannot drift apart in either direction.

Proportional, not complete
--------------------------
The shape this replaces printed the whole registration guide on every run: 8,096
characters, of which the guide was 67%, printed in full for a caller whose only
gap was the client ID -- quota politics and the six-month refresh wall included.
What a caller sees now is the gap they actually have and the steps that close
it, and nothing about the facets that are already fine. The whole orientation is
one flag away: ``music-deck setup --guide``.

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
import textwrap
from pathlib import Path
from typing import Any, Final

from music_deck import setup_guide
from music_deck.check import DEFAULT_REDIRECT_PORT, LOOPBACK_HOST_LITERAL
from music_deck.check import check as run_check
from music_deck.check import config_path, resolve_redirect_uri, state_dir, token_path
from music_deck.errors import ErrorCode, MusicDeckError

CONFIG_DIR_MODE: Final = 0o700
CONFIG_FILE_MODE: Final = 0o600
"""The config file holds nothing secret today -- a client ID is public by PKCE's
design -- but it sits beside the token in the same private tree, and a caller
who later adds a field is not made to notice the difference."""

_HEX: Final = frozenset("0123456789abcdef")

WIDTH: Final = setup_guide.WIDTH
"""How wide the prose is wrapped -- defined in ``setup_guide`` so the gap the
default report prints and the orientation ``--guide`` prints are shaped alike."""

ORIENTATION: Final = {
    "detail": (
        "The whole orientation -- the Development Mode ceiling, the five-user "
        "allowlist, the six-month refresh wall, removing your data -- is on "
        "request:"
    ),
    "command": "music-deck setup --guide",
}
"""Core 8's "which is on request", written down where a reader will meet it."""


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


def normalize_port(value: Any) -> int:
    """A TCP port, or a loud refusal naming what a port looks like.

    ``boundary.v1`` Core 4 makes the redirect port a value the caller registers
    with Spotify by hand, so an unusable one is caught here -- at the moment they
    type it -- rather than at `login`, inside a browser round trip nobody can
    read.
    """
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError):
        raise MusicDeckError(
            ErrorCode.USAGE,
            f"`music-deck setup --port` was given {value!r}, which is not a "
            f"number.",
            "Give a TCP port between 1 and 65535, for example: music-deck setup "
            f"--port {DEFAULT_REDIRECT_PORT}",
        ) from None
    if not 1 <= port <= 65535:
        raise MusicDeckError(
            ErrorCode.USAGE,
            f"`music-deck setup --port` was given {port}, which is not a TCP "
            f"port (1-65535).",
            "Give a TCP port between 1 and 65535, for example: music-deck setup "
            f"--port {DEFAULT_REDIRECT_PORT}",
        )
    return port


def write_client_id(client_id: str) -> dict[str, Any]:
    """Write ``client_id`` into the config file. Returns what was written."""
    return write_config(client_id=client_id)


def write_redirect_uri(redirect_uri: str) -> dict[str, Any]:
    """Write ``redirect_uri`` into the config file. Returns what was written."""
    return write_config(redirect_uri=redirect_uri)


def write_config(
    *, client_id: str | None = None, redirect_uri: str | None = None
) -> dict[str, Any]:
    """Write the given keys into the config file. Returns what was written.

    The directory is created ``0700`` and the file lands ``0600``, both enforced
    after the fact with ``chmod`` so an inherited umask cannot loosen them. The
    redirect URI is written the same way and to the same file as the client ID,
    because ``boundary.v1`` Core 4 makes it the same kind of fact: something the
    caller registered with Spotify and the tool must honour exactly.
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

    values = {
        key: value
        for key, value in (("client_id", client_id), ("redirect_uri", redirect_uri))
        if value is not None
    }
    document = _read_existing_config(path)
    replaced = any(
        document.get(key) and document.get(key) != value
        for key, value in values.items()
    )
    document.update(values)

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
        **values,
        "replaced_previous": replaced,
    }


# --------------------------------------------------------------------------- #
# Where everything lives
# --------------------------------------------------------------------------- #
def paths() -> dict[str, Any]:
    """The three locations a caller ever needs to know about."""
    config = config_path()
    return {
        "config_file": str(config),
        "config_dir": str(config.parent),
        "state_dir": str(state_dir()),
        "token_file": str(token_path()),
        "overrides": {
            "config_dir": "MUSIC_DECK_CONFIG_DIR, else XDG_CONFIG_HOME",
            "state_dir": "MUSIC_DECK_STATE_DIR, else XDG_STATE_HOME",
            "client_id": "MUSIC_DECK_CLIENT_ID wins over the config file",
        },
    }


# --------------------------------------------------------------------------- #
# What is already true, what is missing, and what to run next
# --------------------------------------------------------------------------- #
def _have(facts: dict[str, Any]) -> list[str]:
    """What is configured -- the required facets only, one line each.

    Core 8 asks `setup` to report "what is configured". It stays to the two
    things a caller must have for the Spotify verbs to work, and never mentions
    the optional model provider: a caller who has already configured one has no
    gap there, and Core 8's "proportional to the gap" makes telling them about
    it noise. The conformance kit says the same thing from the other end --
    `setup` "stays silent about what is not".
    """
    have: list[str] = []

    client_id = facts.get("client_id") or {}
    if client_id.get("present"):
        source = client_id.get("source") or "an unnamed source"
        have.append(f"A Spotify client ID, from {source}.")

    token_file = facts.get("token_file") or {}
    if token_file.get("present"):
        have.append(f"A Spotify token, at {token_file.get('path')}.")

    return have


def _missing(facts: dict[str, Any]) -> list[dict[str, Any]]:
    """The gaps between here and a working `music-deck login`, in order.

    Read off ``check()``'s own facts so the two verbs cannot disagree. Each gap
    carries what is wrong (``detail``), the one thing to do about it
    (``remedy``), and -- where closing it takes more than a command -- the
    ``steps`` that close *that* gap and no others.
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
                    "quota. Registering one takes about ten minutes."
                ),
                "steps": list(
                    setup_guide.client_id_steps(
                        (facts.get("redirect_uri") or {}).get("value")
                    )
                ),
                "remedy": "Then tell music-deck the client ID you copied:",
                "command": "music-deck setup --client-id <your client id>",
            }
        )

    redirect = facts.get("redirect_uri") or {}
    if redirect.get("conforms") is False:
        gaps.append(
            {
                "what": "redirect_uri",
                "detail": f"Redirect URI {redirect.get('value')!r}: "
                f"{redirect.get('detail')}",
                "remedy": redirect.get("remedy") or "",
            }
        )

    token_file = facts.get("token_file") or {}
    refresh_token = facts.get("refresh_token") or {}
    if not token_file.get("present"):
        gaps.append(
            {
                "what": "authorization",
                "detail": "Not signed in to Spotify -- there is no token yet.",
                "remedy": (
                    "Sign in. This is the one step that opens a browser, and "
                    "the only interactive verb music-deck has:"
                ),
                "command": "music-deck login",
            }
        )
    elif refresh_token.get("past_wall"):
        gaps.append(
            {
                "what": "authorization",
                "detail": (
                    "The refresh token is past Spotify's six-month wall, so "
                    "signing in again is the only way forward."
                ),
                "remedy": "Sign in again:",
                "command": "music-deck login",
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
                    "install the matching SDK with:"
                ),
                "command": setup_guide.install_with("anthropic"),
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
# The verb -- the document
# --------------------------------------------------------------------------- #
def _redirect_uri_block(facts: dict[str, Any]) -> dict[str, Any]:
    """The one string a caller has to type into Spotify's dashboard.

    ``boundary.v1`` Core 4 makes the redirect URI one value that ``check``
    reports and ``login`` binds; the third reader is the caller, who registers it
    by hand. So `setup` names it, character for character, taken from the same
    resolver -- not from a sentence somebody wrote down once.
    """
    fact = facts.get("redirect_uri") or {}
    return {
        "value": fact.get("value") or "",
        "source": fact.get("source") or "built-in default",
        "detail": (
            "Register this exact string as your Spotify app's redirect URI -- "
            "with its port, and never http://localhost. music-deck binds exactly "
            "this when you sign in, and `music-deck check` reports it. To use a "
            "different port, run `music-deck setup --port <n>` and register that "
            "one instead."
        ),
    }


def setup(
    client_id: str | None = None,
    port: int | str | None = None,
    show: bool = False,
    guide: bool = False,
) -> dict[str, Any]:
    """Report, configure, locate, or orient -- and never a prompt.

    ``client_id`` and ``port`` write the config file; ``show`` reports the paths;
    ``guide`` returns the whole registration orientation; the bare call reports
    the state and the gaps. Exit is always 0 except for an invalid ``client_id``
    or ``port``, which are invalid input (exit 2).

    This is the document. :func:`render` is the prose a person reads, built from
    exactly this and nothing else.
    """
    if show:
        return {"tool": "music-deck", "action": "paths", "paths": paths()}

    if guide:
        return {
            "tool": "music-deck",
            "action": "guide",
            "spotify_app": setup_guide.guide(),
        }

    written: dict[str, Any] | None = None
    values: dict[str, Any] = {}
    if client_id is not None:
        values["client_id"] = normalize_client_id(client_id)
    if port is not None:
        values["redirect_uri"] = (
            f"http://{LOOPBACK_HOST_LITERAL}:{normalize_port(port)}"
        )
    if values:
        written = write_config(**values)

    facts = run_check()
    gaps = _missing(facts)
    ready = bool((facts.get("ready") or {}).get("spotify_verbs"))

    document: dict[str, Any] = {
        "tool": "music-deck",
        "version": facts.get("version", "unknown"),
        "action": "configured" if written is not None else "report",
        "ready": ready,
        "have": _have(facts),
        "missing": gaps,
        "next_command": _next_command(facts),
        "orientation": dict(ORIENTATION),
    }
    # Proportional (Core 8): a caller who is already signed in has registered it
    # and needs no reminder. Anyone still on their way to `login` -- or who just
    # changed the port -- is about to type it into a dashboard.
    if not ready or written is not None:
        document["redirect_uri"] = _redirect_uri_block(facts)
    if written is not None:
        document["wrote"] = written
        notes: list[str] = []
        client_source = (facts.get("client_id") or {}).get("source") or ""
        if "client_id" in written and client_source.startswith("environment"):
            notes.append(
                "MUSIC_DECK_CLIENT_ID is set in this environment and wins over "
                "the config file, so `check` reports the environment's value, "
                "not the one just written."
            )
        redirect_source = (facts.get("redirect_uri") or {}).get("source") or ""
        if "redirect_uri" in written and redirect_source.startswith("environment"):
            notes.append(
                "MUSIC_DECK_REDIRECT_URI is set in this environment and wins "
                "over the config file, so `check` reports -- and `login` binds "
                "-- the environment's value, not the one just written."
            )
        if notes:
            document["note"] = " ".join(notes)
    return document


# --------------------------------------------------------------------------- #
# The verb -- the prose
# --------------------------------------------------------------------------- #
def _wrap(text: str, indent: str = "", first: str | None = None) -> list[str]:
    """One paragraph, wrapped, with words and URLs left intact.

    ``break_long_words`` and ``break_on_hyphens`` are both off so that no token a
    reader might copy -- a URL, a command, a client ID -- is ever split across
    two lines.
    """
    return textwrap.wrap(
        text,
        width=WIDTH,
        initial_indent=first if first is not None else indent,
        subsequent_indent=indent,
        break_long_words=False,
        break_on_hyphens=False,
    ) or [indent.rstrip()]


def _command(command: str, prefix: str = "", indent: str = "  ") -> list[str]:
    """A command the reader will copy, on one line whatever the width.

    Never wrapped, and never merged into a wrapped paragraph. A command split
    across two lines pastes into a shell as two commands, and the second half of
    ``uv tool install --force --with anthropic git+https://...`` is not a
    command at all -- which is a remedy that leads nowhere, the exact failure
    ``cli.v1`` Core 4 names.
    """
    line = f"{prefix}{command}"
    if len(line) <= WIDTH:
        return [line]
    # Too long for one line with its label, so the label goes above it. An
    # indent-only prefix has no label, and an empty line in its place would read
    # as a paragraph break that is not there.
    label = prefix.rstrip()
    return ([label] if label else []) + [f"{indent}{command}"]


def _title(document: dict[str, Any]) -> str:
    version = document.get("version") or "unknown"
    if version == "unknown":
        return "music-deck (version unknown)"
    return f"music-deck {version}"


def _count(number: int) -> str:
    words = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five"}
    return words.get(number, str(number))


def _render_paths(document: dict[str, Any]) -> str:
    """`setup --show`: the four locations, and what overrides each."""
    locations = document["paths"]
    lines = ["music-deck -- where everything lives.", ""]
    for label, key in (
        ("config file", "config_file"),
        ("config dir ", "config_dir"),
        ("state dir  ", "state_dir"),
        ("token file ", "token_file"),
    ):
        lines.append(f"  {label}  {locations[key]}")
    lines += ["", "Overrides:"]
    for key, value in (locations.get("overrides") or {}).items():
        lines += _wrap(f"{key}: {value}", indent="    ", first="  - ")
    return "\n".join(lines)


def _render_gap(index: int, gap: dict[str, Any]) -> list[str]:
    """One required gap: what is wrong, the steps that close it, the command."""
    lines = _wrap(gap["detail"], indent="   ", first=f"{index}. ")
    steps = gap.get("steps") or []
    if steps:
        lines.append("")
        for step in steps:
            lines += _wrap(step, indent="     ", first="   - ")
    lines.append("")
    lines += _wrap(gap["remedy"], indent="   ", first="   ")
    if gap.get("command"):
        lines += _command(gap["command"], prefix="     ", indent="     ")
    return lines


def _render_report(document: dict[str, Any]) -> str:
    """The bare `setup`, and `setup --client-id`: the gap, and what closes it."""
    lines: list[str] = []
    wrote = document.get("wrote")

    if wrote is not None:
        names = [
            label
            for key, label in (
                ("client_id", "client ID"),
                ("redirect_uri", "redirect URI"),
            )
            if key in wrote
        ]
        lines.append(f"{_title(document)} -- {' and '.join(names)} written.")
        lines.append("")
        for key in ("client_id", "redirect_uri"):
            if key in wrote:
                lines.append(f"  {wrote[key]}")
        lines.append(f"  {wrote['path']}  (mode {wrote['mode']}, yours alone)")
        if wrote.get("replaced_previous"):
            lines.append("  It replaced the value that was there before.")
        lines.append("")
    else:
        ready = "ready." if document.get("ready") else "not ready yet."
        lines += [f"{_title(document)} -- {ready}", ""]

    note = document.get("note")
    if note:
        lines += _wrap(note) + [""]

    redirect = document.get("redirect_uri")
    if redirect:
        lines.append(f"Redirect URI (from {redirect['source']}):")
        lines.append("")
        lines.append(f"  {redirect['value']}")
        lines.append("")
        lines += _wrap(redirect["detail"], indent="  ", first="  ")
        lines.append("")

    have = document.get("have") or []
    if have:
        lines.append("Already configured:")
        for item in have:
            lines += _wrap(item, indent="    ", first="  - ")
        lines.append("")

    missing = document.get("missing") or []
    required = [gap for gap in missing if not gap.get("optional")]
    optional = [gap for gap in missing if gap.get("optional")]

    if required:
        thing = "thing is" if len(required) == 1 else "things are"
        lines += [f"{_count(len(required))} {thing} missing:", ""]
        for index, gap in enumerate(required, start=1):
            lines += _render_gap(index, gap)
            lines.append("")
    else:
        lines += ["Nothing is missing.", ""]

    if optional:
        lines.append("Optional:")
        for gap in optional:
            lines += _wrap(gap["detail"], indent="    ", first="  - ")
            lines += _wrap(gap["remedy"], indent="    ", first="    ")
            if gap.get("command"):
                lines += _command(gap["command"], prefix="      ", indent="      ")
        lines.append("")

    lines += _command(document["next_command"], prefix="Next: ")
    orientation = document["orientation"]
    lines += ["", *_wrap(orientation["detail"])]
    lines += _command(orientation["command"], prefix="  ")
    return "\n".join(lines)


def render(document: dict[str, Any]) -> str:
    """The prose a person reads, built from the document and nothing else.

    ``cli.v1`` Core 4: "A verb whose result is guidance writes it for its reader,
    with ``--json`` for the same content structured." This is that reader's half,
    and the argument is the ``--json`` half -- so the prose cannot say anything
    the structured form does not carry. ``tests/test_setup.py`` asserts the
    converse: every string in the document reaches this text.
    """
    action = document.get("action")
    if action == "paths":
        return _render_paths(document)
    if action == "guide":
        # The URI comes out of the document, not out of the resolver a second
        # time. Re-resolving here would let the prose and its `--json` twin
        # disagree whenever the configured value changed between the two calls --
        # the very drift this split exists to prevent.
        return setup_guide.render((document.get("spotify_app") or {}).get("redirect_uri"))
    return _render_report(document)
