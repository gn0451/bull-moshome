"""Device support profiles and capability confidence classification."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class SupportTier(str, Enum):
    """Confidence and safety level for an exposed device capability."""

    VERIFIED = "verified"
    PROFILED = "profiled"
    INFERRED_SAFE = "inferred-safe"
    READ_ONLY = "read-only"
    SPECIALIZED = "specialized"


@dataclass(frozen=True)
class DeviceProfile:
    """Resolved support information for one product."""

    product_id: int
    category: str
    support_tier: SupportTier
    evidence_level: str
    verified_on: str | None = None
    app_version: str | None = None
    reason: str | None = None


_PROFILE_PATH = Path(__file__).with_name("device_profiles.json")
with _PROFILE_PATH.open(encoding="utf-8") as profile_file:
    PROFILE_REGISTRY: dict[str, Any] = json.load(profile_file)

COMPATIBILITY_PROFILES: dict[str, frozenset[int]] = {
    category: frozenset(product_ids)
    for category, product_ids in PROFILE_REGISTRY["compatibility_profiles"].items()
}
READ_ONLY_PROFILES: dict[int, dict[str, str]] = {
    int(product_id): profile
    for product_id, profile in PROFILE_REGISTRY["read_only_profiles"].items()
}
FIELD_EVIDENCE: dict[int, dict[str, str]] = {
    int(product_id): evidence
    for product_id, evidence in PROFILE_REGISTRY["field_evidence"].items()
}


def resolve_profile(product_id: int) -> DeviceProfile | None:
    """Resolve an explicit product profile without guessing from properties."""
    if product_id in READ_ONLY_PROFILES:
        profile = READ_ONLY_PROFILES[product_id]
        return DeviceProfile(
            product_id=product_id,
            category=profile["category"],
            support_tier=SupportTier.READ_ONLY,
            evidence_level="field_schema",
            reason=profile["reason"],
        )

    for category, product_ids in COMPATIBILITY_PROFILES.items():
        if product_id not in product_ids:
            continue
        specialized = category in {"cloud_charger", "ble_charger"}
        evidence = FIELD_EVIDENCE.get(product_id, {})
        support_tier = (
            SupportTier.SPECIALIZED
            if specialized
            else (
                SupportTier.VERIFIED
                if evidence.get("level") == "control_and_readback"
                else SupportTier.PROFILED
            )
        )
        return DeviceProfile(
            product_id=product_id,
            category=category,
            support_tier=support_tier,
            evidence_level=evidence.get("level", "compatibility_profile"),
            verified_on=evidence.get("verified_on"),
            app_version=evidence.get("app_version"),
        )
    return None


def infer_switch_tier(
    product_id: int, properties: Mapping[str, Any], identifiers: list[str]
) -> SupportTier | None:
    """Classify a switch capability using profiles first, then safe inference."""
    profile = resolve_profile(product_id)
    if profile is not None:
        if profile.support_tier is SupportTier.READ_ONLY:
            return SupportTier.READ_ONLY
        if profile.category == "switch":
            return profile.support_tier
        return None

    if not identifiers:
        return None

    # Unknown battery-powered products are commonly scene panels. Do not create
    # a load control until a product profile or stronger load evidence exists.
    battery_keys = {"BatteryStatus", "BatteryPercent", "BatteryLevel"}
    load_keys = {
        "RealTimePower",
        "RealTimeCurrent",
        "RealTimeVoltage",
        "TotalConsumption",
        "PowerOnDuration",
    }
    if battery_keys.intersection(properties) and not load_keys.intersection(properties):
        return SupportTier.READ_ONLY

    return SupportTier.INFERRED_SAFE


def profile_report(product_id: int) -> dict[str, Any]:
    """Return a JSON-safe support record for diagnostics."""
    profile = resolve_profile(product_id)
    if profile is None:
        return {
            "product_id": product_id,
            "support_tier": "unprofiled",
            "evidence_level": "none",
        }
    return {
        "product_id": profile.product_id,
        "category": profile.category,
        "support_tier": profile.support_tier.value,
        "evidence_level": profile.evidence_level,
        "verified_on": profile.verified_on,
        "app_version": profile.app_version,
        "reason": profile.reason,
    }
