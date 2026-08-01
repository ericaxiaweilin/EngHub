#!/usr/bin/env bash

# Commit the current workspace and deploy the exact commit to EngHub production.
# Usage: ./deploy.sh "fix: describe the change"

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_HOST="${DEPLOY_HOST:-eric@100.96.188.77}"
REMOTE_DIR="${REMOTE_DIR:-/home/eric/enghub}"
CONTAINER="${CONTAINER:-docker-backend-1}"
DB_CONTAINER="${DB_CONTAINER:-docker-postgres-1}"
DB_USER="${DB_USER:-enghub}"
DB_NAME="${DB_NAME:-enghub}"
DEPLOY_BASE_SHA="${DEPLOY_BASE_SHA:-}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:18888/health}"
PUBLIC_URL="${PUBLIC_URL:-http://${DEPLOY_HOST#*@}:18888}"
CHECK_ONLY=false
if [[ "${1:-}" == "--check" ]]; then
  CHECK_ONLY=true
  shift
fi
COMMIT_MESSAGE="${1:-deploy: $(date '+%Y-%m-%d %H:%M:%S')}"
RELEASE_DIR=""
ARCHIVE=""
FRONTEND_ARCHIVE=""
MANIFEST=""

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok() { printf '\033[1;32mOK\033[0m  %s\n' "$*"; }
fail() { printf '\033[1;31mERROR\033[0m %s\n' "$*" >&2; exit 1; }

cleanup() {
  [[ -n "$ARCHIVE" ]] && rm -f "$ARCHIVE"
  [[ -n "$FRONTEND_ARCHIVE" ]] && rm -f "$FRONTEND_ARCHIVE"
  [[ -n "$MANIFEST" ]] && rm -f "$MANIFEST"
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
    [[ -z "$file" ]] && continue
    case "$(basename "$file")" in
      *" 2"*) continue ;;
    esac
    python3 -m py_compile "$file"
  done <<< "$PYTHON_FILES"
fi

info "构建前端"
npm --prefix frontend run build

if [[ "$CHECK_ONLY" == true ]]; then
  ok "部署前检查通过"
  exit 0
fi

info "提交本地更新"
git add -u
while IFS= read -r -d '' file; do
  case "$(basename "$file")" in
    *" 2"*) info "跳过重复文件: $file" ;;
    *) git add -- "$file" ;;
  esac
done < <(git ls-files --others --exclude-standard -z)
if git diff --cached --quiet; then
  ok "没有待提交变更，部署当前 HEAD"
else
  git commit -m "$COMMIT_MESSAGE"
fi

COMMIT_SHA="$(git rev-parse HEAD)"
SHORT_SHA="$(git rev-parse --short HEAD)"
BASE_SHA="${DEPLOY_BASE_SHA:-$(ssh "$DEPLOY_HOST" "cat '$REMOTE_DIR/.last_deployed_commit' 2>/dev/null || true")}"
if [[ -z "$BASE_SHA" ]] || ! git cat-file -e "${BASE_SHA}^{commit}" 2>/dev/null; then
  BASE_SHA="$(git rev-parse "${COMMIT_SHA}^" 2>/dev/null || printf '%s' "$COMMIT_SHA")"
fi
ARCHIVE="$(mktemp "/tmp/enghub-source-${SHORT_SHA}.XXXXXX.tgz")"
FRONTEND_ARCHIVE="$(mktemp "/tmp/enghub-frontend-${SHORT_SHA}.XXXXXX.tgz")"
MANIFEST="$(mktemp "/tmp/enghub-manifest-${SHORT_SHA}.XXXXXX.txt")"
RELEASE_DIR="/tmp/enghub-release-${COMMIT_SHA}"

info "打包提交 ${SHORT_SHA}（基线 ${BASE_SHA:0:7}）"
git archive --format=tar.gz -o "$ARCHIVE" HEAD
COPYFILE_DISABLE=1 tar --no-xattrs -C frontend/dist -czf "$FRONTEND_ARCHIVE" .
git diff --name-status "$BASE_SHA" "$COMMIT_SHA" > "$MANIFEST"

info "上传源码和前端产物"
scp -q "$ARCHIVE" "$DEPLOY_HOST:/tmp/enghub-source-${COMMIT_SHA}.tgz"
scp -q "$FRONTEND_ARCHIVE" "$DEPLOY_HOST:/tmp/enghub-frontend-${COMMIT_SHA}.tgz"
scp -q "$MANIFEST" "$DEPLOY_HOST:/tmp/enghub-manifest-${COMMIT_SHA}.txt"

info "更新服务器源码和容器"
ssh "$DEPLOY_HOST" bash -s -- \
  "$COMMIT_SHA" "$REMOTE_DIR" "$CONTAINER" "$HEALTH_URL" \
  "$DB_CONTAINER" "$DB_USER" "$DB_NAME" <<'REMOTE'
set -Eeuo pipefail

COMMIT_SHA="$1"
REMOTE_DIR="$2"
CONTAINER="$3"
HEALTH_URL="$4"
DB_CONTAINER="$5"
DB_USER="$6"
DB_NAME="$7"
RELEASE_DIR="/tmp/enghub-release-${COMMIT_SHA}"
SOURCE_ARCHIVE="/tmp/enghub-source-${COMMIT_SHA}.tgz"
FRONTEND_ARCHIVE="/tmp/enghub-frontend-${COMMIT_SHA}.tgz"
MANIFEST="/tmp/enghub-manifest-${COMMIT_SHA}.txt"

cleanup() {
  rm -rf "$RELEASE_DIR" "$SOURCE_ARCHIVE" "$FRONTEND_ARCHIVE" "$MANIFEST"
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

# Volume 挂载模式：代码目录直接从宿主机映射进容器，无需 docker cp
# 只需确保权限正确（容器以 appuser 运行）
chmod -R 755 "$REMOTE_DIR/api" "$REMOTE_DIR/core" "$REMOTE_DIR/database" "$REMOTE_DIR/integrations" 2>/dev/null || true
chmod 644 "$REMOTE_DIR/main.py" 2>/dev/null || true

while IFS=$'\t' read -r status path extra; do
  [[ -z "$status" || -z "$path" ]] && continue
  case "$status" in
    R*) path="$extra" ;;
  esac
  case "$path" in
    *" 2."*)
      # Skip duplicate " 2" copies (Finder artifacts); they are not real sources.
      continue
      ;;
    requirements*.txt)
      echo "依赖文件已变化，热部署不支持；请先构建新镜像。" >&2
      exit 1
      ;;
    database/migrations/*.sql)
      echo "应用数据库迁移: $path"
      docker exec -i "$DB_CONTAINER" psql -v ON_ERROR_STOP=1 \
        -U "$DB_USER" -d "$DB_NAME" < "$RELEASE_DIR/source/$path"
      ;;
    database/schema_contract.json)
      continue
      ;;
    api/*|core/*|database/*.py|integrations/*|main.py)
      # Volume 挂载模式下文件已同步到宿主机，无需 docker cp
      # 仅处理删除操作（从宿主机移除）
      if [[ "$status" == D* ]]; then
        rm -f "$REMOTE_DIR/$path"
      fi
      ;;
  esac
done < "$MANIFEST"

# 前端产物直接写入 volume 挂载目录
rm -rf "$REMOTE_DIR/frontend_dist"
mkdir -p "$REMOTE_DIR/frontend_dist"
cp -r "$RELEASE_DIR/frontend_dist/." "$REMOTE_DIR/frontend_dist/"
chmod -R 755 "$REMOTE_DIR/frontend_dist"

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
printf '%s\n' "$COMMIT_SHA" > "$REMOTE_DIR/.last_deployed_commit"
REMOTE

ok "部署完成: ${SHORT_SHA}"
printf '生产地址: %s\n' "$PUBLIC_URL"

# ━━━ 部署后验证（表/列/数据/API 缺失则失败）━━━
info "运行部署验证 checklist"
if ssh "$DEPLOY_HOST" "bash '$REMOTE_DIR/scripts/deploy_verify.sh'"; then
  ok "部署验证通过 ✓"
else
  fail "部署验证失败！请检查上方输出并修复。"
fi
