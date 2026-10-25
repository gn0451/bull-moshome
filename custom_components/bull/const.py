"""Constants for the Bull IoT integration."""

from .device_profiles import (
    COMPATIBILITY_PROFILES,
    READ_ONLY_PROFILES,
    THING_SERVICE_CHARGER_PRODUCT_IDS as THING_SERVICE_CHARGER_PRODUCT_IDS,
)

DOMAIN = "bull"

# 配置流程字段
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_FAMILY_IDS = "family_ids"
LEGACY_CONF_FAMILY_IDS = "selected_families"

# 选项
CONF_SCAN_INTERVAL = "scan_interval"
CONF_MQTT_ENABLED = "mqtt_enabled"

# MQTT is the primary update path. Polling is only a reconciliation fallback.
DEFAULT_SCAN_INTERVAL = 300  # 秒
DEFAULT_MQTT_ENABLED = True

PLATFORMS = [
    "switch",
    "light",
    "cover",
    "sensor",
    "binary_sensor",
    "select",
    "number",
    "button",
]

MANUFACTURER = "公牛 (BULL)"


def mask_account(username: str) -> str:
    """Mask a phone-like account name before showing it in the UI.

    MosHome accounts are phone numbers, and the config entry title is visible in
    Settings → Devices & services, in screenshots and in issue reports.
    """
    digits = username.strip()
    if len(digits) >= 8 and digits.isdigit():
        return f"{digits[:3]}****{digits[-4:]}"
    return username

# Control entities are deliberately opt-in by product. A property named
# PowerSwitch is not sufficient evidence that the product is a load switch:
# wireless scene panels expose similar properties but should be treated as
# event sources instead of controllable loads.
SWITCH_PRODUCT_IDS = COMPATIBILITY_PROFILES["switch"]

LIGHT_PRODUCT_IDS = COMPATIBILITY_PROFILES["light"]
COVER_PRODUCT_IDS = COMPATIBILITY_PROFILES["cover"]

# These products stay visible through connectivity/read-only entities. They
# must not gain a control entity merely because the cloud schema contains a
# PowerSwitch-like field.
READ_ONLY_PRODUCT_IDS = frozenset(READ_ONLY_PROFILES)

BLE_CHARGER_PRODUCT_IDS = COMPATIBILITY_PROFILES["ble_charger"]
CHARGER_PRODUCT_IDS = COMPATIBILITY_PROFILES["cloud_charger"] | BLE_CHARGER_PRODUCT_IDS

BUTTON_ENTITY_MAPPING = {
    258: (
        {
            "id": "activate_charging",
            "name": "激活充电",
            "service": "SheduleAuth",
            "available_when": {"DeviceWorkState.WorkState": 8},
        },
    )
}
