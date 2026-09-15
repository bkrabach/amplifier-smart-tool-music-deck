"""`apply` -- carry out a plan against Spotify, exactly as written.

The deterministic half of the one-way design. ``plan`` spends a model to turn a
brief into a document a person can read; ``apply`` spends no model at all and
does what that document says. Nothing in this module's import graph touches a
provider (``cli.v1`` Core 2), and nothing it sends to Spotify was chosen by a
model -- only searched for, in the caller's own words, in the order the plan
lists them.

Contracts served
----------------
* ``plan.v1`` Core 6 -- the plan is validated **before a socket is opened**.
  :func:`apply_plan` calls :func:`~music_deck.plan_schema.validate_plan` on its
  first line; a refused plan costs zero requests, which is why the refusal test
  can assert an empty transport rather than "no *interesting* requests".
* ``plan.v1`` Core 7 -- "``apply`` executes the plan as written, in step order.
  Each step searches with its ``type``, paginating at Spotify's 10-per-page cap
  until ``take`` results or exhaustion; ``rules`` apply after fetching; the
  target is created or extended in batches of at most 100. The result names the
  playlist and a per-step ``completeness`` (``requested``/``fetched``/``kept``);
  an under-fulfilled step is a documented ``partial_result``, never a silent
  success."
* ``plan.v1`` Core 8 -- determinism. The same plan against the same Spotify
  state produces the same result, unless ``rules.order`` is ``shuffle``. Every
  field this module emits is derived from the plan or from what Spotify
  answered: no clock, no random, no set iteration order, no environment.
* ``cli.v1`` Core 4 -- one JSON document; every playlist object it emits carries
  its own ``external_urls.spotify``, built by :func:`catalog.item_ref` from the
  id rather than hoped for in Spotify's answer.
* ``cli.v1`` Core 6 -- ``invalid_plan`` (exit 2, naming the path) and
  ``partial_result`` (exit 2, carrying a ``completeness`` block).
* ``boundary.v1`` Core 7 -- no path is built here at all. Searching goes through
  MD-3's ``catalog.search``, creating and extending through MD-3's
  ``playlists.playlist_create`` / ``playlist_add``, and both go through MD-2's
  client, where the removed-endpoint guard lives.

What "under-fulfilled" means, and why it is ``kept``
----------------------------------------------------
A step reports three numbers: ``requested`` (its ``take``), ``fetched`` (what
Spotify returned) and ``kept`` (what survived ``rules``). Core 7 calls an
under-fulfilled step a ``partial_result``, and the number that decides it is
``kept`` -- because ``kept`` is what actually reaches the playlist. A step that
fetched all 25 and then lost 7 to a dedupe rule put 18 tracks in front of a
caller who asked for 25; returning exit 0 there is precisely the "silently
truncated success" ``cli.v1`` Core 6 forbids. Both numbers are in the block, so
a caller can see at a glance whether Spotify ran out or the rules did the
cutting.

The refusal is not a failure to do the work. The playlist is created, the items
are added, and the whole result document rides along on the envelope under
``result``. What exit 2 says is "read this before you believe it is finished".

What this module deliberately does NOT do
-----------------------------------------
``plan.v1`` currently permits an album search step, but its deterministic
writer accepts track URIs only. Expanding albums is deliberately not invented
here.  An album step therefore refuses before client resolution: discovering
that mismatch only after a new target had been created would leave an empty
playlist behind.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Final, Sequence

from music_deck.errors import ErrorCode, MusicDeckError
from music_deck.http import SpotifyClient
from music_deck.plan_schema import validate_plan
from music_deck.verbs import catalog, playlists

PLAN_FORMAT: Final = 1


# --------------------------------------------------------------------------- #
# Reading a plan off disk -- the CLI's convenience, in the library
# --------------------------------------------------------------------------- #
def read_plan(path: str | Path) -> dict[str, Any]:
    """The plan document at ``path``, or the matching refusal.

    Lives here rather than in ``cli.py`` because turning "this file is not JSON"
    into ``invalid_plan`` is a judgement about plans, and ``docs/VISION.md``
    principle 1 keeps those in the library -- a Python caller gets the same
    reading and the same two refusals the binary does.

    An unreadable path is ``usage``: the caller pointed at the wrong file. A
    readable file that is not a JSON object is ``invalid_plan`` at ``$``: they
    pointed at the right file and it is not a plan.
    """
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise MusicDeckError(
            ErrorCode.USAGE,
            f"The plan file {str(source)!r} could not be read: {exc.strerror or exc}.",
            "Point `music-deck apply` at a readable plan document, or write one "
            'with `music-deck plan "<your brief>" --output plan.json`.',
        ) from exc

    try:
        document = json.loads(text)
    except ValueError as exc:
        raise MusicDeckError(
            ErrorCode.INVALID_PLAN,
            f"The plan file {str(source)!r} is not valid JSON: {exc}.",
            f"Fix the JSON syntax in {str(source)!r}, then run `music-deck apply` "
            "again.",
            path="$",
        ) from exc
    return document


# --------------------------------------------------------------------------- #
# The verb
# --------------------------------------------------------------------------- #
def apply_plan(
    plan: Any,
    *,
    client: SpotifyClient | None = None,
) -> dict[str, Any]:
    """Execute ``plan`` against Spotify and return what happened.

    Named ``apply_plan`` rather than ``apply`` because ``apply`` reads as the
    long-dead builtin at a Python call site; the *verb* is still ``apply``.

    Raises ``invalid_plan`` before any request when the document is not a
    ``plan.v1`` plan, and ``partial_result`` after the work when any step kept
    fewer items than it asked for.
    """
    # plan.v1 Core 6, first and before anything else: nothing below this line
    # runs for a plan that does not validate, so a refused plan is provably
    # free of side effects.
    validate_plan(plan)
    _require_executable_steps(plan)
    _require_valid_existing_target(plan)

    rules = plan["rules"]
    api = client if client is not None else _client()

    seen: set[Any] = set()
    collected: list[dict[str, Any]] = []
    step_reports: list[dict[str, Any]] = []

    # Core 7 -- "in step order". A plain loop over the list, which is ordered.
    for index, step in enumerate(plan["steps"]):
        requested = step["take"]
        found = catalog.search(
            step["search"], kind=step["type"], limit=requested, client=api
        )
        fetched = [item for item in found["results"] if isinstance(item, dict)]

        # Core 7 -- "`rules` apply after fetching", never folded into the query.
        kept = _keep(fetched, rules, seen)
        collected.extend(kept)

        step_reports.append(
            {
                "step": index,
                "search": step["search"],
                "type": step["type"],
                "completeness": {
                    "requested": requested,
                    "fetched": len(fetched),
                    "kept": len(kept),
                },
            }
        )

    ordered = _ordered(collected, rules["order"])
    uris = [item["uri"] for item in ordered if isinstance(item.get("uri"), str)]

    playlist = _target(plan["target"], api)

    # Core 7 -- "in batches of at most 100". playlists.playlist_add owns the
    # batching, the ordering within it, and the partial_result for a write that
    # gets part way; re-implementing any of that here would fork it.
    if uris:
        added = playlists.playlist_add(playlist["id"], uris, client=api)
        add_requests = added["requests_sent"]
        added_count = added["added"]
        items_per_request = added["items_per_request"]
    else:
        add_requests = 0
        added_count = 0
        items_per_request = playlists.ITEMS_PER_REQUEST

    under_fulfilled = [
        report["step"]
        for report in step_reports
        if report["completeness"]["kept"] < report["completeness"]["requested"]
    ]

    result: dict[str, Any] = {
        "plan_format": PLAN_FORMAT,
        "brief": plan["brief"],
        "playlist": playlist,
        "order": rules["order"],
        "steps": step_reports,
        "completeness": {
            "requested": sum(r["completeness"]["requested"] for r in step_reports),
            "fetched": sum(r["completeness"]["fetched"] for r in step_reports),
            "kept": sum(r["completeness"]["kept"] for r in step_reports),
            "added": added_count,
            "under_fulfilled": under_fulfilled,
        },
        "items": [catalog.uri_ref(uri) for uri in uris],
        "items_per_request": items_per_request,
        "add_requests": add_requests,
    }

    if under_fulfilled:
        raise _partial(result, step_reports, under_fulfilled)
    return result


def _require_executable_steps(plan: dict[str, Any]) -> None:
    """Refuse a structurally valid plan this version cannot write safely."""
    for index, step in enumerate(plan["steps"]):
        if step["type"] == "album":
            raise MusicDeckError(
                ErrorCode.INVALID_PLAN,
                "This build cannot apply an album step without expanding it into "
                f"tracks at $.steps[{index}].type.",
                "Use a track search step, or wait for a version that explicitly "
                "supports album expansion; no playlist was created.",
                path=f"$.steps[{index}].type",
            )


def _require_valid_existing_target(plan: dict[str, Any]) -> None:
    """Reject a wrong-kind target before searches can spend a request."""
    target = plan["target"]
    if target["kind"] != "existing":
        return
    try:
        catalog.to_id(target["playlist_id"], "playlist")
    except MusicDeckError as error:
        raise MusicDeckError(
            ErrorCode.INVALID_PLAN,
            "The existing plan target must be a Spotify playlist reference.",
            "Pass a playlist id, spotify:playlist URI, or matching Spotify URL; "
            "no Spotify request was sent.",
            path="$.target.playlist_id",
        ) from error


# --------------------------------------------------------------------------- #
# plan.v1 Core 7 -- the target is created or extended
# --------------------------------------------------------------------------- #
def _target(target: dict[str, Any], api: SpotifyClient) -> dict[str, Any]:
    """The playlist to fill: newly created, or the existing one named.

    ``kind: "existing"`` sends **no** ``POST /me/playlists``. That is the whole
    difference between the two kinds, and the reason the caller-supplied
    ``playlist_id`` is the one piece of Spotify content ``plan.v1`` Core 5 lets
    a plan carry.

    The returned block is built from the id with :func:`catalog.item_ref`, so
    ``cli.v1`` Core 4's link is present whatever Spotify chose to answer with --
    and so the document is byte-identical run to run (Core 8), which a verbatim
    echo of Spotify's playlist object would not be.
    """
    if target["kind"] == "existing":
        block = catalog.item_ref("playlist", target["playlist_id"])
        block["created"] = False
        return block

    created = playlists.playlist_create(
        target["name"], description=target.get("description"), client=api
    )
    identity = created.get("id") if isinstance(created, dict) else None
    if not isinstance(identity, str) or not identity.strip():
        raise MusicDeckError(
            "spotify_error",
            "Spotify accepted `POST /me/playlists` but its answer carried no "
            "playlist id, so there is nothing to add the plan's items to.",
            "Run `music-deck playlists` to see whether the playlist was created, "
            "then `music-deck apply` again or add to it directly.",
        )

    block = catalog.item_ref("playlist", identity)
    block["name"] = target["name"]
    block["created"] = True
    return block


# --------------------------------------------------------------------------- #
# plan.v1 Core 7 -- rules apply after fetching
# --------------------------------------------------------------------------- #
def _keep(
    items: Sequence[dict[str, Any]],
    rules: dict[str, Any],
    seen: set[Any],
) -> list[dict[str, Any]]:
    """The items of one step that survive ``rules``, in the order fetched.

    ``seen`` is carried **across** steps on purpose: a dedupe rule that reset at
    each step boundary would let the same track in twice from two steps, which
    is the one thing a caller asking for de-duplication is asking not to happen.
    """
    excluded_artists = {name.strip().casefold() for name in rules["exclude_artists"]}
    excluded_terms = [
        term.casefold() for term in rules["exclude_title_terms"] if term.strip()
    ]
    dedupe = rules["dedupe"]

    kept: list[dict[str, Any]] = []
    for item in items:
        if excluded_artists & _artist_names(item):
            continue
        title = _title(item).casefold()
        if any(term in title for term in excluded_terms):
            continue
        key = _dedupe_key(item, dedupe)
        if key is not None:
            if key in seen:
                continue
            seen.add(key)
        kept.append(item)
    return kept


def _artist_names(item: dict[str, Any]) -> set[str]:
    """Every artist name on an item, case-folded.

    ``exclude_artists`` names artists, so the match is on the whole name rather
    than a substring of it: "Air" must not exclude "Air Supply". Contrast
    ``exclude_title_terms``, which the work item states is a substring match --
    a term is a fragment, a name is not.
    """
    artists = item.get("artists")
    if not isinstance(artists, list):
        return set()
    return {
        artist["name"].strip().casefold()
        for artist in artists
        if isinstance(artist, dict) and isinstance(artist.get("name"), str)
    }


def _primary_artist(item: dict[str, Any]) -> str:
    artists = item.get("artists")
    if isinstance(artists, list) and artists and isinstance(artists[0], dict):
        name = artists[0].get("name")
        if isinstance(name, str):
            return name.strip().casefold()
    return ""


def _title(item: dict[str, Any]) -> str:
    name = item.get("name")
    return name if isinstance(name, str) else ""


def _dedupe_key(item: dict[str, Any], dedupe: str) -> Any | None:
    """The identity two items must share to be duplicates, or None for ``none``.

    ``by_track_id`` falls back to the item's URI when it carries no ``id``: the
    URI *is* the id in another spelling, and treating an item with no ``id`` as
    unique would silently disable the rule for exactly the items most likely to
    be duplicates.
    """
    if dedupe == "none":
        return None
    if dedupe == "by_track_id":
        identity = item.get("id") or item.get("uri")
        return ("id", identity) if isinstance(identity, str) else None
    return ("title+artist", _title(item).casefold(), _primary_artist(item))


def _ordered(items: list[dict[str, Any]], order: str) -> list[dict[str, Any]]:
    """``as_planned`` keeps step order; ``shuffle`` is the one licensed variance.

    ``plan.v1`` Core 8 makes determinism the rule and names ``shuffle`` as its
    only exception, so this is the single place in ``apply`` where two runs may
    legitimately differ -- and it is unseeded on purpose. A seeded shuffle would
    be deterministic and therefore not a shuffle; a caller who wanted the same
    order twice would ask for ``as_planned``.
    """
    if order != "shuffle":
        return list(items)
    shuffled = list(items)
    random.shuffle(shuffled)
    return shuffled


# --------------------------------------------------------------------------- #
# cli.v1 Core 6 -- partial_result carries a completeness block
# --------------------------------------------------------------------------- #
def _partial(
    result: dict[str, Any],
    step_reports: Sequence[dict[str, Any]],
    under_fulfilled: Sequence[int],
) -> MusicDeckError:
    """The refusal for a run that did the work but did not fill the plan."""
    totals = result["completeness"]
    which = ", ".join(str(index) for index in under_fulfilled)
    return MusicDeckError(
        ErrorCode.PARTIAL_RESULT,
        f"The plan asked for {totals['requested']} items and "
        f"{totals['added']} were added: Spotify returned {totals['fetched']} and "
        f"{totals['kept']} survived the plan's rules. Under-fulfilled step(s): "
        f"{which}.",
        "The playlist exists and holds what did land -- read `completeness` for "
        "the per-step requested/fetched/kept, then widen the step's `search`, "
        "lower its `take`, or relax `rules` and apply again.",
        completeness={
            "requested": totals["requested"],
            "fetched": totals["fetched"],
            "kept": totals["kept"],
            "added": totals["added"],
            "under_fulfilled": list(under_fulfilled),
            "steps": [dict(report) for report in step_reports],
        },
        playlist=result["playlist"],
        result=result,
    )


def _client() -> SpotifyClient:
    """The authenticated client, resolved late.

    Imported inside the function rather than at module scope so that importing
    ``apply`` -- which ``cli.py`` does at start-up for every verb -- costs no
    token read and no filesystem touch.
    """
    from music_deck.verbs.auth_verbs import spotify_client

    return spotify_client()


__all__ = ["PLAN_FORMAT", "apply_plan", "read_plan"]
