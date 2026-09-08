"""Three stand-ins for a model, each proving a different thing.

``Recording`` -- captures every prompt **verbatim, at the moment it is sent**.
That timing is the whole point. A double that reconstructed the prompt after
the fact, or read it back off the reply, would be evidence about itself rather
than about the tool: the transcript it produced would be exactly as true as the
code that produced it, which is what ``boundary.v1`` Core 3 exists to stop
depending on. So ``run`` appends ``request.prompt`` -- the same string object
handed across the seam -- before it does anything else.

``Scripted`` -- replies from a script, so a model-backed path runs end to end
with no provider configured and no tokens spent. When the request carries tools
it drives them for real, the way a tool-calling model would: read the reply,
call the handler, answer from what came back.

**What a double can and cannot prove.** These three run music-deck's own code
end to end for nothing. What they cannot prove is what a *provider* does with a
prompt, and on 2026-09-06 that gap cost a shipped defect: 655 tests passed over
a verb that described its tools in prose and never declared them, because every
double answered in exactly the JSON the verb hoped for. A real model made a
native tool call and the engine refused the turn. ``tests/test_do_live.py`` is
the test that closes that gap, and no double replaces it.

``Unconfigured`` -- refuses in ``preflight`` and **fails loudly if ``run`` is
ever reached**. That failure is the proof of ``cli.v1`` Core 3's "refuses before
any prompt is built": a caller that assembled a prompt and only then discovered
it had no substrate would have to call ``run`` to find out, and this object
turns that into a test failure rather than a passing test with a hidden defect.

All three satisfy ``music_deck.intelligence.Intelligence``.

The good/bad pair, inverted
---------------------------
``boundary.v1``'s kit assert reads: "A recording model substrate captures every
prompt sent: GOOD = no credential appears in any prompt; BAD = a run with the
access token spliced into the prompt fails." Until 2026-09-06 the pair was about
Spotify *content*; Core 1 now permits that, so ``SPOTIFY_SEARCH_RESULTS`` is
here to be put in a prompt and **pass**, and ``credential_leak_prompt`` is here
to be put in a prompt and **fail**.

The fake credentials below are the shape of the real thing and the value of
nothing: they are long enough and formed like a Spotify access token, refresh
token and client ID, so ``music_deck.prompt_boundary``'s shape net catches them
without anybody handling a real credential to prove the check works.
"""

from __future__ import annotations

import json
import re
from typing import Any, Final

from music_deck.errors import MusicDeckError
from music_deck.intelligence import (
    MISSING_PROVIDER,
    ModelRequest,
    ModelResult,
    NoModelSubstrate,
    ToolSpec,
    ToolStop,
)
from music_deck.prompts import plan_prompt_parts

# A plan draft that validates under plan.v1: what a well-behaved model returns.
# `plan_format` and `brief` are absent by design -- music-deck writes those.
CANNED_PLAN_JSON = """```json
{
  "target": {"kind": "new", "name": "Saturday Morning Guitar",
             "description": "Upbeat 90s guitar songs to start a Saturday"},
  "steps": [
    {"search": "genre:alternative year:1990-1999", "type": "track", "take": 15,
     "why": "the core 90s alt-guitar sound the brief asks for"},
    {"search": "genre:britpop year:1993-1998", "type": "track", "take": 10,
     "why": "brighter, faster guitar pop to keep the mood upbeat"}
  ],
  "rules": {"exclude_artists": [], "exclude_title_terms": ["live", "remix"],
            "dedupe": "by_title_and_primary_artist", "order": "shuffle"}
}
```"""


# --------------------------------------------------------------------------- #
# The good/bad pair for boundary.v1 Core 2
# --------------------------------------------------------------------------- #
FAKE_ACCESS_TOKEN: Final = (
    "BQThisIsNotARealSpotifyAccessTokenItIsAFixtureForTheBoundaryCheck0123456789"
)
FAKE_REFRESH_TOKEN: Final = (
    "AQThisIsNotARealSpotifyRefreshTokenItIsAFixtureForTheBoundaryCheck0123456789"
)
FAKE_CLIENT_ID: Final = "0123456789abcdef0123456789abcdef"
"""Three credentials that are real in shape and fake in value. Each is what
``boundary.v1`` Core 2 forbids in a prompt, and none of them opens anything."""

SPOTIFY_SEARCH_RESULTS: Final = """## What the searches returned

[
  {"id": "3n3Ppam7vgaVa1iaRUc9Lp", "name": "Mr. Brightside",
   "artists": ["The Killers"], "uri": "spotify:track:3n3Ppam7vgaVa1iaRUc9Lp",
   "popularity": 84, "duration_ms": 222075,
   "external_urls": {"spotify": "https://open.spotify.com/track/3n3Ppam7vgaVa1iaRUc9Lp"}},
  {"id": "1301WleyT98MSxVHPZCA6M", "name": "Bittersweet Symphony",
   "artists": ["The Verve"], "uri": "spotify:track:1301WleyT98MSxVHPZCA6M",
   "popularity": 79, "duration_ms": 348893}
]

`genre:grunge year:1990-1999` returned 0 results."""
"""Fetched Spotify content: ids, URIs, links, popularity, the lot.

The GOOD half of the pair. Under the old one-way boundary this was the thing a
prompt could not carry; ``boundary.v1`` Core 1 now says a model may read what
Spotify returns, and a check that still failed this would be enforcing a clause
nobody holds any more."""


def credential_leak_prompt(brief: str, credential: str = FAKE_ACCESS_TOKEN) -> str:
    """What ``plan`` would look like if somebody handed the model the keys.

    The BAD half. Not a doctored string: the same static parts and the same
    caller brief, in the same order, with one credential added the way a
    plausible mistake would add it -- "here is the token, go and fetch". Run it
    through ``Recording`` and ``music_deck.prompt_boundary`` and the check must
    fail, naming which credential it found.
    """
    parts = plan_prompt_parts()
    return "\n\n".join(
        [
            parts["instructions"],
            parts["brief"],
            brief,
            f"Use this credential to call the Spotify Web API: {credential}",
        ]
    )


# --------------------------------------------------------------------------- #
# Standing in for a model that calls tools
# --------------------------------------------------------------------------- #
_FENCE_RE: Final = re.compile(r"```(?:json)?\s*\n(.*?)```", re.DOTALL)


def tool_call_in(reply: str) -> tuple[str, dict[str, Any]] | None:
    """The ``{"tool": ..., "arguments": {...}}`` in a scripted reply, or ``None``.

    A script writes what a model *would call*; this is what turns that into an
    actual call. ``None`` means the reply is the model's final text, which is
    how a turn ends.

    Scripts stayed in this shape across the 2026-09-06 change from a JSON-text
    protocol to native tool calls, on purpose: the shape a test *writes* is not
    the thing that was wrong. What was wrong was that the shipped verb parsed it
    out of a reply instead of declaring tools, so a real model never produced
    it. That parsing now lives here, in the doubles, where it belongs -- and
    ``tests/test_do_live.py`` is what proves a real provider does the other
    thing.
    """
    document = _object_in(reply)
    if document is None:
        return None
    name = document.get("tool")
    if not isinstance(name, str) or not name.strip():
        return None
    arguments = document.get("arguments") or {}
    return name.strip(), dict(arguments) if isinstance(arguments, dict) else {}


def _object_in(reply: str) -> dict[str, Any] | None:
    for candidate in reversed(_FENCE_RE.findall(reply or "")):
        loaded = _load(candidate)
        if loaded is not None:
            return loaded
    start = (reply or "").find("{")
    end = (reply or "").rfind("}")
    if start != -1 and end > start:
        return _load(reply[start : end + 1])
    return None


def _load(text: str) -> dict[str, Any] | None:
    try:
        loaded = json.loads(text)
    except ValueError:
        return None
    return loaded if isinstance(loaded, dict) else None


class Recording:
    """Records every prompt verbatim as it is sent, and replies from a script.

    When the request carries tools it also **behaves like a tool-calling
    model**: it reads each scripted reply, calls the matching handler for real,
    and asks itself for the next reply given what came back. That loop is the
    part a double must reproduce faithfully, because it is where the engine
    would otherwise be doing the work -- including the two ways a real turn
    ends badly, both reproduced here as the codes the engine actually raises:

    * a tool the caller never declared -> ``provider_failed``, which is verbatim
      what the engine raised on the first live ``do`` invocation.
    * a handler raising :class:`ToolStop` -> ``tool_failed``, the turn ended by
      music-deck itself, which is how a ceiling binds.
    """

    implementation = "recording"

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies) or [CANNED_PLAN_JSON]
        self.prompts: list[str] = []
        self.requests: list[ModelRequest] = []
        self.preflight_calls: list[str | None] = []
        #: Every string a handler handed back, in order -- the double's own
        #: record of what it was shown, independent of what the verb published.
        self.observed: list[str] = []

    def preflight(self, provider: str | None = None, model: str | None = None) -> str:
        self.preflight_calls.append(provider)
        return provider or "recording"

    def next_reply(self, last_result: str | None) -> str:
        """The next thing this model says. Scripted; ``last_result`` ignored.

        The hook a reactive double overrides to answer from what it was just
        shown rather than from a list.
        """
        return self.replies.pop(0) if self.replies else ""

    def run(self, request: ModelRequest) -> ModelResult:
        # First line of the method, before anything else can touch it: the
        # transcript is what was sent, not a reconstruction of it.
        self.prompts.append(request.prompt)
        self.requests.append(request)
        reply = self.next_reply(None)
        if request.tools:
            reply = self._drive(request.tools, reply)
        return ModelResult(
            text=reply,
            provider="recording",
            model="recording-1",
            tokens_in=len(request.prompt) // 4,
            tokens_out=len(reply) // 4,
        )

    def _drive(self, tools: tuple[ToolSpec, ...], reply: str) -> str:
        """Call tools until the model answers with text instead of a call."""
        by_name = {spec.name: spec for spec in tools}
        while True:
            call = tool_call_in(reply)
            if call is None:
                return reply
            name, arguments = call
            spec = by_name.get(name)
            if spec is None:
                raise MusicDeckError(
                    "provider_failed",
                    f"The agent engine refused to run a turn: The provider "
                    f"requested an undeclared tool.",
                    "Configure the requested tool or correct the provider "
                    "response.",
                    tool=name,
                )
            try:
                result = spec.handler(arguments)
            except ToolStop as stop:
                raise MusicDeckError(
                    "tool_failed",
                    f"The agent engine refused to run a turn: {stop}",
                    "Correct the reported tool failure before trying again.",
                ) from None
            self.observed.append(result)
            reply = self.next_reply(result)


class Scripted(Recording):
    """Replies from a script. Records too -- recording costs nothing."""

    implementation = "scripted"

    def preflight(self, provider: str | None = None, model: str | None = None) -> str:
        self.preflight_calls.append(provider)
        return provider or "scripted"


class Unconfigured:
    """Nothing configured: a refusal, never a fallback -- and never a prompt."""

    implementation = "unconfigured"

    def __init__(self) -> None:
        self.preflight_calls: list[str | None] = []
        self.run_calls: list[Any] = []

    def preflight(self, provider: str | None = None, model: str | None = None) -> str:
        self.preflight_calls.append(provider)
        raise NoModelSubstrate(
            MISSING_PROVIDER,
            "`plan` is model-backed and no model provider is configured.",
            "Set ANTHROPIC_API_KEY (or OPENAI_API_KEY, GOOGLE_API_KEY, "
            "AZURE_OPENAI_API_KEY) and run again.",
        )

    def run(self, request: ModelRequest) -> ModelResult:
        # Recorded as well as raised: a caller that swallowed the exception
        # would still leave the evidence behind in `run_calls`.
        self.run_calls.append(request)
        raise AssertionError(
            "Unconfigured.run was reached. cli.v1 Core 3 requires `plan` to refuse "
            "before any prompt is built, so preflight must have refused first."
        )


__all__ = [
    "CANNED_PLAN_JSON",
    "FAKE_ACCESS_TOKEN",
    "FAKE_CLIENT_ID",
    "FAKE_REFRESH_TOKEN",
    "SPOTIFY_SEARCH_RESULTS",
    "Recording",
    "Scripted",
    "Unconfigured",
    "credential_leak_prompt",
    "tool_call_in",
]
