"""MQTT 实时状态监听（设备物理操作后云端状态回推）。

协议要点（实测结论）：
- Broker: emqx-prod.iotbull.com
    - 8084/mqtt  MQTT over WebSocket + TLS（证书 *.iotbull.com，GlobalSign 签发）
    - 1883      明文 TCP（官方 App 使用的通道）
- 默认优先走 WSS，连接失败时自动回退到 1883 并在日志里说明
- 用户名 = openid，密码 = access_token
- clientId = "IOS@2.9.1@" + openid
- 连接后订阅 /sys/app/down/account/bind_reply，并向
  /sys/app/up/account/bind 发布绑定报文完成账号绑定
- 绑定后云端把设备消息推给客户端：
    method=thing.properties -> params.items.{identifier}.value 属性变化
    method=thing.status    -> params.status.value 在线状态(ONLINE/OFFLINE/1/3)
"""

import json
import logging
import threading

import paho.mqtt.client as mqtt

_LOGGER = logging.getLogger(__name__)

BIND_REPLY_TOPIC = "/sys/app/down/account/bind_reply"
BIND_TOPIC = "/sys/app/up/account/bind"
BROKER_HOST = "emqx-prod.iotbull.com"
BROKER_PORT = 1883          # 明文 TCP
WSS_PORT = 8084             # MQTT over WebSocket + TLS
WSS_PATH = "/mqtt"
CONNACK_TIMEOUT = 6.0       # 秒：等 CONNACK 的上限，超时即判定该通道不可用


def _new_client(client_id: str, secure: bool = False):
    """创建 paho 客户端，兼容 paho-mqtt 1.6 与 2.x。

    ``secure=True`` 时使用 WebSocket 传输。paho 1.6 的 ws 传输需要额外的
    ``websocket-client``，缺失时会抛 ImportError —— 此时返回 None，
    由调用方回退到明文 TCP，避免把新依赖强加给已有用户。
    """
    transport = "websockets" if secure else "tcp"
    try:
        try:
            client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION1,
                client_id=client_id,
                transport=transport,
            )
        except (AttributeError, TypeError):
            client = mqtt.Client(client_id=client_id, transport=transport)
    except (ImportError, ValueError, OSError):
        return None

    if secure:
        client.tls_set()
        client.ws_set_options(path=WSS_PATH)
    return client


class BullMqttListener:
    """后台线程监听设备状态变化。

    :param openid: 登录后获得的 openid
    :param access_token: 登录后获得的 access_token
    :param on_property: 属性变化回调 fn(iot_id, identifier, value)
    :param on_status: 在线状态变化回调 fn(iot_id, status_value)
    :param wildcard: 是否额外订阅 "#" 用于话题发现（研究用途）
    """

    def __init__(
        self,
        openid: str,
        access_token: str,
        on_property=None,
        on_status=None,
        wildcard: bool = False,
        prefer_tls: bool = True,
    ):
        self.openid = openid
        self.access_token = access_token
        self.on_property = on_property
        self.on_status = on_status
        self.wildcard = wildcard
        self.prefer_tls = prefer_tls
        self.bound = threading.Event()
        self.secure = False          # 实际生效的通道是否为 TLS
        self.connack_rc = None       # 最近一次 CONNACK 返回码
        self._client = None
        self._connected = threading.Event()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    def start(self) -> None:
        """优先建立 WSS 连接，失败时回退到明文 TCP。"""
        if self.prefer_tls:
            if self._connect(secure=True):
                return
            _LOGGER.warning(
                "MQTT over TLS 不可用，回退到明文 1883（token 将明文传输）"
            )
        self._connect(secure=False)

    def _connect(self, secure: bool) -> bool:
        """建立一条连接并等待 CONNACK。返回 True 表示拿到了 CONNACK。"""
        with self._lock:
            client = _new_client(f"IOS@2.9.1@{self.openid}", secure=secure)
            if client is None:
                _LOGGER.debug("当前 paho 版本不支持 WebSocket 传输")
                return False

            self._connected.clear()
            self.connack_rc = None
            client.on_connect = self._on_connect
            client.on_message = self._on_message
            client.username_pw_set(self.openid, self.access_token)
            client.reconnect_delay_set(min_delay=15, max_delay=120)
            self._client = client
            self.secure = secure

            port = WSS_PORT if secure else BROKER_PORT
            try:
                client.connect_async(BROKER_HOST, port=port)
                client.loop_start()
            except Exception:  # noqa: BLE001 - 任何建连异常都视为该通道不可用
                _LOGGER.debug("MQTT 建连异常（secure=%s）", secure, exc_info=True)
                self._client = None
                return False

        got_connack = self._connected.wait(CONNACK_TIMEOUT)
        if not got_connack:
            _LOGGER.debug("MQTT 通道 %s 在 %.0fs 内未收到 CONNACK", port, CONNACK_TIMEOUT)
            try:
                client.loop_stop()
            except Exception:  # noqa: BLE001
                _LOGGER.debug("停止未连通的 MQTT 循环失败", exc_info=True)
            with self._lock:
                if self._client is client:
                    self._client = None
        return got_connack

    def stop(self) -> None:
        with self._lock:
            client = self._client
            self._client = None
        if client is None:
            return
        # 先 disconnect 再停网络循环，确保断开报文能发出
        try:
            client.disconnect()
        except RuntimeError:  # 未连接时 disconnect 会抛异常
            _LOGGER.debug("MQTT disconnect ignored because the client is not connected")
        try:
            client.loop_stop()
        except Exception:  # noqa: BLE001
            _LOGGER.debug("MQTT loop_stop 失败", exc_info=True)

    # ------------------------------------------------------------------ #
    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        rc = getattr(reason_code, "value", reason_code)
        self.connack_rc = rc
        self._connected.set()
        if rc != mqtt.MQTT_ERR_SUCCESS:
            _LOGGER.warning("MQTT 连接失败: %s", rc)
            return
        _LOGGER.debug(
            "MQTT 已连接 %s:%s（%s）",
            BROKER_HOST,
            WSS_PORT if self.secure else BROKER_PORT,
            "WSS" if self.secure else "TCP",
        )
        client.subscribe(BIND_REPLY_TOPIC, qos=0)
        if self.wildcard:
            client.subscribe("#", qos=0)
        # 完成账号绑定
        payload = {
            "id": "msg_id_bind_85",
            "params": {"token": self.access_token},
            "request": {"clientId": f"IOS@2.9.1@{self.openid}", "userId": self.openid},
            "version": "1.0",
        }
        client.publish(BIND_TOPIC, json.dumps(payload))

    def _on_message(self, client, userdata, msg):
        try:
            self._dispatch(client, userdata, msg)
        except Exception:  # 回调异常不能杀掉 paho 网络线程
            _LOGGER.exception("处理 MQTT 报文失败: topic=%s", msg.topic)

    def _dispatch(self, client, userdata, msg):
        try:
            db = json.loads(msg.payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            _LOGGER.debug("MQTT %s <- 非 JSON 报文，已忽略", msg.topic)
            return

        if msg.topic.endswith("/account/bind_reply"):
            code = db.get("code")
            if str(code) != "200":
                # A failed bind means no push updates at all; without this the
                # integration would silently fall back to polling forever.
                _LOGGER.warning(
                    "MQTT 账号绑定失败: code=%s message=%s（实时推送不可用，将依赖轮询）",
                    code,
                    db.get("message"),
                )
                return
            _LOGGER.debug("MQTT 账号绑定成功: code=%s", code)
            self.bound.set()
            return

        if self.wildcard and not db.get("method"):
            # 话题发现模式：原样记录非业务报文
            _LOGGER.debug(
                "MQTT %s <- %s", msg.topic, json.dumps(db, ensure_ascii=False)[:300]
            )
            return

        params = db.get("params") or {}
        iot_id = params.get("iotId")
        if not iot_id:
            return

        if db.get("method") == "thing.properties":
            for identifier, item in (params.get("items") or {}).items():
                value = item.get("value") if isinstance(item, dict) else item
                _LOGGER.debug("MQTT 属性 %s %s = %s", iot_id, identifier, value)
                if self.on_property:
                    self.on_property(iot_id, identifier, value)
        elif db.get("method") == "thing.status":
            status = (params.get("status") or {}).get("value")
            _LOGGER.debug("MQTT 状态 %s -> %s", iot_id, status)
            if self.on_status:
                self.on_status(iot_id, status)
