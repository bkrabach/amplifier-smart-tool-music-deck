"""PKCE authorisation, the token cache, and `login` driven end to end.

Contracts served: ``boundary.v1`` Core 4 (PKCE only, the caller's own client ID,
a loopback IP-literal redirect on the fixed registered port, a token file at mode
``0600``, no client secret anywhere) and Core 5 (``login`` is the only
interactive verb; every other verb refuses ``not_authenticated`` and names
``music-deck login``).

`login` is exercised for real: a loopback receiver is bound on the real resolved
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
import signal
import socket
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
from music_deck.errors import (
    EXIT_FAILURE,
    EXIT_REFUSAL,
    EXIT_SUCCESS,
    ErrorCode,
    MusicDeckError,
)
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
def free_port() -> int:
    """A port nothing is listening on right now.

    Used to keep these tests off the registered default (8888), which a real
    install -- or another test run on the same machine -- may legitimately be
    holding. The value is resolved through the same env var a caller would use,
    so what is exercised is the shipping resolver, not a test-only seam.
    """
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_the_redirect_uri_is_a_loopback_ip_literal_on_the_registered_port(monkeypatch):
    """boundary.v1 Core 4: a loopback IP literal on a fixed, registered port.

    "`localhost` is not allowed as redirect URI" -- Spotify, enforced since
    2025-04-09. The port is no longer whatever the kernel handed out: it is the
    one the caller registered, which is why `check` can report it truthfully.
    """
    port = free_port()
    monkeypatch.setenv("MUSIC_DECK_REDIRECT_URI", f"http://127.0.0.1:{port}")

    with auth.LoopbackReceiver() as receiver:
        uri = receiver.redirect_uri
        bound = receiver._server.server_address[1]

    assert uri == f"http://127.0.0.1:{port}"
    assert "localhost" not in uri
    assert receiver.port == port
    assert bound == port, "the socket bound the registered port, not another"


def test_a_second_receiver_on_the_same_port_refuses_loudly_naming_it(monkeypatch):
    """boundary.v1 kit assert: "`login` refuses loudly, naming the port, when
    that port is already in use -- it never silently picks another"."""
    port = free_port()
    monkeypatch.setenv("MUSIC_DECK_REDIRECT_URI", f"http://127.0.0.1:{port}")

    with auth.LoopbackReceiver() as first:
        with pytest.raises(MusicDeckError) as raised:
            auth.LoopbackReceiver()

    assert raised.value.code == "port_unavailable"
    assert raised.value.exit_code == EXIT_REFUSAL
    assert str(port) in raised.value.message
    assert raised.value.extra["port"] == port
    assert "music-deck setup --port" in raised.value.remedy
    assert first.port == port


def test_a_redirect_uri_that_cannot_be_bound_is_refused_before_any_socket(monkeypatch):
    """A portless URI names no port to bind, so the refusal is about the value,
    not about the socket -- and it says what to register instead."""
    monkeypatch.setenv("MUSIC_DECK_REDIRECT_URI", "http://127.0.0.1")

    with pytest.raises(MusicDeckError) as raised:
        auth.LoopbackReceiver()

    assert raised.value.code == ErrorCode.USAGE
    assert "no usable port" in raised.value.message
    assert "http://127.0.0.1:8888" in raised.value.remedy


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
    """State under $XDG_STATE_HOME, the path boundary.v1 Core 4 names.

    The redirect URI is pinned to a free port rather than left on the registered
    default, so a machine legitimately using 8888 does not turn these tests red.
    Pinning it through MUSIC_DECK_REDIRECT_URI exercises the shipping resolver --
    the same one `check` reads -- rather than reaching past it.
    """
    monkeypatch.delenv("MUSIC_DECK_STATE_DIR", raising=False)
    monkeypatch.delenv("MUSIC_DECK_CONFIG_DIR", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setenv("MUSIC_DECK_CLIENT_ID", "client-id-under-test")
    monkeypatch.setenv("MUSIC_DECK_REDIRECT_URI", f"http://127.0.0.1:{free_port()}")
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
    # boundary.v1 Core 4: the redirect URI actually used is the resolved one.
    assert re.fullmatch(r"http://127\.0\.0\.1:\d+", result["redirect_uri"])
    assert result["redirect_uri"] == os.environ["MUSIC_DECK_REDIRECT_URI"]
    assert result["redirect_uri_source"] == "environment MUSIC_DECK_REDIRECT_URI"
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


# --------------------------------------------------------------------------- #
# Headless login -- MD-11
#
# `cli.v1` Core 6's `cancelled`, and the two defects that came with it: a browser
# opened on a display nobody is sitting at, and the authorisation URL withheld in
# exactly that case. Core 4 keeps stdout to one JSON document, so every line of
# guidance below is asserted on **stderr**.
# --------------------------------------------------------------------------- #
def _resolved_port() -> int:
    """The port the shipping resolver returns -- the one `check` reports."""
    return int(urllib.parse.urlsplit(os.environ["MUSIC_DECK_REDIRECT_URI"]).port)


def test_login_shows_the_url_before_any_browser_and_even_when_one_opens(
    monkeypatch, xdg_state, capsys
):
    """The steward's request, verbatim: show the URL, always.

    A browser opening on this machine's display is not evidence the caller can
    see it -- over ssh onto a host with a desktop it is evidence they cannot. So
    the URL goes out first, and goes out anyway.
    """
    use_fake_transport(
        monkeypatch,
        FakeTransport([json_response(200, TOKEN_RESPONSE), json_response(200, ME_RESPONSE)]),
    )
    browser = BrowserStandIn()

    result = login(timeout_s=10, open_browser=browser, stdin_isatty=lambda: False)

    printed = capsys.readouterr()
    assert result["signed_in"] is True
    url = browser.urls[0]
    assert url in printed.err, "the URL was withheld when a browser opened"
    # Before anything else: the URL precedes the line about the browser opening.
    assert printed.err.index(url) < printed.err.index("A browser was opened")
    # And it is on a line of its own, so it can be copied in one go.
    assert f"\n{url}\n" in printed.err
    # cli.v1 Core 4: stdout carries the caller's JSON, never this guidance.
    assert printed.out == ""


def test_login_names_the_ssh_tunnel_on_the_resolved_port(
    monkeypatch, xdg_state, capsys
):
    """boundary.v1 Core 4: the port `check` reports, never a hardcoded 8888."""
    use_fake_transport(monkeypatch, FakeTransport())
    port = _resolved_port()

    with pytest.raises(MusicDeckError):
        login(timeout_s=0.6, open_browser=lambda _url: True, stdin_isatty=lambda: False)

    printed = capsys.readouterr()
    assert f"ssh -L {port}:127.0.0.1:{port} " in printed.err
    if port != 8888:  # the built-in default, which this run is deliberately not on
        assert "ssh -L 8888:127.0.0.1:8888" not in printed.err


def test_login_with_no_browser_never_calls_the_browser_opener(
    monkeypatch, xdg_state, capsys
):
    """`--no-browser` is a promise about what is NOT done, so the opener is a spy.

    With no browser and no terminal this would otherwise be `no_browser`; asked
    for explicitly, an absent browser is the point, not a failure. What is left
    is the ordinary bounded wait.
    """
    use_fake_transport(monkeypatch, FakeTransport())
    calls: list[str] = []

    with pytest.raises(MusicDeckError) as raised:
        login(
            timeout_s=0.6,
            open_browser=lambda url: bool(calls.append(url)) or True,
            stdin_isatty=lambda: False,
            no_browser=True,
        )

    assert calls == [], "--no-browser opened a browser anyway"
    assert raised.value.code == ErrorCode.NOT_AUTHENTICATED  # the wait timed out
    assert raised.value.code != "no_browser"
    printed = capsys.readouterr()
    assert "https://accounts.spotify.com/authorize" in printed.err
    port = _resolved_port()
    assert f"ssh -L {port}:127.0.0.1:{port} " in printed.err
    assert printed.out == ""


def test_login_without_no_browser_still_refuses_when_nothing_can_authorise(
    monkeypatch, xdg_state
):
    """The existing `no_browser` refusal is unchanged by the new flag."""
    use_fake_transport(monkeypatch, FakeTransport())

    with pytest.raises(MusicDeckError) as raised:
        login(timeout_s=120, open_browser=lambda _url: False, stdin_isatty=lambda: False)

    assert raised.value.code == "no_browser"


def _login_env(tmp_path: Path, port: int) -> dict[str, str]:
    environment = dict(os.environ)
    environment.update(
        {
            "MUSIC_DECK_STATE_DIR": str(tmp_path / "state"),
            "MUSIC_DECK_CONFIG_DIR": str(tmp_path / "config"),
            "MUSIC_DECK_CLIENT_ID": "client-id-under-test",
            "MUSIC_DECK_REDIRECT_URI": f"http://127.0.0.1:{port}",
        }
    )
    return environment


def test_a_ctrl_c_while_login_waits_is_a_refusal_not_a_traceback(tmp_path):
    """cli.v1 Core 6 `cancelled`, proved by a real SIGINT to a real process.

    `KeyboardInterrupt` is a `BaseException`, so `except Exception` in `main()`
    could not see it and Python printed a stack trace through `listener.wait()`.
    Core 4 requires the error envelope and a non-zero exit instead -- and Core 6
    now names the code. Both halves are asserted: the envelope on stdout AND a
    stderr with no traceback in it, because an exit code alone would not notice
    the trace.
    """
    port = free_port()
    environment = _login_env(tmp_path, port)
    errors = tmp_path / "login-stderr.txt"

    with errors.open("wb") as sink:
        process = subprocess.Popen(
            _argv() + ["login", "--no-browser", "--timeout", "120"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=sink,
            text=True,
            env=environment,
        )
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if "accounts.spotify.com/authorize" in errors.read_text(
                    encoding="utf-8", errors="replace"
                ):
                    break
                time.sleep(0.1)
            else:  # pragma: no cover - only on a broken build
                process.kill()
                pytest.fail("login never printed the authorisation URL")
            process.send_signal(signal.SIGINT)
            stdout, _ = process.communicate(timeout=30)
        finally:
            if process.poll() is None:  # pragma: no cover - only on a broken build
                process.kill()

    printed_err = errors.read_text(encoding="utf-8", errors="replace")
    assert process.returncode == EXIT_REFUSAL, printed_err
    document = json.loads(stdout)
    assert document["error"]["code"] == ErrorCode.CANCELLED
    assert document["error"]["remedy"].strip()
    assert "Traceback" not in printed_err
    assert "KeyboardInterrupt" not in printed_err
    assert "socketserver" not in printed_err
    # Core 4 again: nothing half-written on the way out.
    assert not (tmp_path / "state" / "token.json").exists()


def test_the_tunnel_line_names_the_port_check_reports(tmp_path):
    """One value, two readers: what `login` prints is what `check` reports."""
    port = free_port()
    environment = _login_env(tmp_path, port)

    checked = subprocess.run(
        _argv() + ["check"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        env=environment,
        timeout=30,
    )
    reported = json.loads(checked.stdout)["redirect_uri"]["port"]

    errors = tmp_path / "login-stderr.txt"
    with errors.open("wb") as sink:
        process = subprocess.Popen(
            _argv() + ["login", "--no-browser", "--timeout", "120"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=sink,
            text=True,
            env=environment,
        )
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if "ssh -L" in errors.read_text(encoding="utf-8", errors="replace"):
                    break
                time.sleep(0.1)
            else:  # pragma: no cover - only on a broken build
                pytest.fail("login never printed the tunnel line")
            process.send_signal(signal.SIGINT)
            process.communicate(timeout=30)
        finally:
            if process.poll() is None:  # pragma: no cover - only on a broken build
                process.kill()

    printed_err = errors.read_text(encoding="utf-8", errors="replace")
    assert reported == port
    assert f"ssh -L {reported}:127.0.0.1:{reported} " in printed_err


def test_main_turns_a_keyboard_interrupt_into_the_cancelled_envelope(
    monkeypatch, capsys
):
    """The unit-level twin of the SIGINT test: `main()` itself, no signals.

    `issubclass(KeyboardInterrupt, Exception)` is False, so `main()`'s catch-all
    never saw a Ctrl-C. This drives the separate clause that does, and checks
    both halves of the promise -- the envelope on stdout, and a stderr with no
    traceback in it.
    """
    import dataclasses

    from music_deck import cli

    def interrupted(_args):
        raise KeyboardInterrupt

    probe = dataclasses.replace(cli.VERBS_BY_NAME["login"], handler=interrupted)
    monkeypatch.setattr(
        cli, "VERBS", tuple(probe if verb.name == "login" else verb for verb in cli.VERBS)
    )

    code = cli.main(["login"])

    printed = capsys.readouterr()
    assert code == EXIT_REFUSAL
    document = json.loads(printed.out)
    assert document["error"]["code"] == ErrorCode.CANCELLED
    assert "music-deck login" in document["error"]["message"]
    assert document["error"]["remedy"].strip()
    assert "Traceback" not in printed.err
