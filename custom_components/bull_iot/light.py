"""Light platform for verified MosHome tunable-white products."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import LIGHT_PRODUCT_IDS
from .coordinator import BullCoordinator
from .entity import BullDeviceEntity

POWER = "PowerSwitch"
BRIGHTNESS = "BrightValue"
COLOR_TEMP = "ColorTemperature"
MIN_KELVIN = 3000
MAX_KELVIN = 5700


@dataclass(frozen=True)
class LightProtocol:
    """Brightness encoding selected from the device property fingerprint."""

    wifi_scale: bool

    def to_ha_brightness(self, value: float) -> int:
        ratio = (value - 10) / 990 if self.wifi_scale else value / 1000
        return max(1, min(255, round(ratio * 255)))

    def from_ha_brightness(self, value: int) -> int:
        ratio = max(1, min(255, value)) / 255
        return (
            round(10 + ratio * 990) if self.wifi_scale else max(10, round(ratio * 1000))
        )


def _resolve_protocol(properties: dict) -> LightProtocol | None:
    required = {POWER, BRIGHTNESS, COLOR_TEMP}
    if not required.issubset(properties):
        return None
    single_markers = {
        "OffRampTime",
        "OnRampTime",
        "PowerSwitchSave",
        "ThreeDimmerEnable",
        "TestMode",
    }
    wifi_markers = {"PowerGradation", "PowerOffMemory"}
    single = bool(single_markers & properties.keys())
    wifi = bool(wifi_markers & properties.keys())
    if single == wifi:
        return None
    return LightProtocol(wifi_scale=wifi)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up verified light entities."""
    coordinator: BullCoordinator = hass.data["bull_iot"][entry.entry_id]
    entities = []
    for device in coordinator.data.values():
        if device.product_id not in LIGHT_PRODUCT_IDS:
            continue
        protocol = _resolve_protocol(device.properties)
        if protocol is not None:
            entities.append(BullLightEntity(coordinator, device.iot_id, protocol))
    async_add_entities(entities)


class BullLightEntity(BullDeviceEntity, LightEntity):
    """A MosHome dimmable, tunable-white light."""

    _attr_supported_color_modes: ClassVar[set[ColorMode]] = {ColorMode.COLOR_TEMP}

    def __init__(
        self, coordinator: BullCoordinator, iot_id: str, protocol: LightProtocol
    ) -> None:
        super().__init__(coordinator, iot_id, POWER, None, "light")
        self._protocol = protocol
        self._attr_min_color_temp_kelvin = MIN_KELVIN
        self._attr_max_color_temp_kelvin = MAX_KELVIN

    @property
    def is_on(self) -> bool:
        return bool(self._device and self._device.properties.get(POWER))

    @property
    def color_mode(self) -> ColorMode:
        return ColorMode.COLOR_TEMP

    @property
    def brightness(self) -> int | None:
        value = self._device.properties.get(BRIGHTNESS) if self._device else None
        try:
            return self._protocol.to_ha_brightness(float(value))
        except (TypeError, ValueError):
            return None

    @property
    def color_temp_kelvin(self) -> int | None:
        value = self._device.properties.get(COLOR_TEMP) if self._device else None
        try:
            ratio = max(0, min(1000, float(value))) / 1000
        except (TypeError, ValueError):
            return None
        return round(MIN_KELVIN + ratio * (MAX_KELVIN - MIN_KELVIN))

    async def async_turn_on(self, **kwargs) -> None:
        properties = {POWER: 1}
        if ATTR_BRIGHTNESS in kwargs:
            properties[BRIGHTNESS] = self._protocol.from_ha_brightness(
                kwargs[ATTR_BRIGHTNESS]
            )
        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            kelvin = max(MIN_KELVIN, min(MAX_KELVIN, kwargs[ATTR_COLOR_TEMP_KELVIN]))
            properties[COLOR_TEMP] = round(
                (kelvin - MIN_KELVIN) / (MAX_KELVIN - MIN_KELVIN) * 1000
            )
        await self.coordinator.async_set_properties(self._iot_id, properties)
        if self._device:
            self._device.properties.update(properties)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_property(self._iot_id, POWER, 0)
        if self._device:
            self._device.properties[POWER] = 0
        self.async_write_ha_state()
