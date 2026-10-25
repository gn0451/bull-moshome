"""Number entities for Bull products."""

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import BullCoordinator
from .digital_display_socket import (
    DIGITAL_DISPLAY_SOCKET_PRODUCT_IDS,
    brightness_value,
    master_power_is_on,
)
from .entity import BullDeviceEntity


class BullScreenBrightness(BullDeviceEntity, NumberEntity):
    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = 1
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, coordinator, iot_id):
        super().__init__(coordinator, iot_id, "ScreenBrightValue", "屏幕亮度", "number")

    @property
    def available(self) -> bool:
        device = self._device
        return bool(
            super().available and device and master_power_is_on(device.properties)
        )

    @property
    def native_value(self) -> float | None:
        device = self._device
        return (
            brightness_value(device.properties.get(self._identifier))
            if device
            else None
        )

    async def async_set_native_value(self, value: float) -> None:
        device = self._device
        if not device or not master_power_is_on(device.properties):
            raise HomeAssistantError("设备总电源已关闭")
        normalized = round(max(1, min(100, value)))
        await self.coordinator.async_set_property(
            self._iot_id, self._identifier, normalized
        )
        device.properties[self._identifier] = normalized
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: BullCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            BullScreenBrightness(coordinator, device.iot_id)
            for device in coordinator.data.values()
            if device.product_id in DIGITAL_DISPLAY_SOCKET_PRODUCT_IDS
        ]
    )
