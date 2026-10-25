"""Button entities for explicitly mapped Bull Thing Services."""

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import BUTTON_ENTITY_MAPPING
from .coordinator import BullCoordinator
from .entity import BullDeviceEntity


def _matches(values: dict, condition: dict) -> bool:
    return all(values.get(key) == expected for key, expected in condition.items())


class BullMappedButton(BullDeviceEntity, ButtonEntity):
    def __init__(self, coordinator, iot_id, spec):
        super().__init__(coordinator, iot_id, spec["id"], spec["name"], "button")
        self._service = spec["service"]
        self._condition = spec.get("available_when")

    @property
    def available(self) -> bool:
        device = self._device
        return bool(
            super().available
            and device
            and (not self._condition or _matches(device.properties, self._condition))
        )

    async def async_press(self) -> None:
        await self.coordinator.async_invoke_thing_service(self._iot_id, self._service)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: BullCoordinator = hass.data["bull_iot"][entry.entry_id]
    async_add_entities(
        [
            BullMappedButton(coordinator, device.iot_id, spec)
            for device in coordinator.data.values()
            for spec in BUTTON_ENTITY_MAPPING.get(device.product_id, ())
        ]
    )
