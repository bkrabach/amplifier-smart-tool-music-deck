"""Offline guardrails for the opt-in real-provider evaluator."""

from __future__ import annotations

import json

from music_deck import evaluation


def test_evaluation_refuses_before_a_provider_call_without_confirmation(capsys):
    code = evaluation.main(["--scenario", "playlist"])

    assert code == 2
    assert json.loads(capsys.readouterr().out)["error"].startswith(
        "pass --confirm-real-provider"
    )


def test_named_session_evaluation_reports_the_implementation_gap_without_a_provider(capsys):
    code = evaluation.main(
        ["--scenario", "named-session", "--confirm-real-provider"]
    )

    assert code == 0
    document = json.loads(capsys.readouterr().out)
    assert document == {
        "scenario": "named-session",
        "status": "blocked",
        "reason": "Named create/resume sessions are not implemented in this build.",
    }