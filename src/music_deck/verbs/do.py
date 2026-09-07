"""`do` -- one conversational verb that searches, sees, corrects, and reads back.

``plan`` writes a document and ``apply`` carries it out. Between them sits a
failure neither can catch, measured on the steward's own account on 2026-09-06:
asked for three 90s grunge songs, ``plan`` wrote ``genre:grunge year:1990-1999``,
``apply`` searched it, got **zero results**, and created an empty playlist
anyway. ``genre:grunge`` alone returns five. ``genre:alternative
year:1990-1999`` returns five. Only that one conjunction dies, and nothing
except *running the search* reveals it.

``do`` is the verb that runs it. A bounded loop: music-deck declares six tools
to the engine, the model calls them **natively**, each handler runs against the
same library functions ``apply`` uses, and **what Spotify actually returned**
goes back to the model as that call's result. The model sees the zero, and
corrects.

Contracts served
----------------
* ``boundary.v1`` Core 1 -- "A model may read what Spotify returns." Search
  results and the caller's own playlists go into the prompt. This is the clause
  that makes the verb possible, and the clause that breaches Developer Policy
  §III; the steward ratified it knowingly on 2026-09-06.
* ``boundary.v1`` Core 2 -- no credential ever enters a prompt.
  :func:`_assert_transcript_clean` runs ``check_prompts`` over the whole
  transcript **before anything is handed back**, on the success path and on the
  refusal path both, and fails closed if it reports a violation.
* ``boundary.v1`` Core 3 -- the transcript is an observable output. Every prompt
  is assembled in this module and nowhere else. ``transcript`` is what that
  clause names: every prompt sent, verbatim. Since the model now drives itself
  through native tool calls, a prompt is not the only thing music-deck sends it,
  so the result also carries ``tool_results`` -- the exact strings each handler
  handed back. Together they are the whole of what crossed from music-deck to
  the model, and :func:`_assert_nothing_leaked` checks **both** for credentials,
  which is Core 2's "not in text, not in a tool result" read literally.
* ``cli.v1`` Core 2 -- ``do`` is model-backed and ``--help`` says so. Nothing
  here imports a provider or the engine at module scope; both arrive through the
  ``Intelligence`` seam, whose imports are already lazy.
* ``cli.v1`` Core 3 -- ``preflight`` runs before a character of prompt exists,
  so a caller with no substrate gets exit 3 naming the missing precondition.
* ``cli.v1`` Core 4 -- one JSON document; every Spotify object carries its
  ``external_urls.spotify``.
* ``cli.v1`` Core 7 -- the library is the tool. Every effect goes through
  :mod:`music_deck.verbs.catalog` and :mod:`music_deck.verbs.playlists`. There is
  no second implementation of search or of a playlist write in this file.
* ``refusals.v1`` -- Core 1 closes the vocabulary, and this module holds it
  closed. Its own codes are named there already (``usage``, ``invalid_input``,
  ``partial_result``, ``no_provider_configured``, ``internal_error``, plus
  whatever the HTTP layer raises); the engine's are not, and
  :func:`_named_refusal` maps them on. See that function for which, and why.

Why the model drives, and music-deck holds the reins
----------------------------------------------------
Until 2026-09-06 this verb ran its own loop and registered no tools: it
described them in the prompt and asked the model to answer with
``{"tool": ..., "arguments": ...}`` as text. That was wrong, and the first live
invocation said so::

    $ music-deck do 'three 90s grunge songs in a new playlist called "..."'
    exit 1
    code: provider_failed
    "The agent engine refused to run a turn on anthropic/claude-sonnet-5:
     The provider requested an undeclared tool."

A real model, handed a prompt describing tools, makes a **native tool call**;
the engine refuses one it was never told about. 655 tests passed over that
defect, because every one of them used a double that answered in exactly the
JSON the loop was hoping for. Doubles cannot prove a provider's tool-calling
behaviour. Only a provider can, which is why ``tests/test_do_live.py`` exists.

So the model now drives the loop through the engine, and this file keeps every
guarantee the old loop was written to hold -- each one moved into a handler
rather than surrendered:

* **The ceilings are still enforced here**, not requested of a model. The
  engine's own iteration cap is ``-1``; ``_Run._handle`` refuses the tool call
  that would exceed ``--max-turns`` and :class:`_BudgetedClient` refuses the
  request that would exceed ``--max-requests``. Development Mode quota is shared
  and undisclosed; a runaway loop is a real cost somebody else pays.
* **An empty result set still cannot become a playlist.** ``create_playlist``
  takes its tracks in the same call, refuses an empty list, and refuses a URI
  that no search in this run actually returned. Unreachable, not discouraged.
* **The transcript is still the literal strings that crossed**, because they are
  still assembled here: the prompt in :func:`assemble_prompt`, and each tool
  result in :meth:`_Run._handle`. Nothing is reconstructed after the fact --
  ``music_deck.testing.intelligence_doubles`` says why that would be worthless.
* **The approvals question now arises, and is answered.** Declaring a tool means
  the engine consults an approvals authority before every call, and with none it
  answers ``unavailable``. ``music_deck.intelligence._static_approval_policy``
  is that authority: a static, deterministic allow-list of exactly the six names
  below. It is spelled as a handler rather than the literal ``approvals="allow"``
  for a measured reason -- the engine registers its own built-ins (``bash``,
  ``write``, ``web_fetch`` and the rest) alongside the caller's, so "allow"
  would hand a shell on the caller's machine to a model asked to make a
  playlist. A denial ends the turn as a named refusal, never a traceback.
"""

from __future__ import annotations

import json
import re
from typing import Any, Final, Mapping, Sequence

from music_deck.errors import ErrorCode, MusicDeckError
from music_deck.http import SpotifyClient
from music_deck.intelligence import (
    MISSING_PROVIDER,
    Intelligence,
    ModelRequest,
    NoModelSubstrate,
    ToolSpec,
    ToolStop,
    resolve,
)
from music_deck.prompt_boundary import check_plan_transcript
from music_deck.prompts import do_prompt_parts
from music_deck.verbs import catalog, playlists

DEFAULT_MAX_TURNS: Final = 8
"""How many model turns one ``do`` run may spend.

Enough to search, see a zero, correct, search again, and write -- the measured
grunge sequence is four -- with room for one more correction. A ceiling a caller
can raise, never one they can remove.
"""

DEFAULT_MAX_REQUESTS: Final = 40
"""How many Spotify requests one ``do`` run may send.

Search pages at ten results per request since February 2026, so this is roughly
three or four generous searches plus the writes and the read-back. Spotify's
Development Mode quota is shared across every app the account owns and Spotify
does not disclose what is left of it, so an unbounded loop spends somebody
else's budget without ever being told it did.
"""

MAX_TRACKS_SHOWN: Final = 25
"""How many results of one search go into the next prompt.

The model needs enough to choose from and the transcript needs to stay
readable; a caller who asks for more results gets more requests, not a prompt
nobody can review.
"""

READ_BACK_LIMIT: Final = 100
"""How many tracks the closing read-back asks Spotify for."""

SCHEMA_DIALECT: Final = "https://json-schema.org/draft/2020-12/schema"
"""The JSON Schema dialect the engine validates a caller tool's schema against.

Named on every schema below because the engine names it on its own built-ins,
and because a dialect left to be inferred is a dialect nobody agreed on.
"""

_URI_OR_ID: Final[dict[str, Any]] = {"type": "string", "minLength": 1}
_LIMIT: Final[dict[str, Any]] = {"type": "integer", "minimum": 1, "maximum": 50}
_TRACKS: Final[dict[str, Any]] = {
    "type": "array",
    "minItems": 1,
    "items": {"type": "string", "minLength": 1},
    "description": (
        "Exact `uri` strings from a search result in THIS run. music-deck "
        "refuses a URI no search here returned, and refuses an empty list."
    ),
}


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    """One tool's input schema, closed to anything it does not name.

    ``additionalProperties: False`` is not decoration: the handlers below read
    named arguments and would silently ignore a misspelled one, so the schema is
    where a misspelling becomes visible to the model instead of becoming a
    default it did not ask for.
    """
    return {
        "$schema": SCHEMA_DIALECT,
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": required,
    }


TOOL_DECLARATIONS: Final[tuple[tuple[str, str, dict[str, Any]], ...]] = (
    (
        "search",
        "Run one Spotify search and see exactly what came back. Judge the "
        "result by its count and its contents, never by how good the query "
        "looked. `genre:` combined with `year:` is the filter pair most likely "
        "to return nothing; if it returns 0, change the query and search again.",
        _schema(
            {
                "query": {
                    "type": "string",
                    "minLength": 1,
                    "description": (
                        "A Spotify search expression. Field filters help: "
                        "artist:, album:, track:, year: (a year or a 1990-1999 "
                        "range), genre:."
                    ),
                },
                "type": {"type": "string", "enum": ["track", "album"]},
                "limit": _LIMIT,
            },
            ["query"],
        ),
    ),
    (
        "list_playlists",
        "The caller's own playlists, for when the brief names one that already "
        "exists.",
        _schema({"limit": _LIMIT}, []),
    ),
    (
        "playlist_tracks",
        "What is already in one of the caller's playlists.",
        _schema({"playlist_id": _URI_OR_ID, "limit": _LIMIT}, ["playlist_id"]),
    ),
    (
        "create_playlist",
        "Create a NEW playlist and put tracks in it, in one step. There is "
        "deliberately no way to create an empty playlist: if you have not found "
        "tracks yet, search again first.",
        _schema(
            {
                "name": {"type": "string", "minLength": 1},
                "description": {"type": "string"},
                "tracks": _TRACKS,
            },
            ["name", "tracks"],
        ),
    ),
    (
        "add_to_playlist",
        "Add tracks to a playlist that already exists.",
        _schema({"playlist_id": _URI_OR_ID, "tracks": _TRACKS}, ["playlist_id", "tracks"]),
    ),
    (
        "finish",
        "Stop. Call this once the brief is satisfied, or once you are certain "
        "it cannot be. Then reply with one line and call no further tools.",
        _schema({"summary": {"type": "string", "minLength": 1}}, ["summary"]),
    ),
)
"""The whole vocabulary the model may call: name, description, input schema.

One table, read twice -- by :meth:`_Run.tool_specs`, which turns it into the
``ToolSpec`` objects the engine is handed, and by ``prompts/do.md``, which
describes the same six in prose. They cannot drift into describing different
tools, because the model is *offered* exactly this and nothing else: the engine
refuses a call to a name it was not given, and
``intelligence._static_approval_policy`` denies any other name the engine itself
registered.
"""

TOOLS: Final[tuple[str, ...]] = tuple(name for name, _, _ in TOOL_DECLARATIONS)
"""Just the names, in order. Derived from the declarations above so a tool
cannot be named in one place and forgotten in the other."""

_TRACK_URI_RE: Final = re.compile(r"spotify:track:[0-9A-Za-z]{22}")

_RECOVERABLE: Final = frozenset({ErrorCode.USAGE, "invalid_input"})
"""Refusals that are the *model's* mistake and go back to it as an observation.

Everything else -- ``not_authenticated``, ``rate_limited``, ``spotify_error`` --
is about the account or about Spotify, and a loop that swallowed one would burn
its whole budget re-provoking it. Those propagate to the caller unchanged.
"""


# --------------------------------------------------------------------------- #
# The Spotify request ceiling
# --------------------------------------------------------------------------- #
class _CeilingReached(Exception):
    """The run hit a ceiling. Caught by the loop, never seen by a caller."""

    def __init__(self, which: str, limit: int) -> None:
        super().__init__(f"{which} ceiling of {limit} reached")
        self.which = which
        self.limit = limit


class _BudgetedClient:
    """A :class:`SpotifyClient` that counts requests and stops at a ceiling.

    Delegation rather than a subclass, because the caller hands ``do`` a client
    that is already built. Everything not named here falls through to the real
    client; ``paginate`` is deliberately the **unbound** ``SpotifyClient``
    method called with this object as ``self``, so Spotify's paging rules are
    reused verbatim and every page it fetches goes through the counter below.
    Re-implementing paging here to count it would fork the one place that knows
    the ten-per-page search cap.
    """

    def __init__(self, client: SpotifyClient, limit: int) -> None:
        self._client = client
        self.limit = limit
        self.used = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        if self.used >= self.limit:
            raise _CeilingReached("spotify_requests", self.limit)
        self.used += 1
        return self._client.request(method, path, **kwargs)

    def get(self, path: str, **params: Any) -> Any:
        return self.request("GET", path, params=params or None)

    def post(self, path: str, body: Any = None, **params: Any) -> Any:
        return self.request("POST", path, params=params or None, body=body)

    def put(self, path: str, body: Any = None, **params: Any) -> Any:
        return self.request("PUT", path, params=params or None, body=body)

    def delete(self, path: str, body: Any = None, **params: Any) -> Any:
        return self.request("DELETE", path, params=params or None, body=body)

    def paginate(self, *args: Any, **kwargs: Any) -> list[Any]:
        return SpotifyClient.paginate(self, *args, **kwargs)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# The prompt -- the whole of it, every turn
# --------------------------------------------------------------------------- #
def assemble_prompt(brief: str, *, max_turns: int, max_requests: int) -> str:
    """Build the one prompt a ``do`` run sends: instructions, tools, brief, budget.

    One prompt, not one per turn. The model drives itself from here with native
    tool calls, and what it learns along the way arrives as those calls' results
    -- so re-sending a hand-rolled history would be describing the conversation
    to the model *inside* the conversation it is already having.

    That makes this string the whole of what ``boundary.v1`` Core 3's
    ``transcript`` carries, and :attr:`_Run.tool_results` the rest of what
    crossed. Both are published, and both are checked for credentials.

    The caller's brief goes in **verbatim**. Nothing here is a credential, which
    is the whole of what Core 2 forbids.

    There is no ``history`` section any more: ``prompts/do.md`` lost it in the
    same change, so a section this function stopped sending cannot linger in the
    shipped file pretending it is still sent.
    """
    parts = do_prompt_parts()
    return "\n\n".join(
        [
            parts["instructions"],
            parts["tools"],
            parts["brief"],
            brief,
            parts["ceilings"],
            f"- tool calls this run may make: {max_turns}\n"
            f"- Spotify requests this run may send: {max_requests}",
        ]
    )


# --------------------------------------------------------------------------- #
# The verb
# --------------------------------------------------------------------------- #
def do(
    brief: str,
    *,
    max_turns: int = DEFAULT_MAX_TURNS,
    max_requests: int = DEFAULT_MAX_REQUESTS,
    provider: str | None = None,
    model: str | None = None,
    intelligence: Intelligence | None = None,
    client: SpotifyClient | None = None,
) -> dict[str, Any]:
    """Run a brief to a finished playlist, correcting along the way.

    Returns one JSON-shaped document naming the playlist, the tracks **read back
    from Spotify**, every action taken, both ceilings, and the transcript.

    Raises ``partial_result`` (exit 2) when the run ends without writing
    anything -- every search empty, a ceiling reached first, or the model
    stopping short. The playlist is never created for an empty result set;
    that is the failure this verb exists to prevent.
    """
    if not brief or not brief.strip():
        raise MusicDeckError(
            ErrorCode.USAGE,
            "`music-deck do` needs a brief: what you want, in your own words.",
            'Run: music-deck do "three 90s grunge songs in a new playlist called Flannel"',
        )
    turn_ceiling = _positive(max_turns, "--max-turns")
    request_ceiling = _positive(max_requests, "--max-requests")

    engine = resolve(intelligence)

    # cli.v1 Core 3: the refusal happens here, before any prompt exists.
    # Nothing above this line has assembled a character of prompt.
    chosen = _preflight(engine, provider)

    run = _Run(brief, turn_ceiling, request_ceiling, client)
    # Named before the turn runs, so a run music-deck ends itself still reports
    # which provider it was talking to rather than an empty string.
    run.usage["provider"] = chosen
    return run.execute(engine, provider=provider, model=model)


class _Run:
    """One ``do`` invocation: its budget, its record, and its single exit funnel.

    A class rather than a pile of locals because every conclusion -- success,
    empty results, a ceiling -- has to publish the *same* record, and the
    boundary check has to run over it exactly once on every path out.
    """

    def __init__(
        self,
        brief: str,
        max_turns: int,
        max_requests: int,
        client: SpotifyClient | None,
    ) -> None:
        self.brief = brief
        self.max_turns = max_turns
        self.max_requests = max_requests
        self._client_given = client
        self._api: Any = None

        self.transcript: list[str] = []
        self.tool_results: list[str] = []
        self.history: list[dict[str, Any]] = []
        self.searches: list[dict[str, Any]] = []
        self.turns_used = 0
        self.playlist: dict[str, Any] | None = None
        self.selected: list[str] = []
        self.added = 0
        self.summary: str | None = None
        self.stopped_by: str | None = None
        # Set when the run ends for a reason music-deck chose. The engine will
        # report its own failure for the same moment (`tool_failed`, because a
        # ToolStop reaches it as ToolFailed); these two say what actually
        # happened, and `execute` publishes them instead.
        self.finished = False
        self.fatal: MusicDeckError | None = None
        self.usage: dict[str, Any] = {
            "provider": "",
            "model": None,
            "turns": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            # False whenever music-deck ended the turn itself: the engine had no
            # completed turn to report usage for, so the zeros above are
            # "not counted", not "cost nothing". Saying which is the difference
            # between an honest report and a cheap-looking one.
            "tokens_counted": False,
        }

        # Every track URI this run has actually seen come back from Spotify,
        # plus any the caller typed into the brief. A write may name nothing
        # else: a model that invents a URI cannot turn an empty search into a
        # playlist, which is precisely the measured failure.
        self.seen: set[str] = set(_TRACK_URI_RE.findall(brief))

    # -- the client, resolved late ------------------------------------------ #
    @property
    def api(self) -> Any:
        if self._api is None:
            client = self._client_given
            if client is None:
                from music_deck.verbs.auth_verbs import spotify_client

                client = spotify_client()
            self._api = _BudgetedClient(client, self.max_requests)
        return self._api

    @property
    def requests_used(self) -> int:
        return 0 if self._api is None else int(self._api.used)

    # -- what the engine is handed ------------------------------------------ #
    def tool_specs(self) -> tuple[ToolSpec, ...]:
        """The six tools, bound to this run.

        Each handler closes over ``self``, so the ceilings, the record, and the
        set of URIs a search actually returned are this run's and no other's.
        The bodies are the same :meth:`_run_tool` branches the old loop called;
        nothing was reimplemented to make them reachable from the engine.
        """
        return tuple(
            ToolSpec(
                name=name,
                description=description,
                input_schema=schema,
                handler=(lambda arguments, _name=name: self._handle(_name, arguments)),
            )
            for name, description, schema in TOOL_DECLARATIONS
        )

    # -- one tool call ------------------------------------------------------ #
    def _handle(self, tool: str, arguments: Mapping[str, Any]) -> str:
        """Run one tool call and return the exact string the model will see.

        The single place a ceiling can bind, a refusal can be recycled, and a
        failure that is not the model's to fix can end the run. Three outcomes,
        deliberately distinct:

        * **an observation** -- returned as JSON. Includes the model's own
          recoverable mistakes (a missing argument, a URI no search returned),
          because handing those back is what lets a model correct itself at the
          cost of one call rather than ending the run.
        * **a ceiling** -- :class:`ToolStop`. The engine ends the turn; this run
          has already recorded which ceiling, and publishes that.
        * **a failure that is not the model's** -- ``not_authenticated``,
          ``rate_limited``, ``spotify_error``. Stashed in :attr:`fatal` and
          re-raised by :meth:`execute` **unchanged**, because a loop that
          swallowed one would burn its whole budget re-provoking it.
        """
        if self.finished:
            raise ToolStop(
                f"`finish` was already called; {tool!r} came after it. The run "
                "is over -- reply with one line and call no further tools."
            )
        if self.turns_used >= self.max_turns:
            self.stopped_by = "turns"
            raise ToolStop(
                f"This run's ceiling of {self.max_turns} tool calls is spent."
            )
        self.turns_used += 1

        if tool == "finish":
            self.summary = _text(arguments.get("summary"))
            self.stopped_by = "finish"
            self.finished = True
            observation: Any = {
                "ok": True,
                "note": "The run is complete. Reply with one line for the "
                "caller and call no further tools.",
            }
        else:
            try:
                observation = self._run_tool(tool, arguments)
            except _CeilingReached as ceiling:
                self.stopped_by = ceiling.which
                raise ToolStop(
                    f"This run's ceiling of {ceiling.limit} Spotify requests is "
                    "spent."
                ) from None
            except MusicDeckError as failure:
                if failure.code not in _RECOVERABLE:
                    self.fatal = failure
                    raise ToolStop(failure.message) from None
                observation = {"error": failure.code, "message": failure.message}

        self._record(tool, arguments, observation)
        rendered = json.dumps(observation, indent=2, sort_keys=False)
        # boundary.v1 Core 2 says a credential must not reach the model "in a
        # tool result" either, so what is checked has to be the string that was
        # actually returned -- kept here, not rebuilt from `history` later.
        self.tool_results.append(rendered)
        return rendered

    # -- the run ------------------------------------------------------------ #
    def execute(
        self,
        engine: Intelligence,
        *,
        provider: str | None,
        model: str | None,
    ) -> dict[str, Any]:
        """One agentic turn: the model drives, this run holds the reins.

        Exactly one call across the seam. Everything the model does after that
        happens through :meth:`_handle`, and every way the run can end funnels
        back here: it finished, a ceiling bound, something failed that is not
        the model's to fix, or the engine itself refused.
        """
        prompt = assemble_prompt(
            self.brief, max_turns=self.max_turns, max_requests=self.max_requests
        )
        self.transcript.append(prompt)

        try:
            result = engine.run(
                ModelRequest(
                    prompt=prompt,
                    provider=provider,
                    model=model,
                    tools=self.tool_specs(),
                )
            )
        except MusicDeckError as failure:
            # A turn that ended because *this run* ended it. The engine reports
            # its own `tool_failed`; the reason music-deck recorded is the true
            # one, so that is what the caller gets.
            if self.fatal is not None:
                raise self.fatal from failure
            if self.stopped_by is None:
                raise _named_refusal(failure) from failure
            self.usage["turns"] = self.turns_used
        else:
            self._count_usage(result)
            self.summary = self.summary or _text(result.text) or None

        return self._conclude()

    def _count_usage(self, result: Any) -> None:
        """What the completed turn cost, as the engine reported it."""
        # One turn across the seam, but the model spoke once per tool call plus
        # once to conclude. Reporting "1" would make a long run look like a
        # short one; the tool calls are the part music-deck can actually count.
        self.usage["turns"] = self.turns_used + 1
        self.usage["tokens_in"] = int(getattr(result, "tokens_in", 0) or 0)
        self.usage["tokens_out"] = int(getattr(result, "tokens_out", 0) or 0)
        self.usage["tokens_counted"] = True
        self.usage["provider"] = getattr(result, "provider", "") or self.usage["provider"]
        self.usage["model"] = getattr(result, "model", None) or self.usage["model"]
        cost = getattr(result, "cost_usd", None)
        if cost is not None:
            self.usage["cost_usd"] = str(cost)

    def _record(
        self, tool: str, arguments: Mapping[str, Any], observation: Any
    ) -> None:
        self.history.append(
            {
                "turn": self.turns_used,
                "tool": tool,
                "arguments": dict(arguments),
                "observation": observation,
            }
        )

    # -- the tools ---------------------------------------------------------- #
    def _run_tool(self, tool: str, arguments: Mapping[str, Any]) -> Any:
        if tool == "search":
            return self._search(arguments)
        if tool == "list_playlists":
            return self._list_playlists(arguments)
        if tool == "playlist_tracks":
            return self._playlist_tracks(arguments)
        if tool == "create_playlist":
            return self._write_new_playlist(arguments)
        if tool == "add_to_playlist":
            return self._add_to_playlist(arguments)
        return {
            "error": "unknown_tool",
            "message": f"{tool!r} is not a tool. Call one of: {list(TOOLS)}.",
        }

    def _search(self, arguments: Mapping[str, Any]) -> Any:
        query = _text(arguments.get("query"))
        kind = _text(arguments.get("type")) or "track"
        limit = _limit(arguments.get("limit"), default=10)
        found = catalog.search(query, kind=kind, limit=limit, client=self.api)

        items = [item for item in found["results"] if isinstance(item, dict)]
        self._remember(items)
        self.searches.append(
            {
                "query": found["query"],
                "type": found["type"],
                "requested": found["requested"],
                "returned": found["returned"],
            }
        )
        shown = [_for_model(item) for item in items[:MAX_TRACKS_SHOWN]]
        observation: dict[str, Any] = {
            "query": found["query"],
            "type": found["type"],
            "returned": found["returned"],
            "results": shown,
        }
        if not shown:
            # Said out loud rather than left as an empty list, because this is
            # the exact signal the verb exists to put in front of the model.
            observation["note"] = (
                "This search returned NOTHING. Do not repeat it. Change the "
                "query -- drop the narrowest filter, widen the years, or name "
                "artists directly -- and search again."
            )
        return observation

    def _list_playlists(self, arguments: Mapping[str, Any]) -> Any:
        limit = _limit(arguments.get("limit"), default=20)
        found = playlists.playlists(limit=limit, client=self.api)
        return {
            "returned": found["returned"],
            "playlists": [
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "tracks": _track_count(item),
                }
                for item in found["playlists"]
                if isinstance(item, dict)
            ],
        }

    def _playlist_tracks(self, arguments: Mapping[str, Any]) -> Any:
        playlist_id = _text(arguments.get("playlist_id"))
        limit = _limit(arguments.get("limit"), default=20)
        found = playlists.playlist_items(playlist_id, limit=limit, client=self.api)
        tracks = _tracks_of(found["items"])
        self._remember(tracks)
        return {
            "playlist": found["playlist"],
            "returned": found["returned"],
            "tracks": [_for_model(track) for track in tracks[:MAX_TRACKS_SHOWN]],
        }

    def _write_new_playlist(self, arguments: Mapping[str, Any]) -> Any:
        """Create a playlist **and fill it**, or create nothing at all.

        One tool rather than two on purpose. ``apply`` created the target and
        then discovered it had nothing to put in it; here there is no call that
        creates an empty playlist, so that outcome is unreachable rather than
        discouraged.
        """
        name = _text(arguments.get("name"))
        if not name:
            return {"error": "usage", "message": "create_playlist needs a `name`."}
        uris, refusal = self._vet(arguments.get("tracks"))
        if refusal is not None:
            return refusal

        created = playlists.playlist_create(
            name,
            description=_text(arguments.get("description")) or None,
            client=self.api,
        )
        identity = created.get("id") if isinstance(created, dict) else None
        if not isinstance(identity, str) or not identity.strip():
            raise MusicDeckError(
                "spotify_error",
                "Spotify accepted `POST /me/playlists` but its answer carried no "
                f"playlist id, so there is nothing to add tracks to: {created!r}",
                "Run `music-deck playlists` to see whether the playlist was "
                "created, then run `music-deck do` again.",
            )

        block = catalog.item_ref("playlist", identity)
        block["name"] = name
        block["created"] = True
        self.playlist = block
        return self._add(identity, uris)

    def _add_to_playlist(self, arguments: Mapping[str, Any]) -> Any:
        playlist_id = _text(arguments.get("playlist_id"))
        if not playlist_id:
            return {
                "error": "usage",
                "message": "add_to_playlist needs a `playlist_id`.",
            }
        uris, refusal = self._vet(arguments.get("tracks"))
        if refusal is not None:
            return refusal

        identity = catalog.to_id(playlist_id, "playlist")
        if self.playlist is None:
            block = catalog.item_ref("playlist", identity)
            block["created"] = False
            self.playlist = block
        return self._add(identity, uris)

    def _add(self, playlist_id: str, uris: Sequence[str]) -> Any:
        written = playlists.playlist_add(playlist_id, list(uris), client=self.api)
        self.added += int(written["added"])
        for uri in written["uris"]:
            if uri not in self.selected:
                self.selected.append(uri)
        return {
            "playlist": written["playlist"],
            "added": written["added"],
            "note": "The tracks are in the playlist. Call `finish` when done.",
        }

    # -- the write gate ----------------------------------------------------- #
    def _vet(self, tracks: Any) -> tuple[list[str], dict[str, Any] | None]:
        """The track URIs a write may use, or the refusal to hand back instead.

        Two rules, both structural rather than advisory. A write needs at least
        one track -- there is no empty playlist to create. And every URI must be
        one this run actually saw Spotify return; a model that answers a failed
        search by inventing plausible ids gets refused by name, and the caller's
        account is untouched.
        """
        if not isinstance(tracks, (list, tuple)) or not tracks:
            return [], {
                "error": "no_tracks",
                "message": (
                    "A playlist write needs a non-empty `tracks` list, and "
                    "music-deck will not create an empty playlist. Search "
                    "first, then write the URIs that search returned."
                ),
            }

        uris: list[str] = []
        invented: list[str] = []
        for value in tracks:
            text = _text(value)
            if not text:
                continue
            try:
                uri = catalog.to_uri(text, "track")
            except MusicDeckError:
                invented.append(text)
                continue
            if uri not in self.seen:
                invented.append(text)
                continue
            if uri not in uris:
                uris.append(uri)

        if invented:
            return [], {
                "error": "unseen_tracks",
                "message": (
                    "These track URIs were never returned by a search in this "
                    f"run, so music-deck will not write them: {invented[:5]}. "
                    "Use the exact `uri` values from a search result."
                ),
            }
        if not uris:
            return [], {
                "error": "no_tracks",
                "message": "No usable track URI in `tracks`. Search first.",
            }
        return uris, None

    def _remember(self, items: Sequence[Any]) -> None:
        for item in items:
            if isinstance(item, dict) and isinstance(item.get("uri"), str):
                self.seen.add(item["uri"])

    # -- the single exit funnel --------------------------------------------- #
    def _conclude(self) -> dict[str, Any]:
        read_back = self._read_back()
        completeness = self._completeness(read_back)
        ceilings = {
            "turns": {"limit": self.max_turns, "used": self.turns_used},
            "spotify_requests": {
                "limit": self.max_requests,
                "used": self.requests_used,
            },
        }
        result: dict[str, Any] = {
            "brief": self.brief,
            "playlist": self.playlist,
            "tracks": read_back,
            "tool_results": list(self.tool_results),
            "read_back": {
                "source": "GET /playlists/{id}/items",
                "returned": len(read_back),
                "asked_for": len(self.selected),
            },
            "summary": self.summary,
            "stopped_by": self.stopped_by,
            "searches": self.searches,
            "actions": [
                {
                    "turn": entry["turn"],
                    "tool": entry["tool"],
                    "arguments": entry["arguments"],
                    "observation": entry["observation"],
                }
                for entry in self.history
            ],
            "completeness": completeness,
            "ceilings": ceilings,
            "usage": self.usage,
            "transcript": list(self.transcript),
        }

        # boundary.v1 Core 2, on every path out, before the caller sees a word
        # of it. The refusal below carries the same document, so the check has
        # to happen above both of them or it is not on every path.
        _assert_nothing_leaked(self.transcript, self.tool_results)

        if not read_back:
            raise self._partial(result, completeness, ceilings)
        return result

    def _read_back(self) -> list[dict[str, Any]]:
        """What Spotify says is in the playlist -- not what we asked it to hold.

        The acceptance criterion this verb was written against says the result
        must report what was READ BACK. So this is a real ``GET
        /playlists/{id}/items`` after the writes, and the ``tracks`` a caller
        reads come from its answer. A read-back that cannot run -- no playlist,
        or the request ceiling reached -- reports nothing rather than falling
        back to echoing the write, because echoing the write is exactly the
        claim that must not be made.
        """
        if self.playlist is None:
            return []
        try:
            found = playlists.playlist_items(
                self.playlist["id"], limit=READ_BACK_LIMIT, client=self.api
            )
        except _CeilingReached:
            self.stopped_by = self.stopped_by or "spotify_requests"
            return []
        return [_for_caller(track) for track in _tracks_of(found["items"])]

    def _completeness(self, read_back: Sequence[Any]) -> dict[str, Any]:
        """``refusals.v1`` Core 5's block, in this verb's terms.

        ``requested``/``fetched`` are summed over the searches this run ran;
        ``kept`` is what the model chose to write; ``added`` is what Spotify
        accepted; ``read_back`` is what Spotify then said it holds.
        ``under_fulfilled`` names the searches that came back short -- which for
        the grunge case is the whole story, in one line.
        """
        return {
            "requested": sum(int(s["requested"]) for s in self.searches),
            "fetched": sum(int(s["returned"]) for s in self.searches),
            "kept": len(self.selected),
            "added": self.added,
            "read_back": len(read_back),
            "searches_run": len(self.searches),
            "searches_with_results": sum(
                1 for s in self.searches if int(s["returned"]) > 0
            ),
            "under_fulfilled": [
                index
                for index, s in enumerate(self.searches)
                if int(s["returned"]) < int(s["requested"])
            ],
            "searches": [dict(s) for s in self.searches],
        }

    def _partial(
        self,
        result: Mapping[str, Any],
        completeness: Mapping[str, Any],
        ceilings: Mapping[str, Any],
    ) -> MusicDeckError:
        """The refusal for a run that finished without a playlist to show."""
        if completeness["searches_run"] and not completeness["searches_with_results"]:
            why = (
                f"every one of the {completeness['searches_run']} search(es) it "
                "ran returned 0 results, so there was nothing to put in a "
                "playlist and none was created"
            )
            remedy = (
                "Widen the brief or name artists directly. The `searches` block "
                "lists every query tried and what each returned -- a `genre:` "
                "and `year:` pair together is the combination most likely to "
                "return nothing."
            )
        elif self.stopped_by in ("turns", "spotify_requests"):
            limit = ceilings["turns" if self.stopped_by == "turns" else "spotify_requests"]
            why = (
                f"it reached its {self.stopped_by} ceiling of {limit['limit']} "
                f"(used {limit['used']}) before anything was written"
            )
            remedy = (
                f"Raise the ceiling with --max-turns / --max-requests, or give a "
                f"narrower brief. `actions` shows every turn it spent."
            )
        else:
            why = "it stopped without writing anything"
            remedy = (
                "Read `actions` for what it tried, then run `music-deck do` "
                "again with a more specific brief."
            )

        return MusicDeckError(
            ErrorCode.PARTIAL_RESULT,
            f"`music-deck do` did not finish the brief: {why}.",
            remedy,
            completeness=dict(completeness),
            ceilings=dict(ceilings),
            stopped_by=self.stopped_by,
            result=dict(result),
        )


# --------------------------------------------------------------------------- #
# cli.v1 Core 3 -- the refusal, naming the verb the caller actually ran
# --------------------------------------------------------------------------- #
def _preflight(engine: Intelligence, provider: str | None) -> str:
    """Establish a usable substrate and name it, or refuse naming ``do``.

    ``intelligence.preflight``'s own message still says "``plan`` is
    model-backed and no model provider is configured" -- it was written when
    ``plan`` was the only one, which ``cli.v1`` Cores 2-3 stopped saying at
    ``b3ac378``. Measured against an installed copy on 2026-09-06: ``music-deck
    do`` with no provider exits 3 correctly, and tells the caller about a verb
    they did not run.

    ``intelligence.py`` belongs to another lane this round, so the correction
    lives here and touches only the sentence: the code, the ``missing``
    precondition and the remedy are the ones the seam produced. The day that
    message stops naming a verb, this becomes a no-op on its own -- the
    substitution only fires when the message names ``plan``.
    """
    try:
        return engine.preflight(provider)
    except NoModelSubstrate as refusal:
        corrected = refusal.message.replace("`plan`", "`do`")
        if corrected == refusal.message:
            raise
        raise NoModelSubstrate(
            refusal.missing, corrected, refusal.remedy
        ) from refusal


# --------------------------------------------------------------------------- #
# refusals.v1 Core 1 -- the vocabulary is closed, and this is what closes it
# --------------------------------------------------------------------------- #
NAMED_IN_REFUSALS: Final[frozenset[str]] = frozenset(
    {
        # Core 2
        "not_authenticated",
        "reauthorization_required",
        "not_allowlisted",
        # Core 3
        "premium_required",
        "no_active_device",
        # Core 4
        "rate_limited",
        "quota_exceeded",
        # Core 5
        "partial_result",
        # Core 6
        "usage",
        "invalid_input",
        "invalid_plan",
        # Core 7
        "no_provider_configured",
        "port_unavailable",
        "no_browser",
        "cancelled",
        # Core 8
        "spotify_error",
        "playlist_items_unavailable",
        "internal_error",
        "not_implemented",
    }
)
"""Every code ``contracts/refusals.v1.md`` names, clause by clause.

Written out rather than imported because ``music_deck.errors`` still enumerates
``cli.v1`` Core 6's twelve, from before the vocabulary was split out into its own
contract on 2026-09-06 -- and that module belongs to another lane. A test sweeps
this set against the contract file, so the copy cannot drift silently.
"""

_SUBSTRATE_CODES: Final[frozenset[str]] = frozenset(
    {
        "selector_rejected",
        "model_not_selected",
        "provider_unavailable",
    }
)
"""Engine codes a **caller** can act on: the model id is stale, the deployment
was never named, the provider cannot be reached.

``refusals.v1`` Core 7 already has the right words for that -- "a model-backed
verb without a usable substrate" -- so they take ``no_provider_configured`` and
its exit 3, and the remedy still names ``MUSIC_DECK_MODEL`` the way the seam
wrote it.

``provider_failed`` is deliberately **not** here. The engine raises it when a
provider requests an undeclared tool, repeats a call id, or sends undecodable
arguments -- none of which a caller can fix by setting an environment variable,
and the first of which was music-deck's own defect on 2026-09-06.
"""


def _named_refusal(failure: MusicDeckError) -> MusicDeckError:
    """One engine failure, wearing a code ``refusals.v1`` actually names.

    ``music_deck.intelligence`` carries the engine's own ``code`` through
    verbatim, which is right for ``plan`` -- the layer that knows why a turn
    failed is the layer that failed it, and ``tests/test_engine_boot.py`` freezes
    that pass-through. But ``refusals.v1`` Core 1 says the *emitted* vocabulary
    is closed, and ``provider_failed`` is in no contract. That is the drift this
    function exists to stop, and it is why the first live ``do`` printed a code
    its caller could not look up.

    Three outcomes:

    * a code :data:`NAMED_IN_REFUSALS` already names -> **unchanged**. Nothing
      here relabels ``rate_limited`` or ``no_provider_configured``.
    * :data:`_SUBSTRATE_CODES` -> ``no_provider_configured`` (Core 7), exit 3.
    * everything else -> ``internal_error`` (Core 8, "a defect in music-deck; it
      says so plainly rather than blaming the caller"). ``provider_failed``
      lands here, and so does an approval that did not resolve to *allow*:
      music-deck sets that policy itself, so an ``approval_denied`` or
      ``approval_unavailable`` reaching a caller is music-deck's own defect and
      never theirs. That is the difference between a named refusal and the
      traceback this would otherwise be.

    The engine's own code is never thrown away -- it travels in ``engine_code``,
    so a bug report still names the thing that actually failed.

    A mapping and not a new code, because ``contracts/`` is not this lane's to
    edit. DONE.md records the gap it papers over: the vocabulary has no code for
    "the model substrate failed mid-turn", and ``internal_error`` is a widening
    of Core 8 to cover a case that is sometimes the provider's fault rather than
    music-deck's.
    """
    code = failure.code
    if code in NAMED_IN_REFUSALS:
        return failure
    if code in _SUBSTRATE_CODES:
        return NoModelSubstrate(MISSING_PROVIDER, failure.message, failure.remedy)
    extra = {key: value for key, value in failure.extra.items() if key != "engine_code"}
    return MusicDeckError(
        "internal_error",
        failure.message,
        failure.remedy,
        engine_code=code,
        **extra,
    )


# --------------------------------------------------------------------------- #
# boundary.v1 Core 2 -- fail closed
# --------------------------------------------------------------------------- #
def _assert_nothing_leaked(
    transcript: Sequence[str], tool_results: Sequence[str]
) -> None:
    """Refuse to hand back anything if a credential reached the model.

    Both directions music-deck can send one, because Core 2 names both: "not in
    text, not in a tool result, not in a retry". The prompt is checked because
    the caller's brief goes in verbatim; the tool results are checked because
    they carry whatever Spotify said, including the text of an error.

    ``internal_error`` rather than a code of its own: ``refusals.v1`` Core 8
    defines it as "a defect in music-deck; it says so plainly rather than
    blaming the caller", which is exactly what a credential reaching a model is.
    The vocabulary is closed (Core 1), and this verb adds nothing to it.
    """
    report = check_plan_transcript([*transcript, *tool_results])
    if not report.ok:
        raise MusicDeckError(
            "internal_error",
            "music-deck refused to hand back a result whose prompt or tool "
            f"result carried a credential.\n{report.describe()}",
            "This is a defect in music-deck, not in your invocation. Report it "
            "with the message above; no access token, refresh token or client "
            "ID should ever be able to reach a model.",
        )


# --------------------------------------------------------------------------- #
# Shaping Spotify's answers
# --------------------------------------------------------------------------- #
def _for_model(item: Mapping[str, Any]) -> dict[str, Any]:
    """One track as the model sees it: enough to choose by, and its URI.

    Carries ``external_urls.spotify`` like every other item music-deck emits.
    The model has no use for a link, but this shape is republished verbatim in
    the result's ``actions`` -- it is the record of what the model was shown --
    and ``cli.v1`` Core 4 admits no exception for "an item that happens to be
    inside a record". One rule, everywhere, is cheaper to keep than an
    exemption to remember.
    """
    shaped = _for_caller(item)
    if isinstance(item.get("popularity"), int):
        shaped["popularity"] = item["popularity"]
    album = item.get("album")
    if isinstance(album, dict) and isinstance(album.get("release_date"), str):
        shaped["released"] = album["release_date"]
    return shaped


def _for_caller(item: Mapping[str, Any]) -> dict[str, Any]:
    """One track as the caller reads it, carrying its link -- ``cli.v1`` Core 4.

    The link is built from the URI by :func:`catalog.uri_ref` rather than taken
    from whatever Spotify happened to include, so it is present on every item.
    """
    uri = item.get("uri")
    shaped = catalog.uri_ref(uri) if isinstance(uri, str) else {}
    shaped["name"] = item.get("name")
    shaped["artists"] = _artists(item)
    return shaped


def _artists(item: Mapping[str, Any]) -> list[str]:
    artists = item.get("artists")
    if not isinstance(artists, list):
        return []
    return [
        artist["name"]
        for artist in artists
        if isinstance(artist, dict) and isinstance(artist.get("name"), str)
    ]


def _tracks_of(items: Sequence[Any]) -> list[dict[str, Any]]:
    """The track objects inside a playlist-items page.

    Spotify wraps each one in ``{"track": {...}}``; a fake, a future shape, or a
    flattened page may hand the track directly. Both are read rather than one
    being assumed, because a read-back that silently found nothing would look
    exactly like a playlist that is genuinely empty.
    """
    tracks: list[dict[str, Any]] = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        inner = entry.get("track")
        track = inner if isinstance(inner, dict) else entry
        if isinstance(track.get("uri"), str):
            tracks.append(track)
    return tracks


def _track_count(playlist: Mapping[str, Any]) -> int | None:
    tracks = playlist.get("tracks")
    if isinstance(tracks, dict) and isinstance(tracks.get("total"), int):
        return tracks["total"]
    return None


# --------------------------------------------------------------------------- #
# Small readings of caller and model input
# --------------------------------------------------------------------------- #
def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _limit(value: Any, *, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(1, min(50, value))


def _positive(value: Any, flag: str) -> int:
    """A ceiling of at least one, or ``usage``.

    ``usage`` rather than ``invalid_input``, although ``refusals.v1`` Core 6
    names both: Core 6 says all of that group "exit 2", and today
    ``errors.exit_code_for`` maps ``invalid_input`` to 1 because it is not in
    ``FROZEN_CODES``. ``errors.py`` belongs to another lane, so this verb takes
    the code that is already wired to the exit its clause requires -- and
    ``errors.py``'s own docstring puts "a bad value" under ``usage`` anyway.
    The drift is recorded in DONE.md rather than patched from here.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise MusicDeckError(
            ErrorCode.USAGE,
            f"{flag} must be a whole number of at least 1; got {value!r}.",
            f"Pass {flag} 1 or more, or leave it out for the default.",
        )
    return value


__all__ = [
    "DEFAULT_MAX_REQUESTS",
    "DEFAULT_MAX_TURNS",
    "MAX_TRACKS_SHOWN",
    "NAMED_IN_REFUSALS",
    "READ_BACK_LIMIT",
    "SCHEMA_DIALECT",
    "TOOLS",
    "TOOL_DECLARATIONS",
    "assemble_prompt",
    "do",
]
