"""`login`, `disconnect`, `whoami` -- the three verbs that own the account.

``boundary.v1`` Core 5: "``login`` is the only interactive verb. Every other verb
fails ``not_authenticated``, naming ``music-deck login`` as the remedy."
``boundary.v1`` Core 6: "``disconnect`` deletes the token and every locally
cached byte of Spotify content, and reports what it deleted."

What "interactive" means here, exactly
--------------------------------------
``login`` shows the authorisation URL, optionally opens a browser, and waits a
**bounded** time for Spotify to redirect back to the loopback port the caller
registered -- the one ``music_deck.check.resolve_redirect_uri`` returns and
``check`` reports, never one chosen at runtime (``boundary.v1`` Core 4). It never
reads stdin -- nothing in music-deck ever does -- so ``cli.v1`` Core 1's "a run
with stdin closed never hangs" survives even for this verb. The one case that
cannot be served is *no browser opened, no terminal to paste a URL into, and
``--no-browser`` not asked for*: that fails loud and immediately rather than
waiting out the clock on an interaction that can never arrive.

The URL is printed **before** any browser is attempted, and printed even when one
opens. The caller may be at a different machine than the display -- an ssh
session onto a host that has a desktop opens a browser nobody is sitting in front
of -- and that is precisely the case where the URL is needed, so withholding it
there was the defect this shape fixes. ``--no-browser`` (``no_browser=True``)
skips the opener entirely: on a headless host an absent browser is the point, not
an error.

Every other verb in music-deck reaches Spotify through :func:`spotify_client`,
which refuses ``not_authenticated`` before a single request when there is no
token -- so "runs unauthenticated" costs no network round trip and no browser.
"""

from __future__ import annotations

import secrets
import sys
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from music_deck.auth import (
    DEFAULT_SCOPES,
    FileTokenSource,
    LoopbackReceiver,
    authorize_url,
    exchange_code,
    new_pkce_pair,
    read_token,
    require_client_id,
    token_file_mode,
    write_token,
)
from music_deck.check import (
    redirect_uri_parts,
    resolve_redirect_uri,
    state_dir,
    token_path,
)
from music_deck.errors import ErrorCode, MusicDeckError
from music_deck.http import SpotifyClient, Transport

DEFAULT_LOGIN_TIMEOUT_S: float = 180.0
"""How long `login` waits for the browser round trip before refusing."""


# --------------------------------------------------------------------------- #
# The shared client every other verb will use
# --------------------------------------------------------------------------- #
def spotify_client(
    transport: Transport | None = None,
    *,
    token_file: Path | None = None,
    now: Callable[[], datetime] | None = None,
    **client_options: Any,
) -> SpotifyClient:
    """A client bound to the stored token.

    Building one is free and touches nothing; the refusal for a missing token
    happens on the first request, through ``FileTokenSource.bearer()``.
    """
    source = FileTokenSource(
        transport=transport,
        path=token_file,
        **({"now": now} if now is not None else {}),
    )
    return SpotifyClient(source, transport, **client_options)


# --------------------------------------------------------------------------- #
# login
# --------------------------------------------------------------------------- #
class NoBrowserError(MusicDeckError):
    """No browser opened, no terminal to hand the URL to, and ``--no-browser``
    was not asked for.

    Deliberately not one of ``cli.v1`` Core 6's frozen codes: it describes the
    machine music-deck is running on, not the state of the Spotify account, and
    inventing a frozen-looking name would fork a vocabulary this lane does not
    own. It exits ``1`` and says exactly what to do instead.
    """

    def __init__(self, url: str) -> None:
        super().__init__(
            "no_browser",
            "music-deck could not open a browser here, and stdin is closed, so "
            "there is nobody to hand the authorisation URL to either. Authorising "
            "needs one or the other.",
            "Run `music-deck login --no-browser` and open the URL it prints on "
            "whatever machine your browser is on (it also prints the `ssh -L` "
            "line if you need to forward the port), or run `music-deck login` "
            "from an interactive terminal, or set BROWSER to a command that opens "
            "a browser.",
            authorize_url=url,
        )


def _open_browser(url: str) -> bool:
    try:
        return bool(webbrowser.open(url, new=1, autoraise=True))
    except Exception:  # noqa: BLE001 - a browser that errors is a browser that did not open
        return False


def _stdin_is_a_terminal() -> bool:
    try:
        return bool(sys.stdin) and sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def _tunnel_command(port: int | None) -> str:
    """The `ssh -L` line that makes `login` work from another machine's browser.

    The port is the **resolved** one -- what ``resolve_redirect_uri`` returned and
    ``check`` reports (``boundary.v1`` Core 4), never a hardcoded default. The
    user and host are this machine's own, so the line can be copied in one go;
    each falls back to a placeholder rather than guessing when it cannot be read.
    """
    import getpass
    import socket

    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001 - a nameless account is a placeholder, not a crash
        user = "<user>"
    try:
        host = socket.gethostname() or "<host>"
    except Exception:  # noqa: BLE001 - same
        host = "<host>"
    shown = port if port is not None else "<port>"
    return f"ssh -L {shown}:127.0.0.1:{shown} {user}@{host}"


def _announce(url: str, redirect_uri: str, timeout_s: float) -> None:
    """Show the authorisation URL -- always, before any browser is attempted.

    ``cli.v1`` Core 4: stdout carries the one JSON document a caller parses, so
    this is stderr, and it is "written for its reader". The URL is on a line of
    its own, unwrapped, so it can be copied in one go.

    Always, because the caller may not be sitting at this machine's display. A
    browser that opens on a server nobody is watching is exactly the case where
    the URL was previously withheld -- the one case where it is needed most.
    """
    _host, port = redirect_uri_parts(redirect_uri)
    print(
        "\nmusic-deck login -- open this URL in a browser to authorise:\n"
        f"\n{url}\n"
        f"\nSpotify will then redirect to {redirect_uri}, which has to be "
        "reachable\nfrom whichever machine that browser is on. If that is not "
        "this machine,\nforward the port from there first:\n"
        f"\n  {_tunnel_command(port)}\n"
        f"\nWaiting up to {timeout_s:g}s for the redirect.\n",
        file=sys.stderr,
    )


def login(
    *,
    timeout_s: float = DEFAULT_LOGIN_TIMEOUT_S,
    transport: Transport | None = None,
    open_browser: Callable[[str], bool] = _open_browser,
    stdin_isatty: Callable[[], bool] = _stdin_is_a_terminal,
    no_browser: bool = False,
    scopes: tuple[str, ...] = DEFAULT_SCOPES,
    client_id: str | None = None,
    token_file: Path | None = None,
    receiver: LoopbackReceiver | None = None,
    now: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Authorise against the caller's own Spotify app, once, via PKCE.

    Returns the account, the granted scopes, and where the token was written.
    Every keyword with a default is a seam a test replaces -- the browser, the
    clock, the transport -- so this verb is exercised end to end without a
    network, a browser, or a Spotify account.
    """
    resolved_id, id_source = (
        (client_id, "supplied by the caller") if client_id else require_client_id()
    )
    pkce = new_pkce_pair()
    state = secrets.token_urlsafe(16)

    resolved_uri, uri_source = resolve_redirect_uri()

    owned = receiver is None
    listener = receiver or LoopbackReceiver(resolved_uri)
    try:
        # `boundary.v1` Core 4: one value, two readers. The receiver was built
        # from what `resolve_redirect_uri` returned -- the same call `check`
        # makes -- and bound that exact port or refused naming it, so this is
        # the value `check` reports, not a port the kernel happened to hand out.
        redirect_uri = listener.redirect_uri
        url = authorize_url(resolved_id, redirect_uri, pkce.challenge, state, scopes)

        # The URL first, always -- before any browser is attempted. A browser
        # that opens on a display nobody is watching is the case where the URL
        # matters most, and it used to be the one case that withheld it.
        _announce(url, redirect_uri, timeout_s)

        if no_browser:
            # An absent browser is not a failure here; it is what was asked for.
            print(
                "--no-browser: music-deck did not try to open one. Paste the URL "
                "above\ninto the browser you are actually sitting at.",
                file=sys.stderr,
            )
        else:
            opened = open_browser(url)
            if opened:
                print(
                    "A browser was opened on THIS machine's display. If that is "
                    "not where\nyou are, ignore it and use the URL above instead.",
                    file=sys.stderr,
                )
            elif not stdin_isatty():
                raise NoBrowserError(url)
            else:
                print(
                    "music-deck could not open a browser here, so use the URL "
                    "above.",
                    file=sys.stderr,
                )

        query = listener.wait(timeout_s)
    finally:
        if owned:
            listener.close()

    if "error" in query:
        raise MusicDeckError(
            ErrorCode.NOT_AUTHENTICATED,
            f"Spotify did not authorise music-deck: {query['error']}.",
            "Run `music-deck login` again and accept the permissions Spotify asks "
            "for.",
        )
    if query.get("state") != state:
        raise MusicDeckError(
            ErrorCode.NOT_AUTHENTICATED,
            "The authorisation response carried the wrong `state` value, so it "
            "did not come from the request music-deck made. Nothing was stored.",
            "Run `music-deck login` again.",
        )

    document = exchange_code(
        client_id=resolved_id,
        code=query.get("code", ""),
        verifier=pkce.verifier,
        redirect_uri=redirect_uri,
        transport=transport,
        **({"now": now} if now is not None else {}),
    )
    written = write_token(document, token_file)

    account: dict[str, Any] | None = None
    findings: list[str] = []
    try:
        account = spotify_client(transport, token_file=token_file, now=now).get("/me")
    except MusicDeckError as exc:
        findings.append(
            f"Signed in, but reading the account profile refused `{exc.code}`: "
            f"{exc.message}"
        )

    return {
        "signed_in": True,
        "account": account,
        "client_id_source": id_source,
        "scopes": list(document.get("scopes") or []),
        "token_path": str(written),
        "token_mode": format(token_file_mode(token_file) or 0, "04o"),
        "redirect_uri": redirect_uri,
        "redirect_uri_source": uri_source,
        "expires_at": document.get("expires_at"),
        "authorized_at": document.get("authorized_at"),
        "refresh_wall_note": (
            "Spotify refresh tokens last six months from this moment, and "
            "refreshing does not extend that. `music-deck check` reports how much "
            "is left."
        ),
        "findings": findings,
    }


# --------------------------------------------------------------------------- #
# disconnect
# --------------------------------------------------------------------------- #
def disconnect(*, token_file: Path | None = None) -> dict[str, Any]:
    """Delete the token and every locally cached byte of Spotify content.

    ``boundary.v1`` Core 6 and Developer Terms section V's disconnect mechanism.
    Everything music-deck writes lives under one state directory, so this empties
    that directory and names each file it removed -- a report a reviewer can
    check, rather than a claim.

    The config file is left alone on purpose: it holds the caller's own client
    ID, which is not Spotify content and not a credential Spotify issued.
    """
    directory = state_dir()
    target = token_file or token_path()

    deleted: list[str] = []
    failed: list[dict[str, str]] = []

    candidates: list[Path] = []
    try:
        candidates = sorted(path for path in directory.rglob("*") if path.is_file())
    except OSError:
        candidates = []
    if target.exists() and target not in candidates:
        candidates.append(target)

    for path in candidates:
        try:
            path.unlink()
            deleted.append(str(path))
        except OSError as exc:
            failed.append({"path": str(path), "error": exc.strerror or str(exc)})

    remaining: list[str] = []
    try:
        remaining = sorted(str(path) for path in directory.rglob("*") if path.is_file())
    except OSError:
        remaining = []

    if failed:
        raise MusicDeckError(
            ErrorCode.PARTIAL_RESULT,
            "Some of music-deck's stored files could not be deleted: "
            + ", ".join(f"{item['path']} ({item['error']})" for item in failed),
            "Delete the listed files by hand, then run `music-deck check` to "
            "confirm nothing remains.",
            completeness={
                "requested": len(candidates),
                "deleted": len(deleted),
                "failed": len(failed),
                "deleted_paths": deleted,
                "failed_paths": failed,
            },
        )

    return {
        "disconnected": True,
        "deleted": deleted,
        "deleted_count": len(deleted),
        "state_dir": str(directory),
        "token_path": str(target),
        "remaining": remaining,
        "summary": (
            f"Deleted {len(deleted)} file(s) from {directory}. "
            "No Spotify content remains on disk."
            if deleted
            else f"Nothing to delete: {directory} held no music-deck files."
        ),
        "note": (
            "The config file was left in place -- it holds your own client ID, "
            "which is not Spotify content. Delete it by hand if you want it gone."
        ),
    }


# --------------------------------------------------------------------------- #
# whoami
# --------------------------------------------------------------------------- #
def whoami(
    transport: Transport | None = None,
    *,
    token_file: Path | None = None,
    now: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Report the signed-in Spotify account -- ``GET /me``.

    The first verb most callers reach for after ``login``, and therefore the one
    that most often has to say ``not_authenticated`` instead. It does so before
    any request, from the absence of a token file.
    """
    payload = spotify_client(transport, token_file=token_file, now=now).get("/me")
    if not isinstance(payload, dict):
        raise MusicDeckError(
            "spotify_error",
            "Spotify's account profile response was not a JSON object.",
            "Run `music-deck check`, then try again.",
        )
    stored = read_token(token_file)
    return {
        "account": payload,
        "scopes": list((stored or {}).get("scopes") or []),
        "token_path": str(token_file or token_path()),
    }
