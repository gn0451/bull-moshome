# 公牛智家云（MosHome）完整使用指南

> 本指南覆盖三种使用方式：**Home Assistant 集成**（推荐，适合绝大多数人）、
> **Python 客户端**（适合开发者）、**命令行工具**（适合快速调试）。
> 协议细节见 [PROTOCOL.md](PROTOCOL.md)，安装包见 [homeassistant/](homeassistant/)。

## 目录

1. [这是什么](#1-这是什么)
2. [方式一：Home Assistant 集成](#2-方式一home-assistant-集成推荐)
3. [方式二：Python 客户端](#3-方式二python-客户端)
4. [方式三：命令行工具](#4-方式三命令行工具)
5. [协议要点速览](#5-协议要点速览)
6. [常见问题](#6-常见问题)
7. [安全与隐私](#7-安全与隐私)

---

## 1. 这是什么

本项目围绕公牛智家云（`api.iotbull.com`，App 名"公牛智家"/MosHome）提供：

- 完整的 HTTP 客户端（登录、家庭/设备列表、属性控制、服务调用）
- MQTT 实时状态通道（设备被物理操作后云端秒级回推）
- Home Assistant 自定义集成（开关、灯、窗帘、传感器、选择器、数值与按钮）
- 经 MosHome 5.3.1、线上网关和真实设备验证的签名、加密与设备控制能力

**支持设备**（实测出现过的标识符）：G27/G55 系列开关（多通道）、智能插座、
WiFi 转换器、无线开关/传感器（电池供电）、灯、窗帘和充电桩等。HA 只为
经过验证的 PID 与能力创建控制实体，未知设备保持连通性或只读状态。

---

## 2. 方式一：Home Assistant 集成（推荐）

### 2.1 安装

```bash
# 在 Home Assistant 配置目录下（含 configuration.yaml 的目录）
unzip bull_iot-ha-1.2.0.zip        # 得到 custom_components/bull_iot/
```

没有 zip 也可以直接从本仓库复制：

```bash
cp -r homeassistant/custom_components/bull_iot <HA配置目录>/custom_components/
```

然后 **重启 Home Assistant**（设置 → 系统 → 重启）。

### 2.2 添加集成

设置 → 设备与服务 → **添加集成** → 搜索 `Bull MosHome` → 输入账号密码：

- 用户名：手机号（账号）
- 密码：App 内设置的登录密码

> 如果账号只用手机验证码登录过 App，需先在 App 内（我的 → 设置 → 账号与安全）
> 设置一个密码，本集成只支持账号密码登录。

### 2.3 你会得到什么

| 实体类型 | 示例 | 用途 |
|---------|------|------|
| `switch` × N | `switch.进门射灯`、`switch.客厅吊灯` | 每路通道一个开关，名称取 App 昵称 |
| `sensor` | `sensor.xxx_实时功率`、`sensor.xxx_累计用电量` | 功率/电压/电流/电量/电量百分比等 |
| `binary_sensor` | `binary_sensor.xxx_在线状态` | 设备在线/离线 |

命名规则：实体名前缀是设备昵称（App 里设置的名字），后缀是通道名或指标名。

### 2.4 自动化示例

**人体传感器联动射灯**（人来灯开，3 分钟无人关）：

```yaml
automation:
  - alias: "玄关人来灯亮"
    trigger:
      - platform: state
        entity_id: binary_sensor.玄关_人体传感器_occupancy   # 你的人体传感器实体
        to: "on"
    action:
      - service: switch.turn_on
        target:
          entity_id: switch.进门射灯

  - alias: "玄关人走灯灭"
    trigger:
      - platform: state
        entity_id: binary_sensor.玄关_人体传感器_occupancy
        to: "off"
        for: "00:03:00"
    action:
      - service: switch.turn_off
        target:
          entity_id: switch.进门射灯
```

**插座每日用电统计**（配合 HA 的效用 helper 或模板传感器）：

```yaml
template:
  - sensor:
      - name: "插座今日用电"
        unique_id: outlet_today_energy
        unit_of_measurement: "kWh"
        device_class: energy
        state: >
          {{ states('sensor.公牛插座_累计用电量') | float(0) }}
```

**设备离线通知**：

```yaml
automation:
  - alias: "公牛设备离线提醒"
    trigger:
      - platform: state
        entity_id: binary_sensor.客厅吊灯_在线状态
        to: "off"
        for: "00:10:00"
    action:
      - service: notify.persistent_notification
        data:
          message: "设备「客厅吊灯」已离线超过 10 分钟"
```

### 2.5 选项与维护

- **轮询间隔**：集成条目 → 齿轮 → 选项，15–3600 秒可调（默认 60）。
  MQTT 在线时状态是实时的，轮询只是兜底，可以调大。
- **MQTT 实时推送**：默认开启；关闭后仅靠轮询（延迟最高等于轮询间隔）。
- **凭证失效**：密码修改或 token 彻底失效时，HA 会自动弹出"重新验证"对话框，
  输入新密码即可，**不需要删除集成重加**，实体和自动化都不受影响。

---

## 3. 方式二：Python 客户端

### 3.1 安装

```bash
pip install requests cryptography paho-mqtt
git clone <本仓库> && cd bull-moshome   # 或直接把 bull_iot/ 目录拷进你的项目
```

### 3.2 快速开始

```python
from bull_iot import BullCloudClient

with BullCloudClient() as client:
    client.login("你的账号", "你的密码")

    devices = client.list_devices()
    for d in devices:
        print(d.iot_id, d.name, d.room)
        print("  ", d.describe())

    # 打开设备第一路开关
    client.set_property(devices[0].iot_id, "PowerSwitch", 1)
    # 关闭
    client.set_property(devices[0].iot_id, "PowerSwitch", 0)
```

### 3.3 核心 API

| 方法 | 说明 |
|------|------|
| `login(username, password)` | 账号密码登录，获取 token |
| `refresh_access_token()` | 刷新 token（失效时内部会自动重登） |
| `list_devices(family_ids=None)` | 遍历所有家庭，返回 `Device` 列表 |
| `refresh_devices(devices, family_ids=None)` | 增量刷新进已有缓存（定时任务用） |
| `get_families()` / `switch_family(id)` | 家庭列表 / 切换家庭 |
| `get_device_info(iot_id)` | 单设备详情（型号、固件） |
| `set_property(iot_id, identifier, value)` | 设置单个属性 |
| `set_properties(iot_id, {...})` | 批量设置 |
| `invoke_thing_service(iot_id, identifier)` | 调用设备服务（如充电桩 `SheduleAuth`） |

### 3.4 定时巡检示例

```python
import time
from bull_iot import BullCloudClient

client = BullCloudClient()
client.login("账号", "密码")
devices = {}

while True:
    devices = client.refresh_devices(devices)   # 增量：新设备才拉详情
    for d in devices.values():
        if d.status != "ONLINE":
            print(f"设备离线: {d.name}")
    time.sleep(300)
```

---

## 4. 方式三：命令行工具

凭证优先级：`--user/--password` 参数 > 环境变量 `BULL_USERNAME`/`BULL_PASSWORD`
> 交互输入。

```bash
# 不登录验证签名实现（假凭证探活，无需账号）
python -m bull_iot.cli probe

# 列出全部设备及属性
python -m bull_iot.cli devices

# 控制单个属性
python -m bull_iot.cli set --iot-id <iotId> --identifier PowerSwitch_1 --value 0

# MQTT 实时监听 60 秒（期间按物理开关，观察状态回推）
python -m bull_iot.cli watch --seconds 60
```

---

## 5. 协议要点速览

完整推导过程见 [PROTOCOL.md](PROTOCOL.md)，这里只列结论：

| 环节 | 结论 |
|------|------|
| 请求签名 | 阿里云 API 网关风格 `x-ca-*` HMAC-SHA256；表单请求的签名 query 用**表单字段本身**（网关从 body 重建），不算 Content-MD5 |
| 登录加密 | 用户名 AES-128-CBC（随机 IV + 大写 Hex）；密码 `sha256(sha256(pwd)+sha256("GONGNIU"))` |
| 登录请求 | `x-www-form-urlencoded` + 头部 `Login_parameter: APP_PWD`（大小写敏感） |
| 设备列表 | `GET /mos/home/v3/rooms` 返回拍平的设备列表；主条目（`deviceEntity=true`）带昵称，功能实体带通道名 |
| 属性控制 | `PUT /mos/v1/dc/setDeviceProperty/{iotId}`，body 为 `[{"identifier":..., "value":...}]` |
| MQTT | `emqx-prod.iotbull.com:1883`，username=openid、password=access_token、clientId=`IOS@2.9.1@<openid>`；连接后发布绑定报文，之后接收 `thing.properties` / `thing.status` 推送 |

---

## 6. 常见问题

**Q: 只有验证码登录过 App，没有密码？**
A: 在 App 内 我的 → 设置 → 账号与安全 → 设置密码，然后用账号密码登录。

**Q: 为什么开关名字是"进门射灯"这种？**
A: 直接取你在公牛智家 App 里给该通道设置的昵称。在 App 里改名，HA 侧下次刷新同步。

**Q: 设备出现了两次/控制的是旧状态？**
A: 云端设备会跨家庭共享，客户端已按 iotId 去重。若状态异常，检查集成选项里
MQTT 是否开启、轮询间隔是否过大。

**Q: 家庭很多，有些设备看不到？**
A: 云端家庭列表接口硬上限 50 条且不支持分页/搜索，只能覆盖最近访问的 50 个家庭。
这是云端限制，非本客户端问题。

**Q: 提示重新验证（reauth）？**
A: 改了密码或 token 失效。按弹窗输入新密码即可，实体不用重建。

**Q: 支持充电桩/电量统计吗？**
A: 充电桩走 `invoke_thing_service`（如 `SheduleAuth` 激活充电）；带计量功能的
设备会暴露实时功率/累计电量传感器。

---

## 7. 安全与隐私

- 账号密码**只存两处**：你自己机器上的 `.env`（客户端用，已默认 gitignore），
  或 Home Assistant 的 `.storage` 配置条目（集成用，删除集成即清除）。
- 本仓库**不包含、也不上传**任何真实凭证；代码中的示例手机号均为虚构测试号。
- 所有网络通信仅与公牛官方云端点（`api.iotbull.com` / `emqx-prod.iotbull.com`）发生。
- 通过云端控制大功率设备（充电桩、加热器等）有安全风险，请谨慎配置自动化，
  避免"无人值守时自动开启大功率负载"。

---

## 联系方式

技术交流 / 问题反馈欢迎加微信（加好友请注明 **BULL**）：

![WeChat QR](docs/wechat-qr.png)

也可以直接在 GitHub 仓库提 Issue。

---

*本项目仅用于个人设备接入与学习研究。使用本代码产生的一切后果由使用者自行承担。*
