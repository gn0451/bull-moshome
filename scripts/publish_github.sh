#!/usr/bin/env bash
# 发布 bull-moshome 到 GitHub。
#
# 用法:
#   export GITHUB_TOKEN=<你的 token>        # 需要 repo 权限
#   bash scripts/publish_github.sh [仓库名] [public|private]
#
# 依赖: git、curl、python3。Token 仅通过环境变量传入，不落盘、不写入 git 配置。
set -euo pipefail

REPO_NAME="${1:-bull-moshome}"
VISIBILITY="${2:-public}"

if [ -z "${GITHUB_TOKEN:-}" ]; then
    echo "错误: 请先 export GITHUB_TOKEN=<你的 token>" >&2
    exit 1
fi

API="https://api.github.com"
AUTH="Authorization: Bearer ${GITHUB_TOKEN}"

# 1. 确认身份（只打印登录名）
LOGIN=$(curl -s -H "$AUTH" "$API/user" | python3 -c 'import json,sys; print(json.load(sys.stdin)["login"])')
echo "GitHub 账号: ${LOGIN}"

# 2. 创建仓库（已存在则跳过，保持幂等）
PRIVATE=false
[ "$VISIBILITY" = "private" ] && PRIVATE=true
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST -H "$AUTH" \
    -H "Accept: application/vnd.github+json" \
    "$API/user/repos" \
    -d "{
        \"name\": \"${REPO_NAME}\",
        \"private\": ${PRIVATE},
        \"description\": \"公牛智家云(MosHome) Python 客户端 + Home Assistant 自定义集成\",
        \"has_issues\": true,
        \"has_wiki\": false
    }")
if [ "$HTTP_CODE" = "201" ]; then
    echo "仓库已创建: ${REPO_NAME} (${VISIBILITY})"
elif [ "$HTTP_CODE" = "422" ]; then
    echo "仓库已存在，直接推送"
else
    echo "创建仓库返回 HTTP ${HTTP_CODE}" >&2
    exit 1
fi

# 3. 关联远程并推送 main
#    注意：不要把 token 拼进 remote URL —— 那会明文写进 .git/config 并留在磁盘上。
#    这里用一次性的 http.extraheader 传入，推送结束即失效。
git remote remove origin 2>/dev/null || true
git remote add origin "https://github.com/${LOGIN}/${REPO_NAME}.git"
git -c http.extraheader="Authorization: Bearer ${GITHUB_TOKEN}" \
    push -u origin main

echo ""
echo "发布完成: https://github.com/${LOGIN}/${REPO_NAME}"
