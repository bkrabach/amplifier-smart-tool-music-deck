"""Bounded, read-only Linux IPv4 observation of Spotify Connect advertisements."""
from __future__ import annotations

import asyncio
import inspect
import ipaddress
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, Mapping, Sequence

SERVICE_TYPE = "_spotify-connect._tcp.local."
MAX_RECORDS, MAX_METADATA_CONCURRENCY = 64, 8
REQUEST_TIMEOUT_S, MAX_BODY_BYTES, OPERATION_TIMEOUT_S = 2, 64 * 1024, 20
_VIRTUAL = ("lo", "tailscale", "docker", "veth", "br-", "br", "podman", "cni", "tun", "tap", "wg", "virbr")


@dataclass(frozen=True)
class Interface:
    name: str
    address: str
    network: ipaddress.IPv4Network


@dataclass(frozen=True)
class Advertisement:
    addresses: tuple[str, ...] = ()
    port: int | None = None
    path: str | None = None
    service_name: str = ""


@dataclass(frozen=True)
class DiscoveryBatch:
    advertisements: tuple[Advertisement, ...]
    record_cap: bool = False
    deadline: bool = False


@dataclass(frozen=True)
class LocalResponse:
    status: int
    body: bytes
    body_capped: bool = False


Discovery = Callable[[int, Sequence[Interface]], Awaitable[Iterable[Advertisement] | DiscoveryBatch] | Iterable[Advertisement] | DiscoveryBatch]
Transport = Callable[[str, Mapping[str, str], float], Awaitable[LocalResponse] | LocalResponse]
Inventory = Callable[[], Iterable[Interface]]


def _rfc1918(value: str) -> ipaddress.IPv4Address | None:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return None
    private = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
    return address if isinstance(address, ipaddress.IPv4Address) and any(address in ipaddress.ip_network(net) for net in private) else None


def eligible_interfaces() -> list[Interface]:
    """Return only Linux UP+MULTICAST NICs backed by a physical device."""
    if not sys.platform.startswith("linux"):
        return []
    import ifaddr
    found: list[Interface] = []
    for adapter in ifaddr.get_adapters():
        name = adapter.nice_name
        root = Path("/sys/class/net") / name
        if name.lower().startswith(_VIRTUAL):
            continue
        try:
            flags = int((root / "flags").read_text(encoding="ascii").strip(), 16)
        except OSError:
            continue
        if not flags & 0x1 or not flags & 0x1000 or not (root / "device").exists():
            continue
        for item in adapter.ips:
            address = _rfc1918(item.ip) if isinstance(item.ip, str) else None
            if address:
                found.append(Interface(name, str(address), ipaddress.ip_network(f"{address}/{int(item.network_prefix)}", strict=False)))
    return found


def _contains_credential(value: object, credentials: tuple[str, ...]) -> bool:
    return isinstance(value, str) and any(secret and secret in value for secret in credentials)


def _clean(value: object, credentials: tuple[str, ...], limit: int = 128) -> str | None:
    if not isinstance(value, str) or _contains_credential(value, credentials):
        return None
    value = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", value)
    value = "".join(char for char in value if char.isprintable() and char not in "\x1b\r\n\t").strip()
    return value[:limit] or None


def _path(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > 256 or not re.fullmatch(r"/[A-Za-z0-9._~!$&'()*+,;=:@/-]*", value):
        return None
    return None if value.startswith("//") or ".." in value or "%" in value else value


def _base(ad: Advertisement, credentials: tuple[str, ...]) -> dict[str, Any]:
    result: dict[str, Any] = {"control_verified": False}
    if name := _clean(ad.service_name, credentials):
        result["service_name"] = name
    return result


def _target(addresses: Sequence[str], interfaces: Sequence[Interface]) -> str | None:
    local = {item.address for item in interfaces}
    for raw in addresses:
        address = _rfc1918(raw)
        if address and str(address) not in local and any(
            address in item.network and address not in {item.network.network_address, item.network.broadcast_address}
            for item in interfaces
        ):
            return str(address)
    return None


def _metadata(payload: object, api_devices: Mapping[str, bool | None], credentials: tuple[str, ...]) -> dict[str, Any] | None:
    if not isinstance(payload, dict) or payload.get("status") != 101:
        return None
    result: dict[str, Any] = {}
    for key, raw in (("name", payload.get("remoteName") or payload.get("displayName")), ("brand", payload.get("brandDisplayName")), ("model", payload.get("modelDisplayName")), ("device_type", payload.get("deviceType")), ("token_type", payload.get("tokenType")), ("availability", payload.get("availability"))):
        if value := _clean(raw, credentials):
            result[key] = value
    aliases, ids = [], [payload.get("deviceID")]
    if isinstance(payload.get("aliases"), list):
        for alias in payload["aliases"]:
            if isinstance(alias, dict):
                ids.append(alias.get("id"))
                if len(aliases) < 16 and (value := _clean(alias.get("name") or alias.get("displayName"), credentials)):
                    aliases.append(value)
    if aliases:
        result["aliases"] = aliases
    for value in ids:
        if isinstance(value, str) and value in api_devices:
            result["api_match"] = {"id": value, "is_restricted": api_devices[value]}
            break
    return result


class LocalConnectObserver:
    """One bounded browse and validated GET-only metadata observation."""
    def __init__(self, *, discovery: Discovery | None = None, transport: Transport | None = None, inventory: Inventory = eligible_interfaces) -> None:
        self._discovery, self._transport, self._inventory = discovery or _zeroconf_discovery, transport or _http_get, inventory

    def observe(self, web_devices: Sequence[object], *, discovery_timeout_s: int = 5, interface: str | None = None) -> dict[str, Any]:
        limits = {"discovery_timeout_s": discovery_timeout_s, "operation_timeout_s": OPERATION_TIMEOUT_S, "max_records": MAX_RECORDS, "metadata_concurrency": MAX_METADATA_CONCURRENCY, "request_timeout_s": REQUEST_TIMEOUT_S, "response_body_bytes": MAX_BODY_BYTES}
        try:
            selected = _select_interfaces(list(self._inventory()), interface)
        except Exception:
            return _result("error", [], limits, {"inventory_error": 1})
        if not selected:
            reason = "invalid_interface" if interface else ("platform_unsupported" if not sys.platform.startswith("linux") else "no_eligible_interface")
            return _result("unavailable", [], limits, {reason: 1})
        api = {item["id"]: item.get("is_restricted") if isinstance(item.get("is_restricted"), bool) else None for item in web_devices if isinstance(item, dict) and isinstance(item.get("id"), str)}
        from music_deck.prompt_boundary import machine_credentials
        credentials = tuple(item.value for item in machine_credentials() if item.value)
        try:
            return asyncio.run(self._observe(selected, api, credentials, discovery_timeout_s, limits))
        except Exception:
            return _result("error", [], limits, {"discovery_error": 1})

    async def _observe(self, interfaces: Sequence[Interface], api: Mapping[str, bool | None], credentials: tuple[str, ...], timeout: int, limits: dict[str, int]) -> dict[str, Any]:
        outcomes: dict[str, int] = {}
        deadline = asyncio.get_running_loop().time() + OPERATION_TIMEOUT_S
        try:
            async with asyncio.timeout(OPERATION_TIMEOUT_S):
                value = self._discovery(timeout, interfaces)
                value = await value if inspect.isawaitable(value) else value
        except TimeoutError:
            return _result("partial", [], limits, {"discovery_deadline": 1})
        except Exception:
            return _result("error", [], limits, {"discovery_error": 1})
        batch = value if isinstance(value, DiscoveryBatch) else DiscoveryBatch(tuple(value))
        if batch.record_cap:
            outcomes["record_cap"] = 1
        if batch.deadline:
            outcomes["discovery_deadline"] = 1
        ads, seen = [], set()
        for ad in batch.advertisements:
            key = ad.service_name or (ad.addresses, ad.port, ad.path)
            if key in seen:
                outcomes["duplicates"] = outcomes.get("duplicates", 0) + 1
            elif len(ads) < MAX_RECORDS:
                seen.add(key); ads.append(ad)
            else:
                outcomes["record_cap"] = 1
        if not ads:
            return _result("partial" if outcomes else "complete", [], limits, outcomes)
        semaphore = asyncio.Semaphore(MAX_METADATA_CONCURRENCY)

        async def observe_one(ad: Advertisement) -> dict[str, Any]:
            async with semaphore:
                return await self._one(ad, interfaces, api, credentials)

        tasks = {asyncio.create_task(observe_one(ad)): ad for ad in ads}
        done, pending = await asyncio.wait(
            tasks, timeout=max(0, deadline - asyncio.get_running_loop().time())
        )
        records = [task.result() if not task.cancelled() and task.exception() is None else _pending(tasks[task], interfaces, credentials, "request_unavailable") for task in done]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
            records.extend(_pending(tasks[task], interfaces, credentials, "metadata_deadline") for task in pending)
        for record in records:
            if reason := record.get("reason"):
                outcomes[reason] = outcomes.get(reason, 0) + 1
        partial = bool({"record_cap", "discovery_deadline", "metadata_deadline"} & outcomes.keys()) or any(record["status"] != "observed" for record in records)
        return _result("partial" if partial else "complete", sorted(records, key=lambda row: (row.get("address", ""), row.get("port", 0), row.get("service_name", ""))), limits, outcomes)

    async def _one(self, ad: Advertisement, interfaces: Sequence[Interface], api: Mapping[str, bool | None], credentials: tuple[str, ...]) -> dict[str, Any]:
        record = _pending(ad, interfaces, credentials, "")
        port, path, address = ad.port, _path(ad.path), _target(ad.addresses, interfaces)
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535 or not path:
            return {**record, "status": "unsupported_endpoint", "reason": "unsupported_endpoint"}
        if not address:
            return {**record, "status": "unavailable", "reason": "unresolved_advertisement" if not ad.addresses else "invalid_target"}
        record.update(address=address, port=port)
        try:
            response = self._transport(f"http://{address}:{port}{path}?action=getInfo&version=2.7.1", {"Content-Type": "application/x-www-form-urlencoded", "Connection": "close"}, REQUEST_TIMEOUT_S)
            response = await response if inspect.isawaitable(response) else response
        except TimeoutError:
            return {**record, "status": "unavailable", "reason": "request_timeout"}
        except Exception:
            return {**record, "status": "unavailable", "reason": "request_unavailable"}
        if response.body_capped:
            return {**record, "status": "unavailable", "http_status": response.status, "reason": "body_cap"}
        if response.status != 200:
            return {**record, "status": "unavailable", "http_status": response.status, "reason": "http_unavailable"}
        try:
            metadata = _metadata(json.loads(response.body.decode()), api, credentials)
        except (ValueError, UnicodeDecodeError):
            metadata = None
        return {**record, "status": "observed", "http_status": 200, **metadata} if metadata is not None else {**record, "status": "unavailable", "http_status": 200, "reason": "invalid_metadata"}


def _pending(ad: Advertisement, interfaces: Sequence[Interface], credentials: tuple[str, ...], reason: str) -> dict[str, Any]:
    record = _base(ad, credentials)
    if address := _target(ad.addresses, interfaces):
        record["address"] = address
    if isinstance(ad.port, int) and not isinstance(ad.port, bool) and 1 <= ad.port <= 65535:
        record["port"] = ad.port
    if reason:
        record.update(status="unavailable", reason=reason)
    return record


def _select_interfaces(items: Sequence[Interface], explicit: str | None) -> list[Interface]:
    return list(items) if explicit is None else [item for item in items if item.address == str(_rfc1918(explicit))]


def _result(status: str, devices: list[dict[str, Any]], limits: dict[str, int], outcomes: dict[str, int]) -> dict[str, Any]:
    return {"service_type": SERVICE_TYPE, "devices": devices, "count": len(devices), "status": status, "limits": limits, "outcomes": outcomes, "limitation": "Linux physical multicast IPv4 observations identify advertisements only; they do not make a receiver playable or controllable."}


async def _http_get(url: str, headers: Mapping[str, str], timeout_s: float) -> LocalResponse:
    import httpx
    async with asyncio.timeout(timeout_s):
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=timeout_s) as client:
            async with client.stream("GET", url, headers=dict(headers)) as reply:
                body = bytearray()
                async for chunk in reply.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_BODY_BYTES:
                        return LocalResponse(reply.status_code, b"", True)
                return LocalResponse(reply.status_code, bytes(body))


async def _zeroconf_discovery(timeout_s: int, interfaces: Sequence[Interface]) -> DiscoveryBatch:
    from zeroconf import IPVersion, ServiceStateChange
    from zeroconf.asyncio import AsyncServiceBrowser, AsyncZeroconf
    names: list[str] = []
    capped = False
    accepting = True
    def changed(zeroconf: Any, service_type: str, name: str, state_change: Any) -> None:
        nonlocal capped
        if accepting and state_change is ServiceStateChange.Added and name not in names:
            if len(names) < MAX_RECORDS: names.append(name)
            else: capped = True
    zeroconf = AsyncZeroconf(
        interfaces=[item.address for item in interfaces],
        ip_version=IPVersion.V4Only,
    )
    try:
        browser = AsyncServiceBrowser(zeroconf.zeroconf, SERVICE_TYPE, handlers=[changed])
        try:
            await asyncio.sleep(timeout_s)
            accepting = False
            semaphore = asyncio.Semaphore(MAX_METADATA_CONCURRENCY)
            async def resolve(name: str) -> Any:
                async with semaphore:
                    return await zeroconf.async_get_service_info(SERVICE_TYPE, name, timeout=1000)
            tasks = {asyncio.create_task(resolve(name)): name for name in names}
            if tasks:
                done, pending = await asyncio.wait(
                    tasks, timeout=max(0, OPERATION_TIMEOUT_S - REQUEST_TIMEOUT_S - timeout_s)
                )
            else:
                done, pending = set(), set()
            infos_by_name = {
                tasks[task]: task.result()
                for task in done
                if not task.cancelled() and task.exception() is None
            }
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        finally:
            accepting = False
            await browser.async_cancel()
        return DiscoveryBatch(
            tuple(
                Advertisement(
                    tuple(info.parsed_addresses(IPVersion.V4Only)) if info else (),
                    info.port if info else None,
                    _txt(info.properties if info else {}),
                    name,
                )
                for name in names
                for info in (infos_by_name.get(name),)
            ),
            capped,
            bool(pending),
        )
    finally:
        await zeroconf.async_close()


def _txt(properties: Mapping[bytes, bytes]) -> str | None:
    try: return properties.get(b"CPath", b"").decode("ascii") or None
    except UnicodeDecodeError: return None