"""Authenticated FEB3 BLE protocol used by the PID 309 charger."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from bleak import BleakClient
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_LOGGER = logging.getLogger(__name__)

SERVICE_UUID = "0000feb3-0000-1000-8000-00805f9b34fb"
WRITE_UUIDS = (
    ("0000fed5-0000-1000-8000-00805f9b34fb", True),
    ("0000fed7-0000-1000-8000-00805f9b34fb", False),
)
NOTIFY_UUIDS = (
    "0000fed8-0000-1000-8000-00805f9b34fb",
    "0000fed6-0000-1000-8000-00805f9b34fb",
)
CMD_EVENT, CMD_REQUEST, CMD_RESPONSE, CMD_BUBBLE = 1, 2, 3, 12
CMD_RANDOM, CMD_CIPHER, CMD_AUTH_RESULT, CMD_AUTH_DONE = 16, 17, 18, 19


class BullBleError(RuntimeError):
    """A BLE protocol or transport operation failed."""


@dataclass(frozen=True, slots=True)
class BleIdentity:
    pid: int
    dn: str


@dataclass(frozen=True, slots=True)
class BusinessMessage:
    command: int
    message_id: int
    opcode: int | None
    transaction_id: int | None
    attr_type: int | None
    value: bytes


def _encrypt(clear: bytes, key: bytes, iv: bytes) -> bytes:
    padding = 16 - len(clear) % 16
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return encryptor.update(clear + bytes((padding,)) * padding) + encryptor.finalize()


def _decrypt(ciphertext: bytes, size: int, key: bytes, iv: bytes) -> bytes:
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    padding = padded[-1] if padded else 0
    if not 1 <= padding <= 16 or padded[-padding:] != bytes((padding,)) * padding:
        raise BullBleError("BLE 帧填充无效")
    clear = padded[:-padding]
    if len(clear) != size:
        raise BullBleError("BLE 帧长度不匹配")
    return clear


class BullBleSession:
    """One authenticated protocol session over an already connected client."""

    def __init__(
        self,
        client: BleakClient,
        identity: BleIdentity,
        confirm_random,
        confirm_device,
        on_event=None,
    ):
        self.client = client
        self.identity = identity
        self.confirm_random = confirm_random
        self.confirm_device = confirm_device
        self.on_event: Callable[[BusinessMessage], Awaitable[None]] | None = on_event
        self.queue: asyncio.Queue[bytes] = asyncio.Queue()
        self.fragments: dict[tuple[int, int, bool], dict[int, bytes]] = {}
        self.fragment_last: dict[tuple[int, int, bool], int] = {}
        self.pending: dict[int, tuple[int, int, asyncio.Future]] = {}
        self.lock = asyncio.Lock()
        self.message_id = 0
        self.write_char = None
        self.write_response = True
        self.key: bytes | None = None
        self.iv: bytes | None = None
        self.reader: asyncio.Task | None = None

    def _next_id(self) -> int:
        self.message_id = self.message_id % 15 + 1
        return self.message_id

    def _notification(self, _sender, data: bytearray) -> None:
        self.queue.put_nowait(bytes(data))

    async def async_start(self) -> None:
        if not self.client.is_connected:
            raise BullBleError("BLE 在会话初始化前已断开")
        services = self.client.services
        if services.get_service(SERVICE_UUID) is None:
            raise BullBleError("设备未提供公牛 FEB3 服务")
        for uuid, response in WRITE_UUIDS:
            char = services.get_characteristic(uuid)
            if char is not None:
                self.write_char, self.write_response = char, response
                break
        if self.write_char is None:
            raise BullBleError("未找到可写 BLE 特征")
        subscribed = False
        for uuid in NOTIFY_UUIDS:
            char = services.get_characteristic(uuid)
            if char is not None:
                await self.client.start_notify(char, self._notification)
                subscribed = True
        if not subscribed:
            raise BullBleError("未找到 BLE 通知特征")
        await self._authenticate()
        self.reader = asyncio.create_task(self._reader_loop())

    async def async_stop(self) -> None:
        if self.reader and not self.reader.done():
            self.reader.cancel()
        if self.reader:
            try:
                await self.reader
            except asyncio.CancelledError:
                pass
            except Exception:
                _LOGGER.debug("BLE reader stopped with an error", exc_info=True)
        self.reader = None

    def disconnected(self) -> None:
        if self.reader and not self.reader.done():
            self.reader.cancel()

    async def async_wait_stopped(self) -> None:
        if self.reader is None:
            raise BullBleError("BLE 通知任务未运行")
        await asyncio.shield(self.reader)

    async def _write(
        self, message_id: int, command: int, payload: bytes, encrypted: bool
    ) -> None:
        if self.write_char is None:
            raise BullBleError("BLE 写特征未初始化")
        data = payload
        marker = message_id
        if encrypted:
            if self.key is None or self.iv is None:
                raise BullBleError("BLE 会话尚未认证")
            data = _encrypt(payload, self.key, self.iv)
            marker |= 0x10
        frame = bytes((marker, command, 0, len(payload))) + data
        await self.client.write_gatt_char(
            self.write_char, frame, response=self.write_response
        )

    async def _send(self, command: int, payload: bytes, encrypted: bool = False) -> int:
        message_id = self._next_id()
        await self._write(message_id, command, payload, encrypted)
        return message_id

    async def _next_frame(self, timeout: float | None) -> tuple[int, int, bytes]:
        try:
            raw = (
                await asyncio.wait_for(self.queue.get(), timeout)
                if timeout
                else await self.queue.get()
            )
        except TimeoutError as err:
            raise BullBleError("等待 BLE 响应超时") from err
        if len(raw) < 4:
            raise BullBleError("BLE 帧过短")
        message_id, command, fragment, size = raw[0] & 15, raw[1], raw[2], raw[3]
        encrypted = bool(raw[0] & 16) and command not in (32, 33)
        payload = raw[4:]
        if encrypted:
            if self.key is None or self.iv is None:
                raise BullBleError("认证前收到加密 BLE 帧")
            payload = _decrypt(payload, size, self.key, self.iv)
        index, last = fragment & 15, fragment >> 4
        key = (message_id, command, encrypted)
        if index == 0:
            self.fragments[key] = {}
            self.fragment_last[key] = last
        if key not in self.fragments or self.fragment_last[key] != last:
            raise BullBleError("BLE 分片顺序无效")
        self.fragments[key][index] = payload
        if len(self.fragments[key]) != last + 1:
            return await self._next_frame(timeout)
        result = b"".join(self.fragments[key][i] for i in range(last + 1))
        self.fragments.pop(key, None)
        self.fragment_last.pop(key, None)
        return message_id, command, result

    async def _wait_command(self, expected: int) -> bytes:
        deadline = asyncio.get_running_loop().time() + 12
        while True:
            _, command, payload = await self._next_frame(
                max(0.1, deadline - asyncio.get_running_loop().time())
            )
            if command == expected:
                return payload

    async def _authenticate(self) -> None:
        random_value = await self.confirm_random(self.identity.pid, self.identity.dn)
        iv = random_value.encode()
        if len(iv) != 16:
            raise BullBleError("云端随机数不是 16 字节")
        await self._send(CMD_RANDOM, iv)
        cipher = await self._wait_command(CMD_CIPHER)
        key_hex = await self.confirm_device(
            random_value, self.identity.pid, self.identity.dn, cipher
        )
        self.key, self.iv = bytes.fromhex(key_hex), iv
        await self._send(CMD_AUTH_RESULT, b"\0")
        await self._wait_command(CMD_AUTH_DONE)

    @staticmethod
    def _decode(command: int, message_id: int, payload: bytes) -> BusinessMessage:
        if len(payload) < 7 or payload[0] != 0x41:
            return BusinessMessage(command, message_id, None, None, None, payload)
        return BusinessMessage(
            command,
            message_id,
            payload[1],
            payload[4],
            int.from_bytes(payload[5:7], "little"),
            payload[7:],
        )

    async def _reader_loop(self) -> None:
        try:
            while True:
                message_id, command, payload = await self._next_frame(None)
                message = self._decode(command, message_id, payload)
                if command in (CMD_EVENT, CMD_BUBBLE):
                    if self.on_event:
                        await self.on_event(message)
                    continue
                pending = self.pending.get(message_id)
                if command == CMD_RESPONSE and pending and not pending[2].done():
                    transaction, attr, future = pending
                    if (
                        message.opcode == 0xD3
                        and message.transaction_id == transaction
                        and message.attr_type == attr
                    ):
                        future.set_result(message)
        finally:
            error = BullBleError("BLE 通知任务已停止")
            for _, _, future in self.pending.values():
                if not future.done():
                    future.set_exception(error)

    async def request(
        self, attr_type: int, value: bytes | None = None
    ) -> BusinessMessage:
        async with self.lock:
            if not self.client.is_connected or not self.reader or self.reader.done():
                raise BullBleError("BLE 会话未连接")
            transaction = self._next_id()
            opcode = 0xD0 if value is None else 0xD1
            payload = (
                b"\x41"
                + bytes((opcode,))
                + b"\x12\x07"
                + bytes((transaction,))
                + attr_type.to_bytes(2, "little")
                + (value or b"")
            )
            message_id = self._next_id()
            future = asyncio.get_running_loop().create_future()
            self.pending[message_id] = (transaction, attr_type, future)
            try:
                await self._write(message_id, CMD_REQUEST, payload, True)
                return await asyncio.wait_for(asyncio.shield(future), 12)
            except TimeoutError as err:
                raise BullBleError("等待 BLE 业务响应超时") from err
            finally:
                self.pending.pop(message_id, None)
                if not future.done():
                    future.cancel()

    async def send_service(self, attr_type: int) -> None:
        transaction = self._next_id()
        payload = (
            b"\x41\xd1\x12\x07"
            + bytes((transaction,))
            + attr_type.to_bytes(2, "little")
        )
        await self._send(CMD_REQUEST, payload, True)
