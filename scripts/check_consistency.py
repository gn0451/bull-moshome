#!/usr/bin/env python3
"""仓库一致性自检：客户端副本同步 + 版本号统一。

本地运行：
    python scripts/check_consistency.py

CI 在 `.github/workflows/validate.yml` 的 consistency job 中调用同一脚本。
退出码 0 表示通过，1 表示存在不一致（并打印具体差异）。
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
LIB_DIR = ROOT / "bull_iot"
COMP_DIR = ROOT / "custom_components" / "bull"

# 集成目录由 HACS 单独分发，无法引用仓库根目录的包，因此这四个模块各存一份。
# 两边必须逐字节相同，否则同一个 bug 要修两遍、CLI 与集成行为会分叉。
SHARED_MODULES = ("client.py", "crypto.py", "signing.py", "mqtt_listener.py")


def check_copies() -> list[str]:
    """Return a list of problems with the duplicated client modules."""
    problems: list[str] = []
    for name in SHARED_MODULES:
        lib_file = LIB_DIR / name
        comp_file = COMP_DIR / name
        if not lib_file.exists() or not comp_file.exists():
            problems.append(f"{name}: 文件缺失（bull_iot 或 custom_components/bull）")
            continue
        if lib_file.read_bytes() != comp_file.read_bytes():
            problems.append(
                f"{name}: bull_iot/{name} 与 custom_components/bull/{name} 内容不一致\n"
                f"    修复: cp custom_components/bull/{name} bull_iot/{name}"
            )
    return problems


def check_versions() -> list[str]:
    """Return a list of problems with version numbers across the repo."""
    problems: list[str] = []
    manifest_version = json.loads(
        (COMP_DIR / "manifest.json").read_text(encoding="utf-8")
    )["version"]

    init_source = (LIB_DIR / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', init_source)
    if match is None:
        problems.append("bull_iot/__init__.py: 找不到 __version__")
        return problems
    lib_version = match.group(1)

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    heading = re.search(r"^##\s+([0-9][^\s]*)", changelog, re.MULTILINE)
    if heading is None:
        problems.append("CHANGELOG.md: 找不到版本标题（形如 '## 1.3.1'）")
        return problems
    changelog_version = heading.group(1)

    print(
        f"版本号: manifest={manifest_version} "
        f"lib={lib_version} changelog={changelog_version}"
    )
    if not manifest_version == lib_version == changelog_version:
        problems.append(
            "版本号不一致：custom_components/bull/manifest.json、"
            "bull_iot/__init__.py 的 __version__、CHANGELOG.md 首条标题必须相同"
        )
    return problems


def main() -> int:
    problems = check_copies() + check_versions()
    if not problems:
        print("一致性检查通过 ✓")
        return 0
    print("\n发现以下不一致：", file=sys.stderr)
    for problem in problems:
        print(f"  - {problem}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
