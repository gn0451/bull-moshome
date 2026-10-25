"""Cover platform for verified MosHome curtain products."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import COVER_PRODUCT_IDS, DOMAIN
from .coordinator import BullCoordinator
from .entity import BullDeviceEntity


@dataclass(frozen=True)
class CoverProtocol:
    control: str
    position: str


PROTOCOLS = (
    CoverProtocol("curtainConrtol", "curtainPosition"),
    CoverProtocol("CurtainConrtol", "CurtainPosition"),
)


def _resolve_protocol(properties: dict) -> CoverProtocol | None:
    matches = [
        protocol
        for protocol in PROTOCOLS
        if protocol.control in properties and protocol.position in properties
    ]
    return matches[0] if len(matches) == 1 else None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up verified cover entities."""
    coordinator: BullCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for device in coordinator.data.values():
        if device.product_id not in COVER_PRODUCT_IDS:
            continue
        protocol = _resolve_protocol(device.properties)
        if protocol is not None:
            entities.append(BullCoverEntity(coordinator, device.iot_id, protocol))
    async_add_entities(entities)


class BullCoverEntity(BullDeviceEntity, CoverEntity):
    """A MosHome curtain entity with position control."""

    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.SET_POSITION
        | CoverEntityFeature.STOP
    )

    def __init__(
        self, coordinator: BullCoordinator, iot_id: str, protocol: CoverProtocol
    ) -> None:
        super().__init__(coordinator, iot_id, protocol.position, None, "cover")
        self._protocol = protocol

    @property
    def current_cover_position(self) -> int | None:
        value = (
            self._device.properties.get(self._protocol.position)
            if self._device
            else None
        )
        try:
            return max(0, min(100, int(value)))
        except (TypeError, ValueError):
            return None

    @property
    def is_closed(self) -> bool | None:
        position = self.current_cover_position
        return position == 0 if position is not None else None

    async def _set(self, identifier: str, value: int) -> None:
        await self.coordinator.async_set_property(self._iot_id, identifier, value)
        if self._device:
            self._device.properties[identifier] = value
        self.async_write_ha_state()

    async def async_open_cover(self, **kwargs) -> None:
        await self._set(self._protocol.control, 1)

    async def async_close_cover(self, **kwargs) -> None:
        await self._set(self._protocol.control, 0)

    async def async_stop_cover(self, **kwargs) -> None:
        await self._set(self._protocol.control, 2)

    async def async_set_cover_position(self, **kwargs) -> None:
        await self._set(self._protocol.position, kwargs[ATTR_POSITION])
