"""The player: `now-playing`, `devices`, `queue`, the transport controls,
`top` and `recently-played`.

Contracts served
----------------
* ``cli.v1`` Core 2 -- deterministic; no model anywhere in this file.
* ``cli.v1`` Core 4 -- one JSON document per result. Every Player *write*
  answers ``204 No Content``, so what these verbs return is music-deck's own
  confirmation of what it asked for, with the item it acted on carrying its
  ``external_urls.spotify`` link.
* ``cli.v1`` Core 6 -- ``premium_required`` and ``no_active_device``, both
  decided in ``http.py``: a 403 on a ``/me/player`` write is Premium, a 204 on a
  ``/me/player`` read is "nothing is playing". Neither is caught here.
* ``boundary.v1`` Core 7 -- every path below survived February 2026.

What this verb family cannot do, and says so
--------------------------------------------
The Web API is a **remote control for Spotify Connect**; it renders no audio.
Evidence brief §6: a CLI cannot create a playback device, because the Web
Playback SDK is browser-only and ``GET /me/player/devices`` lists only clients
that are already running and signed in. So ``play`` on a machine with no Spotify
client anywhere refuses ``no_active_device`` and names the remedy -- it does not
"start playing" into silence.

Premium cannot be checked in advance either: February 2026 removed ``product``
from ``GET /me``, so the only way to learn that an account is not Premium is to
be told 403 by a write. That is why ``premium_required`` is a refusal a caller
must expect rather than a precondition music-deck can screen for.
"""

from __future__ import annotations

import ipaddress
from typing import Any, Final

from music_deck.errors import ErrorCode, MusicDeckError
from music_deck.http import DEFAULT_PAGE_CAP, SpotifyClient
from music_deck.verbs.auth_verbs import spotify_client
from music_deck.verbs.catalog import split_reference, to_any_uri, uri_ref

PLAYER: Final = "/me/player"
"""Playback state (GET) and transfer (PUT)."""

DEVICES: Final = f"{PLAYER}/devices"
QUEUE: Final = f"{PLAYER}/queue"
RECENTLY_PLAYED: Final = f"{PLAYER}/recently-played"
PLAY: Final = f"{PLAYER}/play"
PAUSE: Final = f"{PLAYER}/pause"
NEXT: Final = f"{PLAYER}/next"
PREVIOUS: Final = f"{PLAYER}/previous"
SEEK: Final = f"{PLAYER}/seek"
VOLUME: Final = f"{PLAYER}/volume"
SHUFFLE: Final = f"{PLAYER}/shuffle"
REPEAT: Final = f"{PLAYER}/repeat"

TOP_KINDS: Final[tuple[str, ...]] = ("artists", "tracks")
TIME_RANGES: Final[tuple[str, ...]] = ("short_term", "medium_term", "long_term")
REPEAT_STATES: Final[tuple[str, ...]] = ("off", "track", "context")

CONTEXT_KINDS: Final[tuple[str, ...]] = ("album", "artist", "playlist")
"""What Spotify accepts as a playback *context*. A track or an episode is not a
context; it is played as a one-item list of URIs."""

PREMIUM_NOTE: Final = (
    "Spotify requires Premium on the account being controlled for every playback "
    "write, and music-deck produces no audio itself -- it asks a Spotify Connect "
    "device that is already running to do something."
)


def _client(client: SpotifyClient | None) -> SpotifyClient:
    return client if client is not None else spotify_client()


def _usage(message: str, remedy: str) -> MusicDeckError:
    return MusicDeckError(ErrorCode.USAGE, message, remedy)


def _private_ipv4(value: str | None) -> bool:
    try:
        address = ipaddress.ip_address(value or "")
    except ValueError:
        return False
    return isinstance(address, ipaddress.IPv4Address) and any(
        address in network
        for network in (
            ipaddress.ip_network("10.0.0.0/8"),
            ipaddress.ip_network("172.16.0.0/12"),
            ipaddress.ip_network("192.168.0.0/16"),
        )
    )


def _device_params(device: str | None) -> dict[str, Any]:
    """``device_id`` when the caller named one, nothing when they did not.

    Omitting it means "whatever is active", which is what Spotify does with an
    absent ``device_id`` -- and what a caller who did not pass ``--device``
    meant.
    """
    return {"device_id": device} if device else {}


def _acted(action: str, device: str | None, **extra: Any) -> dict[str, Any]:
    """The document a write returns: Spotify answers 204 and nothing else."""
    result: dict[str, Any] = {
        "ok": True,
        "action": action,
        "device": device,
        "note": PREMIUM_NOTE,
    }
    result.update(extra)
    return result


# --------------------------------------------------------------------------- #
# reads
# --------------------------------------------------------------------------- #
def now_playing(*, client: SpotifyClient | None = None) -> Any:
    """What is playing right now -- ``GET /me/player``.

    Spotify answers 200 with the playback state, or **204 when nothing is
    active**. The client turns that 204 into ``no_active_device`` (``cli.v1``
    Core 6), which is a refusal with a remedy rather than an empty success --
    "nothing is playing" and "I could not tell" would otherwise look identical.
    """
    return _client(client).get(PLAYER)


def devices(
    *,
    client: SpotifyClient | None = None,
    local: bool = False,
    discovery_timeout_s: int = 5,
    interface: str | None = None,
    observer: Any | None = None,
) -> dict[str, Any]:
    """Every Spotify Connect device the account can see -- ``GET /me/player/devices``.

    The default list is Spotify's authenticated view of clients already running
    and signed in. With ``local=True``, a separate, read-only Linux local
    observation is appended; it neither changes that list nor enables playback.
    """
    if not isinstance(discovery_timeout_s, int) or isinstance(discovery_timeout_s, bool) or not 1 <= discovery_timeout_s <= 15:
        raise _usage(
            f"--discovery-timeout must be an integer from 1 to 15; got {discovery_timeout_s!r}.",
            "Pass a value from 1 through 15, or leave it at 5.",
        )
    if not local and (interface is not None or discovery_timeout_s != 5):
        raise _usage(
            "Local discovery options need --local.",
            "Pass --local with --discovery-timeout or --interface, or omit those options.",
        )
    if interface is not None:
        if not _private_ipv4(interface):
            raise _usage(
                f"--interface must be a private numeric IPv4 address; got {interface!r}.",
                "Pass an address assigned to an eligible local interface.",
            )

    payload = _client(client).get(DEVICES)
    found = payload.get("devices") if isinstance(payload, dict) else None
    found = found if isinstance(found, list) else []
    result = {
        "devices": found,
        "count": len(found),
        "active": next(
            (item for item in found if isinstance(item, dict) and item.get("is_active")),
            None,
        ),
    }
    if local:
        if observer is None:
            # Deliberately lazy: plain `devices` imports neither zeroconf nor
            # httpx and sends no local-network traffic.
            from music_deck.local_connect import LocalConnectObserver

            observer = LocalConnectObserver()
        result["local"] = observer.observe(
            found, discovery_timeout_s=discovery_timeout_s, interface=interface
        )
    return result


def queue(*, client: SpotifyClient | None = None) -> dict[str, Any]:
    """The playback queue -- ``GET /me/player/queue``."""
    payload = _client(client).get(QUEUE)
    if not isinstance(payload, dict):
        return {"currently_playing": None, "queue": [], "count": 0}
    upcoming = payload.get("queue")
    upcoming = upcoming if isinstance(upcoming, list) else []
    return {
        "currently_playing": payload.get("currently_playing"),
        "queue": upcoming,
        "count": len(upcoming),
    }


def top(
    *,
    kind: str = "tracks",
    time_range: str = "medium_term",
    limit: int = 20,
    client: SpotifyClient | None = None,
) -> dict[str, Any]:
    """The account's own top artists or tracks -- ``GET /me/top/{type}``.

    ``time_range`` is Spotify's, verbatim: ``short_term`` about four weeks,
    ``medium_term`` about six months (the default), ``long_term`` about a year.
    """
    if kind not in TOP_KINDS:
        raise _usage(
            f"--type {kind!r} is not something Spotify keeps a top list of.",
            f"Use one of: {', '.join(TOP_KINDS)}.",
        )
    if time_range not in TIME_RANGES:
        raise _usage(
            f"--time-range {time_range!r} is not one Spotify offers.",
            f"Use one of: {', '.join(TIME_RANGES)}.",
        )
    found = _client(client).paginate(
        f"/me/top/{kind}", limit=limit, params={"time_range": time_range}
    )
    return {
        "type": kind,
        "time_range": time_range,
        "requested": limit,
        "returned": len(found),
        "items": found,
    }


def recently_played(
    *, limit: int = 20, client: SpotifyClient | None = None
) -> dict[str, Any]:
    """Recently played tracks -- ``GET /me/player/recently-played``.

    Cursor-paged, like ``following`` and unlike everything else: each page hands
    back ``cursors.before``, a Unix-millisecond timestamp to walk further back
    from. ``after`` and ``before`` are mutually exclusive, so only ``before`` is
    ever sent. Spotify's own note: this endpoint "currently doesn't support
    podcast episodes".
    """
    api = _client(client)
    collected: list[Any] = []
    before: str | None = None

    while len(collected) < limit:
        want = min(DEFAULT_PAGE_CAP, limit - len(collected))
        params: dict[str, Any] = {"limit": want}
        if before:
            params["before"] = before
        payload = api.get(RECENTLY_PLAYED, **params)

        page = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(page, list) or not page:
            break
        collected.extend(page)

        cursors = payload.get("cursors") if isinstance(payload, dict) else None
        before = cursors.get("before") if isinstance(cursors, dict) else None
        if not before or len(page) < want:
            break

    return {
        "requested": limit,
        "returned": len(collected),
        "items": collected[:limit],
    }


# --------------------------------------------------------------------------- #
# writes -- every one of these needs Premium and an already-running device
# --------------------------------------------------------------------------- #
def play(
    *,
    uri: str | None = None,
    position_ms: int | None = None,
    device: str | None = None,
    client: SpotifyClient | None = None,
) -> dict[str, Any]:
    """Start or resume playback -- ``PUT /me/player/play``.

    With no ``--uri`` this resumes whatever is loaded. With one, *what* it sends
    depends on the kind: an album, artist or playlist is a ``context_uri``; a
    track or an episode is a one-item ``uris`` list. Sending the wrong one is a
    400 from Spotify, so the distinction is made here rather than discovered
    there.
    """
    body: dict[str, Any] = {}
    played: dict[str, Any] | None = None

    if uri:
        resolved = to_any_uri(uri)
        kind, _ = split_reference(resolved)
        if kind in CONTEXT_KINDS:
            body["context_uri"] = resolved
        else:
            body["uris"] = [resolved]
        played = {"kind": kind, **uri_ref(resolved)}

    if position_ms is not None:
        if position_ms < 0:
            raise _usage(
                f"--position-ms cannot be negative; got {position_ms}.",
                "Pass a position in milliseconds from the start of the track.",
            )
        body["position_ms"] = position_ms

    _client(client).put(PLAY, body or None, **_device_params(device))
    return _acted(
        "play",
        device,
        playing=played,
        resumed=uri is None,
        position_ms=position_ms,
    )


def pause(*, device: str | None = None, client: SpotifyClient | None = None):
    """Pause playback -- ``PUT /me/player/pause``."""
    _client(client).put(PAUSE, None, **_device_params(device))
    return _acted("pause", device)


def next_track(*, device: str | None = None, client: SpotifyClient | None = None):
    """Skip forward -- ``POST /me/player/next``."""
    _client(client).post(NEXT, None, **_device_params(device))
    return _acted("next", device)


def previous_track(*, device: str | None = None, client: SpotifyClient | None = None):
    """Skip back -- ``POST /me/player/previous``."""
    _client(client).post(PREVIOUS, None, **_device_params(device))
    return _acted("previous", device)


def seek(
    position_ms: int, *, device: str | None = None, client: SpotifyClient | None = None
):
    """Seek within the current track -- ``PUT /me/player/seek``."""
    if position_ms < 0:
        raise _usage(
            f"A position cannot be negative; got {position_ms}.",
            "Pass a position in milliseconds from the start of the track.",
        )
    _client(client).put(SEEK, None, position_ms=position_ms, **_device_params(device))
    return _acted("seek", device, position_ms=position_ms)


def volume(
    percent: int, *, device: str | None = None, client: SpotifyClient | None = None
):
    """Set the volume -- ``PUT /me/player/volume``.

    Spotify takes 0-100, and only on a device that reports ``supports_volume``;
    ``music-deck devices`` says which do.
    """
    if not 0 <= percent <= 100:
        raise _usage(
            f"Volume is a percentage from 0 to 100; got {percent}.",
            "Pass a whole number between 0 and 100.",
        )
    _client(client).put(
        VOLUME, None, volume_percent=percent, **_device_params(device)
    )
    return _acted("volume", device, volume_percent=percent)


def shuffle(
    state: str, *, device: str | None = None, client: SpotifyClient | None = None
):
    """Turn shuffle on or off -- ``PUT /me/player/shuffle``."""
    wanted = (state or "").strip().lower()
    if wanted not in {"on", "off"}:
        raise _usage(
            f"Shuffle is `on` or `off`; got {state!r}.",
            "Run `music-deck shuffle on` or `music-deck shuffle off`.",
        )
    on = wanted == "on"
    _client(client).put(SHUFFLE, None, state=on, **_device_params(device))
    return _acted("shuffle", device, shuffle=on)


def repeat(
    state: str, *, device: str | None = None, client: SpotifyClient | None = None
):
    """Set the repeat mode -- ``PUT /me/player/repeat``."""
    wanted = (state or "").strip().lower()
    if wanted not in REPEAT_STATES:
        raise _usage(
            f"Repeat is one of {', '.join(REPEAT_STATES)}; got {state!r}.",
            "`off` stops repeating, `track` repeats one track, `context` repeats "
            "the album or playlist.",
        )
    _client(client).put(REPEAT, None, state=wanted, **_device_params(device))
    return _acted("repeat", device, repeat=wanted)


def transfer(
    device_id: str, *, play_after: bool = False, client: SpotifyClient | None = None
):
    """Move playback to another device -- ``PUT /me/player``.

    Spotify's ``device_ids`` is an array but takes exactly one: "only a single
    device_id is currently supported. Supplying more than one will return 400."
    """
    wanted = (device_id or "").strip()
    if not wanted:
        raise _usage(
            "No device was named.",
            "Run `music-deck devices` and pass the id of one of them.",
        )
    _client(client).put(PLAYER, {"device_ids": [wanted], "play": bool(play_after)})
    return _acted("transfer", wanted, playing_after_transfer=bool(play_after))


def queue_add(
    uri: str, *, device: str | None = None, client: SpotifyClient | None = None
):
    """Add one item to the queue -- ``POST /me/player/queue``."""
    resolved = to_any_uri(uri)
    _client(client).post(QUEUE, None, uri=resolved, **_device_params(device))
    return _acted("queue-add", device, queued=uri_ref(resolved))
