"""CloudAPI 网关 HMAC-SHA256 签名（阿里云 API 网关风格 x-ca-* 签名）。

公牛智家云的所有 HTTP 请求都经过 api.iotbull.com 网关，签名规则（2026-10 实测复现）：
    签名字符串 = METHOD\n
                 Accept\n
                 Content-MD5\n
                 Content-Type\n
                 Date\n
                 CanonicalHeaders      # x-ca-* 头，按 key 排序，每行 "key:value\n"
                 CanonicalResource     # path[?query]，query 按 key 排序
    签名 = Base64(HmacSHA256(APP_SECRET, 签名字符串))

实测要点（网关报错头 X-Ca-Error-Message 会回显服务端的待签字符串，可用来校准）：
- x-www-form-urlencoded 请求：网关用表单字段本身重建 CanonicalResource，
  因此签名的 query 就是表单字段（按 key 排序），且不计算 Content-MD5。
- 登录接口还必须带头部 Login_parameter: APP_PWD（大小写敏感，连字符写法不行）。
"""

import base64
import hashlib
import hmac
import uuid
from datetime import UTC, datetime
from urllib.parse import parse_qsl

# MosHome 5.1.13 客户端内置的应用凭证；已验证 5.3.1 云端兼容性。
APP_KEY = "2037288812025"
APP_SECRET = b"XxNjYxonJBt6DskF368fdjLEQZC9ziMeLOZPf"
APP_VERSION = "5.1.13"
APP_CLIENT_ID = "paascloudclientuic"
APP_CLIENT_SECRET = "paascloudClientSecret"
API_HOST = "api.iotbull.com"

ACCEPT = "application/json; charset=utf-8"


def _http_date() -> str:
    """RFC 1123 格式的 UTC 时间，如 'Tue, 21 Nov 2023 10:00:00 GMT'。"""
    return datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S GMT")


def signing_query(content_type: str, body: str, query: dict | None) -> dict | None:
    """确定参与签名的 query。

    实测结论：网关会用 x-www-form-urlencoded 请求的表单字段重建待签名
    资源路径，因此表单请求的 query 就是表单字段本身（按 key 排序）；
    其余请求使用显式传入的 query。
    """
    if query is not None:
        return query
    if content_type.startswith("application/x-www-form-urlencoded") and body:
        return dict(parse_qsl(body, keep_blank_values=True))
    return None


def canonical_resource(path: str, query: dict | None) -> str:
    """拼接待签名的资源路径：query 按 key 排序，空值只保留键名。"""
    if not query:
        return path
    parts = [f"{k}={v}" if v else k for k, v in sorted(query.items())]
    joined = "&".join(parts)
    return f"{path}?{joined}" if joined else path


def build_headers(
    method: str,
    path: str,
    content_type: str,
    body: str = "",
    query: dict | None = None,
) -> dict:
    """生成一套带签名的 CloudAPI 请求头。"""
    date = _http_date()
    query = signing_query(content_type, body, query)
    x_ca_headers = {
        "x-ca-key": APP_KEY,
        "x-ca-nonce": str(uuid.uuid4()),
        "x-ca-signature-method": "HmacSHA256",
        "x-ca-timestamp": str(int(datetime.now(UTC).timestamp() * 1000)),
    }
    canonical_headers = "".join(f"{k}:{v}\n" for k, v in sorted(x_ca_headers.items()))

    # 表单请求（登录）不计算 Content-MD5，其余有 body 的请求都计算
    content_md5 = ""
    if body and not query:
        content_md5 = base64.b64encode(
            hashlib.md5(body.encode("utf-8")).digest()
        ).decode()

    string_to_sign = (
        f"{method}\n{ACCEPT}\n{content_md5}\n{content_type}\n{date}\n"
        f"{canonical_headers}{canonical_resource(path, query)}"
    )
    signature = base64.b64encode(
        hmac.new(APP_SECRET, string_to_sign.encode("utf-8"), hashlib.sha256).digest()
    ).decode()

    headers = {
        "Host": API_HOST,
        "X-Ca-Key": APP_KEY,
        "X-Ca-Nonce": x_ca_headers["x-ca-nonce"],
        "X-Ca-Signature-Method": "HmacSHA256",
        "X-Ca-Timestamp": x_ca_headers["x-ca-timestamp"],
        "X-Ca-Signature-Headers": ",".join(sorted(x_ca_headers)),
        "X-Ca-Signature": signature,
        "CA_VERSION": "1",
        # 应用级 Basic 凭证（client_id:client_secret），用户级 Bearer token 会覆盖它
        "Authorization": "Basic "
        + base64.b64encode(f"{APP_CLIENT_ID}:{APP_CLIENT_SECRET}".encode()).decode(),
        "X-App-Platform": "android",
        "X-App-Version": APP_VERSION,
        "User-Agent": "ALIYUN-ANDROID-DEMO",
        "Accept": ACCEPT,
        "Accept-Language": "zh-Hans;q=1, zh-Hant-CN;q=0.9, en-CN;q=0.8",
        "Date": date,
        "Content-Type": content_type,
    }
    if content_md5:
        headers["Content-Md5"] = content_md5
    return headers
