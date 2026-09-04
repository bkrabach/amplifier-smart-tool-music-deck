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
"""

from __future__ import annotations

from typing import Any

from music_deck.intelligence import (
    MISSING_PROVIDER,
    ModelRequest,
    ModelResult,
    NoModelSubstrate,
)

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


__all__ = ["CANNED_PLAN_JSON", "Recording", "Scripted", "Unconfigured"]
