"""Switch platform for Bull IoT: one entity per controllable channel."""

from __future__ import annotations

import re

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import BLE_CHARGER_PRODUCT_IDS, CHARGER_PRODUCT_IDS, DOMAIN
from .coordinator import BullCoordinator
from .device_profiles import SupportTier, infer_switch_tier
from .digital_display_socket import (
    DIGITAL_DISPLAY_SOCKET_PORT_NAMES,
    DIGITAL_DISPLAY_SOCKET_PORTS,
    DIGITAL_DISPLAY_SOCKET_PRODUCT_IDS,
    master_power_is_on,
    port_property_value,
)
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
    coordinator: BullCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[BullSwitchEntity] = []

    for device in coordinator.data.values():
        if device.product_id in DIGITAL_DISPLAY_SOCKET_PRODUCT_IDS:
            entities.append(
                BullDigitalDisplaySocketSwitch(
                    coordinator, device.iot_id, "PowerSwitch", "总电源"
                )
            )
            entities.extend(
                BullDigitalDisplaySocketSwitch(
                    coordinator,
                    device.iot_id,
                    f"{port}PowerSwitch",
                    DIGITAL_DISPLAY_SOCKET_PORT_NAMES[port],
                    port=port,
                    guarded=True,
                )
                for port in DIGITAL_DISPLAY_SOCKET_PORTS
            )
            entities.append(
                BullDigitalDisplaySocketSwitch(
                    coordinator,
                    device.iot_id,
                    "OffScreenSwitch",
                    "自动熄屏",
                    guarded=True,
                )
            )
            continue
        if device.product_id in BLE_CHARGER_PRODUCT_IDS:
            if device.iot_id in coordinator.ble_chargers:
                entities.append(BullChargerSwitch(coordinator, device.iot_id))
            continue
        if device.product_id in CHARGER_PRODUCT_IDS:
            if (
                "ChargeSwitch" in device.properties
                or device.iot_id in coordinator.cloud_chargers
                or device.iot_id in coordinator.ble_chargers
            ):
                entities.append(BullChargerSwitch(coordinator, device.iot_id))
            continue
        identifiers = _collect_switch_identifiers(device.properties)
        support_tier = infer_switch_tier(
            device.product_id, device.properties, identifiers
        )
        if support_tier in (None, SupportTier.READ_ONLY):
            continue
        # 收集通道名: __name__PowerSwitch_N -> "客厅吊灯"
        channel_names = {
            key[len("__name__") :]: value
            for key, value in device.properties.items()
            if key.startswith("__name__") and value
        }
        for identifier in identifiers:
            name = channel_names.get(identifier)
            entities.append(
                BullSwitchEntity(
                    coordinator,
                    device.iot_id,
                    identifier,
                    name,
                    support_tier=support_tier,
                )
            )

    async_add_entities(entities)


class BullSwitchEntity(BullDeviceEntity, SwitchEntity):
    """A controllable channel of a Bull device."""

    def __init__(
        self,
        coordinator: BullCoordinator,
        iot_id: str,
        identifier: str,
        name: str | None,
        *,
        support_tier: SupportTier = SupportTier.PROFILED,
    ) -> None:
        super().__init__(coordinator, iot_id, identifier, name, "switch")
        self._support_tier = support_tier
        self._attr_entity_registry_enabled_default = (
            support_tier is not SupportTier.INFERRED_SAFE
        )

    @property
    def extra_state_attributes(self) -> dict[str, str | int]:
        """Expose why this entity exists without leaking device identifiers."""
        device = self._device
        return {
            "support_tier": self._support_tier.value,
            "product_id": device.product_id if device else -1,
        }

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


class BullDigitalDisplaySocketSwitch(BullSwitchEntity):
    """Master, port and screen switches for PID 296."""

    def __init__(
        self, coordinator, iot_id, identifier, name, *, port=None, guarded=False
    ):
        self._port = port
        self._guarded = guarded
        super().__init__(coordinator, iot_id, identifier, name)

    @property
    def available(self) -> bool:
        device = self._device
        return bool(
            super().available
            and device
            and (not self._guarded or master_power_is_on(device.properties))
        )

    @property
    def is_on(self) -> bool | None:
        device = self._device
        if not device:
            return None
        value = (
            port_property_value(device.properties, self._port, "PowerSwitch")
            if self._port
            else device.properties.get(self._identifier)
        )
        return None if value is None else bool(value)

    def _ensure_available(self) -> None:
        if (
            self._guarded
            and self._device
            and not master_power_is_on(self._device.properties)
        ):
            raise HomeAssistantError("设备总电源已关闭")

    async def async_turn_on(self, **kwargs) -> None:
        self._ensure_available()
        await super().async_turn_on(**kwargs)

    async def async_turn_off(self, **kwargs) -> None:
        self._ensure_available()
        await super().async_turn_off(**kwargs)


class BullChargerSwitch(BullDeviceEntity, SwitchEntity):
    """Charging switch routed to cloud properties, Thing Service or local BLE."""

    def __init__(self, coordinator, iot_id):
        super().__init__(coordinator, iot_id, "ChargeSwitch", "充电", "switch")

    @property
    def available(self) -> bool:
        if self._iot_id in self.coordinator.ble_chargers:
            return bool(self.coordinator.ble_chargers[self._iot_id].available)
        return super().available

    @property
    def is_on(self) -> bool | None:
        cloud = self.coordinator.cloud_chargers.get(self._iot_id)
        if cloud:
            return cloud.is_charging
        device = self._device
        if not device:
            return None
        value = device.properties.get("ChargeSwitch")
        if value is None:
            value = device.properties.get("WorkState")
            return None if value is None else value in (2, 10)
        return bool(value)

    async def _set(self, value: bool) -> None:
        ble = self.coordinator.ble_chargers.get(self._iot_id)
        cloud = self.coordinator.cloud_chargers.get(self._iot_id)
        if ble:
            await ble.async_set_charging(value)
        elif self._device and self._device.product_id in BLE_CHARGER_PRODUCT_IDS:
            raise HomeAssistantError("充电桩 BLE 当前不可用")
        elif cloud:
            await cloud.async_set_charging(value)
        else:
            await self.coordinator.async_set_property(
                self._iot_id, "ChargeSwitch", int(value)
            )

    async def async_turn_on(self, **kwargs) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._set(False)
