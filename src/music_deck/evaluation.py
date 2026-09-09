"""Opt-in real-provider evaluation of installed ``do`` against fake boundaries.

Run this module only from an installed wheel or sdist, with a deliberately
configured provider.  It invokes music-deck's real native engine and handlers;
the injected Spotify and LAN doubles hard-fail any endpoint they do not model,
so no Spotify or local-network traffic can escape the evaluation.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from typing import Any, Sequence

from music_deck.errors import MusicDeckError
from music_deck.verbs.do import do


TRACK_ID = "EEEEEEEEEEEEEEEEEEEEEE"
PLAYLIST_ID = "PPPPPPPPPPPPPPPPPPPPPP"


@dataclass
class FakeSpotify:
    """A closed, in-memory Spotify state; unexpected requests fail immediately."""

    requests: list[tuple[str, str]] = field(default_factory=list)
    playlist_tracks: list[dict[str, Any]] = field(default_factory=list)

    def request(self, method: str, path: str, **_kwargs: Any) -> Any:
        self.requests.append((method, path))
        if method == "GET" and path == "/search":
            return {"tracks": {"items": [self._track()]}}
        if method == "POST" and path == "/me/playlists":
            return {
                "id": PLAYLIST_ID,
                "uri": f"spotify:playlist:{PLAYLIST_ID}",
                "name": "Evaluation playlist",
                "type": "playlist",
                "public": False,
            }
        if path == f"/playlists/{PLAYLIST_ID}/items" and method == "POST":
            self.playlist_tracks = [self._track()]
            return {"snapshot_id": "synthetic-snapshot"}
        if path == f"/playlists/{PLAYLIST_ID}/items" and method == "GET":
            return {"items": [{"item": track} for track in self.playlist_tracks]}
        if method == "GET" and path == "/me/library":
            return {"items": [{"item": self._track()}]}
        if method == "GET" and path == "/me/player/devices":
            return {
                "devices": [
                    {
                        "id": "synthetic-device",
                        "name": "Synthetic device",
                        "type": "Computer",
                        "is_active": True,
                    }
                ]
            }
        raise AssertionError(f"evaluation blocked unexpected Spotify request: {method} {path}")

    @staticmethod
    def _track() -> dict[str, Any]:
        return {
            "id": TRACK_ID,
            "uri": f"spotify:track:{TRACK_ID}",
            "name": "Synthetic Track",
            "type": "track",
            "artists": [{"id": TRACK_ID, "name": "Synthetic Artist", "type": "artist"}],
        }


class FakeLan:
    """A LAN observer that returns a fixture and never opens a socket."""

    def observe(self, _devices: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"observed": True, "receivers": [{"name": "Synthetic receiver"}]}


def _run(scenario: str, *, provider: str | None, model: str | None) -> dict[str, Any]:
    if scenario == "named-session":
        return {
            "scenario": scenario,
            "status": "blocked",
            "reason": "Named create/resume sessions are not implemented in this build.",
        }

    spotify = FakeSpotify()
    kwargs: dict[str, Any] = {
        "client": spotify,
        "provider": provider,
        "model": model,
    }
    if scenario == "playlist":
        brief = (
            "Search for one track, then create a new playlist named Evaluation "
            "playlist containing that exact returned track, and finish."
        )
    elif scenario == "readonly-inventory":
        brief = "Read my saved tracks and devices, including the allowed local observation, then finish."
        kwargs.update(read_only=True, local=True, local_observer=FakeLan())
    elif scenario == "no-playback":
        brief = "Pause playback, then finish."
        kwargs.update(no_playback=True)
    else:
        raise ValueError(scenario)

    try:
        result = do(brief, **kwargs)
        error = None
    except MusicDeckError as caught:
        result = caught.extra.get("result")
        error = caught.code

    writes = [(method, path) for method, path in spotify.requests if method != "GET"]
    if scenario == "playlist":
        passed = bool(spotify.playlist_tracks) and error is None
    elif scenario == "readonly-inventory":
        passed = not writes and error is None
    else:
        passed = not writes and error == "partial_result"
    return {
        "scenario": scenario,
        "status": "pass" if passed else "fail",
        "error_code": error,
        "spotify_requests": spotify.requests,
        "writes": writes,
        "operations": result.get("operations", []) if isinstance(result, dict) else [],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run real installed music-deck do/native-engine scenarios against fake "
            "Spotify and LAN state. This can call the selected real model provider."
        )
    )
    parser.add_argument(
        "--scenario",
        choices=("playlist", "readonly-inventory", "no-playback", "named-session"),
        required=True,
    )
    parser.add_argument("--provider", help="Provider passed to music-deck do.")
    parser.add_argument("--model", help="Model passed to music-deck do.")
    parser.add_argument(
        "--confirm-real-provider",
        action="store_true",
        help="Required acknowledgement that this evaluates a real configured provider.",
    )
    args = parser.parse_args(argv)
    if not args.confirm_real_provider:
        print(json.dumps({"error": "pass --confirm-real-provider to start a provider call"}))
        return 2
    outcome = _run(args.scenario, provider=args.provider, model=args.model)
    print(json.dumps(outcome, indent=2))
    return 0 if outcome["status"] in {"pass", "blocked"} else 1


if __name__ == "__main__":
    raise SystemExit(main())