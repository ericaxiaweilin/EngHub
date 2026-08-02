#!/usr/bin/env bash

# Commit the current workspace and deploy the exact commit to EngHub production.
# Usage: ./deploy.sh "fix: describe the change"
#
# 部署守卫（任一环节失败 → 自动回滚到部署前快照）：
#   1. 血缘校验：拒绝与服务器当前上线提交无关的代码线
#   2. 部署前快照：代码目录 + frontend_dist（DEPLOY_DB_BACKUP=1 时追加 pg_dump）
#   3. 健康检查 + deploy_verify.sh 全绿才算成功，否则回滚
#
# 环境变量：
#   DEPLOY_DB_BACKUP=1        部署前额外做全量 pg_dump（默认关闭，dump 约 800MB）
#   DEPLOY_ALLOW_UNRELATED=1  跳过血缘校验（仅在明确知道要换代码线时使用）
#   BACKUP_KEEP=5             保留最近 N 份快照

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_HOST="${DEPLOY_HOST:-eric@100.96.188.77}"
REMOTE_DIR="${REMOTE_DIR:-/home/eric/enghub}"
CONTAINER="${CONTAINER:-enghub-backend-1}"
DB_CONTAINER="${DB_CONTAINER:-docker-postgres-1}"
DB_USER="${DB_USER:-enghub}"
DB_NAME="${DB_NAME:-enghub}"
DEPLOY_BASE_SHA="${DEPLOY_BASE_SHA:-}"
DEPLOY_DB_BACKUP="${DEPLOY_DB_BACKUP:-0}"
DEPLOY_ALLOW_UNRELATED="${DEPLOY_ALLOW_UNRELATED:-0}"
BACKUP_KEEP="${BACKUP_KEEP:-5}"
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
BACKUP_TAG=""
ROLLBACK_NEEDED=false

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok() { printf '\033[1;32mOK\033[0m  %s\n' "$*"; }
warn() { printf '\033[1;33mWARN\033[0m %s\n' "$*" >&2; }
fail() { printf '\033[1;31mERROR\033[0m %s\n' "$*" >&2; exit 1; }

cleanup() {
  [[ -n "$ARCHIVE" ]] && rm -f "$ARCHIVE"
  [[ -n "$FRONTEND_ARCHIVE" ]] && rm -f "$FRONTEND_ARCHIVE"
  [[ -n "$MANIFEST" ]] && rm -f "$MANIFEST"
  return 0
}

rollback() {
  [[ "$ROLLBACK_NEEDED" == true ]] || return 0
  ROLLBACK_NEEDED=false
  warn "═══ 部署失败，自动回滚到快照 ${BACKUP_TAG} ═══"
  ssh "$DEPLOY_HOST" bash -s -- \
    "$REMOTE_DIR" "$BACKUP_TAG" "$CONTAINER" "$HEALTH_URL" \
    "$DB_CONTAINER" "$DB_USER" "$DB_NAME" <<'ROLLBACK' \
    || warn "回滚过程有步骤失败，请立即人工检查生产状态"
set -Eeuo pipefail

REMOTE_DIR="$1"; TAG="$2"; CONTAINER="$3"; HEALTH_URL="$4"
DB_CONTAINER="$5"; DB_USER="$6"; DB_NAME="$7"
BACKUP_DIR="$REMOTE_DIR/backups/$TAG"

[[ -d "$BACKUP_DIR" ]] || { echo "快照不存在: $BACKUP_DIR" >&2; exit 1; }

# bind mount 目录可能被容器 root 改过属主，否则覆盖会 Permission denied
docker exec -u 0 "$CONTAINER" chown -R "$(id -u):$(id -g)" \
  /app/api /app/core /app/database /app/integrations /app/main.py /app/frontend_dist \
  >/dev/null 2>&1 || true

# 与部署改动的路径逐一对应，少一项就等于回滚不干净
for path in api core database integrations scripts frontend/src frontend_dist \
            main.py requirements.txt frontend/package.json frontend/package-lock.json; do
  [[ -e "$BACKUP_DIR/snapshot/$path" ]] || continue
  rm -rf "${REMOTE_DIR:?}/$path"
  mkdir -p "$(dirname "$REMOTE_DIR/$path")"
  cp -a "$BACKUP_DIR/snapshot/$path" "$REMOTE_DIR/$path"
  echo "已还原 $path"
done
[[ -f "$BACKUP_DIR/last_deployed_commit" ]] \
  && cp -a "$BACKUP_DIR/last_deployed_commit" "$REMOTE_DIR/.last_deployed_commit"

if [[ -f "$BACKUP_DIR/database.sql" ]]; then
  echo "还原数据库快照"
  docker exec -i "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" \
    < "$BACKUP_DIR/database.sql" >/dev/null
fi

docker restart "$CONTAINER" >/dev/null
for _ in $(seq 1 45); do
  if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
    echo "回滚完成，服务已恢复健康"
    exit 0
  fi
  sleep 1
done
echo "回滚后服务仍不健康，请立即人工介入" >&2
exit 1
ROLLBACK
}

on_exit() {
  local status=$?
  [[ "$status" -eq 0 ]] || rollback
  cleanup
  return 0
}
trap on_exit EXIT

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

# ━━━ 血缘校验：本地必须与服务器当前上线的是同一条代码线 ━━━
info "校验代码血缘"
BASE_SHA="${DEPLOY_BASE_SHA:-$(ssh "$DEPLOY_HOST" "cat '$REMOTE_DIR/.last_deployed_commit' 2>/dev/null || true")}"
BASE_SHA="$(printf '%s' "$BASE_SHA" | tr -d '[:space:]')"
LINEAGE_CHECKED=false
if [[ -z "$BASE_SHA" ]]; then
  warn "服务器没有 .last_deployed_commit，无法校验血缘"
elif git cat-file -e "${BASE_SHA}^{commit}" 2>/dev/null; then
  LINEAGE_CHECKED=true
  ok "服务器上线提交 ${BASE_SHA:0:12} 在本仓库历史中"
elif [[ "$DEPLOY_ALLOW_UNRELATED" == "1" ]]; then
  warn "服务器上线提交 ${BASE_SHA:0:12} 不在本仓库历史中，已按 DEPLOY_ALLOW_UNRELATED=1 放行"
  BASE_SHA=""
else
  fail "服务器当前上线提交 ${BASE_SHA:0:12} 不在本仓库历史中：本地与生产不是同一条代码线。
       继续部署会用另一条分支的文件整体覆盖线上模块。
       请先切到生产分支并同步（git fetch && git checkout <生产分支>），
       确认无误后再部署；确需换代码线时用 DEPLOY_ALLOW_UNRELATED=1 显式放行。"
fi

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
if [[ "$LINEAGE_CHECKED" == true ]] \
  && ! git merge-base --is-ancestor "$BASE_SHA" "$COMMIT_SHA"; then
  if [[ "$DEPLOY_ALLOW_UNRELATED" == "1" ]]; then
    warn "待部署提交不是线上提交的后代，已按 DEPLOY_ALLOW_UNRELATED=1 放行"
  else
    fail "待部署提交 ${SHORT_SHA} 不是线上提交 ${BASE_SHA:0:12} 的后代：这是一次代码回退或换线。
       请先 git merge/rebase 线上提交，或用 DEPLOY_ALLOW_UNRELATED=1 显式放行。"
  fi
fi
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

# ━━━ 部署前快照（代码必做，DB 按需）━━━
BACKUP_TAG="backup_$(date '+%Y%m%d_%H%M%S')"
info "建立部署前快照 ${BACKUP_TAG}"
BACKUP_SIZE="$(
  ssh "$DEPLOY_HOST" bash -s -- \
    "$REMOTE_DIR" "$BACKUP_TAG" "$BACKUP_KEEP" "$DEPLOY_DB_BACKUP" \
    "$DB_CONTAINER" "$DB_USER" "$DB_NAME" "$CONTAINER" <<'BACKUP'
set -Eeuo pipefail

REMOTE_DIR="$1"; TAG="$2"; KEEP="$3"; DB_BACKUP="$4"
DB_CONTAINER="$5"; DB_USER="$6"; DB_NAME="$7"; CONTAINER="$8"
BACKUP_DIR="$REMOTE_DIR/backups/$TAG"
mkdir -p "$BACKUP_DIR"

# bind mount 目录可能被容器 root 改过属主，先纠正，否则快照与回滚都会失败
docker exec -u 0 "$CONTAINER" chown -R "$(id -u):$(id -g)" \
  /app/api /app/core /app/database /app/integrations /app/main.py /app/frontend_dist \
  >/dev/null 2>&1 || true

# 快照范围必须覆盖部署会改动的每一个路径，否则回滚不干净
for path in api core database integrations scripts frontend/src frontend_dist \
            main.py requirements.txt frontend/package.json frontend/package-lock.json; do
  [[ -e "$REMOTE_DIR/$path" ]] || continue
  mkdir -p "$(dirname "$BACKUP_DIR/snapshot/$path")"
  cp -a "$REMOTE_DIR/$path" "$BACKUP_DIR/snapshot/$path"
done
[[ -f "$REMOTE_DIR/.last_deployed_commit" ]] \
  && cp -a "$REMOTE_DIR/.last_deployed_commit" "$BACKUP_DIR/last_deployed_commit"
git -C "$REMOTE_DIR" rev-parse HEAD > "$BACKUP_DIR/git_head" 2>/dev/null || true
git -C "$REMOTE_DIR" branch --show-current > "$BACKUP_DIR/git_branch" 2>/dev/null || true

if [[ "$DB_BACKUP" == "1" ]]; then
  docker exec "$DB_CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" > "$BACKUP_DIR/database.sql"
fi

cd "$REMOTE_DIR/backups"
ls -1dt backup_* 2>/dev/null | tail -n "+$((KEEP + 1))" | xargs -r rm -rf
du -sh "$BACKUP_DIR" | cut -f1
BACKUP
)" || fail "部署前快照失败，已终止（生产未被改动）"
ok "快照完成: ${BACKUP_TAG} (${BACKUP_SIZE})"
[[ "$DEPLOY_DB_BACKUP" == "1" ]] || info "未做数据库快照（需要时用 DEPLOY_DB_BACKUP=1）"

info "上传源码和前端产物"
scp -q "$ARCHIVE" "$DEPLOY_HOST:/tmp/enghub-source-${COMMIT_SHA}.tgz"
scp -q "$FRONTEND_ARCHIVE" "$DEPLOY_HOST:/tmp/enghub-frontend-${COMMIT_SHA}.tgz"
scp -q "$MANIFEST" "$DEPLOY_HOST:/tmp/enghub-manifest-${COMMIT_SHA}.txt"

# 从这里开始生产会被改动，失败一律回滚
ROLLBACK_NEEDED=true

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

# 容器重启后到模型网关的连接需要时间，不等会把竞态误判成部署失败
info "等待模型底座就绪"
ssh "$DEPLOY_HOST" bash -s -- "$HEALTH_URL" <<'WARMUP' || warn "模型底座未就绪，部署验证可能失败"
set -Eeuo pipefail
CHAT_HEALTH_URL="${1%/health}/api/v1/chat/health"
for _ in $(seq 1 60); do
  if curl -fsS --max-time 5 "$CHAT_HEALTH_URL" 2>/dev/null | grep -q '"reachable":true'; then
    echo "模型底座已就绪"
    exit 0
  fi
  sleep 2
done
echo "模型底座 120s 内仍不可达" >&2
exit 1
WARMUP

# ━━━ 部署后验证（表/列/数据/API/前端模块缺失则回滚）━━━
info "运行部署验证 checklist"
ssh "$DEPLOY_HOST" "test -f '$REMOTE_DIR/scripts/deploy_verify.sh'" \
  || fail "服务器上缺少 scripts/deploy_verify.sh，无法验证本次部署"
ssh "$DEPLOY_HOST" "bash '$REMOTE_DIR/scripts/deploy_verify.sh'" \
  || fail "部署验证失败！"
ok "部署验证通过 ✓"

ROLLBACK_NEEDED=false
ok "部署完成: ${SHORT_SHA}"
printf '生产地址: %s\n' "$PUBLIC_URL"
printf '回滚快照: %s/backups/%s\n' "$REMOTE_DIR" "$BACKUP_TAG"
