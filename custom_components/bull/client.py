"""公牛智家云（MosHome / api.iotbull.com）Python 客户端。

协议常量最初依据 MosHome 5.1.13 分析，并经 5.3.1、云端 API 与设备验收。
仅使用公牛账号体系内的开放云接口，用于个人设备的接入与自动化。
"""

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from urllib.parse import urlencode, urljoin

import requests

from .crypto import encrypt_username, hash_password
from .signing import API_HOST, build_headers

API_URL = f"https://{API_HOST}"


class BullCloudError(Exception):
    """云端返回的业务错误。"""

    def __init__(self, operation: str, code=None, message: str = ""):
        self.operation = operation
        self.code = code
        self.message = message
        super().__init__(f"{operation} 失败: code={code} message={message!r}")


class AuthenticationError(BullCloudError):
    """用户名/密码错误。"""


class TokenExpiredError(BullCloudError):
    """access_token 失效，需要刷新或重新登录。"""

    def __init__(self):
        super().__init__("token 失效", code=9008, message="请重新登录")


# 登录接口的业务错误码
LOGIN_ERRORS = {
    901006: "用户名或密码错误",
    901001: "用户不存在",
    901015: "密码错误",
}


@dataclass
class Device:
    """一台公牛智家设备（可能包含多个开关/通道，共享同一 iotId）。"""

    iot_id: str
    product_id: int
    name: str = ""
    room: str = ""
    status: str = ""
    product_name: str = ""
    model_name: str = ""
    firmware_version: str = ""
    properties: dict = field(default_factory=dict)  # 扁平化后的 identifier -> value
    raw: dict = field(default_factory=dict)
    detail: dict = field(default_factory=dict)

    def describe(self) -> str:
        lines = [
            (
                f"  [{self.iot_id}] {self.name or self.product_name}"
                f"  (房间: {self.room or '-'}, 状态: {self.status or '-'})"
            ),
            f"      型号: {self.product_name} / {self.model_name} / 固件 {self.firmware_version}",
        ]
        if self.properties:
            props = ", ".join(f"{k}={v}" for k, v in sorted(self.properties.items()))
            lines.append(f"      属性: {props}")
        return "\n".join(lines)


def flatten_properties(target: dict, identifier: str, value) -> None:
    """把嵌套属性拍平成 identifier / identifier.child 两种键。

    模块级纯函数：客户端解析设备列表与 MQTT 属性回推共用。
    """
    target[identifier] = value
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            target[f"{identifier}.{child_key}"] = child_value


class BullCloudClient:
    """公牛智家云 HTTP 客户端。

    用法::

        client = BullCloudClient()
        client.login("username", "password")
        devices = client.list_devices()
        client.set_property(devices[0].iot_id, "PowerSwitch", 1)
    """

    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout
        self.session = requests.Session()
        # requests.Session 不保证线程安全：并发拉设备详情时每个线程各用一个
        self._local = threading.local()
        self._sessions: list[requests.Session] = [self.session]
        self._sessions_lock = threading.Lock()
        self._timings_lock = threading.Lock()
        # 并发度：单设备详情约 400ms，19 台串行要 8s，4 路并发压到 ~2s
        self.device_info_workers = 4
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.openid: str | None = None
        self.username: str | None = None
        self.password: str | None = None
        self._families: list[dict] = []
        # 每个端点的累计耗时（毫秒），由调用方决定何时清零，用于定位慢请求
        self.request_timings: dict[str, float] = {}

    # ------------------------------------------------------------------ #
    # 基础请求
    # ------------------------------------------------------------------ #
    def _session(self) -> requests.Session:
        """Return this thread's own Session (``requests.Session`` is not thread safe)."""
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            self._local.session = session
            with self._sessions_lock:
                self._sessions.append(session)
        return session

    def _request(
        self,
        method: str,
        path: str,
        content_type: str = "application/json",
        body: str = "",
        query: dict | None = None,
        extra_headers: dict | None = None,
        bearer: bool = True,
    ) -> dict:
        """按端点记录耗时后转发给 :meth:`_request_impl`。"""
        started = time.perf_counter()
        try:
            return self._request_impl(
                method, path, content_type, body, query, extra_headers, bearer
            )
        finally:
            # 家庭 ID 等数字段归一化，避免每个家庭各占一个键
            key = f"{method} {re.sub(r'/[0-9]+', '/{id}', path)}"
            elapsed = (time.perf_counter() - started) * 1000
            with self._timings_lock:
                self.request_timings[key] = round(
                    self.request_timings.get(key, 0.0) + elapsed, 1
                )

    def _request_impl(
        self,
        method: str,
        path: str,
        content_type: str = "application/json",
        body: str = "",
        query: dict | None = None,
        extra_headers: dict | None = None,
        bearer: bool = True,
    ) -> dict:
        """发送一个带 CloudAPI 签名的请求，返回解析后的 JSON。"""
        headers = build_headers(method, path, content_type, body, query)
        if extra_headers:
            headers.update(extra_headers)
        if bearer and self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"

        resp = self._session().request(
            method,
            urljoin(API_URL, path),
            headers=headers,
            data=body.encode("utf-8"),
            timeout=self.timeout,
        )
        try:
            res = resp.json()
        except json.JSONDecodeError as err:
            raise BullCloudError(
                f"{method} {path}", code=resp.status_code, message=resp.text[:200]
            ) from err

        if not res.get("success"):
            if res.get("error") == "invalid_token" or res.get("code") == 9008:
                raise TokenExpiredError()
            raise BullCloudError(
                f"{method} {path}", code=res.get("code"), message=res.get("message", "")
            )
        return res

    def _request_with_auth_recovery(self, method: str, path: str, **kwargs) -> dict:
        """带一次 token 恢复重试的请求。"""
        try:
            return self._request(method, path, **kwargs)
        except TokenExpiredError:
            self.refresh_access_token()
            return self._request(method, path, **kwargs)

    # ------------------------------------------------------------------ #
    # 登录与令牌
    # ------------------------------------------------------------------ #
    def login(self, username: str, password: str) -> None:
        """账号密码登录，获取 access_token / refresh_token / openid。

        实测要点（2026-10）：
        - 用户名 AES 加密、密码双 sha256 派生后，以 x-www-form-urlencoded 提交
        - 签名的 CanonicalResource 用表单字段本身作 query（网关行为）
        - 必须携带头部 Login_parameter: APP_PWD（大小写敏感）
        """
        form = {
            "username": encrypt_username(username),
            "password": hash_password(password),
        }
        try:
            res = self._request(
                "POST",
                "/mos/uic/v2/auth/form",
                content_type="application/x-www-form-urlencoded; charset=utf-8",
                body=urlencode(form),
                extra_headers={"Login_parameter": "APP_PWD"},
                bearer=False,
            )
        except BullCloudError as err:
            if err.code in LOGIN_ERRORS:
                raise AuthenticationError(
                    "登录", err.code, LOGIN_ERRORS[err.code]
                ) from err
            raise

        result = res["result"]
        self.username = username
        self.password = password
        self.access_token = result["access_token"]
        self.refresh_token = result["refresh_token"]
        self.openid = str(result["openid"])

    def refresh_access_token(self) -> None:
        """用 refresh_token 换新的 access_token；失败则回退到重新登录。"""
        try:
            res = self._request(
                "POST",
                "/mos/uic/v1/auth/token",
                content_type="application/json; charset=utf-8",
                body=json.dumps(
                    {
                        "refresh_token": self.refresh_token,
                        "grant_type": "refresh_token",
                    },
                    separators=(",", ":"),
                ),
                bearer=False,
            )
            self.access_token = res["result"]["access_token"]
            self.refresh_token = res["result"]["refresh_token"]
        except (TokenExpiredError, BullCloudError):
            if not (self.username and self.password):
                raise
            self.login(self.username, self.password)

    # ------------------------------------------------------------------ #
    # 家庭与设备
    # ------------------------------------------------------------------ #
    def get_families(self) -> list[dict]:
        """获取账号下的家庭列表。"""
        res = self._request_with_auth_recovery("GET", "/v2/families")
        self._families = res["result"]
        return self._families

    def switch_family(self, family_id: int) -> None:
        """切换当前家庭（设备列表接口只返回最近访问家庭的设备）。"""
        self._request_with_auth_recovery(
            "POST",
            f"/v1/families/{family_id}/switch",
            content_type="application/json",
            body="{}",
        )

    def get_rooms_and_devices(self) -> list[dict]:
        """获取当前家庭的房间与设备列表（MosHome v3 接口）。"""
        res = self._request_with_auth_recovery("GET", "/mos/home/v3/rooms")
        return res["result"]["devices"][0]["deviceList"]

    def get_device_info(self, iot_id: str) -> dict:
        """获取单台设备的详细信息（型号、固件等）。"""
        res = self._request_with_auth_recovery(
            "GET", f"/mos/device/v1/deviceInfo/{iot_id}/get"
        )
        return res["result"]

    def list_devices(self, family_ids: list[int] | None = None) -> list[Device]:
        """完整流程：登录态 -> 遍历家庭 -> 汇总所有设备。"""
        return list(self.refresh_devices({}, family_ids).values())

    def refresh_devices(
        self, devices: dict[str, Device], family_ids: list[int] | None = None
    ) -> dict[str, Device]:
        """把各家庭设备刷新进已有缓存（新设备才拉取一次详情，适合定时轮询）。"""
        if family_ids is None:
            families = self.get_families()
            family_ids = [f["familyId"] for f in families]

        seen_iot_ids: set[str] = set()
        new_iot_ids: list[str] = []
        for family_id in family_ids:
            self.switch_family(family_id)
            for info in self.get_rooms_and_devices():
                seen_iot_ids.add(info["iotId"])
                self._parse_device(devices, info, new_iot_ids)
        # 新设备的型号/固件要逐台查详情（单台约 400ms），串行会把启动拖到 10s，
        # 这里用小并发补，失败不影响主流程。
        self._enrich_device_info(devices, new_iot_ids)

        # Only prune after every selected family completed successfully. This
        # removes devices deleted from MosHome without turning a partial cloud
        # failure into accidental cache loss.
        for iot_id in set(devices) - seen_iot_ids:
            devices.pop(iot_id, None)
        return devices

    def _parse_device(
        self,
        devices: dict[str, Device],
        info: dict,
        new_iot_ids: list[str] | None = None,
    ) -> None:
        """解析一条设备记录；deviceEntity=true 的是主设备条目，其余是功能实体。

        ``new_iot_ids`` 不为 None 时只登记待补详情的设备，由 :meth:`refresh_devices`
        统一并发拉取；直接调用本方法（旧用法）时退化为同步拉取。
        """
        iot_id = info["iotId"]
        product_id = info["product"]["globalProductId"]

        if iot_id not in devices:
            device = Device(iot_id=iot_id, product_id=product_id, raw=info)
            device.status = info.get("status", "")
            device.room = info.get("roomName", "")
            for prop in info.get("property", {}).values():
                flatten_properties(device.properties, prop["identifier"], prop["value"])
            if new_iot_ids is None:
                self._fetch_device_info(device)
            else:
                new_iot_ids.append(iot_id)
            devices[iot_id] = device
        else:
            device = devices[iot_id]
            device.product_id = product_id
            device.status = info.get("status", device.status)
            device.room = info.get("roomName", device.room)
            device.raw = info
            for prop in info.get("property", {}).values():
                flatten_properties(device.properties, prop["identifier"], prop["value"])

        if info.get("deviceEntity"):
            # 主设备条目携带用户设置的昵称
            device.name = info.get("nickName") or device.name
        elif info.get("nickName"):
            # 功能实体条目：记录通道名（如 "客厅吊灯"）
            element = info.get("elementIdentifier")
            if element:
                device.properties.setdefault(f"__name__{element}", info["nickName"])

    def _enrich_device_info(
        self, devices: dict[str, Device], iot_ids: list[str]
    ) -> None:
        """Fetch model/firmware for new devices with bounded concurrency."""
        # Device.detail 默认是 {}，所以用「空字典」表示还没拉过；
        # 拉取失败的设备会写入占位标记，避免每轮刷新都重试。
        todo = [
            iot_id
            for iot_id in dict.fromkeys(iot_ids)
            if iot_id in devices and not devices[iot_id].detail
        ]
        if not todo:
            return
        workers = max(1, min(self.device_info_workers, len(todo)))
        if workers == 1:
            for iot_id in todo:
                self._fetch_device_info(devices[iot_id])
            return
        with ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="bull-info"
        ) as pool:
            list(pool.map(lambda iot_id: self._fetch_device_info(devices[iot_id]), todo))

    def _fetch_device_info(self, device: Device) -> None:
        """Fill model/firmware from ``deviceInfo``; failures must not break refresh."""
        try:
            detail = self.get_device_info(device.iot_id)
        except BullCloudError:
            # 标记已尝试（真值），避免每轮刷新都重试同一台失败设备
            device.detail = {"_unavailable": True}
            return
        device.detail = detail
        device.product_name = detail.get("productName", "") or device.product_name
        device.model_name = detail.get("modelName", "") or device.model_name
        device.firmware_version = (
            detail.get("firmwareVersion", "") or device.firmware_version
        )

    # 兼容旧引用的静态方法入口
    _flatten_properties = staticmethod(flatten_properties)

    # ------------------------------------------------------------------ #
    # 控制
    # ------------------------------------------------------------------ #
    def set_property(self, iot_id: str, identifier: str, value) -> None:
        """设置单个属性，如 PowerSwitch=1 开 / 0 关。"""
        self.set_properties(iot_id, {identifier: value})

    def set_properties(self, iot_id: str, properties: dict) -> None:
        """一次请求批量设置多个属性。"""
        body = json.dumps(
            [{"value": v, "identifier": k} for k, v in properties.items()],
            separators=(",", ":"),
        )
        self._request_with_auth_recovery(
            "PUT",
            f"/mos/v1/dc/setDeviceProperty/{iot_id}",
            content_type="application/json",
            body=body,
        )

    def invoke_thing_service(self, iot_id: str, identifier: str) -> None:
        """调用设备服务，如充电桩的 SheduleAuth（激活充电）。"""
        self._request_with_auth_recovery(
            "PUT",
            f"/mos/iot/v1/devices/{iot_id}/invokeThingService",
            content_type="application/json",
            body=json.dumps({"identifier": identifier}, separators=(",", ":")),
        )

    def confirm_ble_random(self, pid: int, device_name: str) -> str:
        """Get the cloud challenge used to authenticate a local BLE session."""
        body = json.dumps({"pid": str(pid), "dn": device_name}, separators=(",", ":"))
        res = self._request_with_auth_recovery(
            "POST", "/mos/ble/v1/confirmRandom", body=body
        )
        result = res.get("result")
        value = result.get("random") if isinstance(result, dict) else result
        if not isinstance(value, str) or len(value.encode()) != 16:
            raise BullCloudError(
                "BLE confirmRandom", message="云端未返回 16 字节随机数"
            )
        return value

    def confirm_ble_device(
        self, random_value: str, pid: int, device_name: str, cipher: bytes
    ) -> str:
        """Exchange the device proof for a local BLE session key."""
        body = json.dumps(
            {
                "random": random_value,
                "pid": str(pid),
                "dn": device_name,
                "cipher": cipher.hex().upper(),
            },
            separators=(",", ":"),
        )
        res = self._request_with_auth_recovery(
            "POST", "/mos/ble/v1/confirmDevice", body=body
        )
        result = res.get("result")
        key = result.get("bleKey") if isinstance(result, dict) else result
        if not isinstance(key, str) or len(key) != 32:
            raise BullCloudError("BLE confirmDevice", message="云端未返回 16 字节密钥")
        try:
            bytes.fromhex(key)
        except ValueError as err:
            raise BullCloudError(
                "BLE confirmDevice", message="云端密钥格式错误"
            ) from err
        return key

    def close(self) -> None:
        with self._sessions_lock:
            sessions, self._sessions = self._sessions, []
        for session in sessions:
            try:
                session.close()
            except Exception:  # noqa: BLE001 - 关闭失败不影响退出
                pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
