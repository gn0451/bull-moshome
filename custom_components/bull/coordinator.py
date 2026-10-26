"""DataUpdateCoordinator for Bull IoT.

职责：
- 把同步客户端（requests）调用包进 executor，适配 HA 异步环境
- 首次刷新：登录 + 全量设备；周期刷新：增量属性更新
- MQTT 后台线程实时接收属性/状态变化，切回 HA 事件循环更新实体
- access_token 失效时自动刷新/重登；彻底失效时抛 ConfigEntryAuthFailed
"""

from __future__ import annotations

import inspect
import logging
import time
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import (
    AuthenticationError,
    BullCloudClient,
    BullCloudError,
    Device,
    flatten_properties,
)
from .const import (
    BLE_CHARGER_PRODUCT_IDS,
    CONF_FAMILY_IDS,
    CONF_MQTT_ENABLED,
    CONF_SCAN_INTERVAL,
    DEFAULT_MQTT_ENABLED,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    LEGACY_CONF_FAMILY_IDS,
    THING_SERVICE_CHARGER_PRODUCT_IDS,
)
from .mqtt_listener import BullMqttListener

_LOGGER = logging.getLogger(__name__)

# 单次刷新超过这个时长就打一条 info，方便用户反馈「启动很慢」时有据可查
SLOW_REFRESH_MS = 5000


class BullCoordinator(DataUpdateCoordinator[dict[str, Device]]):
    """Coordinator that keeps Bull devices in sync with the cloud."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        interval = int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        coordinator_kwargs = {
            "name": DOMAIN,
            "update_interval": timedelta(seconds=max(15, interval)),
        }
        # ``config_entry`` was added to DataUpdateCoordinator in a later core
        # release. Detect support by signature instead of catching TypeError,
        # which would also swallow genuine type errors from the constructor.
        if "config_entry" in inspect.signature(
            DataUpdateCoordinator.__init__
        ).parameters:
            super().__init__(hass, _LOGGER, config_entry=entry, **coordinator_kwargs)
        else:
            super().__init__(hass, _LOGGER, **coordinator_kwargs)
        self.entry = entry
        self.client = BullCloudClient()
        self.devices: dict[str, Device] = {}
        self._mqtt: BullMqttListener | None = None
        self._mqtt_token: str | None = None
        self.ble_chargers: dict[str, object] = {}
        # 最近一次刷新的分阶段耗时（毫秒），诊断与日志共用
        self.last_refresh_timings: dict[str, object] = {}
        self.cloud_chargers: dict[str, object] = {}

    @property
    def family_ids(self) -> list[int] | None:
        """Return the explicitly selected MosHome families.

        Entries created before family selection was introduced retain the old
        all-family behavior until the integration is reconfigured.
        """
        family_ids = self.entry.options.get(CONF_FAMILY_IDS)
        if family_ids is None:
            family_ids = self.entry.data.get(
                CONF_FAMILY_IDS, self.entry.data.get(LEGACY_CONF_FAMILY_IDS)
            )
        if family_ids is None:
            return None
        return [int(family_id) for family_id in family_ids]

    # ------------------------------------------------------------------ #
    # 首次刷新 / 周期刷新
    # ------------------------------------------------------------------ #
    async def _async_update_data(self) -> dict[str, Device]:
        """Fetch data from the cloud (runs on the coordinator's schedule)."""

        overall_started = time.perf_counter()

        def _sync_update() -> dict[str, Device]:
            # 计时边界由协调器控制：只统计本次刷新的请求
            self.client.request_timings.clear()
            try:
                if not self.client.access_token:
                    self.client.login(self.username, self.password)
                return self.client.refresh_devices(self.devices, self.family_ids)
            except AuthenticationError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            except BullCloudError as err:
                if err.code in (9008, 901006, 901015):
                    # 令牌或凭证问题：重登录一次再试
                    try:
                        self.client.login(self.username, self.password)
                    except AuthenticationError as auth_err:
                        raise ConfigEntryAuthFailed(str(auth_err)) from auth_err
                    return self.client.refresh_devices(self.devices, self.family_ids)
                raise UpdateFailed(str(err)) from err

        devices = await self.hass.async_add_executor_job(_sync_update)
        # refresh_devices 正常情况下原地更新 self.devices；若客户端返回了新
        # dict（防御未来变化），这里同步引用，保证 MQTT 回推与实体读到同一份数据
        if devices is not self.devices:
            self.devices = devices
        fetch_ms = (time.perf_counter() - overall_started) * 1000
        await self._async_manage_mqtt()
        self._setup_cloud_chargers()
        await self._async_setup_ble_chargers()
        self._record_timings(fetch_ms, (time.perf_counter() - overall_started) * 1000)
        return devices

    def _record_timings(self, fetch_ms: float, total_ms: float) -> None:
        """Split the refresh time into login / families / rooms and log it."""
        per_endpoint = dict(getattr(self.client, "request_timings", {}) or {})
        login_ms = sum(v for k, v in per_endpoint.items() if "/auth/form" in k)
        families_ms = sum(
            v
            for k, v in per_endpoint.items()
            if "/v2/families" in k or "/switch" in k
        )
        rooms_ms = sum(v for k, v in per_endpoint.items() if "/rooms" in k)
        self.last_refresh_timings = {
            "login_ms": round(login_ms, 1),
            "families_ms": round(families_ms, 1),
            "rooms_ms": round(rooms_ms, 1),
            "fetch_ms": round(fetch_ms, 1),
            "total_ms": round(total_ms, 1),
            "per_endpoint_ms": per_endpoint,
        }
        _LOGGER.debug("刷新耗时明细: %s", self.last_refresh_timings)
        if total_ms >= SLOW_REFRESH_MS:
            _LOGGER.info(
                "刷新耗时 %.1fs（登录 %.0fms / 家庭切换 %.0fms / 设备列表 %.0fms / 其余 %.0fms）",
                total_ms / 1000,
                login_ms,
                families_ms,
                rooms_ms,
                max(0.0, total_ms - login_ms - families_ms - rooms_ms),
            )

    def _setup_cloud_chargers(self) -> None:
        from .cloud_charger import BullCloudServiceCharger

        for device in self.devices.values():
            if device.product_id in THING_SERVICE_CHARGER_PRODUCT_IDS:
                self.cloud_chargers.setdefault(
                    device.iot_id, BullCloudServiceCharger(self, device.iot_id)
                )
        for iot_id in set(self.cloud_chargers) - set(self.devices):
            self.cloud_chargers.pop(iot_id, None)

    async def _async_setup_ble_chargers(self) -> None:
        """Start a local BLE owner for account devices that expose a valid identity."""
        try:
            from .ble import BleIdentity
            from .ble_charger import BullBleCharger
        except ImportError:
            return

        stale = set(self.ble_chargers) - set(self.devices)
        for iot_id in stale:
            charger = self.ble_chargers.pop(iot_id)
            await charger.async_stop()

        for device in self.devices.values():
            if device.product_id not in BLE_CHARGER_PRODUCT_IDS:
                continue
            raw = device.raw if isinstance(device.raw, dict) else {}
            detail = device.detail if isinstance(device.detail, dict) else {}
            dn = (
                raw.get("deviceName")
                or raw.get("dn")
                or detail.get("deviceName")
                or detail.get("dn")
            )
            if not isinstance(dn, str):
                continue
            dn = dn.upper()
            if (
                len(dn) != 12
                or any(char not in "0123456789ABCDEF" for char in dn)
                or device.iot_id in self.ble_chargers
            ):
                continue
            charger = BullBleCharger(
                self.hass,
                device,
                BleIdentity(device.product_id, dn),
                self.async_confirm_ble_random,
                self.async_confirm_ble_device,
                self._async_ble_update,
            )
            self.ble_chargers[device.iot_id] = charger
            await charger.async_start()

    @callback
    def _async_ble_update(self) -> None:
        self.async_set_updated_data(self.devices)

    @property
    def mqtt_transport(self) -> str | None:
        """Return the transport actually carrying MQTT push (``wss`` / ``tcp``)."""
        if self._mqtt is None:
            return None
        return "wss" if getattr(self._mqtt, "secure", False) else "tcp"

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
        enabled = self.entry.options.get(
            CONF_MQTT_ENABLED,
            self.entry.data.get(CONF_MQTT_ENABLED, DEFAULT_MQTT_ENABLED),
        )
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

        await self.async_set_properties(iot_id, {identifier: value})

    async def async_set_properties(self, iot_id: str, properties: dict) -> None:
        """Set one or more properties in a single cloud request.

        Cloud failures surface as HomeAssistantError so the UI shows the reason
        instead of a generic "unknown error". Entities write an optimistic state
        immediately; when MQTT push is off the authoritative state arrives with
        the next scheduled poll (or on an explicit ``homeassistant.update_entity``
        call, which triggers a coordinator refresh).
        """

        def _sync_set() -> None:
            try:
                self.client.set_properties(iot_id, properties)
            except AuthenticationError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            except BullCloudError as err:
                raise HomeAssistantError(f"下发指令失败：{err.message or err}") from err

        await self.hass.async_add_executor_job(_sync_set)

    async def async_invoke_thing_service(self, iot_id: str, identifier: str) -> None:
        await self.hass.async_add_executor_job(
            self.client.invoke_thing_service, iot_id, identifier
        )

    async def async_confirm_ble_random(self, pid: int, device_name: str) -> str:
        return await self.hass.async_add_executor_job(
            self.client.confirm_ble_random, pid, device_name
        )

    async def async_confirm_ble_device(
        self, random_value: str, pid: int, device_name: str, cipher: bytes
    ) -> str:
        return await self.hass.async_add_executor_job(
            self.client.confirm_ble_device,
            random_value,
            pid,
            device_name,
            cipher,
        )

    # ------------------------------------------------------------------ #
    # 卸载
    # ------------------------------------------------------------------ #
    async def async_shutdown(self) -> None:
        await self._async_stop_mqtt()
        chargers = list(self.ble_chargers.values())
        self.ble_chargers.clear()
        if chargers:
            import asyncio

            await asyncio.gather(
                *(charger.async_stop() for charger in chargers),
                return_exceptions=True,
            )
        await self.hass.async_add_executor_job(self.client.close)
