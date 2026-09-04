"""The one HTTP client music-deck uses to talk to Spotify.

Every Spotify request in this tool goes through :class:`SpotifyClient`. That is
the point: the refusal vocabulary of ``cli.v1`` Core 6 is only frozen if there
is exactly one place that decides what a Spotify failure is *called*, and the
removed-endpoint guard of ``boundary.v1`` Core 7 is only a guarantee if there is
exactly one place a request can be built.

Contracts served
----------------
* ``cli.v1`` Core 4 -- every failure is the one envelope; every emitted Spotify
  item carries its own ``external_urls.spotify`` link (see :func:`surface_links`).
* ``cli.v1`` Core 5 -- refusals exit 2, through ``errors.exit_code_for``.
* ``cli.v1`` Core 6 -- the frozen vocabulary. This module is where a status code
  becomes one of those words:

  =============================== ==================================
  What Spotify returned           What music-deck calls it
  =============================== ==================================
  401, no refresh token           ``not_authenticated``
  401, refresh rejected           ``reauthorization_required``
  401 again after a good refresh  ``not_authenticated``
  403 on ``/playlists/*/items``   ``playlist_items_unavailable``
  403, reason ``PREMIUM_REQUIRED``  ``premium_required``
  403 on a player write           ``premium_required``
  403, anything else              ``not_allowlisted``
  204 on a player *read*          ``no_active_device``
  429, reason ``QUOTA_EXCEEDED``  ``quota_exceeded`` (never retried)
  429, otherwise                  ``rate_limited`` (one bounded retry)
  =============================== ==================================

* ``boundary.v1`` Core 7 -- :data:`REMOVED_ENDPOINTS` and :func:`check_removed`.
  The guard runs *before* the request is built, so a removed path can never
  reach the network even once.
* ``boundary.v1`` Core 8 -- nothing here caches a Spotify response to disk. The
  single file this module may write is ``last-403.json``, which records only a
  timestamp, an endpoint *template* with every id redacted, and Spotify's own
  reason string -- no Spotify content. ``check`` reads it to answer "is this
  account allowlisted?", which Spotify offers no endpoint for.

Codes outside the frozen vocabulary
-----------------------------------
``cli.v1`` Core 6 freezes the ten codes a *caller* can provoke. Two failures
here are music-deck's own fault or the network's, not the caller's, and they are
deliberately **not** given frozen names (which would fork a vocabulary this lane
does not own -- ``errors.py`` is MD-1's file):

* ``removed_endpoint`` -- the guard caught music-deck about to construct a path
  Spotify has withdrawn. This is a defect in music-deck, reported loudly.
* ``spotify_error`` / ``network_unreachable`` -- an upstream fault with no
  frozen name.

All three fall through ``errors.exit_code_for`` to exit ``1`` ("failure"), which
is exactly what ``cli.v1`` Core 5 leaves that code for.

Why the standard library
------------------------
``urllib.request`` and nothing else. ``pyproject.toml``'s base dependencies
carry no HTTP client and this module adds none, so the deterministic verbs of
``cli.v1`` Core 2 keep running in an environment with nothing installed. The
:class:`Transport` seam is what tests substitute, so the suite never reaches
``api.spotify.com`` -- not "does not by convention", but *cannot*: no test
constructs a :class:`UrllibTransport`.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Final, Mapping, Protocol

from music_deck.check import LAST_403_FILENAME, state_dir
from music_deck.errors import ErrorCode, MusicDeckError

API_BASE: Final = "https://api.spotify.com/v1"
"""Every path in this module is relative to this."""

OPEN_SPOTIFY: Final = "https://open.spotify.com"
"""Where a ``spotify:track:...`` URI points for a human -- ``cli.v1`` Core 4."""

SEARCH_PAGE_CAP: Final = 10
"""February 2026: search ``limit`` max is 10, default 5 (was 50/20)."""

DEFAULT_PAGE_CAP: Final = 50
"""Everything else that pages -- playlists, library, top items -- caps at 50."""

DEFAULT_TIMEOUT_S: Final = 30.0
DEFAULT_MAX_RETRY_WAIT_S: Final = 10.0
"""The longest ``Retry-After`` music-deck will actually wait out.

``cli.v1`` Core 6: "at most one bounded retry, then refuses ... never an
unbounded wait". A ``Retry-After`` larger than this is not slept on at all; the
tool refuses immediately and hands the caller ``retry_after_s``.
"""

_PLAYER_READ_PATHS: Final = frozenset(
    {"/me/player", "/me/player/currently-playing", "/me/player/queue"}
)
"""``GET /me/player`` answers 200 *or* 204; 204 means nothing is playing."""

_SPOTIFY_ID = re.compile(r"[0-9A-Za-z]{22}")


def _default_sleep(seconds: float) -> None:
    """The one place a bounded retry actually blocks.

    A module-level function rather than a default argument bound at import time,
    so a test can replace it and prove the wait happened without paying for it.
    """
    time.sleep(seconds)


# --------------------------------------------------------------------------- #
# The transport seam
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Request:
    """One HTTP request, fully resolved. Transports do not build URLs."""

    method: str
    url: str
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes | None = None


@dataclass(frozen=True)
class Response:
    """One HTTP response, as bytes. Nothing here interprets the body."""

    status: int
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""

    def header(self, name: str) -> str | None:
        """Case-insensitive header lookup -- HTTP header names are not case-sensitive."""
        wanted = name.lower()
        for key, value in self.headers.items():
            if key.lower() == wanted:
                return value
        return None

    def json(self) -> Any:
        """The body as JSON, or ``None`` when there is no body / it is not JSON."""
        if not self.body:
            return None
        try:
            return json.loads(self.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None


class Transport(Protocol):
    """Anything that can turn a :class:`Request` into a :class:`Response`."""

    def send(self, request: Request, timeout_s: float) -> Response: ...


class UrllibTransport:
    """The real one. The only class in music-deck that touches a socket."""

    def send(self, request: Request, timeout_s: float = DEFAULT_TIMEOUT_S) -> Response:
        native = urllib.request.Request(
            request.url,
            data=request.body,
            headers=dict(request.headers),
            method=request.method.upper(),
        )
        try:
            with urllib.request.urlopen(native, timeout=timeout_s) as reply:
                return Response(
                    status=reply.status,
                    headers=dict(reply.headers.items()),
                    body=reply.read(),
                )
        except urllib.error.HTTPError as exc:
            # A 4xx/5xx is a response, not an exception -- the client maps it.
            return Response(
                status=exc.code,
                headers=dict(exc.headers.items()) if exc.headers else {},
                body=exc.read(),
            )
        except urllib.error.URLError as exc:
            raise MusicDeckError(
                "network_unreachable",
                f"Could not reach {urllib.parse.urlsplit(request.url).netloc}: "
                f"{exc.reason}",
                "Check the network connection and try again.",
            ) from exc
        except TimeoutError as exc:
            raise MusicDeckError(
                "network_unreachable",
                f"Timed out after {timeout_s:g}s waiting for "
                f"{urllib.parse.urlsplit(request.url).netloc}.",
                "Check the network connection and try again.",
            ) from exc


class TokenSource(Protocol):
    """Where :class:`SpotifyClient` gets a bearer token, and how it renews one.

    ``auth.FileTokenSource`` is the implementation; the protocol exists so this
    module never imports ``auth`` (which imports this one).
    """

    def bearer(self) -> str:
        """The current access token. Raises ``not_authenticated`` if there is none."""

    def can_refresh(self) -> bool:
        """Whether a refresh is even possible (a refresh token is on hand)."""

    def refresh(self) -> str:
        """Renew and return a fresh access token, or raise the matching refusal."""


# --------------------------------------------------------------------------- #
# boundary.v1 Core 7 -- the removed-endpoint guard
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class RemovedEndpoint:
    """One withdrawn family: how to spot it, when it went, and what replaced it."""

    pattern: re.Pattern[str]
    methods: frozenset[str] | None  # None = every method
    name: str
    withdrawn: str
    replacement: str

    def matches(self, method: str, path: str) -> bool:
        if self.methods is not None and method.upper() not in self.methods:
            return False
        return bool(self.pattern.match(path))


_ID = r"[^/]+"

# --- BEGIN REMOVED ENDPOINT TABLE ------------------------------------------- #
# The one place in src/ where a withdrawn path may appear as a literal. These
# strings exist to be REFUSED, never to be requested: `check_removed` runs
# before any URL is built. `tests/test_removed_endpoints.py` excises exactly the
# region between these two markers and then asserts no withdrawn path literal
# survives anywhere else in src/ -- which is what makes the static half of
# boundary.v1's conformance assert meaningful rather than self-satisfied.
#
# Evidence: investigation/B-spotify-api-reality.md section 3.1 (the November 27,
# 2024 list) and section 3.2 (the February 2026 changelog), re-confirmed
# independently in that brief's Appendix C.
REMOVED_ENDPOINTS: Final[tuple[RemovedEndpoint, ...]] = (
    # -- February 2026: batch fetch, all of it ------------------------------- #
    *(
        RemovedEndpoint(
            re.compile(rf"^/{kind}/?$"),
            frozenset({"GET"}),
            f"batch GET /{kind}",
            "February 2026",
            f"/{kind}/{{id}}, one request per item",
        )
        for kind in (
            "tracks",
            "albums",
            "artists",
            "episodes",
            "shows",
            "audiobooks",
            "chapters",
        )
    ),
    # -- February 2026: other users ------------------------------------------ #
    RemovedEndpoint(
        re.compile(r"^/users(/|$)"),
        None,
        "/users/{id} and everything under it",
        "February 2026",
        "/me for the current user; POST /me/playlists to create",
    ),
    # -- February 2026: browse ----------------------------------------------- #
    RemovedEndpoint(
        re.compile(r"^/browse(/|$)"),
        None,
        "/browse/*",
        "February 2026",
        "none -- new releases, categories and featured playlists are gone",
    ),
    RemovedEndpoint(
        re.compile(r"^/markets/?$"),
        None,
        "/markets",
        "February 2026",
        "none -- market enumeration is no longer possible",
    ),
    # -- November 2024: the personalisation family --------------------------- #
    RemovedEndpoint(
        re.compile(r"^/recommendations(/|$)"),
        None,
        "/recommendations",
        "November 2024",
        "none -- music-deck plans with a model instead, from the caller's words",
    ),
    RemovedEndpoint(
        re.compile(r"^/audio-features(/|$)"),
        None,
        "/audio-features",
        "November 2024",
        "none",
    ),
    RemovedEndpoint(
        re.compile(r"^/audio-analysis(/|$)"),
        None,
        "/audio-analysis",
        "November 2024",
        "none",
    ),
    RemovedEndpoint(
        re.compile(rf"^/artists/{_ID}/related-artists/?$"),
        None,
        "/artists/{id}/related-artists",
        "November 2024",
        "none",
    ),
    RemovedEndpoint(
        re.compile(rf"^/artists/{_ID}/top-tracks/?$"),
        None,
        "/artists/{id}/top-tracks",
        "February 2026",
        "none",
    ),
    # -- February 2026: playlist /tracks became /items ------------------------ #
    RemovedEndpoint(
        re.compile(rf"^/playlists/{_ID}/tracks/?$"),
        None,
        "/playlists/{id}/tracks",
        "February 2026",
        "/playlists/{id}/items",
    ),
    RemovedEndpoint(
        re.compile(rf"^/playlists/{_ID}/followers(/|$)"),
        None,
        "/playlists/{id}/followers",
        "February 2026",
        "PUT|DELETE /me/library with the playlist URI",
    ),
    # -- February 2026: type-specific library writes and contains ------------- #
    RemovedEndpoint(
        re.compile(r"^/me/(tracks|albums|episodes|shows|audiobooks|following)/?$"),
        frozenset({"PUT", "DELETE"}),
        "type-specific /me/<type> library writes",
        "February 2026",
        "PUT|DELETE /me/library, which takes Spotify URIs and any content type",
    ),
    RemovedEndpoint(
        re.compile(
            r"^/me/(tracks|albums|episodes|shows|audiobooks|following)/contains/?$"
        ),
        None,
        "type-specific /me/<type>/contains",
        "February 2026",
        "GET /me/library/contains, which takes Spotify URIs",
    ),
)
# --- END REMOVED ENDPOINT TABLE --------------------------------------------- #


class RemovedEndpointError(MusicDeckError):
    """music-deck was about to construct a path Spotify has withdrawn.

    Not a frozen refusal code: no caller can provoke this by asking for
    something reasonable, so it is a defect in music-deck rather than a
    conversation with the user. It exits ``1`` and names the replacement.
    """

    def __init__(self, method: str, path: str, removed: RemovedEndpoint) -> None:
        super().__init__(
            "removed_endpoint",
            f"{method.upper()} {path} is in the {removed.name} family, which "
            f"Spotify withdrew in {removed.withdrawn}. music-deck refused to send "
            f"it. Replacement: {removed.replacement}.",
            (
                "This is a defect in music-deck, not something you did. "
                "boundary.v1 Core 7 forbids constructing a withdrawn endpoint; "
                "report it."
            ),
            method=method.upper(),
            path=path,
            withdrawn=removed.withdrawn,
            replacement=removed.replacement,
        )


def check_removed(method: str, path: str) -> None:
    """Raise :class:`RemovedEndpointError` if ``path`` is a withdrawn endpoint.

    Called before a URL is built, so a refused path never reaches a socket --
    which is the difference between "we do not call it" and "we cannot call it".
    """
    normalised = path if path.startswith("/") else f"/{path}"
    normalised = normalised.split("?", 1)[0]
    for removed in REMOVED_ENDPOINTS:
        if removed.matches(method, normalised):
            raise RemovedEndpointError(method, normalised, removed)


# --------------------------------------------------------------------------- #
# cli.v1 Core 4 -- every item carries its own open.spotify.com link
# --------------------------------------------------------------------------- #
_URI_KINDS: Final = frozenset(
    {
        "track",
        "album",
        "artist",
        "playlist",
        "show",
        "episode",
        "audiobook",
        "chapter",
        "user",
    }
)


def link_for_uri(uri: str) -> str | None:
    """``spotify:track:ID`` -> ``https://open.spotify.com/track/ID``, or None."""
    parts = uri.split(":") if isinstance(uri, str) else []
    if len(parts) != 3 or parts[0] != "spotify" or parts[1] not in _URI_KINDS:
        return None
    return f"{OPEN_SPOTIFY}/{parts[1]}/{parts[2]}"


def surface_links(payload: Any) -> Any:
    """Give every object carrying a Spotify URI its ``external_urls.spotify``.

    ``cli.v1`` Core 4: "Every Spotify item the tool emits carries its own
    ``external_urls.spotify`` link." Spotify usually supplies one; where it does
    not, the link is derived from the item's own URI rather than left absent, so
    a caller never has to know which endpoints happen to include it.
    """
    if isinstance(payload, list):
        return [surface_links(item) for item in payload]
    if not isinstance(payload, dict):
        return payload

    result = {key: surface_links(value) for key, value in payload.items()}
    uri = payload.get("uri")
    link = link_for_uri(uri) if isinstance(uri, str) else None
    if link is None:
        return result
    external = result.get("external_urls")
    if not isinstance(external, dict):
        external = {}
    if not external.get("spotify"):
        external["spotify"] = link
    result["external_urls"] = external
    return result


# --------------------------------------------------------------------------- #
# The allowlist signal -- a 403 is the only one Spotify gives
# --------------------------------------------------------------------------- #
def redact_path(path: str) -> str:
    """Replace Spotify ids with ``{id}``.

    ``boundary.v1`` Core 8 permits no persistent store of Spotify content. The
    403 record exists so ``check`` can report "an account may not be
    allowlisted"; the *shape* of the endpoint is all that needs to survive, so
    every id is redacted before anything is written.
    """
    return _SPOTIFY_ID.sub("{id}", path)


def record_403(path: str, reason: str | None) -> None:
    """Note that a 403 happened, for ``check`` to report. Never raises."""
    try:
        directory = state_dir()
        directory.mkdir(parents=True, exist_ok=True)
        (directory / LAST_403_FILENAME).write_text(
            json.dumps(
                {
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                    "endpoint": redact_path(path),
                    "reason": reason or "no reason given by Spotify",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001 - recording evidence must never break a run
        return


# --------------------------------------------------------------------------- #
# The client
# --------------------------------------------------------------------------- #
def _reason_of(payload: Any) -> str | None:
    """Spotify's ``error.reason``, when the body carries one."""
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            reason = error.get("reason")
            if isinstance(reason, str) and reason.strip():
                return reason.strip()
    return None


def _message_of(payload: Any, fallback: str) -> str:
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        message = payload.get("error_description")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return fallback


def _retry_after_of(response: Response) -> float | None:
    raw = response.header("Retry-After")
    if raw is None:
        return None
    try:
        return max(0.0, float(str(raw).strip()))
    except (TypeError, ValueError):
        return None


class SpotifyClient:
    """One authenticated conversation with the Spotify Web API.

    Every argument with a default is a seam a test replaces: ``transport`` so
    the suite never opens a socket, ``sleep`` so a bounded retry costs no real
    seconds, ``now`` so expiry is decidable.
    """

    def __init__(
        self,
        token_source: TokenSource,
        transport: Transport | None = None,
        *,
        sleep: Callable[[float], None] | None = None,
        base: str = API_BASE,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        max_retry_wait_s: float = DEFAULT_MAX_RETRY_WAIT_S,
    ) -> None:
        self._tokens = token_source
        self._transport = transport if transport is not None else UrllibTransport()
        self._sleep = sleep
        self._base = base.rstrip("/")
        self._timeout_s = timeout_s
        self._max_retry_wait_s = max_retry_wait_s

    # -- the one request path ------------------------------------------------ #
    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        body: Any = None,
    ) -> Any:
        """Send one request and return its payload, or raise the matching refusal.

        Returns ``{}`` for a successful empty body (a player write answers 204),
        and the JSON payload with links surfaced otherwise.

        Two things can happen between the first send and the answer, each at most
        once: a 401 renews the access token and repeats the request, and a 429
        carrying a short ``Retry-After`` is waited out and repeated. A second 429
        is refused, carrying ``retry_after_s`` -- ``cli.v1`` Core 6's "at most one
        bounded retry, then refuses".
        """
        check_removed(method, path)  # boundary.v1 Core 7 -- before anything else
        response = self._send(method, path, params, body, bearer=self._tokens.bearer())

        if response.status == 401:
            response = self._after_401(response, method, path, params, body)

        if response.status == 429:
            wait_s = self._bounded_retry(response)
            if wait_s is not None:
                (self._sleep or _default_sleep)(wait_s)
                response = self._send(
                    method, path, params, body, bearer=self._tokens.bearer()
                )

        return self._interpret(response, method, path)

    def get(self, path: str, **params: Any) -> Any:
        return self.request("GET", path, params=params or None)

    def post(self, path: str, body: Any = None, **params: Any) -> Any:
        return self.request("POST", path, params=params or None, body=body)

    def put(self, path: str, body: Any = None, **params: Any) -> Any:
        return self.request("PUT", path, params=params or None, body=body)

    def delete(self, path: str, body: Any = None, **params: Any) -> Any:
        return self.request("DELETE", path, params=params or None, body=body)

    # -- paging -------------------------------------------------------------- #
    def paginate(
        self,
        path: str,
        *,
        limit: int = 20,
        params: Mapping[str, Any] | None = None,
        items_key: str = "items",
    ) -> list[Any]:
        """Collect up to ``limit`` items, page by page, respecting Spotify's caps.

        Search caps a page at 10 items since February 2026 (it was 50); every
        other paged endpoint caps at 50. Asking for more than a page holds is
        therefore not an error -- it is more requests, which this walks for you
        and stops at ``limit`` exactly.
        """
        is_search = path.rstrip("/").endswith("/search")
        page_cap = SEARCH_PAGE_CAP if is_search else DEFAULT_PAGE_CAP
        collected: list[Any] = []
        offset = int((params or {}).get("offset", 0) or 0)
        while len(collected) < limit:
            want = min(page_cap, limit - len(collected))
            query = dict(params or {})
            query.update({"limit": want, "offset": offset})
            payload = self.request("GET", path, params=query)
            page = _page_of(payload, items_key)
            if page is None:
                # Not a paged shape after all -- hand back what the caller got.
                return collected or ([payload] if payload is not None else [])
            collected.extend(page)
            if len(page) < want:
                break
            offset += len(page)
        return collected[:limit]

    # -- internals ----------------------------------------------------------- #
    def _send(
        self,
        method: str,
        path: str,
        params: Mapping[str, Any] | None,
        body: Any,
        *,
        bearer: str,
    ) -> Response:
        url = self._url(path, params)
        headers = {
            "Authorization": f"Bearer {bearer}",
            "Accept": "application/json",
        }
        encoded: bytes | None = None
        if body is not None:
            encoded = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(method.upper(), url, headers, encoded)
        return self._transport.send(request, self._timeout_s)

    def _url(self, path: str, params: Mapping[str, Any] | None) -> str:
        url = f"{self._base}{path if path.startswith('/') else '/' + path}"
        if not params:
            return url
        pairs: list[tuple[str, str]] = []
        for key, value in params.items():
            if value is None:
                continue
            if isinstance(value, (list, tuple)):
                pairs.append((key, ",".join(str(item) for item in value)))
            elif isinstance(value, bool):
                pairs.append((key, "true" if value else "false"))
            else:
                pairs.append((key, str(value)))
        query = urllib.parse.urlencode(pairs)
        return f"{url}?{query}" if query else url

    def _after_401(
        self,
        response: Response,
        method: str,
        path: str,
        params: Mapping[str, Any] | None,
        body: Any,
    ) -> Response:
        """A 401 is either "renew and carry on" or one of two refusals."""
        if not self._tokens.can_refresh():
            raise MusicDeckError(
                ErrorCode.NOT_AUTHENTICATED,
                _message_of(
                    response.json(),
                    "Spotify rejected the access token and there is no refresh "
                    "token to renew it with.",
                ),
            )
        bearer = self._tokens.refresh()  # raises reauthorization_required if rejected
        retried = self._send(method, path, params, body, bearer=bearer)
        if retried.status == 401:
            raise MusicDeckError(
                ErrorCode.NOT_AUTHENTICATED,
                _message_of(
                    retried.json(),
                    "Spotify rejected the access token even after refreshing it.",
                ),
            )
        return retried

    def _interpret(self, response: Response, method: str, path: str) -> Any:
        status = response.status
        payload = response.json()

        if status == 204:
            if method.upper() == "GET" and path.split("?", 1)[0] in _PLAYER_READ_PATHS:
                raise MusicDeckError(
                    ErrorCode.NO_ACTIVE_DEVICE,
                    "Spotify has no active playback session for this account "
                    "(204 No Content).",
                )
            return {}

        if 200 <= status < 300:
            return {} if payload is None else surface_links(payload)

        if status == 401:
            # Only reachable when a retry answered 401 -- a first 401 is handled
            # before this point, by refreshing.
            raise MusicDeckError(
                ErrorCode.NOT_AUTHENTICATED,
                _message_of(payload, "Spotify rejected the access token."),
            )

        if status == 403:
            raise self._forbidden(response, payload, method, path)

        if status == 429:
            raise self._too_many(response, payload)

        raise MusicDeckError(
            "spotify_error",
            f"Spotify answered {status} for {method.upper()} {path}: "
            f"{_message_of(payload, 'no message in the response body')}",
            "Run `music-deck check` to report the tool's state, then try again.",
            status=status,
            endpoint=redact_path(path),
        )

    def _forbidden(
        self, response: Response, payload: Any, method: str, path: str
    ) -> MusicDeckError:
        reason = _reason_of(payload)
        bare = path.split("?", 1)[0]

        if re.match(rf"^/playlists/{_ID}/items/?$", bare) and method.upper() == "GET":
            return MusicDeckError(
                ErrorCode.PLAYLIST_ITEMS_UNAVAILABLE,
                _message_of(
                    payload,
                    "Spotify returns a playlist's items only to an account that "
                    "owns or collaborates on it.",
                ),
            )
        if reason == "PREMIUM_REQUIRED" or self._is_player_write(method, bare):
            return MusicDeckError(
                ErrorCode.PREMIUM_REQUIRED,
                _message_of(
                    payload,
                    "Spotify refused a playback control. Every Player write "
                    "endpoint requires Spotify Premium on the account being "
                    "controlled.",
                ),
            )
        record_403(bare, reason)
        return MusicDeckError(
            ErrorCode.NOT_ALLOWLISTED,
            _message_of(
                payload,
                "Spotify refused the request with 403. On a Development Mode app "
                "that means this account is not on the app's allowlist.",
            ),
        )

    @staticmethod
    def _is_player_write(method: str, path: str) -> bool:
        return method.upper() in {"PUT", "POST"} and path.startswith("/me/player")

    def _too_many(self, response: Response, payload: Any) -> MusicDeckError:
        """429 is two different things wearing one status code."""
        if _reason_of(payload) == "QUOTA_EXCEEDED":
            return MusicDeckError(
                ErrorCode.QUOTA_EXCEEDED,
                _message_of(
                    payload,
                    "Your Spotify developer quota is exhausted. This is a "
                    "different mechanism from rate limiting and waiting will not "
                    "clear it.",
                ),
                reason="QUOTA_EXCEEDED",
            )
        retry_after = _retry_after_of(response)
        return MusicDeckError(
            ErrorCode.RATE_LIMITED,
            _message_of(
                payload,
                "Spotify rate-limited this app (429). music-deck already honoured "
                "`Retry-After` once and will not wait again.",
            ),
            retry_after_s=retry_after,
        )

    def _bounded_retry(self, response: Response) -> float | None:
        """The seconds to sleep before the single permitted retry, or None.

        ``None`` means "do not retry at all": a quota 429 (waiting never clears
        one), a 429 with no ``Retry-After`` to honour, or a ``Retry-After``
        longer than this client is willing to block for. In every one of those
        cases the caller is refused immediately and told how long to wait itself,
        which is what "never an unbounded wait" means in practice.
        """
        if _reason_of(response.json()) == "QUOTA_EXCEEDED":
            return None
        retry_after = _retry_after_of(response)
        if retry_after is None or retry_after > self._max_retry_wait_s:
            return None
        return retry_after


def _page_of(payload: Any, items_key: str) -> list[Any] | None:
    """The list of items in a Spotify paging object, wherever it is nested."""
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return None
    candidate = payload.get(items_key)
    if isinstance(candidate, list):
        return candidate
    # Search nests one paging object per requested type: {"tracks": {"items": []}}.
    for value in payload.values():
        if isinstance(value, dict) and isinstance(value.get(items_key), list):
            return value[items_key]
    return None
