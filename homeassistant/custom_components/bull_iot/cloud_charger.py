"""Cloud Thing Service control for PID 193/195 charging stations."""

from __future__ import annotations

import asyncio

from homeassistant.exceptions import HomeAssistantError

WORK_STATE = "DeviceState.WorkState"
GUN_STATE = "DeviceState.GunState"
CHARGING_STATES = {2, 10}
STARTING = 1
STOPPING = 3
COMMAND_TIMEOUT = 10


def _as_int(value) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class BullCloudServiceCharger:
    """Control a charger through the same Thing Services used by MosHome."""

    def __init__(self, coordinator, iot_id: str) -> None:
        self.coordinator = coordinator
        self.iot_id = iot_id
        self._lock = asyncio.Lock()

    @property
    def device(self):
        return self.coordinator.devices.get(self.iot_id)

    @property
    def work_state(self) -> int | None:
        device = self.device
        return _as_int(device.properties.get(WORK_STATE)) if device else None

    @property
    def is_charging(self) -> bool | None:
        state = self.work_state
        return None if state is None else state in CHARGING_STATES

    async def async_set_charging(self, charging: bool) -> None:
        async with self._lock:
            device = self.device
            if device is None or device.status not in ("ONLINE", 1):
                raise HomeAssistantError("充电桩当前离线")
            if _as_int(device.properties.get(GUN_STATE)) == 0:
                raise HomeAssistantError("请插入充电枪")
            if self.is_charging is charging:
                return

            service = "AppStartCharge" if charging else "AppStopCharge"
            expected = STARTING if charging else STOPPING
            try:
                async with asyncio.timeout(COMMAND_TIMEOUT):
                    await self.coordinator.async_invoke_thing_service(
                        self.iot_id, service
                    )
                    while self.work_state != expected:
                        await self.coordinator.async_request_refresh()
                        if self.is_charging is charging:
                            return
                        await asyncio.sleep(0.5)
            except TimeoutError as err:
                raise HomeAssistantError(
                    f"{service} 已发送，但设备状态未在 {COMMAND_TIMEOUT} 秒内响应"
                ) from err
