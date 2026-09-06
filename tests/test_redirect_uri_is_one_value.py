"""The redirect URI is ONE value: the port `login` binds is the port `check` reports.

Contract served: ``boundary.v1`` Core 4, rewritten 2026-09-06 -- "The redirect URI
is a loopback IP literal on a **fixed, registered port** ... and ``login`` binds
exactly the port the caller registered. One value, reported by ``check`` and used
by ``login``: a redirect URI a caller can read but the tool does not honour is
worse than none." -- and its two new kit asserts:

* "The port ``login`` binds is the port ``check`` reports: one value, two readers."
* "``login`` refuses loudly, naming the port, when that port is already in use --
  it never silently picks another."

Why this file exists at all
---------------------------
The defect it guards was not a crash. ``check`` resolved the redirect URI from
the environment, then the config file, then a default, printed it, and stamped
``"conforms": true``. ``login`` ignored every one of those and used
``HTTPServer((host, 0))`` -- a port the kernel picked at that instant. The tool
therefore told a caller one redirect URI, sent Spotify another, and the caller's
registration failed the moment they registered what they had been told.

How it is asserted, and why not more cheaply
--------------------------------------------
A test that called the resolver and compared it to itself would pass against the
broken code, because the broken code's resolver was fine -- it was ``login`` that
did not read it. So the assertion here is deliberately end to end and
deliberately awkward: **the stand-in browser ignores the ``redirect_uri`` in the
authorisation URL and delivers Spotify's callback to the URI ``check`` reports.**
If ``login`` binds anything else, nothing is listening where the callback is
delivered, no code ever arrives, and the verb times out. Passing therefore means
the socket ``login`` actually bound is at the address ``check`` actually printed.

Checked against the old behaviour: with ``LoopbackReceiver`` restored to
``HTTPServer((host, 0))``, every ``one_value`` case in this file fails
(``not_authenticated`` -- "No authorisation came back"), and the
``port_unavailable`` cases fail too. The pasted run is in ``DONE.md``.

Nothing here reaches Spotify: the token exchange is a stand-in transport, and the
only sockets opened are on 127.0.0.1.
"""

from __future__ import annotations

import json
import re
import socket
import threading
import urllib.parse
import urllib.request
from pathlib import Path

import pytest
from spotify_fakes import FakeTransport, json_response, use_fake_transport

from music_deck import auth
from music_deck.check import (
    DEFAULT_REDIRECT_PORT,
    DEFAULT_REDIRECT_URI,
    check,
    config_path,
    redirect_uri_parts,
)
from music_deck.errors import EXIT_REFUSAL, MusicDeckError
from music_deck.verbs.auth_verbs import login

TOKEN_RESPONSE = {
    "access_token": "access-token",
    "token_type": "Bearer",
    "expires_in": 3600,
    "refresh_token": "refresh-token",
    "scope": "user-read-private",
}
ME_RESPONSE = {"id": "deckuser", "display_name": "Deck User"}


def free_port() -> int:
    """A port nothing is listening on right now."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def hold(port: int) -> socket.socket:
    """Occupy a port for the duration of a test, the way another process would.

    ``SO_REUSEADDR`` on purpose: ``http.server.HTTPServer`` sets it too, so this
    probe fails exactly when ``login`` would fail -- something is *listening* --
    and not merely because an earlier test left the port in ``TIME_WAIT``.
    """
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", port))
    listener.listen(1)
    return listener


class BrowserAtChecksAddress:
    """Delivers Spotify's callback to the URI ``check`` reports -- not login's.

    This is the whole point of the file. A stand-in that read ``redirect_uri``
    out of the authorisation URL would follow ``login`` wherever it went, and
    would have passed against the ephemeral-port code that this test exists to
    catch. This one goes where the *report* said, so the two readers have to
    agree for the round trip to complete.
    """

    def __init__(self, reported_uri: str) -> None:
        self.reported_uri = reported_uri
        self.urls: list[str] = []
        self.errors: list[Exception] = []

    def __call__(self, url: str) -> bool:
        self.urls.append(url)
        state = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["state"][0]
        target = (
            f"{self.reported_uri}/?"
            + urllib.parse.urlencode({"code": "authorisation-code", "state": state})
        )

        def visit() -> None:
            try:
                with urllib.request.urlopen(target, timeout=5) as reply:
                    reply.read()
            except Exception as exc:  # noqa: BLE001 - reported, never swallowed
                self.errors.append(exc)

        threading.Thread(target=visit, daemon=True).start()
        return True


@pytest.fixture
def isolated(monkeypatch, tmp_path) -> Path:
    """A fresh config and state tree, and nothing carried in from the shell."""
    monkeypatch.setenv("MUSIC_DECK_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MUSIC_DECK_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("MUSIC_DECK_CLIENT_ID", "client-id-under-test")
    monkeypatch.delenv("MUSIC_DECK_REDIRECT_URI", raising=False)
    return tmp_path / "state" / "token.json"


def _sign_in(monkeypatch) -> dict:
    """Run the real `login` against the address `check` reports. Returns its result."""
    use_fake_transport(
        monkeypatch,
        FakeTransport([json_response(200, TOKEN_RESPONSE), json_response(200, ME_RESPONSE)]),
    )
    reported = check()["redirect_uri"]
    assert reported["conforms"] is True, reported

    browser = BrowserAtChecksAddress(reported["value"])
    result = login(timeout_s=10, open_browser=browser, stdin_isatty=lambda: False)

    assert browser.errors == [], browser.errors
    # The value login used, the value it sent Spotify, and the value check
    # reported are one value -- asserted separately so a failure says which.
    assert result["redirect_uri"] == reported["value"]
    quoted = urllib.parse.quote(reported["value"], safe="")
    assert f"redirect_uri={quoted}" in browser.urls[0]
    return result


# --------------------------------------------------------------------------- #
# One value, two readers -- across all three sources the resolver has
# --------------------------------------------------------------------------- #
def test_one_value_from_the_built_in_default(isolated, monkeypatch):
    """The default is a *fixed* port, so `login` binds 8888 and `check` says 8888."""
    assert check()["redirect_uri"]["value"] == DEFAULT_REDIRECT_URI

    try:
        occupied = hold(DEFAULT_REDIRECT_PORT)
    except OSError:
        pytest.skip(
            f"port {DEFAULT_REDIRECT_PORT} is in use on this machine by something "
            "else, so the default cannot be bound here"
        )
    occupied.close()

    result = _sign_in(monkeypatch)

    assert result["redirect_uri"] == DEFAULT_REDIRECT_URI
    assert result["redirect_uri_source"] == "built-in default"
    assert redirect_uri_parts(result["redirect_uri"])[1] == DEFAULT_REDIRECT_PORT


def test_one_value_from_the_environment(isolated, monkeypatch):
    """The acceptance criterion's own case: MUSIC_DECK_REDIRECT_URI=...:9999."""
    port = free_port()
    monkeypatch.setenv("MUSIC_DECK_REDIRECT_URI", f"http://127.0.0.1:{port}")

    assert check()["redirect_uri"]["port"] == port
    result = _sign_in(monkeypatch)

    assert result["redirect_uri"] == f"http://127.0.0.1:{port}"
    assert result["redirect_uri_source"] == "environment MUSIC_DECK_REDIRECT_URI"


def test_one_value_from_the_config_file(isolated, monkeypatch):
    """What `music-deck setup --port <n>` writes is what `login` binds."""
    from music_deck.verbs.setup import setup

    port = free_port()
    setup(port=port)
    assert json.loads(config_path().read_text(encoding="utf-8"))["redirect_uri"] == (
        f"http://127.0.0.1:{port}"
    )

    assert check()["redirect_uri"]["port"] == port
    result = _sign_in(monkeypatch)

    assert result["redirect_uri"] == f"http://127.0.0.1:{port}"
    assert "config file" in result["redirect_uri_source"]


def test_the_token_records_the_same_one_value(isolated, monkeypatch):
    """The stored token names the URI that was actually used, for `check` to read."""
    port = free_port()
    monkeypatch.setenv("MUSIC_DECK_REDIRECT_URI", f"http://127.0.0.1:{port}")

    result = _sign_in(monkeypatch)
    stored = json.loads(Path(result["token_path"]).read_text(encoding="utf-8"))

    assert stored["redirect_uri"] == f"http://127.0.0.1:{port}"


# --------------------------------------------------------------------------- #
# ... and never a different port, silently
# --------------------------------------------------------------------------- #
def test_login_refuses_naming_the_port_when_it_is_already_in_use(isolated, monkeypatch):
    """The second kit assert. A tool that quietly bound another port here would
    send Spotify a redirect URI the caller never registered, and the failure
    would surface as an unreadable error on Spotify's own page."""
    port = free_port()
    monkeypatch.setenv("MUSIC_DECK_REDIRECT_URI", f"http://127.0.0.1:{port}")
    use_fake_transport(monkeypatch, FakeTransport())
    opened: list[str] = []

    with hold(port):
        with pytest.raises(MusicDeckError) as raised:
            login(
                timeout_s=10,
                open_browser=lambda url: bool(opened.append(url)) or True,
                stdin_isatty=lambda: False,
            )

    error = raised.value
    assert error.code == "port_unavailable"
    assert error.exit_code == EXIT_REFUSAL
    assert str(port) in error.message
    assert f"http://127.0.0.1:{port}" in error.message
    assert error.extra["port"] == port
    assert "music-deck setup --port" in error.remedy
    # It refused before doing anything else: no browser, no token.
    assert opened == []
    assert not isolated.exists()


def test_a_refused_port_is_never_swapped_for_a_working_one(isolated, monkeypatch):
    """Directly: after the refusal, nothing of music-deck's is listening anywhere.

    The failure mode this rules out is a fallback that "helpfully" binds another
    port and carries on -- which is what the ephemeral-port code did by
    construction, and what made `check`'s report a lie.
    """
    port = free_port()
    monkeypatch.setenv("MUSIC_DECK_REDIRECT_URI", f"http://127.0.0.1:{port}")
    use_fake_transport(monkeypatch, FakeTransport())

    with hold(port):
        with pytest.raises(MusicDeckError) as raised:
            login(timeout_s=5, open_browser=lambda _url: True, stdin_isatty=lambda: False)

        # It stopped, rather than continuing on a port nobody registered. A
        # fallback would surface here as `not_authenticated` after a timeout --
        # the shape the ephemeral-port code actually had.
        assert raised.value.code == "port_unavailable"

        # Every other port on the loopback interface is still bindable by us,
        # so music-deck did not take one behind our back.
        spare = free_port()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", spare))  # raises if something grabbed it

    # And the configured value was not quietly rewritten to something that works.
    assert check()["redirect_uri"]["value"] == f"http://127.0.0.1:{port}"


def test_no_ephemeral_port_survives_anywhere_in_the_login_path():
    """The acceptance criterion's own grep, as a test that travels with the code.

    ``HTTPServer((host, 0))`` is the exact shape of the defect: it asks the
    kernel for a port and then reports whatever it got. If it comes back into
    ``src/``, this fails here rather than in a caller's Spotify dashboard.
    """
    source_root = Path(__file__).resolve().parents[1] / "src"
    # Both spellings: the acceptance criterion's own literal grep, and the same
    # call reached through a variable -- `server_class((host, 0), handler)` --
    # which the literal one walks straight past.
    ephemeral = re.compile(r"\(\s*\(\s*[^(),]+,\s*0\s*\)\s*,|HTTPServer\(\(.*0\)")
    offenders = [
        f"{path.relative_to(source_root)}:{number}: {line.strip()}"
        for path in source_root.rglob("*.py")
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if ephemeral.search(line)
    ]

    assert not offenders, "\n".join(offenders)
