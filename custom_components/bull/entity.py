"""Shared entity base class for Bull IoT."""

from __future__ import annotations

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import BLE_CHARGER_PRODUCT_IDS, DOMAIN, MANUFACTURER
from .coordinator import BullCoordinator


class BullDeviceEntity(CoordinatorEntity[BullCoordinator]):
    """Base entity bound to one device (or one channel of a device)."""

    def __init__(
        self,
        coordinator: BullCoordinator,
        iot_id: str,
        identifier: str,
        name: str | None,
        entity_kind: str,
    ) -> None:
        super().__init__(coordinator)  # CoordinatorEntity 初始化
        self._iot_id = iot_id
        self._identifier = identifier
        self._name = name
        # Keep the established Bull integration identity so HACS upgrades do
        # not duplicate entities or break automations and external allowlists.
        self._attr_unique_id = f"{iot_id}.{identifier}"
        self._attr_has_entity_name = True

    @property
    def _device(self):
        return self.coordinator.devices.get(self._iot_id)

    @property
    def name(self) -> str:
        if self._name:
            return self._name
        device = self._device
        if device is None:
            return self._identifier
        return f"{device.name or device.product_name} {self._identifier}"

    @property
    def available(self) -> bool:
        """Return true only when both the coordinator and device are online."""
        device = self._device
        ble_charger = self.coordinator.ble_chargers.get(self._iot_id)
        if ble_charger is not None:
            return bool(super().available and ble_charger.available)
        if device is not None and device.product_id in BLE_CHARGER_PRODUCT_IDS:
            return False
        return bool(
            super().available and device is not None and device.status in ("ONLINE", 1)
        )

    @property
    def device_info(self) -> DeviceInfo:
        device = self._device
        return DeviceInfo(
            identifiers={(DOMAIN, self._iot_id)},
            name=(device.name or device.product_name) if device else self._iot_id,
            manufacturer=MANUFACTURER,
            model=(device.model_name or device.product_name) if device else None,
            sw_version=device.firmware_version if device else None,
        )
