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

from typing import Any, Final

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
def steps() -> list[dict[str, Any]]:
    """The registration steps, in order, as structured data.

    Returned fresh each call so a caller may edit the result without changing
    what the next caller sees. ``cli.v1`` Core 4 wants one JSON document per
    result, so these are data rather than a wall of Markdown: an agent can read
    ``steps[2]["do"]`` and a person can read the same words.
    """
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
            "title": "Set the redirect URI to exactly http://127.0.0.1",
            "do": [
                "Enter exactly: http://127.0.0.1",
                "Leave the port off. music-deck adds a freshly chosen port at "
                "sign-in time (http://127.0.0.1:<port>), which Spotify permits "
                "only for a loopback IP literal -- so music-deck never squats "
                "on a fixed port.",
                "Do not spell it http://localhost. Spotify rejects the name "
                "`localhost` even though it means the same thing to your "
                "machine; the IP literal is required.",
                "Plain http is allowed here and only here, because 127.0.0.1 "
                "(or [::1]) is a loopback address.",
            ],
            "why": (
                "This is the one field that silently costs people an "
                "afternoon. boundary.v1 Core 4 requires the loopback IP "
                "literal, and `music-deck check` reports whether yours "
                "conforms."
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


def guide() -> dict[str, Any]:
    """The whole registration guide as one structured block."""
    return {
        "summary": (
            "music-deck ships no credentials. It runs under your own Spotify "
            "app, using your own client ID, and stores only your token. This "
            "is the whole setup; it takes about ten minutes."
        ),
        "dashboard": DASHBOARD_URL,
        "before_you_start": list(CONSTRAINTS),
        "steps": steps(),
        "afterwards": list(AFTERWARDS),
        "client_id_shape": CLIENT_ID_SHAPE,
    }


def render() -> str:
    """The same guide as plain text, for a human reading it in a terminal.

    Never printed to stdout by the CLI -- ``cli.v1`` Core 4 keeps stdout to one
    JSON document -- but a library caller holding this text can print it, and a
    test can read it, without re-deriving the wording.
    """
    lines: list[str] = ["Registering your own Spotify app", ""]
    lines += [guide()["summary"], "", "Before you start:"]
    lines += [f"  - {item}" for item in CONSTRAINTS]
    for entry in steps():
        lines += ["", f"Step {entry['step']} -- {entry['title']}"]
        lines += [f"  {item}" for item in entry["do"]]
        lines += [f"  ({entry['why']})"]
    lines += ["", "Afterwards:"]
    lines += [f"  - {item}" for item in AFTERWARDS]
    return "\n".join(lines)
