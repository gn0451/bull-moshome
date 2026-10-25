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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Bull connectivity sensors from a config entry."""
    coordinator: BullCoordinator = hass.data["bull_iot"][entry.entry_id]
    entities = [
        BullConnectivityEntity(coordinator, device.iot_id)
        for device in coordinator.data.values()
    ]
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
