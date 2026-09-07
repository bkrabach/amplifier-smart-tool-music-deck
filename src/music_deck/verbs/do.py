"""`do` -- one conversational verb that searches, sees, corrects, and reads back.

``plan`` writes a document and ``apply`` carries it out. Between them sits a
failure neither can catch, measured on the steward's own account on 2026-09-06:
asked for three 90s grunge songs, ``plan`` wrote ``genre:grunge year:1990-1999``,
``apply`` searched it, got **zero results**, and created an empty playlist
anyway. ``genre:grunge`` alone returns five. ``genre:alternative
year:1990-1999`` returns five. Only that one conjunction dies, and nothing
except *running the search* reveals it.

``do`` is the verb that runs it. A bounded loop: music-deck sends a prompt, the
model answers with one tool call, music-deck runs that tool against the same
library functions ``apply`` uses, and puts **what Spotify actually returned**
into the next prompt. The model sees the zero, and corrects.

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
  is assembled in this module and nowhere else, and each turn re-sends the whole
  prompt, so a transcript entry is a complete record of one turn rather than a
  fragment a reader has to reassemble.
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
* ``refusals.v1`` -- every code this module can emit is named there already:
  ``usage``, ``invalid_input``, ``partial_result``, ``no_provider_configured``
  (through the seam), ``internal_error``, and whatever the HTTP layer raises.

Why music-deck owns the loop, and does not register tools with the engine
------------------------------------------------------------------------
amplifier-agent v1 can hold tools itself and run its own loop. This verb does
not use that, and the reason is ``boundary.v1`` Core 3: with the engine driving,
the prompts actually sent are assembled inside the engine and inside the
provider SDK, so the only ``transcript`` music-deck could publish would be a
*reconstruction* of them. ``music_deck.testing.intelligence_doubles`` already
says why that is worthless -- a transcript rebuilt after the fact "would be
evidence about itself rather than about the tool". Owning the loop makes the
transcript the literal strings that crossed the seam.

Three more things follow from owning it, each of which the engine would have had
to be trusted for instead:

* **The turn and request ceilings are enforced by this file**, not requested of
  a model. Development Mode quota is shared and undisclosed; a runaway loop is a
  real cost somebody else pays.
* **An empty result set cannot become a playlist.** ``create_playlist`` takes
  its tracks in the same call, refuses an empty list, and refuses a URI that no
  search in this run actually returned. The empty-playlist failure above is not
  discouraged in the prompt, it is unreachable.
* **The approvals question does not arise.** The library's rule is that with no
  approvals channel a tool effect fails ``approval_unavailable``; with no engine
  tools there is no engine tool effect to approve. The gate on every write is
  the code in :func:`_write_new_playlist` and :func:`_add_to_playlist`, which a
  reviewer can read.
"""

from __future__ import annotations

import json
import re
from typing import Any, Final, Mapping, Sequence

from music_deck.errors import ErrorCode, MusicDeckError
from music_deck.http import SpotifyClient
from music_deck.intelligence import Intelligence, ModelRequest, resolve
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

TOOLS: Final[tuple[str, ...]] = (
    "search",
    "list_playlists",
    "playlist_tracks",
    "create_playlist",
    "add_to_playlist",
    "finish",
)
"""The whole vocabulary the model may call. Anything else is refused back to it
as an observation, naming these -- a model that misremembers a tool name gets to
correct itself, which is cheaper than ending the run."""

_JSON_FENCE_RE: Final = re.compile(r"```(?:json)?\s*\n(.*?)```", re.DOTALL)
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
def assemble_prompt(
    brief: str,
    history: Sequence[Mapping[str, Any]],
    *,
    turns_left: int,
    requests_left: int,
) -> str:
    """Build the prompt for one turn: instructions, tools, brief, history, budget.

    The whole prompt every turn, not a delta. That costs tokens and buys the
    property ``boundary.v1`` Core 3 is for: one transcript entry is the complete
    text of one turn, readable on its own by somebody who was not there.

    The caller's brief goes in **verbatim**. Nothing here is a credential, which
    is the whole of what Core 2 forbids.
    """
    parts = do_prompt_parts()
    segments = [parts["instructions"], parts["tools"], parts["brief"], brief]
    if history:
        segments += [parts["history"], _render_history(history)]
    segments += [
        parts["ceilings"],
        f"- turns left after this one: {turns_left}\n"
        f"- Spotify requests left: {requests_left}",
    ]
    return "\n\n".join(segments)


def _render_history(history: Sequence[Mapping[str, Any]]) -> str:
    """The action log as the model sees it: what was called, what came back."""
    blocks: list[str] = []
    for entry in history:
        blocks.append(
            f"### Turn {entry['turn']}: {entry['tool']}\n"
            f"arguments: {json.dumps(entry['arguments'], sort_keys=True)}\n"
            f"result: {json.dumps(entry['observation'], indent=2)}"
        )
    return "\n\n".join(blocks)


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
    engine.preflight(provider)

    run = _Run(brief, turn_ceiling, request_ceiling, client)
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
        self.history: list[dict[str, Any]] = []
        self.searches: list[dict[str, Any]] = []
        self.turns_used = 0
        self.playlist: dict[str, Any] | None = None
        self.selected: list[str] = []
        self.added = 0
        self.summary: str | None = None
        self.stopped_by: str | None = None
        # Totalled across turns, not overwritten by the last one: a loop's cost
        # is what the whole loop spent, and reporting only the final turn would
        # make an expensive run look cheap.
        self.usage: dict[str, Any] = {
            "provider": "",
            "model": None,
            "turns": 0,
            "tokens_in": 0,
            "tokens_out": 0,
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

    # -- the loop ----------------------------------------------------------- #
    def execute(
        self,
        engine: Intelligence,
        *,
        provider: str | None,
        model: str | None,
    ) -> dict[str, Any]:
        for turn in range(1, self.max_turns + 1):
            prompt = assemble_prompt(
                self.brief,
                self.history,
                turns_left=self.max_turns - turn,
                requests_left=max(0, self.max_requests - self.requests_used),
            )
            self.transcript.append(prompt)
            self.turns_used = turn

            result = engine.run(
                ModelRequest(prompt=prompt, provider=provider, model=model)
            )
            self._count_usage(result)

            call = _read_call(result.text)
            if isinstance(call, str):
                # Unreadable reply: hand the model its own mistake and let it
                # correct. It costs a turn, which is the honest price.
                self._record("(unreadable)", {}, {"error": call})
                continue

            tool, arguments = call
            if tool == "finish":
                self.summary = _text(arguments.get("summary"))
                self.stopped_by = "finish"
                break

            try:
                observation = self._run_tool(tool, arguments)
            except _CeilingReached as ceiling:
                self.stopped_by = ceiling.which
                break
            except MusicDeckError as failure:
                if failure.code not in _RECOVERABLE:
                    raise
                observation = {"error": failure.code, "message": failure.message}

            self._record(tool, arguments, observation)
        else:
            self.stopped_by = "turns"

        return self._conclude()

    def _count_usage(self, result: Any) -> None:
        """Add one turn's cost to the run's total."""
        self.usage["turns"] += 1
        self.usage["tokens_in"] += int(getattr(result, "tokens_in", 0) or 0)
        self.usage["tokens_out"] += int(getattr(result, "tokens_out", 0) or 0)
        self.usage["provider"] = getattr(result, "provider", "") or self.usage["provider"]
        self.usage["model"] = getattr(result, "model", None) or self.usage["model"]
        cost = getattr(result, "cost_usd", None)
        if cost is not None:
            previous = self.usage.get("cost_usd")
            self.usage["cost_usd"] = str(
                cost if previous is None else type(cost)(previous) + cost
            )

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
        _assert_transcript_clean(self.transcript)

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
# boundary.v1 Core 2 -- fail closed
# --------------------------------------------------------------------------- #
def _assert_transcript_clean(transcript: Sequence[str]) -> None:
    """Refuse to hand back anything if a credential reached a prompt.

    ``internal_error`` rather than a code of its own: ``refusals.v1`` Core 8
    defines it as "a defect in music-deck; it says so plainly rather than
    blaming the caller", which is exactly what a credential in a prompt is. The
    vocabulary is closed (Core 1), and this verb adds nothing to it.
    """
    report = check_plan_transcript(transcript)
    if not report.ok:
        raise MusicDeckError(
            "internal_error",
            "music-deck refused to hand back a result whose prompt carried a "
            f"credential.\n{report.describe()}",
            "This is a defect in music-deck, not in your invocation. Report it "
            "with the message above; no access token, refresh token or client "
            "ID should ever be able to reach a prompt.",
        )


# --------------------------------------------------------------------------- #
# Reading the model's reply
# --------------------------------------------------------------------------- #
def _read_call(reply: str) -> tuple[str, dict[str, Any]] | str:
    """``(tool, arguments)``, or a sentence explaining what was wrong.

    A string return is not an error to raise: it is the text handed straight
    back to the model as its own observation, so an unreadable turn costs one
    turn and corrects itself rather than ending the run.
    """
    document = _extract_json_object(reply)
    if document is None:
        return (
            "Your reply carried no JSON object. Answer with exactly one JSON "
            'object: {"thought": "...", "tool": "...", "arguments": {...}}.'
        )
    tool = _text(document.get("tool"))
    if not tool:
        return f'Your JSON has no "tool" field. Call one of: {list(TOOLS)}.'
    arguments = document.get("arguments")
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return '"arguments" must be a JSON object, even when empty: {}.'
    return tool, arguments


def _extract_json_object(reply: str) -> dict[str, Any] | None:
    """The JSON object in a reply, fenced blocks last-first then widest span.

    The same reading ``plan`` does, and deliberately so: one model, one habit,
    one way of getting an object out of a reply that narrates around it.
    """
    for candidate in reversed(_JSON_FENCE_RE.findall(reply or "")):
        loaded = _load_object(candidate)
        if loaded is not None:
            return loaded
    start = (reply or "").find("{")
    end = (reply or "").rfind("}")
    if start != -1 and end > start:
        return _load_object(reply[start : end + 1])
    return None


def _load_object(text: str) -> dict[str, Any] | None:
    try:
        loaded = json.loads(text)
    except ValueError:
        return None
    return loaded if isinstance(loaded, dict) else None


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
    "READ_BACK_LIMIT",
    "TOOLS",
    "assemble_prompt",
    "do",
]
