"""公牛智家云（MosHome / api.iotbull.com）Python 客户端。

协议与设备能力依据 MosHome 5.3.1、云端 API 和真实设备验证结果实现。
仅使用公牛账号体系内的开放云接口，用于个人设备的接入与自动化。
"""

import json
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
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.openid: str | None = None
        self.username: str | None = None
        self.password: str | None = None
        self._families: list[dict] = []

    # ------------------------------------------------------------------ #
    # 基础请求
    # ------------------------------------------------------------------ #
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
        """发送一个带 CloudAPI 签名的请求，返回解析后的 JSON。"""
        headers = build_headers(method, path, content_type, body, query)
        if extra_headers:
            headers.update(extra_headers)
        if bearer and self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"

        resp = self.session.request(
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
        for family_id in family_ids:
            self.switch_family(family_id)
            for info in self.get_rooms_and_devices():
                seen_iot_ids.add(info["iotId"])
                self._parse_device(devices, info)

        for iot_id in set(devices) - seen_iot_ids:
            devices.pop(iot_id, None)
        return devices

    def _parse_device(self, devices: dict[str, Device], info: dict) -> None:
        """解析一条设备记录；deviceEntity=true 的是主设备条目，其余是功能实体。"""
        iot_id = info["iotId"]
        product_id = info["product"]["globalProductId"]

        if iot_id not in devices:
            device = Device(iot_id=iot_id, product_id=product_id, raw=info)
            device.status = info.get("status", "")
            device.room = info.get("roomName", "")
            for prop in info.get("property", {}).values():
                flatten_properties(device.properties, prop["identifier"], prop["value"])
            try:
                detail = self.get_device_info(iot_id)
                device.product_name = detail.get("productName", "")
                device.model_name = detail.get("modelName", "")
                device.firmware_version = detail.get("firmwareVersion", "")
            except BullCloudError:
                pass
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

    def close(self) -> None:
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
