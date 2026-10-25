#!/usr/bin/env bash
# 打一个发布 tag。
#
# 用法:
#   bash scripts/release.sh            # 用 manifest.json 里的版本号
#   bash scripts/release.sh --dry-run  # 只检查，不打 tag
#
# 脚本只负责「自检 + 打 annotated tag」，推 tag 和发 Release 需要你手动做
# （见 RELEASING.md），避免误推到远端。
set -euo pipefail

DRY_RUN=false
[ "${1:-}" = "--dry-run" ] && DRY_RUN=true

cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-python3}"

echo "==> 1/4 一致性自检（副本同步 + 版本号统一）"
"$PYTHON" scripts/check_consistency.py

echo "==> 2/4 工作区必须干净"
if [ -n "$(git status --porcelain)" ]; then
    echo "错误: 工作区有未提交的改动，先 commit 再发版" >&2
    git status --short >&2
    exit 1
fi

echo "==> 3/4 读取版本号"
VERSION=$("$PYTHON" -c "import json;print(json.load(open('custom_components/bull/manifest.json'))['version'])")
TAG="v${VERSION}"
echo "    版本: ${VERSION}  tag: ${TAG}"

if git rev-parse "$TAG" >/dev/null 2>&1; then
    echo "错误: tag ${TAG} 已存在" >&2
    exit 1
fi

echo "==> 4/4 创建 annotated tag"
if $DRY_RUN; then
    echo "    --dry-run：跳过创建"
else
    git tag -a "$TAG" -m "Bull MosHome ${VERSION}"
    echo "    已创建 ${TAG}"
fi

cat <<EOF

下一步（手动）：

  1. 推送 tag:
       git push origin ${TAG}

  2. 发 Release（网页，2 分钟）:
       https://github.com/gn0451/bull-moshome/releases/new?tag=${TAG}
       - 标题填 ${TAG}
       - 描述粘贴 CHANGELOG.md 里 "## ${VERSION}" 这一段
       - 点 Publish release

  发完之后 HACS 才会显示版本号并推送更新提示。
EOF
