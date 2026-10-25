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

from .coordinator import BullCoordinator
from .entity import BullDeviceEntity

# identifier -> (名称, 设备类别, 状态类别, 单位, 缩放)
SENSOR_TYPES: dict[str, tuple[str, str | None, str | None, str | None, float]] = {
    "RealTimePower": ("实时功率", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, "W", 1),
    "RealTimeVoltage": ("实时电压", SensorDeviceClass.VOLTAGE, SensorStateClass.MEASUREMENT, "V", 1),
    "RealTimeCurrent": ("实时电流", SensorDeviceClass.CURRENT, SensorStateClass.MEASUREMENT, "A", 1),
    "TotalConsumption": ("累计用电量", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, "kWh", 1),
    "PowerOnDuration": ("通电时长", SensorDeviceClass.DURATION, None, "min", 1),
    "BatteryPercent": ("电池电量", SensorDeviceClass.BATTERY, SensorStateClass.MEASUREMENT, "%", 1),
    "ActivePower": ("充电功率", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, "W", 1),
    "Voltage": ("电压", SensorDeviceClass.VOLTAGE, SensorStateClass.MEASUREMENT, "V", 10),
    "Current": ("电流", SensorDeviceClass.CURRENT, SensorStateClass.MEASUREMENT, "A", 100),
    "EnergyUsed": ("充电量", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, "kWh", 100),
    "ChargingTime": ("充电时长", SensorDeviceClass.DURATION, None, "min", 1),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Bull sensors from a config entry."""
    coordinator: BullCoordinator = hass.data["bull_iot"][entry.entry_id]
    entities: list[BullSensorEntity] = []

    for device in coordinator.data.values():
        for identifier in list(device.properties):
            if identifier in SENSOR_TYPES:
                entities.append(
                    BullSensorEntity(coordinator, device.iot_id, identifier)
                )

    async_add_entities(entities)


class BullSensorEntity(BullDeviceEntity, SensorEntity):
    """A numeric readout exposed by a Bull device."""

    def __init__(self, coordinator: BullCoordinator, iot_id: str, identifier: str) -> None:
        name, device_class, state_class, unit, scale = SENSOR_TYPES[identifier]
        super().__init__(coordinator, iot_id, identifier, name, "sensor")
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_native_unit_of_measurement = unit
        self._scale = scale

    @property
    def native_value(self):
        value = self._device.properties.get(self._identifier) if self._device else None
        if value is None or isinstance(value, (str, dict, list)):
            return None
        try:
            return float(value) / self._scale
        except (TypeError, ValueError, ZeroDivisionError):
            return None
