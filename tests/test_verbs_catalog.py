"""`search` and the five single-item lookups.

Contracts under test: ``cli.v1`` Core 4 (one document; every item linked),
``boundary.v1`` Core 7 (single-item GETs only, and the 10-per-request search
cap February 2026 introduced).
"""

from __future__ import annotations

import pytest
from spotify_fakes import (
    FakeTransport,
    install_token,
    json_response,
    run_cli,
    token_document,
    use_fake_transport,
)
from verb_fixtures import (
    ALBUM_ID,
    ARTIST_ID,
    TRACK_ID,
    assert_every_item_is_linked,
    path_of,
    query_of,
    search_page,
    sent,
    track_item,
)

from music_deck.errors import EXIT_REFUSAL, EXIT_SUCCESS, ErrorCode
from music_deck.http import SEARCH_PAGE_CAP
from music_deck.verbs import catalog


@pytest.fixture
def signed_in(monkeypatch, tmp_path):
    install_token(monkeypatch, tmp_path, token_document())
    return tmp_path


def _tracks(count: int, start: int = 0) -> dict:
    """A search page of ``count`` distinct tracks."""
    return search_page(
        [track_item(f"{start + index:022d}".replace("0", "a", 1), f"track {start + index}")
         for index in range(count)]
    )


# --------------------------------------------------------------------------- #
# The February 2026 search cap: 10 per request, paged
# --------------------------------------------------------------------------- #
def test_asking_for_25_results_pages_at_ten_per_request(signed_in, monkeypatch, capsys):
    """The acceptance criterion, verbatim: requests of limit <= 10, until 25."""
    transport = use_fake_transport(
        monkeypatch,
        FakeTransport(
            [
                json_response(200, _tracks(10, 0)),
                json_response(200, _tracks(10, 10)),
                json_response(200, _tracks(5, 20)),
            ]
        ),
    )

    code, document, _ = run_cli(capsys, "search", "aphex twin", "--limit", "25")

    assert code == EXIT_SUCCESS
    assert document["returned"] == 25
    assert document["requested"] == 25
    assert len(document["results"]) == 25

    limits = [int(query_of(request.url)["limit"]) for request in transport.requests]
    offsets = [int(query_of(request.url)["offset"]) for request in transport.requests]
    assert limits == [10, 10, 5], limits
    assert max(limits) <= SEARCH_PAGE_CAP
    assert offsets == [0, 10, 20], offsets
    assert {path_of(request.url) for request in transport.requests} == {"/search"}


def test_paging_stops_at_exhaustion_rather_than_asking_forever(
    signed_in, monkeypatch, capsys
):
    """A short page means Spotify ran out; asking again would be a wasted request."""
    transport = use_fake_transport(
        monkeypatch,
        FakeTransport(
            [json_response(200, _tracks(10, 0)), json_response(200, _tracks(4, 10))]
        ),
    )

    code, document, _ = run_cli(capsys, "search", "obscure", "--limit", "25")

    assert code == EXIT_SUCCESS
    assert len(transport.requests) == 2
    assert document["requested"] == 25
    assert document["returned"] == 14, "a short answer must say so, not look complete"


def test_search_asks_for_the_type_the_caller_named(signed_in, monkeypatch, capsys):
    transport = use_fake_transport(
        monkeypatch, FakeTransport([json_response(200, search_page([], "album"))])
    )

    code, document, _ = run_cli(capsys, "search", "ambient", "--type", "album")

    assert code == EXIT_SUCCESS
    assert query_of(transport.requests[0].url)["type"] == "album"
    assert document["type"] == "album"
    assert document["returned"] == 0


def test_search_results_gain_the_link_spotify_left_out(signed_in, monkeypatch, capsys):
    """cli.v1 Core 4, on nested items: the track, its album, and its artist."""
    use_fake_transport(
        monkeypatch, FakeTransport([json_response(200, search_page([track_item()]))])
    )

    _code, document, _ = run_cli(capsys, "search", "xtal")

    # The track, its album, and an artist on each of them: four linked items.
    assert assert_every_item_is_linked(document, at_least=4) == 4
    found = document["results"][0]
    assert found["external_urls"]["spotify"].endswith(f"/track/{TRACK_ID}")
    assert found["album"]["external_urls"]["spotify"].endswith(f"/album/{ALBUM_ID}")
    assert found["artists"][0]["external_urls"]["spotify"].endswith(f"/artist/{ARTIST_ID}")


# --------------------------------------------------------------------------- #
# Single-item lookups -- boundary.v1 Core 7
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "reference",
    [
        TRACK_ID,
        f"spotify:track:{TRACK_ID}",
        f"https://open.spotify.com/track/{TRACK_ID}",
        f"https://open.spotify.com/track/{TRACK_ID}?si=abc123",
        f"https://open.spotify.com/intl-de/track/{TRACK_ID}",
    ],
    ids=["bare id", "uri", "url", "url with si", "localised url"],
)
def test_every_reference_form_resolves_to_the_same_single_item_request(
    signed_in, monkeypatch, capsys, reference
):
    transport = use_fake_transport(
        monkeypatch, FakeTransport([json_response(200, track_item())])
    )

    code, _document, _ = run_cli(capsys, "track", reference)

    assert code == EXIT_SUCCESS
    assert sent(transport) == [("GET", f"/tracks/{TRACK_ID}")]


def test_a_reference_of_the_wrong_kind_refuses_before_a_request(
    signed_in, monkeypatch, capsys
):
    """`music-deck album spotify:track:...` is a mistake worth catching for free."""
    transport = use_fake_transport(monkeypatch, FakeTransport())

    code, document, _ = run_cli(capsys, "album", f"spotify:track:{TRACK_ID}")

    assert code == EXIT_REFUSAL
    assert document["error"]["code"] == ErrorCode.USAGE
    assert "track" in document["error"]["message"]
    assert transport.requests == [], "nothing should reach the network"


@pytest.mark.parametrize(
    "reference", ["", "   ", "spotify:track", "spotify:nonsense:abc", "https://example.com/track/x"]
)
def test_an_unusable_reference_refuses_with_a_remedy(
    signed_in, monkeypatch, capsys, reference
):
    use_fake_transport(monkeypatch, FakeTransport())

    code, document, _ = run_cli(capsys, "track", reference)

    assert code == EXIT_REFUSAL
    assert document["error"]["code"] == ErrorCode.USAGE
    assert document["error"]["remedy"].strip()


def test_a_zero_limit_refuses_rather_than_returning_nothing(signed_in, monkeypatch, capsys):
    use_fake_transport(monkeypatch, FakeTransport())

    code, document, _ = run_cli(capsys, "search", "anything", "--limit", "0")

    assert code == EXIT_REFUSAL
    assert document["error"]["code"] == ErrorCode.USAGE


def test_an_unknown_search_type_refuses_in_the_library_too(signed_in, monkeypatch):
    """The CLI's `choices` catches this; the library must catch it as well.

    ``cli.v1`` Core 7 -- "the library is the tool" -- means a Python caller gets
    the same refusal, not a request built from an unknown type.
    """
    use_fake_transport(monkeypatch, FakeTransport())

    with pytest.raises(Exception) as raised:
        catalog.search("anything", kind="podcast")

    assert getattr(raised.value, "code", None) == ErrorCode.USAGE


# --------------------------------------------------------------------------- #
# The helpers the other verb modules build on
# --------------------------------------------------------------------------- #
def test_batches_cuts_at_the_size_and_keeps_the_order():
    values = list(range(250))
    chunks = catalog.batches(values, 100)
    assert [len(chunk) for chunk in chunks] == [100, 100, 50]
    assert [value for chunk in chunks for value in chunk] == values


def test_a_bare_id_is_refused_where_the_kind_cannot_be_inferred():
    """`PUT /me/library` takes URIs; a bare id would have to be guessed at."""
    with pytest.raises(Exception) as raised:
        catalog.to_any_uri(TRACK_ID)
    assert getattr(raised.value, "code", None) == ErrorCode.USAGE
    assert "spotify:track" in raised.value.remedy


def test_item_ref_carries_the_link_for_a_write_spotify_answers_empty():
    reference = catalog.item_ref("playlist", "37i9dQZF1DXcBWIGoYBM5M")
    assert reference["uri"] == "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M"
    assert reference["external_urls"]["spotify"] == (
        "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
    )
