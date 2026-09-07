"""Three stand-ins for a model, each proving a different thing.

``Recording`` -- captures every prompt **verbatim, at the moment it is sent**.
That timing is the whole point. A double that reconstructed the prompt after
the fact, or read it back off the reply, would be evidence about itself rather
than about the tool: the transcript it produced would be exactly as true as the
code that produced it, which is what ``boundary.v1`` Core 3 exists to stop
depending on. So ``run`` appends ``request.prompt`` -- the same string object
handed across the seam -- before it does anything else.

``Scripted`` -- replies from a script, so a model-backed path runs end to end
with no provider configured and no tokens spent.

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

from typing import Any, Final

from music_deck.intelligence import (
    MISSING_PROVIDER,
    ModelRequest,
    ModelResult,
    NoModelSubstrate,
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


class Recording:
    """Records every prompt verbatim as it is sent, and replies from a script."""

    implementation = "recording"

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies) or [CANNED_PLAN_JSON]
        self.prompts: list[str] = []
        self.requests: list[ModelRequest] = []
        self.preflight_calls: list[str | None] = []

    def preflight(self, provider: str | None = None) -> str:
        self.preflight_calls.append(provider)
        return provider or "recording"

    def run(self, request: ModelRequest) -> ModelResult:
        # First line of the method, before anything else can touch it: the
        # transcript is what was sent, not a reconstruction of it.
        self.prompts.append(request.prompt)
        self.requests.append(request)
        reply = self.replies.pop(0) if self.replies else ""
        return ModelResult(
            text=reply,
            provider="recording",
            model="recording-1",
            tokens_in=len(request.prompt) // 4,
            tokens_out=len(reply) // 4,
        )


class Scripted(Recording):
    """Replies from a script. Records too -- recording costs nothing."""

    implementation = "scripted"

    def preflight(self, provider: str | None = None) -> str:
        self.preflight_calls.append(provider)
        return provider or "scripted"


class Unconfigured:
    """Nothing configured: a refusal, never a fallback -- and never a prompt."""

    implementation = "unconfigured"

    def __init__(self) -> None:
        self.preflight_calls: list[str | None] = []
        self.run_calls: list[Any] = []

    def preflight(self, provider: str | None = None) -> str:
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
]
