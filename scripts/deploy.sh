#!/usr/bin/env bash

# Commit the current workspace and deploy the exact commit to EngHub production.
# Usage: ./deploy.sh "fix: describe the change"

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_HOST="${DEPLOY_HOST:-eric@100.96.188.77}"
REMOTE_DIR="${REMOTE_DIR:-/home/eric/enghub}"
CONTAINER="${CONTAINER:-enghub}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:18888/health}"
CHECK_ONLY=false
if [[ "${1:-}" == "--check" ]]; then
  CHECK_ONLY=true
  shift
fi
COMMIT_MESSAGE="${1:-deploy: $(date '+%Y-%m-%d %H:%M:%S')}"
RELEASE_DIR=""
ARCHIVE=""
FRONTEND_ARCHIVE=""

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok() { printf '\033[1;32mOK\033[0m  %s\n' "$*"; }
fail() { printf '\033[1;31mERROR\033[0m %s\n' "$*" >&2; exit 1; }

cleanup() {
  [[ -n "$ARCHIVE" ]] && rm -f "$ARCHIVE"
  [[ -n "$FRONTEND_ARCHIVE" ]] && rm -f "$FRONTEND_ARCHIVE"
  return 0
}
trap cleanup EXIT

for command in git npm python3 rsync ssh scp tar curl; do
  command -v "$command" >/dev/null 2>&1 || fail "缺少命令: $command"
done

cd "$ROOT_DIR"
[[ -d .git ]] || fail "请在 EngHub Git 仓库中运行"
[[ -f frontend/package.json ]] || fail "未找到 frontend/package.json"

info "检查 SSH 和生产容器"
ssh -o BatchMode=yes -o ConnectTimeout=10 "$DEPLOY_HOST" \
  "test -d '$REMOTE_DIR' && docker inspect '$CONTAINER' >/dev/null" \
  || fail "无法连接生产服务器或容器不存在"

info "检查代码格式和 Python 语法"
git diff --check
PYTHON_FILES="$(
  {
    git diff --name-only --diff-filter=ACMR HEAD -- '*.py'
    git ls-files --others --exclude-standard -- '*.py'
  } | sort -u
)"
if [[ -n "$PYTHON_FILES" ]]; then
  while IFS= read -r file; do
    [[ -z "$file" ]] || python3 -m py_compile "$file"
  done <<< "$PYTHON_FILES"
fi

info "构建前端"
npm --prefix frontend run build

if [[ "$CHECK_ONLY" == true ]]; then
  ok "部署前检查通过"
  exit 0
fi

info "提交本地更新"
git add -A
if git diff --cached --quiet; then
  ok "没有待提交变更，部署当前 HEAD"
else
  git commit -m "$COMMIT_MESSAGE"
fi

COMMIT_SHA="$(git rev-parse HEAD)"
SHORT_SHA="$(git rev-parse --short HEAD)"
ARCHIVE="$(mktemp "/tmp/enghub-source-${SHORT_SHA}.XXXXXX.tgz")"
FRONTEND_ARCHIVE="$(mktemp "/tmp/enghub-frontend-${SHORT_SHA}.XXXXXX.tgz")"
RELEASE_DIR="/tmp/enghub-release-${COMMIT_SHA}"

info "打包提交 ${SHORT_SHA}"
git archive --format=tar.gz -o "$ARCHIVE" HEAD
COPYFILE_DISABLE=1 tar -C frontend/dist -czf "$FRONTEND_ARCHIVE" .

info "上传源码和前端产物"
scp -q "$ARCHIVE" "$DEPLOY_HOST:/tmp/enghub-source-${COMMIT_SHA}.tgz"
scp -q "$FRONTEND_ARCHIVE" "$DEPLOY_HOST:/tmp/enghub-frontend-${COMMIT_SHA}.tgz"

info "更新服务器源码和容器"
ssh "$DEPLOY_HOST" bash -s -- \
  "$COMMIT_SHA" "$REMOTE_DIR" "$CONTAINER" "$HEALTH_URL" <<'REMOTE'
set -Eeuo pipefail

COMMIT_SHA="$1"
REMOTE_DIR="$2"
CONTAINER="$3"
HEALTH_URL="$4"
RELEASE_DIR="/tmp/enghub-release-${COMMIT_SHA}"
SOURCE_ARCHIVE="/tmp/enghub-source-${COMMIT_SHA}.tgz"
FRONTEND_ARCHIVE="/tmp/enghub-frontend-${COMMIT_SHA}.tgz"

cleanup() {
  rm -rf "$RELEASE_DIR" "$SOURCE_ARCHIVE" "$FRONTEND_ARCHIVE"
}
trap cleanup EXIT

mkdir -p "$RELEASE_DIR/source" "$RELEASE_DIR/frontend_dist"
tar -xzf "$SOURCE_ARCHIVE" -C "$RELEASE_DIR/source"
tar -xzf "$FRONTEND_ARCHIVE" -C "$RELEASE_DIR/frontend_dist"

# Keep the server checkout useful for inspection without touching its .git or secrets.
for dir in api core database integrations scripts frontend/src; do
  if [[ -d "$RELEASE_DIR/source/$dir" ]]; then
    mkdir -p "$REMOTE_DIR/$dir"
    rsync -a --delete "$RELEASE_DIR/source/$dir/" "$REMOTE_DIR/$dir/"
  fi
done
for file in main.py requirements.txt frontend/package.json frontend/package-lock.json; do
  if [[ -f "$RELEASE_DIR/source/$file" ]]; then
    mkdir -p "$REMOTE_DIR/$(dirname "$file")"
    cp "$RELEASE_DIR/source/$file" "$REMOTE_DIR/$file"
  fi
done

# Replace runtime code as root so deleted files cannot survive an update.
docker exec -u 0 "$CONTAINER" sh -lc \
  'rm -rf /app/api /app/core /app/database /app/integrations /app/frontend_dist'
for dir in api core database integrations; do
  docker cp "$RELEASE_DIR/source/$dir" "$CONTAINER:/app/$dir"
done
docker cp "$RELEASE_DIR/source/main.py" "$CONTAINER:/app/main.py"
docker cp "$RELEASE_DIR/frontend_dist" "$CONTAINER:/app/frontend_dist"
docker exec -u 0 "$CONTAINER" sh -lc \
  'chown -R appuser:appgroup /app/api /app/core /app/database /app/integrations /app/frontend_dist /app/main.py'

docker restart "$CONTAINER" >/dev/null

healthy=0
for _ in $(seq 1 45); do
  if curl -fsS "$HEALTH_URL" >/tmp/enghub-deploy-health.json 2>/dev/null; then
    healthy=1
    break
  fi
  sleep 1
done
[[ "$healthy" -eq 1 ]] || {
  docker logs --tail 100 "$CONTAINER" >&2
  exit 1
}

docker inspect "$CONTAINER" --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}'
cat /tmp/enghub-deploy-health.json
printf '\nasset='
curl -fsS "${HEALTH_URL%/health}/" | grep -o 'index-[A-Za-z0-9_-]*\.js' | head -1
printf '\n'
REMOTE

ok "部署完成: ${SHORT_SHA}"
printf '生产地址: %s\n' "${HEALTH_URL%/health}"
