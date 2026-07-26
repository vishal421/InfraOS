"""
Translates raw PAN-OS XML elements into the normalized models defined in
plugins/base.py. Isolated from client.py (which only knows HTTP/XML
transport) and from plugin.py (which orchestrates calls) so that PAN-OS
schema changes across versions are absorbed here.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Optional
from xml.etree import ElementTree as ET

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


def _text(el: Optional[ET.Element], default: str = "") -> str:
    if el is None or el.text is None:
        return default
    return el.text.strip()


def _findtext(root: ET.Element, path: str, default: str = "") -> str:
    el = root.find(path)
    return _text(el, default)


def map_system_info(root: ET.Element) -> dict:
    """Parses <response><result><system>...</system></result></response>
    from `<show><system><info/></system></show>`."""
    system = root.find(".//result/system")
    if system is None:
        raise ValueError("Unexpected system info response: <system> element missing")

    return {
        "hostname": _findtext(system, "hostname"),
        "model": _findtext(system, "model"),
        "serial": _findtext(system, "serial"),
        "sw_version": _findtext(system, "sw-version"),
        "uptime": _findtext(system, "uptime"),
    }


def map_ha_state(root: ET.Element) -> tuple[HAState, Optional[str]]:
    """Parses `<show><high-availability><state/></high-availability></show>`.
    Standalone devices return an 'enabled' = 'no' element."""
    enabled = _findtext(root, ".//result/enabled").lower()
    if enabled != "yes":
        return HAState.STANDALONE, None

    local_state = _findtext(root, ".//result/group/local-info/state").lower()
    peer_serial = _findtext(root, ".//result/group/peer-info/serial") or None

    if "active" in local_state:
        return HAState.ACTIVE, peer_serial
    if "passive" in local_state:
        return HAState.PASSIVE, peer_serial
    return HAState.UNKNOWN, peer_serial


def map_licenses(root: ET.Element) -> list[LicenseInfo]:
    """Parses `<request><license><info/></license></request>`."""
    licenses: list[LicenseInfo] = []
    for entry in root.findall(".//result/licenses/entry"):
        expires = _findtext(entry, "expires") or None
        expired = _is_expired(expires)
        licenses.append(
            LicenseInfo(
                feature=_findtext(entry, "feature"),
                description=_findtext(entry, "description") or None,
                expires=expires,
                expired=expired,
            )
        )
    return licenses


def _is_expired(expires: Optional[str]) -> bool:
    if not expires or expires.lower() in ("never", ""):
        return False
    for fmt in ("%B %d, %Y", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(expires, fmt) < datetime.now(timezone.utc).replace(tzinfo=None)
        except ValueError:
            continue
    return False


def build_discovery_result(
    system_info: dict,
    ha_state: HAState,
    ha_peer: Optional[str],
    licenses: list[LicenseInfo],
    panorama_managed: bool = False,
    panorama_hostname: Optional[str] = None,
    device_group: Optional[str] = None,
) -> DeviceDiscoveryResult:
    uptime_seconds = _parse_uptime(system_info.get("uptime", ""))
    return DeviceDiscoveryResult(
        hostname=system_info.get("hostname", ""),
        model=system_info.get("model", ""),
        serial=system_info.get("serial", ""),
        os_version=system_info.get("sw_version", ""),
        ha_state=ha_state,
        ha_peer_serial=ha_peer,
        panorama_managed=panorama_managed,
        panorama_hostname=panorama_hostname,
        device_group=device_group,
        uptime_seconds=uptime_seconds,
        licenses=licenses,
    )


def _parse_uptime(uptime_str: str) -> Optional[int]:
    """PAN-OS uptime string looks like '124 days, 3:11:47'."""
    if not uptime_str:
        return None
    try:
        days = 0
        rest = uptime_str
        if "day" in uptime_str:
            day_part, rest = uptime_str.split(",", 1)
            days = int(day_part.strip().split()[0])
        h, m, s = (int(x) for x in rest.strip().split(":"))
        return days * 86400 + h * 3600 + m * 60 + s
    except (ValueError, IndexError):
        return None


# --------------------------------------------------------------------
# Configuration parsing
# --------------------------------------------------------------------

def config_hash(raw_xml: str) -> str:
    return hashlib.sha256(raw_xml.encode("utf-8")).hexdigest()


def map_interfaces(config_root: ET.Element) -> list[NormalizedInterface]:
    """Parses interfaces under
    devices/entry/network/interface/ethernet/entry (layer3 shown; vwire/l2
    follow the same entry-based pattern and are handled identically)."""
    interfaces: list[NormalizedInterface] = []
    for eth_entry in config_root.findall(
        ".//network/interface/ethernet/entry"
    ):
        name = eth_entry.attrib.get("name", "")
        layer3 = eth_entry.find("layer3")
        mode = "layer3" if layer3 is not None else (
            "layer2" if eth_entry.find("layer2") is not None else "unknown"
        )
        ip_addresses = []
        if layer3 is not None:
            for ip_entry in layer3.findall("ip/entry"):
                ip_addresses.append(ip_entry.attrib.get("name", ""))

        interfaces.append(
            NormalizedInterface(
                name=name,
                ip_addresses=ip_addresses,
                mode=mode,
                enabled=True,
            )
        )
    return interfaces


def map_interface_status(interface_root: ET.Element, counter_root: ET.Element) -> list[InterfaceStatus]:
    """Combines two PAN-OS op-command responses into live per-interface
    status:

    - `<show><interface>all</interface></show>` -> `ifnet` entries give
      zone + configured IP(s) per logical unit; `hw` entries give physical
      link state, speed, and duplex per physical port.
    - `<show><counter><interface>all</interface></counter></show>` -> `ifnet`
      entries give cumulative traffic counters (bytes/packets/errors/drops).

    Both are joined by interface name so the caller gets one row per
    interface with configured IP, link state, and live traffic counters
    together, rather than three separate device round-trips' worth of
    disjoint data.
    """
    hw_by_name: dict[str, ET.Element] = {}
    for hw_entry in interface_root.findall(".//result/hw/entry"):
        name = _findtext(hw_entry, "name")
        if name:
            hw_by_name[name] = hw_entry

    counters_by_name: dict[str, ET.Element] = {}
    for counter_entry in counter_root.findall(".//result/ifnet/entry"):
        name = _findtext(counter_entry, "name")
        if name:
            counters_by_name[name] = counter_entry

    statuses: dict[str, InterfaceStatus] = {}
    for ifnet_entry in interface_root.findall(".//result/ifnet/entry"):
        name = _findtext(ifnet_entry, "name")
        if not name:
            continue

        zone = _findtext(ifnet_entry, "zone") or None
        ip_raw = _findtext(ifnet_entry, "ip")
        ip_addresses = [ip_raw] if ip_raw and ip_raw.upper() != "N/A" else []

        # The physical port backing a subinterface (e.g. "ethernet1/1.100")
        # reports hw/link state under the base port name.
        base_name = name.split(".")[0]
        hw_entry = hw_by_name.get(name) or hw_by_name.get(base_name)
        state = _findtext(hw_entry, "state").lower() if hw_entry is not None else ""
        speed_text = _findtext(hw_entry, "speed") if hw_entry is not None else ""
        duplex = _findtext(hw_entry, "duplex") or None if hw_entry is not None else None

        speed_mbps = None
        if speed_text and speed_text.isdigit():
            speed_mbps = float(speed_text)

        counter_entry = counters_by_name.get(name)
        statuses[name] = InterfaceStatus(
            name=name,
            zone=zone,
            admin_up=True,
            oper_up=(state == "up") if hw_entry is not None else True,
            ip_addresses=ip_addresses,
            speed_mbps=speed_mbps,
            duplex=duplex,
            in_bytes=_findint(counter_entry, "ibytes"),
            out_bytes=_findint(counter_entry, "obytes"),
            in_packets=_findint(counter_entry, "ipackets"),
            out_packets=_findint(counter_entry, "opackets"),
            in_errors=_findint(counter_entry, "ierrors"),
            out_errors=_findint(counter_entry, "collisions"),
            in_drops=_findint(counter_entry, "idrops"),
            out_drops=_findint(counter_entry, "odrops"),
        )

    # Physical ports with no logical/IP-bearing unit configured (e.g. an
    # unused ethernet port) only show up in `hw`, not `ifnet` — surface them
    # too so "interface monitor" covers every port, not just ones with an IP.
    for name, hw_entry in hw_by_name.items():
        if name in statuses:
            continue
        state = _findtext(hw_entry, "state").lower()
        speed_text = _findtext(hw_entry, "speed")
        counter_entry = counters_by_name.get(name)
        statuses[name] = InterfaceStatus(
            name=name,
            zone=None,
            admin_up=True,
            oper_up=(state == "up"),
            ip_addresses=[],
            speed_mbps=float(speed_text) if speed_text.isdigit() else None,
            duplex=_findtext(hw_entry, "duplex") or None,
            in_bytes=_findint(counter_entry, "ibytes"),
            out_bytes=_findint(counter_entry, "obytes"),
            in_packets=_findint(counter_entry, "ipackets"),
            out_packets=_findint(counter_entry, "opackets"),
            in_errors=_findint(counter_entry, "ierrors"),
            out_errors=_findint(counter_entry, "collisions"),
            in_drops=_findint(counter_entry, "idrops"),
            out_drops=_findint(counter_entry, "odrops"),
        )

    return list(statuses.values())


def _findint(entry: Optional[ET.Element], tag: str) -> Optional[int]:
    if entry is None:
        return None
    el = entry.find(tag)
    if el is None or not el.text:
        return None
    try:
        return int(el.text.strip())
    except ValueError:
        return None


def map_zones(config_root: ET.Element) -> list[NormalizedZone]:
    zones: list[NormalizedZone] = []
    for zone_entry in config_root.findall(".//vsys/entry/zone/entry"):
        name = zone_entry.attrib.get("name", "")
        interfaces = [
            m.text.strip()
            for m in zone_entry.findall("network/layer3/member")
            if m.text
        ]
        zones.append(NormalizedZone(name=name, interfaces=interfaces))
    return zones


def _members(entry: ET.Element, path: str) -> list[str]:
    return [m.text.strip() for m in entry.findall(path) if m.text]


def map_address_objects(config_root: ET.Element) -> list[NormalizedObject]:
    objects: list[NormalizedObject] = []
    for entry in config_root.findall(".//vsys/entry/address/entry"):
        name = entry.attrib.get("name", "")
        definition = {child.tag: (child.text or "").strip() for child in entry}
        objects.append(NormalizedObject(name=name, object_type=ObjectType.ADDRESS, definition=definition))

    for entry in config_root.findall(".//vsys/entry/address-group/entry"):
        name = entry.attrib.get("name", "")
        definition = {"static": _members(entry, "static/member")}
        objects.append(
            NormalizedObject(name=name, object_type=ObjectType.ADDRESS_GROUP, definition=definition)
        )
    return objects


def map_service_objects(config_root: ET.Element) -> list[NormalizedObject]:
    objects: list[NormalizedObject] = []
    for entry in config_root.findall(".//vsys/entry/service/entry"):
        name = entry.attrib.get("name", "")
        proto_el = entry.find("protocol")
        definition = {}
        if proto_el is not None:
            for proto in proto_el:
                port_el = proto.find("port")
                definition = {"protocol": proto.tag, "port": _text(port_el)}
        objects.append(NormalizedObject(name=name, object_type=ObjectType.SERVICE, definition=definition))

    for entry in config_root.findall(".//vsys/entry/service-group/entry"):
        name = entry.attrib.get("name", "")
        definition = {"members": _members(entry, "members/member")}
        objects.append(
            NormalizedObject(name=name, object_type=ObjectType.SERVICE_GROUP, definition=definition)
        )
    return objects


def map_security_policies(config_root: ET.Element) -> list[NormalizedPolicy]:
    policies: list[NormalizedPolicy] = []
    for idx, entry in enumerate(
        config_root.findall(".//vsys/entry/rulebase/security/rules/entry"), start=1
    ):
        name = entry.attrib.get("name", "")
        action = _findtext(entry, "action")
        definition = {child.tag: [m.text for m in child.findall("member")] for child in entry}
        policies.append(
            NormalizedPolicy(
                name=name,
                policy_type=PolicyType.SECURITY,
                rule_order=idx,
                source_zones=_members(entry, "from/member"),
                destination_zones=_members(entry, "to/member"),
                source=_members(entry, "source/member"),
                destination=_members(entry, "destination/member"),
                application=_members(entry, "application/member"),
                service=_members(entry, "service/member"),
                action=action,
                definition=definition,
            )
        )
    return policies


def map_nat_policies(config_root: ET.Element) -> list[NormalizedPolicy]:
    policies: list[NormalizedPolicy] = []
    for idx, entry in enumerate(config_root.findall(".//vsys/entry/rulebase/nat/rules/entry"), start=1):
        name = entry.attrib.get("name", "")
        definition = {child.tag: ET.tostring(child, encoding="unicode") for child in entry}
        policies.append(
            NormalizedPolicy(
                name=name,
                policy_type=PolicyType.NAT,
                rule_order=idx,
                source_zones=_members(entry, "from/member"),
                destination_zones=_members(entry, "to/member"),
                source=_members(entry, "source/member"),
                destination=_members(entry, "destination/member"),
                definition=definition,
            )
        )
    return policies
