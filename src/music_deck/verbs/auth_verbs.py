"""`login`, `disconnect`, `whoami` -- the three verbs that own the account.

``boundary.v1`` Core 5: "``login`` is the only interactive verb. Every other verb
fails ``not_authenticated``, naming ``music-deck login`` as the remedy."
``boundary.v1`` Core 6: "``disconnect`` deletes the token and every locally
cached byte of Spotify content, and reports what it deleted."

What "interactive" means here, exactly
--------------------------------------
``login`` opens a browser and waits a **bounded** time for Spotify to redirect
back to a loopback port it bound itself. It never reads stdin -- nothing in
music-deck ever does -- so ``cli.v1`` Core 1's "a run with stdin closed never
hangs" survives even for this verb. The one case that cannot be served is *no
browser opened and no terminal to paste a URL into*: that fails loud and
immediately rather than waiting out the clock on an interaction that can never
arrive.

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
from music_deck.check import state_dir, token_path
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
    """No browser opened and no terminal to hand the URL to.

    Deliberately not one of ``cli.v1`` Core 6's frozen codes: it describes the
    machine music-deck is running on, not the state of the Spotify account, and
    inventing a frozen-looking name would fork a vocabulary this lane does not
    own. It exits ``1`` and says exactly what to do instead.
    """

    def __init__(self, url: str) -> None:
        super().__init__(
            "no_browser",
            "music-deck could not open a browser, and stdin is closed, so the "
            "authorisation URL cannot be handed to you either. Authorising needs "
            "one or the other.",
            "Run `music-deck login` from an interactive terminal, or set BROWSER "
            "to a command that opens a browser, then run it again.",
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


def login(
    *,
    timeout_s: float = DEFAULT_LOGIN_TIMEOUT_S,
    transport: Transport | None = None,
    open_browser: Callable[[str], bool] = _open_browser,
    stdin_isatty: Callable[[], bool] = _stdin_is_a_terminal,
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

    owned = receiver is None
    listener = receiver or LoopbackReceiver()
    try:
        redirect_uri = listener.redirect_uri  # http://127.0.0.1:<ephemeral port>
        url = authorize_url(resolved_id, redirect_uri, pkce.challenge, state, scopes)

        opened = open_browser(url)
        if not opened:
            if not stdin_isatty():
                raise NoBrowserError(url)
            print(
                "music-deck could not open a browser. Open this URL to authorise:\n"
                f"{url}",
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
