"""The Spotify-app registration steps, shipped **inside** the package.

``cli.v1`` Core 8: "``setup`` gets a new caller from nothing to ready, without
prompting. It reports what is configured and what is missing, carries the steps
to register a Spotify app in plain words, and writes the client ID when given
one."

``cli.v1`` Core 4: "A remedy -- and the manifest's ``install`` -- names what the
reader HAS: a command their install method takes, or text the installed package
carries. **Never a source-tree path.**"

That second clause is why this module exists at all, and why it is a module
rather than a document. ``docs/spotify-app.md`` is in the repository, and the
repository is not what a reader has: ``pyproject.toml`` ships
``packages = ["src/music_deck"]``, so a reader who ran
``uv tool install git+https://...`` has the package and nothing else. Pointing
them at ``docs/spotify-app.md`` names a file that does not exist on their
machine. The steps below travel with the code, so ``music-deck setup`` can print
them from any install, offline, with no repository anywhere in sight.

Everything here is inert data. Reading this module contacts nothing, configures
nothing, and requires no credential -- ``music_deck.verbs.setup`` renders it.
"""

from __future__ import annotations

import textwrap
from typing import Any, Final

WIDTH: Final = 78
"""How wide prose is wrapped, here and in ``music_deck.verbs.setup``. Long
enough to read, narrow enough to survive a terminal nobody widened. Defined once
so the two renderings of the same words do not disagree about the shape."""

DASHBOARD_URL: Final = "https://developer.spotify.com/dashboard"
REVOKE_URL: Final = "https://www.spotify.com/account/apps/"

REPO_URL: Final = "https://github.com/bkrabach/amplifier-smart-tool-music-deck"
"""Where music-deck itself comes from. A URL resolves for any reader; a
repo-relative path resolves only inside a checkout (``cli.v1`` Core 4)."""

INSTALL_COMMAND: Final = f"uv tool install git+{REPO_URL}"
"""The documented install method. Every remedy that installs anything into
music-deck's own environment has to be a form of this one -- a tool install owns
its virtualenv, and ``uv pip install`` cannot reach inside it."""


def install_with(extra_package: str) -> str:
    """The documented install command, plus one extra package in the tool env.

    ``uv tool install --force --with <pkg> git+<repo>`` is the only form that
    adds a package to an already tool-installed copy: ``uv pip install`` has no
    way to name the tool's virtualenv. Every "install the provider SDK" remedy
    is built from here so the refusal and the fix cannot drift apart.
    """
    return f"uv tool install --force --with {extra_package} git+{REPO_URL}"


CLIENT_ID_LENGTH: Final = 32
"""Spotify client IDs are 32 hexadecimal characters. `setup --client-id` checks
this shape so an obviously wrong paste -- a dashboard URL, a client *secret*
label, half an id -- refuses immediately instead of failing later inside a
browser round trip nobody can read."""

CLIENT_ID_SHAPE: Final = (
    "A Spotify client ID is 32 hexadecimal characters (0-9, a-f) with no "
    "spaces or punctuation, for example "
    "0123456789abcdef0123456789abcdef. Copy it from the app's settings page "
    f"at {DASHBOARD_URL} -- the field labelled Client ID, never the client "
    "secret (music-deck never asks for one)."
)


# --------------------------------------------------------------------------- #
# The client-ID gap, and only that gap
# --------------------------------------------------------------------------- #
def client_id_steps(redirect_uri: str | None = None) -> tuple[str, ...]:
    """The steps that close the client-ID gap, and nothing else.

    ``cli.v1`` Core 8 asks for "the steps for that gap -- proportional to the
    gap, not the whole orientation every run, which is on request". These four
    are what a caller with no client ID has to do; :func:`steps` is the whole
    orientation, and ``music-deck setup --guide`` is the request.

    The redirect URI is **taken from the resolver**, never written down here:
    ``boundary.v1`` Core 4 makes it one value that ``check`` reports and ``login``
    binds, so the string this tells a caller to register has to be that same
    value. Guidance naming a URI the tool does not use is precisely the defect
    this argument exists to prevent.

    The two facts that measurably cost people an afternoon are carried in full
    rather than summarised, because a summary of them is what fails: the redirect
    URI is the loopback IP literal *with its port* and never ``localhost``, and
    the value to copy is the client ID, never the client secret. Both also appear
    in :func:`steps`; ``tests/test_setup.py`` asserts the two forms agree, so the
    short path cannot quietly lose what the long path says.
    """
    uri = redirect_uri or _resolved_redirect_uri()
    return (
        f"Go to {DASHBOARD_URL}, sign in, choose Create app, and tick Web API.",
        f"Set the redirect URI to exactly {uri} -- that whole string, port and "
        "all, and never http://localhost. Spotify's dashboard refuses a "
        "registration with no port (whatever its documentation says), and "
        "rejects the name `localhost` even though it means the same thing to "
        "your machine. music-deck binds exactly this port when you sign in, and "
        "`music-deck check` reports the value it will send.",
        "Copy the Client ID from the app's settings page -- the client ID, not "
        "the client secret. music-deck never asks for a secret and never stores "
        "one; a tool that asks you for one is not doing PKCE.",
        "Open User Management and add the Spotify account of everyone who will "
        "use the app, yourself included. Skipping this is the usual cause of a "
        "403 that looks like a bug in the tool.",
    )


def __getattr__(name: str) -> Any:
    """``setup_guide.CLIENT_ID_STEPS`` -- the steps for the redirect URI in force.

    This was a module constant until ``boundary.v1`` Core 4 made the redirect URI
    a resolved value rather than a fixed string. A constant would have to be
    built at import time, before the environment that decides that value has been
    read, so the name now answers with :func:`client_id_steps` each time it is
    asked. Callers reading it see the steps for the URI music-deck will actually
    use, which is the only version of them worth printing.
    """
    if name == "CLIENT_ID_STEPS":
        return client_id_steps()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _resolved_redirect_uri() -> str:
    """The redirect URI music-deck will actually use -- the one resolver.

    Imported inside the function so this module stays inert data that can be read
    without importing the rest of the package.
    """
    from music_deck.check import resolve_redirect_uri

    return resolve_redirect_uri()[0]


# --------------------------------------------------------------------------- #
# What a caller is signing up for -- the ceiling, stated before the steps
# --------------------------------------------------------------------------- #
CONSTRAINTS: Final[tuple[str, ...]] = (
    "The app owner must hold Spotify Premium. If Premium lapses the app stops "
    "working, and starts again when you resubscribe.",
    "Five authorised users, maximum. Everyone who uses the app must be added "
    "to its allowlist by name. Someone who is not on it can still sign in -- "
    "and then every request they make comes back 403. That is the only signal.",
    "The quota is shared and unpublished, and since July 2026 it is counted "
    "per developer account, not per client ID: registering more apps buys no "
    "more room.",
    "A newly registered app lives in Spotify's Development Mode and stays "
    "there. There is no realistic path out for a personal tool -- extended "
    "quota needs an organisation, a registered business, a launched service, "
    "and roughly a quarter of a million monthly users.",
)


# --------------------------------------------------------------------------- #
# The steps
# --------------------------------------------------------------------------- #
def steps(redirect_uri: str | None = None) -> list[dict[str, Any]]:
    """The registration steps, in order, as structured data.

    Returned fresh each call so a caller may edit the result without changing
    what the next caller sees. ``cli.v1`` Core 4 wants one JSON document per
    result, so these are data rather than a wall of Markdown: an agent can read
    ``steps[2]["do"]`` and a person can read the same words.

    ``redirect_uri`` defaults to the resolved one, for the reason
    :func:`client_id_steps` gives: the string a caller is told to register is the
    string the tool will send.
    """
    uri = redirect_uri or _resolved_redirect_uri()
    return [
        {
            "step": 1,
            "title": "Have Spotify Premium on the account that will own the app",
            "do": [
                "Sign in to Spotify and confirm the account you will own the "
                "app with has an active Premium subscription.",
                "This is the account that owns the app, not necessarily the "
                "account that listens.",
            ],
            "why": (
                "Spotify requires the app owner to hold Premium for a "
                "Development Mode app to function at all."
            ),
        },
        {
            "step": 2,
            "title": "Register the app",
            "do": [
                f"Go to {DASHBOARD_URL} and sign in.",
                "Choose Create app.",
                "Give it any name and description -- neither is shown to "
                "anyone but you.",
                "For 'Which API/SDKs are you planning to use', tick Web API.",
                "Set the redirect URI -- see step 3, it is the part people get "
                "wrong.",
                "Accept the terms and save.",
            ],
            "why": "music-deck ships no credentials; it runs under your app.",
        },
        {
            "step": 3,
            "title": f"Set the redirect URI to exactly {uri}",
            "do": [
                f"Enter exactly: {uri}",
                "Keep the port. Spotify's own documentation says a loopback "
                "literal may be registered without one; its dashboard refuses "
                "that registration, and the dashboard is what you are typing "
                "into. music-deck binds this exact port at sign-in.",
                "Do not spell it http://localhost. Spotify rejects the name "
                "`localhost` even though it means the same thing to your "
                "machine; the IP literal is required.",
                "Plain http is allowed here and only here, because 127.0.0.1 "
                "(or [::1]) is a loopback address.",
                "Want a different port? Run `music-deck setup --port <n>` and "
                "register http://127.0.0.1:<n> instead -- or set "
                "MUSIC_DECK_REDIRECT_URI to whatever your dashboard accepted. "
                "Both feed the one value `check` reports and `login` binds.",
            ],
            "why": (
                "This is the one field that silently costs people an "
                "afternoon. boundary.v1 Core 4 requires a loopback IP literal "
                "on a fixed, registered port, and `music-deck check` reports "
                "the exact value music-deck will send."
            ),
        },
        {
            "step": 4,
            "title": "Copy the client ID -- not the client secret",
            "do": [
                "Open the app's settings and copy the Client ID.",
                "Do NOT copy the client secret. music-deck never asks for one "
                "and never stores one; if a tool asks you for a Spotify client "
                "secret, it is not doing PKCE.",
            ],
            "why": (
                "PKCE is designed so a public client can hold the client ID. "
                "It is yours, and music-deck bundles none."
            ),
        },
        {
            "step": 5,
            "title": "Tell music-deck about it",
            "do": [
                "Run: music-deck setup --client-id <the client id you copied>",
                "That writes it to your config file, readable only by you.",
                "An environment variable works too and wins over the file: "
                "export MUSIC_DECK_CLIENT_ID=<the client id you copied>",
                "Confirm with: music-deck check",
            ],
            "why": (
                "`check` reports what it found and exits 0 either way. Seeing "
                '"client_id": {"present": false} is a report, not a crash.'
            ),
        },
        {
            "step": 6,
            "title": "Add yourself to the app's allowlist",
            "do": [
                "In the dashboard, open User Management.",
                "Add the Spotify account (name and email) of every person who "
                "will use the tool -- including yourself. Up to five.",
            ],
            "why": (
                "Skipping this is the single most common cause of a 403 that "
                "looks like a bug in the tool. music-deck reports it as "
                "`not_allowlisted`; this step is the remedy."
            ),
        },
        {
            "step": 7,
            "title": "Sign in",
            "do": [
                "Run: music-deck login",
                "Your browser opens, you approve the scopes, and the token is "
                "stored readable only by you.",
            ],
            "why": (
                "`login` is the only interactive verb music-deck has "
                "(boundary.v1 Core 5). Everything after this runs "
                "non-interactively."
            ),
        },
    ]


AFTERWARDS: Final[tuple[str, ...]] = (
    "You will sign in again roughly twice a year. Refresh tokens issued to "
    "dashboard-registered apps last six months from the moment you "
    "authorised, and refreshing an access token does not extend that. "
    "`music-deck check` reports how much of the six months is left.",
    "Access tokens last one hour; music-deck refreshes them for you.",
    "Playback needs a device that is already playing -- music-deck produces no "
    "audio of its own. With nothing playing, playback verbs refuse "
    "`no_active_device`.",
    "You cannot check for Premium in advance. Spotify removed the field that "
    "said whether an account is Premium, so music-deck learns it the way you "
    "would: a playback write comes back 403 and it reports `premium_required`.",
    f"To remove your data: `music-deck disconnect` deletes the token and every "
    f"locally cached byte, and reports what it deleted. Revoke the app itself "
    f"at {REVOKE_URL}.",
)


def guide(redirect_uri: str | None = None) -> dict[str, Any]:
    """The whole registration guide as one structured block."""
    uri = redirect_uri or _resolved_redirect_uri()
    return {
        "summary": (
            "music-deck ships no credentials. It runs under your own Spotify "
            "app, using your own client ID, and stores only your token. This "
            "is the whole setup; it takes about ten minutes."
        ),
        "dashboard": DASHBOARD_URL,
        "before_you_start": list(CONSTRAINTS),
        "steps": steps(uri),
        "redirect_uri": uri,
        "afterwards": list(AFTERWARDS),
        "client_id_shape": CLIENT_ID_SHAPE,
    }


def render(redirect_uri: str | None = None) -> str:
    """The same guide as plain text, for a human reading it in a terminal.

    This is what ``music-deck setup --guide`` prints. ``cli.v1`` Core 4, as
    rewritten on 2026-09-06, says "a verb whose result is guidance writes it for
    its reader, with ``--json`` for the same content structured" -- so this text
    is the default shape of ``--guide`` and :func:`guide` is its twin. Both are
    built from the same constants above, and every string :func:`guide` carries
    reaches this text (``tests/test_setup.py`` asserts it), so a reader who runs
    one form is never shown less than the other.
    """
    uri = redirect_uri or _resolved_redirect_uri()
    document = guide(uri)
    lines: list[str] = ["Registering your own Spotify app", ""]
    lines += [document["summary"], "", "Before you start:"]
    lines += [f"  - {item}" for item in CONSTRAINTS]
    for entry in steps(uri):
        lines += ["", f"Step {entry['step']} -- {entry['title']}"]
        lines += [f"  {item}" for item in entry["do"]]
        lines += [f"  ({entry['why']})"]
    lines += ["", "Afterwards:"]
    lines += [f"  - {item}" for item in AFTERWARDS]
    lines += ["", f"The client ID's shape: {document['client_id_shape']}"]
    return "\n".join(wrapped for line in lines for wrapped in _fill(line))


def _fill(line: str) -> list[str]:
    """One line, wrapped to :data:`WIDTH`, keeping its own indent.

    A URL, a command or a client ID is never split: ``break_long_words`` and
    ``break_on_hyphens`` are both off, so every token a reader might copy
    survives intact.
    """
    if not line.strip():
        return [""]
    indent = line[: len(line) - len(line.lstrip())]
    return textwrap.wrap(
        line.strip(),
        width=WIDTH,
        initial_indent=indent,
        subsequent_indent=indent + ("  " if indent else ""),
        break_long_words=False,
        break_on_hyphens=False,
    ) or [line]
