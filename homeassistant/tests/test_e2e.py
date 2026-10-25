"""bull_iot HA 集成端到端 mock 测试。

不访问真实网络：mock BullCloudClient 的全部出网方法，验证
config flow（user/reauth/reauth_confirm）、coordinator（首刷/周期刷新/
MQTT 回推/属性应用）、三个平台实体的创建与控制路径。
"""

import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

# 组件目录 = <repo>/homeassistant/custom_components（相对本测试文件定位）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "custom_components"))

from homeassistant.exceptions import ConfigEntryAuthFailed  # noqa: E402
from homeassistant.helpers.update_coordinator import UpdateFailed  # noqa: E402

import bull_iot  # noqa: E402
import bull_iot.binary_sensor as bs_mod  # noqa: E402
import bull_iot.config_flow as cf_mod  # noqa: E402
import bull_iot.coordinator as coord_mod  # noqa: E402
import bull_iot.sensor as sensor_mod  # noqa: E402
import bull_iot.switch as switch_mod  # noqa: E402
from bull_iot.client import AuthenticationError, BullCloudError, Device  # noqa: E402
from bull_iot.const import DOMAIN  # noqa: E402

PASSED = []
FAILED = []


async def check(name, fn):
    try:
        await fn()
        PASSED.append(name)
        print(f"  PASS {name}")
    except Exception as err:  # noqa: BLE001
        FAILED.append((name, err))
        import traceback

        traceback.print_exc()
        print(f"  FAIL {name}: {type(err).__name__}: {err}")


# ---------------------------------------------------------------------- #
# Fake 基础设施
# ---------------------------------------------------------------------- #
class FakeHass:
    """最小 HomeAssistant 替身：只需 executor/loop/config_entries/data。"""

    def __init__(self):
        self.loop = asyncio.get_event_loop()
        self.data = {}
        self.config_entries = types.SimpleNamespace(
            async_update_entry=MagicMock(return_value=True),
            async_schedule_reload=MagicMock(),
            async_get_entry=MagicMock(return_value=None),
            async_entry_for_domain_unique_id=MagicMock(return_value=None),
            flow=MagicMock(),
        )

    async def async_add_executor_job(self, func, *args):
        return func(*args)


class FakeEntry:
    def __init__(self, data=None, options=None):
        self.data = data or {"username": "13800138000", "password": "secret"}
        self.options = options or {}
        self.entry_id = "test_entry_1"
        self.title = "13800138000"


def make_fake_device():
    """一台 G27 三位开关（模拟真实抓包结构）。"""
    dev = Device(
        iot_id="fake_iot_001",
        product_id=1234,
        name="进门射灯",
        room="客厅",
        status="ONLINE",
        product_name="G27 三位开关",
        model_name="G27-3",
        firmware_version="1.2.3",
    )
    dev.properties.update(
        {
            "PowerSwitch": 1,
            "PowerSwitch_1": 1,
            "PowerSwitch_2": 0,
            "PowerSwitch_3": 0,
            "__name__PowerSwitch_1": "进门射灯",
            "__name__PowerSwitch_2": "客厅吊灯",
            "RealTimePower": 12,
        }
    )
    return dev


def make_fake_client():
    client = MagicMock()
    client.access_token = "fake_token"
    client.refresh_token = "fake_refresh"
    client.openid = "fake_openid"
    return client


async def make_coordinator(hass, entry, device=None):
    """构造 coordinator、执行首刷、注册进 hass.data（模拟 __init__.py 的行为）。"""
    client = make_fake_client()
    if device is not None:
        client.refresh_devices.side_effect = lambda d, f=None: {**d, device.iot_id: device}
    with patch.object(coord_mod, "BullCloudClient", return_value=client):
        coordinator = coord_mod.BullCoordinator(hass, entry)
    await coordinator._async_update_data()
    # HA 的 _async_refresh 会赋值 data；平台 setup 从 coordinator.data 读设备
    coordinator.data = coordinator.devices
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    return coordinator


# ---------------------------------------------------------------------- #
# 测试用例
# ---------------------------------------------------------------------- #
async def test_config_flow_user_success():
    """user 步骤：凭证有效 -> 创建 entry。"""
    flow = cf_mod.BullConfigFlow()
    flow.hass = FakeHass()
    flow.handler = DOMAIN
    flow.flow_id = "flow1"
    flow.context = {"source": "user"}

    with patch.object(cf_mod, "_validate_credentials", new=lambda hass, u, p: asyncio.sleep(0)):
        result = await flow.async_step_user(
            {"username": "13800138000", "password": "secret"}
        )
    assert result["type"] == "create_entry", result
    assert result["data"]["username"] == "13800138000"


async def test_config_flow_user_bad_credentials():
    """user 步骤：凭证错误 -> invalid_auth 错误留在表单。"""

    async def bad_validate(hass, u, p):
        raise AuthenticationError("登录", 901006, "用户名或密码错误")

    flow = cf_mod.BullConfigFlow()
    flow.hass = FakeHass()
    flow.handler = DOMAIN
    flow.flow_id = "flow2"
    flow.context = {"source": "user"}

    with patch.object(cf_mod, "_validate_credentials", new=bad_validate):
        result = await flow.async_step_user({"username": "x", "password": "y"})
    assert result["type"] == "form", result
    assert result["errors"] == {"base": "invalid_auth"}, result


async def test_config_flow_user_cannot_connect():
    """user 步骤：网络异常 -> cannot_connect。"""

    async def boom(hass, u, p):
        raise cf_mod.CannotConnect()

    flow = cf_mod.BullConfigFlow()
    flow.hass = FakeHass()
    flow.handler = DOMAIN
    flow.flow_id = "flow3"
    flow.context = {"source": "user"}

    with patch.object(cf_mod, "_validate_credentials", new=boom):
        result = await flow.async_step_user({"username": "x", "password": "y"})
    assert result["type"] == "form"
    assert result["errors"] == {"base": "cannot_connect"}, result


async def test_config_flow_reauth_flow():
    """reauth 两步：reauth -> reauth_confirm -> 更新并 abort。"""
    hass = FakeHass()
    entry = FakeEntry()
    hass.config_entries.async_get_entry = MagicMock(return_value=entry)

    flow = cf_mod.BullConfigFlow()
    flow.hass = hass
    flow.handler = DOMAIN
    flow.flow_id = "flow4"
    flow.context = {"source": "reauth", "entry_id": entry.entry_id}

    async def ok_validate(hass_, u, p):
        return None

    with patch.object(cf_mod, "_validate_credentials", new=ok_validate):
        # 第一步：自动跳到 confirm 表单
        r1 = await flow.async_step_reauth({"username": "u", "password": "p"})
        assert r1["type"] == "form", r1
        assert r1["step_id"] == "reauth_confirm", r1
        # 第二步：提交新凭证 -> update + abort
        r2 = await flow.async_step_reauth_confirm(
            {"username": "new_user", "password": "new_pass"}
        )
    assert r2["type"] == "abort", r2
    assert r2["reason"] == "reauth_successful", r2
    hass.config_entries.async_update_entry.assert_called_once()
    call_kwargs = hass.config_entries.async_update_entry.call_args.kwargs
    assert call_kwargs["data"]["username"] == "new_user", call_kwargs


async def test_coordinator_first_refresh():
    """coordinator 首刷（已有 token）：直接拉设备，不重复登录。"""
    hass = FakeHass()
    entry = FakeEntry()
    device = make_fake_device()

    coordinator = await make_coordinator(hass, entry, device)
    data = coordinator.data
    assert device.iot_id in data
    assert coordinator.devices is data
    assert coordinator.client.login.call_count == 0  # token 有效，无需登录


async def test_coordinator_login_when_no_token():
    """coordinator 首刷（无 token）：先登录再拉设备。"""
    hass = FakeHass()
    entry = FakeEntry()
    device = make_fake_device()

    client = make_fake_client()
    client.access_token = None
    client.refresh_devices.side_effect = lambda d, f=None: {**d, device.iot_id: device}
    with patch.object(coord_mod, "BullCloudClient", return_value=client):
        coordinator = coord_mod.BullCoordinator(hass, entry)
    data = await coordinator._async_update_data()
    assert device.iot_id in data
    client.login.assert_called_once_with("13800138000", "secret")


async def test_coordinator_token_recovery():
    """首刷遇 9008 -> 自动重登后再拉设备。"""
    hass = FakeHass()
    entry = FakeEntry()
    client = make_fake_client()
    device = make_fake_device()

    def refresh_devices(devices, family_ids=None):
        devices[device.iot_id] = device
        return devices

    def flaky_refresh(devices, family_ids=None):
        if not client.login.called:
            raise BullCloudError("refresh", code=9008, message="token 失效")
        return refresh_devices(devices, family_ids)

    client.refresh_devices.side_effect = flaky_refresh

    with patch.object(coord_mod, "BullCloudClient", return_value=client):
        coordinator = coord_mod.BullCoordinator(hass, entry)
    data = await coordinator._async_update_data()
    assert device.iot_id in data
    assert client.login.call_count == 1  # 触发了一次重登


async def test_coordinator_relogin_failure_raises_auth_failed():
    """重登仍失败 -> ConfigEntryAuthFailed（触发 HA reauth 提示）。"""
    hass = FakeHass()
    entry = FakeEntry()
    client = make_fake_client()

    def always_9008(devices, family_ids=None):
        raise BullCloudError("refresh", code=9008, message="token 失效")

    client.refresh_devices.side_effect = always_9008
    client.login.side_effect = AuthenticationError("登录", 901006, "用户名或密码错误")

    with patch.object(coord_mod, "BullCloudClient", return_value=client):
        coordinator = coord_mod.BullCoordinator(hass, entry)
    try:
        await coordinator._async_update_data()
    except ConfigEntryAuthFailed:
        pass
    else:
        raise AssertionError("expected ConfigEntryAuthFailed")


async def test_coordinator_generic_error_is_update_failed():
    """普通业务错误 -> UpdateFailed（HA 显示 unavailable 但不弹 reauth）。"""
    hass = FakeHass()
    entry = FakeEntry()
    client = make_fake_client()
    client.refresh_devices.side_effect = BullCloudError(
        "refresh", code=500, message="服务器内部错误"
    )

    with patch.object(coord_mod, "BullCloudClient", return_value=client):
        coordinator = coord_mod.BullCoordinator(hass, entry)
    try:
        await coordinator._async_update_data()
    except UpdateFailed:
        pass
    else:
        raise AssertionError("expected UpdateFailed")


async def test_mqtt_property_applied():
    """MQTT 属性回推 -> 设备属性更新 + coordinator 数据刷新。"""
    hass = FakeHass()
    entry = FakeEntry()
    device = make_fake_device()

    coordinator = await make_coordinator(hass, entry, device)

    # 模拟 MQTT 线程回调 -> 事件循环应用
    coordinator._on_mqtt_property(device.iot_id, "PowerSwitch_1", 0)
    await asyncio.sleep(0)  # 让 call_soon_threadsafe 回调执行
    assert coordinator.devices[device.iot_id].properties["PowerSwitch_1"] == 0

    coordinator._on_mqtt_status(device.iot_id, "OFFLINE")
    await asyncio.sleep(0)
    assert coordinator.devices[device.iot_id].status == "OFFLINE"


async def test_switch_platform():
    """switch 平台：每通道一个实体 + 开/关控制 + 乐观更新。"""
    hass = FakeHass()
    entry = FakeEntry()
    device = make_fake_device()

    coordinator = await make_coordinator(hass, entry, device)
    client = coordinator.client

    added = []
    await switch_mod.async_setup_entry(hass, entry, lambda ents: added.extend(ents))
    assert len(added) == 3, f"应有 3 个开关通道, got {len(added)}"

    ent = next(e for e in added if e._identifier == "PowerSwitch_1")
    assert ent.name == "进门射灯", ent.name
    assert ent.is_on is True
    assert ent.unique_id == f"{device.iot_id}_switch_PowerSwitch_1"
    info = ent.device_info
    assert info["identifiers"] == {(DOMAIN, device.iot_id)}
    assert info["manufacturer"] == "公牛 (BULL)"

    ent.async_write_ha_state = lambda: None
    await ent.async_turn_off()
    assert device.properties["PowerSwitch_1"] == 0
    assert ent.is_on is False
    client.set_property.assert_called_once_with(
        device.iot_id, "PowerSwitch_1", 0
    )


async def test_switch_single_channel_device():
    """单键设备（只有裸 PowerSwitch）：暴露总开关，不重复。"""
    hass = FakeHass()
    entry = FakeEntry()
    device = Device(
        iot_id="fake_plug_001",
        product_id=5678,
        name="插座",
        status="ONLINE",
        product_name="智能插座",
    )
    device.properties["PowerSwitch"] = 1

    coordinator = await make_coordinator(hass, entry, device)

    added = []
    await switch_mod.async_setup_entry(hass, entry, lambda ents: added.extend(ents))
    assert len(added) == 1, f"单键设备应只有 1 个开关, got {len(added)}"
    assert added[0]._identifier == "PowerSwitch"
    assert added[0].is_on is True


async def test_sensor_platform():
    """sensor 平台：数值缩放与单位。"""
    hass = FakeHass()
    entry = FakeEntry()
    device = make_fake_device()

    coordinator = await make_coordinator(hass, entry, device)

    added = []
    await sensor_mod.async_setup_entry(hass, entry, lambda ents: added.extend(ents))
    assert len(added) == 1, f"只有 RealTimePower 命中, got {len(added)}"
    ent = added[0]
    assert ent.native_value == 12.0
    assert ent.native_unit_of_measurement == "W"

    # 缩放测试: Voltage ÷10
    device.properties["Voltage"] = 2205
    added2 = []
    await sensor_mod.async_setup_entry(hass, entry, lambda ents: added2.extend(ents))
    volt = next(e for e in added2 if e._identifier == "Voltage")
    assert volt.native_value == 220.5, volt.native_value


async def test_binary_sensor_platform():
    """binary_sensor 平台：在线状态。"""
    hass = FakeHass()
    entry = FakeEntry()
    device = make_fake_device()

    coordinator = await make_coordinator(hass, entry, device)

    added = []
    await bs_mod.async_setup_entry(hass, entry, lambda ents: added.extend(ents))
    assert len(added) == 1
    assert added[0].is_on is True
    device.status = "OFFLINE"
    assert added[0].is_on is False


async def test_options_flow():
    """选项流：轮询间隔 + MQTT 开关。"""
    flow = cf_mod.BullConfigFlow()
    flow.hass = FakeHass()
    flow.handler = DOMAIN
    flow.flow_id = "flow5"
    flow.context = {"source": "user"}

    result = await flow.async_get_options_flow(FakeEntry()).async_step_init(
        {"scan_interval": 30, "mqtt_enabled": False}
    )
    assert result["type"] == "create_entry", result
    assert result["data"]["scan_interval"] == 30
    assert result["data"]["mqtt_enabled"] is False


async def main():
    tests = [
        ("config_flow: user 成功", test_config_flow_user_success),
        ("config_flow: 密码错误", test_config_flow_user_bad_credentials),
        ("config_flow: 无法连接", test_config_flow_user_cannot_connect),
        ("config_flow: reauth 两步", test_config_flow_reauth_flow),
        ("coordinator: 首刷", test_coordinator_first_refresh),
        ("coordinator: 无 token 先登录", test_coordinator_login_when_no_token),
        ("coordinator: token 恢复", test_coordinator_token_recovery),
        ("coordinator: 重登失败 -> reauth", test_coordinator_relogin_failure_raises_auth_failed),
        ("coordinator: 普通错误 -> unavailable", test_coordinator_generic_error_is_update_failed),
        ("coordinator: MQTT 属性回推", test_mqtt_property_applied),
        ("switch 平台", test_switch_platform),
        ("switch 平台（单键设备）", test_switch_single_channel_device),
        ("sensor 平台", test_sensor_platform),
        ("binary_sensor 平台", test_binary_sensor_platform),
        ("options 流", test_options_flow),
    ]
    print("=" * 60)
    for name, fn in tests:
        await check(name, fn)
    print("=" * 60)
    print(f"通过 {len(PASSED)}/{len(tests)}")
    if FAILED:
        for name, err in FAILED:
            print(f"  FAILED: {name}: {err}")
        sys.exit(1)


asyncio.run(main())
