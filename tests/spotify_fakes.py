"""Test support: a Spotify that never leaves the machine.

Every test in this repository that exercises the Spotify boundary uses the
:class:`FakeTransport` below. That is not a convention -- it is the mechanism
that makes "no test ever reaches ``api.spotify.com``" true rather than intended:
:func:`use_fake_transport` replaces ``UrllibTransport`` in **both** namespaces
that construct one (``music_deck.http`` for API calls, ``music_deck.auth`` for
token calls), so a request that this file did not queue raises instead of
opening a socket.

The helpers here are deliberately dumb. A fake that interprets requests would be
a second implementation of the client under test, and would pass for reasons the
real Spotify never would.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Mapping, Sequence

import music_deck.auth as auth_module
import music_deck.http as http_module
from music_deck import cli
from music_deck.http import Request, Response

DEFAULT_SCOPES_SAMPLE = ["playlist-read-private", "user-read-private"]


# --------------------------------------------------------------------------- #
# Responses
# --------------------------------------------------------------------------- #
def json_response(
    status: int, payload: Any = None, headers: Mapping[str, str] | None = None
) -> Response:
    """A response whose body is JSON (or empty, for a 204)."""
    body = b"" if payload is None else json.dumps(payload).encode("utf-8")
    merged = {"Content-Type": "application/json"} if payload is not None else {}
    merged.update(dict(headers or {}))
    return Response(status=status, headers=merged, body=body)


def spotify_error(status: int, message: str, reason: str | None = None) -> dict[str, Any]:
    """Spotify's own error envelope: ``{"error": {"status", "message", ...}}``."""
    error: dict[str, Any] = {"status": status, "message": message}
    if reason is not None:
        error["reason"] = reason
    return {"error": error}


# --------------------------------------------------------------------------- #
# The transport
# --------------------------------------------------------------------------- #
class FakeTransport:
    """Answers queued responses in order and records every request it was given.

    An unqueued request is an error, not an empty answer: a test that sends more
    requests than it expected is a test whose subject changed behaviour.
    """

    def __init__(self, responses: Sequence[Response | Callable[[Request], Response]] = ()) -> None:
        self.responses: list[Response | Callable[[Request], Response]] = list(responses)
        self.requests: list[Request] = []

    def queue(self, *responses: Response | Callable[[Request], Response]) -> "FakeTransport":
        self.responses.extend(responses)
        return self

    def send(self, request: Request, timeout_s: float = 30.0) -> Response:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError(
                f"the tool sent an unexpected request: {request.method} {request.url}"
            )
        item = self.responses.pop(0)
        return item(request) if callable(item) else item

    # -- what happened ------------------------------------------------------- #
    @property
    def calls(self) -> list[str]:
        return [f"{request.method} {request.url}" for request in self.requests]

    def urls(self) -> list[str]:
        return [request.url for request in self.requests]

    def bodies(self) -> list[str]:
        return [
            request.body.decode("utf-8") if request.body else "" for request in self.requests
        ]


def use_fake_transport(monkeypatch, transport: FakeTransport) -> FakeTransport:
    """Point every code path that would build a real transport at ``transport``."""

    def factory(*_args: Any, **_kwargs: Any) -> FakeTransport:
        return transport

    monkeypatch.setattr(http_module, "UrllibTransport", factory)
    monkeypatch.setattr(auth_module, "UrllibTransport", factory)
    return transport


def record_sleeps(monkeypatch) -> list[float]:
    """Capture the bounded retry's wait without paying for it in wall-clock time."""
    slept: list[float] = []
    monkeypatch.setattr(http_module, "_default_sleep", slept.append)
    return slept


# --------------------------------------------------------------------------- #
# The token file
# --------------------------------------------------------------------------- #
def token_document(
    *,
    access_token: str = "access-token-under-test",
    refresh_token: str | None = "refresh-token-under-test",
    expires_in_s: float = 3600,
    authorized_days_ago: float = 1.0,
    scopes: Iterable[str] = tuple(DEFAULT_SCOPES_SAMPLE),
    client_id: str = "client-id-under-test",
    redirect_uri: str = "http://127.0.0.1:41234",
    now: datetime | None = None,
) -> dict[str, Any]:
    """A stored token in exactly the shape ``auth.write_token`` produces."""
    moment = now or datetime.now(timezone.utc)
    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "refresh_token": refresh_token or "",
        "scopes": list(scopes),
        "expires_at": (moment + timedelta(seconds=expires_in_s)).isoformat(),
        "authorized_at": (moment - timedelta(days=authorized_days_ago)).isoformat(),
        "redirect_uri": redirect_uri,
        "client_id": client_id,
    }


def install_token(monkeypatch, tmp_path, document: Mapping[str, Any] | None = None):
    """Point music-deck's config and state at ``tmp_path`` and store a token.

    Returns the token path. Nothing in the caller's real ``~/.local/state`` is
    read or written by any test that uses this.
    """
    state = tmp_path / "state"
    config = tmp_path / "config"
    state.mkdir(parents=True, exist_ok=True)
    config.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MUSIC_DECK_STATE_DIR", str(state))
    monkeypatch.setenv("MUSIC_DECK_CONFIG_DIR", str(config))
    monkeypatch.setenv("MUSIC_DECK_CLIENT_ID", "client-id-under-test")
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    path = state / "token.json"
    if document is not None:
        auth_module.write_token(document, path)
    return path


# --------------------------------------------------------------------------- #
# Running the real CLI in-process
# --------------------------------------------------------------------------- #
def run_cli(capsys, *argv: str) -> tuple[int, Any, str]:
    """``(exit_code, parsed stdout, stderr)`` from the real ``main()``.

    In-process rather than a subprocess because the point of these tests is what
    happens when a *mocked* Spotify answers -- and a subprocess cannot be handed
    a fake transport. Everything else is the shipping path: the same parser, the
    same dispatch, the same envelope, the same exit code.
    """
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    parsed = json.loads(captured.out) if captured.out.strip() else None
    return code, parsed, captured.err


def run_probe(monkeypatch, capsys, call: Callable[[], Any]) -> tuple[int, Any, str]:
    """Run the whole CLI pipeline with ``whoami``'s handler replaced by ``call``.

    Three of the refusals this lane must produce -- ``no_active_device``,
    ``premium_required`` from a player write, ``playlist_items_unavailable`` --
    are decided by the *path* being requested, and the verbs that request those
    paths belong to later lanes (MD-3, MD-4). Rather than assert the code from
    inside the library and call that "the CLI emits it", this swaps in a stand-in
    handler that makes exactly the call the missing verb will make, and then runs
    the real parser, the real dispatch, the real envelope and the real exit code
    over it.
    """
    probe = dataclasses.replace(cli.VERBS_BY_NAME["whoami"], handler=lambda _args: call())
    monkeypatch.setattr(
        cli, "VERBS", tuple(probe if verb.name == "whoami" else verb for verb in cli.VERBS)
    )
    return run_cli(capsys, "whoami")
