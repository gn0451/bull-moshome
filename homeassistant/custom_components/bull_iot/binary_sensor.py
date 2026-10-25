"""Binary sensor platform for Bull IoT: device connectivity."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import BullCoordinator
from .entity import BullDeviceEntity

# product_id -> (identifier, name, HA device class)
SENSOR_BINARY_TYPES = {
    61: (("GasStatus", "燃气报警", BinarySensorDeviceClass.GAS),),
    63: (("WatervolumeStatus", "漏水报警", BinarySensorDeviceClass.MOISTURE),),
    66: (("HumanActivity", "人体活动", BinarySensorDeviceClass.MOTION),),
    68: (
        ("DoorStatus", "门磁状态", BinarySensorDeviceClass.DOOR),
        ("DismantleStatus", "防拆报警", BinarySensorDeviceClass.TAMPER),
    ),
}


def _binary_value(value) -> bool | None:
    """Interpret only the explicit 0/1 states used by MosHome sensors."""
    if isinstance(value, bool):
        return value
    if value in (0, "0"):
        return False
    if value in (1, "1"):
        return True
    return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Bull connectivity sensors from a config entry."""
    coordinator: BullCoordinator = hass.data["bull_iot"][entry.entry_id]
    entities: list[BinarySensorEntity] = [
        BullConnectivityEntity(coordinator, device.iot_id)
        for device in coordinator.data.values()
    ]
    for device in coordinator.data.values():
        for identifier, name, device_class in SENSOR_BINARY_TYPES.get(
            device.product_id, ()
        ):
            if identifier in device.properties:
                entities.append(
                    BullPropertyBinaryEntity(
                        coordinator,
                        device.iot_id,
                        identifier,
                        name,
                        device_class,
                    )
                )
    async_add_entities(entities)


class BullConnectivityEntity(BullDeviceEntity, BinarySensorEntity):
    """Whether the device is online (cloud status)."""

    def __init__(self, coordinator: BullCoordinator, iot_id: str) -> None:
        super().__init__(coordinator, iot_id, "status", "在线状态", "binary_sensor")
        self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    @property
    def is_on(self) -> bool:
        # status: ONLINE / 1 = 在线; OFFLINE / 3 = 离线
        return (self._device.status in ("ONLINE", 1)) if self._device else False

    @property
    def available(self) -> bool:
        """Connectivity remains readable while the device itself is offline."""
        return self.coordinator.last_update_success


class BullPropertyBinaryEntity(BullDeviceEntity, BinarySensorEntity):
    """A persistent alarm/activity property from a verified sensor product."""

    def __init__(
        self,
        coordinator: BullCoordinator,
        iot_id: str,
        identifier: str,
        name: str,
        device_class: BinarySensorDeviceClass,
    ) -> None:
        super().__init__(coordinator, iot_id, identifier, name, "binary_sensor")
        self._attr_device_class = device_class

    @property
    def is_on(self) -> bool | None:
        value = self._device.properties.get(self._identifier) if self._device else None
        return _binary_value(value)
