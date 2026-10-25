"""Constants for the Bull IoT integration."""

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
SWITCH_PRODUCT_IDS = {
    4,
    5,
    6,
    7,
    13,
    14,
    30,
    34,
    35,
    36,
    53,
    102,
    103,
    104,
    149,
    157,
    158,
    159,
    180,
    206,
    219,
    220,
    221,
    279,
    296,
}

LIGHT_PRODUCT_IDS = {79, 125, 127, 171, 175, 236, 237}
COVER_PRODUCT_IDS = {31, 56, 59, 168, 198, 291}

# These products stay visible through connectivity/read-only entities. They
# must not gain a control entity merely because the cloud schema contains a
# PowerSwitch-like field.
READ_ONLY_PRODUCT_IDS = {3, 20, 21, 69}

THING_SERVICE_CHARGER_PRODUCT_IDS = {193, 195}
BLE_CHARGER_PRODUCT_IDS = {309}
CHARGER_PRODUCT_IDS = (
    {
        74,
        75,
        141,
        196,
        199,
        258,
        274,
        275,
    }
    | THING_SERVICE_CHARGER_PRODUCT_IDS
    | BLE_CHARGER_PRODUCT_IDS
)

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
