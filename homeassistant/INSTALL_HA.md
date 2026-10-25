# 公牛智家（MosHome）Home Assistant 自定义集成 — 安装说明

> 核心协议最初依据 MosHome 5.1.13 分析并通过线上 API 校准，随后使用
> MosHome 5.3.1 和真实设备完成兼容验收。详见 `../PROTOCOL.md` 与
> `../PROVENANCE.md`。

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
- **安全边界**：已有产品档案默认启用；未知但具有标准负载属性的开关生成默认禁用
  的实验实体。PID 3、20、21、69 及未知电池面板保持只读。
- **诊断导出**：HA 的“下载诊断”只输出 PID、型号、固件、属性名称和支持等级，
  不输出账号、设备 ID、昵称、房间或属性值。
- **原位升级**：沿用现有 `bull` 集成域名、配置条目、设备标识和实体唯一 ID，
  现有实体 ID、自动化及 OpenClaw 白名单无需重建。

## 二、安装

### HACS（推荐）

1. HACS → 集成 → 右上角菜单 → 自定义存储库。
2. 添加 `https://github.com/gn0451/bull-moshome`，类型选择“集成”。
3. 下载 **Bull MosHome** 并重启 Home Assistant。

### 手动安装

把仓库中的 `custom_components/bull` 复制到 HA 配置目录：

   ```bash
   cp -R custom_components/bull /path/to/ha/config/custom_components/
   ```

1. **重启 Home Assistant**（设置 → 系统 → 重启）。

2. 设置 → 设备与服务 → 添加集成 → 搜索 **Bull MosHome**。

3. 输入公牛智家账号密码：

   - 手机号即用户名（如 `13800138000`）
   - 密码为 App 内设置的登录密码（纯验证码登录的账号需先在 App 内设置密码）

4. 只选择需要接入这套 HA 的家庭。以后可在集成选项中调整。

5. 完成。设备会出现在“设备与服务”页面。

> **依赖安装**：集成 manifest 声明了 `requests` / `cryptography` / `paho-mqtt`，
> HA 首次加载时自动安装（需要 HA 能访问 PyPI）。
> HA Container/venv 安装方式同样支持；Core 安装方式需自行 `pip install` 这三个包。
> BLE 依赖由 HA 内置 `bluetooth` 集成提供。

## 三、选项配置

集成条目右侧"齿轮"→ 选项：

| 选项 | 默认 | 说明 |
|------|------|------|
| 接入家庭 | 安装时选择 | 可随时调整，无需删除集成 |
| 轮询间隔 | 300 秒 | 范围 15–3600；MQTT 为主要更新通道，轮询只做状态校准 |
| MQTT 实时推送 | 开 | 秒级状态回推；关闭后仅使用轮询 |

## 四、已知限制（来自云端实测）

1. **家庭列表上限 50 条**：`/v2/families` 接口硬上限 50 条且忽略一切分页参数、
   无搜索端点。账号下家庭超过 50 个时，只能覆盖最近访问的 50 个。
2. **设备跨家庭共享**：同一账号遍历所有家庭时设备记录会重复出现。HA 集成只刷新用户选中的家庭，并按 `iotId` 去重；命令行工具未指定家庭时仍保留遍历全部家庭的研究行为。
3. **多通道开关**：通道 1 通常对应 App 里的第一路（如"进门射灯"），
   实体名直接取 App 昵称，HA 侧改名不影响云端。

## 五、卸载

设置 → 设备与服务 → Bull IoT 条目 → 删除。会同时移除全部实体与保存的凭证
（密码仅存于 HA 的 `.storage` 配置条目，删除即清除）。

## 六、从现有 Bull IoT 原位升级

本集成沿用 `bull` 域名，并兼容旧配置条目的 `selected_families` 字段以及
`<iotId>.<identifier>` 实体唯一 ID。通过 HACS 覆盖升级后，原有配置、实体 ID、
自动化、HA-Fusion 页面和 OpenClaw 白名单应保持不变。

升级前仍应备份 `config/custom_components/bull` 和 HA `.storage`。升级后先核对实体
数量与可用性，再做一组低风险开关的开、关、状态回读测试；未通过前使用备份回滚。

## 七、文件结构

```
custom_components/bull/
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
├── diagnostics.py       # 匿名能力诊断导出
├── device_profiles.py   # 能力分级与安全推断
├── device_profiles.json # 设备兼容性证据登记
├── const.py             # 常量
├── manifest.json        # 依赖声明（requests/cryptography/paho-mqtt）
├── strings.json         # UI 文案
├── client.py            # 公牛智家云 HTTP 客户端
├── signing.py           # x-ca-* HMAC-SHA256 签名
├── crypto.py            # 登录字段加密（AES + 双 sha256）
└── mqtt_listener.py     # MQTT 实时状态监听
```

## 八、自检命令（可选，在 HA 主机上）

```bash
# 确认组件目录就位
ls config/custom_components/bull/manifest.json

# 确认依赖已装（HA venv 内）
source bin/activate 2>/dev/null || true
python -c "import requests, cryptography, paho.mqtt.client; print('deps ok')"

# 看集成日志
# 设置 → 系统 → 日志，过滤 bull
```
