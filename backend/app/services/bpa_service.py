from __future__ import annotations

from app.models.entities import ConfigVersion, Device
from app.services import config_service
from app.services.device_service import get_device

# Point penalties per finding, subtracted from a 100 baseline. Deliberately
# simple and transparent rather than a black-box weighted model — an
# operator should be able to look at a finding and know exactly why the
# score moved. Tune these as real usage tells you which findings matter
# more in practice.
PENALTIES = {
    "any_any_allow_rule": 15,
    "unused_object": 3,
    "duplicate_policy": 8,
    "expired_license": 10,
    "unsupported_os_version": 20,
    "single_rule_no_logging_signal": 0,  # see note in _check_policies — not scored, informational only
}

MIN_RECOMMENDED_MAJOR_VERSION = 10


class NoConfigurationError(Exception):
    pass


def _check_any_any_rules(policies: list[dict]) -> list[dict]:
    findings = []
    for policy in policies:
        if policy.get("action") != "allow":
            continue
        source_is_any = policy.get("source") in ([], ["any"]) or "any" in policy.get("source", [])
        dest_is_any = policy.get("destination") in ([], ["any"]) or "any" in policy.get("destination", [])
        service_is_any = "any" in policy.get("service", []) or policy.get("service") == []
        app_is_any = "any" in policy.get("application", []) or policy.get("application") == []

        if source_is_any and dest_is_any and (service_is_any or app_is_any):
            findings.append(
                {
                    "category": "any_any_allow_rule",
                    "severity": "high",
                    "target": policy["name"],
                    "message": f"Policy '{policy['name']}' allows any-source/any-destination traffic with broad service/application scope.",
                }
            )
    return findings


def _check_unused_objects(objects: list[dict], policies: list[dict]) -> list[dict]:
    referenced: set[str] = set()
    for policy in policies:
        referenced |= set(policy.get("source", []))
        referenced |= set(policy.get("destination", []))
        referenced |= set(policy.get("service", []))
        referenced |= set(policy.get("application", []))

    findings = []
    for obj in objects:
        if obj["object_type"] in ("address_group", "service_group"):
            # Groups reference members, not the other way round for this
            # simple check — skip to avoid false positives on groups that
            # are referenced only by other groups (not modeled here yet).
            continue
        if obj["name"] not in referenced:
            findings.append(
                {
                    "category": "unused_object",
                    "severity": "low",
                    "target": obj["name"],
                    "message": f"Object '{obj['name']}' ({obj['object_type']}) is not referenced by any collected security policy.",
                }
            )
    return findings


def _check_duplicate_policies(policies: list[dict]) -> list[dict]:
    seen: dict[tuple, str] = {}
    findings = []
    for policy in policies:
        key = (
            tuple(sorted(policy.get("source_zones", []))),
            tuple(sorted(policy.get("destination_zones", []))),
            tuple(sorted(policy.get("source", []))),
            tuple(sorted(policy.get("destination", []))),
            tuple(sorted(policy.get("service", []))),
            tuple(sorted(policy.get("application", []))),
            policy.get("action"),
        )
        if key in seen:
            findings.append(
                {
                    "category": "duplicate_policy",
                    "severity": "medium",
                    "target": policy["name"],
                    "message": f"Policy '{policy['name']}' has identical match criteria and action to policy '{seen[key]}'.",
                }
            )
        else:
            seen[key] = policy["name"]
    return findings


def _check_licenses(device: Device) -> list[dict]:
    findings = []
    for lic in device.licenses or []:
        if lic.get("expired"):
            findings.append(
                {
                    "category": "expired_license",
                    "severity": "medium",
                    "target": lic.get("feature", "unknown"),
                    "message": f"License '{lic.get('feature')}' expired on {lic.get('expires')}.",
                }
            )
    return findings


def _check_os_version(device: Device) -> list[dict]:
    findings = []
    version = device.os_version or ""
    try:
        major = int(version.split(".")[0])
        if major < MIN_RECOMMENDED_MAJOR_VERSION:
            findings.append(
                {
                    "category": "unsupported_os_version",
                    "severity": "high",
                    "target": device.hostname or device.mgmt_host,
                    "message": f"PAN-OS {version} is below the recommended minimum major version {MIN_RECOMMENDED_MAJOR_VERSION}.",
                }
            )
    except (ValueError, IndexError):
        pass
    return findings


async def analyze(db, device_id: str) -> dict:
    device = await get_device(db, device_id)
    version: ConfigVersion | None = await config_service.get_latest_config_version(db, device_id)
    if version is None:
        raise NoConfigurationError("No configuration collected yet for this device — run Collect Config first")

    findings: list[dict] = []
    findings += _check_any_any_rules(version.policies)
    findings += _check_unused_objects(version.objects, version.policies)
    findings += _check_duplicate_policies(version.policies)
    findings += _check_licenses(device)
    findings += _check_os_version(device)

    score = 100
    for finding in findings:
        score -= PENALTIES.get(finding["category"], 5)
    score = max(0, score)

    by_category: dict[str, int] = {}
    for f in findings:
        by_category[f["category"]] = by_category.get(f["category"], 0) + 1

    return {
        "device_id": device_id,
        "config_version": version.version_num,
        "security_score": score,
        "finding_count": len(findings),
        "findings_by_category": by_category,
        "findings": findings,
    }
