"""`check` -- the deterministic smoke verb. Reports the facts and exits 0.

``boundary.v1`` Core 6: "``check`` reports the auth facts and exits 0 always --
it never fails just because the account is not connected." ``cli.v1`` Core 2:
"``check`` additionally succeeds (exit 0) with no credentials and no network, in
a fresh working directory -- it is the smoke test; **reporting problems IS its
success**."

So this module has one hard rule: **it never raises and it never fails.** Every
lookup is wrapped; anything unreadable is reported as a fact rather than thrown.
A caller reading `"present": false` is reading a successful run.

It touches only the environment and the filesystem. No network, no Spotify, no
model -- which is what makes it usable as the install smoke test.

What it reports, in order:

* the client ID -- present or not, and where it came from
* the redirect URI -- its value, and whether its shape conforms to
  ``boundary.v1`` Core 4 (loopback IP literal, never ``localhost``)
* the token cache -- present or not, its path, and its file mode
* the access token -- when it expires
* the refresh token -- how old it is against Spotify's six-month wall
* the granted scopes
* the last observed 403, which is the only signal an account is not on the
  app's Development Mode allowlist
* whether a model provider is configured, which only ``plan`` needs
"""

from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

TOKEN_FILENAME: Final = "token.json"
CONFIG_FILENAME: Final = "config.json"
LAST_403_FILENAME: Final = "last-403.json"

REFRESH_TOKEN_WALL_DAYS: Final = 183
"""Spotify: "Refresh tokens issued to apps registered in the Developer Dashboard
have a lifetime of 6 months" and "refreshing an access token does not extend the
refresh token's lifetime". Six months is taken here as 183 days."""

TOKEN_FILE_MODE: Final = 0o600
"""``boundary.v1`` Core 4: the token file is mode 0600."""

DEFAULT_REDIRECT_URI: Final = "http://127.0.0.1"
"""Registered without a port. ``boundary.v1`` Core 4 puts an ephemeral port on
the authorisation request, which Spotify supports only for loopback literals."""

_LOOPBACK_HOSTS: Final = ("127.0.0.1", "[::1]")

_PROVIDER_ENV_VARS: Final = (
    "MUSIC_DECK_PROVIDER",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
)


# --------------------------------------------------------------------------- #
# Where music-deck's files live
# --------------------------------------------------------------------------- #
def config_dir() -> Path:
    """``~/.config/music-deck``, honouring ``XDG_CONFIG_HOME``.

    ``MUSIC_DECK_CONFIG_DIR`` overrides both -- state belongs outside the tool's
    own directory and outside whatever working directory it was invoked from.
    """
    override = os.environ.get("MUSIC_DECK_CONFIG_DIR")
    if override:
        return Path(override)
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "music-deck"


def state_dir() -> Path:
    """``~/.local/state/music-deck``, honouring ``XDG_STATE_HOME``.

    ``MUSIC_DECK_STATE_DIR`` overrides both. ``boundary.v1`` Core 4 puts the
    token at ``$XDG_STATE_HOME/music-deck/token.json``.
    """
    override = os.environ.get("MUSIC_DECK_STATE_DIR")
    if override:
        return Path(override)
    base = os.environ.get("XDG_STATE_HOME")
    root = Path(base) if base else Path.home() / ".local" / "state"
    return root / "music-deck"


def token_path() -> Path:
    return state_dir() / TOKEN_FILENAME


def config_path() -> Path:
    return config_dir() / CONFIG_FILENAME


# --------------------------------------------------------------------------- #
# Small total helpers -- none of these raise
# --------------------------------------------------------------------------- #
def _read_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """``(document, None)``, or ``(None, reason)``. Never raises."""
    try:
        if not path.exists():
            return None, None
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"could not be read: {exc.strerror or exc}"
    except Exception as exc:  # noqa: BLE001 - check reports, it never crashes
        return None, f"could not be read: {exc}"
    try:
        document = json.loads(text)
    except ValueError as exc:
        return None, f"is not valid JSON: {exc}"
    if not isinstance(document, dict):
        return None, f"is a {type(document).__name__}, not a JSON object"
    return document, None


def _parse_timestamp(value: Any) -> datetime | None:
    """Accept an ISO-8601 string or epoch seconds. Never raises."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _iso(moment: datetime | None) -> str | None:
    return None if moment is None else moment.astimezone(timezone.utc).isoformat()


def _round(value: float) -> float:
    return round(value, 1)


# --------------------------------------------------------------------------- #
# The individual facts
# --------------------------------------------------------------------------- #
def _client_id_fact(config: dict[str, Any] | None) -> dict[str, Any]:
    """``cli.v1``/``boundary.v1``: the caller brings the client ID; none ships."""
    from_env = os.environ.get("MUSIC_DECK_CLIENT_ID", "").strip()
    if from_env:
        return {
            "present": True,
            "source": "environment MUSIC_DECK_CLIENT_ID",
            "length": len(from_env),
        }
    from_config = ""
    if config is not None:
        value = config.get("client_id")
        from_config = value.strip() if isinstance(value, str) else ""
    if from_config:
        return {
            "present": True,
            "source": f"config file {config_path()}",
            "length": len(from_config),
        }
    return {
        "present": False,
        "source": None,
        "length": 0,
        "remedy": (
            "Run `music-deck setup --client-id <your client id>` to write it, "
            "or set MUSIC_DECK_CLIENT_ID. Run `music-deck setup` with no "
            "arguments for the steps to register a Spotify app."
        ),
    }


def _redirect_uri_fact(config: dict[str, Any] | None) -> dict[str, Any]:
    """``boundary.v1`` Core 4: a loopback IP literal, never ``localhost``."""
    value = os.environ.get("MUSIC_DECK_REDIRECT_URI", "").strip()
    source = "environment MUSIC_DECK_REDIRECT_URI"
    if not value and config is not None:
        candidate = config.get("redirect_uri")
        if isinstance(candidate, str) and candidate.strip():
            value, source = candidate.strip(), f"config file {config_path()}"
    if not value:
        value, source = DEFAULT_REDIRECT_URI, "built-in default"

    conforms, detail = _redirect_uri_shape(value)
    return {"value": value, "source": source, "conforms": conforms, "detail": detail}


def _redirect_uri_shape(value: str) -> tuple[bool, str]:
    if not value.startswith("http://"):
        return False, (
            "must start with http:// -- Spotify permits plain HTTP only for a "
            "loopback address, and music-deck uses a loopback address."
        )
    remainder = value[len("http://") :]
    host = remainder.split("/", 1)[0]
    if host.startswith("[") and "]" in host:
        host_only = host[: host.index("]") + 1]
    else:
        host_only = host.split(":", 1)[0]
    if host_only == "localhost":
        return False, (
            "`localhost` is not allowed by Spotify as a redirect URI. Use the IP "
            "literal http://127.0.0.1 instead."
        )
    if host_only not in _LOOPBACK_HOSTS:
        return False, (
            f"host {host_only!r} is not a loopback IP literal. boundary.v1 Core 4 "
            "requires http://127.0.0.1 (or http://[::1])."
        )
    return True, "loopback IP literal, as boundary.v1 Core 4 requires."


def _token_file_fact() -> dict[str, Any]:
    """The token cache: present, at what path, at what mode."""
    path = token_path()
    fact: dict[str, Any] = {"path": str(path), "present": False}
    try:
        exists = path.exists()
    except OSError as exc:
        fact["error"] = f"could not be checked: {exc.strerror or exc}"
        return fact
    if not exists:
        fact["remedy"] = "Run `music-deck login` to authorise and create it."
        return fact

    fact["present"] = True
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
        fact["mode"] = format(mode, "04o")
        fact["mode_ok"] = mode == TOKEN_FILE_MODE
        if mode != TOKEN_FILE_MODE:
            fact["remedy"] = (
                f"boundary.v1 Core 4 requires mode 0600. Run: chmod 600 {path}"
            )
    except OSError as exc:
        fact["error"] = f"mode could not be read: {exc.strerror or exc}"
    return fact


def _token_facts(token: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """``(access_token_fact, refresh_token_fact)`` -- expiry, and the 6-month wall."""
    now = datetime.now(timezone.utc)

    access: dict[str, Any] = {"present": False}
    refresh: dict[str, Any] = {
        "present": False,
        "wall_days": REFRESH_TOKEN_WALL_DAYS,
        "note": (
            "Spotify refresh tokens last six months from the moment you authorised, "
            "and refreshing an access token does not extend that."
        ),
    }
    if token is None:
        return access, refresh

    if isinstance(token.get("access_token"), str) and token["access_token"].strip():
        access["present"] = True
        expires_at = _parse_timestamp(
            token.get("expires_at", token.get("expires_at_epoch"))
        )
        access["expires_at"] = _iso(expires_at)
        if expires_at is None:
            access["expired"] = None
            access["detail"] = (
                "no readable `expires_at` in the token file; expiry is unknown"
            )
        else:
            remaining = (expires_at - now).total_seconds()
            access["seconds_remaining"] = int(remaining)
            access["expired"] = remaining <= 0
            if remaining <= 0:
                access["detail"] = "expired; music-deck will refresh it on next use"

    raw_refresh = token.get("refresh_token")
    if isinstance(raw_refresh, str) and raw_refresh.strip():
        refresh["present"] = True
        authorized_at = _parse_timestamp(
            token.get("authorized_at", token.get("refresh_token_issued_at"))
        )
        refresh["authorized_at"] = _iso(authorized_at)
        if authorized_at is None:
            refresh["age_days"] = None
            refresh["days_remaining"] = None
            refresh["past_wall"] = None
            refresh["detail"] = (
                "no readable `authorized_at` in the token file; how much of the "
                "six months is left cannot be worked out"
            )
        else:
            age_days = (now - authorized_at).total_seconds() / 86400.0
            refresh["age_days"] = _round(age_days)
            refresh["days_remaining"] = _round(REFRESH_TOKEN_WALL_DAYS - age_days)
            refresh["past_wall"] = age_days >= REFRESH_TOKEN_WALL_DAYS
            if refresh["past_wall"]:
                refresh["remedy"] = (
                    "Past the six-month wall. Run `music-deck login` to authorise again."
                )
    return access, refresh


def _scopes_fact(token: dict[str, Any] | None) -> dict[str, Any]:
    """The scopes Spotify actually granted, as recorded at sign-in."""
    if token is None:
        return {"known": False, "granted": [], "detail": "no token file to read"}
    raw = token.get("scopes", token.get("scope"))
    if isinstance(raw, str):
        granted = [item for item in raw.split() if item]
    elif isinstance(raw, list):
        granted = [item for item in raw if isinstance(item, str) and item.strip()]
    else:
        return {
            "known": False,
            "granted": [],
            "detail": "the token file records no `scopes`",
        }
    return {"known": True, "granted": sorted(granted), "count": len(granted)}


def _allowlist_fact() -> dict[str, Any]:
    """The last observed 403 -- the only signal that an account is not allowlisted.

    Spotify: "Users may be able to log into a development mode app without having
    been allowlisted... However, API requests... will receive a 403 status code
    error." There is no endpoint that answers the question directly, so the
    honest answer with no evidence on disk is "unknown".
    """
    path = state_dir() / LAST_403_FILENAME
    document, problem = _read_json(path)
    if problem is not None:
        return {"state": "unknown", "last_403": None, "detail": f"{path} {problem}"}
    if document is None:
        return {
            "state": "unknown",
            "last_403": None,
            "detail": (
                "no 403 has been recorded. Spotify offers no way to ask whether an "
                "account is on an app's allowlist; a 403 is the only signal."
            ),
        }
    return {
        "state": "suspect",
        "last_403": {
            "observed_at": document.get("observed_at"),
            "endpoint": document.get("endpoint"),
            "reason": document.get("reason"),
        },
        "remedy": (
            "A 403 on a Development Mode app usually means this Spotify account is "
            "not on the app's allowlist. Add it under User Management in the Spotify "
            "developer dashboard. Run `music-deck setup` for the steps."
        ),
    }


def _provider_fact() -> dict[str, Any]:
    """Whether a model provider is configured. Only ``plan`` needs one.

    ``cli.v1`` Core 2: every other verb runs with no provider configured and no
    provider SDK installed, so "false" here is never a problem for `check`.
    """
    for name in _PROVIDER_ENV_VARS:
        if os.environ.get(name, "").strip():
            return {
                "configured": True,
                "source": f"environment {name}",
                "needed_by": ["plan"],
            }
    return {
        "configured": False,
        "source": None,
        "needed_by": ["plan"],
        "detail": (
            "No model provider is configured. Every verb except `plan` runs without "
            "one; `plan` will refuse (exit 3) naming what is missing."
        ),
    }


# --------------------------------------------------------------------------- #
# The verb
# --------------------------------------------------------------------------- #
def check() -> dict[str, Any]:
    """Report music-deck's current state as one structured document.

    Never raises. Never reports failure. A caller reads the facts and decides.
    """
    try:
        return _check()
    except Exception as exc:  # noqa: BLE001 - check reports, it never crashes
        # Reaching here is itself a fact worth reporting, and still not a failure.
        return {
            "tool": "music-deck",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "internal_error": f"{type(exc).__name__}: {exc}",
            "findings": [
                "check hit an unexpected internal error and reported it rather than "
                "failing. The tool is installed and runnable; something it inspected "
                "is not."
            ],
        }


def _check() -> dict[str, Any]:
    config, config_problem = _read_json(config_path())
    token, token_problem = _read_json(token_path())

    client_id = _client_id_fact(config)
    redirect_uri = _redirect_uri_fact(config)
    token_file = _token_file_fact()
    if token_problem is not None:
        token_file["error"] = f"{token_path()} {token_problem}"
    access_token, refresh_token = _token_facts(token)
    scopes = _scopes_fact(token)
    allowlist = _allowlist_fact()
    provider = _provider_fact()

    findings: list[str] = []
    if not client_id["present"]:
        findings.append(
            "No Spotify client ID is configured. music-deck ships none by design -- "
            "register your own app, then run `music-deck setup --client-id <id>`. "
            "Run `music-deck setup` for the steps."
        )
    if not redirect_uri["conforms"]:
        findings.append(f"Redirect URI {redirect_uri['value']!r}: {redirect_uri['detail']}")
    if not token_file["present"]:
        findings.append("Not signed in to Spotify. Run `music-deck login`.")
    elif token_file.get("mode_ok") is False:
        findings.append(
            f"The token file is mode {token_file.get('mode')}, not 0600. "
            f"Run: chmod 600 {token_file['path']}"
        )
    if refresh_token.get("past_wall"):
        findings.append(
            "The refresh token is past Spotify's six-month wall. Run `music-deck login`."
        )
    elif isinstance(refresh_token.get("days_remaining"), (int, float)) and refresh_token[
        "days_remaining"
    ] < 14:
        findings.append(
            f"The refresh token expires in about {refresh_token['days_remaining']} days. "
            "Run `music-deck login` before then."
        )
    if allowlist["state"] == "suspect":
        findings.append(
            "A 403 was recorded. On a Development Mode app that usually means this "
            "account is not on the app's allowlist. Run `music-deck setup` for the "
            "steps, including User Management."
        )
    if config_problem is not None:
        findings.append(f"The config file at {config_path()} {config_problem}.")
    if token_problem is not None:
        findings.append(f"The token file at {token_path()} {token_problem}.")

    ready_for_spotify = bool(
        client_id["present"]
        and redirect_uri["conforms"]
        and token_file["present"]
        and token_problem is None
        and refresh_token.get("past_wall") is not True
    )

    return {
        "tool": "music-deck",
        "version": _version(),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "config_path": str(config_path()),
        "state_dir": str(state_dir()),
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "token_file": token_file,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "scopes": scopes,
        "allowlist": allowlist,
        "provider": provider,
        "ready": {
            "spotify_verbs": ready_for_spotify,
            "plan": bool(provider["configured"]),
        },
        "findings": findings,
    }


def _version() -> str:
    try:
        from importlib.metadata import version

        return version("music-deck")
    except Exception:  # noqa: BLE001 - a version we cannot read is not a failure
        return "unknown"
