"""Switch platform for Bull IoT: one entity per controllable channel."""

from __future__ import annotations

import re

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import MANUFACTURER
from .coordinator import BullCoordinator
from .entity import BullDeviceEntity

# 通道属性形如 PowerSwitch_1 / PowerSwitch_12；裸 PowerSwitch 是整设备总开关
_CHANNEL_RE = re.compile(r"^PowerSwitch_\d+$")


def _collect_switch_identifiers(properties: dict) -> list[str]:
    """返回该设备应暴露的开关 identifier 列表。

    多通道设备（PowerSwitch_1..N）只暴露各通道，避免与整设备总开关
    PowerSwitch 在 UI 上重复；单键设备（只有 PowerSwitch）暴露总开关。
    """
    channels = [k for k in properties if _CHANNEL_RE.match(k)]
    if channels:
        return sorted(channels, key=lambda k: int(k.rsplit("_", 1)[1]))
    if "PowerSwitch" in properties:
        return ["PowerSwitch"]
    return []


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Bull switches from a config entry."""
    coordinator: BullCoordinator = hass.data["bull_iot"][entry.entry_id]
    entities: list[BullSwitchEntity] = []

    for device in coordinator.data.values():
        # 收集通道名: __name__PowerSwitch_N -> "客厅吊灯"
        channel_names = {
            key[len("__name__") :]: value
            for key, value in device.properties.items()
            if key.startswith("__name__") and value
        }
        for identifier in _collect_switch_identifiers(device.properties):
            name = channel_names.get(identifier)
            entities.append(
                BullSwitchEntity(coordinator, device.iot_id, identifier, name)
            )

    async_add_entities(entities)


class BullSwitchEntity(BullDeviceEntity, SwitchEntity):
    """A controllable channel of a Bull device."""

    def __init__(self, coordinator: BullCoordinator, iot_id: str, identifier: str, name: str | None) -> None:
        super().__init__(coordinator, iot_id, identifier, name, "switch")

    @property
    def is_on(self) -> bool:
        device = self._device
        if device is None:
            return False
        return bool(device.properties.get(self._identifier))

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_property(self._iot_id, self._identifier, 1)
        if self._device is not None:
            self._device.properties[self._identifier] = 1
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_property(self._iot_id, self._identifier, 0)
        if self._device is not None:
            self._device.properties[self._identifier] = 0
        self.async_write_ha_state()
