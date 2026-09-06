"""PKCE authorisation against the caller's own Spotify app, and the token cache.

``boundary.v1`` Core 4, verbatim (rewritten 2026-09-06): "Auth is PKCE only, with
the caller's own client ID. The redirect URI is a loopback IP literal on a
**fixed, registered port** -- ``http://127.0.0.1:8888`` by default, never
``localhost`` -- and ``login`` binds exactly the port the caller registered. One
value, reported by ``check`` and used by ``login``: a redirect URI a caller can
read but the tool does not honour is worse than none. Plain HTTP only because the
host is loopback. The token lives at ``$XDG_STATE_HOME/music-deck/token.json``,
mode ``0600``. No client secret anywhere, and no credential ships with the tool."

Every one of those is load-bearing, and each has a reason drawn from evidence
rather than habit (``investigation/B-spotify-api-reality.md``):

* **PKCE, not authorization-code.** A CLI is a public client: there is nowhere
  safe to keep a secret, and Spotify says so itself -- "In scenarios where
  storing the client secret is not safe ... you can use the authorization code
  with PKCE" (B section 1.2). Client credentials is the other secretless-looking
  option and is useless here: it yields no user context at all, so no playlists,
  no library, no playback.
* **``127.0.0.1``, never ``localhost``.** Spotify's redirect-URI rules, enforced
  for new apps since 2025-04-09: "``localhost`` is not allowed as redirect URI"
  (B section 1.3). The string in nearly every pre-2025 tutorial is now rejected.
* **A fixed, registered port -- not an ephemeral one.** Spotify's documentation
  says the opposite: "If you don't know the port number in advance, register your
  redirect URI with a loopback IP literal, but without any port number" (B
  section 1.3). Its dashboard refused exactly that registration on 2026-09-06,
  and the dashboard is the reality a caller meets. So the port is resolved once
  by :func:`music_deck.check.resolve_redirect_uri` -- the same call ``check``
  makes -- and :class:`LoopbackReceiver` binds that port or refuses naming it.
  The whole URI stays overridable via ``MUSIC_DECK_REDIRECT_URI`` for a caller
  whose dashboard demands something else again.
* **The six-month wall.** "Refresh tokens issued to apps registered in the
  Developer Dashboard have a lifetime of 6 months" and "refreshing an access
  token does not extend the refresh token's lifetime" (B section 1.4). music-deck
  therefore detects the wall and refuses ``reauthorization_required`` *before*
  spending a request, rather than discovering it as a mystery 401.

The token file
--------------
One JSON object at ``$XDG_STATE_HOME/music-deck/token.json``, mode ``0600``,
written atomically. ``check`` (``src/music_deck/check.py``) reads exactly these
keys, so the shape is a shared surface between the two modules:

.. code-block:: json

    {
      "access_token":  "...",            // the bearer, good for one hour
      "token_type":    "Bearer",
      "refresh_token": "...",            // six months from `authorized_at`
      "scopes":        ["user-read-private", "..."],
      "expires_at":    "2026-09-04T12:00:00+00:00",   // ISO 8601, UTC
      "authorized_at": "2026-09-04T11:00:00+00:00",   // when `login` last ran
      "redirect_uri":  "http://127.0.0.1:8888",       // the registered URI, bound
      "client_id":     "..."             // not a secret; PKCE has no secret
    }

``authorized_at`` is set by ``login`` and **never** moved by a refresh -- that is
what makes the six-month wall computable at all.

No client secret appears in this file, in this module, or anywhere else in
``src/``; ``tests/test_auth.py`` asserts that statically.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import socket
import stat
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Final, Mapping

from music_deck.check import (
    DEFAULT_REDIRECT_URI,
    REFRESH_TOKEN_WALL_DAYS,
    TOKEN_FILE_MODE,
    config_path,
    redirect_uri_parts,
    redirect_uri_remedy,
    redirect_uri_shape,
    resolve_redirect_uri,
    state_dir,
    token_path,
)
from music_deck.errors import ErrorCode, MusicDeckError
from music_deck.http import Request, Response, Transport, UrllibTransport

ACCOUNTS_BASE: Final = "https://accounts.spotify.com"
AUTHORIZE_URL: Final = f"{ACCOUNTS_BASE}/authorize"
TOKEN_URL: Final = f"{ACCOUNTS_BASE}/api/token"

LOOPBACK_HOST: Final = "127.0.0.1"
"""``boundary.v1`` Core 4. The IP literal, never the name ``localhost``."""

CLIENT_ID_ENV: Final = "MUSIC_DECK_CLIENT_ID"
CLIENT_ID_ENV_ALIAS: Final = "SPOTIFY_CLIENT_ID"
"""A documented alias. ``MUSIC_DECK_CLIENT_ID`` wins when both are set."""

ACCESS_TOKEN_SKEW_S: Final = 60
"""Refresh a token this many seconds before it expires, not after."""

DEFAULT_SCOPES: Final[tuple[str, ...]] = (
    # Who am I -- `whoami`.
    "user-read-private",
    # Playlists -- `playlists`, `playlist items|create|add|remove|reorder|rename`.
    "playlist-read-private",
    "playlist-read-collaborative",
    "playlist-modify-private",
    "playlist-modify-public",
    # Library -- `library list|save|remove|contains`, and follow, which is now
    # library semantics (PUT /me/library with an artist URI).
    "user-library-read",
    "user-library-modify",
    "user-follow-read",
    # Listening history -- `top`, `recently-played`, resume position on shows.
    "user-top-read",
    "user-read-recently-played",
    "user-read-playback-position",
    # Spotify Connect -- `now-playing`, `devices`, `queue`, and every transport
    # control. Writes additionally need Premium, which no scope can grant.
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
)
"""The minimum set that covers the verbs ``cli.v1`` Core 2 names. Not `streaming`
or `app-remote-control` (browser/mobile SDKs only), not `user-read-email` (the
February 2026 changes stopped returning an email at all), not `ugc-image-upload`
(no verb uploads a cover)."""


# --------------------------------------------------------------------------- #
# The client ID -- the caller brings their own; none ships with the tool
# --------------------------------------------------------------------------- #
def resolve_client_id() -> tuple[str | None, str | None]:
    """``(client_id, where it came from)``, or ``(None, None)``.

    Order: ``MUSIC_DECK_CLIENT_ID``, then the documented alias
    ``SPOTIFY_CLIENT_ID``, then ``client_id`` in the config file. Never raises --
    ``check`` needs to ask this question without failing.
    """
    for name in (CLIENT_ID_ENV, CLIENT_ID_ENV_ALIAS):
        value = os.environ.get(name, "").strip()
        if value:
            return value, f"environment {name}"

    path = config_path()
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - an unreadable config is "not configured"
        return None, None
    if isinstance(document, dict):
        value = document.get("client_id")
        if isinstance(value, str) and value.strip():
            return value.strip(), f"config file {path}"
    return None, None


def require_client_id() -> tuple[str, str]:
    """The client ID, or a loud refusal naming exactly how to supply one.

    Exits ``2``: ``cli.v1`` Core 5 puts "invalid input" there, and a run with no
    client ID has been given no usable input. A new code would fork the frozen
    vocabulary of Core 6, which this module does not own.
    """
    client_id, source = resolve_client_id()
    if client_id:
        return client_id, source or "unknown"
    raise MusicDeckError(
        ErrorCode.USAGE,
        "No Spotify client ID is configured. music-deck ships none by design: "
        "you run it against your own Spotify app, under your own quota.",
        f'Run `music-deck setup --client-id <your client id>` to write it, or '
        f'set {CLIENT_ID_ENV} (or {CLIENT_ID_ENV_ALIAS}). Run `music-deck setup` '
        f'with no arguments for the steps to register a Spotify app.',
    )


# --------------------------------------------------------------------------- #
# PKCE
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PkcePair:
    """A code verifier and the challenge derived from it."""

    verifier: str
    challenge: str
    method: str = "S256"


def new_pkce_pair() -> PkcePair:
    """A fresh verifier/challenge pair, to Spotify's stated rules.

    B section 1.2: verifier is 43-128 characters from ``[A-Za-z0-9_.-~]``;
    challenge is ``base64url(SHA256(verifier))`` with padding stripped.
    ``secrets.token_urlsafe(64)`` yields 86 characters from ``[A-Za-z0-9_-]``,
    inside both bounds and inside the alphabet.
    """
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return PkcePair(verifier=verifier, challenge=challenge)


def authorize_url(
    client_id: str,
    redirect_uri: str,
    challenge: str,
    state: str,
    scopes: tuple[str, ...] = DEFAULT_SCOPES,
) -> str:
    """The URL to open in a browser. Carries the challenge, never the verifier."""
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": " ".join(scopes),
            "code_challenge_method": "S256",
            "code_challenge": challenge,
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


# --------------------------------------------------------------------------- #
# The loopback receiver -- the fixed, registered port, and no other
# --------------------------------------------------------------------------- #
class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Catches Spotify's redirect and hands the query back to the receiver."""

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's spelling
        parsed = urllib.parse.urlsplit(self.path)
        query = {
            key: values[0]
            for key, values in urllib.parse.parse_qs(parsed.query).items()
            if values
        }
        server: Any = self.server
        if "code" in query or "error" in query:
            server.callback_query = query
            body = (
                b"<!doctype html><meta charset=utf-8><title>music-deck</title>"
                b"<p>music-deck is authorised. You can close this tab and return "
                b"to your terminal.</p>"
            )
            status = 200
        else:
            body = b"<!doctype html><meta charset=utf-8><p>Nothing to do here.</p>"
            status = 404
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: Any) -> None:
        """Silence. ``cli.v1`` Core 4 keeps stdout for the one JSON document."""


class _IPv6Server(http.server.HTTPServer):
    """``HTTPServer`` for an ``[::1]`` redirect URI. Same server, other family."""

    address_family = socket.AF_INET6


class LoopbackReceiver:
    """A one-shot HTTP server on **the registered redirect URI**, or nothing.

    ``boundary.v1`` Core 4, rewritten 2026-09-06: the redirect URI is a loopback
    IP literal on a *fixed, registered* port, and "``login`` binds exactly the
    port the caller registered. One value, reported by ``check`` and used by
    ``login``." So this takes that value -- from
    :func:`music_deck.check.resolve_redirect_uri`, the one resolver ``check``
    reads too -- and binds precisely it.

    What it deliberately does **not** do is fall back. Port ``0`` (ask the kernel
    for any free port) is exactly how the tool used to contradict its own report:
    ``check`` said one URI, ``login`` sent another, and Spotify rejected the
    registration the caller had been told to make. A port that is taken is
    therefore a loud refusal naming the port, never a quiet substitution.
    """

    def __init__(self, redirect_uri: str | None = None) -> None:
        self.redirect_uri: str = redirect_uri or resolve_redirect_uri()[0]

        conforms, detail = redirect_uri_shape(self.redirect_uri)
        if not conforms:
            raise MusicDeckError(
                ErrorCode.USAGE,
                f"The redirect URI {self.redirect_uri!r} cannot be used: {detail}",
                redirect_uri_remedy(self.redirect_uri),
                redirect_uri=self.redirect_uri,
            )

        host, port = redirect_uri_parts(self.redirect_uri)
        self.host: str = host
        self.port: int = int(port)  # redirect_uri_shape has proved it is a port

        server_class = _IPv6Server if ":" in host else http.server.HTTPServer
        try:
            self._server = server_class((host, self.port), _CallbackHandler)
        except OSError as exc:
            raise MusicDeckError(
                ErrorCode.PORT_UNAVAILABLE,
                f"Port {self.port} on {host} is already in use, so music-deck "
                f"cannot receive Spotify's redirect at {self.redirect_uri} "
                f"({exc.strerror or exc}). It will not bind a different port: the "
                f"port it binds has to be the one your Spotify app has "
                f"registered.",
                f"Free port {self.port}, or choose another and register it: run "
                f"`music-deck setup --port <n>`, set the app's redirect URI to "
                f"http://{host}:<n> in the Spotify dashboard, then run "
                f"`music-deck login` again. `music-deck check` reports the port "
                f"music-deck will use.",
                port=self.port,
                redirect_uri=self.redirect_uri,
            ) from exc
        self._server.callback_query = None  # type: ignore[attr-defined]

    def wait(self, timeout_s: float, clock: Callable[[], float] | None = None) -> dict[str, str]:
        """Serve until the redirect arrives, or refuse when the time is up.

        Bounded on purpose: ``cli.v1`` Core 1 says a run never hangs, and an
        unbounded wait for a browser the user may have closed is a hang.
        """
        import time as _time

        now = clock or _time.monotonic
        deadline = now() + timeout_s
        self._server.timeout = 0.5
        while now() < deadline:
            self._server.handle_request()
            query = getattr(self._server, "callback_query", None)
            if query:
                return query
        raise MusicDeckError(
            ErrorCode.NOT_AUTHENTICATED,
            f"No authorisation came back within {timeout_s:g}s. music-deck stopped "
            f"waiting rather than hanging.",
            "Run `music-deck login` again and complete the Spotify page in the "
            "browser it opens.",
        )

    def close(self) -> None:
        self._server.server_close()

    def __enter__(self) -> "LoopbackReceiver":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()


# --------------------------------------------------------------------------- #
# The token file
# --------------------------------------------------------------------------- #
def read_token(path: Path | None = None) -> dict[str, Any] | None:
    """The stored token document, or ``None`` when there is not one."""
    target = path or token_path()
    try:
        document = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise MusicDeckError(
            ErrorCode.NOT_AUTHENTICATED,
            f"The token file at {target} could not be read: {exc}",
            "Run `music-deck login` to authorise again, or `music-deck disconnect` "
            "to clear the stored credentials first.",
        ) from exc
    if not isinstance(document, dict):
        raise MusicDeckError(
            ErrorCode.NOT_AUTHENTICATED,
            f"The token file at {target} is not a JSON object.",
            "Run `music-deck disconnect`, then `music-deck login`.",
        )
    return document


def write_token(document: Mapping[str, Any], path: Path | None = None) -> Path:
    """Write the token document at mode ``0600``, atomically.

    ``boundary.v1`` Core 4 fixes the mode. The file is created with ``0600`` from
    the first byte -- never written world-readable and narrowed afterwards, which
    would leave a window in which the token was readable by anyone on the box.
    """
    target = path or token_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.partial")
    descriptor = os.open(
        temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, TOKEN_FILE_MODE
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(dict(document), handle, indent=2, sort_keys=False)
            handle.write("\n")
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    os.chmod(temporary, TOKEN_FILE_MODE)  # in case an umask or a prior file argued
    os.replace(temporary, target)
    os.chmod(target, TOKEN_FILE_MODE)
    return target


def token_file_mode(path: Path | None = None) -> int | None:
    """The token file's permission bits, or ``None`` when there is no file."""
    target = path or token_path()
    try:
        return stat.S_IMODE(target.stat().st_mode)
    except OSError:
        return None


# --------------------------------------------------------------------------- #
# Talking to accounts.spotify.com
# --------------------------------------------------------------------------- #
def _post_form(
    transport: Transport, fields: Mapping[str, str], timeout_s: float = 30.0
) -> Response:
    """POST ``application/x-www-form-urlencoded`` to Spotify's token endpoint."""
    body = urllib.parse.urlencode(fields).encode("utf-8")
    request = Request(
        "POST",
        TOKEN_URL,
        {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        body,
    )
    return transport.send(request, timeout_s)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _token_document(
    payload: Mapping[str, Any],
    *,
    client_id: str,
    redirect_uri: str,
    authorized_at: datetime,
    previous: Mapping[str, Any] | None = None,
    issued_at: datetime | None = None,
) -> dict[str, Any]:
    """Turn Spotify's token response into the document this tool stores.

    Spotify does not always return a refresh token on a refresh: "When a refresh
    token is not returned, continue using the existing token" (B section 1.4).
    Hence ``previous``.
    """
    moment = issued_at or _now()
    try:
        seconds = int(float(payload.get("expires_in")))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        seconds = 3600  # Spotify's documented default: an access token lasts an hour
    refresh = payload.get("refresh_token")
    if not (isinstance(refresh, str) and refresh.strip()) and previous:
        refresh = previous.get("refresh_token")
    scope = payload.get("scope")
    if isinstance(scope, str) and scope.strip():
        scopes = sorted({item for item in scope.split() if item})
    elif previous and isinstance(previous.get("scopes"), list):
        scopes = list(previous["scopes"])
    else:
        scopes = []
    return {
        "access_token": payload.get("access_token", ""),
        "token_type": payload.get("token_type", "Bearer"),
        "refresh_token": refresh or "",
        "scopes": scopes,
        "expires_at": (moment + timedelta(seconds=seconds)).isoformat(),
        "authorized_at": authorized_at.isoformat(),
        "redirect_uri": redirect_uri,
        "client_id": client_id,
    }


def exchange_code(
    *,
    client_id: str,
    code: str,
    verifier: str,
    redirect_uri: str,
    transport: Transport | None = None,
    now: Callable[[], datetime] = _now,
) -> dict[str, Any]:
    """Trade an authorisation code for tokens. No client secret is sent."""
    sender = transport if transport is not None else UrllibTransport()
    response = _post_form(
        sender,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    payload = response.json()
    if response.status >= 400 or not isinstance(payload, dict):
        raise MusicDeckError(
            ErrorCode.NOT_AUTHENTICATED,
            "Spotify refused the authorisation code "
            f"({response.status}): {_error_text(payload)}",
            "Run `music-deck login` again. If it keeps failing, check that the "
            "client ID belongs to an app whose registered redirect URI is exactly "
            f"{redirect_uri} -- `music-deck check` reports the value music-deck "
            "sends, and it has to match the dashboard character for character.",
        )
    moment = now()
    return _token_document(
        payload,
        client_id=client_id,
        redirect_uri=redirect_uri,
        authorized_at=moment,
        issued_at=moment,
    )


def refresh_token_document(
    token: Mapping[str, Any],
    *,
    client_id: str | None = None,
    transport: Transport | None = None,
    now: Callable[[], datetime] = _now,
) -> dict[str, Any]:
    """Renew the access token, keeping ``authorized_at`` where it was.

    Refreshing does not extend the six-month refresh-token lifetime (B section
    1.4), so moving ``authorized_at`` would quietly hide the wall until a request
    failed. It stays put.
    """
    refresh = token.get("refresh_token")
    if not (isinstance(refresh, str) and refresh.strip()):
        raise MusicDeckError(
            ErrorCode.NOT_AUTHENTICATED,
            "There is no refresh token stored, so the access token cannot be "
            "renewed.",
        )
    resolved_client_id = client_id or token.get("client_id") or require_client_id()[0]
    sender = transport if transport is not None else UrllibTransport()
    response = _post_form(
        sender,
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": str(resolved_client_id),
        },
    )
    payload = response.json()
    if response.status >= 400 or not isinstance(payload, dict):
        raise MusicDeckError(
            ErrorCode.REAUTHORIZATION_REQUIRED,
            "Spotify rejected the refresh token "
            f"({response.status}): {_error_text(payload)}. Spotify's own guidance "
            "is to discard it and send the user through authorisation again "
            "rather than retry.",
        )
    authorized_at = _parse_moment(token.get("authorized_at")) or now()
    return _token_document(
        payload,
        client_id=str(resolved_client_id),
        redirect_uri=str(token.get("redirect_uri") or resolve_redirect_uri()[0]),
        authorized_at=authorized_at,
        previous=token,
        issued_at=now(),
    )


def _error_text(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("error_description", "error", "message"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return "no description in the response"


def _parse_moment(value: Any) -> datetime | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def past_refresh_wall(token: Mapping[str, Any], now: datetime | None = None) -> bool:
    """Whether the six months since ``login`` have run out."""
    authorized_at = _parse_moment(token.get("authorized_at"))
    if authorized_at is None:
        return False  # unknowable is not "expired" -- let Spotify answer
    moment = now or _now()
    return (moment - authorized_at) >= timedelta(days=REFRESH_TOKEN_WALL_DAYS)


# --------------------------------------------------------------------------- #
# What SpotifyClient asks for a bearer token
# --------------------------------------------------------------------------- #
class FileTokenSource:
    """The stored token, kept fresh. Implements ``http.TokenSource``.

    Refuses in exactly two words, and never a third: ``not_authenticated`` when
    there is nothing usable to start from (``boundary.v1`` Core 5: every verb but
    ``login`` says so and names ``music-deck login``), and
    ``reauthorization_required`` when there *was* something and Spotify will not
    renew it -- including the six-month wall, which is checked before a request
    is spent finding out.
    """

    def __init__(
        self,
        *,
        transport: Transport | None = None,
        path: Path | None = None,
        now: Callable[[], datetime] = _now,
        client_id: str | None = None,
    ) -> None:
        self._transport = transport
        self._path = path
        self._now = now
        self._client_id = client_id
        self._token: dict[str, Any] | None = None

    # -- reading ------------------------------------------------------------- #
    def token(self) -> dict[str, Any]:
        if self._token is None:
            document = read_token(self._path)
            if document is None:
                raise MusicDeckError(
                    ErrorCode.NOT_AUTHENTICATED,
                    "music-deck is not signed in to Spotify: there is no token at "
                    f"{self._path or token_path()}.",
                )
            self._token = document
        return self._token

    def can_refresh(self) -> bool:
        try:
            token = self.token()
        except MusicDeckError:
            return False
        refresh = token.get("refresh_token")
        return bool(isinstance(refresh, str) and refresh.strip())

    def bearer(self) -> str:
        token = self.token()
        if past_refresh_wall(token, self._now()):
            raise MusicDeckError(
                ErrorCode.REAUTHORIZATION_REQUIRED,
                "This authorisation is past Spotify's six-month refresh-token "
                "wall. Refreshing never extended it, so it cannot be renewed.",
            )
        access = token.get("access_token")
        expires_at = _parse_moment(token.get("expires_at"))
        fresh = (
            isinstance(access, str)
            and access.strip()
            and expires_at is not None
            and (expires_at - self._now()).total_seconds() > ACCESS_TOKEN_SKEW_S
        )
        if fresh:
            return str(access)
        if self.can_refresh():
            return self.refresh()
        if isinstance(access, str) and access.strip() and expires_at is None:
            # The file records no readable expiry, so "expired" is not something
            # this can know. Let Spotify be the judge rather than refuse on
            # arithmetic that was never possible.
            return str(access)
        raise MusicDeckError(
            ErrorCode.NOT_AUTHENTICATED,
            "The stored access token has expired and there is no refresh token to "
            "renew it with.",
        )

    # -- renewing ------------------------------------------------------------ #
    def refresh(self) -> str:
        token = self.token()
        if past_refresh_wall(token, self._now()):
            raise MusicDeckError(
                ErrorCode.REAUTHORIZATION_REQUIRED,
                "This authorisation is past Spotify's six-month refresh-token "
                "wall and cannot be renewed.",
            )
        renewed = refresh_token_document(
            token,
            client_id=self._client_id,
            transport=self._transport,
            now=self._now,
        )
        write_token(renewed, self._path)
        self._token = renewed
        access = renewed.get("access_token")
        if not (isinstance(access, str) and access.strip()):
            raise MusicDeckError(
                ErrorCode.REAUTHORIZATION_REQUIRED,
                "Spotify's refresh response carried no access token.",
            )
        return access


def state_files() -> list[Path]:
    """Everything music-deck has put in its state directory. Used by `disconnect`."""
    directory = state_dir()
    try:
        return sorted(path for path in directory.rglob("*") if path.is_file())
    except OSError:
        return []
