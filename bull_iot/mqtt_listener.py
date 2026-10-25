"""MQTT 实时状态监听（设备物理操作后云端状态回推）。

协议要点（逆向结论）：
- Broker: emqx-prod.iotbull.com:1883（明文 TCP，无 TLS）
- 用户名 = openid，密码 = access_token
- clientId = "IOS@2.9.1@" + openid
- 连接后订阅 /sys/app/down/account/bind_reply，并向
  /sys/app/up/account/bind 发布绑定报文完成账号绑定
- 绑定后云端把设备消息推给客户端：
    method=thing.properties -> params.items.{identifier}.value 属性变化
    method=thing.status    -> params.status.value 在线状态(ONLINE/OFFLINE/1/3)
"""

import json
import threading

import paho.mqtt.client as mqtt

BIND_REPLY_TOPIC = "/sys/app/down/account/bind_reply"
BIND_TOPIC = "/sys/app/up/account/bind"


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
    ):
        self.openid = openid
        self.access_token = access_token
        self.on_property = on_property
        self.on_status = on_status
        self.wildcard = wildcard
        self.bound = threading.Event()
        self._client = mqtt.Client(client_id=f"IOS@2.9.1@{openid}")
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.username_pw_set(openid, access_token)
        self._client.reconnect_delay_set(min_delay=15, max_delay=120)

    # ------------------------------------------------------------------ #
    def start(self) -> None:
        self._client.connect_async("emqx-prod.iotbull.com", port=1883)
        self._client.loop_start()

    def stop(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()

    # ------------------------------------------------------------------ #
    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        rc = getattr(reason_code, "value", reason_code)
        print(f"[MQTT] 连接结果: {rc}")
        if rc != mqtt.MQTT_ERR_SUCCESS:
            return
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
            db = json.loads(msg.payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            print(f"[MQTT] {msg.topic} <- 非 JSON 报文，已忽略")
            return

        if msg.topic.endswith("/account/bind_reply"):
            print(f"[MQTT] 账号绑定应答: code={db.get('code')} message={db.get('message')}")
            self.bound.set()
            return

        if self.wildcard and not db.get("method"):
            # 话题发现模式：原样打印非业务报文
            print(f"[MQTT] {msg.topic} <- {json.dumps(db, ensure_ascii=False)[:300]}")
            return

        params = db.get("params") or {}
        iot_id = params.get("iotId")
        if not iot_id:
            return

        if db.get("method") == "thing.properties":
            for identifier, item in (params.get("items") or {}).items():
                value = item.get("value") if isinstance(item, dict) else item
                print(f"[MQTT] 属性 {iot_id} {identifier} = {value}")
                if self.on_property:
                    self.on_property(iot_id, identifier, value)
        elif db.get("method") == "thing.status":
            status = (params.get("status") or {}).get("value")
            print(f"[MQTT] 状态 {iot_id} -> {status}")
            if self.on_status:
                self.on_status(iot_id, status)
