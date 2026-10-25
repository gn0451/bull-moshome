"""DataUpdateCoordinator for Bull IoT.

职责：
- 把同步客户端（requests）调用包进 executor，适配 HA 异步环境
- 首次刷新：登录 + 全量设备；周期刷新：增量属性更新
- MQTT 后台线程实时接收属性/状态变化，切回 HA 事件循环更新实体
- access_token 失效时自动刷新/重登；彻底失效时抛 ConfigEntryAuthFailed
"""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import AuthenticationError, BullCloudClient, BullCloudError, Device, flatten_properties
from .const import (
    CONF_MQTT_ENABLED,
    CONF_SCAN_INTERVAL,
    DEFAULT_MQTT_ENABLED,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .mqtt_listener import BullMqttListener

_LOGGER = logging.getLogger(__name__)


class BullCoordinator(DataUpdateCoordinator[dict[str, Device]]):
    """Coordinator that keeps Bull devices in sync with the cloud."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        interval = int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=max(15, interval)),
        )
        self.entry = entry
        self.client = BullCloudClient()
        self.devices: dict[str, Device] = {}
        self._mqtt: BullMqttListener | None = None
        self._mqtt_token: str | None = None

    # ------------------------------------------------------------------ #
    # 首次刷新 / 周期刷新
    # ------------------------------------------------------------------ #
    async def _async_update_data(self) -> dict[str, Device]:
        """Fetch data from the cloud (runs on the coordinator's schedule)."""

        def _sync_update() -> dict[str, Device]:
            try:
                if not self.client.access_token:
                    self.client.login(self.username, self.password)
                return self.client.refresh_devices(self.devices)
            except AuthenticationError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            except BullCloudError as err:
                if err.code in (9008, 901006, 901015):
                    # 令牌或凭证问题：重登录一次再试
                    try:
                        self.client.login(self.username, self.password)
                    except AuthenticationError as auth_err:
                        raise ConfigEntryAuthFailed(str(auth_err)) from auth_err
                    return self.client.refresh_devices(self.devices)
                raise UpdateFailed(str(err)) from err

        devices = await self.hass.async_add_executor_job(_sync_update)
        # refresh_devices 正常情况下原地更新 self.devices；若客户端返回了新
        # dict（防御未来变化），这里同步引用，保证 MQTT 回推与实体读到同一份数据
        if devices is not self.devices:
            self.devices = devices
        await self._async_manage_mqtt()
        return devices

    # ------------------------------------------------------------------ #
    # 凭证
    # ------------------------------------------------------------------ #
    @property
    def username(self) -> str:
        return self.entry.data["username"]

    @property
    def password(self) -> str:
        return self.entry.data["password"]

    # ------------------------------------------------------------------ #
    # MQTT 实时通道
    # ------------------------------------------------------------------ #
    async def _async_manage_mqtt(self) -> None:
        """Start/restart the MQTT listener when the token changes."""
        enabled = self.entry.options.get(CONF_MQTT_ENABLED, DEFAULT_MQTT_ENABLED)
        token = self.client.access_token
        if not enabled or not token or not self.client.openid:
            if self._mqtt is not None:
                await self._async_stop_mqtt()
            return
        if self._mqtt is not None and self._mqtt_token == token:
            return  # 已在运行且令牌未变
        await self._async_stop_mqtt()

        def _start() -> None:
            listener = BullMqttListener(
                self.client.openid,
                token,
                on_property=self._on_mqtt_property,
                on_status=self._on_mqtt_status,
            )
            listener.start()
            self._mqtt = listener

        await self.hass.async_add_executor_job(_start)
        self._mqtt_token = token

    async def _async_stop_mqtt(self) -> None:
        listener, self._mqtt = self._mqtt, None
        self._mqtt_token = None
        if listener is not None:
            await self.hass.async_add_executor_job(listener.stop)

    def _on_mqtt_property(self, iot_id: str, identifier: str, value) -> None:
        """MQTT 线程回调：调度到 HA 事件循环。"""
        self.hass.loop.call_soon_threadsafe(
            self._async_apply_property, iot_id, identifier, value
        )

    def _on_mqtt_status(self, iot_id: str, status) -> None:
        self.hass.loop.call_soon_threadsafe(self._async_apply_status, iot_id, status)

    @callback
    def _async_apply_property(self, iot_id: str, identifier: str, value) -> None:
        device = self.devices.get(iot_id)
        if device is None:
            return
        flatten_properties(device.properties, identifier, value)
        self.async_set_updated_data(self.devices)

    @callback
    def _async_apply_status(self, iot_id: str, status) -> None:
        device = self.devices.get(iot_id)
        if device is None:
            return
        device.status = status
        self.async_set_updated_data(self.devices)

    # ------------------------------------------------------------------ #
    # 控制
    # ------------------------------------------------------------------ #
    async def async_set_property(self, iot_id: str, identifier: str, value) -> None:
        """Set one device property (executor-wrapped)."""

        def _sync_set() -> None:
            try:
                self.client.set_property(iot_id, identifier, value)
            except AuthenticationError as err:
                raise ConfigEntryAuthFailed(str(err)) from err

        await self.hass.async_add_executor_job(_sync_set)

    # ------------------------------------------------------------------ #
    # 卸载
    # ------------------------------------------------------------------ #
    async def async_shutdown(self) -> None:
        await self._async_stop_mqtt()
        await self.hass.async_add_executor_job(self.client.close)
