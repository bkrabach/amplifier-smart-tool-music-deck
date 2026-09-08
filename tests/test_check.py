"""`check` reports the facts, never fails, and never touches the network.

Contracts served: ``boundary.v1`` Core 6 ("`check` reports the auth facts and
exits 0 always -- it never fails just because the account is not connected") and
``cli.v1`` Core 2 ("`check` additionally succeeds (exit 0) with no credentials
and no network, in a fresh working directory").

The hardest of those to assert honestly is "no network", so it is asserted
directly: sockets are replaced with something that raises, and `check` is run.
A version of `check` that reached for Spotify would fail this test loudly rather
than passing quietly because the machine happened to be offline.
"""

from __future__ import annotations

import json
import os
import socket
import stat
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from music_deck.check import (
    DEFAULT_REDIRECT_PORT,
    DEFAULT_REDIRECT_URI,
    REFRESH_TOKEN_WALL_DAYS,
    check,
    config_dir,
    redirect_uri_parts,
    redirect_uri_shape,
    resolve_redirect_uri,
    state_dir,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FACTS = (
    "client_id",
    "redirect_uri",
    "token_file",
    "access_token",
    "refresh_token",
    "scopes",
    "allowlist",
    "provider",
    "model_runtime",
)

_MODEL_ENV = (
    "MUSIC_DECK_PROVIDER",
    "MUSIC_DECK_MODEL",
    "MUSIC_DECK_ENDPOINT",
    "MUSIC_DECK_BASE_URL",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "AZURE_OPENAI_API_KEY",
)


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """A fresh, empty config and state directory -- nothing carried in."""
    config = tmp_path / "config"
    state = tmp_path / "state"
    config.mkdir()
    state.mkdir()
    monkeypatch.setenv("MUSIC_DECK_CONFIG_DIR", str(config))
    monkeypatch.setenv("MUSIC_DECK_STATE_DIR", str(state))
    for name in ("MUSIC_DECK_CLIENT_ID", "MUSIC_DECK_REDIRECT_URI", *_MODEL_ENV):
        monkeypatch.delenv(name, raising=False)
    return config, state


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def _write_token(state, **fields):
    path = state / "token.json"
    path.write_text(json.dumps(fields), encoding="utf-8")
    path.chmod(0o600)
    return path


# --------------------------------------------------------------------------- #
# The promise: it reports, it never fails
# --------------------------------------------------------------------------- #
def test_reports_every_fact_the_contract_names(isolated):
    result = check()
    for fact in REQUIRED_FACTS:
        assert fact in result, f"check did not report {fact}"
    assert isinstance(result["findings"], list)


def test_a_completely_unconfigured_machine_is_a_successful_report(isolated):
    """boundary.v1 Core 6: reporting a missing credential is success, not failure."""
    result = check()
    assert result["client_id"]["present"] is False
    assert result["token_file"]["present"] is False
    assert "internal_error" not in result
    assert result["findings"], "an unconfigured machine should produce findings"


def test_check_makes_no_network_call(isolated, monkeypatch):
    """cli.v1 Core 2: `check` succeeds with no network."""

    def refuse(*args, **kwargs):
        raise AssertionError("check attempted a network call")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    result = check()
    assert result["tool"] == "music-deck"


def test_check_runtime_inspection_imports_no_sdk_or_engine(tmp_path):
    """The complete readiness report remains local and lazy on a bare install."""
    probe = (
        "import json, socket, sys;"
        "socket.socket = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('network'));"
        "from music_deck.check import check;"
        "check();"
        "print(json.dumps(sorted(m for m in sys.modules if m.split('.')[0] in "
        "{'anthropic','openai','google','amplifier_agent'})))"
    )
    env = {
        name: value
        for name, value in os.environ.items()
        if name
        not in {
            "MUSIC_DECK_PROVIDER",
            "MUSIC_DECK_MODEL",
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "GOOGLE_API_KEY",
            "GEMINI_API_KEY",
            "AZURE_OPENAI_API_KEY",
        }
    }

    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []


def test_check_never_raises_on_unreadable_files(isolated):
    """Garbage on disk is a fact to report, not an exception to propagate."""
    config, state = isolated
    (config / "config.json").write_text("{not json at all", encoding="utf-8")
    (state / "token.json").write_text("[]", encoding="utf-8")
    result = check()
    assert "internal_error" not in result
    joined = " ".join(result["findings"])
    assert "config.json" in joined
    assert "token.json" in joined


def test_check_never_raises_when_directories_do_not_exist(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSIC_DECK_CONFIG_DIR", str(tmp_path / "nope" / "config"))
    monkeypatch.setenv("MUSIC_DECK_STATE_DIR", str(tmp_path / "nope" / "state"))
    result = check()
    assert "internal_error" not in result
    assert result["token_file"]["present"] is False


# --------------------------------------------------------------------------- #
# The individual facts
# --------------------------------------------------------------------------- #
def test_client_id_is_read_from_the_environment(isolated, monkeypatch):
    monkeypatch.setenv("MUSIC_DECK_CLIENT_ID", "abc123")
    fact = check()["client_id"]
    assert fact["present"] is True
    assert "MUSIC_DECK_CLIENT_ID" in fact["source"]


def test_client_id_is_read_from_the_config_file(isolated):
    config, _state = isolated
    (config / "config.json").write_text(json.dumps({"client_id": "abc"}), encoding="utf-8")
    fact = check()["client_id"]
    assert fact["present"] is True
    assert "config file" in fact["source"]


def test_the_client_id_value_is_never_echoed(isolated, monkeypatch):
    """A credential belongs in the token file, not in a diagnostic report."""
    monkeypatch.setenv("MUSIC_DECK_CLIENT_ID", "s3cr3t-client-id")
    assert "s3cr3t-client-id" not in json.dumps(check())


@pytest.mark.parametrize(
    "value, conforms",
    [
        ("http://127.0.0.1:8888", True),
        ("http://127.0.0.1:8080", True),
        ("http://[::1]:8080", True),
        # No port: what Spotify's documentation describes and its dashboard
        # refused on 2026-09-06. boundary.v1 Core 4 now requires the port.
        ("http://127.0.0.1", False),
        ("http://[::1]", False),
        ("http://localhost:8080", False),
        ("https://example.com/callback", False),
        ("http://192.168.0.4:8080", False),
        ("http://127.0.0.1:not-a-port", False),
        ("http://127.0.0.1:99999", False),
    ],
)
def test_redirect_uri_shape_follows_boundary_core_4(value, conforms):
    """boundary.v1 Core 4: a loopback IP literal on a fixed, registered port."""
    assert redirect_uri_shape(value)[0] is conforms


def test_the_default_redirect_uri_conforms_and_carries_the_registered_port():
    assert redirect_uri_shape(DEFAULT_REDIRECT_URI)[0] is True
    assert DEFAULT_REDIRECT_URI == f"http://127.0.0.1:{DEFAULT_REDIRECT_PORT}"
    assert redirect_uri_parts(DEFAULT_REDIRECT_URI) == ("127.0.0.1", 8888)


def test_a_nonconforming_redirect_uri_becomes_a_finding(isolated, monkeypatch):
    monkeypatch.setenv("MUSIC_DECK_REDIRECT_URI", "http://localhost:8080")
    result = check()
    assert result["redirect_uri"]["conforms"] is False
    assert any("localhost" in finding for finding in result["findings"])


def test_a_portless_loopback_uri_is_refused_and_the_remedy_names_what_to_register(
    isolated, monkeypatch
):
    """The defect the steward caught: Spotify's dashboard refuses a portless
    registration, so reporting one as conforming sends a caller to a form that
    will not accept what they were told to type."""
    monkeypatch.setenv("MUSIC_DECK_REDIRECT_URI", "http://127.0.0.1")
    fact = check()["redirect_uri"]

    assert fact["conforms"] is False
    assert fact["port"] is None
    assert "no usable port" in fact["detail"]
    # Names what to register INSTEAD -- the same host, with a port.
    assert "http://127.0.0.1:8888" in fact["remedy"]


def test_check_reports_the_value_the_resolver_returns_from_every_source(
    isolated, monkeypatch
):
    """boundary.v1 Core 4: one value. `check` never invents its own."""
    config, _state = isolated

    assert check()["redirect_uri"] == {
        **check()["redirect_uri"],
        "value": DEFAULT_REDIRECT_URI,
        "source": "built-in default",
        "port": DEFAULT_REDIRECT_PORT,
        "conforms": True,
    }

    (config / "config.json").write_text(
        json.dumps({"redirect_uri": "http://127.0.0.1:9100"}), encoding="utf-8"
    )
    fact = check()["redirect_uri"]
    assert (fact["value"], fact["port"]) == ("http://127.0.0.1:9100", 9100)
    assert "config file" in fact["source"]

    monkeypatch.setenv("MUSIC_DECK_REDIRECT_URI", "http://127.0.0.1:9200")
    fact = check()["redirect_uri"]
    assert (fact["value"], fact["port"]) == ("http://127.0.0.1:9200", 9200)
    assert fact["source"] == "environment MUSIC_DECK_REDIRECT_URI"
    assert resolve_redirect_uri() == (fact["value"], fact["source"])


def test_a_loose_token_file_mode_is_reported(isolated):
    """boundary.v1 Core 4: the token file is mode 0600."""
    _config, state = isolated
    path = _write_token(state, access_token="x")
    path.chmod(0o644)
    result = check()
    assert result["token_file"]["mode"] == "0644"
    assert result["token_file"]["mode_ok"] is False
    assert any("0600" in finding for finding in result["findings"])
    assert stat.S_IMODE(path.stat().st_mode) == 0o644  # check changed nothing


def test_access_token_expiry_is_reported(isolated):
    _config, state = isolated
    expires = datetime.now(timezone.utc) + timedelta(minutes=30)
    _write_token(state, access_token="x", expires_at=_iso(expires))
    fact = check()["access_token"]
    assert fact["present"] is True
    assert fact["expired"] is False
    assert 0 < fact["seconds_remaining"] <= 1800


def test_an_expired_access_token_is_reported_without_failing(isolated):
    _config, state = isolated
    expires = datetime.now(timezone.utc) - timedelta(minutes=5)
    _write_token(state, access_token="x", expires_at=_iso(expires))
    fact = check()["access_token"]
    assert fact["expired"] is True
    assert fact["seconds_remaining"] < 0


def test_refresh_token_age_is_measured_against_the_six_month_wall(isolated):
    _config, state = isolated
    authorized = datetime.now(timezone.utc) - timedelta(days=10)
    _write_token(state, refresh_token="r", authorized_at=_iso(authorized))
    fact = check()["refresh_token"]
    assert fact["present"] is True
    assert fact["wall_days"] == REFRESH_TOKEN_WALL_DAYS
    assert 9.5 <= fact["age_days"] <= 10.5
    assert fact["past_wall"] is False


def test_a_refresh_token_past_the_wall_is_reported(isolated):
    _config, state = isolated
    authorized = datetime.now(timezone.utc) - timedelta(days=REFRESH_TOKEN_WALL_DAYS + 3)
    _write_token(state, refresh_token="r", authorized_at=_iso(authorized))
    result = check()
    assert result["refresh_token"]["past_wall"] is True
    assert any("six-month wall" in finding for finding in result["findings"])
    assert result["ready"]["spotify_verbs"] is False


@pytest.mark.parametrize(
    "token",
    [
        {},
        {"access_token": "   ", "refresh_token": "  "},
        {
            "access_token": "fixture-access-token",
            "expires_at": _iso(datetime.now(timezone.utc) - timedelta(seconds=1)),
        },
    ],
)
def test_an_unusable_local_token_does_not_make_spotify_verbs_ready(isolated, token):
    """Readiness means the auth layer can produce or refresh a bearer locally."""
    config, state = isolated
    (config / "config.json").write_text(json.dumps({"client_id": "fixture-id"}), encoding="utf-8")
    _write_token(state, **token)

    report = check()

    assert report["token_file"]["present"] is True
    assert report["ready"]["spotify_verbs"] is False


def test_a_fresh_access_token_or_a_refresh_token_makes_spotify_verbs_ready(isolated):
    config, state = isolated
    (config / "config.json").write_text(json.dumps({"client_id": "fixture-id"}), encoding="utf-8")
    _write_token(
        state,
        access_token="fixture-access-token",
        expires_at=_iso(datetime.now(timezone.utc) + timedelta(hours=1)),
    )
    assert check()["ready"]["spotify_verbs"] is True

    _write_token(
        state,
        access_token="fixture-access-token",
        expires_at=_iso(datetime.now(timezone.utc) - timedelta(seconds=1)),
        refresh_token="fixture-refresh-token",
        authorized_at=_iso(datetime.now(timezone.utc)),
    )
    assert check()["ready"]["spotify_verbs"] is True


def test_an_access_token_inside_auths_refresh_skew_is_not_ready_without_refresh(isolated):
    """`check` uses the same safety margin as `TokenProvider.bearer`."""
    config, state = isolated
    (config / "config.json").write_text(json.dumps({"client_id": "fixture-id"}), encoding="utf-8")
    _write_token(
        state,
        access_token="fixture-access-token",
        expires_at=_iso(datetime.now(timezone.utc) + timedelta(seconds=1)),
    )

    assert check()["ready"]["spotify_verbs"] is False


def test_an_unknown_authorisation_date_says_so_rather_than_guessing(isolated):
    _config, state = isolated
    _write_token(state, refresh_token="r")
    fact = check()["refresh_token"]
    assert fact["present"] is True
    assert fact["past_wall"] is None
    assert fact["age_days"] is None


@pytest.mark.parametrize(
    "recorded", [{"scopes": ["b", "a"]}, {"scope": "b a"}]
)
def test_granted_scopes_are_reported_in_either_recorded_form(isolated, recorded):
    _config, state = isolated
    _write_token(state, access_token="x", **recorded)
    fact = check()["scopes"]
    assert fact["known"] is True
    assert fact["granted"] == ["a", "b"]


def test_allowlist_state_is_unknown_until_a_403_is_seen(isolated):
    """Spotify offers no way to ask; a 403 is the only signal there is."""
    fact = check()["allowlist"]
    assert fact["state"] == "unknown"
    assert fact["last_403"] is None


def test_a_recorded_403_becomes_a_suspected_allowlist_problem(isolated):
    _config, state = isolated
    (state / "last-403.json").write_text(
        json.dumps(
            {
                "observed_at": _iso(datetime.now(timezone.utc)),
                "endpoint": "/me/player",
                "reason": "Forbidden",
            }
        ),
        encoding="utf-8",
    )
    result = check()
    assert result["allowlist"]["state"] == "suspect"
    assert result["allowlist"]["last_403"]["endpoint"] == "/me/player"
    assert any("allowlist" in finding for finding in result["findings"])


def test_provider_absence_is_reported_and_runtime_is_not_ready(isolated, monkeypatch):
    """Raw provider compatibility does not mistake a key-shaped setting for readiness."""
    for name in list(os.environ):
        if "API_KEY" in name or name == "MUSIC_DECK_PROVIDER":
            monkeypatch.delenv(name, raising=False)
    result = check()
    assert result["provider"]["configured"] is False
    assert result["provider"]["needed_by"] == ["plan", "do"]
    assert result["model_runtime"]["missing"] == "provider"
    assert result["ready"]["plan"] is False
    assert result["ready"]["do"] is False
    assert not any("provider" in finding.lower() for finding in result["findings"])


def test_explicit_provider_without_a_key_is_not_runtime_ready(isolated, monkeypatch):
    monkeypatch.setenv("MUSIC_DECK_PROVIDER", "anthropic")

    runtime = check()["model_runtime"]

    assert runtime["ready"] is False
    assert runtime["missing"] == "credentials"
    assert "ANTHROPIC_API_KEY" in runtime["remedy"]


def test_runtime_reports_missing_sdk_with_the_complete_install(isolated, monkeypatch):
    from music_deck import intelligence

    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    monkeypatch.setattr(intelligence, "missing_package", lambda provider: "anthropic")

    runtime = check()["model_runtime"]

    assert runtime["ready"] is False
    assert runtime["missing"] == "provider_sdk"
    assert runtime["command"] == intelligence.runtime_install_command("anthropic")


def test_runtime_reports_missing_engine_with_the_complete_install(isolated, monkeypatch):
    from music_deck import intelligence

    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    monkeypatch.setattr(intelligence, "missing_package", lambda provider: None)
    monkeypatch.setattr(intelligence, "engine_installed", lambda: False)

    runtime = check()["model_runtime"]

    assert runtime["ready"] is False
    assert runtime["missing"] == "engine"
    assert runtime["command"] == intelligence.runtime_install_command("anthropic")


def test_runtime_reports_selected_provider_and_model_when_complete(isolated, monkeypatch):
    from music_deck import intelligence

    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    monkeypatch.setattr(intelligence, "missing_package", lambda provider: None)
    monkeypatch.setattr(intelligence, "engine_installed", lambda: True)

    runtime = check()["model_runtime"]

    assert runtime == {
        "ready": True,
        "missing": None,
        "provider": "anthropic",
        "model": intelligence.PROVIDER_DEFAULT_MODEL["anthropic"],
        "detail": "The selected provider, SDK, engine, and model are ready locally.",
    }
    assert check()["ready"]["plan"] is True
    assert check()["ready"]["do"] is False


def test_azure_runtime_requires_its_explicit_deployment_model(isolated, monkeypatch):
    from music_deck import intelligence

    monkeypatch.setenv("MUSIC_DECK_PROVIDER", "azure-openai")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "not-a-real-key")
    monkeypatch.setattr(intelligence, "missing_package", lambda provider: None)
    monkeypatch.setattr(intelligence, "engine_installed", lambda: True)

    runtime = check()["model_runtime"]

    assert runtime["ready"] is False
    assert runtime["missing"] == "model"
    assert runtime["provider"] == "azure-openai"
    assert "MUSIC_DECK_MODEL" in runtime["remedy"]


def test_runtime_docs_follow_the_canonical_uri_and_install_command():
    """User-facing setup text is pinned to code values, not page-only wording."""
    from music_deck import intelligence, setup_guide

    runtime_command = intelligence.runtime_install_command("anthropic")
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    spotify_app = (REPO_ROOT / "docs" / "spotify-app.md").read_text(encoding="utf-8")
    smart_tool = (REPO_ROOT / "src" / "music_deck" / "SMART_TOOL.md").read_text(
        encoding="utf-8"
    )
    evidence_readme = (REPO_ROOT / "evidence" / "README.md").read_text(encoding="utf-8")
    evidence_script = (REPO_ROOT / "evidence" / "live_round_trip.py").read_text(
        encoding="utf-8"
    )
    checkout_command = (
        f'uv run --with "{intelligence.ENGINE_REQUIREMENT}" --extra anthropic '
        "python evidence/live_round_trip.py"
    )

    assert DEFAULT_REDIRECT_URI in readme
    assert DEFAULT_REDIRECT_URI in spotify_app
    assert runtime_command in readme
    assert runtime_command in smart_tool
    assert runtime_command in setup_guide.render()
    assert checkout_command in evidence_readme
    assert checkout_command in evidence_script


def test_state_and_config_directories_are_outside_the_working_directory(monkeypatch):
    """invocation.md: state belongs in the per-user location, not beside the source."""
    for name in ("MUSIC_DECK_CONFIG_DIR", "MUSIC_DECK_STATE_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    assert config_dir().parts[-2:] == (".config", "music-deck")
    assert state_dir().parts[-3:] == (".local", "state", "music-deck")
