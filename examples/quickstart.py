"""完整示例：登录 -> 列设备 -> 控制 -> MQTT 监听。

运行前设置环境变量（或改成交互输入）：
    export BULL_USERNAME="你的账号"
    export BULL_PASSWORD="你的密码"

    python examples/quickstart.py
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from bull_iot import BullCloudClient, BullMqttListener  # noqa: E402


def main() -> None:
    username = os.getenv("BULL_USERNAME") or input("账号: ")
    password = os.getenv("BULL_PASSWORD") or input("密码: ")

    client = BullCloudClient()
    client.login(username, password)
    print(f"登录成功 openid={client.openid}")

    # 1. 家庭与设备
    families = client.get_families()
    print(f"家庭: {[(f['familyId'], f.get('familyName')) for f in families]}")

    devices = client.list_devices()
    print(f"\n共 {len(devices)} 台设备:")
    for d in devices:
        print(d.describe(), "\n")

    if not devices:
        return

    # 2. 控制第一台设备的第一个开关通道（演示：开 -> 等 2 秒 -> 关）
    target = devices[0]
    identifier = "PowerSwitch"
    print(f"演示控制 {target.iot_id} {identifier} ...")
    client.set_property(target.iot_id, identifier, 1)
    time.sleep(2)
    client.set_property(target.iot_id, identifier, 0)

    # 3. MQTT 实时监听 30 秒（期间可按设备物理开关）
    print("\nMQTT 监听 30 秒，按设备物理开关试试...\n")
    listener = BullMqttListener(client.openid, client.access_token)
    listener.start()
    time.sleep(30)
    listener.stop()
    client.close()


if __name__ == "__main__":
    main()
