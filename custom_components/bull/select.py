"""Select entities for Bull charging products."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import BLE_CHARGER_PRODUCT_IDS, DOMAIN
from .coordinator import BullCoordinator
from .digital_display_socket import (
    DIGITAL_DISPLAY_SOCKET_PRODUCT_IDS,
    master_power_is_on,
)
from .entity import BullDeviceEntity

CHARGER_MODES = {"plug_and_charge": 0, "automatic_start": 1}
SOCKET_SELECTS = {
    "ChargeMode": {
        "name": "功率分配模式",
        "options": {"smart": 0, "dual_laptop": 1, "sleep": 2, "balanced": 3},
    },
    "OffScreenTime": {
        "name": "自动熄屏时间",
        "options": {
            "30_seconds": 0,
            "1_minute": 1,
            "5_minutes": 2,
            "10_minutes": 3,
            "30_minutes": 4,
            "always_on": 5,
        },
    },
    "TimerType": {"name": "时钟格式", "options": {"12_hour": 0, "24_hour": 1}},
}
CUSTOM_MODES = {
    4: "custom_1",
    5: "custom_2",
    6: "custom_3",
    7: "custom_4",
    8: "custom_5",
}


class BullPropertySelect(BullDeviceEntity, SelectEntity):
    def __init__(self, coordinator, iot_id, identifier, name, options):
        super().__init__(coordinator, iot_id, identifier, name, "select")
        self._values = options
        self._by_value = {value: option for option, value in options.items()}

    @property
    def available(self) -> bool:
        device = self._device
        return bool(
            super().available and device and master_power_is_on(device.properties)
        )

    @property
    def options(self) -> list[str]:
        options = list(self._values)
        device = self._device
        value = device.properties.get(self._identifier) if device else None
        if self._identifier == "ChargeMode" and value in CUSTOM_MODES:
            options.append(CUSTOM_MODES[value])
        return options

    @property
    def current_option(self) -> str | None:
        device = self._device
        value = device.properties.get(self._identifier) if device else None
        return self._by_value.get(value, CUSTOM_MODES.get(value))

    async def async_select_option(self, option: str) -> None:
        device = self._device
        if not device or not master_power_is_on(device.properties):
            raise HomeAssistantError("设备总电源已关闭")
        if option not in self._values:
            if option == self.current_option:
                return
            raise HomeAssistantError("自定义功率模式只能在公牛智家 App 中保存")
        value = self._values[option]
        await self.coordinator.async_set_property(self._iot_id, self._identifier, value)
        device.properties[self._identifier] = value
        self.async_write_ha_state()


class BullBleChargeModeSelect(BullDeviceEntity, SelectEntity):
    def __init__(self, coordinator, iot_id):
        super().__init__(coordinator, iot_id, "ChargeMode", "充电模式", "select")
        self._attr_options = list(CHARGER_MODES)

    @property
    def current_option(self) -> str | None:
        device = self._device
        value = device.properties.get("ChargeMode") if device else None
        return {value: name for name, value in CHARGER_MODES.items()}.get(value)

    @property
    def available(self) -> bool:
        charger = self.coordinator.ble_chargers.get(self._iot_id)
        return bool(super().available and charger and charger.available)

    async def async_select_option(self, option: str) -> None:
        charger = self.coordinator.ble_chargers.get(self._iot_id)
        if charger is None:
            raise HomeAssistantError("充电桩 BLE 当前不可用")
        await charger.async_set_charge_mode(CHARGER_MODES[option])


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: BullCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SelectEntity] = []
    for device in coordinator.data.values():
        if device.product_id in DIGITAL_DISPLAY_SOCKET_PRODUCT_IDS:
            for identifier, spec in SOCKET_SELECTS.items():
                entities.append(
                    BullPropertySelect(
                        coordinator,
                        device.iot_id,
                        identifier,
                        spec["name"],
                        spec["options"],
                    )
                )
        if device.product_id in BLE_CHARGER_PRODUCT_IDS:
            entities.append(BullBleChargeModeSelect(coordinator, device.iot_id))
    async_add_entities(entities)
