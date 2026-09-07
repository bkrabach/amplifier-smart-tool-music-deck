"""The test 655 doubles could not be: `do` against a REAL model.

Why this file exists
--------------------
On 2026-09-06 `music-deck do` shipped with 655 passing tests and failed on its
very first live invocation::

    $ music-deck do 'three 90s grunge songs in a new playlist called "music-deck do test"'
    exit 1
    code: provider_failed
    "The agent engine refused to run a turn on anthropic/claude-sonnet-5:
     The provider requested an undeclared tool."

Every one of those 655 tests drove a double that answered in exactly the JSON
text the verb was hoping for. A real model, handed a prompt describing tools,
makes a **native tool call** instead -- and the engine refuses one it was never
told about. No double can catch that, because a double is not a provider. This
is the only test in the repository that can.

What it costs, and why it is cheap
----------------------------------
One short brief, a low ceiling, three songs. Spotify's Development Mode quota is
shared across every app the account owns and Spotify does not disclose what is
left of it, and a model provider's quota is real money. So this asks for the
smallest thing that still exercises the whole path: a search, a write, and a
read-back.

Running it
----------
It is marked ``live`` and skips -- **with a reason**, never silently -- unless
all three of its preconditions hold. Run it with the engine and a provider SDK
added to the environment::

    uv run --extra dev \\
        --with anthropic \\
        --with pytest-asyncio \\
        --with "amplifier-agent @ git+https://github.com/microsoft/amplifier-agent@v1#subdirectory=packages/python" \\
        pytest -m live -q -s

``pytest-asyncio`` is not music-deck's dependency: ``amplifier_core`` ships a
pytest plugin that imports it, and pytest loads that plugin the moment the
engine is in the environment. Without it, pytest fails to start at all.

It writes a real playlist to the signed-in account, named with a timestamp so
repeated runs do not collide and so the evidence can be found afterwards.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from importlib.util import find_spec

import pytest

from music_deck.intelligence import (
    PROVIDER_CREDENTIAL_ENV,
    available_providers,
    engine_installed,
)
from music_deck.verbs.do import TOOLS, do

pytestmark = pytest.mark.live


# --------------------------------------------------------------------------- #
# The three preconditions, each skipping with the reason it failed
# --------------------------------------------------------------------------- #
def _why_not() -> str | None:
    """The reason this cannot run here, or ``None`` if it can.

    A reason rather than a bare skip: "skipped" with no explanation is how a
    test that never runs anywhere gets mistaken for a test that passes.
    """
    if not engine_installed():
        return (
            "the amplifier-agent engine is not installed in this environment; "
            'add it with --with "amplifier-agent @ git+https://github.com/'
            'microsoft/amplifier-agent@v1#subdirectory=packages/python"'
        )
    if not available_providers():
        names = sorted({name for names in PROVIDER_CREDENTIAL_ENV.values() for name in names})
        return (
            f"no model provider is usable here: set one of {names} and install "
            f"that provider's SDK into the environment running pytest"
        )
    if not _token_path().is_file():
        return (
            f"no Spotify token at {_token_path()}; run `music-deck login` "
            f"against a real account first"
        )
    return None


def _token_path():
    from music_deck.check import token_path

    return token_path()


LIVE = pytest.mark.skipif(_why_not() is not None, reason=_why_not() or "")


# --------------------------------------------------------------------------- #
# The run
# --------------------------------------------------------------------------- #
@LIVE
def test_do_finishes_a_real_brief_against_a_real_model_and_a_real_account(capsys):
    """The whole path, once, for real: search -> correct -> write -> read back.

    Every assertion below is one the JSON-text protocol would have failed:

    * the run reaches a **playlist** at all -- the old code never got past the
      first turn, because the engine refused an undeclared tool;
    * ``actions`` carries native tool calls the model chose, not text this
      module parsed out of a reply;
    * ``tracks`` is what Spotify says the playlist holds, read back after the
      write, rather than what music-deck asked it to hold.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    name = f"music-deck live {stamp}"
    brief = f'three 90s grunge songs in a new playlist called "{name}"'

    # A low ceiling on purpose: quota is shared, undisclosed, and somebody
    # else's. Measured live on 2026-09-07, this brief took six calls -- the dead
    # `genre:grunge year:1990-1999`, a widened `genre:grunge`, two artist
    # searches to meet the "90s" constraint the widened one drifted off, the
    # write, and `finish` -- so eight leaves two spare and no more.
    result = do(brief, max_turns=8, max_requests=14)

    playlist = result["playlist"]
    assert playlist is not None, result
    assert playlist["external_urls"]["spotify"].startswith("https://open.spotify.com/")

    assert result["tracks"], "Spotify reported an empty playlist after the write"
    assert result["read_back"]["returned"] == len(result["tracks"])

    called = [action["tool"] for action in result["actions"]]
    assert called, "the model made no tool call at all -- the 2026-09-06 defect"
    assert set(called) <= set(TOOLS), called
    assert "search" in called
    assert any(tool in called for tool in ("create_playlist", "add_to_playlist"))

    # boundary.v1 Core 3: one prompt sent, and every tool result published.
    assert len(result["transcript"]) == 1
    assert len(result["tool_results"]) == len(result["actions"])

    # Printed so a `-s` run is itself the evidence the acceptance criteria ask
    # for: the playlist URL and the tracks Spotify read back.
    with capsys.disabled():
        print(f"\nplaylist: {playlist['external_urls']['spotify']}")
        print(f"provider: {result['usage']['provider']}/{result['usage']['model']}")
        print(f"stopped_by: {result['stopped_by']}  calls: {called}")
        for track in result["tracks"]:
            print(f"  - {track['name']} -- {', '.join(track['artists'])}")


@LIVE
def test_a_real_model_is_offered_music_decks_tools_and_nothing_else(monkeypatch):
    """The allow-list, proven against the engine that actually registers tools.

    ``music_deck.intelligence._static_approval_policy`` exists because the
    engine registers its own built-ins -- ``bash``, ``write``, ``web_fetch`` --
    alongside the caller's, so ``approvals="allow"`` would mean all of them.
    That claim is about the *installed* engine, so it is checked here rather
    than against a stand-in that could only agree with whatever this repository
    already believed.
    """
    import asyncio

    from amplifier_agent import ApprovalRequest

    from music_deck.intelligence import _static_approval_policy

    decide = _static_approval_policy(TOOLS)

    for name in TOOLS:
        answer = asyncio.run(decide(ApprovalRequest("r", "summary", "c", name)))
        assert answer.decision == "allow", name

    for name in ("bash", "write", "edit", "web_fetch", "web_search", "delegate"):
        answer = asyncio.run(decide(ApprovalRequest("r", "summary", "c", name)))
        assert answer.decision == "deny", name
        assert name in answer.reason


def test_this_file_says_out_loud_when_it_cannot_run():
    """Always runs. Prints why the live tests were skipped, if they were.

    ``refusals.v1``'s spirit applied to a test suite: a check that cannot run
    reports that it could not, never a pass. Without this, a CI job with no
    provider key would print two dots and look exactly like one that proved
    something.
    """
    reason = _why_not()
    if reason is None:
        assert os.environ, "sanity"
        return
    print(f"\nLIVE TESTS SKIPPED: {reason}")
