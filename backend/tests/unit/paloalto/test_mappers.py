from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

from app.plugins.base import HAState, ObjectType, PolicyType
from app.plugins.installed.paloalto import mappers

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "paloalto"


def load_fixture(name: str) -> ET.Element:
    return ET.fromstring((FIXTURES / name).read_text())


def test_map_system_info():
    root = load_fixture("system_info.xml")
    info = mappers.map_system_info(root)
    assert info["hostname"] == "fw-branch-01"
    assert info["model"] == "PA-440"
    assert info["serial"] == "001122334455"
    assert info["sw_version"] == "10.2.4"


def test_parse_uptime():
    seconds = mappers._parse_uptime("124 days, 3:11:47")
    assert seconds == 124 * 86400 + 3 * 3600 + 11 * 60 + 47


def test_map_ha_state_standalone():
    root = load_fixture("ha_state_standalone.xml")
    state, peer = mappers.map_ha_state(root)
    assert state == HAState.STANDALONE
    assert peer is None


def test_map_licenses_flags_expired():
    root = load_fixture("licenses.xml")
    licenses = mappers.map_licenses(root)
    assert len(licenses) == 2
    threat_prevention = next(l for l in licenses if l.feature == "Threat Prevention")
    url_filtering = next(l for l in licenses if l.feature == "PAN-DB URL Filtering")
    assert threat_prevention.expired is False
    assert url_filtering.expired is True  # Jan 15, 2024 is in the past


def test_map_interfaces():
    root = load_fixture("running_config.xml")
    config_el = root.find(".//result/config")
    interfaces = mappers.map_interfaces(config_el)
    names = {i.name for i in interfaces}
    assert names == {"ethernet1/1", "ethernet1/2"}
    eth1 = next(i for i in interfaces if i.name == "ethernet1/1")
    assert eth1.ip_addresses == ["10.0.1.1/24"]
    assert eth1.mode == "layer3"


def test_map_zones():
    root = load_fixture("running_config.xml")
    config_el = root.find(".//result/config")
    zones = mappers.map_zones(config_el)
    names = {z.name for z in zones}
    assert names == {"trust", "untrust"}
    trust = next(z for z in zones if z.name == "trust")
    assert trust.interfaces == ["ethernet1/1"]


def test_map_address_objects_and_groups():
    root = load_fixture("running_config.xml")
    config_el = root.find(".//result/config")
    objects = mappers.map_address_objects(config_el)
    address_objs = [o for o in objects if o.object_type == ObjectType.ADDRESS]
    groups = [o for o in objects if o.object_type == ObjectType.ADDRESS_GROUP]
    assert len(address_objs) == 1
    assert address_objs[0].name == "finance-server-1"
    assert address_objs[0].definition.get("ip-netmask") == "10.0.1.50/32"
    assert len(groups) == 1
    assert groups[0].definition["static"] == ["finance-server-1"]


def test_map_security_policies():
    root = load_fixture("running_config.xml")
    config_el = root.find(".//result/config")
    policies = mappers.map_security_policies(config_el)
    assert len(policies) == 1
    policy = policies[0]
    assert policy.name == "allow-finance-to-sap"
    assert policy.policy_type == PolicyType.SECURITY
    assert policy.source_zones == ["trust"]
    assert policy.destination_zones == ["untrust"]
    assert policy.source == ["finance-servers"]
    assert policy.action == "allow"


def test_config_hash_is_deterministic():
    h1 = mappers.config_hash("<a>1</a>")
    h2 = mappers.config_hash("<a>1</a>")
    h3 = mappers.config_hash("<a>2</a>")
    assert h1 == h2
    assert h1 != h3
