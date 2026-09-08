"""No credential ever enters a prompt, as a function anyone can run.

``boundary.v1`` Core 2 is the promise this module makes checkable:

    No credential ever enters a prompt. Not the access token, the refresh
    token, or the client ID -- not in text, not in a tool result, not in a
    retry. A model that can read Spotify still never reads the keys to it.

``boundary.v1`` Core 3 is what makes it checkable *from outside*: ``plan``
returns the verbatim text of every prompt it sent, so a reviewer runs this check
over the tool's own published output rather than over its source.

What this check is, and what it replaced
----------------------------------------
Until 2026-09-06 this module enforced a one-way boundary: nothing Spotify
returned could reach a prompt, checked by *cover* -- every allowed source text
removed from the prompt, and whatever was left a violation. **That clause is
gone**, removed by ratification rather than by accident (``boundary.v1``'s
Changelog, and Core 1: "A model may read what Spotify returns"). A model that
cannot see its own search results cannot correct them: asked for 90s grunge it
wrote ``genre:grunge year:1990-1999``, which returns nothing, and only running
the search reveals that.

So search results and the caller's own playlists in a prompt are **permitted
here, and pass**. What survives is the half that was never about content: the
keys stay on this side of the seam.

Two nets, either of which decides
---------------------------------
1. **Exact value.** The credentials this machine actually holds -- the stored
   access and refresh tokens, and the client ID ``check`` reports -- searched
   for as literal strings. Precise, and it names which one leaked.
2. **Shape.** A Spotify access token (``BQ...``), a refresh token (``AQ...``)
   and a 32-hex-character client ID, recognised by their form. This net exists
   because the first is only as good as the credentials it was handed: on a
   machine with nothing signed in the exact-value net is empty, and a check
   with nothing to look for would pass every prompt vacuously.

A 22-character Spotify id is deliberately *not* a shape here. That is content,
and under Core 1 content is allowed.

Neither net is advisory: a hit on either is a violation.

No value is ever printed
------------------------
A violation names *which* credential and *where* -- never the value. A check
whose failure message quoted the credential it caught would be a worse leak
than the one it reported.

Purity
------
``check_prompts`` is a pure function of its two arguments. It reads no file,
touches no environment, and calls nothing -- so ``boundary.v1``'s conformance
kit can call it against a transcript captured anywhere, and against credentials
that never existed. ``check_plan_transcript`` is the convenience wrapper that is
deliberately **not** pure: handed no credentials it gathers this machine's own,
because a credential check has to know what the credentials are.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Final, Mapping, Sequence

CLAUSE: Final = "boundary.v1 Core 2"
"""The clause a failure of this check breaks, named in every message."""

CLAUSE_TEXT: Final = (
    "No credential ever enters a prompt. Not the access token, the refresh "
    "token, or the client ID -- not in text, not in a tool result, not in a "
    "retry."
)

ACCESS_TOKEN: Final = "the access token"
REFRESH_TOKEN: Final = "the refresh token"
CLIENT_ID: Final = "the client ID"
"""The three credentials Core 2 names, spelled the way a message reads."""

BY_VALUE: Final = "its exact value"
BY_SHAPE: Final = "its shape"


@dataclass(frozen=True)
class Credential:
    """One credential to look for: what it is, and what it is."""

    kind: str
    value: str


# The shape net. Conservative on purpose -- each pattern is a form no Spotify
# *content* takes, so allowing content through costs nothing here.
_SHAPES: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    (re.compile(r"BQ[A-Za-z0-9_\-]{60,}"), ACCESS_TOKEN),
    (re.compile(r"AQ[A-Za-z0-9_\-]{60,}"), REFRESH_TOKEN),
    (re.compile(r"(?<![0-9A-Za-z])[0-9a-f]{32}(?![0-9A-Za-z])"), CLIENT_ID),
)

_MIN_VALUE_LEN: Final = 8
"""A shorter value is not searched for: too short to be a credential, and long
enough to match half the prompt if a config file holds something odd."""


@dataclass(frozen=True)
class Violation:
    """One credential found inside one prompt. Carries no credential value."""

    prompt_index: int
    credential: str
    found_by: str
    at: int
    length: int
    clause: str = CLAUSE

    def describe(self) -> str:
        return (
            f"{self.clause} broken by prompt {self.prompt_index}: it carries "
            f"{self.credential}, caught by {self.found_by}, at character "
            f"{self.at} ({self.length} characters long). The value is not "
            "printed here -- printing it would leak it a second time."
        )


@dataclass(frozen=True)
class BoundaryReport:
    """The verdict over a whole transcript."""

    ok: bool
    checked: int
    violations: tuple[Violation, ...] = ()
    known: int = 0
    """How many exact credential values were searched for. Reported because a
    pass against zero of them is a weaker statement than a pass against three."""

    def describe(self) -> str:
        if self.ok and self.checked == 0:
            return (
                f"{CLAUSE} not checked: no prompt was examined, so nothing was "
                "proven. An absent transcript is not a passing one."
            )
        if self.ok:
            head = (
                f"{CLAUSE} kept: none of {self.checked} prompt(s) carries a "
                f"credential -- searched for {self.known} known credential "
                "value(s), and for the shape of an access token, a refresh "
                "token and a client ID."
            )
            if not self.known:
                head += (
                    " No credential value was supplied, so only the shape net "
                    "ran: this machine holds nothing to leak."
                )
            return head
        prompts = len({violation.prompt_index for violation in self.violations})
        lines = [
            f"{CLAUSE} BROKEN in {prompts} of {self.checked} prompt(s), "
            f"{len(self.violations)} finding(s).",
            f"  the clause: {CLAUSE_TEXT}",
        ]
        lines += [f"  {violation.describe()}" for violation in self.violations]
        return "\n".join(lines)

    def raise_if_broken(self) -> None:
        if not self.ok:
            raise BoundaryViolation(self.describe())


class BoundaryViolation(AssertionError):
    """Raised when a transcript fails the check. An AssertionError on purpose:
    a credential in a prompt is a fact about the program, not a user error."""


CredentialSet = Mapping[str, str] | Sequence["Credential | tuple[str, str]"]


def as_credentials(credentials: CredentialSet) -> tuple[Credential, ...]:
    """Normalise however the caller spelled the credential set.

    A mapping of ``{kind: value}`` is the ergonomic form; a sequence of
    ``Credential`` or ``(kind, value)`` pairs is the explicit one. A bare
    sequence of strings -- the shape the *removed* cover-based check took as its
    allowed set -- is refused loudly rather than iterated into nonsense.
    """
    if isinstance(credentials, Mapping):
        return tuple(
            Credential(str(kind), str(value))
            for kind, value in credentials.items()
            if value
        )
    out: list[Credential] = []
    for entry in credentials:
        if isinstance(entry, Credential):
            out.append(entry)
            continue
        if isinstance(entry, str):
            raise TypeError(
                "check_prompts' second argument is now the CREDENTIALS to look "
                "for, not the allowed source texts it used to cover a prompt "
                "with -- boundary.v1 Core 2 was inverted on 2026-09-06. Pass "
                "{'the access token': <value>} or a sequence of Credential."
            )
        kind, value = entry
        out.append(Credential(str(kind), str(value)))
    return tuple(out)


def credentials_in(
    prompt: str,
    credentials: CredentialSet = (),
    *,
    prompt_index: int = 0,
) -> tuple[Violation, ...]:
    """Every credential found in one prompt, by exact value or by shape.

    Both nets run over the same prompt; a span already reported by the
    exact-value net is not reported a second time by the shape net, so the
    number of findings is a number of leaked credentials.
    """
    found: dict[tuple[int, int], Violation] = {}
    for credential in as_credentials(credentials):
        value = credential.value
        if len(value) < _MIN_VALUE_LEN:
            continue
        start = prompt.find(value)
        while start != -1:
            span = (start, len(value))
            found.setdefault(
                span, Violation(prompt_index, credential.kind, BY_VALUE, *span)
            )
            start = prompt.find(value, start + 1)
    for pattern, kind in _SHAPES:
        for match in pattern.finditer(prompt):
            span = (match.start(), len(match.group(0)))
            found.setdefault(span, Violation(prompt_index, kind, BY_SHAPE, *span))
    return tuple(found[span] for span in sorted(found))


def check_prompts(
    prompts: Sequence[str], credentials: CredentialSet = ()
) -> BoundaryReport:
    """Check every prompt for the credentials Core 2 forbids.

    ``credentials`` is what to look for by exact value -- typically
    ``machine_credentials()``. The shape net runs whether or not anything was
    passed. Pure: same arguments, same answer, anywhere.
    """
    known = as_credentials(credentials)
    violations = tuple(
        violation
        for index, prompt in enumerate(prompts)
        for violation in credentials_in(prompt, known, prompt_index=index)
    )
    return BoundaryReport(
        ok=not violations,
        checked=len(prompts),
        violations=violations,
        known=len(known),
    )


def machine_credentials() -> tuple[Credential, ...]:
    """Every credential this machine actually holds, for the exact-value net.

    The client ID as ``check`` resolves it -- environment first, then the config
    file, so a caller who ran ``music-deck setup --client-id`` is covered -- plus
    the access and refresh tokens in the stored token file. Never raises: a
    machine with nothing signed in has nothing to leak, and returns ``()``.
    """
    try:
        from music_deck.auth import read_token, resolve_client_id
    except Exception:  # noqa: BLE001 - a check that cannot import cannot gather
        return ()

    found: list[Credential] = []
    try:
        client_id, _source = resolve_client_id()
    except Exception:  # noqa: BLE001 - "not configured" is the ordinary case
        client_id = None
    if client_id:
        found.append(Credential(CLIENT_ID, client_id))

    try:
        token = read_token()
    except Exception:  # noqa: BLE001 - no token, or an unreadable one
        token = None
    if isinstance(token, dict):
        for key, kind in (("access_token", ACCESS_TOKEN), ("refresh_token", REFRESH_TOKEN)):
            value = token.get(key)
            if isinstance(value, str) and value.strip():
                found.append(Credential(kind, value.strip()))
    # Provider credentials are keys too.  The model runtime reads these directly
    # from the environment, so a caller who pastes one into a brief would expose
    # it unless this exact-value net includes them.  Importing the table is safe:
    # it imports no provider SDK and performs no provider operation.
    try:
        from music_deck.intelligence import PROVIDER_CREDENTIAL_ENV

        for provider, names in PROVIDER_CREDENTIAL_ENV.items():
            for name in names:
                value = os.environ.get(name, "").strip()
                if value:
                    found.append(Credential(f"the {provider} provider credential", value))
    except Exception:  # noqa: BLE001 - the shape net remains available
        pass
    return tuple(found)


def check_plan_transcript(
    transcript: Sequence[str],
    *,
    credentials: CredentialSet | None = None,
) -> BoundaryReport:
    """Check a ``plan`` result's transcript for credentials.

    The convenience wrapper a reviewer reaches for: hand it what ``plan``
    printed and it looks for this machine's own credentials, plus anything
    shaped like one. Pass ``credentials`` explicitly to check a transcript
    against credentials this machine does not hold -- which is how a conformance
    kit proves the check *fails* without ever handling a real token.
    """
    if credentials is None:
        credentials = machine_credentials()
    return check_prompts(transcript, credentials)


__all__ = [
    "ACCESS_TOKEN",
    "BY_SHAPE",
    "BY_VALUE",
    "CLAUSE",
    "CLAUSE_TEXT",
    "CLIENT_ID",
    "REFRESH_TOKEN",
    "BoundaryReport",
    "BoundaryViolation",
    "Credential",
    "Violation",
    "as_credentials",
    "check_plan_transcript",
    "check_prompts",
    "credentials_in",
    "machine_credentials",
]
