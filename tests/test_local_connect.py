"""Bounded local Connect observation never reaches a real LAN in this suite."""

from __future__ import annotations

import asyncio
import json
import types

import pytest

from music_deck import cli
from music_deck.errors import ErrorCode, MusicDeckError
from music_deck.local_connect import Advertisement, DiscoveryBatch, Interface, LocalConnectObserver, LocalResponse
from music_deck.verbs import player


NETWORK = Interface("physical0", "192.168.50.2", __import__("ipaddress").ip_network("192.168.50.0/24"))
WEB = [{"id": "web-1", "name": "living room"}]


class Client:
    def __init__(self, payload=None, error=None):
        self.payload = payload if payload is not None else {"devices": WEB}
        self.error = error
        self.calls = []

    def get(self, path):
        self.calls.append(path)
        if self.error:
            raise self.error
        return self.payload


def observer(advertisements, responses=()):
    calls = []

    async def discover(_timeout, _interfaces):
        return advertisements

    async def transport(url, headers, timeout):
        calls.append((url, dict(headers), timeout))
        item = responses[len(calls) - 1]
        return item if isinstance(item, LocalResponse) else LocalResponse(200, json.dumps(item).encode())

    return LocalConnectObserver(discovery=discover, transport=transport, inventory=lambda: [NETWORK]), calls


def test_plain_devices_is_the_legacy_shape_without_importing_local_observer(monkeypatch):
    client = Client()
    monkeypatch.delitem(__import__("sys").modules, "music_deck.local_connect", raising=False)

    result = player.devices(client=client)

    assert result == {"devices": WEB, "count": 1, "active": None}
    assert client.calls == ["/me/player/devices"]
    assert "music_deck.local_connect" not in __import__("sys").modules


def test_authenticated_web_api_read_precedes_local_observer_and_failure_starts_no_lan():
    seen = []

    class Observe:
        def observe(self, *_args, **_kwargs):
            seen.append("lan")
            return {}

    client = Client(error=MusicDeckError(ErrorCode.NOT_AUTHENTICATED, "no", "login"))
    with pytest.raises(MusicDeckError):
        player.devices(client=client, local=True, observer=Observe())
    assert client.calls == ["/me/player/devices"]
    assert seen == []

    api_devices = [
        {"id": "active", "is_active": True, "is_restricted": False, "extra": {"nested": 1}},
        {"id": "restricted", "is_active": False, "is_restricted": True},
    ]
    ready = Client(payload={"devices": api_devices})
    result = player.devices(client=ready, local=True, observer=Observe())
    assert ready.calls == ["/me/player/devices"]
    assert seen == ["lan"]
    assert result["local"] == {}
    assert {key: result[key] for key in ("devices", "count", "active")} == {
        "devices": api_devices,
        "count": 2,
        "active": api_devices[0],
    }


def test_observation_uses_only_exact_safe_getinfo_request_and_sanitizes_metadata():
    item = Advertisement(("192.168.50.40",), 4070, "/spotifyConnect")
    body = {
        "deviceID": "web-1",
        "remoteName": " Kitchen\x1b[31m ",
        "brandDisplayName": "Brand",
        "modelDisplayName": "Model",
        "deviceType": "speaker",
        "status": 101,
        "tokenType": "accessToken",
        "availability": "available",
        "aliases": [{"id": "no-match", "name": "Other"}],
        "publicKey": "must-not-escape",
        "activeUser": "must-not-escape",
        "userName": "must-not-escape",
        "unknown": "must-not-escape",
    }
    local, calls = observer([item], [body])

    result = local.observe(WEB)

    assert calls == [(
        "http://192.168.50.40:4070/spotifyConnect?action=getInfo&version=2.7.1",
        {"Content-Type": "application/x-www-form-urlencoded", "Connection": "close"},
        2,
    )]
    record = result["devices"][0]
    assert record["control_verified"] is False
    assert record["api_match"] == {"id": "web-1", "is_restricted": None}
    assert record["name"] == "Kitchen"
    assert record["aliases"] == ["Other"]
    assert not any(word in json.dumps(record) for word in ("publicKey", "activeUser", "userName", "unknown"))


def test_alias_id_matches_but_names_and_partial_ids_never_do():
    item = Advertisement(("192.168.50.40",), 1400, "/spotifyzc")
    local, _ = observer([item], [{"status": 101, "deviceID": "web", "remoteName": "web-1", "aliases": [{"id": "web-1", "name": "another"}]}])
    assert local.observe(WEB)["devices"][0]["api_match"] == {"id": "web-1", "is_restricted": None}

    local, _ = observer([item], [{"status": 101, "deviceID": "web", "remoteName": "web-1", "aliases": [{"id": "web-1-partial", "name": "living room"}]}])
    assert "api_match" not in local.observe(WEB)["devices"][0]


@pytest.mark.parametrize(
    "advertisement,reason",
    [
        (Advertisement((), 1400, "/ok"), "unresolved_advertisement"),
        (Advertisement(("8.8.8.8",), 1400, "/ok"), "invalid_target"),
        (Advertisement(("127.0.0.1",), 1400, "/ok"), "invalid_target"),
        (Advertisement(("192.168.50.2",), 1400, "/ok"), "invalid_target"),
        (Advertisement(("192.168.51.4",), 1400, "/ok"), "invalid_target"),
        (Advertisement(("192.168.50.255",), 1400, "/ok"), "invalid_target"),
        (Advertisement(("192.168.50.40",), 0, "/ok"), "unsupported_endpoint"),
        (Advertisement(("192.168.50.40",), 1400, "//bad"), "unsupported_endpoint"),
        (Advertisement(("192.168.50.40",), 1400, "/bad?query"), "unsupported_endpoint"),
        (Advertisement(("192.168.50.40",), 1400, "/../bad"), "unsupported_endpoint"),
    ],
)
def test_unsafe_advertisements_are_retained_without_any_http(advertisement, reason):
    local, calls = observer([advertisement], [])
    record = local.observe(WEB)["devices"][0]
    assert record["reason"] == reason
    assert record["control_verified"] is False
    assert calls == []


def test_empty_partial_duplicate_cap_and_http_failures_are_explicit():
    empty, _ = observer([])
    result = empty.observe(WEB)
    assert result["status"] == "complete"
    assert result["count"] == 0

    item = Advertisement(("192.168.50.40",), 1400, "/ok")
    many = [item, item] + [Advertisement((f"192.168.50.{index}",), 1400, "/ok") for index in range(3, 68)]
    capped, calls = observer(many, [{"status": 101}] * 64)
    result = capped.observe(WEB)
    assert result["status"] == "partial"
    assert result["outcomes"]["duplicates"] == 2
    assert result["outcomes"]["record_cap"] == 1
    assert len(calls) == 64

    failed, _ = observer([item], [LocalResponse(400, b"")])
    failed_record = failed.observe(WEB)["devices"][0]
    assert failed_record["reason"] == "http_unavailable"
    assert failed_record["address"] == "192.168.50.40"


def test_restricted_and_invalid_json_are_observations_not_control_claims():
    item = Advertisement(("192.168.50.40",), 1400, "/ok")
    local, _ = observer([item], [{"status": 101}])
    record = local.observe(WEB)["devices"][0]
    assert record["control_verified"] is False
    assert record["status"] == "observed"

    invalid, _ = observer([item], [LocalResponse(200, b"not json")])
    assert invalid.observe(WEB)["devices"][0]["reason"] == "invalid_metadata"


def test_explicit_interface_must_be_eligible_and_library_rejects_silent_local_options():
    local, calls = observer([])
    assert local.observe(WEB, interface="192.168.50.3")["status"] == "unavailable"
    assert calls == []
    with pytest.raises(MusicDeckError):
        player.devices(client=Client(), discovery_timeout_s=4)
    with pytest.raises(MusicDeckError):
        player.devices(client=Client(), local=True, interface="127.0.0.1")
    with pytest.raises(MusicDeckError):
        player.devices(client=Client(), local=True, discovery_timeout_s=16)


def test_cli_options_use_the_library_and_reject_local_options_without_flag(monkeypatch, capsys):
    received = []

    def fake_devices(**kwargs):
        received.append(kwargs)
        return {"devices": [], "count": 0, "active": None, "local": {}}

    monkeypatch.setattr(player, "devices", fake_devices)
    assert cli.main(["devices", "--local", "--discovery-timeout", "4", "--interface", "192.168.50.2"]) == 0
    assert received == [{"local": True, "discovery_timeout_s": 4, "interface": "192.168.50.2"}]
    json.loads(capsys.readouterr().out)
    assert cli.main(["devices", "--discovery-timeout", "4"]) == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == ErrorCode.USAGE


def test_deadline_retains_completed_records_and_cancels_pending(monkeypatch):
    monkeypatch.setattr("music_deck.local_connect.OPERATION_TIMEOUT_S", 0.01)
    done = Advertisement(("192.168.50.40",), 1400, "/ok", "done")
    late = Advertisement(("192.168.50.41",), 1400, "/ok", "late")
    closed = []

    async def transport(url, _headers, _timeout):
        if ".40:" in url:
            return LocalResponse(200, b'{"status":101,"remoteName":"done"}')
        try:
            await asyncio.sleep(1)
        finally:
            closed.append("cancelled")

    local = LocalConnectObserver(
        discovery=lambda *_: DiscoveryBatch((done, late)),
        transport=transport,
        inventory=lambda: [NETWORK],
    )
    result = local.observe(WEB, discovery_timeout_s=0)
    assert result["status"] == "partial"
    assert {row.get("service_name") for row in result["devices"]} == {"done", "late"}
    assert any(row.get("reason") == "metadata_deadline" for row in result["devices"])
    assert result["outcomes"]["metadata_deadline"] == 1
    assert closed == ["cancelled"]


def test_getinfo_concurrency_is_bounded_and_all_records_survive():
    from music_deck.local_connect import MAX_METADATA_CONCURRENCY

    active, peak, finished = 0, 0, 0
    ads = tuple(
        Advertisement((f"192.168.50.{number}",), 1400, "/ok", f"receiver-{number}")
        for number in range(10, 34)
    )

    async def transport(_url, _headers, _timeout):
        nonlocal active, peak, finished
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.001)
            finished += 1
            return LocalResponse(200, b'{"status":101}')
        finally:
            active -= 1

    local = LocalConnectObserver(
        discovery=lambda *_: DiscoveryBatch(ads),
        transport=transport,
        inventory=lambda: [NETWORK],
    )
    result = local.observe(WEB)
    assert peak == MAX_METADATA_CONCURRENCY
    assert active == 0
    assert finished == len(ads)
    assert result["count"] == len(ads)
    assert result["status"] == "complete"


def test_credential_substrings_and_protocol_shape_never_escape(monkeypatch):
    key = "synthetic-key-for-test"
    monkeypatch.setattr(
        "music_deck.prompt_boundary.machine_credentials",
        lambda: (types.SimpleNamespace(value=key),),
    )
    local, _ = observer(
        [Advertisement(("192.168.50.40",), 1400, "/ok", f"svc-{key}")],
        [{"status": 101, "remoteName": f"speaker {key} name", "aliases": [{"name": f"alias {key}"}]}],
    )
    document = local.observe(WEB)
    assert key not in json.dumps(document)
    assert document["devices"][0]["status"] == "observed"


@pytest.mark.parametrize("announcements", [0, 65])
def test_real_zeroconf_backend_accepts_keyword_callback_and_closes(monkeypatch, announcements):
    import music_deck.local_connect as module

    events, calls = [], []
    added = object()
    class Info:
        port = 1400
        properties = {b"CPath": b"/spotifyzc"}
        def parsed_addresses(self, version):
            calls.append(version)
            return ["192.168.50.40"]
    class ZC:
        zeroconf = object()
        async def async_get_service_info(self, service_type, name, timeout):
            events.append(("resolve", service_type, name, timeout))
            return Info()
        async def async_close(self): events.append("close")
    class Browser:
        def __init__(self, _zc, service_type, handlers):
            events.append(("browser", service_type))
            for number in range(announcements):
                handlers[0](
                    zeroconf=_zc,
                    service_type=service_type,
                    name=f"synthetic-{number}._spotify-connect._tcp.local.",
                    state_change=added,
                )
        async def async_cancel(self): events.append("cancel")
    zeroconf = types.ModuleType("zeroconf")
    zeroconf.IPVersion = types.SimpleNamespace(V4Only="v4")
    zeroconf.ServiceStateChange = types.SimpleNamespace(Added=added)
    async_mod = types.ModuleType("zeroconf.asyncio")
    async_mod.AsyncZeroconf = lambda **kwargs: (calls.append(kwargs) or ZC())
    async_mod.AsyncServiceBrowser = Browser
    monkeypatch.setitem(__import__("sys").modules, "zeroconf", zeroconf)
    monkeypatch.setitem(__import__("sys").modules, "zeroconf.asyncio", async_mod)
    sleep = asyncio.sleep
    monkeypatch.setattr(module.asyncio, "sleep", lambda _seconds: sleep(0))
    batch = asyncio.run(module._zeroconf_discovery(1, [NETWORK]))
    assert calls[0] == {"interfaces": ["192.168.50.2"], "ip_version": "v4"}
    if announcements:
        assert calls[1] == "v4"
    expected = min(announcements, 64)
    assert len(batch.advertisements) == expected
    assert batch.record_cap is (announcements > 64)
    assert len([event for event in events if isinstance(event, tuple) and event[0] == "resolve"]) == expected
    assert events[-2:] == ["cancel", "close"]


def test_linux_inventory_requires_up_multicast_physical_and_private(monkeypatch):
    import music_deck.local_connect as module

    class IP:
        def __init__(self, ip): self.ip, self.network_prefix = ip, 24
    class Adapter:
        def __init__(self, name, ip): self.nice_name, self.ips = name, [IP(ip)]
    flags = {"good": "0x1001", "down": "0x1000", "nomcast": "0x1"}
    class Path:
        def __init__(self, value): self.value = str(value)
        def __truediv__(self, other): return Path(f"{self.value}/{other}")
        def read_text(self, **_): return flags[self.value.split("/")[-2]]
        def exists(self): return self.value.endswith("/good/device")
    monkeypatch.setattr(module.sys, "platform", "linux")
    monkeypatch.setattr(module, "Path", Path)
    monkeypatch.setattr(
        __import__("ifaddr"), "get_adapters",
        lambda: [Adapter("good", "192.168.50.2"), Adapter("down", "192.168.50.3"), Adapter("nomcast", "192.168.50.4"), Adapter("docker0", "192.168.50.5"), Adapter("good", "8.8.8.8")],
    )
    assert module.eligible_interfaces() == [
        Interface("good", "192.168.50.2", __import__("ipaddress").ip_network("192.168.50.0/24"))
    ]
    monkeypatch.setattr(module.sys, "platform", "darwin")
    assert module.eligible_interfaces() == []