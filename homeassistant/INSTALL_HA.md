# 公牛智家（MosHome）Home Assistant 自定义集成 — 安装说明

> 本集成基于对公牛智家云（api.iotbull.com）的**独立协议逆向**实现，
> 不依赖、不复用任何第三方插件代码。协议细节见 `../PROTOCOL.md`。

## 一、集成能力

| 平台 | 实体 | 说明 |
|------|------|------|
| `switch` | 每路开关通道一个实体 | 多通道设备（如 G27 三位开关）按 `PowerSwitch_1..N` 逐路暴露，通道名取 App 内昵称（如"进门射灯"）；单键设备（如智能插座）暴露 `PowerSwitch` 总开关 |
| `sensor` | 功率/电压/电流/电量等 | 覆盖 `RealTimePower`、`TotalConsumption`、`BatteryPercent`、`Voltage`(÷10) 等 11 类标识符，自动带单位与设备类别 |
| `binary_sensor` | 设备在线状态 | 云端 `ONLINE/OFFLINE` |

- **实时性**：默认同时启用 MQTT 长连接（`emqx-prod.iotbull.com`），设备被物理操作后秒级回推；轮询兜底（默认 60 秒，可在选项里调 15–3600 秒）。
- **凭证失效**：自动重登；彻底失效时 HA 弹出"重新验证"对话框，输一次密码即可，无需删集成重加。

## 二、安装（手动方式，适用于任意 HA 版本）

1. 把 `bull_iot-ha-1.0.0.zip` 传到 HA 主机，解压：

   ```bash
   cd /path/to/ha/config
   unzip bull_iot-ha-1.0.0.zip
   # 解压后得到 config/custom_components/bull_iot/ 目录
   ```

   或者手动复制：把整个 `bull_iot` 目录放到 HA 配置目录下的
   `custom_components/bull_iot/`（没有 `custom_components` 目录就新建）。

2. **重启 Home Assistant**（设置 → 系统 → 重启）。

3. 设置 → 设备与服务 → 添加集成 → 搜索 **Bull IoT**（或"公牛智家"）。

4. 输入公牛智家账号密码：

   - 手机号即用户名（如 `13800138000`）
   - 密码为 App 内设置的登录密码（纯验证码登录的账号需先在 App 内设置密码）

5. 完成。设备会出现在"设备与服务"页面，开关可直接用于自动化/场景/面板。

> **依赖安装**：集成 manifest 声明了 `requests` / `cryptography` / `paho-mqtt`，
> HA 首次加载时自动安装（需要 HA 能访问 PyPI）。
> HA Container/venv 安装方式同样支持；Core 安装方式需自行 `pip install` 这三个包。

## 三、选项配置

集成条目右侧"齿轮"→ 选项：

| 选项 | 默认 | 说明 |
|------|------|------|
| 轮询间隔 | 60 秒 | 范围 15–3600；MQTT 在线时可适当调大 |
| MQTT 实时推送 | 开 | 关闭后仅靠轮询更新状态 |

## 四、已知限制（来自逆向实测）

1. **家庭列表上限 50 条**：`/v2/families` 接口硬上限 50 条且忽略一切分页参数、
   无搜索端点。账号下家庭超过 50 个时，只能覆盖最近访问的 50 个。
2. **设备跨家庭共享**：同一账号遍历所有家庭时设备记录会重复出现
   （实测 1117 条记录 vs 448 台唯一设备），集成按 `iotId` 去重，每台设备只建一套实体。
3. **多通道开关**：通道 1 通常对应 App 里的第一路（如"进门射灯"），
   实体名直接取 App 昵称，HA 侧改名不影响云端。

## 五、卸载

设置 → 设备与服务 → Bull IoT 条目 → 删除。会同时移除全部实体与保存的凭证
（密码仅存于 HA 的 `.storage` 配置条目，删除即清除）。

## 六、与 hass-iotbull 的差异

| | 本集成 | hass-iotbull |
|---|---|---|
| 协议实现 | 从零独立逆向（`PROTOCOL.md` 有完整推导） | 社区早期逆向成果 |
| 分发方式 | 手动复制 zip | HACS |
| 实时通道 | MQTT 长连接 + 轮询 | 轮询为主 |
| 凭证失效处理 | 自动重登 + reauth 对话框 | 需手动重加 |

## 七、文件结构

```
custom_components/bull_iot/
├── __init__.py          # 集成入口：setup/unload/重载
├── config_flow.py       # UI 配置流 + 重新验证(reauth)
├── coordinator.py       # DataUpdateCoordinator：轮询/登录/MQTT 调度
├── switch.py            # 开关通道实体
├── sensor.py            # 电量类传感器实体
├── binary_sensor.py     # 在线状态实体
├── entity.py            # 实体基类（设备信息/唯一 ID）
├── const.py             # 常量
├── manifest.json        # 依赖声明（requests/cryptography/paho-mqtt）
├── strings.json         # UI 文案
├── client.py            # 公牛智家云 HTTP 客户端（独立逆向）
├── signing.py           # x-ca-* HMAC-SHA256 签名
├── crypto.py            # 登录字段加密（AES + 双 sha256）
└── mqtt_listener.py     # MQTT 实时状态监听
```

## 八、自检命令（可选，在 HA 主机上）

```bash
# 确认组件目录就位
ls config/custom_components/bull_iot/manifest.json

# 确认依赖已装（HA venv 内）
source bin/activate 2>/dev/null || true
python -c "import requests, cryptography, paho.mqtt.client; print('deps ok')"

# 看集成日志
# 设置 → 系统 → 日志，过滤 bull_iot
```
