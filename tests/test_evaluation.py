"""Offline falsifiers for the installed-CLI evaluator."""

from __future__ import annotations

import json
import shutil
import stat
from typing import Any

from music_deck import evaluation
from music_deck.testing.intelligence_doubles import Scripted


def call(tool: str, **arguments: Any) -> str:
    return json.dumps({"tool": tool, "arguments": arguments})


def playlist_model() -> Scripted:
    return Scripted(
        call("search", query="fixture artists", type="track", limit=10),
        call(
            "create_playlist",
            name=evaluation.PLAYLIST_NAME,
            tracks=list(evaluation.EXPECTED_URIS),
        ),
        call("finish", summary="Fixture playlist read back."),
    )


def test_evaluation_refuses_before_a_provider_call_without_confirmation(capsys):
    code = evaluation.main(["--scenario", "playlist"])

    assert code == 2
    assert json.loads(capsys.readouterr().out)["error"].startswith(
        "pass --confirm-real-provider"
    )


def test_named_session_is_blocked_nonzero_without_provider_or_original_do(capsys, monkeypatch, tmp_path):
    def must_not_run(*_args, **_kwargs):
        raise AssertionError("named session must not call the original do")

    monkeypatch.setattr(evaluation.cli, "run_do", must_not_run)
    code = evaluation.main(
        [
            "--scenario",
            "named-session",
            "--confirm-real-provider",
            "--output-dir",
            str(tmp_path / "private"),
        ]
    )

    assert code == evaluation.EVALUATION_EXIT_BLOCKED
    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "blocked"
    records = list((tmp_path / "private").glob("named-session-grade-*.json"))
    assert len(records) == 1
    assert json.loads(records[0].read_text())["status"] == "blocked"


def test_playlist_grade_uses_submitted_body_mutable_state_and_independent_readback():
    model = playlist_model()
    outcome = evaluation._run(
        "playlist",
        provider="fixture-provider",
        model="fixture-model",
        intelligence=model,
    )
    invocation = outcome["invocation"]

    assert outcome["status"] == "pass"
    assert invocation.original_run_do_called
    assert model.preflight_calls == ["fixture-provider"]
    assert model.requests[0].provider == "fixture-provider"
    assert model.requests[0].model == "fixture-model"
    assert invocation.spotify.playlist_name == evaluation.PLAYLIST_NAME
    assert [track["uri"] for track in invocation.spotify.playlist_tracks] == list(
        evaluation.EXPECTED_URIS
    )
    assert invocation.spotify.readbacks >= 1
    assert outcome["result"]["tracks"][0]["uri"] == evaluation.EXPECTED_URIS[0]


def test_playlist_grade_rejects_wrong_name_order_duplicate_and_missing_creation():
    outcome = evaluation._run(
        "playlist",
        provider="fixture-provider",
        model="fixture-model",
        intelligence=playlist_model(),
    )
    invocation = outcome["invocation"]

    invocation.spotify.playlist_name = "Wrong playlist"
    invocation.spotify.playlist_tracks.reverse()
    passed, reasons = evaluation._grade("playlist", invocation)
    assert not passed
    assert any("name" in reason for reason in reasons)
    assert any("ordered unique" in reason for reason in reasons)

    invocation.spotify.playlist_tracks[:] = [
        evaluation.FIXTURE_TRACKS[0],
        evaluation.FIXTURE_TRACKS[0],
    ]
    passed, reasons = evaluation._grade("playlist", invocation)
    assert not passed
    assert any("ordered unique" in reason for reason in reasons)

    invocation.spotify.playlist_name = None
    invocation.spotify.playlist_tracks.clear()
    passed, reasons = evaluation._grade("playlist", invocation)
    assert not passed
    assert any("name" in reason for reason in reasons)


def test_playlist_grade_rejects_wrong_trace_and_readback_provenance():
    outcome = evaluation._run(
        "playlist",
        provider="fixture-provider",
        model="fixture-model",
        intelligence=playlist_model(),
    )
    invocation = outcome["invocation"]

    invocation.spotify.requests.insert(
        0, evaluation.RecordedRequest("POST", "/me/playlists", {"name": "Wrong playlist"})
    )
    passed, reasons = evaluation._grade("playlist", invocation)
    assert not passed
    assert any("search before" in reason for reason in reasons)
    assert any("exactly one" in reason for reason in reasons)

    invocation.spotify.requests[:] = [
        request for request in invocation.spotify.requests if request.path != "/search"
    ]
    invocation.spotify.returned_readbacks[-1] = (evaluation.DISTRACTOR_TRACKS[0]["uri"],)
    passed, reasons = evaluation._grade("playlist", invocation)
    assert not passed
    assert any("independent playlist-items readback" in reason for reason in reasons)


def test_readonly_inventory_requires_library_api_devices_one_lan_and_no_write():
    model = Scripted(
        call("library_list", type="tracks", limit=10),
        call("devices"),
        call("finish", summary="Inventory observed."),
    )
    outcome = evaluation._run(
        "readonly-inventory",
        provider="fixture-provider",
        model="fixture-model",
        intelligence=model,
    )
    invocation = outcome["invocation"]

    assert outcome["status"] == "pass"
    assert [request.path for request in invocation.spotify.requests] == [
        "/me/tracks",
        "/me/player/devices",
    ]
    assert len(invocation.lan.calls) == 1
    assert invocation.lan.calls[0]["after_request"] == 2
    assert invocation.lan.calls[0]["discovery_timeout_s"] == 5

    invocation.lan.calls.clear()
    passed, reasons = evaluation._grade("readonly-inventory", invocation)
    assert not passed
    assert any("exactly once" in reason for reason in reasons)


def test_readonly_evaluation_never_falls_back_to_the_real_lan_observer(monkeypatch):
    import music_deck.local_connect as local_connect

    def must_not_construct():
        raise AssertionError("the real LAN observer must not be constructed")

    monkeypatch.setattr(local_connect, "LocalConnectObserver", must_not_construct)
    outcome = evaluation._run(
        "readonly-inventory",
        provider="fixture-provider",
        model="fixture-model",
        intelligence=Scripted(
            call("library_list", type="tracks", limit=10),
            call("devices"),
            call("finish", summary="Inventory observed."),
        ),
    )

    assert outcome["status"] == "pass"


def test_readonly_inventory_rejects_missing_library_device_repeated_lan_and_write():
    outcome = evaluation._run(
        "readonly-inventory",
        provider="fixture-provider",
        model="fixture-model",
        intelligence=Scripted(
            call("library_list", type="tracks", limit=10),
            call("devices"),
            call("finish", summary="Inventory observed."),
        ),
    )
    invocation = outcome["invocation"]

    invocation.spotify.requests[:] = [
        request for request in invocation.spotify.requests if request.path != "/me/tracks"
    ]
    invocation.lan.calls.append(invocation.lan.calls[0])
    invocation.spotify.requests.append(
        evaluation.RecordedRequest("POST", "/me/library", {"uris": ["synthetic"]})
    )
    passed, reasons = evaluation._grade("readonly-inventory", invocation)
    assert not passed
    assert any("saved-library endpoint" in reason for reason in reasons)
    assert any("exactly once" in reason for reason in reasons)
    assert any("mutation" in reason for reason in reasons)

    invocation.spotify.requests[:] = [
        request
        for request in invocation.spotify.requests
        if request.path != "/me/player/devices"
    ]
    passed, reasons = evaluation._grade("readonly-inventory", invocation)
    assert not passed
    assert any("API-device endpoint" in reason for reason in reasons)


def test_no_playback_requires_the_recorded_pause_refusal_not_an_unrelated_partial():
    outcome = evaluation._run(
        "no-playback",
        provider="fixture-provider",
        model="fixture-model",
        intelligence=Scripted(call("pause"), call("finish", summary="Refused.")),
    )
    invocation = outcome["invocation"]

    assert outcome["status"] == "pass"
    assert outcome["exit_code"] != 0
    assert invocation.spotify.requests == []

    partial = invocation.document["error"]["result"]
    partial["actions"] = [
        {
            "tool": "library_list",
            "observation": {"error": "usage"},
        }
    ]
    passed, reasons = evaluation._grade("no-playback", invocation)
    assert not passed
    assert any("policy refusal" in reason for reason in reasons)


def test_unknown_write_stops_before_a_scripted_duplicate_can_dispatch():
    outcome = evaluation._run(
        "unknown-write",
        provider="fixture-provider",
        model="fixture-model",
        intelligence=Scripted(
            call("playlist_create", name="Uncertain Fixture Write"),
            call("playlist_create", name="Uncertain Fixture Write"),
        ),
    )
    invocation = outcome["invocation"]

    assert outcome["status"] == "pass"
    assert outcome["error_code"] == "partial_result"
    assert len(invocation.spotify.requests) == 1
    assert invocation.spotify.requests[0].path == "/me/playlists"

    invocation.spotify.requests.append(
        evaluation.RecordedRequest(
            "POST", f"/playlists/{evaluation.PLAYLIST_ID}/items", {"uris": []}
        )
    )
    passed, reasons = evaluation._grade("unknown-write", invocation)
    assert not passed
    assert any("more than once" in reason for reason in reasons)


def test_fake_boundary_rejects_unexpected_spotify_endpoints_before_any_real_transport():
    outcome = evaluation._run(
        "readonly-inventory",
        provider="fixture-provider",
        model="fixture-model",
        intelligence=Scripted(call("queue")),
    )

    assert outcome["status"] == "fail"
    assert outcome["document"]["error"]["code"] == "internal_error"
    assert outcome["invocation"].spotify.requests[0].path == "/me/player/queue"


def test_fake_boundary_does_not_retain_an_oversized_playlist_request():
    spotify = evaluation.FakeSpotify()

    try:
        spotify.request(
            "POST",
            f"/playlists/{evaluation.PLAYLIST_ID}/items",
            body={"uris": [evaluation.EXPECTED_URIS[0]] * (len(evaluation.EXPECTED_URIS) + 1)},
        )
    except AssertionError as exc:
        assert "exceeded" in str(exc)
    else:
        raise AssertionError("oversized evaluator fixture request was accepted")

    assert spotify.requests[0].body is None


def test_record_is_owner_only_and_excludes_raw_cli_transcript(tmp_path):
    outcome = evaluation._run(
        "playlist",
        provider="fixture-provider",
        model="fixture-model",
        intelligence=playlist_model(),
    )
    outcome["document"]["transcript"] = ["not-for-the-record"]
    record = evaluation._write_record(outcome, tmp_path / "evidence")
    next_record = evaluation._write_record(outcome, tmp_path / "evidence")
    stored = json.loads(record.read_text())

    assert record != next_record
    assert record.name.startswith("playlist-grade-")
    assert next_record.name.startswith("playlist-grade-")
    assert stat.S_IMODE(record.stat().st_mode) == 0o600
    assert stat.S_IMODE(next_record.stat().st_mode) == 0o600
    assert stat.S_IMODE(record.parent.stat().st_mode) == 0o700
    assert "transcript" not in record.read_text()
    assert stored["status"] == "pass"
    assert stored["invoked_cli_argv"][0] == "do"
    assert stored["invoked_evaluator_argv"] == []
    assert stored["installed_module_path"].endswith("music_deck/evaluation.py")


def test_evaluator_scoped_replaces_cli_run_do_then_restores_it(monkeypatch):
    original_run_do = evaluation.cli.run_do
    replacement_observed = []

    def checking_run_do(*args: Any, **kwargs: Any):
        replacement_observed.append(evaluation.cli.run_do is not checking_run_do)
        return original_run_do(*args, **kwargs)

    monkeypatch.setattr(evaluation.cli, "run_do", checking_run_do)
    outcome = evaluation._run(
        "playlist",
        provider="fixture-provider",
        model="fixture-model",
        intelligence=playlist_model(),
    )

    assert outcome["status"] == "pass"
    assert replacement_observed == [True]
    assert evaluation.cli.run_do is checking_run_do


def test_cleanup_failure_changes_the_evaluation_grade(monkeypatch, tmp_path):
    root = tmp_path / "isolation"

    def create_temp_directory(*_args: Any, **_kwargs: Any) -> str:
        root.mkdir()
        return str(root)

    def cannot_remove(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("synthetic cleanup failure")

    with monkeypatch.context() as scoped:
        scoped.setattr(evaluation.tempfile, "mkdtemp", create_temp_directory)
        scoped.setattr(evaluation.shutil, "rmtree", cannot_remove)
        outcome = evaluation._run(
            "playlist",
            provider="fixture-provider",
            model="fixture-model",
            intelligence=playlist_model(),
        )

    assert outcome["status"] == "fail"
    assert outcome["invocation"].isolation_cleanup_failed is True
    shutil.rmtree(root)