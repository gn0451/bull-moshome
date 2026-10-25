"""Constants for the Bull IoT integration."""

from .device_profiles import COMPATIBILITY_PROFILES, READ_ONLY_PROFILES

DOMAIN = "bull_iot"

# 配置流程字段
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_FAMILY_IDS = "family_ids"

# 选项
CONF_SCAN_INTERVAL = "scan_interval"
CONF_MQTT_ENABLED = "mqtt_enabled"

# MQTT is the primary update path. Polling is only a reconciliation fallback.
DEFAULT_SCAN_INTERVAL = 300  # 秒
DEFAULT_MQTT_ENABLED = False

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

THING_SERVICE_CHARGER_PRODUCT_IDS = frozenset({193, 195})
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
