"""bull HA 集成端到端 mock 测试。

不访问真实网络：mock BullCloudClient 的全部出网方法，验证
config flow（user/reauth/reauth_confirm）、coordinator（首刷/周期刷新/
MQTT 回推/属性应用）、能力分级、八个平台实体与匿名诊断。
"""

import asyncio
import os
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# 组件目录 = <repo>/custom_components（相对本测试文件定位）
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "custom_components"))

import bull.binary_sensor as bs_mod
import bull.ble as ble_mod
import bull.ble_charger as ble_charger_mod
import bull.button as button_mod
import bull.config_flow as cf_mod
import bull.coordinator as coord_mod
import bull.cover as cover_mod
import bull.diagnostics as diagnostics_mod
import bull.light as light_mod
import bull.number as number_mod
import bull.select as select_mod
import bull.sensor as sensor_mod
import bull.switch as switch_mod
from bull.client import AuthenticationError, BullCloudError, Device
from bull.const import (
    CONF_FAMILY_IDS,
    CONF_MQTT_ENABLED,
    DOMAIN,
    LEGACY_CONF_FAMILY_IDS,
)
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

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
        # Store 需要 hass.config.path(...)，真实 HA 一定有，替身也要给
        self.config = types.SimpleNamespace(
            config_dir="/tmp/fake-ha-config",
            path=lambda *parts: os.path.join("/tmp/fake-ha-config", *parts),
        )
        self.config_entries = types.SimpleNamespace(
            async_update_entry=MagicMock(return_value=True),
            async_schedule_reload=MagicMock(),
            async_get_entry=MagicMock(return_value=None),
            async_get_known_entry=MagicMock(return_value=None),
            async_entry_for_domain_unique_id=MagicMock(return_value=None),
            flow=MagicMock(),
        )

    async def async_add_executor_job(self, func, *args):
        return func(*args)


class FakeEntry:
    def __init__(self, data=None, options=None):
        self.data = data or {
            "username": "13800138000",
            "password": "secret",
            CONF_FAMILY_IDS: [1001],
            CONF_MQTT_ENABLED: False,
        }
        self.options = options or {}
        self.entry_id = "test_entry_1"
        self.title = "13800138000"
        self.unique_id = "fake_openid"
        self._unload_callbacks = []
        # 以下属性用于模拟 ConfigEntry 的公开接口。HA 版本升级后会陆续访问这些字段
        # （例如 async_update_reload_and_abort 会读 update_listeners），补齐可避免
        # 测试替身因新版 HA 内部实现变化而报 AttributeError。
        self.domain = DOMAIN
        self.version = 1
        self.minor_version = 1
        self.source = "user"
        self.state = "loaded"
        self.update_listeners = []
        self.discovery_keys = {}
        self.pref_disable_polling = False
        self.runtime_data = None

    def async_on_unload(self, callback):
        self._unload_callbacks.append(callback)


def make_fake_device():
    """一台 G27 三位开关（模拟真实抓包结构）。"""
    dev = Device(
        iot_id="fake_iot_001",
        product_id=6,
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
        client.refresh_devices.side_effect = lambda d, f=None, c=None: {
            **d,
            device.iot_id: device,
        }
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

    async def valid(hass, username, password):
        return "fake_openid", [{"familyId": 1001, "familyName": "家", "deviceCount": 3}]

    with patch.object(cf_mod, "_validate_credentials", new=valid):
        select_result = await flow.async_step_user(
            {"username": "13800138000", "password": "secret"}
        )
        assert select_result["type"] == "form", select_result
        assert select_result["step_id"] == "select_family", select_result
        result = await flow.async_step_select_family(
            {CONF_FAMILY_IDS: ["1001"], CONF_MQTT_ENABLED: False}
        )
    assert result["type"] == "create_entry", result
    assert result["data"]["username"] == "13800138000"
    # 条目名要脱敏：手机号会出现在设置页、截图和 issue 里
    assert result["title"] == "138****8000", result["title"]
    assert result["data"][CONF_FAMILY_IDS] == [1001]
    assert result["data"][CONF_MQTT_ENABLED] is False


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
    hass.config_entries.async_get_known_entry = MagicMock(return_value=entry)

    flow = cf_mod.BullConfigFlow()
    flow.hass = hass
    flow.handler = DOMAIN
    flow.flow_id = "flow4"
    flow.context = {"source": "reauth", "entry_id": entry.entry_id}

    async def ok_validate(hass_, u, p):
        return "fake_openid", []

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


async def test_config_flow_reauth_rejects_wrong_account():
    """reauth must not replace an entry with another MosHome account."""
    hass = FakeHass()
    entry = FakeEntry()
    hass.config_entries.async_get_entry = MagicMock(return_value=entry)
    hass.config_entries.async_get_known_entry = MagicMock(return_value=entry)
    flow = cf_mod.BullConfigFlow()
    flow.hass = hass
    flow.handler = DOMAIN
    flow.flow_id = "flow-wrong-account"
    flow.context = {"source": "reauth", "entry_id": entry.entry_id}

    async def wrong_account(hass_, username, password):
        return "another_openid", []

    with patch.object(cf_mod, "_validate_credentials", new=wrong_account):
        result = await flow.async_step_reauth_confirm(
            {"username": "other", "password": "valid"}
        )
    assert result["type"] == "form", result
    assert result["errors"] == {"base": "wrong_account"}, result
    hass.config_entries.async_update_entry.assert_not_called()


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
    assert coordinator.client.refresh_devices.call_count == 1
    assert coordinator.client.refresh_devices.call_args.args[1] == [1001]


async def test_coordinator_login_when_no_token():
    """coordinator 首刷（无 token）：先登录再拉设备。"""
    hass = FakeHass()
    entry = FakeEntry()
    device = make_fake_device()

    client = make_fake_client()
    client.access_token = None
    client.refresh_devices.side_effect = lambda d, f=None, c=None: {**d, device.iot_id: device}
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

    def refresh_devices(devices, family_ids=None, info_cache=None):
        devices[device.iot_id] = device
        return devices

    def flaky_refresh(devices, family_ids=None, info_cache=None):
        if not client.login.called:
            raise BullCloudError("refresh", code=9008, message="token 失效")
        return refresh_devices(devices, family_ids, info_cache)

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

    def always_9008(devices, family_ids=None, info_cache=None):
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
    assert ent.unique_id == f"{device.iot_id}.PowerSwitch_1"
    info = ent.device_info
    assert info["identifiers"] == {(DOMAIN, device.iot_id)}
    assert info["manufacturer"] == "公牛 (BULL)"

    ent.async_write_ha_state = lambda: None
    await ent.async_turn_off()
    assert device.properties["PowerSwitch_1"] == 0
    assert ent.is_on is False
    client.set_properties.assert_called_once_with(device.iot_id, {"PowerSwitch_1": 0})


async def test_switch_read_only_products():
    """情景面板即使暴露 PowerSwitch，也不能生成负载开关。"""
    for product_id in (3, 20, 21, 69):
        hass = FakeHass()
        entry = FakeEntry()
        device = make_fake_device()
        device.product_id = product_id
        await make_coordinator(hass, entry, device)
        added = []
        await switch_mod.async_setup_entry(
            hass, entry, lambda entities, target=added: target.extend(entities)
        )
        assert added == [], f"PID {product_id} 不应生成控制开关"


async def test_switch_unknown_capability_is_discovered_disabled():
    """An unknown load-like schema is discoverable but disabled by default."""
    hass = FakeHass()
    entry = FakeEntry()
    device = make_fake_device()
    device.product_id = 9999
    device.properties = {"PowerSwitch_1": 0, "RealTimePower": 0}
    await make_coordinator(hass, entry, device)
    added = []
    await switch_mod.async_setup_entry(hass, entry, lambda values: added.extend(values))
    assert len(added) == 1
    assert added[0].entity_registry_enabled_default is False
    assert added[0]._support_tier is switch_mod.SupportTier.INFERRED_SAFE


async def test_switch_unknown_battery_panel_stays_read_only():
    """An unprofiled battery panel must not become a load control."""
    hass = FakeHass()
    entry = FakeEntry()
    device = make_fake_device()
    device.product_id = 9998
    device.properties = {"PowerSwitch_1": 0, "BatteryStatus": 80}
    await make_coordinator(hass, entry, device)
    added = []
    await switch_mod.async_setup_entry(hass, entry, lambda values: added.extend(values))
    assert added == []


async def test_light_platform():
    """已验证灯 PID 按属性指纹生成可调光实体。"""
    hass = FakeHass()
    entry = FakeEntry()
    device = make_fake_device()
    device.product_id = 79
    device.properties = {
        "PowerSwitch": 1,
        "BrightValue": 500,
        "ColorTemperature": 500,
        "PowerGradation": 1,
    }
    await make_coordinator(hass, entry, device)
    added = []
    await light_mod.async_setup_entry(hass, entry, lambda ents: added.extend(ents))
    assert len(added) == 1
    assert added[0].is_on is True
    assert 120 <= added[0].brightness <= 130


async def test_cover_platform():
    """已验证窗帘 PID 按精确协议属性生成 cover。"""
    hass = FakeHass()
    entry = FakeEntry()
    device = make_fake_device()
    device.product_id = 31
    device.properties = {"curtainConrtol": 2, "curtainPosition": 35}
    await make_coordinator(hass, entry, device)
    added = []
    await cover_mod.async_setup_entry(hass, entry, lambda ents: added.extend(ents))
    assert len(added) == 1
    assert added[0].current_cover_position == 35


async def test_switch_single_channel_device():
    """单键设备（只有裸 PowerSwitch）：暴露总开关，不重复。"""
    hass = FakeHass()
    entry = FakeEntry()
    device = Device(
        iot_id="fake_plug_001",
        product_id=13,
        name="插座",
        status="ONLINE",
        product_name="智能插座",
    )
    device.properties["PowerSwitch"] = 1

    await make_coordinator(hass, entry, device)

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

    await make_coordinator(hass, entry, device)

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


async def test_digital_display_socket_platforms():
    """PID 296 exposes dedicated ports, display settings and telemetry."""
    hass = FakeHass()
    entry = FakeEntry()
    device = Device(
        iot_id="socket_296",
        product_id=296,
        name="数显插座",
        status="ONLINE",
        product_name="数显桌面充电站",
    )
    device.properties = {
        "PowerSwitch": 1,
        "C1": {"PowerSwitch": 1, "RealTimePower": 65, "CurrentProtocol": 1},
        "ChargeMode": 4,
        "OffScreenTime": 2,
        "TimerType": 1,
        "ScreenBrightValue": 66,
        "OffScreenSwitch": 1,
    }
    await make_coordinator(hass, entry, device)

    switches = []
    selects = []
    numbers = []
    sensors = []
    await switch_mod.async_setup_entry(
        hass, entry, lambda values: switches.extend(values)
    )
    await select_mod.async_setup_entry(
        hass, entry, lambda values: selects.extend(values)
    )
    await number_mod.async_setup_entry(
        hass, entry, lambda values: numbers.extend(values)
    )
    await sensor_mod.async_setup_entry(
        hass, entry, lambda values: sensors.extend(values)
    )

    assert len(switches) == 8
    assert len(selects) == 3
    assert len(numbers) == 1
    assert len(sensors) == 36
    c1 = next(entity for entity in switches if entity._port == "C1")
    assert c1.is_on is True
    protocol = next(
        entity
        for entity in sensors
        if getattr(entity, "_port", None) == "C1"
        and getattr(entity, "_suffix", None) == "CurrentProtocol"
    )
    assert protocol.native_value == "PD"
    mode = next(entity for entity in selects if entity._identifier == "ChargeMode")
    assert mode.current_option == "custom_1"
    assert "custom_1" in mode.options
    mode.async_write_ha_state = lambda: None
    await mode.async_select_option("smart")
    assert device.properties["ChargeMode"] == 0
    numbers[0].async_write_ha_state = lambda: None
    await numbers[0].async_set_native_value(80)
    assert device.properties["ScreenBrightValue"] == 80

    device.properties["PowerSwitch"] = 0
    assert c1.available is False
    assert numbers[0].available is False


async def test_mapped_charger_button():
    """PID 258 activation button follows the explicit state guard."""
    hass = FakeHass()
    entry = FakeEntry()
    device = Device(
        iot_id="charger_258",
        product_id=258,
        name="充电桩",
        status="ONLINE",
        product_name="公牛充电桩",
    )
    device.properties = {"DeviceWorkState.WorkState": 8}
    coordinator = await make_coordinator(hass, entry, device)
    added = []
    await button_mod.async_setup_entry(hass, entry, lambda values: added.extend(values))
    assert len(added) == 1
    assert added[0].available is True
    await added[0].async_press()
    coordinator.client.invoke_thing_service.assert_called_once_with(
        device.iot_id, "SheduleAuth"
    )
    device.properties["DeviceWorkState.WorkState"] = 2
    assert added[0].available is False


async def test_cloud_thing_service_charger():
    """PID 193/195 uses AppStopCharge and confirms the state transition."""
    hass = FakeHass()
    entry = FakeEntry()
    device = Device(
        iot_id="charger_193",
        product_id=193,
        name="交流充电桩",
        status="ONLINE",
        product_name="公牛充电桩",
    )
    device.properties = {
        "DeviceState.WorkState": 2,
        "DeviceState.GunState": 1,
    }
    coordinator = await make_coordinator(hass, entry, device)
    added = []
    await switch_mod.async_setup_entry(hass, entry, lambda values: added.extend(values))
    assert len(added) == 1
    assert added[0].is_on is True

    async def transition():
        device.properties["DeviceState.WorkState"] = 3

    coordinator.async_request_refresh = AsyncMock(side_effect=transition)
    await added[0].async_turn_off()
    coordinator.client.invoke_thing_service.assert_called_once_with(
        device.iot_id, "AppStopCharge"
    )


async def test_ble_protocol_and_telemetry_decode():
    """PID 309 BLE primitives decode identity, crypto and charger telemetry."""
    key = bytes.fromhex("00112233445566778899AABBCCDDEEFF")
    iv = b"0123456789ABCDEF"
    clear = b"bull-ble"
    cipher = ble_mod._encrypt(clear, key, iv)
    assert ble_mod._decrypt(cipher, len(clear), key, iv) == clear
    assert ble_charger_mod.dn_from_ble_address("AA:BB:CC:DD:EE:FF") == "AABBCCDDEEFF"
    assert ble_charger_mod.dn_from_ble_address("not-a-mac") is None

    device = Device(
        iot_id="charger_309",
        product_id=309,
        name="D3 充电桩",
        status="ONLINE",
    )
    updates = []
    charger = ble_charger_mod.BullBleCharger(
        MagicMock(),
        device,
        ble_mod.BleIdentity(309, "AABBCCDDEEFF"),
        AsyncMock(),
        AsyncMock(),
        lambda: updates.append(True),
    )
    charger._apply(ble_charger_mod.ATTR_WORK_STATE, b"\x02")
    charger._apply(ble_charger_mod.ATTR_CHARGE_MODE, b"\x01")
    assert device.properties["WorkState"] == 2
    assert device.properties["ChargeSwitch"] == 1
    assert device.properties["ChargeMode"] == 1
    assert len(updates) == 2


async def test_ble_charger_has_no_cloud_property_fallback():
    """PID 309 stays non-controllable when no valid BLE identity is available."""
    hass = FakeHass()
    entry = FakeEntry()
    device = Device(
        iot_id="charger_309_no_identity",
        product_id=309,
        name="D3 充电桩",
        status="ONLINE",
    )
    device.properties = {"ChargeSwitch": 0, "ChargeMode": 0}
    await make_coordinator(hass, entry, device)
    switches = []
    selects = []
    await switch_mod.async_setup_entry(
        hass, entry, lambda values: switches.extend(values)
    )
    await select_mod.async_setup_entry(
        hass, entry, lambda values: selects.extend(values)
    )
    assert switches == []
    assert len(selects) == 1
    assert selects[0].available is False


async def test_ble_charger_coordinator_lifecycle():
    """A valid PID 309 identity starts once and is stopped during unload."""
    hass = FakeHass()
    entry = FakeEntry()
    device = Device(
        iot_id="charger_309_lifecycle",
        product_id=309,
        name="D3 充电桩",
        status="ONLINE",
        raw={"deviceName": "AABBCCDDEEFF"},
    )
    fake_charger = MagicMock(available=False)
    fake_charger.async_start = AsyncMock()
    fake_charger.async_stop = AsyncMock()
    with patch.object(
        ble_charger_mod, "BullBleCharger", return_value=fake_charger
    ) as charger_class:
        coordinator = await make_coordinator(hass, entry, device)
        assert coordinator.ble_chargers[device.iot_id] is fake_charger
        fake_charger.async_start.assert_awaited_once()
        charger_class.assert_called_once()
        await coordinator.async_shutdown()
        fake_charger.async_stop.assert_awaited_once()


async def test_binary_sensor_platform():
    """binary_sensor 平台：在线状态。"""
    hass = FakeHass()
    entry = FakeEntry()
    device = make_fake_device()

    await make_coordinator(hass, entry, device)

    added = []
    await bs_mod.async_setup_entry(hass, entry, lambda ents: added.extend(ents))
    assert len(added) == 1
    assert added[0].unique_id == f"{device.iot_id}.connectivity"
    assert added[0].is_on is True
    device.status = "OFFLINE"
    assert added[0].is_on is False


async def test_options_flow():
    """选项流：家庭范围 + 轮询间隔 + MQTT 开关。"""
    flow = cf_mod.BullConfigFlow()
    flow.hass = FakeHass()
    flow.handler = DOMAIN
    flow.flow_id = "flow5"
    flow.context = {"source": "user"}

    options_flow = flow.async_get_options_flow(FakeEntry())
    options_flow._config_entry = FakeEntry()
    result = await options_flow.async_step_init(
        {
            CONF_FAMILY_IDS: ["1001"],
            "scan_interval": 30,
            "mqtt_enabled": False,
        }
    )
    assert result["type"] == "create_entry", result
    assert result["data"]["scan_interval"] == 30
    assert result["data"]["mqtt_enabled"] is False
    assert result["data"][CONF_FAMILY_IDS] == [1001]


async def test_options_flow_loads_current_families():
    """Opening options refreshes family labels while preserving the selection."""
    flow = cf_mod.BullConfigFlow()
    flow.hass = FakeHass()
    entry = FakeEntry()
    flow.hass.config_entries.async_get_known_entry = MagicMock(return_value=entry)
    options_flow = flow.async_get_options_flow(entry)
    options_flow.hass = flow.hass
    options_flow.handler = entry.entry_id

    async def load_families(hass, username, password):
        return "fake_openid", [
            {"familyId": 1001, "familyName": "测试家庭", "deviceCount": 3}
        ]

    with patch.object(cf_mod, "_validate_credentials", new=load_families):
        result = await options_flow.async_step_init()
    assert result["type"] == "form", result
    assert result["errors"] == {}, result


async def test_coordinator_options_override_family_scope():
    """A changed family selection takes effect without recreating the entry."""
    entry = FakeEntry(options={CONF_FAMILY_IDS: [2002]})
    with patch.object(coord_mod, "BullCloudClient", return_value=make_fake_client()):
        coordinator = coord_mod.BullCoordinator(FakeHass(), entry)
    assert coordinator.family_ids == [2002]


async def test_coordinator_accepts_legacy_family_scope():
    """Entries created by the established bull integration upgrade in place."""
    entry = FakeEntry(
        data={
            "username": "13800138000",
            "password": "secret",
            LEGACY_CONF_FAMILY_IDS: [3003],
        }
    )
    with patch.object(coord_mod, "BullCloudClient", return_value=make_fake_client()):
        coordinator = coord_mod.BullCoordinator(FakeHass(), entry)
    assert DOMAIN == "bull"
    assert coordinator.family_ids == [3003]


async def test_anonymized_diagnostics():
    """Diagnostics expose schemas and support levels, never IDs or values."""
    hass = FakeHass()
    entry = FakeEntry()
    device = make_fake_device()
    coordinator = await make_coordinator(hass, entry, device)
    coordinator.devices = {device.iot_id: device}
    report = await diagnostics_mod.async_get_config_entry_diagnostics(hass, entry)
    serialized = repr(report)
    assert device.iot_id not in serialized
    assert entry.data["username"] not in serialized
    assert "1001" not in serialized
    assert "PowerSwitch_1" in serialized
    assert report["devices"][0]["support_tier"] == "profiled"


async def test_info_cache_saved_immediately_when_grown():
    """缓存新增要立即落盘：否则用户装完马上重启会丢缓存，误以为优化没生效。"""
    hass = FakeHass()
    entry = FakeEntry()
    device = make_fake_device()
    coordinator = await make_coordinator(hass, entry, device)

    coordinator._store = MagicMock()
    coordinator._store.async_save = AsyncMock()
    coordinator._store.async_delay_save = MagicMock()
    coordinator._info_cache = {"iot_a": {"ts": 1.0, "detail": {"modelName": "M"}}}

    await coordinator._async_persist_info_cache(grew=True)
    coordinator._store.async_save.assert_awaited_once()
    coordinator._store.async_delay_save.assert_not_called()

    coordinator._store.async_save.reset_mock()
    await coordinator._async_persist_info_cache(grew=False)
    coordinator._store.async_save.assert_not_awaited()
    coordinator._store.async_delay_save.assert_called_once()



async def test_info_cache_loads_from_store():
    """Store 读取路径要真的走通（1.3.7 的教训：别让整条路径没人执行）。"""
    hass = FakeHass()
    entry = FakeEntry()
    device = make_fake_device()
    coordinator = await make_coordinator(hass, entry, device)

    # 空存储：不报错，缓存为 0
    await coordinator.async_load_info_cache()
    assert coordinator.info_cache_size == 0

    # 有数据：原样装载
    stored = {"iot_a": {"ts": 1.0, "detail": {"modelName": "M"}}}
    coordinator._store.async_load = AsyncMock(return_value=stored)
    await coordinator.async_load_info_cache()
    assert coordinator.info_cache_size == 1, coordinator.info_cache_size



async def test_path_normalization_groups_device_ids():
    """iotId 是字母数字混合，必须归一化成一个计时键，否则每台设备各占一行。"""
    from bull.client import _normalize_path

    assert (
        _normalize_path("/mos/device/v1/deviceInfo/KZFX7or158QNYLU9eCdY000000/get")
        == "/mos/device/v1/deviceInfo/{id}/get"
    )
    assert _normalize_path("/v1/families/182552/switch") == "/v1/families/{id}/switch"
    # 静态段不能被误伤
    assert _normalize_path("/mos/home/v3/rooms") == "/mos/home/v3/rooms"
    assert _normalize_path("/v2/families") == "/v2/families"
    assert (
        _normalize_path("/mos/v1/dc/setDeviceProperty")
        == "/mos/v1/dc/setDeviceProperty"
    )


async def test_device_info_cache_avoids_refetch():
    """缓存命中时不得再请求云端（这是重启变快的关键）。"""
    import time

    from bull.client import BullCloudClient

    client = BullCloudClient()
    devices = {"iot_a": Device(iot_id="iot_a", product_id=1)}
    cache = {
        "iot_a": {
            "ts": time.time(),
            "detail": {
                "productName": "P",
                "modelName": "M-1",
                "firmwareVersion": "9.9",
            },
        }
    }
    called = []
    client.get_device_info = lambda iot_id: called.append(iot_id) or {}
    try:
        client._enrich_device_info(devices, ["iot_a"], cache)
    finally:
        client.close()

    assert called == [], f"缓存命中却仍然请求了云端: {called}"
    assert devices["iot_a"].model_name == "M-1"
    assert devices["iot_a"].firmware_version == "9.9"


async def test_device_info_cache_expires():
    """缓存过期后应重新拉取，并写回新的时间戳。"""
    import time

    from bull.client import DEVICE_INFO_TTL, BullCloudClient

    client = BullCloudClient()
    devices = {"iot_a": Device(iot_id="iot_a", product_id=1)}
    cache = {
        "iot_a": {
            "ts": time.time() - DEVICE_INFO_TTL - 10,
            "detail": {"productName": "OLD", "modelName": "OLD", "firmwareVersion": "0"},
        }
    }
    called = []

    def fake_info(iot_id):
        called.append(iot_id)
        return {"productName": "NEW", "modelName": "NEW", "firmwareVersion": "1"}

    client.get_device_info = fake_info
    try:
        client._enrich_device_info(devices, ["iot_a"], cache)
    finally:
        client.close()

    assert called == ["iot_a"], called
    assert devices["iot_a"].model_name == "NEW"
    assert cache["iot_a"]["detail"]["modelName"] == "NEW"



async def test_request_path_uses_thread_session():
    """真实走一遍 _request：1.3.7 就是因为 _session 缺失在这里没被拦住。"""
    import requests

    from bull.client import BullCloudClient

    client = BullCloudClient()
    calls = {}

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"success": True, "result": {"families": []}}

    def fake_request(session, method, url, **kwargs):
        calls["method"] = method
        calls["url"] = url
        calls["session"] = id(session)
        return FakeResponse()

    original = requests.Session.request
    requests.Session.request = fake_request
    try:
        result = client._request("GET", "/v2/families")
        assert result["result"] == {"families": []}, result
        assert calls["url"].endswith("/v2/families"), calls["url"]
        assert calls["method"] == "GET", calls
        # 同一线程内应复用同一个 Session
        assert id(client._session()) == calls["session"]
    finally:
        requests.Session.request = original
        client.close()

    # 计时包装器确实记录了这次请求
    assert "GET /v2/families" in client.request_timings, client.request_timings


async def test_session_is_thread_local():
    """每个线程必须拿到自己的 Session（requests.Session 不保证线程安全）。"""
    import threading

    from bull.client import BullCloudClient

    client = BullCloudClient()
    main_session = client._session()
    assert client._session() is main_session

    box = {}

    def worker():
        box["session"] = client._session()

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    try:
        assert box["session"] is not main_session, "并发线程共用了同一个 Session"
    finally:
        client.close()



async def test_device_info_enrichment_is_concurrent():
    """新设备的型号/固件要并发拉取：串行 19 台会把启动拖到 8s+。"""
    import threading
    import time

    from bull.client import BullCloudClient

    client = BullCloudClient()
    devices = {
        f"iot_{i}": Device(iot_id=f"iot_{i}", product_id=1) for i in range(8)
    }
    lock = threading.Lock()
    state = {"now": 0, "max": 0}

    def fake_info(iot_id):
        with lock:
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
        time.sleep(0.03)
        with lock:
            state["now"] -= 1
        return {
            "productName": "P",
            "modelName": f"M-{iot_id}",
            "firmwareVersion": "1.0",
        }

    client.get_device_info = fake_info
    try:
        client._enrich_device_info(devices, list(devices))
    finally:
        client.close()

    assert state["max"] > 1, "设备详情没有并发，仍是串行请求"
    assert all(
        d.model_name == f"M-{d.iot_id}" and d.detail for d in devices.values()
    ), [d.model_name for d in devices.values()]



async def test_refresh_timings_breakdown():
    """分阶段计时：登录 / 家庭切换 / 设备列表要分别落到对应字段。"""
    hass = FakeHass()
    entry = FakeEntry()
    device = make_fake_device()
    coordinator = await make_coordinator(hass, entry, device)
    coordinator.client.request_timings = {
        "POST /mos/uic/v2/auth/form": 1200.0,
        "POST /v1/families/{id}/switch": 800.0,
        "GET /mos/home/v3/rooms": 3000.0,
    }

    coordinator._record_timings(fetch_ms=5200.0, total_ms=6000.0)
    timings = coordinator.last_refresh_timings
    assert timings["login_ms"] == 1200.0, timings
    assert timings["families_ms"] == 800.0, timings
    assert timings["rooms_ms"] == 3000.0, timings
    assert timings["fetch_ms"] == 5200.0, timings
    assert timings["total_ms"] == 6000.0, timings

    report = await diagnostics_mod.async_get_config_entry_diagnostics(hass, entry)
    assert report["last_refresh_timings_ms"]["rooms_ms"] == 3000.0, report



async def test_diagnostics_redact_legacy_family_scope():
    """老条目把家庭存在 selected_families 里：诊断不能泄露它，计数也不能是 0。"""
    hass = FakeHass()
    entry = FakeEntry(
        data={
            "username": "13800138000",
            "password": "secret",
            LEGACY_CONF_FAMILY_IDS: [182552],
            CONF_MQTT_ENABLED: False,
        }
    )
    device = make_fake_device()
    coordinator = await make_coordinator(hass, entry, device)
    coordinator.devices = {device.iot_id: device}

    report = await diagnostics_mod.async_get_config_entry_diagnostics(hass, entry)
    serialized = repr(report)
    assert "182552" not in serialized, "家庭 ID 泄露到诊断里"
    assert report["selected_family_count"] == 1, report["selected_family_count"]



async def test_migrate_entry_masks_account_title():
    """v1 -> v2：把旧条目名里的手机号脱敏，避免出现在设置页和截图里。"""
    import bull as bull_pkg

    hass = FakeHass()
    entry = FakeEntry()
    entry.version = 1
    entry.title = "13819880398"

    assert await bull_pkg.async_migrate_entry(hass, entry) is True
    kwargs = hass.config_entries.async_update_entry.call_args.kwargs
    assert kwargs["title"] == "138****0398", kwargs
    assert kwargs["version"] == 2, kwargs


async def main():
    tests = [
        ("config_flow: user 成功", test_config_flow_user_success),
        ("config_flow: 密码错误", test_config_flow_user_bad_credentials),
        ("config_flow: 无法连接", test_config_flow_user_cannot_connect),
        ("config_flow: reauth 两步", test_config_flow_reauth_flow),
        (
            "config_flow: reauth 拒绝其他账号",
            test_config_flow_reauth_rejects_wrong_account,
        ),
        ("coordinator: 首刷", test_coordinator_first_refresh),
        ("coordinator: 无 token 先登录", test_coordinator_login_when_no_token),
        ("coordinator: token 恢复", test_coordinator_token_recovery),
        (
            "coordinator: 重登失败 -> reauth",
            test_coordinator_relogin_failure_raises_auth_failed,
        ),
        (
            "coordinator: 普通错误 -> unavailable",
            test_coordinator_generic_error_is_update_failed,
        ),
        ("coordinator: MQTT 属性回推", test_mqtt_property_applied),
        ("switch 平台", test_switch_platform),
        ("switch 只读 PID 保护", test_switch_read_only_products),
        (
            "switch 未知设备安全发现",
            test_switch_unknown_capability_is_discovered_disabled,
        ),
        ("switch 未知电池面板只读", test_switch_unknown_battery_panel_stays_read_only),
        ("switch 平台（单键设备）", test_switch_single_channel_device),
        ("light 平台", test_light_platform),
        ("cover 平台", test_cover_platform),
        ("sensor 平台", test_sensor_platform),
        ("PID 296 数显插座专用平台", test_digital_display_socket_platforms),
        ("PID 258 充电激活按钮", test_mapped_charger_button),
        ("PID 193/195 云端充电桩", test_cloud_thing_service_charger),
        ("PID 309 BLE 协议与遥测解析", test_ble_protocol_and_telemetry_decode),
        ("PID 309 禁止云属性降级控制", test_ble_charger_has_no_cloud_property_fallback),
        ("PID 309 BLE 生命周期", test_ble_charger_coordinator_lifecycle),
        ("binary_sensor 平台", test_binary_sensor_platform),
        ("options 流", test_options_flow),
        ("options 加载家庭", test_options_flow_loads_current_families),
        ("options 家庭范围生效", test_coordinator_options_override_family_scope),
        ("legacy bull 配置原位升级", test_coordinator_accepts_legacy_family_scope),
        ("缓存新增立即落盘", test_info_cache_saved_immediately_when_grown),
        ("设备信息缓存装载", test_info_cache_loads_from_store),
        ("路径归一化", test_path_normalization_groups_device_ids),
        ("设备信息缓存命中", test_device_info_cache_avoids_refetch),
        ("设备信息缓存过期", test_device_info_cache_expires),
        ("请求走线程 Session", test_request_path_uses_thread_session),
        ("Session 线程隔离", test_session_is_thread_local),
        ("设备详情并发补全", test_device_info_enrichment_is_concurrent),
        ("刷新分阶段计时", test_refresh_timings_breakdown),
        ("诊断脱敏老条目家庭", test_diagnostics_redact_legacy_family_scope),
        ("条目名脱敏迁移", test_migrate_entry_masks_account_title),
        ("匿名诊断", test_anonymized_diagnostics),
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
