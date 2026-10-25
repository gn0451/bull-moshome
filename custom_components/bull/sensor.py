"""Sensor platform for Bull IoT: power/energy/battery style readouts."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import BLE_CHARGER_PRODUCT_IDS, DOMAIN
from .coordinator import BullCoordinator
from .digital_display_socket import (
    DIGITAL_DISPLAY_SOCKET_PORT_NAMES,
    DIGITAL_DISPLAY_SOCKET_PORTS,
    DIGITAL_DISPLAY_SOCKET_PRODUCT_IDS,
    port_property_value,
)
from .entity import BullDeviceEntity

# identifier -> (名称, 设备类别, 状态类别, 单位, 缩放)
SENSOR_TYPES: dict[str, tuple[str, str | None, str | None, str | None, float]] = {
    "RealTimePower": (
        "实时功率",
        SensorDeviceClass.POWER,
        SensorStateClass.MEASUREMENT,
        "W",
        1,
    ),
    "RealTimeVoltage": (
        "实时电压",
        SensorDeviceClass.VOLTAGE,
        SensorStateClass.MEASUREMENT,
        "V",
        1,
    ),
    "RealTimeCurrent": (
        "实时电流",
        SensorDeviceClass.CURRENT,
        SensorStateClass.MEASUREMENT,
        "A",
        1,
    ),
    "TotalConsumption": (
        "累计用电量",
        SensorDeviceClass.ENERGY,
        SensorStateClass.TOTAL_INCREASING,
        "kWh",
        1,
    ),
    "PowerOnDuration": ("通电时长", SensorDeviceClass.DURATION, None, "min", 1),
    "PowerLevel": ("功率档位", None, None, None, 1),
    "BatteryPercent": (
        "电池电量",
        SensorDeviceClass.BATTERY,
        SensorStateClass.MEASUREMENT,
        "%",
        1,
    ),
    "ActivePower": (
        "充电功率",
        SensorDeviceClass.POWER,
        SensorStateClass.MEASUREMENT,
        "W",
        1,
    ),
    "Voltage": (
        "电压",
        SensorDeviceClass.VOLTAGE,
        SensorStateClass.MEASUREMENT,
        "V",
        10,
    ),
    "Current": (
        "电流",
        SensorDeviceClass.CURRENT,
        SensorStateClass.MEASUREMENT,
        "A",
        100,
    ),
    "EnergyUsed": (
        "充电量",
        SensorDeviceClass.ENERGY,
        SensorStateClass.TOTAL_INCREASING,
        "kWh",
        100,
    ),
    "ChargingTime": ("充电时长", SensorDeviceClass.DURATION, None, "min", 1),
    "DeviceFaultCodeInfo": ("故障信息", None, None, None, 1),
    "WorkState": ("充电状态", None, None, None, 1),
    "GunState": ("插枪状态", None, None, None, 1),
    "DeviceRealInfo.ChargingTime": (
        "充电时长",
        SensorDeviceClass.DURATION,
        None,
        "s",
        1,
    ),
    "DeviceRealInfo.ChargeVoltage": (
        "实时电压",
        SensorDeviceClass.VOLTAGE,
        SensorStateClass.MEASUREMENT,
        "V",
        1,
    ),
    "DeviceRealInfo.ChargeCurrent": (
        "实时电流",
        SensorDeviceClass.CURRENT,
        SensorStateClass.MEASUREMENT,
        "A",
        1,
    ),
    "DeviceRealInfo.ChargeActivePower": (
        "实时功率",
        SensorDeviceClass.POWER,
        SensorStateClass.MEASUREMENT,
        "kW",
        1,
    ),
    "DeviceRealInfo.ChargeEnergyUsed": (
        "当前充电量",
        SensorDeviceClass.ENERGY,
        SensorStateClass.TOTAL_INCREASING,
        "kWh",
        1,
    ),
    "DeviceRealInfo.ChargeMBTemp": (
        "主板温度",
        SensorDeviceClass.TEMPERATURE,
        SensorStateClass.MEASUREMENT,
        "°C",
        1,
    ),
    "DeviceRealInfo.ChargeSlotTemp": (
        "插座温度",
        SensorDeviceClass.TEMPERATURE,
        SensorStateClass.MEASUREMENT,
        "°C",
        1,
    ),
    "DeviceRealInfo.ChargeGunTemp": (
        "枪头温度",
        SensorDeviceClass.TEMPERATURE,
        SensorStateClass.MEASUREMENT,
        "°C",
        1,
    ),
    "DeviceState.WorkState": ("充电状态", None, None, None, 1),
    "DeviceState.GunState": ("插枪状态", None, None, None, 1),
    "DeviceWorkState.WorkState": ("充电状态", None, None, None, 1),
    "DeviceWorkState.GunState": ("插枪状态", None, None, None, 1),
}

WORK_STATE_MAP = {
    0: "待机",
    1: "启动中",
    2: "充电中",
    3: "停止中",
    4: "已完成",
    5: "已暂停",
    6: "故障",
    7: "维护",
    8: "待认证",
    9: "预约中",
    10: "降流充电中",
}
VALUE_MAPS = {
    "WorkState": WORK_STATE_MAP,
    "DeviceState.WorkState": WORK_STATE_MAP,
    "DeviceWorkState.WorkState": {
        0: "未工作",
        2: "充电中",
        8: "已插枪未激活",
        9: "已插枪已激活",
    },
    "GunState": {0: "未插枪", 1: "已插枪"},
    "DeviceState.GunState": {0: "未插枪", 1: "已插枪"},
    "DeviceWorkState.GunState": {0: "未插枪", 1: "已插枪"},
}

SOCKET_MASTER_SENSORS = (
    "RealTimePower",
    "RealTimeVoltage",
    "RealTimeCurrent",
    "TotalConsumption",
    "PowerOnDuration",
    "PowerLevel",
)
SOCKET_PORT_SENSORS = {
    "RealTimePower": SENSOR_TYPES["RealTimePower"],
    "RealTimeVoltage": SENSOR_TYPES["RealTimeVoltage"],
    "RealTimeCurrent": SENSOR_TYPES["RealTimeCurrent"],
    "Duration": ("供电时长", SensorDeviceClass.DURATION, None, "min", 1),
    "CurrentProtocol": ("快充协议", None, None, None, 1),
}
PROTOCOL_MAP = {
    0: "未连接",
    1: "PD",
    2: "UFCS",
    3: "QC 2.0",
    4: "QC 3.0",
    5: "QC 3+",
    6: "FCP",
    7: "SCP",
    8: "SFCP",
    9: "TFCP",
    10: "AFC",
    11: "PE",
    12: "Xiaomi",
}
BLE_SENSOR_KEYS = (
    "WorkState",
    "GunState",
    "DeviceFaultCodeInfo",
    "DeviceRealInfo.ChargingTime",
    "DeviceRealInfo.ChargeVoltage",
    "DeviceRealInfo.ChargeCurrent",
    "DeviceRealInfo.ChargeActivePower",
    "DeviceRealInfo.ChargeEnergyUsed",
    "DeviceRealInfo.ChargeMBTemp",
    "DeviceRealInfo.ChargeSlotTemp",
    "DeviceRealInfo.ChargeGunTemp",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Bull sensors from a config entry."""
    coordinator: BullCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[BullSensorEntity] = []

    for device in coordinator.data.values():
        if device.product_id in DIGITAL_DISPLAY_SOCKET_PRODUCT_IDS:
            entities.extend(
                BullSensorEntity(coordinator, device.iot_id, identifier)
                for identifier in SOCKET_MASTER_SENSORS
            )
            entities.extend(
                BullSocketPortSensor(coordinator, device.iot_id, port, suffix, spec)
                for port in DIGITAL_DISPLAY_SOCKET_PORTS
                for suffix, spec in SOCKET_PORT_SENSORS.items()
            )
            continue
        if device.product_id in BLE_CHARGER_PRODUCT_IDS:
            entities.extend(
                BullSensorEntity(coordinator, device.iot_id, identifier)
                for identifier in BLE_SENSOR_KEYS
            )
            continue
        for identifier in list(device.properties):
            if identifier in SENSOR_TYPES:
                entities.append(
                    BullSensorEntity(coordinator, device.iot_id, identifier)
                )

    async_add_entities(entities)


class BullSensorEntity(BullDeviceEntity, SensorEntity):
    """A numeric readout exposed by a Bull device."""

    def __init__(
        self, coordinator: BullCoordinator, iot_id: str, identifier: str
    ) -> None:
        name, device_class, state_class, unit, scale = SENSOR_TYPES[identifier]
        super().__init__(coordinator, iot_id, identifier, name, "sensor")
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_native_unit_of_measurement = unit
        self._scale = scale

    @property
    def native_value(self):
        value = self._device.properties.get(self._identifier) if self._device else None
        if value is None or isinstance(value, (dict, list)):
            return None
        if self._identifier in VALUE_MAPS:
            return VALUE_MAPS[self._identifier].get(value, value)
        if isinstance(value, str):
            return value if self._attr_device_class is None else None
        try:
            return float(value) / self._scale
        except (TypeError, ValueError, ZeroDivisionError):
            return None


class BullSocketPortSensor(BullDeviceEntity, SensorEntity):
    """One telemetry value from a PID 296 USB port."""

    def __init__(self, coordinator, iot_id, port, suffix, spec):
        name, device_class, state_class, unit, scale = spec
        super().__init__(
            coordinator,
            iot_id,
            f"{port}{suffix}",
            f"{DIGITAL_DISPLAY_SOCKET_PORT_NAMES[port]} {name}",
            "sensor",
        )
        self._port = port
        self._suffix = suffix
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_native_unit_of_measurement = unit
        self._scale = scale

    @property
    def native_value(self):
        device = self._device
        value = (
            port_property_value(device.properties, self._port, self._suffix)
            if device
            else None
        )
        if value is None or isinstance(value, (dict, list)):
            return None
        if self._suffix == "CurrentProtocol":
            return PROTOCOL_MAP.get(value, value)
        try:
            return float(value) / self._scale
        except (TypeError, ValueError, ZeroDivisionError):
            return None
