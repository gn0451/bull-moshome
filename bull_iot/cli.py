"""命令行入口。

凭证获取优先级：--user/--password 参数 > 环境变量 BULL_USERNAME/BULL_PASSWORD > 交互输入。

示例::

    # 列出所有设备
    python -m bull_iot.cli devices

    # 打开某设备的第一个开关通道
    python -m bull_iot.cli set --iot-id DEVICE_IOT_ID --identifier PowerSwitch --value 1

    # MQTT 实时监听 60 秒
    python -m bull_iot.cli watch --seconds 60

    # 不登录，仅用假凭证探测网关签名是否被接受
    python -m bull_iot.cli probe
"""

import argparse
import getpass
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from .client import BullCloudClient, BullCloudError

# 支持项目根目录的 .env 文件（存放 BULL_USERNAME / BULL_PASSWORD，勿提交 git）
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def resolve_credentials(args) -> tuple[str, str]:
    username = args.user or os.getenv("BULL_USERNAME")
    password = args.password or os.getenv("BULL_PASSWORD")
    if not username:
        username = input("公牛智家账号（手机号/用户名）: ").strip()
    if not password:
        password = getpass.getpass("密码: ")
    return username, password


def make_client(args) -> BullCloudClient:
    client = BullCloudClient()
    username, password = resolve_credentials(args)
    print(f"正在登录 {username} ...")
    client.login(username, password)
    print(f"登录成功，openid={client.openid}")
    return client


def cmd_devices(args) -> None:
    client = make_client(args)
    try:
        devices = client.list_devices()
        if not devices:
            print("账号下没有设备。")
            return
        print(f"\n共 {len(devices)} 台设备：\n")
        for device in devices:
            print(device.describe())
            print()
    finally:
        client.close()


def cmd_families(args) -> None:
    client = make_client(args)
    try:
        for family in client.get_families():
            print(f"  familyId={family['familyId']}  {family.get('familyName', '')}")
    finally:
        client.close()


def cmd_info(args) -> None:
    client = make_client(args)
    try:
        info = client.get_device_info(args.iot_id)
        for key in ("productName", "modelName", "firmwareVersion", "nickName"):
            if key in info:
                print(f"  {key}: {info[key]}")
    finally:
        client.close()


def cmd_set(args) -> None:
    client = make_client(args)
    try:
        value = int(args.value) if args.value.lstrip("-").isdigit() else args.value
        client.set_property(args.iot_id, args.identifier, value)
        print(f"已下发: {args.iot_id} {args.identifier} = {value}")
    finally:
        client.close()


def cmd_invoke(args) -> None:
    client = make_client(args)
    try:
        client.invoke_thing_service(args.iot_id, args.identifier)
        print(f"已调用服务: {args.identifier}")
    finally:
        client.close()


def cmd_watch(args) -> None:
    from .mqtt_listener import BullMqttListener

    client = make_client(args)
    try:
        listener = BullMqttListener(
            client.openid, client.access_token, wildcard=args.wildcard
        )
        listener.start()
        print(f"MQTT 监听中（{args.seconds} 秒），按设备物理开关可看到状态回推...\n")
        deadline = time.time() + args.seconds
        while time.time() < deadline:
            time.sleep(0.5)
        listener.stop()
    finally:
        client.close()


def cmd_probe(args) -> None:
    """不登录，直接用假凭证打登录接口，验证签名实现是否被网关接受。"""
    from .client import AuthenticationError

    client = BullCloudClient()
    try:
        client.login("00000000000", "not-a-real-password")
        print("异常：假凭证竟然登录成功了？")
    except AuthenticationError as err:
        print(f"探活成功：网关接受了签名，返回业务错误 -> {err}")
        print("这说明请求签名/加密与云端一致，换成真实凭证即可登录。")
    except BullCloudError as err:
        print(f"探活失败：网关未接受请求 -> {err}")
        print("如果错误与签名相关（如 InvalidSignature），说明签名实现有偏差。")
    finally:
        client.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="bull_iot", description="公牛智家云（MosHome）Python 客户端"
    )
    parser.add_argument("--user", help="账号（也可用环境变量 BULL_USERNAME）")
    parser.add_argument("--password", help="密码（也可用环境变量 BULL_PASSWORD）")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("families", help="列出家庭").set_defaults(func=cmd_families)
    sub.add_parser("devices", help="列出所有设备及属性").set_defaults(func=cmd_devices)

    p_info = sub.add_parser("info", help="设备详情")
    p_info.add_argument("--iot-id", required=True)
    p_info.set_defaults(func=cmd_info)

    p_set = sub.add_parser("set", help="设置设备属性")
    p_set.add_argument("--iot-id", required=True)
    p_set.add_argument("--identifier", required=True, help="如 PowerSwitch")
    p_set.add_argument("--value", required=True, help="如 1 或 0")
    p_set.set_defaults(func=cmd_set)

    p_invoke = sub.add_parser("invoke", help="调用设备服务")
    p_invoke.add_argument("--iot-id", required=True)
    p_invoke.add_argument("--identifier", required=True, help="如 SheduleAuth")
    p_invoke.set_defaults(func=cmd_invoke)

    p_watch = sub.add_parser("watch", help="MQTT 实时监听设备状态")
    p_watch.add_argument("--seconds", type=int, default=60)
    p_watch.add_argument("--wildcard", action="store_true", help="订阅 # 话题发现")
    p_watch.set_defaults(func=cmd_watch)

    sub.add_parser("probe", help="用假凭证探测网关签名是否被接受").set_defaults(func=cmd_probe)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\n已取消")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
