"""Constants for the Bull IoT integration."""

DOMAIN = "bull_iot"

# 配置流程字段
CONF_USERNAME = "username"
CONF_PASSWORD = "password"

# 选项
CONF_SCAN_INTERVAL = "scan_interval"
CONF_MQTT_ENABLED = "mqtt_enabled"
CONF_FAMILY_IDS = "family_ids"  # 预留：指定加载的家庭（暂未用，默认全部）

DEFAULT_SCAN_INTERVAL = 60  # 秒
DEFAULT_MQTT_ENABLED = True

PLATFORMS = ["switch", "sensor", "binary_sensor"]

MANUFACTURER = "公牛 (BULL)"
