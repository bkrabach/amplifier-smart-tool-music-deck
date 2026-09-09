"""Live-run diagnostics stay private; these checks use only synthetic text."""

from __future__ import annotations

import importlib.util
import os
import stat
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def evidence(monkeypatch):
    name = "_music_deck_evidence_privacy_test"
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "evidence" / "live_round_trip.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


def test_live_record_defaults_to_private_directory(evidence):
    assert evidence.EVIDENCE_DIR == evidence.REPO_ROOT / ".private" / "evidence"
    help_text = evidence.build_parser().format_help()
    assert ".private/evidence/live-round-trip-" in help_text
    assert "out of version control" in help_text


@pytest.mark.parametrize("existing", [False, True])
def test_private_evidence_is_owner_only_even_when_replacing(evidence, tmp_path, existing):
    path = tmp_path / "private-record.md"
    if existing:
        path.write_text("old record", encoding="utf-8")
        path.chmod(0o644)

    wrote, _ = evidence.write_evidence(
        "Synthetic private diagnostic", path=path, secrets=(), allow_ids=()
    )

    assert wrote is True
    assert path.read_text(encoding="utf-8") == "Synthetic private diagnostic"
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert list(tmp_path.iterdir()) == [path]