from __future__ import annotations

import hashlib
import json
from typing import Any

from app.plugins.base import (
    DeviceDiscoveryResult,
    HAState,
    InterfaceStatus,
    LicenseInfo,
    NormalizedInterface,
    NormalizedObject,
    NormalizedPolicy,
    NormalizedZone,
    ObjectType,
    PolicyType,
)


def map_discovery(status_body: dict[str, Any], ha_body: dict[str, Any]) -> DeviceDiscoveryResult:
    result = status_body.get("results", {})
    ha_mode = ha_body.get("results", {}).get("mode", "standalone")
    ha_state = HAState.STANDALONE if ha_mode == "standalone" else HAState.ACTIVE

    return DeviceDiscoveryResult(
        hostname=result.get("hostname", ""),
        model=result.get("model_name", result.get("model", "")),
        serial=result.get("serial", ""),
        os_version=result.get("version", ""),
        ha_state=ha_state,
        licenses=[],  # FortiOS license info comes from a separate endpoint not modeled in Phase 1
    )


def map_interfaces(interface_body: dict[str, Any]) -> list[NormalizedInterface]:
    interfaces = []
    for entry in interface_body.get("results", []):
        ip = entry.get("ip", "")
        interfaces.append(
            NormalizedInterface(
                name=entry.get("name", ""),
                zone=None,
                ip_addresses=[ip] if ip and ip != "0.0.0.0 0.0.0.0" else [],
                mode="layer3",
                enabled=entry.get("status", "up") == "up",
            )
        )
    return interfaces


def map_interface_status(monitor_body: dict[str, Any]) -> list[InterfaceStatus]:
    """Parses `GET /api/v2/monitor/system/interface` (all interfaces, no
    `?interface=` filter). FortiOS returns `results` as an object keyed by
    interface name on most builds; handled defensively as a list too since
    that shape has been seen on some FortiOS/FortiManager-proxied versions.
    Unlike `/api/v2/cmdb/system/interface` (configured state only), this is
    live link/IP/traffic-counter data."""
    results = monitor_body.get("results", {})
    if isinstance(results, dict):
        entries = [{"name": name, **data} for name, data in results.items()]
    elif isinstance(results, list):
        entries = results
    else:
        entries = []

    statuses: list[InterfaceStatus] = []
    for entry in entries:
        ip = entry.get("ip", "")
        ip_addresses = [ip] if ip and ip != "0.0.0.0" else []
        statuses.append(
            InterfaceStatus(
                name=entry.get("name") or entry.get("interface", ""),
                zone=entry.get("vdom"),
                admin_up=entry.get("status", "up") == "up",
                oper_up=entry.get("link") in (True, "up", 1),
                ip_addresses=ip_addresses,
                speed_mbps=_speed_to_mbps(entry.get("speed")),
                duplex=entry.get("duplex"),
                mtu=entry.get("mtu"),
                in_bytes=entry.get("rx_bytes"),
                out_bytes=entry.get("tx_bytes"),
                in_packets=entry.get("rx_packets"),
                out_packets=entry.get("tx_packets"),
                in_errors=entry.get("rx_errors"),
                out_errors=entry.get("tx_errors"),
                in_drops=entry.get("rx_dropped") or entry.get("rx_drops"),
                out_drops=entry.get("tx_dropped") or entry.get("tx_drops"),
            )
        )
    return statuses


def _speed_to_mbps(speed: Any) -> float | None:
    """FortiOS reports speed as either a bare Mbps int or a string like
    '1000full' / 'auto' depending on model/version; extract the numeric
    part where present and ignore unparseable/auto values rather than
    guessing."""
    if speed is None:
        return None
    if isinstance(speed, (int, float)):
        return float(speed)
    digits = "".join(ch for ch in str(speed) if ch.isdigit())
    return float(digits) if digits else None


def map_zones(zone_body: dict[str, Any]) -> list[NormalizedZone]:
    zones = []
    for entry in zone_body.get("results", []):
        members = [m.get("interface-name", m.get("name", "")) for m in entry.get("interface", [])]
        zones.append(NormalizedZone(name=entry.get("name", ""), interfaces=members))
    return zones


def map_address_objects(address_body: dict[str, Any]) -> list[NormalizedObject]:
    objects = []
    for entry in address_body.get("results", []):
        objects.append(
            NormalizedObject(
                name=entry.get("name", ""),
                object_type=ObjectType.ADDRESS,
                definition={"subnet": entry.get("subnet", ""), "type": entry.get("type", "")},
            )
        )
    return objects


def map_service_objects(service_body: dict[str, Any]) -> list[NormalizedObject]:
    objects = []
    for entry in service_body.get("results", []):
        objects.append(
            NormalizedObject(
                name=entry.get("name", ""),
                object_type=ObjectType.SERVICE,
                definition={"protocol": entry.get("protocol", ""), "port": entry.get("tcp-portrange", "")},
            )
        )
    return objects


def map_policies(policy_body: dict[str, Any]) -> list[NormalizedPolicy]:
    policies = []
    for entry in policy_body.get("results", []):
        policies.append(
            NormalizedPolicy(
                name=entry.get("name") or f"policy-{entry.get('policyid')}",
                policy_type=PolicyType.SECURITY,
                rule_order=entry.get("policyid", 0),
                source_zones=[z.get("name", "") for z in entry.get("srcintf", [])],
                destination_zones=[z.get("name", "") for z in entry.get("dstintf", [])],
                source=[a.get("name", "") for a in entry.get("srcaddr", [])],
                destination=[a.get("name", "") for a in entry.get("dstaddr", [])],
                application=[s.get("name", "") for s in entry.get("service", [])],
                service=[s.get("name", "") for s in entry.get("service", [])],
                action=entry.get("action", "deny"),
                definition=entry,
            )
        )
    return policies


def config_hash(raw: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()
