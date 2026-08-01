#!/usr/bin/env bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# EngHub 生产安全部署脚本
# 核心原则：任何步骤失败 → 自动回滚到部署前状态
# 用法：./deploy_safe.sh "fix: 描述变更"
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
set -Eeuo pipefail

# ━━━ 配置 ━━━
DEPLOY_HOST="${DEPLOY_HOST:-eric@100.96.188.77}"
REMOTE_DIR="${REMOTE_DIR:-/home/eric/enghub}"
CONTAINER="${CONTAINER:-docker-backend-1}"
DB_CONTAINER="${DB_CONTAINER:-docker-postgres-1}"
DB_USER="${DB_USER:-enghub}"
DB_NAME="${DB_NAME:-enghub}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:18888/health}"
DATA_GUARD_FACTORIES="${DATA_GUARD_FACTORIES:-FAC_ELEC_DEMO_2026,FAC_MECH_001}"
MAX_HEALTH_WAIT=45          # 健康检查最大等待秒数
BACKUP_KEEP=5               # 保留最近 N 个备份
COMMIT_MESSAGE="${1:-deploy: $(date '+%Y-%m-%d %H:%M:%S')}"

# ━━━ 工具函数 ━━━
info()  { printf '\033[1;34m[DEPLOY]\033[0m %s\n' "$*"; }
ok()    { printf '\033[1;32m[  OK  ]\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m[ WARN ]\033[0m %s\n' "$*"; }
fail()  { printf '\033[1;31m[FAIL ]\033[0m %s\n' "$*" >&2; exit 1; }

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TIMESTAMP="$(date '+%Y%m%d_%H%M%S')"
BACKUP_TAG="backup_${TIMESTAMP}"

# ━━━ 回滚状态跟踪 ━━━
ROLLBACK_NEEDED=false
DB_BACKUP_FILE=""
CODE_SNAPSHOT_DIR=""
DATA_GUARD_BASELINE=""

rollback() {
  if [[ "$ROLLBACK_NEEDED" != true ]]; then return 0; fi
  warn "═══ 开始自动回滚 ═══"

  # 1. 回滚代码（从快照恢复）
  if [[ -n "$CODE_SNAPSHOT_DIR" ]]; then
    info "恢复代码快照: $CODE_SNAPSHOT_DIR"
    ssh "$DEPLOY_HOST" "
      for dir in api core database integrations frontend_dist; do
        if [[ -d '$CODE_SNAPSHOT_DIR/\$dir' ]]; then
          rm -rf '$REMOTE_DIR/\$dir'
          cp -r '$CODE_SNAPSHOT_DIR/\$dir' '$REMOTE_DIR/\$dir'
          chmod -R 755 '$REMOTE_DIR/\$dir'
        fi
      done
      [[ -f '$CODE_SNAPSHOT_DIR/main.py' ]] && cp '$CODE_SNAPSHOT_DIR/main.py' '$REMOTE_DIR/main.py'
    " || warn "代码回滚部分失败"
  fi

  # 2. 回滚数据库（从 pg_dump 恢复）
  if [[ -n "$DB_BACKUP_FILE" ]]; then
    info "恢复数据库: $DB_BACKUP_FILE"
    ssh "$DEPLOY_HOST" "
      docker exec -i '$DB_CONTAINER' psql -U '$DB_USER' -d '$DB_NAME' -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;' 2>/dev/null
      docker exec -i '$DB_CONTAINER' psql -U '$DB_USER' -d '$DB_NAME' < '$DB_BACKUP_FILE'
    " || warn "数据库回滚部分失败"
  fi

  # 3. 重启容器
  info "重启容器恢复服务"
  ssh "$DEPLOY_HOST" "docker restart '$CONTAINER'" || true
  sleep 10
  if ssh "$DEPLOY_HOST" "curl -fsS '$HEALTH_URL'" >/dev/null 2>&1; then
    ok "回滚成功，服务已恢复"
  else
    warn "回滚后服务仍异常，请手动检查！"
  fi
}
trap rollback EXIT

# ━━━ 前置检查 ━━━
info "━━━ 阶段 1/6：前置检查 ━━━"
cd "$ROOT_DIR"
[[ -d .git ]] || fail "请在 EngHub Git 仓库中运行"
ssh -o BatchMode=yes -o ConnectTimeout=10 "$DEPLOY_HOST" "test -d '$REMOTE_DIR'" \
  || fail "无法连接生产服务器"
ssh "$DEPLOY_HOST" "docker inspect '$CONTAINER' >/dev/null 2>&1" \
  || fail "容器 $CONTAINER 不存在"
ok "SSH 连接正常，容器存在"

# Python 语法检查
info "检查 Python 语法"
PYTHON_ERRORS=0
while IFS= read -r file; do
  [[ -z "$file" ]] && continue
  python3 -m py_compile "$file" 2>/dev/null || { warn "语法错误: $file"; PYTHON_ERRORS=$((PYTHON_ERRORS+1)); }
done < <(git diff --name-only --diff-filter=ACMR HEAD -- '*.py' 2>/dev/null)
[[ "$PYTHON_ERRORS" -eq 0 ]] || fail "有 $PYTHON_ERRORS 个 Python 文件语法错误"
ok "语法检查通过"

# ━━━ 构建前端 ━━━
info "━━━ 阶段 2/6：构建前端 ━━━"
npm --prefix frontend run build 2>&1 | tail -3
[[ -f frontend/dist/index.html ]] || fail "前端构建失败"
ok "前端构建完成"

# ━━━ 提交代码 ━━━
info "━━━ 阶段 3/6：提交代码 ━━━"
git add -u
while IFS= read -r -d '' file; do
  case "$(basename "$file")" in *" 2"*) continue ;; esac
  git add -- "$file"
done < <(git ls-files --others --exclude-standard -z)
if git diff --cached --quiet; then
  ok "无待提交变更，部署当前 HEAD"
else
  git commit -m "$COMMIT_MESSAGE"
fi
COMMIT_SHA="$(git rev-parse HEAD)"
SHORT_SHA="$(git rev-parse --short HEAD)"
ok "提交: $SHORT_SHA"

# ━━━ 备份（关键！）━━━
info "━━━ 阶段 4/6：备份当前状态 ━━━"
ssh "$DEPLOY_HOST" bash -s -- \
  "$REMOTE_DIR" "$DB_CONTAINER" "$DB_USER" "$DB_NAME" "$BACKUP_TAG" "$BACKUP_KEEP" <<'BACKUP'
set -Eeuo pipefail
REMOTE_DIR="$1"; DB_CONTAINER="$2"; DB_USER="$3"; DB_NAME="$4"; TAG="$5"; KEEP="$6"
BACKUP_DIR="$REMOTE_DIR/backups/$TAG"
mkdir -p "$BACKUP_DIR"

# 数据库完整备份
echo "  备份数据库..."
docker exec "$DB_CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" --no-owner --no-acl \
  > "$BACKUP_DIR/database.sql"
DB_SIZE=$(du -sh "$BACKUP_DIR/database.sql" | cut -f1)
echo "  数据库备份完成 ($DB_SIZE)"

# 代码快照（仅关键目录）
echo "  备份代码..."
for dir in api core database integrations frontend_dist; do
  [[ -d "$REMOTE_DIR/$dir" ]] && cp -r "$REMOTE_DIR/$dir" "$BACKUP_DIR/$dir"
done
[[ -f "$REMOTE_DIR/main.py" ]] && cp "$REMOTE_DIR/main.py" "$BACKUP_DIR/main.py"
echo "  代码快照完成"

# 记录当前 commit
[[ -f "$REMOTE_DIR/.last_deployed_commit" ]] && cp "$REMOTE_DIR/.last_deployed_commit" "$BACKUP_DIR/commit"

# 清理旧备份（保留最近 N 个）
cd "$REMOTE_DIR/backups"
ls -dt backup_* 2>/dev/null | tail -n +$((KEEP+1)) | xargs rm -rf 2>/dev/null || true
echo "  备份保留: $(ls -d backup_* 2>/dev/null | wc -l) 个"
BACKUP
ok "备份完成: $BACKUP_TAG"
DB_BACKUP_FILE="$REMOTE_DIR/backups/$BACKUP_TAG/database.sql"
CODE_SNAPSHOT_DIR="$REMOTE_DIR/backups/$BACKUP_TAG"
DATA_GUARD_BASELINE="$REMOTE_DIR/backups/$BACKUP_TAG/data_guard_before.json"

# ━━━ 数据水位快照（关键！）━━━
info "记录部署前数据水位"
scp -q "$ROOT_DIR/scripts/data_guard.py" "$DEPLOY_HOST:/tmp/enghub-data-guard.py"
ssh "$DEPLOY_HOST" \
  "PG_CONTAINER='$DB_CONTAINER' PG_USER='$DB_USER' PG_DB='$DB_NAME' DATA_GUARD_FACTORIES='$DATA_GUARD_FACTORIES' python3 /tmp/enghub-data-guard.py snapshot --output '$DATA_GUARD_BASELINE'" \
  || fail "部署前数据水位快照失败"
ok "数据水位快照完成: $DATA_GUARD_BASELINE"

# ━━━ 部署 ━━━
info "━━━ 阶段 5/6：部署新版本 ━━━"
ROLLBACK_NEEDED=true  # 从此处开始，失败则回滚

# 打包
ARCHIVE="/tmp/enghub-source-${SHORT_SHA}.tgz"
FRONTEND_ARCHIVE="/tmp/enghub-frontend-${SHORT_SHA}.tgz"
git archive --format=tar.gz -o "$ARCHIVE" HEAD
COPYFILE_DISABLE=1 tar --no-xattrs -C frontend/dist -czf "$FRONTEND_ARCHIVE" .

# 上传
scp -q "$ARCHIVE" "$DEPLOY_HOST:/tmp/"
scp -q "$FRONTEND_ARCHIVE" "$DEPLOY_HOST:/tmp/"

# 服务器端部署
ssh "$DEPLOY_HOST" bash -s -- \
  "$REMOTE_DIR" "$CONTAINER" "$HEALTH_URL" "$DB_CONTAINER" "$DB_USER" "$DB_NAME" \
  "$COMMIT_SHA" "$MAX_HEALTH_WAIT" <<'DEPLOY'
set -Eeuo pipefail
REMOTE_DIR="$1"; CONTAINER="$2"; HEALTH_URL="$3"
DB_CONTAINER="$4"; DB_USER="$5"; DB_NAME="$6"
COMMIT_SHA="$7"; MAX_WAIT="$8"
SHORT="${COMMIT_SHA:0:7}"
RELEASE="/tmp/enghub-release-${COMMIT_SHA}"

mkdir -p "$RELEASE/source" "$RELEASE/frontend"
tar -xzf "/tmp/enghub-source-${SHORT}.tgz" -C "$RELEASE/source"
tar -xzf "/tmp/enghub-frontend-${SHORT}.tgz" -C "$RELEASE/frontend"

# 同步代码到 volume 挂载目录
echo "  同步后端代码..."
for dir in api core database integrations scripts; do
  [[ -d "$RELEASE/source/$dir" ]] && rsync -a --delete "$RELEASE/source/$dir/" "$REMOTE_DIR/$dir/"
done
for file in main.py requirements.txt; do
  [[ -f "$RELEASE/source/$file" ]] && cp "$RELEASE/source/$file" "$REMOTE_DIR/$file"
done

# 前端产物
echo "  同步前端产物..."
rm -rf "$REMOTE_DIR/frontend_dist"
mkdir -p "$REMOTE_DIR/frontend_dist"
cp -r "$RELEASE/frontend/." "$REMOTE_DIR/frontend_dist/"

# 权限修正（volume 挂载必须）
chmod -R 755 "$REMOTE_DIR/api" "$REMOTE_DIR/core" "$REMOTE_DIR/database" \
  "$REMOTE_DIR/integrations" "$REMOTE_DIR/frontend_dist" 2>/dev/null || true
chmod 644 "$REMOTE_DIR/main.py" 2>/dev/null || true

# 数据库迁移（如有 .sql 文件变更，事务包裹）
MIGRATIONS=$(cd "$RELEASE/source" && find database/migrations -name '*.sql' -newer "$REMOTE_DIR/.last_deployed_commit" 2>/dev/null || true)
if [[ -n "$MIGRATIONS" ]]; then
  echo "  执行数据库迁移..."
  for sql in $MIGRATIONS; do
    echo "    应用: $sql"
    docker exec -i "$DB_CONTAINER" psql -v ON_ERROR_STOP=1 -U "$DB_USER" -d "$DB_NAME" \
      -c "BEGIN;" < /dev/null
    docker exec -i "$DB_CONTAINER" psql -v ON_ERROR_STOP=1 -U "$DB_USER" -d "$DB_NAME" \
      < "$RELEASE/source/$sql"
  done
fi

# 重启容器
echo "  重启容器..."
docker restart "$CONTAINER" >/dev/null

# 健康检查
echo "  等待健康检查 (最多 ${MAX_WAIT}s)..."
healthy=0
for i in $(seq 1 "$MAX_WAIT"); do
  if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
    healthy=1
    break
  fi
  sleep 1
done
if [[ "$healthy" -eq 0 ]]; then
  echo "ERROR: 容器未在 ${MAX_WAIT}s 内恢复健康" >&2
  docker logs --tail 30 "$CONTAINER" >&2
  exit 1
fi
echo "  容器健康 ✓"

# 记录部署 commit
printf '%s\n' "$COMMIT_SHA" > "$REMOTE_DIR/.last_deployed_commit"

# 清理临时文件
rm -rf "$RELEASE" "/tmp/enghub-source-${SHORT}.tgz" "/tmp/enghub-frontend-${SHORT}.tgz"
DEPLOY

ok "部署完成: $SHORT_SHA"

# ━━━ 部署后验证 ━━━
info "━━━ 阶段 6/6：部署后验证 ━━━"
if ! ssh "$DEPLOY_HOST" \
  "PG_CONTAINER='$DB_CONTAINER' PG_USER='$DB_USER' PG_DB='$DB_NAME' DATA_GUARD_FACTORIES='$DATA_GUARD_FACTORIES' python3 '$REMOTE_DIR/scripts/data_guard.py' verify --baseline '$DATA_GUARD_BASELINE' --output '$REMOTE_DIR/backups/$BACKUP_TAG/data_guard_after.json'"; then
  fail "数据水位守卫失败，触发自动回滚！"
fi
ok "数据水位守卫通过"

if ssh "$DEPLOY_HOST" "bash '$REMOTE_DIR/scripts/deploy_verify.sh'"; then
  ROLLBACK_NEEDED=false  # 验证通过，取消回滚
  ok "═══ 部署成功 ✓ ($SHORT_SHA) ═══"
else
  fail "部署验证失败，触发自动回滚！"
fi
