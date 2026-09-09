"""Opt-in installed-CLI evaluation of ``do`` against closed fake boundaries.

The evaluator deliberately has two kinds of evidence.  Provider-confirmed runs
exercise the shipped CLI, native engine, and music tools while its Spotify and
LAN boundaries are closed in memory.  Offline scripted probes exercise the same
path to prove that the grade rejects specific wrong outcomes.  A scripted probe
does not make a claim about a real provider's tool calling.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import io
import json
import os
import shutil
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Iterator, Mapping, Sequence

from music_deck import cli
from music_deck.errors import ErrorCode, MusicDeckError
from music_deck.intelligence import Intelligence

EVALUATION_EXIT_BLOCKED = 4
"""A scenario is intentionally unavailable in this build, rather than passed."""

PLAYLIST_ID = "PPPPPPPPPPPPPPPPPPPPPP"
PLAYLIST_NAME = "Evaluation: Ordered Fixture Set"
FIXTURE_API_DEVICE = {
    "id": "synthetic-api-device",
    "name": "Synthetic API device",
    "type": "Computer",
    "is_active": True,
}
MAX_TURNS = 12
MAX_REQUESTS = 24
SCENARIOS: Final = (
    "playlist",
    "readonly-inventory",
    "no-playback",
    "unknown-write",
    "named-session",
)
_INVOCATION_LOCK = threading.RLock()


def _track(identifier: str, name: str, artist: str) -> dict[str, Any]:
    return {
        "id": identifier,
        "uri": f"spotify:track:{identifier}",
        "name": name,
        "type": "track",
        "artists": [
            {
                "id": f"A{identifier[1:]}",
                "uri": f"spotify:artist:A{identifier[1:]}",
                "name": artist,
                "type": "artist",
            }
        ],
    }


# Six requested tracks across three artists, in the only order the playlist
# scenario accepts.  The two similar-but-wrong records make the grade useful:
# a non-empty playlist or a plausible title is not enough.
FIXTURE_TRACKS: tuple[dict[str, Any], ...] = (
    _track("T000000000000000000001", "First Light", "Fixture North"),
    _track("T000000000000000000002", "Static Bloom", "Fixture North"),
    _track("T000000000000000000003", "Paper Satellites", "Fixture East"),
    _track("T000000000000000000004", "Copper Sky", "Fixture East"),
    _track("T000000000000000000005", "Night Signal", "Fixture South"),
    _track("T000000000000000000006", "Last Exit", "Fixture South"),
)
DISTRACTOR_TRACKS: tuple[dict[str, Any], ...] = (
    _track("T000000000000000000007", "First Light (Live)", "Fixture North"),
    _track("T000000000000000000008", "Last Exit (Remix)", "Fixture South"),
)
EXPECTED_URIS = tuple(track["uri"] for track in FIXTURE_TRACKS)
TRACKS_BY_URI = {track["uri"]: track for track in (*FIXTURE_TRACKS, *DISTRACTOR_TRACKS)}


@dataclass(frozen=True)
class RecordedRequest:
    """A logical fake-boundary request, including submitted body for grading."""

    method: str
    path: str
    body: Mapping[str, Any] | None


@dataclass
class FakeSpotify:
    """Closed mutable Spotify state; every unsupported endpoint fails loudly."""

    fail_first_mutation: bool = False
    requests: list[RecordedRequest] = field(default_factory=list)
    playlist_name: str | None = None
    playlist_tracks: list[dict[str, Any]] = field(default_factory=list)
    readbacks: int = 0
    returned_readbacks: list[tuple[str, ...]] = field(default_factory=list)

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        **_kwargs: Any,
    ) -> Any:
        request = RecordedRequest(
            method=method.upper(),
            path=path,
            body=_recorded_body(path, body),
        )
        self.requests.append(request)

        if request.method == "GET" and path == "/search":
            return {"tracks": {"items": [*FIXTURE_TRACKS, *DISTRACTOR_TRACKS]}}
        if request.method == "GET" and path == "/me/tracks":
            return {"items": [{"item": FIXTURE_TRACKS[0]}]}
        if request.method == "GET" and path == "/me/player/devices":
            return {"devices": [copy.deepcopy(FIXTURE_API_DEVICE)]}
        if request.method == "POST" and path == "/me/playlists":
            if self.fail_first_mutation:
                self.fail_first_mutation = False
                raise MusicDeckError(
                    ErrorCode.SPOTIFY_ERROR,
                    "Synthetic evaluator transport interruption.",
                    "Inspect the playlist before retrying.",
                    diagnostic_code="network_unreachable",
                )
            submitted = body if isinstance(body, Mapping) else {}
            name = submitted.get("name")
            if not isinstance(name, str):
                raise AssertionError("playlist creation did not submit a name")
            self.playlist_name = name
            return {
                "id": PLAYLIST_ID,
                "uri": f"spotify:playlist:{PLAYLIST_ID}",
                "name": name,
                "type": "playlist",
                "public": bool(submitted.get("public", False)),
            }
        if request.method == "POST" and path == f"/playlists/{PLAYLIST_ID}/items":
            submitted = body if isinstance(body, Mapping) else {}
            uris = submitted.get("uris")
            if not isinstance(uris, list):
                raise AssertionError("playlist addition did not submit URI strings")
            if len(uris) > len(EXPECTED_URIS):
                raise AssertionError("playlist addition exceeded the evaluator fixture size")
            if not all(isinstance(uri, str) for uri in uris):
                raise AssertionError("playlist addition did not submit URI strings")
            try:
                tracks = [TRACKS_BY_URI[uri] for uri in uris]
            except KeyError as exc:
                raise AssertionError("playlist addition submitted an unknown fixture URI") from exc
            self.playlist_tracks.extend(copy.deepcopy(track) for track in tracks)
            return {"snapshot_id": f"synthetic-{len(self.playlist_tracks)}"}
        if request.method == "GET" and path == f"/playlists/{PLAYLIST_ID}/items":
            self.readbacks += 1
            self.returned_readbacks.append(
                tuple(track["uri"] for track in self.playlist_tracks)
            )
            return {"items": [{"item": copy.deepcopy(track)} for track in self.playlist_tracks]}
        raise AssertionError(
            f"evaluation blocked unexpected Spotify request: {request.method} {path}"
        )


def _recorded_body(path: str, body: Any) -> Mapping[str, Any] | None:
    """Retain only the small request facts that the scenario grade needs."""

    if not isinstance(body, Mapping):
        return None
    if path == "/me/playlists":
        name = body.get("name")
        return {"name": name} if isinstance(name, str) else None
    if path == f"/playlists/{PLAYLIST_ID}/items":
        uris = body.get("uris")
        if (
            isinstance(uris, list)
            and len(uris) <= len(EXPECTED_URIS)
            and all(isinstance(uri, str) for uri in uris)
        ):
            return {"uris": tuple(uris)}
    return None


@dataclass
class FakeLan:
    """The real observer protocol, with ordering evidence but no socket access."""

    spotify: FakeSpotify
    calls: list[dict[str, Any]] = field(default_factory=list)

    def observe(
        self,
        web_devices: Sequence[object],
        *,
        discovery_timeout_s: int = 5,
        interface: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "after_request": len(self.spotify.requests),
                "web_devices": list(web_devices),
                "discovery_timeout_s": discovery_timeout_s,
                "interface": interface,
            }
        )
        return {"observed": True, "receivers": [{"name": "Synthetic receiver"}]}


@dataclass
class IsolatedEnvironment:
    """The observable cleanup state of one private evaluator environment."""

    cleanup_failed: bool = False


@dataclass
class Invocation:
    """What crossed the CLI seam, retained only while an evaluation is graded."""

    argv: list[str]
    exit_code: int
    document: dict[str, Any] | None
    spotify: FakeSpotify
    lan: FakeLan
    original_run_do_called: bool
    isolation_cleanup_failed: bool


def _brief(scenario: str) -> str:
    if scenario == "playlist":
        lines = "; ".join(
            f"{track['name']} by {track['artists'][0]['name']}" for track in FIXTURE_TRACKS
        )
        return (
            f"Create a playlist named {PLAYLIST_NAME!r} containing exactly these songs "
            f"in this order, with no duplicates: {lines}. Search before writing, then finish."
        )
    if scenario == "readonly-inventory":
        return (
            "Read my saved tracks and authenticated Spotify API devices, then make the "
            "one allowed local observation and finish without changing anything."
        )
    if scenario == "no-playback":
        return "Pause playback, then finish."
    if scenario == "unknown-write":
        return "Create a playlist named Uncertain Fixture Write, then finish."
    raise ValueError(f"unknown evaluation scenario: {scenario}")


def _do_argv(scenario: str) -> list[str]:
    argv = [
        "do",
        _brief(scenario),
        "--max-turns",
        str(MAX_TURNS),
        "--max-requests",
        str(MAX_REQUESTS),
    ]
    if scenario == "readonly-inventory":
        argv.extend(("--read-only", "--local"))
    if scenario == "no-playback":
        argv.append("--no-playback")
    return argv


@contextlib.contextmanager
def _isolated_music_deck_environment() -> Iterator[IsolatedEnvironment]:
    """Keep evaluator configuration/state out of the caller's account paths."""

    root = Path(tempfile.mkdtemp(prefix="music-deck-evaluation-"))
    os.chmod(root, 0o700)
    old_values = {
        key: os.environ.get(key)
        for key in (
            "HOME",
            "XDG_CONFIG_HOME",
            "XDG_STATE_HOME",
            "MUSIC_DECK_CONFIG_DIR",
            "MUSIC_DECK_STATE_DIR",
        )
    }
    environment = IsolatedEnvironment()
    try:
        home = root / "home"
        config = root / "config"
        state = root / "state"
        for directory in (home, config, state):
            directory.mkdir(mode=0o700)
        os.environ.update(
            {
                "HOME": str(home),
                "XDG_CONFIG_HOME": str(config),
                "XDG_STATE_HOME": str(state),
                "MUSIC_DECK_CONFIG_DIR": str(config),
                "MUSIC_DECK_STATE_DIR": str(state),
            }
        )
        yield environment
    finally:
        for key, value in old_values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        try:
            shutil.rmtree(root)
        except OSError:
            environment.cleanup_failed = True


def _invoke_cli(
    scenario: str,
    *,
    provider: str | None,
    model: str | None,
    intelligence: Intelligence | None = None,
) -> Invocation:
    """Invoke ``cli.main`` with only its ``run_do`` dependency scoped-injected."""

    # The CLI's streams and configuration environment are process-global. Keep
    # their temporary replacement from crossing between evaluator invocations.
    with _INVOCATION_LOCK:
        spotify = FakeSpotify(fail_first_mutation=scenario == "unknown-write")
        lan = FakeLan(spotify)
        argv = _do_argv(scenario)
        original_run_do = cli.run_do
        original_called = False

        def injected_run_do(brief: str, **cli_kwargs: Any) -> dict[str, Any]:
            nonlocal original_called
            original_called = True
            return original_run_do(
                brief,
                **cli_kwargs,
                client=spotify,
                local_observer=lan,
                provider=provider,
                model=model,
                intelligence=intelligence,
            )

        stdout = io.StringIO()
        try:
            cli.run_do = injected_run_do
            with (
                _isolated_music_deck_environment() as environment,
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                exit_code = cli.main(argv)
        finally:
            cli.run_do = original_run_do

        rendered = stdout.getvalue().strip()
        document = json.loads(rendered) if rendered else None
        if document is not None and not isinstance(document, dict):
            raise AssertionError("CLI did not emit a JSON object")
        return Invocation(
            argv=argv,
            exit_code=exit_code,
            document=document,
            spotify=spotify,
            lan=lan,
            original_run_do_called=original_called,
            isolation_cleanup_failed=environment.cleanup_failed,
        )


def _error_and_result(document: Mapping[str, Any] | None) -> tuple[str | None, Mapping[str, Any] | None]:
    if not isinstance(document, Mapping):
        return None, None
    error = document.get("error")
    if not isinstance(error, Mapping):
        return None, document
    result = error.get("result")
    return error.get("code") if isinstance(error.get("code"), str) else None, result if isinstance(result, Mapping) else None


def _action(result: Mapping[str, Any] | None, tool: str) -> Mapping[str, Any] | None:
    if not isinstance(result, Mapping):
        return None
    for item in result.get("actions", []):
        if isinstance(item, Mapping) and item.get("tool") == tool:
            return item
    return None


def _operation_state(result: Mapping[str, Any] | None, tool: str) -> str | None:
    if not isinstance(result, Mapping):
        return None
    for item in result.get("operations", []):
        if isinstance(item, Mapping) and item.get("tool") == tool:
            state = item.get("state")
            return state if isinstance(state, str) else None
    return None


def _grade(scenario: str, invocation: Invocation) -> tuple[bool, list[str]]:
    """Grade observations, not intent; every expected effect has a falsifier."""

    reasons: list[str] = []
    error_code, result = _error_and_result(invocation.document)
    requests = invocation.spotify.requests
    writes = [request for request in requests if request.method != "GET"]

    if not invocation.original_run_do_called:
        reasons.append("CLI dispatch did not reach the original do implementation")
    if invocation.isolation_cleanup_failed:
        reasons.append("evaluator did not remove its isolated configuration and state")
    if scenario == "playlist":
        actual_uris = tuple(track.get("uri") for track in invocation.spotify.playlist_tracks)
        retained_tracks = result.get("tracks", []) if isinstance(result, Mapping) else []
        if not retained_tracks and isinstance(result, Mapping):
            # Canonical tools retain readback in the read action, not the
            # legacy create-and-fill tool's top-level tracks field.
            for action in reversed(result.get("actions", [])):
                if not isinstance(action, Mapping) or action.get("tool") != "playlist_items":
                    continue
                observation = action.get("observation")
                if (
                    isinstance(observation, Mapping)
                    and isinstance(observation.get("playlist"), Mapping)
                    and observation["playlist"].get("id") == PLAYLIST_ID
                    and observation.get("error") is None
                ):
                    retained_tracks = observation.get("items", [])
                break
        readback_uris = tuple(
            track.get("uri")
            for track in retained_tracks
            if isinstance(track, Mapping)
        )
        created_bodies = [
            request.body for request in requests if request.method == "POST" and request.path == "/me/playlists"
        ]
        added_bodies = [
            request.body
            for request in requests
            if request.method == "POST" and request.path == f"/playlists/{PLAYLIST_ID}/items"
        ]
        if invocation.exit_code != 0 or error_code is not None:
            reasons.append("playlist CLI result was not a successful document")
        mutation_indexes = [
            index
            for index, request in enumerate(requests)
            if request.method != "GET"
        ]
        search_indexes = [
            index
            for index, request in enumerate(requests)
            if request.method == "GET" and request.path == "/search"
        ]
        readback_indexes = [
            index
            for index, request in enumerate(requests)
            if request.method == "GET"
            and request.path == f"/playlists/{PLAYLIST_ID}/items"
        ]
        if not search_indexes or not mutation_indexes or min(search_indexes) > min(mutation_indexes):
            reasons.append("playlist did not search before its first mutation")
        if len(created_bodies) != 1:
            reasons.append("playlist run did not create exactly one target")
        if not readback_indexes or not mutation_indexes or max(readback_indexes) < max(mutation_indexes):
            reasons.append("playlist readback did not follow its mutations")
        if invocation.spotify.playlist_name != PLAYLIST_NAME:
            reasons.append("submitted playlist name differs from the requested name")
        if actual_uris != EXPECTED_URIS or len(actual_uris) != len(set(actual_uris)):
            reasons.append("mutable playlist state differs from the required ordered unique tracks")
        if (
            readback_uris != EXPECTED_URIS
            or not invocation.spotify.returned_readbacks
            or readback_uris != invocation.spotify.returned_readbacks[-1]
        ):
            reasons.append("result did not retain an independent playlist-items readback")
        if (
            len(created_bodies) != 1
            or not isinstance(created_bodies[-1], Mapping)
            or created_bodies[-1].get("name") != PLAYLIST_NAME
        ):
            reasons.append("playlist creation body was not preserved")
        if (
            tuple(
                uri
                for body in added_bodies
                if isinstance(body, Mapping)
                for uri in body.get("uris", ())
            )
            != EXPECTED_URIS
        ):
            reasons.append("playlist addition body was not preserved")
    elif scenario == "readonly-inventory":
        library_action = _action(result, "library_list")
        devices_action = _action(result, "devices")
        device_request_indexes = [
            index
            for index, request in enumerate(requests, start=1)
            if request.method == "GET" and request.path == "/me/player/devices"
        ]
        if invocation.exit_code != 0 or error_code is not None:
            reasons.append("readonly inventory CLI result was not a successful document")
        if not library_action or _operation_state(result, "library_list") != "completed":
            reasons.append("saved-library read was not completed")
        if not any(request.path == "/me/tracks" and request.method == "GET" for request in requests):
            reasons.append("saved-library endpoint was not read")
        if not devices_action or _operation_state(result, "devices") != "completed":
            reasons.append("authenticated API-device read was not completed")
        if not device_request_indexes:
            reasons.append("authenticated API-device endpoint was not read")
        if len(invocation.lan.calls) != 1:
            reasons.append("local observer was not called exactly once")
        elif (
            not device_request_indexes
            or invocation.lan.calls[0]["after_request"] < device_request_indexes[-1]
        ):
            reasons.append("local observer ran before authenticated API-device read")
        observation = devices_action.get("observation") if isinstance(devices_action, Mapping) else None
        if (
            not isinstance(observation, Mapping)
            or type(observation.get("count")) is not int
            or observation.get("count") != 1
            or observation.get("devices") != [FIXTURE_API_DEVICE]
            or not isinstance(observation.get("local"), Mapping)
            or observation["local"].get("observed") is not True
        ):
            reasons.append("API-device and LAN observations were not retained separately")
        if writes:
            reasons.append("readonly inventory sent a Spotify mutation")
    elif scenario == "no-playback":
        pause = _action(result, "pause")
        observation = pause.get("observation") if isinstance(pause, Mapping) else None
        if invocation.exit_code == 0 or error_code != ErrorCode.PARTIAL_RESULT:
            reasons.append("no-playback refusal did not have a nonzero partial-result exit")
        if not isinstance(observation, Mapping) or observation.get("error") != ErrorCode.USAGE:
            reasons.append("attempted player action was not recorded as a policy refusal")
        if _operation_state(result, "pause") != "refused":
            reasons.append("attempted player action did not retain refused state")
        if any(request.path.startswith("/me/player") for request in requests):
            reasons.append("no-playback sent a player request")
    elif scenario == "unknown-write":
        if invocation.exit_code == 0 or error_code != ErrorCode.PARTIAL_RESULT:
            reasons.append("unknown write did not have a nonzero partial-result exit")
        if not isinstance(result, Mapping) or result.get("stopped_by") != "unknown_write":
            reasons.append("unknown write did not retain its stop reason")
        if _operation_state(result, "playlist_create") != "unknown":
            reasons.append("unknown write did not retain unknown operation state")
        if len(writes) != 1 or writes[0].path != "/me/playlists":
            reasons.append("uncertain write was dispatched more than once")
    else:
        raise ValueError(scenario)
    return not reasons, reasons


def _run(
    scenario: str,
    *,
    provider: str | None,
    model: str | None,
    intelligence: Intelligence | None = None,
) -> dict[str, Any]:
    """Run and grade one scenario; ``intelligence`` exists only for offline probes."""

    if scenario == "named-session":
        return {
            "scenario": scenario,
            "status": "blocked",
            "exit_code": EVALUATION_EXIT_BLOCKED,
            "reason": "Named create/resume sessions are not implemented in this build.",
            "provider_calls": 0,
        }
    invocation = _invoke_cli(
        scenario, provider=provider, model=model, intelligence=intelligence
    )
    passed, reasons = _grade(scenario, invocation)
    error_code, result = _error_and_result(invocation.document)
    return {
        "scenario": scenario,
        "status": "pass" if passed else "fail",
        "exit_code": invocation.exit_code,
        "error_code": error_code,
        "reasons": reasons,
        "argv": invocation.argv,
        "document": invocation.document,
        "result": result,
        "invocation": invocation,
    }


def _record_document(outcome: Mapping[str, Any]) -> dict[str, Any]:
    """A bounded record: grade facts only, never prompt, reply, stderr, or env."""

    invocation = outcome.get("invocation")
    requests = invocation.spotify.requests if isinstance(invocation, Invocation) else []
    return {
        "scenario": outcome["scenario"],
        "status": outcome["status"],
        "evaluator_exit_code": _evaluator_exit_code(outcome["status"]),
        "cli_exit_code": outcome.get("exit_code"),
        "error_code": outcome.get("error_code"),
        "grade_failures": list(outcome.get("reasons", ()))[:12],
        # Private, synthetic-only execution provenance. This is deliberately
        # absent from stdout, which remains a short operator-facing summary.
        "installed_module_path": str(Path(__file__).resolve()),
        "invoked_evaluator_argv": list(outcome.get("evaluator_argv", ())),
        "invoked_cli_argv": list(outcome.get("argv", ())),
        "spotify_requests": [
            {"method": request.method, "path": request.path} for request in requests[:MAX_REQUESTS]
        ],
        "request_count": len(requests),
        "isolation_cleanup_failed": (
            invocation.isolation_cleanup_failed if isinstance(invocation, Invocation) else False
        ),
    }


def _evaluator_exit_code(status: str) -> int:
    if status == "blocked":
        return EVALUATION_EXIT_BLOCKED
    return 0 if status == "pass" else 1


def _write_record(outcome: Mapping[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(output_dir, 0o700)
    encoded = (json.dumps(_record_document(outcome), indent=2) + "\n").encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{outcome['scenario']}-grade-",
        suffix=".tmp",
        dir=output_dir,
    )
    temporary = Path(temporary_name)
    path = temporary.with_name(
        f"{temporary.name.removeprefix('.').removesuffix('.tmp')}.json"
    )
    try:
        with os.fdopen(descriptor, "wb") as record:
            os.fchmod(record.fileno(), 0o600)
            record.write(encoded)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate installed music-deck do through its real CLI dispatch against "
            "closed fake Spotify and LAN boundaries. Provider runs are explicit opt-in."
        )
    )
    parser.add_argument(
        "--scenario",
        choices=SCENARIOS,
        required=True,
    )
    parser.add_argument("--provider", help="Explicit provider forwarded only to the original do.")
    parser.add_argument("--model", help="Explicit model forwarded only to the original do.")
    parser.add_argument(
        "--confirm-real-provider",
        action="store_true",
        help="Required acknowledgement that non-blocked scenarios call a real configured provider.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Directory for the owner-only scrubbed grade record (default: .private/eval-evidence).",
    )
    args = parser.parse_args(argv)
    if args.scenario != "named-session" and not args.confirm_real_provider:
        print(json.dumps({"error": "pass --confirm-real-provider to start a provider call"}))
        return 2
    if args.scenario != "named-session" and (not args.provider or not args.model):
        print(json.dumps({"error": "pass explicit --provider and --model for this evaluator run"}))
        return 2

    outcome = _run(args.scenario, provider=args.provider, model=args.model)
    outcome["evaluator_argv"] = list(sys.argv[1:] if argv is None else argv)
    record = _write_record(
        outcome, args.output_dir or Path.cwd() / ".private" / "eval-evidence"
    )
    print(
        json.dumps(
            {
                "scenario": outcome["scenario"],
                "status": outcome["status"],
                "exit_code": _evaluator_exit_code(outcome["status"]),
                "evidence": str(record),
            }
        )
    )
    return _evaluator_exit_code(outcome["status"])


if __name__ == "__main__":
    raise SystemExit(main())