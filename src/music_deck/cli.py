"""The `music-deck` binary -- a thin adapter over the `music_deck` library.

``cli.v1`` Core 1: "One binary, ``music-deck``, on PATH. Non-interactive. A run
with stdin closed never hangs. ``-h`` gives a terse human summary; ``--help``
gives a complete listing for an agent -- every verb, its arguments, types,
return shape, and which verbs are model-backed. Help goes to stdout, exits 0,
and is the only non-JSON output the binary ever prints to stdout."

Two rules shape this file.

**No domain logic lives here.** ``docs/VISION.md`` principle 1 -- the library is
the tool -- and the Smart Tools spec agree: "domain logic in the CLI is a defect:
it is capability the library cannot reach". Each verb resolves to a library call
and this module does the argument parsing and the printing, nothing else.

**The verb table below is the single source of truth for the surface.** The
argparse parser and both help texts are generated from it, so ``--help`` cannot
drift away from what the parser actually accepts -- a complete listing that lies
is worse than none, because an agent has no way to notice.

Verbs whose lane has not landed yet are present, listed in help, and refuse
loudly with ``not_implemented`` and a non-zero exit. A stub that exits 0 would
hide the gap from every caller, which the spec names explicitly as the failure
to avoid.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Final, Sequence

from music_deck.check import check as run_check
from music_deck.errors import (
    EXIT_FAILURE,
    EXIT_NO_PROVIDER,
    EXIT_REFUSAL,
    EXIT_SUCCESS,
    FROZEN_CODES,
    ErrorCode,
    MusicDeckError,
    NotImplementedVerb,
    emit_error,
    emit_json,
)
from music_deck.manifest import manifest as read_manifest
from music_deck.verbs import catalog, library, player, playlists
from music_deck.verbs.plan import plan as run_plan
from music_deck.verbs.auth_verbs import disconnect as run_disconnect
from music_deck.verbs.auth_verbs import login as run_login
from music_deck.verbs.auth_verbs import whoami as run_whoami

PROG: Final = "music-deck"


# --------------------------------------------------------------------------- #
# The verb table -- one description of the surface, used three ways
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Arg:
    """One argument: what it is called, its type, and whether it is required."""

    name: str  # "query" for a positional, "--limit" for an option
    type: str  # string | integer | flag | path
    help: str
    required: bool = False
    choices: tuple[str, ...] | None = None
    default: Any = None
    repeated: bool = False

    @property
    def positional(self) -> bool:
        return not self.name.startswith("-")

    def signature(self) -> str:
        """How this argument reads in the complete listing."""
        kind = self.type + ("[]" if self.repeated else "")
        if self.choices:
            kind = f"{kind} one of {'|'.join(self.choices)}"
        marks = "required" if self.required else "optional"
        if self.default is not None:
            marks += f", default {self.default}"
        return f"{self.name} ({kind}, {marks})"


@dataclass(frozen=True)
class Verb:
    """One verb: what it does, what it takes, what it returns."""

    name: str
    summary: str
    returns: str
    args: tuple[Arg, ...] = ()
    subverbs: tuple["Verb", ...] = ()
    model_backed: bool = False
    handler: Callable[[argparse.Namespace], dict[str, Any]] | None = None
    detail: str = field(default="")

    @property
    def implemented(self) -> bool:
        return self.handler is not None


_LIMIT = Arg(
    "--limit", "integer", "How many items to return.", default=20
)
_DEVICE = Arg(
    "--device", "string", "Spotify device id to act on. Defaults to the active device."
)


def _handle_check(_args: argparse.Namespace) -> dict[str, Any]:
    return run_check()


def _handle_manifest(_args: argparse.Namespace) -> dict[str, Any]:
    return read_manifest()


def _handle_plan(args: argparse.Namespace) -> dict[str, Any]:
    """`plan` -- the only model-backed verb (``cli.v1`` Core 3).

    The CLI reads ``--context`` off disk and hands the library its *content*:
    a library that took a path would be deciding what a caller may read. The
    library never touches the filesystem for this.

    ``--output`` writes the plan document alone, so the file is directly
    applicable with ``music-deck apply --plan <file>``. stdout still carries the
    full result -- plan plus prompt transcript -- because ``boundary.v1`` Core 3
    makes the transcript part of the answer, not an optional extra.
    """
    context: str | None = None
    if getattr(args, "context", None):
        source = Path(args.context)
        try:
            context = source.read_text(encoding="utf-8")
        except OSError as exc:
            raise MusicDeckError(
                ErrorCode.USAGE,
                f"--context {str(source)!r} could not be read: {exc.strerror or exc}.",
                "Point --context at a readable text file, or leave it out.",
            ) from exc

    result = run_plan(args.brief, context=context)

    if getattr(args, "output", None):
        destination = Path(args.output)
        try:
            destination.write_text(
                json.dumps(result["plan"], indent=2) + "\n", encoding="utf-8"
            )
        except OSError as exc:
            raise MusicDeckError(
                ErrorCode.USAGE,
                f"--output {str(destination)!r} could not be written: "
                f"{exc.strerror or exc}.",
                "Point --output at a writable path, or leave it out and read the "
                "plan from stdout.",
            ) from exc
    return result


def _handle_login(args: argparse.Namespace) -> dict[str, Any]:
    return run_login(timeout_s=float(getattr(args, "timeout", 180) or 180))


def _handle_disconnect(_args: argparse.Namespace) -> dict[str, Any]:
    return run_disconnect()


def _handle_whoami(_args: argparse.Namespace) -> dict[str, Any]:
    return run_whoami()


# -- the deterministic Spotify verbs ---------------------------------------- #
# Each of these is one line on purpose: `cli.v1` Core 7 and docs/VISION.md
# principle 1 put the whole implementation in the library, so the CLI's share of
# a verb is exactly "read the parsed arguments, call the function". Anything
# more here would be capability a Python caller could not reach.
def _handle_search(args: argparse.Namespace) -> dict[str, Any]:
    return catalog.search(args.query, kind=args.type, limit=args.limit)


def _handle_track(args: argparse.Namespace) -> Any:
    return catalog.track(args.id)


def _handle_album(args: argparse.Namespace) -> Any:
    return catalog.album(args.id)


def _handle_artist(args: argparse.Namespace) -> Any:
    return catalog.artist(args.id)


def _handle_show(args: argparse.Namespace) -> Any:
    return catalog.show(args.id)


def _handle_episode(args: argparse.Namespace) -> Any:
    return catalog.episode(args.id)


def _handle_playlists(args: argparse.Namespace) -> dict[str, Any]:
    return playlists.playlists(limit=args.limit)


def _handle_playlist_items(args: argparse.Namespace) -> dict[str, Any]:
    return playlists.playlist_items(args.playlist_id, limit=args.limit)


def _handle_playlist_create(args: argparse.Namespace) -> Any:
    return playlists.playlist_create(
        args.name, description=args.description, public=args.public
    )


def _handle_playlist_add(args: argparse.Namespace) -> dict[str, Any]:
    return playlists.playlist_add(args.playlist_id, args.track)


def _handle_playlist_remove(args: argparse.Namespace) -> dict[str, Any]:
    return playlists.playlist_remove(args.playlist_id, args.track)


def _handle_playlist_reorder(args: argparse.Namespace) -> dict[str, Any]:
    return playlists.playlist_reorder(
        args.playlist_id,
        range_start=args.range_start,
        insert_before=args.insert_before,
        range_length=args.range_length,
    )


def _handle_playlist_rename(args: argparse.Namespace) -> dict[str, Any]:
    return playlists.playlist_rename(args.playlist_id, args.name)


def _handle_library_list(args: argparse.Namespace) -> dict[str, Any]:
    return library.library_list(kind=args.type, limit=args.limit)


def _handle_library_save(args: argparse.Namespace) -> dict[str, Any]:
    return library.library_save(args.item)


def _handle_library_remove(args: argparse.Namespace) -> dict[str, Any]:
    return library.library_remove(args.item)


def _handle_library_contains(args: argparse.Namespace) -> dict[str, Any]:
    return library.library_contains(args.item)


def _handle_following(args: argparse.Namespace) -> dict[str, Any]:
    return library.following(limit=args.limit)


def _handle_top(args: argparse.Namespace) -> dict[str, Any]:
    return player.top(kind=args.type, time_range=args.time_range, limit=args.limit)


def _handle_recently_played(args: argparse.Namespace) -> dict[str, Any]:
    return player.recently_played(limit=args.limit)


def _handle_now_playing(_args: argparse.Namespace) -> Any:
    return player.now_playing()


def _handle_devices(_args: argparse.Namespace) -> dict[str, Any]:
    return player.devices()


def _handle_queue(_args: argparse.Namespace) -> dict[str, Any]:
    return player.queue()


def _handle_play(args: argparse.Namespace) -> dict[str, Any]:
    return player.play(
        uri=args.uri, position_ms=args.position_ms, device=args.device
    )


def _handle_pause(args: argparse.Namespace) -> dict[str, Any]:
    return player.pause(device=args.device)


def _handle_next(args: argparse.Namespace) -> dict[str, Any]:
    return player.next_track(device=args.device)


def _handle_previous(args: argparse.Namespace) -> dict[str, Any]:
    return player.previous_track(device=args.device)


def _handle_seek(args: argparse.Namespace) -> dict[str, Any]:
    return player.seek(args.position_ms, device=args.device)


def _handle_volume(args: argparse.Namespace) -> dict[str, Any]:
    return player.volume(args.percent, device=args.device)


def _handle_shuffle(args: argparse.Namespace) -> dict[str, Any]:
    return player.shuffle(args.state, device=args.device)


def _handle_repeat(args: argparse.Namespace) -> dict[str, Any]:
    return player.repeat(args.state, device=args.device)


def _handle_transfer(args: argparse.Namespace) -> dict[str, Any]:
    return player.transfer(args.device_id, play_after=args.play)


def _handle_queue_add(args: argparse.Namespace) -> dict[str, Any]:
    return player.queue_add(args.uri, device=args.device)


# The order here is the order cli.v1 Core 2 lists them, with `check` and
# `manifest` first because they are the two that work today.
VERBS: Final[tuple[Verb, ...]] = (
    Verb(
        "check",
        "Report music-deck's own state: credentials, token, scopes, provider.",
        "A JSON object of facts, with a `findings` list of what to do about them.",
        handler=_handle_check,
        detail=(
            "The deterministic smoke test. Runs with no credentials, no provider, "
            "and no network, and exits 0 always -- reporting a problem is its "
            "success, never a failure."
        ),
    ),
    Verb(
        "manifest",
        "Print this tool's SMART_TOOL.md manifest as structured data.",
        "A JSON object: the manifest frontmatter.",
        handler=_handle_manifest,
    ),
    # `plan` is declared further down, in the order cli.v1 lists the verbs; its
    # handler is wired there.
    Verb(
        "login",
        "Authorise against your own Spotify app, once, via PKCE in a browser.",
        "A JSON object naming the account, the granted scopes, and the token path.",
        args=(
            Arg(
                "--timeout",
                "integer",
                "Seconds to wait for the browser round trip before refusing.",
                default=180,
            ),
        ),
        handler=_handle_login,
        detail=(
            "The only interactive verb. Every other verb refuses "
            "`not_authenticated`. Needs MUSIC_DECK_CLIENT_ID (or a client_id in "
            "the config file): music-deck ships no credential of its own."
        ),
    ),
    Verb(
        "disconnect",
        "Delete the stored token and every locally cached byte of Spotify content.",
        "A JSON object listing exactly what was deleted.",
        handler=_handle_disconnect,
    ),
    Verb(
        "whoami",
        "Report the signed-in Spotify account.",
        "A JSON object describing the account.",
        handler=_handle_whoami,
    ),
    Verb(
        "search",
        "Search the Spotify catalogue.",
        "A JSON object with a `results` list; each item carries external_urls.spotify.",
        args=(
            Arg("query", "string", "The search expression.", required=True),
            Arg(
                "--type",
                "string",
                "What to search for.",
                choices=("track", "album", "artist", "show", "episode"),
                default="track",
            ),
            Arg(
                "--limit",
                "integer",
                "How many results. Spotify caps Development Mode search at 10 per page.",
                default=10,
            ),
        ),
        handler=_handle_search,
        detail=(
            "Spotify caps a search request at 10 results (February 2026; it was "
            "50). Asking for more is not an error and not a truncation -- it is "
            "more requests, walked for you, stopping at --limit exactly. The "
            "result reports `requested` beside `returned`."
        ),
    ),
    Verb(
        "track",
        "Look up one track.",
        "A JSON object describing the track.",
        args=(Arg("id", "string", "Spotify track id or URI.", required=True),),
        handler=_handle_track,
        detail=(
            "One item, one request. Spotify withdrew the batch fetch endpoints "
            "in February 2026, so music-deck never asks for several at once."
        ),
    ),
    Verb(
        "album",
        "Look up one album.",
        "A JSON object describing the album.",
        args=(Arg("id", "string", "Spotify album id or URI.", required=True),),
        handler=_handle_album,
        detail=(
            "One item, one request. Spotify withdrew the batch fetch endpoints "
            "in February 2026, so music-deck never asks for several at once."
        ),
    ),
    Verb(
        "artist",
        "Look up one artist.",
        "A JSON object describing the artist.",
        args=(Arg("id", "string", "Spotify artist id or URI.", required=True),),
        handler=_handle_artist,
        detail=(
            "One item, one request. Spotify withdrew the batch fetch endpoints "
            "in February 2026, so music-deck never asks for several at once."
        ),
    ),
    Verb(
        "show",
        "Look up one podcast show.",
        "A JSON object describing the show.",
        args=(Arg("id", "string", "Spotify show id or URI.", required=True),),
        handler=_handle_show,
        detail=(
            "One item, one request. Spotify withdrew the batch fetch endpoints "
            "in February 2026, so music-deck never asks for several at once."
        ),
    ),
    Verb(
        "episode",
        "Look up one podcast episode.",
        "A JSON object describing the episode.",
        args=(Arg("id", "string", "Spotify episode id or URI.", required=True),),
        handler=_handle_episode,
        detail=(
            "One item, one request. Spotify withdrew the batch fetch endpoints "
            "in February 2026, so music-deck never asks for several at once."
        ),
    ),
    Verb(
        "playlists",
        "List the signed-in account's playlists.",
        "A JSON object with a `playlists` list.",
        args=(_LIMIT,),
        handler=_handle_playlists,
    ),
    Verb(
        "playlist",
        "Read and edit one playlist.",
        "See each sub-verb.",
        subverbs=(
            Verb(
                "items",
                "List the items in a playlist.",
                "A JSON object with an `items` list.",
                args=(
                    Arg("playlist_id", "string", "Spotify playlist id.", required=True),
                    _LIMIT,
                ),
                handler=_handle_playlist_items,
                detail=(
                    "Spotify returns items only for a playlist the caller owns or "
                    "collaborates on; anything else refuses "
                    "`playlist_items_unavailable`."
                ),
            ),
            Verb(
                "create",
                "Create a new playlist.",
                "A JSON object describing the created playlist.",
                args=(
                    Arg("name", "string", "The playlist's name.", required=True),
                    Arg("--description", "string", "The playlist's description."),
                    Arg("--public", "flag", "Make the playlist public."),
                ),
                handler=_handle_playlist_create,
                detail="Private unless --public is passed.",
            ),
            Verb(
                "add",
                "Add tracks to a playlist.",
                "A JSON object naming the playlist and what was added.",
                args=(
                    Arg("playlist_id", "string", "Spotify playlist id.", required=True),
                    Arg(
                        "track",
                        "string",
                        "One or more Spotify track ids or URIs.",
                        required=True,
                        repeated=True,
                    ),
                ),
                handler=_handle_playlist_add,
                detail=(
                    "Spotify takes at most 100 items per request, so 250 tracks "
                    "is three requests sent in order. A run that gets part way "
                    "refuses `partial_result` naming what did land."
                ),
            ),
            Verb(
                "remove",
                "Remove tracks from a playlist.",
                "A JSON object naming the playlist and what was removed.",
                args=(
                    Arg("playlist_id", "string", "Spotify playlist id.", required=True),
                    Arg(
                        "track",
                        "string",
                        "One or more Spotify track ids or URIs.",
                        required=True,
                        repeated=True,
                    ),
                ),
                handler=_handle_playlist_remove,
                detail="Batched at 100 per request, like `playlist add`.",
            ),
            Verb(
                "reorder",
                "Move a run of items within a playlist.",
                "A JSON object naming the playlist and the new order's snapshot.",
                args=(
                    Arg("playlist_id", "string", "Spotify playlist id.", required=True),
                    Arg(
                        "--range-start",
                        "integer",
                        "Zero-based index of the first item to move.",
                        required=True,
                    ),
                    Arg(
                        "--insert-before",
                        "integer",
                        "Zero-based index to insert the moved items before.",
                        required=True,
                    ),
                    Arg(
                        "--range-length",
                        "integer",
                        "How many items to move.",
                        default=1,
                    ),
                ),
                handler=_handle_playlist_reorder,
                detail="Positions are zero-based: the first item is position 0.",
            ),
            Verb(
                "rename",
                "Rename a playlist.",
                "A JSON object describing the renamed playlist.",
                args=(
                    Arg("playlist_id", "string", "Spotify playlist id.", required=True),
                    Arg("name", "string", "The new name.", required=True),
                ),
                handler=_handle_playlist_rename,
            ),
        ),
    ),
    Verb(
        "library",
        "Read and edit the saved library.",
        "See each sub-verb.",
        subverbs=(
            Verb(
                "list",
                "List saved library items.",
                "A JSON object with an `items` list.",
                args=(
                    Arg(
                        "--type",
                        "string",
                        "Which saved content type to list.",
                        choices=("tracks", "albums", "shows", "episodes", "audiobooks"),
                        default="tracks",
                    ),
                    _LIMIT,
                ),
                handler=_handle_library_list,
                detail=(
                    "Spotify enumerates saved items one content type at a time, "
                    "so this takes --type. Saving and removing do not: they take "
                    "URIs of any type together."
                ),
            ),
            Verb(
                "save",
                "Save items to the library.",
                "A JSON object naming what was saved.",
                args=(
                    Arg(
                        "item",
                        "string",
                        "One or more Spotify URIs or open.spotify.com links.",
                        required=True,
                        repeated=True,
                    ),
                ),
                handler=_handle_library_save,
                detail=(
                    "Takes URIs, not bare ids: since February 2026 one endpoint "
                    "saves any content type, so the URI is what says which type "
                    "this is. Following an artist is saving its URI."
                ),
            ),
            Verb(
                "remove",
                "Remove items from the library.",
                "A JSON object naming what was removed.",
                args=(
                    Arg(
                        "item",
                        "string",
                        "One or more Spotify URIs or open.spotify.com links.",
                        required=True,
                        repeated=True,
                    ),
                ),
                handler=_handle_library_remove,
                detail="Takes URIs, not bare ids -- see `library save`.",
            ),
            Verb(
                "contains",
                "Ask whether items are in the library.",
                "A JSON object mapping each URI to true or false.",
                args=(
                    Arg(
                        "item",
                        "string",
                        "One or more Spotify URIs or open.spotify.com links.",
                        required=True,
                        repeated=True,
                    ),
                ),
                handler=_handle_library_contains,
                detail="Takes URIs, not bare ids -- see `library save`.",
            ),
        ),
    ),
    Verb(
        "following",
        "List the artists the account follows.",
        "A JSON object with an `artists` list.",
        args=(_LIMIT,),
        handler=_handle_following,
        detail=(
            "Reading who the account follows is all that survived February 2026: "
            "following and unfollowing are `library save` and `library remove`."
        ),
    ),
    Verb(
        "top",
        "List the account's top artists or tracks.",
        "A JSON object with an `items` list.",
        args=(
            Arg(
                "--type",
                "string",
                "Which top list to read.",
                choices=("artists", "tracks"),
                default="tracks",
            ),
            Arg(
                "--time-range",
                "string",
                "How far back to look: about 4 weeks, 6 months, or a year.",
                choices=("short_term", "medium_term", "long_term"),
                default="medium_term",
            ),
            _LIMIT,
        ),
        handler=_handle_top,
        detail=(
            "Spotify's own windows: short_term is about four weeks, medium_term "
            "about six months, long_term about a year."
        ),
    ),
    Verb(
        "recently-played",
        "List recently played tracks.",
        "A JSON object with an `items` list.",
        args=(_LIMIT,),
        handler=_handle_recently_played,
        detail="Spotify's note: this does not currently include podcast episodes.",
    ),
    Verb(
        "now-playing",
        "Report what is playing right now.",
        "A JSON object describing current playback.",
        handler=_handle_now_playing,
        detail=(
            "With nothing playing, Spotify answers 204 No Content and music-deck "
            "refuses `no_active_device` rather than returning an empty document: "
            "\"nothing is playing\" and \"I could not tell\" must not look alike."
        ),
    ),
    Verb(
        "devices",
        "List the account's available Spotify Connect devices.",
        "A JSON object with a `devices` list.",
        handler=_handle_devices,
        detail=(
            "Only Spotify clients already running and signed in appear here. An "
            "empty list is a real answer -- and the one to read before `transfer`."
        ),
    ),
    Verb(
        "queue",
        "Read the playback queue.",
        "A JSON object with `currently_playing` and a `queue` list.",
        handler=_handle_queue,
    ),
    Verb(
        "play",
        "Start or resume playback on a device that is already available.",
        "A JSON object confirming the playback state.",
        args=(
            Arg("--uri", "string", "Spotify URI to play. Omit to resume."),
            Arg("--position-ms", "integer", "Where in the track to start."),
            _DEVICE,
        ),
        handler=_handle_play,
        detail=(
            "Needs Premium and an active device; music-deck produces no audio "
            "itself. An album, artist or playlist URI plays as a context; a track "
            "or episode URI plays on its own. Omit --uri to resume."
        ),
    ),
    Verb(
        "pause",
        "Pause playback.",
        "A JSON object confirming the playback state.",
        args=(_DEVICE,),
        handler=_handle_pause,
    ),
    Verb(
        "next",
        "Skip to the next track.",
        "A JSON object confirming the playback state.",
        args=(_DEVICE,),
        handler=_handle_next,
    ),
    Verb(
        "previous",
        "Skip to the previous track.",
        "A JSON object confirming the playback state.",
        args=(_DEVICE,),
        handler=_handle_previous,
    ),
    Verb(
        "seek",
        "Seek within the current track.",
        "A JSON object confirming the playback state.",
        args=(
            Arg("position_ms", "integer", "Position in milliseconds.", required=True),
            _DEVICE,
        ),
        handler=_handle_seek,
    ),
    Verb(
        "volume",
        "Set the volume on a device.",
        "A JSON object confirming the volume.",
        args=(
            Arg("percent", "integer", "Volume from 0 to 100.", required=True),
            _DEVICE,
        ),
        handler=_handle_volume,
        detail="Only devices that report `supports_volume` accept this.",
    ),
    Verb(
        "shuffle",
        "Turn shuffle on or off.",
        "A JSON object confirming the shuffle state.",
        args=(
            Arg("state", "string", "on or off.", required=True, choices=("on", "off")),
            _DEVICE,
        ),
        handler=_handle_shuffle,
    ),
    Verb(
        "repeat",
        "Set the repeat mode.",
        "A JSON object confirming the repeat mode.",
        args=(
            Arg(
                "state",
                "string",
                "off, track, or context.",
                required=True,
                choices=("off", "track", "context"),
            ),
            _DEVICE,
        ),
        handler=_handle_repeat,
    ),
    Verb(
        "transfer",
        "Move playback to another device.",
        "A JSON object confirming which device is now active.",
        args=(
            Arg("device_id", "string", "The device to move playback to.", required=True),
            Arg("--play", "flag", "Start playing after transferring."),
        ),
        handler=_handle_transfer,
        detail=(
            "Spotify supports exactly one device per transfer. Run `music-deck "
            "devices` for the ids."
        ),
    ),
    Verb(
        "queue-add",
        "Add one item to the playback queue.",
        "A JSON object confirming what was queued.",
        args=(
            Arg("uri", "string", "Spotify track or episode URI.", required=True),
            _DEVICE,
        ),
        handler=_handle_queue_add,
    ),
    Verb(
        "apply",
        "Carry out a plan against Spotify, deterministically.",
        (
            "A JSON object naming the playlist and a per-step `completeness` of "
            "requested/fetched/kept."
        ),
        args=(
            Arg("--plan", "path", "Path to a plan JSON document.", required=True),
        ),
        detail=(
            "No model runs during apply. An under-fulfilled step is reported as "
            "`partial_result`, never as a silent success."
        ),
    ),
    Verb(
        "plan",
        "Turn a brief in your own words into a readable plan document.",
        (
            "A JSON object: `plan` (a plan.v1 document) and `transcript` (the "
            "verbatim text of every prompt sent to the model)."
        ),
        args=(
            Arg("brief", "string", "What you want, in your own words.", required=True),
            Arg(
                "--context",
                "path",
                "A text file whose contents are passed to the model as caller data.",
            ),
            Arg(
                "--output",
                "path",
                "Write the plan document here, ready for `apply`. stdout still "
                "carries the plan and its transcript.",
            ),
        ),
        model_backed=True,
        handler=_handle_plan,
        detail=(
            "The only model-backed verb. With no usable model substrate it exits 3 "
            "naming the missing precondition -- no provider configured, no "
            "credentials, the provider SDK absent, or the engine absent -- and "
            "never falls back to a deterministic answer. It makes no Spotify "
            "request at all and needs no token: every prompt is built from your "
            "own text and music-deck's own static prompt text, and `transcript` "
            "is there so you can check that yourself."
        ),
    ),
)


VERBS_BY_NAME: Final[dict[str, Verb]] = {verb.name: verb for verb in VERBS}


# --------------------------------------------------------------------------- #
# Help -- generated from the table above, printed to stdout, exits 0
# --------------------------------------------------------------------------- #
def _verb_line(verb: Verb, width: int) -> str:
    return f"  {verb.name.ljust(width)}  {verb.summary}"


def terse_help() -> str:
    """``-h``: the scannable human summary."""
    width = max(len(verb.name) for verb in VERBS)
    lines = [
        f"{PROG} -- curate and control music on Spotify from an agent.",
        "",
        f"usage: {PROG} <verb> [arguments]",
        "",
        "Verbs:",
    ]
    lines += [_verb_line(verb, width) for verb in VERBS]
    lines += [
        "",
        "`plan` is the only verb that uses a model; everything else runs without one.",
        f"`{PROG} check` needs no credentials and no network -- start there.",
        "",
        f"Run `{PROG} --help` for the complete listing: every argument, its type, and "
        "what each verb returns.",
    ]
    return "\n".join(lines)


def _render_verb(verb: Verb, prefix: str = "") -> list[str]:
    full_name = f"{prefix}{verb.name}"
    kind = "model-backed" if verb.model_backed else "deterministic"
    status = "" if verb.implemented else "  [NOT IMPLEMENTED in this build]"
    lines = [f"{PROG} {full_name}  ({kind}){status}", f"    {verb.summary}"]
    if verb.detail:
        lines.append(f"    {verb.detail}")
    if verb.args:
        lines.append("    arguments:")
        lines += [f"      {arg.signature()} -- {arg.help}" for arg in verb.args]
    elif not verb.subverbs:
        lines.append("    arguments: none")
    if verb.subverbs:
        lines.append("    sub-verbs:")
        for sub in verb.subverbs:
            lines.append("")
            lines += [f"  {line}" for line in _render_verb(sub, f"{full_name} ")]
    else:
        lines.append(f"    returns: {verb.returns}")
    return lines


def complete_help() -> str:
    """``--help``: the complete listing, written for an agent deciding how to call."""
    lines = [
        f"{PROG} -- curate and control music on Spotify from an agent.",
        "",
        f"usage: {PROG} <verb> [arguments]",
        "",
        "OUTPUT",
        "  Every result is exactly one JSON document on stdout. Progress and",
        "  diagnostics go to stderr. This help text is the only non-JSON output",
        "  the binary ever prints to stdout.",
        "",
        "EXIT CODES",
        f"  {EXIT_SUCCESS}  success",
        f"  {EXIT_FAILURE}  failure",
        f"  {EXIT_REFUSAL}  refusal, usage, or invalid input",
        f"  {EXIT_NO_PROVIDER}  no model provider configured (the `plan` verb only)",
        "",
        "FAILURE SHAPE",
        '  {"error": {"code": ..., "message": ..., "remedy": ...}}',
        "  Codes are frozen; a caller may branch on them:",
    ]
    lines += [f"    {code}" for code in sorted(FROZEN_CODES)]
    lines += [
        "",
        "MODEL-BACKED VERBS",
        "  plan -- the only one. Every other verb runs with no model provider",
        "  configured and no provider SDK installed.",
        "",
        "VERBS",
    ]
    for verb in VERBS:
        lines.append("")
        lines += _render_verb(verb)
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
class _UsageError(Exception):
    """A malformed invocation. Becomes a `usage` envelope and exit 2."""


class _Parser(argparse.ArgumentParser):
    """An argparse parser that refuses through music-deck's error envelope.

    argparse's own behaviour -- print usage to stderr, exit 2 -- would leave
    stdout empty, and ``cli.v1`` Core 4 requires a JSON document there.
    """

    def error(self, message: str) -> Any:  # type: ignore[override]
        raise _UsageError(message)

    def exit(self, status: int = 0, message: str | None = None) -> Any:  # type: ignore[override]
        if status:
            raise _UsageError(message or "invalid invocation")
        raise SystemExit(status)


def _add_args(parser: argparse.ArgumentParser, args: Sequence[Arg]) -> None:
    for arg in args:
        options: dict[str, Any] = {"help": arg.help}
        if arg.type == "flag":
            options["action"] = "store_true"
        else:
            options["type"] = int if arg.type == "integer" else str
            if arg.choices:
                options["choices"] = list(arg.choices)
            if arg.default is not None:
                options["default"] = arg.default
        if arg.positional:
            if arg.repeated:
                options["nargs"] = "+"
            parser.add_argument(arg.name, **options)
        else:
            if arg.required:
                options["required"] = True
            if arg.repeated:
                options["nargs"] = "+"
            parser.add_argument(arg.name, **options)


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser from the verb table.

    ``add_help=False`` throughout: ``-h`` and ``--help`` are handled before
    argparse sees the arguments, because the two must render different text and
    argparse renders one.
    """
    parser = _Parser(prog=PROG, add_help=False)
    verbs = parser.add_subparsers(dest="_verb", metavar="<verb>", required=True)
    for verb in VERBS:
        sub = verbs.add_parser(verb.name, help=verb.summary, add_help=False)
        if verb.subverbs:
            nested = sub.add_subparsers(dest="_subverb", metavar="<sub-verb>", required=True)
            for subverb in verb.subverbs:
                leaf = nested.add_parser(
                    subverb.name, help=subverb.summary, add_help=False
                )
                _add_args(leaf, subverb.args)
                leaf.set_defaults(_resolved=subverb, _path=f"{verb.name} {subverb.name}")
        else:
            _add_args(sub, verb.args)
            sub.set_defaults(_resolved=verb, _path=verb.name)
    return parser


def _help_request(argv: Sequence[str]) -> str | None:
    """The help text to print for this argv, or None if help was not asked for.

    ``-h`` alone is the terse summary. ``--help`` is the complete listing. Both
    win over everything else on the command line: a caller asking how to use the
    tool gets an answer, not a complaint about their other arguments.
    """
    wants_complete = "--help" in argv
    wants_terse = "-h" in argv
    if not (wants_complete or wants_terse):
        return None
    if wants_complete:
        return complete_help()
    return terse_help()


def _dispatch(args: argparse.Namespace) -> int:
    verb: Verb = getattr(args, "_resolved")
    path: str = getattr(args, "_path")
    if verb.handler is None:
        raise NotImplementedVerb(path)
    emit_json(verb.handler(args))
    return EXIT_SUCCESS


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns the process exit code; never raises to the shell."""
    arguments = list(sys.argv[1:] if argv is None else argv)

    help_text = _help_request(arguments)
    if help_text is not None:
        print(help_text)
        return EXIT_SUCCESS

    try:
        args = build_parser().parse_args(arguments)
    except _UsageError as exc:
        print(str(exc), file=sys.stderr)
        return emit_error(
            MusicDeckError(
                ErrorCode.USAGE,
                f"{PROG} could not understand that invocation: {exc}",
            )
        )
    except SystemExit as exc:  # argparse asked to stop cleanly
        return int(exc.code or EXIT_SUCCESS)

    try:
        return _dispatch(args)
    except MusicDeckError as exc:
        print(exc.message, file=sys.stderr)
        return emit_error(exc)
    except Exception as exc:  # noqa: BLE001 - a failure is loud, never a traceback
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return emit_error(
            MusicDeckError(
                "internal_error",
                f"{PROG} hit an unexpected internal error: {type(exc).__name__}: {exc}",
                f"Run `{PROG} check` to report the tool's state, then report this.",
            )
        )


if __name__ == "__main__":
    raise SystemExit(main())
