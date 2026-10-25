"""登录字段加密：复现 MosHome(公牛智家) Android 客户端的加密方式。

逆向结论（2026-10 实测复现）：
- 用户名：AES-128-CBC 加密，密钥为客户端硬编码的 16 字节 Key，
  每次请求随机生成 16 字节 IV 前缀在密文前，整体转大写 Hex 后提交。
- 密码：不传输原文，提交 sha256(sha256(password) + sha256("GONGNIU"))。
"""

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# 客户端硬编码的 AES-128 密钥（Base64 编码，解码后 16 字节）
LOGIN_AES_KEY_B64 = "cjJ2R1dCQTNRQVJOblJsUg=="

# 客户端硬编码的密码盐
PASSWORD_SALT = "GONGNIU"


def encrypt_username(username: str) -> str:
    """按客户端方式加密用户名。

    流程：PKCS#7 填充 -> AES-128-CBC 加密（随机 IV）-> (IV || 密文) -> 大写 Hex。
    """
    key = base64.b64decode(LOGIN_AES_KEY_B64)
    plain = (username or "").strip().encode("utf-8")
    pad_len = 16 - len(plain) % 16
    padded = plain + bytes([pad_len]) * pad_len
    iv = os.urandom(16)
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    return (iv + ciphertext).hex().upper()


def hash_password(password: str) -> str:
    """按客户端方式派生密码哈希：sha256(sha256(pwd) + sha256(salt))。"""
    inner = hashlib.sha256(password.encode("utf-8")).hexdigest()
    salt = hashlib.sha256(PASSWORD_SALT.encode("utf-8")).hexdigest()
    return hashlib.sha256((inner + salt).encode("utf-8")).hexdigest()
