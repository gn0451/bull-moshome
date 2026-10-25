"""Privacy-preserving diagnostics for Bull MosHome."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data

from .const import CONF_FAMILY_IDS, CONF_PASSWORD, CONF_USERNAME, DOMAIN
from .device_profiles import profile_report

TO_REDACT = {
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_FAMILY_IDS,
    "access_token",
    "refresh_token",
    "openid",
    "iot_id",
    "deviceName",
    "dn",
    "BluetoothMac",
    "WIFI_AP_BSSID",
}


def _device_report(device) -> dict[str, Any]:
    """Describe compatibility without returning IDs, names or property values."""
    return {
        **profile_report(device.product_id),
        "product_name": device.product_name or None,
        "model_name": device.model_name or None,
        "firmware_version": device.firmware_version or None,
        "status": device.status,
        "property_identifiers": sorted(
            key for key in device.properties if not key.startswith("__name__")
        ),
    }


async def async_get_config_entry_diagnostics(hass, entry) -> dict[str, Any]:
    """Return an anonymized account-level capability report."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    family_ids = entry.options.get(CONF_FAMILY_IDS, entry.data.get(CONF_FAMILY_IDS, []))
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": async_redact_data(dict(entry.options), TO_REDACT),
        "selected_family_count": len(family_ids),
        "devices": [_device_report(device) for device in coordinator.devices.values()],
    }


async def async_get_device_diagnostics(hass, entry, device_entry) -> dict[str, Any]:
    """Return one anonymized device capability report."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    iot_id = next(
        (
            identifier
            for domain, identifier in device_entry.identifiers
            if domain == DOMAIN
        ),
        None,
    )
    device = coordinator.devices.get(iot_id)
    if device is None:
        return {"error": "device_not_loaded"}
    return _device_report(device)
