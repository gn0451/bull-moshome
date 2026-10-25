"""对线上网关的签名验证测试（无需真实账号）。

原理：用假凭证打各端点。
- 签名/加密正确 -> 网关放行到业务层，返回业务错误（901006 / invalid_token）
- 签名错误     -> 网关返回 HTTP 403 A403IS InvalidSignature

运行: python tests/test_signature.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

from bull_iot.client import AuthenticationError, BullCloudClient
from bull_iot.signing import build_headers

API = "https://api.iotbull.com"
passed = failed = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {label}{(' | ' + detail) if detail else ''}")
    if ok:
        passed += 1
    else:
        failed += 1


def test_login_endpoint() -> None:
    """登录接口：假凭证应被业务层拒绝（901006），而不是签名层拒绝。"""
    client = BullCloudClient()
    try:
        client.login("00000000000", "not-a-real-password")
        check("登录接口返回业务错误", False, "假凭证竟然登录成功")
    except AuthenticationError as err:
        check(
            "登录接口返回业务错误",
            "901006" in str(err) or "901015" in str(err),
            str(err),
        )
    except Exception as err:  # noqa: BLE001
        check("登录接口返回业务错误", False, repr(err))
    finally:
        client.close()


def probe_json_endpoint(method: str, path: str, body: str = "") -> None:
    """需要登录的 JSON 端点：假 token 应得到 invalid_token，而不是 InvalidSignature。"""
    headers = build_headers(method, path, "application/json", body)
    headers["Authorization"] = "Bearer fake-token"
    resp = requests.request(
        method,
        API + path,
        headers=headers,
        data=body.encode() if body else None,
        timeout=10,
    )
    err = resp.headers.get("X-Ca-Error-Message", "")
    is_sig_error = "Invalid Signature" in err
    check(
        f"{method} {path} 签名通过",
        not is_sig_error,
        err or resp.text[:120],
    )


def main() -> int:
    print("== 对 api.iotbull.com 线上网关的签名验证 ==\n")
    test_login_endpoint()
    probe_json_endpoint("GET", "/v2/families")
    probe_json_endpoint("GET", "/mos/home/v3/rooms")
    probe_json_endpoint(
        "PUT",
        "/mos/v1/dc/setDeviceProperty/fake-iot-id",
        json.dumps([{"value": 1, "identifier": "PowerSwitch"}]),
    )
    print(f"\n结果: {passed} 通过, {failed} 失败")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
