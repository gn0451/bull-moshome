# bull-iot-reverse — 公牛智家云独立客户端

对公牛智家云（MosHome / `api.iotbull.com`）协议**独立逆向**后实现的 Python 客户端
与协议文档。不依赖 hass-iotbull 或任何第三方集成代码，仅依赖 `requests`、
`cryptography`、`paho-mqtt`。

协议细节见 [PROTOCOL.md](PROTOCOL.md)（含逆向方法论、签名算法、全部端点）。

## 功能

- 账号密码登录（AES 加密用户名 + 双 SHA256 密码派生 + x-ca-* HMAC 签名）
- 自动 access_token 刷新与失效重试
- 家庭 / 房间 / 设备列表（含属性快照、型号、固件版本）
- 设备控制（`set_property` / `set_properties` / `invoke_thing_service`）
- MQTT 实时监听设备状态回推（物理按键操作后云端推送）

## 安装

```bash
pip install requests cryptography paho-mqtt
```

## 快速开始

```python
from bull_iot import BullCloudClient

with BullCloudClient() as client:
    client.login("你的账号", "你的密码")

    devices = client.list_devices()
    for d in devices:
        print(d.iot_id, d.name, d.properties)

    # 打开第一个开关通道
    client.set_property(devices[0].iot_id, "PowerSwitch", 1)
```

> 账号提示：如果用手机验证码登录的公牛智家 App，需要先在 App 内为账号设置密码，
> 本客户端只支持账号密码登录。

## 命令行

凭证优先级：`--user/--password` 参数 > 环境变量 `BULL_USERNAME`/`BULL_PASSWORD` > 交互输入。

```bash
# 不登录，验证签名实现是否被云端网关接受（假凭证探活）
python -m bull_iot.cli probe

# 列出所有设备及属性
python -m bull_iot.cli devices

# 控制：开 / 关
python -m bull_iot.cli set --iot-id <iotId> --identifier PowerSwitch --value 1
python -m bull_iot.cli set --iot-id <iotId> --identifier PowerSwitch --value 0

# MQTT 实时监听 60 秒（期间按设备物理开关，可看到状态回推）
python -m bull_iot.cli watch --seconds 60

# 话题发现模式（订阅 #，观察云端推送的原始 topic）
python -m bull_iot.cli watch --wildcard --seconds 30
```

## 项目结构

```
bull_iot/
  crypto.py        # 登录字段加密（AES-CBC 用户名 / 双 SHA256 密码）
  signing.py       # CloudAPI x-ca-* HMAC-SHA256 签名
  client.py        # HTTP 客户端：登录、设备、控制
  mqtt_listener.py # MQTT 实时状态监听
  cli.py           # 命令行入口
tests/             # 签名验证测试（假凭证探活，无需账号）
examples/          # 示例脚本
homeassistant/     # Home Assistant 自定义集成（bull_iot）
  custom_components/bull_iot/   # 自包含组件（含客户端四模块副本）
  INSTALL_HA.md                 # 安装说明
  bull_iot-ha-1.0.0.zip         # 一键安装包
  tests/test_e2e.py             # 集成端到端 mock 测试（需安装 homeassistant）
PROTOCOL.md        # 协议逆向文档
```

## Home Assistant 集成

`homeassistant/` 目录是本客户端对应的 **Home Assistant 自定义集成**，
不依赖 hass-iotbull，把设备接入 HA 的开关 / 传感器 / 在线状态实体：

```bash
# 解压即用（在 HA 配置目录下）
unzip homeassistant/bull_iot-ha-1.0.0.zip
# -> custom_components/bull_iot/，然后重启 HA，UI 搜索 "Bull IoT" 添加
```

详见 [homeassistant/INSTALL_HA.md](homeassistant/INSTALL_HA.md)。
集成端到端测试（mock，15 个用例覆盖 config flow / coordinator / 三平台 / MQTT 回推）：

```bash
pip install homeassistant==2024.3.3   # 或任意 >=2024.3 版本
python homeassistant/tests/test_e2e.py
```

## 实测状态（2026-10-25）

- 登录 / 家庭 / 设备 / 控制四类端点的**签名与加密均已对线上网关验证通过**
  （假凭证返回业务错误码而非签名错误，见 PROTOCOL.md 第 11.1 节）
- **真实账号全链路已实测**：登录成功、448 台唯一设备完整拉取、MQTT 绑定应答 code=200、
  **真实设备控制指令已下发并验证**（setDeviceProperty 关闭 G27 开关通道，云端接受且回读一致）
  （见 PROTOCOL.md 第 11.2 节）
- MQTT 属性回推需设备状态变化时触发（监听窗口内无物理操作则只看到绑定应答）

## 免责声明

本项目仅用于个人设备接入与学习研究。通过云端接口控制大功率设备（如充电桩、
加热器）存在安全风险，请谨慎设置自动化。使用本代码产生的一切后果由使用者自行承担。
