"""`disconnect` -- boundary.v1 Core 6, and the reason it exists.

Verbatim: "``disconnect`` deletes the token and every locally cached byte of
Spotify content, and reports what it deleted (Developer Terms section V's
disconnect mechanism). ``check`` reports the auth facts and exits 0 always -- it
never fails just because the account is not connected."

Two halves, and the second is the one that is easy to fake: a verb that deletes
the token and *says* it cleaned up is not the promise. So these tests check the
directory afterwards, not the report -- and then check that the report named
what the directory lost.
"""

from __future__ import annotations

import json

import pytest
from spotify_fakes import (
    FakeTransport,
    install_token,
    json_response,
    run_cli,
    run_probe,
    spotify_error,
    token_document,
    use_fake_transport,
)

from music_deck.check import check
from music_deck.errors import EXIT_REFUSAL, EXIT_SUCCESS, ErrorCode
from music_deck.verbs.auth_verbs import disconnect, spotify_client


@pytest.fixture
def signed_in(monkeypatch, tmp_path):
    """A signed-in install with a token and some cached crumbs beside it."""
    token = install_token(monkeypatch, tmp_path, token_document())
    state = tmp_path / "state"
    (state / "cache").mkdir(parents=True, exist_ok=True)
    (state / "cache" / "playlist-37i9dQZF1DXcBWIGoYBM5M.json").write_text(
        json.dumps({"name": "Today's Top Hits", "items": [{"uri": "spotify:track:x"}]}),
        encoding="utf-8",
    )
    (state / "last-403.json").write_text(
        json.dumps({"observed_at": "2026-09-04T00:00:00+00:00", "endpoint": "/me"}),
        encoding="utf-8",
    )
    return token


def remaining_files(tmp_path) -> list[str]:
    state = tmp_path / "state"
    if not state.exists():
        return []
    return sorted(str(path.relative_to(state)) for path in state.rglob("*") if path.is_file())


# --------------------------------------------------------------------------- #
# It deletes
# --------------------------------------------------------------------------- #
def test_disconnect_leaves_no_spotify_content_on_disk(signed_in, tmp_path, capsys):
    assert remaining_files(tmp_path), "the fixture must start with something to delete"

    code, document, _ = run_cli(capsys, "disconnect")

    assert code == EXIT_SUCCESS
    assert not signed_in.exists(), "the token survived a disconnect"
    assert remaining_files(tmp_path) == [], "Spotify content survived a disconnect"
    assert document["remaining"] == []


def test_disconnect_names_every_file_it_deleted(signed_in, tmp_path, capsys):
    """"and reports what it deleted" -- the report is checkable, not a summary."""
    before = {
        str(path) for path in (tmp_path / "state").rglob("*") if path.is_file()
    }

    code, document, _ = run_cli(capsys, "disconnect")

    assert code == EXIT_SUCCESS
    assert set(document["deleted"]) == before
    assert document["deleted_count"] == len(before)
    assert str(signed_in) in document["deleted"]
    assert any("cache" in path for path in document["deleted"])


def test_disconnect_deletes_the_403_record_a_real_run_leaves_behind(
    monkeypatch, tmp_path, capsys
):
    """End to end: a refused request writes the allowlist signal, and disconnect
    takes it away again -- so nothing music-deck wrote outlives the disconnect."""
    install_token(monkeypatch, tmp_path, token_document())
    use_fake_transport(
        monkeypatch, FakeTransport([json_response(403, spotify_error(403, "Forbidden"))])
    )

    refused, _, _ = run_probe(
        monkeypatch, capsys, lambda: spotify_client().get("/albums/4aawyAB9vmqN3uQ7FjRGTy")
    )
    assert refused == EXIT_REFUSAL
    assert (tmp_path / "state" / "last-403.json").exists()

    code, document, _ = run_cli(capsys, "disconnect")

    assert code == EXIT_SUCCESS
    assert not (tmp_path / "state" / "last-403.json").exists()
    assert any("last-403.json" in path for path in document["deleted"])


# --------------------------------------------------------------------------- #
# It leaves alone what is not Spotify's
# --------------------------------------------------------------------------- #
def test_disconnect_keeps_the_config_file(signed_in, tmp_path, capsys):
    """The client ID is the caller's own, is not Spotify content, and is what
    they would have to go and find again. Deleting it would be a surprise."""
    config = tmp_path / "config" / "config.json"
    config.write_text(json.dumps({"client_id": "client-id-under-test"}), encoding="utf-8")

    code, document, _ = run_cli(capsys, "disconnect")

    assert code == EXIT_SUCCESS
    assert config.exists()
    assert "config file was left in place" in document["note"]


# --------------------------------------------------------------------------- #
# What the world looks like afterwards
# --------------------------------------------------------------------------- #
def test_after_disconnect_every_verb_refuses_not_authenticated(
    signed_in, capsys, monkeypatch
):
    transport = use_fake_transport(monkeypatch, FakeTransport())
    run_cli(capsys, "disconnect")

    code, document, _ = run_cli(capsys, "whoami")

    assert code == EXIT_REFUSAL
    assert document["error"]["code"] == ErrorCode.NOT_AUTHENTICATED
    assert "music-deck login" in document["error"]["remedy"]
    assert transport.requests == []


def test_after_disconnect_check_still_exits_zero_and_says_so(signed_in, capsys):
    """boundary.v1 Core 6's second sentence: `check` never fails just because the
    account is not connected."""
    run_cli(capsys, "disconnect")

    code, report, _ = run_cli(capsys, "check")

    assert code == EXIT_SUCCESS
    assert report["token_file"]["present"] is False
    assert any("Not signed in" in finding for finding in report["findings"])
    assert report["ready"]["spotify_verbs"] is False


def test_disconnect_is_safe_to_run_twice(signed_in, tmp_path, capsys):
    first, _, _ = run_cli(capsys, "disconnect")
    second, document, _ = run_cli(capsys, "disconnect")

    assert (first, second) == (EXIT_SUCCESS, EXIT_SUCCESS)
    assert document["deleted"] == []
    assert "Nothing to delete" in document["summary"]


def test_disconnect_with_nothing_stored_is_a_report_not_a_refusal(monkeypatch, tmp_path):
    install_token(monkeypatch, tmp_path, None)

    result = disconnect()

    assert result["disconnected"] is True
    assert result["deleted"] == []
    assert result["remaining"] == []


def test_check_and_disconnect_agree_on_where_things_live(monkeypatch, tmp_path):
    """One state directory, named the same way by both verbs -- otherwise
    "everything was deleted" and "nothing is left" could both be true of
    different directories."""
    install_token(monkeypatch, tmp_path, token_document())

    report = check()
    result = disconnect()

    assert result["state_dir"] == report["state_dir"]
    assert result["token_path"] == report["token_file"]["path"]
