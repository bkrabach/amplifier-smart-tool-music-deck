"""PKCE authorisation, the token cache, and `login` driven end to end.

Contracts served: ``boundary.v1`` Core 4 (PKCE only, the caller's own client ID,
a loopback IP-literal redirect with an ephemeral port, a token file at mode
``0600``, no client secret anywhere) and Core 5 (``login`` is the only
interactive verb; every other verb refuses ``not_authenticated`` and names
``music-deck login``).

`login` is exercised for real: a loopback receiver is bound on a real ephemeral
port, a stand-in browser performs the redirect Spotify would perform, and a
stand-in transport answers the token exchange. What is *not* stood in for is the
code under test -- the PKCE pair, the URL, the receiver, the exchange, the file
write and its mode are all the shipping ones.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pytest
from spotify_fakes import (
    FakeTransport,
    install_token,
    json_response,
    run_cli,
    token_document,
    use_fake_transport,
)

from music_deck import auth
from music_deck.errors import EXIT_FAILURE, EXIT_REFUSAL, EXIT_SUCCESS, ErrorCode
from music_deck.verbs.auth_verbs import login

TOKEN_RESPONSE = {
    "access_token": "fresh-access-token",
    "token_type": "Bearer",
    "expires_in": 3600,
    "refresh_token": "fresh-refresh-token",
    "scope": "user-read-private playlist-read-private",
}
ME_RESPONSE = {"id": "deckuser", "display_name": "Deck User", "uri": "spotify:user:deckuser"}


# --------------------------------------------------------------------------- #
# PKCE -- B section 1.2
# --------------------------------------------------------------------------- #
def test_the_verifier_is_within_spotifys_stated_bounds_and_alphabet():
    for _ in range(20):
        pair = auth.new_pkce_pair()
        assert 43 <= len(pair.verifier) <= 128
        assert re.fullmatch(r"[A-Za-z0-9_.\-~]+", pair.verifier)


def test_the_challenge_is_unpadded_base64url_of_the_sha256_of_the_verifier():
    pair = auth.new_pkce_pair()
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(pair.verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    assert pair.challenge == expected
    assert "=" not in pair.challenge
    assert pair.method == "S256"


def test_every_login_gets_a_fresh_verifier():
    assert len({auth.new_pkce_pair().verifier for _ in range(50)}) == 50


def test_the_authorization_url_carries_the_challenge_and_never_the_verifier():
    pair = auth.new_pkce_pair()
    url = auth.authorize_url("client-abc", "http://127.0.0.1:5000", pair.challenge, "state-1")
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)

    assert url.startswith("https://accounts.spotify.com/authorize?")
    assert query["code_challenge"] == [pair.challenge]
    assert query["code_challenge_method"] == ["S256"]
    assert query["response_type"] == ["code"]
    assert query["client_id"] == ["client-abc"]
    assert pair.verifier not in url
    assert "client_secret" not in url


# --------------------------------------------------------------------------- #
# The redirect URI -- B section 1.3
# --------------------------------------------------------------------------- #
def test_the_redirect_uri_is_a_loopback_ip_literal_with_a_bound_port():
    """"`localhost` is not allowed as redirect URI" -- Spotify, enforced since
    2025-04-09. The port is whatever the kernel handed out, which is why the app
    is registered without one."""
    with auth.LoopbackReceiver() as receiver:
        uri = receiver.redirect_uri

    assert uri.startswith("http://127.0.0.1:")
    assert "localhost" not in uri
    port = int(uri.rsplit(":", 1)[1])
    assert 1024 < port < 65536


def test_two_receivers_do_not_fight_over_a_port():
    with auth.LoopbackReceiver() as first, auth.LoopbackReceiver() as second:
        assert first.port != second.port


# --------------------------------------------------------------------------- #
# The token file -- boundary.v1 Core 4
# --------------------------------------------------------------------------- #
def test_the_token_file_is_written_at_mode_0600(tmp_path):
    path = tmp_path / "state" / "token.json"
    auth.write_token(token_document(), path)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_loose_pre_existing_token_file_is_tightened_not_inherited(tmp_path):
    path = tmp_path / "state" / "token.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}", encoding="utf-8")
    os.chmod(path, 0o644)

    auth.write_token(token_document(), path)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_the_token_file_is_exactly_what_check_reads(monkeypatch, tmp_path):
    """The shape is a shared surface: MD-1's `check` reads what this lane writes.

    Asserted by running the real `check` over a real written token rather than by
    comparing two lists of key names.
    """
    from music_deck.check import check

    install_token(monkeypatch, tmp_path, token_document(authorized_days_ago=10))
    report = check()

    assert report["token_file"]["present"] is True
    assert report["token_file"]["mode"] == "0600"
    assert report["token_file"]["mode_ok"] is True
    assert report["access_token"]["present"] is True
    assert report["access_token"]["expired"] is False
    assert report["refresh_token"]["present"] is True
    assert report["refresh_token"]["past_wall"] is False
    assert 172 < report["refresh_token"]["days_remaining"] < 174
    assert report["scopes"]["known"] is True


# --------------------------------------------------------------------------- #
# The client ID -- the caller brings their own
# --------------------------------------------------------------------------- #
def test_the_client_id_comes_from_the_environment_then_the_alias_then_config(
    monkeypatch, tmp_path
):
    config = tmp_path / "config"
    config.mkdir()
    monkeypatch.setenv("MUSIC_DECK_CONFIG_DIR", str(config))
    (config / "config.json").write_text(json.dumps({"client_id": "from-config"}))

    monkeypatch.delenv("MUSIC_DECK_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    assert auth.resolve_client_id() == ("from-config", f"config file {config / 'config.json'}")

    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "from-alias")
    assert auth.resolve_client_id() == ("from-alias", "environment SPOTIFY_CLIENT_ID")

    monkeypatch.setenv("MUSIC_DECK_CLIENT_ID", "from-primary")
    assert auth.resolve_client_id() == ("from-primary", "environment MUSIC_DECK_CLIENT_ID")


def test_login_with_no_client_id_refuses_loudly_and_opens_no_browser(
    monkeypatch, tmp_path, capsys
):
    """music-deck ships no credential, so this is the first thing a new user meets.
    It must be a readable refusal, not a browser window and a Spotify error page."""
    monkeypatch.setenv("MUSIC_DECK_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MUSIC_DECK_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("MUSIC_DECK_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url, **_: opened.append(url) or True)

    code, document, _ = run_cli(capsys, "login")

    assert code == EXIT_REFUSAL
    error = document["error"]
    assert error["code"] == ErrorCode.USAGE
    assert "MUSIC_DECK_CLIENT_ID" in error["remedy"]
    assert opened == []


# --------------------------------------------------------------------------- #
# login, end to end
# --------------------------------------------------------------------------- #
class BrowserStandIn:
    """Does what a browser does: fetches the authorisation URL's redirect.

    Spotify's part of the round trip is the only thing simulated -- it redirects
    to the loopback URI carrying `code` and the `state` it was given. The
    receiver, the exchange and the file write are the real ones.
    """

    def __init__(self, *, code: str = "authorisation-code", state: str | None = None) -> None:
        self.code = code
        self.state_override = state
        self.urls: list[str] = []
        self.errors: list[Exception] = []

    def __call__(self, url: str) -> bool:
        self.urls.append(url)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        redirect = query["redirect_uri"][0]
        state = self.state_override or query["state"][0]
        target = f"{redirect}/?{urllib.parse.urlencode({'code': self.code, 'state': state})}"

        def visit() -> None:
            try:
                with urllib.request.urlopen(target, timeout=5) as reply:
                    reply.read()
            except Exception as exc:  # noqa: BLE001 - reported, never swallowed
                self.errors.append(exc)

        threading.Thread(target=visit, daemon=True).start()
        return True


@pytest.fixture
def xdg_state(monkeypatch, tmp_path):
    """State under $XDG_STATE_HOME, the path boundary.v1 Core 4 names."""
    monkeypatch.delenv("MUSIC_DECK_STATE_DIR", raising=False)
    monkeypatch.delenv("MUSIC_DECK_CONFIG_DIR", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setenv("MUSIC_DECK_CLIENT_ID", "client-id-under-test")
    return tmp_path / "xdg-state" / "music-deck" / "token.json"


def test_login_completes_and_leaves_a_0600_token_at_the_contracted_path(
    monkeypatch, xdg_state
):
    use_fake_transport(
        monkeypatch,
        FakeTransport([json_response(200, TOKEN_RESPONSE), json_response(200, ME_RESPONSE)]),
    )
    browser = BrowserStandIn()

    result = login(timeout_s=10, open_browser=browser, stdin_isatty=lambda: False)

    assert browser.errors == []
    assert result["signed_in"] is True
    assert result["account"]["id"] == "deckuser"
    # boundary.v1 Core 4: the path, and the mode.
    assert Path(result["token_path"]) == xdg_state
    assert xdg_state.exists()
    assert stat.S_IMODE(xdg_state.stat().st_mode) == 0o600
    assert result["token_mode"] == "0600"
    # boundary.v1 Core 4: the redirect URI actually used.
    assert re.fullmatch(r"http://127\.0\.0\.1:\d+", result["redirect_uri"])
    assert "localhost" not in browser.urls[0]
    assert f"redirect_uri={urllib.parse.quote(result['redirect_uri'], safe='')}" in browser.urls[0]


def test_login_sends_the_verifier_and_never_a_client_secret(monkeypatch, xdg_state):
    transport = use_fake_transport(
        monkeypatch,
        FakeTransport([json_response(200, TOKEN_RESPONSE), json_response(200, ME_RESPONSE)]),
    )
    browser = BrowserStandIn()

    login(timeout_s=10, open_browser=browser, stdin_isatty=lambda: False)

    exchange = transport.requests[0]
    assert exchange.url == "https://accounts.spotify.com/api/token"
    fields = urllib.parse.parse_qs(exchange.body.decode())
    assert fields["grant_type"] == ["authorization_code"]
    assert fields["code"] == ["authorisation-code"]
    assert fields["code_verifier"], "PKCE proves possession with the verifier"
    assert "client_secret" not in fields
    assert "Authorization" not in exchange.headers, "PKCE sends no basic-auth secret"


def test_login_refuses_a_callback_whose_state_does_not_match(monkeypatch, xdg_state):
    """The state parameter is the only thing that ties a callback to the request
    music-deck made. A mismatch stores nothing."""
    use_fake_transport(monkeypatch, FakeTransport())
    browser = BrowserStandIn(state="not-the-state-we-sent")

    with pytest.raises(Exception) as raised:
        login(timeout_s=10, open_browser=browser, stdin_isatty=lambda: False)

    assert raised.value.code == ErrorCode.NOT_AUTHENTICATED
    assert not xdg_state.exists()


def test_login_with_no_browser_and_no_terminal_fails_loud_and_fast(monkeypatch, xdg_state):
    """The work item's own honesty gate: `login` tested by a stdin-closed test,
    not by hand once. No browser opened and no terminal to paste into is the one
    situation that cannot be served -- so it refuses at once rather than waiting
    out a clock for an interaction that can never arrive."""
    use_fake_transport(monkeypatch, FakeTransport())
    started = time.monotonic()

    with pytest.raises(Exception) as raised:
        login(timeout_s=120, open_browser=lambda _url: False, stdin_isatty=lambda: False)

    assert raised.value.code == "no_browser"
    assert raised.value.exit_code == EXIT_FAILURE
    assert "interactive terminal" in raised.value.remedy
    assert raised.value.extra["authorize_url"].startswith("https://accounts.spotify.com/")
    assert time.monotonic() - started < 5.0
    assert not xdg_state.exists()


def test_login_stops_waiting_rather_than_hanging(monkeypatch, xdg_state):
    """cli.v1 Core 1: a run never hangs -- not even the interactive verb."""
    use_fake_transport(monkeypatch, FakeTransport())
    started = time.monotonic()

    with pytest.raises(Exception) as raised:
        login(timeout_s=0.6, open_browser=lambda _url: True, stdin_isatty=lambda: False)

    assert raised.value.code == ErrorCode.NOT_AUTHENTICATED
    assert "stopped waiting" in raised.value.message
    assert time.monotonic() - started < 5.0


def test_login_reports_the_refusal_when_spotify_declines(monkeypatch, xdg_state):
    use_fake_transport(monkeypatch, FakeTransport())

    class Declines(BrowserStandIn):
        def __call__(self, url: str) -> bool:
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            redirect = query["redirect_uri"][0]
            target = f"{redirect}/?error=access_denied&state={query['state'][0]}"
            threading.Thread(
                target=lambda: urllib.request.urlopen(target, timeout=5).read(), daemon=True
            ).start()
            return True

    with pytest.raises(Exception) as raised:
        login(timeout_s=10, open_browser=Declines(), stdin_isatty=lambda: False)

    assert raised.value.code == ErrorCode.NOT_AUTHENTICATED
    assert "access_denied" in raised.value.message
    assert not xdg_state.exists()


# --------------------------------------------------------------------------- #
# boundary.v1 Core 5, proved against the shipped binary
# --------------------------------------------------------------------------- #
_RUNNER = "import sys; from music_deck.cli import main; sys.exit(main())"


def _argv() -> list[str]:
    installed = shutil.which("music-deck")
    return [installed] if installed else [sys.executable, "-c", _RUNNER]


@pytest.mark.parametrize("verb", ["whoami", "disconnect"])
def test_an_unauthenticated_verb_refuses_fast_and_never_opens_a_browser(
    tmp_path, verb
):
    """boundary.v1 Core 5, end to end, as a real process with stdin closed.

    `BROWSER` points at a script that leaves a file behind if it is ever run, so
    "never opens a browser" is checked rather than assumed. Five seconds is the
    acceptance bar.
    """
    sentinel = tmp_path / "browser-was-opened"
    fake_browser = tmp_path / "fake-browser.sh"
    fake_browser.write_text(f'#!/bin/sh\ntouch "{sentinel}"\n', encoding="utf-8")
    fake_browser.chmod(0o755)

    environment = dict(os.environ)
    environment.update(
        {
            "BROWSER": str(fake_browser),
            "MUSIC_DECK_STATE_DIR": str(tmp_path / "state"),
            "MUSIC_DECK_CONFIG_DIR": str(tmp_path / "config"),
        }
    )
    environment.pop("MUSIC_DECK_CLIENT_ID", None)
    environment.pop("SPOTIFY_CLIENT_ID", None)

    started = time.monotonic()
    result = subprocess.run(
        _argv() + [verb],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        env=environment,
        timeout=20,
    )
    elapsed = time.monotonic() - started

    assert elapsed < 5.0, f"{verb} took {elapsed:.1f}s"
    assert not sentinel.exists(), "a non-login verb opened a browser"
    document = json.loads(result.stdout)

    if verb == "whoami":
        assert result.returncode == EXIT_REFUSAL
        assert document["error"]["code"] == ErrorCode.NOT_AUTHENTICATED
        assert "music-deck login" in document["error"]["remedy"]
    else:
        # boundary.v1 Core 6: `disconnect` with nothing stored is a truthful
        # report of an empty deletion, not a refusal.
        assert result.returncode == EXIT_SUCCESS
        assert document["deleted"] == []
