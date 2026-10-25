<p align="center">
  <img src="brand/icon@2x.png" alt="MosHome" width="160">
</p>

# bull-moshome — 公牛智家云 Python 客户端 + Home Assistant 集成

面向公牛智家云（MosHome / `api.iotbull.com`）的 Python 客户端、Home Assistant
集成与协议文档。核心签名最初依据 MosHome 5.1.13 分析并经线上 API 校准，
随后使用 MosHome 5.3.1 和真实设备完成兼容验收。详细证据边界见
[PROVENANCE.md](PROVENANCE.md)。

协议细节见 [PROTOCOL.md](PROTOCOL.md)（含协议分析过程、签名算法、全部端点）。
设备支持等级和未知设备贡献流程见 [COMPATIBILITY.md](COMPATIBILITY.md)，版本变化见
[CHANGELOG.md](CHANGELOG.md)。

> 本项目是非官方社区项目，与公牛集团及 MosHome 官方无隶属或背书关系。
> MosHome 名称与标识归其权利人所有。

> **完整使用指南**（HA 集成安装、自动化示例、Python/CLI 用法、FAQ）见 [GUIDE.md](GUIDE.md)。

## 功能

- 账号密码登录（AES 加密用户名 + 双 SHA256 密码派生 + x-ca-* HMAC 签名）
- 自动 access_token 刷新与失效重试
- 家庭 / 房间 / 设备列表（含属性快照、型号、固件版本）
- 设备控制（`set_property` / `set_properties` / `invoke_thing_service`）
- MQTT 实时监听设备状态回推（物理按键操作后云端推送）
- Home Assistant 配置时选择家庭，避免遍历账号下全部家庭
- 能力优先发现：已有产品档案默认启用，未知负载型开关默认禁用等待用户确认
- 风险分级：电池情景面板与明确只读产品不会生成负载控制实体
- 匿名诊断导出：只包含协议标识符与支持等级，不包含设备 ID、昵称和属性值
- PID 296 数显桌面充电站：总电源、六路 USB、熄屏、功率模式、亮度与逐口遥测
- 充电桩：普通云属性、PID 193/195 Thing Service、PID 258 激活按钮和 PID 309 本地 BLE

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
custom_components/bull/     # HACS/HA 自定义集成
  device_profiles.json          # 版本化设备能力与实测证据登记
homeassistant/
  INSTALL_HA.md                 # 安装说明
  tests/test_e2e.py             # 集成端到端 mock 测试
PROTOCOL.md        # 协议分析文档
PROVENANCE.md      # 来源、验证和许可证边界
```

## Home Assistant 集成

仓库根目录的 `custom_components/bull/` 是标准 HACS 自定义集成。
它沿用既有 `bull` 域名、配置字段兼容层及实体唯一 ID，可从现有 Bull IoT
安装原位升级，保留实体 ID、自动化和外部白名单。

### HACS 安装

1. HACS → 集成 → 右上角菜单 → 自定义存储库。
2. 添加 `https://github.com/gn0451/bull-moshome`，类型选择“集成”。
3. 下载 **Bull MosHome**，重启 Home Assistant 后添加集成。

也可以手动复制：

```bash
cp -R custom_components/bull /path/to/ha/config/custom_components/
```

详见 [homeassistant/INSTALL_HA.md](homeassistant/INSTALL_HA.md)。
集成端到端测试覆盖 config flow、家庭筛选、coordinator、八个平台、PID
只读保护、充电专用功能、BLE 协议基础与 MQTT 回推：

```bash
uv run --python 3.13 --with pytest --with homeassistant \
  python homeassistant/tests/test_e2e.py
```

## 实测状态（2026-10-25）

- 登录 / 家庭 / 设备 / 控制四类端点的**签名与加密均已对线上网关验证通过**
  （假凭证返回业务错误码而非签名错误，见 PROTOCOL.md 第 11.1 节）
- **真实账号全链路已实测**：登录成功、448 台唯一设备完整拉取、MQTT 绑定应答 code=200、
  **真实设备控制指令已下发并验证**（setDeviceProperty 关闭 G27 开关通道，云端接受且回读一致）
  （见 PROTOCOL.md 第 11.2 节）
- MQTT 属性回推需设备状态变化时触发（监听窗口内无物理操作则只看到绑定应答）

## 联系方式

技术交流 / 问题反馈欢迎加微信（加好友请注明 **BULL**）：

![WeChat QR](docs/wechat-qr.png)

也可以直接在 GitHub 仓库提 [Issue](../../issues)。

## License

MIT，见 [LICENSE](LICENSE)。

## 免责声明

本项目是非官方社区项目，与公牛集团及 MosHome 官方无隶属或背书关系；MosHome
名称与标识归其权利人所有。本项目仅用于个人设备接入与学习研究。通过云端接口控制大功率设备（如充电桩、
加热器）存在安全风险，请谨慎设置自动化。使用本代码产生的一切后果由使用者自行承担。
