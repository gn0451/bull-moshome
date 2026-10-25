# 公牛智家（MosHome）Home Assistant 自定义集成 — 安装说明

> 本集成基于对公牛智家云（api.iotbull.com）的协议的**独立分析**实现，
> 不依赖、不复用任何第三方插件代码。协议细节见 `../PROTOCOL.md`。

## 一、集成能力

| 平台 | 实体 | 说明 |
|------|------|------|
| `switch` | 每路开关通道一个实体 | 多通道设备（如 G27 三位开关）按 `PowerSwitch_1..N` 逐路暴露，通道名取 App 内昵称（如"进门射灯"）；单键设备（如智能插座）暴露 `PowerSwitch` 总开关 |
| `light` | 开关、亮度、色温 | 仅为已验证的灯具 PID 创建实体，并校验属性协议指纹 |
| `cover` | 开、关、停止、位置 | 支持两种已验证的窗帘属性大小写协议 |
| `sensor` | 功率/电压/电流/电量等 | 覆盖 `RealTimePower`、`TotalConsumption`、`BatteryPercent`、`Voltage`(÷10) 等 11 类标识符，自动带单位与设备类别 |
| `binary_sensor` | 在线及安防状态 | 云端 `ONLINE/OFFLINE`，以及已验证的人体、门磁、防拆、燃气和漏水状态 |
| `select` | 功率模式、熄屏时间、时钟格式、BLE 充电模式 | PID 296 保留自定义模式只读显示；PID 309 写入后回读确认 |
| `number` | 屏幕亮度 | PID 296，范围 1–100；总电源关闭时不可操作 |
| `button` | 激活充电 | PID 258 仅在 `DeviceWorkState.WorkState=8` 时可用 |

- **实时性**：MQTT 长连接（`emqx-prod.iotbull.com`）启用后可秒级回推；轮询兜底默认 300 秒，可在选项里调 15–3600 秒。
- **充电桩控制**：PID 193/195 调用 App 同款 Thing Service；PID 309 只允许经认证的本地 BLE 控制，不会降级为未经确认的云属性写入。
- **BLE 前提**：PID 309 需要 HA 主机蓝牙或 ESPHome Bluetooth Proxy 可连接到充电桩；无可用路由时实体保持不可用。
- **凭证失效**：自动重登；彻底失效时 HA 弹出"重新验证"对话框，输一次密码即可，无需删集成重加。
- **安全边界**：只有已验证 PID 才创建控制实体。PID 3、20、21、69 只保留只读状态，不会因为存在 `PowerSwitch` 字段而被误建为负载开关。
- **并行验收**：首次安装默认关闭 MQTT，避免与现有 `bull` 集成使用相同账号时发生客户端连接冲突。候选版通过验收并准备替换旧版后，再在选项中启用。

## 二、安装（手动方式，适用于任意 HA 版本）

1. 把 `bull_iot-ha-1.2.0.zip` 传到 HA 主机，解压：

   ```bash
   cd /path/to/ha/config
   unzip bull_iot-ha-1.2.0.zip
   # 解压后得到 config/custom_components/bull_iot/ 目录
   ```

   或者手动复制：把整个 `bull_iot` 目录放到 HA 配置目录下的
   `custom_components/bull_iot/`（没有 `custom_components` 目录就新建）。

2. **重启 Home Assistant**（设置 → 系统 → 重启）。

3. 设置 → 设备与服务 → 添加集成 → 搜索 **Bull MosHome**。

4. 输入公牛智家账号密码：

   - 手机号即用户名（如 `13800138000`）
   - 密码为 App 内设置的登录密码（纯验证码登录的账号需先在 App 内设置密码）

5. 只选择需要接入这套 HA 的家庭。对于拥有大量共享家庭的账号，这一步会显著减少云端请求和无关设备。

6. 完成。设备会出现在"设备与服务"页面，开关可直接用于自动化/场景/面板。

> **依赖安装**：集成 manifest 声明了 `requests` / `cryptography` / `paho-mqtt`，
> HA 首次加载时自动安装（需要 HA 能访问 PyPI）。
> HA Container/venv 安装方式同样支持；Core 安装方式需自行 `pip install` 这三个包。
> BLE 依赖由 HA 内置 `bluetooth` 集成提供。

## 三、选项配置

集成条目右侧"齿轮"→ 选项：

| 选项 | 默认 | 说明 |
|------|------|------|
| 轮询间隔 | 300 秒 | 范围 15–3600；MQTT 为主要更新通道，轮询只做状态校准 |
| MQTT 实时推送 | 关 | 与旧集成并行时保持关闭；正式切换后启用 |

## 四、已知限制（来自云端实测）

1. **家庭列表上限 50 条**：`/v2/families` 接口硬上限 50 条且忽略一切分页参数、
   无搜索端点。账号下家庭超过 50 个时，只能覆盖最近访问的 50 个。
2. **设备跨家庭共享**：同一账号遍历所有家庭时设备记录会重复出现。HA 集成只刷新用户选中的家庭，并按 `iotId` 去重；独立 CLI 未指定家庭时仍保留遍历全部家庭的研究行为。
3. **多通道开关**：通道 1 通常对应 App 里的第一路（如"进门射灯"），
   实体名直接取 App 昵称，HA 侧改名不影响云端。

## 五、卸载

设置 → 设备与服务 → Bull IoT 条目 → 删除。会同时移除全部实体与保存的凭证
（密码仅存于 HA 的 `.storage` 配置条目，删除即清除）。

## 六、与现有生产集成的关系

`bull_iot` 保留独立协议客户端、CLI 和 reauth 设计，并吸收了现有生产环境中
已经验证的产品 PID 边界、家庭选择以及灯/窗帘/安防实体行为。它使用独立域名
`bull_iot`，不会覆盖已安装的 `bull` 集成，适合先做并行候选测试。

从 `bull` 切换时实体 ID 会变化，OpenClaw 白名单、HA-Fusion 页面和自动化必须
重新映射；未完成真实设备验收前不要直接替换生产集成。

## 七、文件结构

```
custom_components/bull_iot/
├── __init__.py          # 集成入口：setup/unload/重载
├── config_flow.py       # UI 配置流 + 重新验证(reauth)
├── coordinator.py       # DataUpdateCoordinator：轮询/登录/MQTT 调度
├── switch.py            # 开关通道实体
├── light.py             # 灯具实体
├── cover.py             # 窗帘实体
├── sensor.py            # 电量类传感器实体
├── binary_sensor.py     # 在线状态实体
├── select.py            # 数显插座与 BLE 充电模式
├── number.py            # 数显插座屏幕亮度
├── button.py            # 显式映射的 Thing Service 按钮
├── digital_display_socket.py # PID 296 属性兼容读取
├── cloud_charger.py     # PID 193/195 Thing Service 控制
├── ble.py               # FEB3 BLE 会话协议
├── ble_charger.py       # HA Bluetooth 持久连接与安全回读
├── entity.py            # 实体基类（设备信息/唯一 ID）
├── const.py             # 常量
├── manifest.json        # 依赖声明（requests/cryptography/paho-mqtt）
├── strings.json         # UI 文案
├── client.py            # 公牛智家云 HTTP 客户端（独立实现）
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
