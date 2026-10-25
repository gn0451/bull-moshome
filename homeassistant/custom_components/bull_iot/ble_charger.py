"""Persistent Home Assistant Bluetooth owner for PID 309 chargers."""

from __future__ import annotations

import asyncio
import logging
import struct
from contextlib import suppress

from bleak import BleakClient
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from .ble import BleIdentity, BullBleError, BullBleSession, BusinessMessage

_LOGGER = logging.getLogger(__name__)

ATTR_WORK_STATE = 0x0105
ATTR_REAL_INFO = 0x0209
ATTR_FAULT_INFO = 0x0301
ATTR_GUN_STATE = 0x0600
ATTR_CHARGE_MODE = 0x0624
SERVICE_START = 0x9000
SERVICE_STOP = 0x9001
CHARGING_STATES = {2, 10}
START_CONFIRMED = {1, 2, 10}
STOP_CONFIRMED = {0, 3, 4}


def dn_from_ble_address(address: str) -> str | None:
    value = address.replace(":", "").upper()
    if len(value) != 12 or any(char not in "0123456789ABCDEF" for char in value):
        return None
    return value


class BullBleCharger:
    """Authenticate, monitor and control one local charger connection."""

    def __init__(
        self,
        hass,
        device,
        identity: BleIdentity,
        confirm_random,
        confirm_device,
        on_update,
    ) -> None:
        self.hass = hass
        self.device = device
        self.identity = identity
        self.confirm_random = confirm_random
        self.confirm_device = confirm_device
        self.on_update = on_update
        self.address = ":".join(identity.dn[i : i + 2] for i in range(0, 12, 2))
        self.unsubscribe = None
        self.lock = asyncio.Lock()
        self.stop_event = asyncio.Event()
        self.connection_lost = asyncio.Event()
        self.connected = asyncio.Event()
        self.runner: asyncio.Task | None = None
        self.client: BleakClient | None = None
        self.session: BullBleSession | None = None

    @property
    def available(self) -> bool:
        return bool(
            self.connected.is_set() and self.client and self.client.is_connected
        )

    async def async_start(self) -> None:
        from homeassistant.components import bluetooth
        from homeassistant.components.bluetooth import BluetoothScanningMode

        def discovered(service_info, _change) -> None:
            if dn_from_ble_address(service_info.address) == self.identity.dn:
                self.address = service_info.address

        self.unsubscribe = bluetooth.async_register_callback(
            self.hass,
            discovered,
            {"address": self.address, "connectable": True},
            BluetoothScanningMode.ACTIVE,
        )
        self.runner = self.hass.async_create_task(
            self._run(), f"Bull BLE connection {self.identity.dn}"
        )

    async def async_stop(self) -> None:
        if self.unsubscribe:
            self.unsubscribe()
            self.unsubscribe = None
        self.stop_event.set()
        if self.runner:
            self.runner.cancel()
            with suppress(asyncio.CancelledError):
                await self.runner
        self.runner = None
        await self._disconnect()

    def _best_device(self):
        from homeassistant.components import bluetooth

        return bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )

    def _disconnected(self, client: BleakClient) -> None:
        self.hass.loop.call_soon_threadsafe(self._mark_disconnected, client)

    def _mark_disconnected(self, client: BleakClient) -> None:
        if client is self.client:
            if self.session:
                self.session.disconnected()
            self.connection_lost.set()

    async def _connect(self) -> None:
        ble_device = self._best_device()
        if ble_device is None:
            raise BullBleError("HA Bluetooth 当前无法连接此充电桩")
        self.connection_lost.clear()
        client = await establish_connection(
            BleakClientWithServiceCache,
            ble_device,
            self.device.name or self.device.product_name or "Bull charger",
            disconnected_callback=self._disconnected,
            max_attempts=3,
            ble_device_callback=lambda: self._best_device() or ble_device,
        )
        self.client = client
        session = BullBleSession(
            client,
            self.identity,
            self.confirm_random,
            self.confirm_device,
            self._event,
        )
        self.session = session
        await session.async_start()
        async with self.lock:
            await self._refresh(session)
        if not client.is_connected or self.connection_lost.is_set():
            raise BullBleError("BLE 会话初始化期间连接断开")
        self.connected.set()
        self.on_update()

    async def _disconnect(self) -> None:
        async with self.lock:
            session, client = self.session, self.client
            self.session = None
            self.client = None
            self.connected.clear()
            self.on_update()
            if session:
                await session.async_stop()
            if client and client.is_connected:
                with suppress(Exception):
                    await client.disconnect()

    async def _event(self, message: BusinessMessage) -> None:
        if message.attr_type is not None:
            self._apply(message.attr_type, message.value)

    def _apply(self, attr_type: int, value: bytes) -> None:
        if attr_type in (ATTR_WORK_STATE, ATTR_GUN_STATE, ATTR_CHARGE_MODE) and value:
            identifier = {
                ATTR_WORK_STATE: "WorkState",
                ATTR_GUN_STATE: "GunState",
                ATTR_CHARGE_MODE: "ChargeMode",
            }[attr_type]
            self.device.properties[identifier] = value[0]
            if attr_type == ATTR_WORK_STATE:
                self.device.properties["ChargeSwitch"] = int(
                    value[0] in CHARGING_STATES
                )
        elif attr_type == ATTR_FAULT_INFO:
            self.device.properties["DeviceFaultCodeInfo"] = value.decode(
                errors="replace"
            ).rstrip("\0")
        elif attr_type == ATTR_REAL_INFO and len(value) >= 32:
            names = (
                "ChargingTime",
                "ChargeVoltage",
                "ChargeCurrent",
                "ChargeActivePower",
                "ChargeEnergyUsed",
                "ChargeMBTemp",
                "ChargeSlotTemp",
                "ChargeGunTemp",
            )
            for name, item in zip(
                names, struct.unpack("<I7f", value[:32]), strict=True
            ):
                self.device.properties[f"DeviceRealInfo.{name}"] = item
        self.on_update()

    async def _refresh(self, session: BullBleSession) -> None:
        for attr in (
            ATTR_WORK_STATE,
            ATTR_GUN_STATE,
            ATTR_CHARGE_MODE,
            ATTR_REAL_INFO,
            ATTR_FAULT_INFO,
        ):
            result = await session.request(attr)
            if result.attr_type is not None:
                self._apply(result.attr_type, result.value)

    async def _monitor(self, session: BullBleSession) -> None:
        disconnected = asyncio.create_task(self.connection_lost.wait())
        stopped = asyncio.create_task(self.stop_event.wait())
        reader = asyncio.create_task(session.async_wait_stopped())
        health = asyncio.create_task(self._health(session))
        tasks = {disconnected, stopped, reader, health}
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if stopped in done and self.stop_event.is_set():
                return
            if health in done:
                await health
            raise BullBleError("BLE 持久连接已停止")
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError, Exception):
                    await task

    async def _health(self, session: BullBleSession) -> None:
        while True:
            await asyncio.sleep(60)
            async with self.lock:
                if session is not self.session:
                    raise BullBleError("BLE 会话已切换")
                result = await session.request(ATTR_WORK_STATE)
                self._apply(ATTR_WORK_STATE, result.value)

    async def _run(self) -> None:
        delay = 5
        try:
            while not self.stop_event.is_set():
                try:
                    await self._connect()
                    delay = 5
                    if self.session is None:
                        raise BullBleError("BLE 会话未创建")
                    await self._monitor(self.session)
                except asyncio.CancelledError:
                    raise
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning(
                        "Bull BLE %s 连接失败，%s 秒后重试: %s",
                        self.device.iot_id,
                        delay,
                        err,
                    )
                finally:
                    await self._disconnect()
                try:
                    await asyncio.wait_for(self.stop_event.wait(), delay)
                except TimeoutError:
                    pass
                delay = min(delay * 2, 300)
        finally:
            await self._disconnect()

    async def _connected_session(self) -> BullBleSession:
        try:
            await asyncio.wait_for(self.connected.wait(), 90)
        except TimeoutError as err:
            raise BullBleError("充电桩 BLE 当前未连接") from err
        if self.session is None or self.client is None or not self.client.is_connected:
            raise BullBleError("充电桩 BLE 已断开")
        return self.session

    async def async_set_charging(self, enable: bool) -> None:
        session = await self._connected_session()
        async with self.lock:
            work = await session.request(ATTR_WORK_STATE)
            gun = await session.request(ATTR_GUN_STATE)
            if not work.value or not gun.value:
                raise BullBleError("充电桩未返回完整状态")
            if gun.value[0] == 0:
                raise BullBleError("请插入充电枪")
            if enable and work.value[0] in CHARGING_STATES:
                return
            if not enable and work.value[0] not in CHARGING_STATES:
                return
            await session.send_service(SERVICE_START if enable else SERVICE_STOP)
            await asyncio.sleep(3)
            result = await session.request(ATTR_WORK_STATE)
            self._apply(ATTR_WORK_STATE, result.value)
            expected = START_CONFIRMED if enable else STOP_CONFIRMED
            if not result.value or result.value[0] not in expected:
                observed = result.value[0] if result.value else None
                raise BullBleError(f"充电指令回读未确认: {observed}")

    async def async_set_charge_mode(self, mode: int) -> None:
        if mode not in (0, 1):
            raise ValueError(f"不支持的充电模式: {mode}")
        session = await self._connected_session()
        async with self.lock:
            try:
                response = await session.request(ATTR_CHARGE_MODE, bytes((mode,)))
                self._apply(ATTR_CHARGE_MODE, response.value)
            except BullBleError:
                _LOGGER.info("BLE 模式写入未返回 ACK，将执行回读")
            await asyncio.sleep(1)
            result = await session.request(ATTR_CHARGE_MODE)
            self._apply(ATTR_CHARGE_MODE, result.value)
            if not result.value or result.value[0] != mode:
                observed = result.value[0] if result.value else None
                raise BullBleError(f"充电模式回读未确认: {observed}")
