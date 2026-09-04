"""Every refusal this lane can reach, produced by a mocked Spotify response.

The honesty bar for this file, taken from the work item: *"not proven" looks
like refusal codes asserted by reading the code rather than by a mocked response
producing the envelope.* So every test below starts from bytes a real Spotify
could return -- a status, headers, and a body copied from Spotify's own
documented shapes -- and ends at the JSON document the ``music-deck`` binary
prints and the number it exits with.

Contracts served: ``cli.v1`` Core 4 (one JSON document; the envelope), Core 5
(exit codes), Core 6 (the frozen vocabulary and its triggers), ``boundary.v1``
Core 5 (every verb but ``login`` refuses ``not_authenticated``).

Nothing here opens a socket: ``use_fake_transport`` replaces the only class that
can, in both namespaces that build one.
"""

from __future__ import annotations

import json

import pytest
from spotify_fakes import (
    FakeTransport,
    install_token,
    json_response,
    record_sleeps,
    run_cli,
    run_probe,
    spotify_error,
    token_document,
    use_fake_transport,
)

from music_deck.errors import EXIT_REFUSAL, EXIT_SUCCESS, ErrorCode
from music_deck.verbs.auth_verbs import spotify_client

ME_PAYLOAD = {
    "id": "deckuser",
    "display_name": "Deck User",
    "uri": "spotify:user:deckuser",
    "type": "user",
}


@pytest.fixture
def transport(monkeypatch):
    return use_fake_transport(monkeypatch, FakeTransport())


@pytest.fixture
def signed_in(monkeypatch, tmp_path):
    """A stored token that is not expired and can be refreshed."""
    return install_token(monkeypatch, tmp_path, token_document())


def envelope_of(document) -> dict:
    assert isinstance(document, dict) and "error" in document, document
    error = document["error"]
    # cli.v1 Core 4: the three keys are always present, always non-empty.
    assert error["code"] and error["message"] and error["remedy"]
    return error


# --------------------------------------------------------------------------- #
# not_authenticated -- boundary.v1 Core 5
# --------------------------------------------------------------------------- #
def test_a_verb_with_no_token_at_all_refuses_before_any_request(
    monkeypatch, tmp_path, capsys, transport
):
    """boundary.v1 Core 5, and the reason it costs nothing: no request is sent."""
    install_token(monkeypatch, tmp_path, None)

    code, document, _ = run_cli(capsys, "whoami")

    assert code == EXIT_REFUSAL
    error = envelope_of(document)
    assert error["code"] == ErrorCode.NOT_AUTHENTICATED
    assert "music-deck login" in error["remedy"]
    assert transport.requests == [], "a refusal must not cost a Spotify request"


def test_401_with_no_refresh_token_is_not_authenticated(
    monkeypatch, tmp_path, capsys, transport
):
    """Spotify rejected the bearer and there is nothing to renew it with."""
    install_token(monkeypatch, tmp_path, token_document(refresh_token=None))
    transport.queue(
        json_response(401, spotify_error(401, "The access token expired"))
    )

    code, document, _ = run_cli(capsys, "whoami")

    assert code == EXIT_REFUSAL
    assert envelope_of(document)["code"] == ErrorCode.NOT_AUTHENTICATED
    assert len(transport.requests) == 1


# --------------------------------------------------------------------------- #
# reauthorization_required
# --------------------------------------------------------------------------- #
def test_an_expired_token_with_nothing_to_renew_it_is_not_authenticated(
    monkeypatch, tmp_path, capsys, transport
):
    """Access tokens last an hour. Knowing it is dead and having no refresh token
    is a refusal that costs nothing -- not a request sent to be told so."""
    install_token(
        monkeypatch, tmp_path, token_document(expires_in_s=-10, refresh_token=None)
    )

    code, document, _ = run_cli(capsys, "whoami")

    assert code == EXIT_REFUSAL
    assert envelope_of(document)["code"] == ErrorCode.NOT_AUTHENTICATED
    assert transport.requests == []


def test_an_expired_token_is_renewed_before_the_request_not_after_a_401(
    monkeypatch, tmp_path, capsys, transport
):
    """The cheap path: the stored `expires_at` is in the past, so the renewal
    happens first and the request is spent once, not twice."""
    install_token(monkeypatch, tmp_path, token_document(expires_in_s=-10))
    transport.queue(
        json_response(
            200, {"access_token": "renewed-early", "token_type": "Bearer", "expires_in": 3600}
        ),
        json_response(200, ME_PAYLOAD),
    )

    code, document, _ = run_cli(capsys, "whoami")

    assert code == EXIT_SUCCESS
    assert document["account"]["id"] == "deckuser"
    assert len(transport.requests) == 2
    assert "accounts.spotify.com/api/token" in transport.urls()[0]
    assert transport.requests[1].headers["Authorization"] == "Bearer renewed-early"


def test_401_whose_refresh_is_rejected_is_reauthorization_required(
    signed_in, capsys, transport
):
    """Spotify: the token endpoint answers `invalid_grant` for a dead refresh
    token, and its guidance is to re-authorise rather than retry."""
    transport.queue(
        json_response(401, spotify_error(401, "The access token expired")),
        json_response(
            400,
            {
                "error": "invalid_grant",
                "error_description": "Refresh token revoked",
            },
        ),
    )

    code, document, _ = run_cli(capsys, "whoami")

    assert code == EXIT_REFUSAL
    error = envelope_of(document)
    assert error["code"] == ErrorCode.REAUTHORIZATION_REQUIRED
    assert "music-deck login" in error["remedy"]
    assert "accounts.spotify.com/api/token" in transport.urls()[1]


def test_a_token_past_the_six_month_wall_refuses_before_any_request(
    monkeypatch, tmp_path, capsys, transport
):
    """B section 1.4: six months from authorisation, and refreshing never
    extended it. Detected from the stored `authorized_at`, not from a 401."""
    install_token(monkeypatch, tmp_path, token_document(authorized_days_ago=200))

    code, document, _ = run_cli(capsys, "whoami")

    assert code == EXIT_REFUSAL
    assert envelope_of(document)["code"] == ErrorCode.REAUTHORIZATION_REQUIRED
    assert transport.requests == []


def test_401_then_a_good_refresh_retries_once_and_succeeds(signed_in, capsys, transport):
    """The other half of the same seam: a renewable 401 is not a refusal at all."""
    transport.queue(
        json_response(401, spotify_error(401, "The access token expired")),
        json_response(
            200,
            {"access_token": "renewed-token", "token_type": "Bearer", "expires_in": 3600},
        ),
        json_response(200, ME_PAYLOAD),
    )

    code, document, _ = run_cli(capsys, "whoami")

    assert code == EXIT_SUCCESS
    assert document["account"]["id"] == "deckuser"
    assert len(transport.requests) == 3
    assert transport.requests[2].headers["Authorization"] == "Bearer renewed-token"
    # The renewed token was stored, so the next run does not repeat the round trip.
    assert json.loads(signed_in.read_text())["access_token"] == "renewed-token"


def test_a_refresh_never_moves_the_six_month_wall(signed_in, capsys, transport):
    """B section 1.4: "Refreshing an access token does not extend the refresh
    token's lifetime." So `authorized_at` must survive a refresh unchanged."""
    before = json.loads(signed_in.read_text())["authorized_at"]
    transport.queue(
        json_response(401, spotify_error(401, "expired")),
        json_response(
            200, {"access_token": "renewed", "token_type": "Bearer", "expires_in": 3600}
        ),
        json_response(200, ME_PAYLOAD),
    )

    run_cli(capsys, "whoami")

    assert json.loads(signed_in.read_text())["authorized_at"] == before


# --------------------------------------------------------------------------- #
# not_allowlisted / premium_required -- one status code, two meanings
# --------------------------------------------------------------------------- #
def test_403_is_not_allowlisted(signed_in, capsys, transport):
    """A Development Mode app is capped at 5 authorised users; everyone else
    gets 403. Spotify offers no endpoint that answers "am I allowlisted?"."""
    transport.queue(json_response(403, spotify_error(403, "Forbidden")))

    code, document, _ = run_cli(capsys, "whoami")

    assert code == EXIT_REFUSAL
    error = envelope_of(document)
    assert error["code"] == ErrorCode.NOT_ALLOWLISTED
    assert "allowlist" in error["remedy"].lower()


def test_403_records_the_allowlist_signal_with_every_id_redacted(
    monkeypatch, tmp_path, capsys, transport
):
    """`check` reports "a 403 was seen"; boundary.v1 Core 8 forbids storing
    Spotify content, so the endpoint is recorded as a shape, not a target."""
    install_token(monkeypatch, tmp_path, token_document())
    transport.queue(json_response(403, spotify_error(403, "Forbidden")))

    code, _, _ = run_probe(
        monkeypatch, capsys, lambda: spotify_client().get("/albums/4aawyAB9vmqN3uQ7FjRGTy")
    )

    assert code == EXIT_REFUSAL
    recorded = json.loads((tmp_path / "state" / "last-403.json").read_text())
    assert recorded["endpoint"] == "/albums/{id}"
    assert "4aawyAB9vmqN3uQ7FjRGTy" not in json.dumps(recorded)


def test_403_with_reason_premium_required_is_premium_required(
    signed_in, capsys, transport
):
    transport.queue(
        json_response(
            403, spotify_error(403, "Player command failed: Premium required", "PREMIUM_REQUIRED")
        )
    )

    code, document, _ = run_cli(capsys, "whoami")

    assert code == EXIT_REFUSAL
    assert envelope_of(document)["code"] == ErrorCode.PREMIUM_REQUIRED


def test_403_on_a_player_write_is_premium_required_even_with_no_reason(
    monkeypatch, tmp_path, capsys, transport
):
    """B section 9: `product` was removed from GET /me in February 2026, so a
    tool cannot pre-check Premium -- it learns from the 403 on the write."""
    install_token(monkeypatch, tmp_path, token_document())
    transport.queue(json_response(403, spotify_error(403, "Forbidden")))

    code, document, _ = run_probe(
        monkeypatch, capsys, lambda: spotify_client().put("/me/player/play")
    )

    assert code == EXIT_REFUSAL
    assert envelope_of(document)["code"] == ErrorCode.PREMIUM_REQUIRED
    # Not an allowlist signal: a Premium refusal says nothing about allowlisting.
    assert not (tmp_path / "state" / "last-403.json").exists()


# --------------------------------------------------------------------------- #
# no_active_device -- the 204 that is not a success
# --------------------------------------------------------------------------- #
def test_204_on_the_player_read_is_no_active_device(
    monkeypatch, tmp_path, capsys, transport
):
    """B section 4.7: GET /me/player returns 200 *or* 204; 204 means nothing is
    active. A tool that treated it as an empty success would report silence as
    a working player."""
    install_token(monkeypatch, tmp_path, token_document())
    transport.queue(json_response(204))

    code, document, _ = run_probe(
        monkeypatch, capsys, lambda: spotify_client().get("/me/player")
    )

    assert code == EXIT_REFUSAL
    error = envelope_of(document)
    assert error["code"] == ErrorCode.NO_ACTIVE_DEVICE
    assert "transfer" in error["remedy"]


def test_204_on_a_player_write_is_an_ordinary_success(
    monkeypatch, tmp_path, transport
):
    """The same status code, the opposite meaning: every Player write answers
    204 when it worked."""
    install_token(monkeypatch, tmp_path, token_document())
    transport.queue(json_response(204))

    assert spotify_client().put("/me/player/pause") == {}


# --------------------------------------------------------------------------- #
# playlist_items_unavailable
# --------------------------------------------------------------------------- #
def test_a_forbidden_playlist_items_response_is_playlist_items_unavailable(
    monkeypatch, tmp_path, capsys, transport
):
    """February 2026: "Playlist contents (items) are only returned for playlists
    the user owns or collaborates on."""
    install_token(monkeypatch, tmp_path, token_document())
    transport.queue(
        json_response(403, spotify_error(403, "Insufficient client scope"))
    )

    code, document, _ = run_probe(
        monkeypatch,
        capsys,
        lambda: spotify_client().get("/playlists/37i9dQZF1DXcBWIGoYBM5M/items"),
    )

    assert code == EXIT_REFUSAL
    error = envelope_of(document)
    assert error["code"] == ErrorCode.PLAYLIST_ITEMS_UNAVAILABLE
    assert "own" in error["remedy"]


# --------------------------------------------------------------------------- #
# rate_limited / quota_exceeded -- one status code, two mechanisms
# --------------------------------------------------------------------------- #
def test_429_honours_retry_after_for_exactly_one_retry_then_refuses(
    monkeypatch, signed_in, capsys, transport
):
    """cli.v1 Core 6: "honours `Retry-After` for at most one bounded retry, then
    refuses carrying `retry_after_s` -- never an unbounded wait."."""
    slept = record_sleeps(monkeypatch)
    transport.queue(
        json_response(429, spotify_error(429, "API rate limit exceeded"), {"Retry-After": "2"}),
        json_response(429, spotify_error(429, "API rate limit exceeded"), {"Retry-After": "7"}),
    )

    code, document, _ = run_cli(capsys, "whoami")

    assert code == EXIT_REFUSAL
    error = envelope_of(document)
    assert error["code"] == ErrorCode.RATE_LIMITED
    assert error["retry_after_s"] == 7.0
    assert slept == [2.0], "exactly one bounded wait, of exactly the stated length"
    assert len(transport.requests) == 2, "exactly one retry"


def test_429_with_a_retry_after_longer_than_the_bound_is_never_slept_on(
    monkeypatch, signed_in, capsys, transport
):
    """A wait the tool will not sit through is handed back to the caller instead."""
    slept = record_sleeps(monkeypatch)
    transport.queue(
        json_response(429, spotify_error(429, "rate limited"), {"Retry-After": "600"})
    )

    code, document, _ = run_cli(capsys, "whoami")

    assert code == EXIT_REFUSAL
    error = envelope_of(document)
    assert error["code"] == ErrorCode.RATE_LIMITED
    assert error["retry_after_s"] == 600.0
    assert slept == []
    assert len(transport.requests) == 1


def test_429_with_reason_quota_exceeded_is_never_retried(
    monkeypatch, signed_in, capsys, transport
):
    """July 2026 changelog: the quota 429 carries `"reason": "QUOTA_EXCEEDED"` --
    a different enforcement mechanism, which waiting does not clear."""
    slept = record_sleeps(monkeypatch)
    transport.queue(
        json_response(
            429,
            spotify_error(429, "Quota exceeded", "QUOTA_EXCEEDED"),
            {"Retry-After": "2"},
        )
    )

    code, document, _ = run_cli(capsys, "whoami")

    assert code == EXIT_REFUSAL
    error = envelope_of(document)
    assert error["code"] == ErrorCode.QUOTA_EXCEEDED
    assert "will not clear it" in error["remedy"]
    assert slept == [], "a quota is not a wait"
    assert len(transport.requests) == 1


# --------------------------------------------------------------------------- #
# partial_result -- reachable in this build through `disconnect`
# --------------------------------------------------------------------------- #
def test_partial_result_carries_a_completeness_block(monkeypatch, tmp_path, capsys):
    """cli.v1 Core 6: "carrying a `completeness` block naming what succeeded and
    failed -- never a silently truncated success"."""
    install_token(monkeypatch, tmp_path, token_document())
    (tmp_path / "state" / "cached-track.json").write_text("{}", encoding="utf-8")

    import music_deck.verbs.auth_verbs as verbs

    real_unlink = type(tmp_path).unlink

    def refuse_one(self, *args, **kwargs):
        if self.name == "cached-track.json":
            raise OSError(13, "Permission denied")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(type(tmp_path), "unlink", refuse_one)
    assert verbs  # the verb under test is the shipping one, not a stand-in

    code, document, _ = run_cli(capsys, "disconnect")

    assert code == EXIT_REFUSAL
    error = envelope_of(document)
    assert error["code"] == ErrorCode.PARTIAL_RESULT
    assert error["completeness"]["failed"] == 1
    assert error["completeness"]["deleted"] >= 1


# --------------------------------------------------------------------------- #
# cli.v1 Core 4 -- every item carries its own link
# --------------------------------------------------------------------------- #
def test_every_emitted_item_carries_its_own_open_spotify_link(
    signed_in, capsys, transport
):
    """Spotify does not always include `external_urls`; the tool always does."""
    transport.queue(
        json_response(
            200,
            {
                "id": "deckuser",
                "uri": "spotify:user:deckuser",
                "top": {"uri": "spotify:track:4iV5W9uYEdYUVa79Axb7Rh"},
            },
        )
    )

    code, document, _ = run_cli(capsys, "whoami")

    assert code == EXIT_SUCCESS
    account = document["account"]
    assert account["external_urls"]["spotify"] == "https://open.spotify.com/user/deckuser"
    assert (
        account["top"]["external_urls"]["spotify"]
        == "https://open.spotify.com/track/4iV5W9uYEdYUVa79Axb7Rh"
    )


def test_a_link_spotify_supplied_is_never_overwritten(signed_in, capsys, transport):
    transport.queue(
        json_response(
            200,
            {
                "uri": "spotify:user:deckuser",
                "external_urls": {"spotify": "https://open.spotify.com/user/canonical"},
            },
        )
    )

    _, document, _ = run_cli(capsys, "whoami")

    assert (
        document["account"]["external_urls"]["spotify"]
        == "https://open.spotify.com/user/canonical"
    )


# --------------------------------------------------------------------------- #
# Paging -- the February 2026 search cap
# --------------------------------------------------------------------------- #
def test_paging_search_never_asks_for_more_than_ten_at_a_time(
    monkeypatch, tmp_path, transport
):
    """February 2026 tightened search to `limit` max 10, default 5 (was 50/20).
    Asking for 25 is three requests, not one rejected one."""
    install_token(monkeypatch, tmp_path, token_document())
    page = lambda n: json_response(  # noqa: E731 - a table of pages reads better inline
        200, {"tracks": {"items": [{"uri": f"spotify:track:{i}"} for i in range(n)]}}
    )
    transport.queue(page(10), page(10), page(5))

    items = spotify_client().paginate("/search", limit=25, params={"q": "hooks", "type": "track"})

    assert len(items) == 25
    limits = [url.split("limit=")[1].split("&")[0] for url in transport.urls()]
    assert limits == ["10", "10", "5"]


def test_paging_stops_early_when_spotify_runs_out(monkeypatch, tmp_path, transport):
    install_token(monkeypatch, tmp_path, token_document())
    transport.queue(
        json_response(200, {"items": [{"uri": f"spotify:track:{i}"} for i in range(3)]})
    )

    items = spotify_client().paginate("/me/playlists", limit=50)

    assert len(items) == 3
    assert len(transport.requests) == 1


# --------------------------------------------------------------------------- #
# The roll-up: which frozen codes this lane can actually reach
# --------------------------------------------------------------------------- #
REACHED_BY_THIS_LANE = {
    ErrorCode.NOT_AUTHENTICATED,
    ErrorCode.REAUTHORIZATION_REQUIRED,
    ErrorCode.NOT_ALLOWLISTED,
    ErrorCode.PREMIUM_REQUIRED,
    ErrorCode.NO_ACTIVE_DEVICE,
    ErrorCode.RATE_LIMITED,
    ErrorCode.QUOTA_EXCEEDED,
    ErrorCode.PLAYLIST_ITEMS_UNAVAILABLE,
    ErrorCode.PARTIAL_RESULT,
}


def test_every_code_this_file_claims_to_reach_has_a_test_that_reaches_it():
    """A guard against this list drifting away from the tests above it.

    ``invalid_plan`` is the tenth frozen code and is not reachable from the
    Spotify boundary at all -- ``plan.v1`` decides it, and ``apply`` raises it
    (MD-5). It is deliberately absent rather than silently forgotten.
    """
    source = open(__file__, encoding="utf-8").read()
    for code in REACHED_BY_THIS_LANE:
        assert f'== ErrorCode.{code.upper()}' in source or f'"{code}"' in source
    assert ErrorCode.INVALID_PLAN not in REACHED_BY_THIS_LANE
