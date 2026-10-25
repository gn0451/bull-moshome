# 发版流程

HACS 通过 **GitHub Release / tag** 判断版本。没有 release 的仓库，HACS 只能拉默认分支，
用户看不到版本号、收不到更新提示、也无法回滚到历史版本。

## 版本号写在三个地方

| 位置 | 字段 |
|---|---|
| `custom_components/bull/manifest.json` | `"version": "1.3.1"` |
| `bull_iot/__init__.py` | `__version__ = "1.3.1"` |
| `CHANGELOG.md` | 最上面一条 `## 1.3.1` |

三处必须相同，由 `scripts/check_consistency.py` 和 CI 强制校验。

## 步骤

1. **改版本号**（三处）+ 在 `CHANGELOG.md` 顶部补一节。

2. **本地自检**：

   ```bash
   python scripts/check_consistency.py
   ruff check .
   python -m pytest -q tests/test_client_unit.py
   python homeassistant/tests/test_e2e.py     # 需安装 homeassistant
   ```

3. **提交并推送**：

   ```bash
   git add -A && git commit -m "release: 1.3.1"
   git push origin main
   ```

4. **打 tag**（脚本会先跑一遍自检）：

   ```bash
   bash scripts/release.sh --dry-run   # 先看一遍
   bash scripts/release.sh
   git push origin v1.3.1
   ```

5. **发 Release**（网页操作，不需要 gh CLI）：

   - 打开 <https://github.com/gn0451/bull-moshome/releases/new>
   - 选择刚推的 tag `v1.3.1`
   - 标题填 `v1.3.1`
   - 描述粘贴 `CHANGELOG.md` 里对应那一节
   - 点 **Publish release**

6. **验证**：HACS → 集成 → Bull MosHome，应显示版本号；已安装用户会在 HACS 里看到更新提示。

## 回滚

```bash
# 删远端 tag
git push origin :refs/tags/v1.3.1
# 删本地 tag
git tag -d v1.3.1
```

如果 Release 已经发布，还要在网页上删除该 Release。**已安装用户的版本不会自动回退**，
需要他们手动在 HACS 里选择旧版本重新下载。

## 什么时候该发版

- 新增设备支持（改 `device_profiles.json`）
- 修复影响使用的 bug
- 协议变更（如 App 版本升级导致签名失效）

纯文档修改不需要发版。
