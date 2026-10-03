#!/usr/bin/env bash
# enghub 数据库每日备份（cron 02:30，保留 KEEP_DAYS 天）
#
# 2026-10-03 变更：
# 1) 去掉双写：旧版先在 postgres 容器可写层 /tmp 落一份、再 docker cp 到宿主，
#    同一份 350MB 写两遍磁盘。现在把 pg_dump 的 stdout 直接流到宿主临时文件。
# 2) 失败必须响：旧版 pg_dump 失败时靠 set -e 静默退出，日志里没有失败标记，
#    历史上造成 09-20/09-22/09-23 等连续空窗无人发现。现在显式写 FAIL 并非零退出。
# 3) 产出先写 .part，通过校验才改正式名，避免半截文件冒充可用备份。
#
# 校验强度说明（不夸大）：宿主与容器都无法对 .part 做 pg_restore -l
# （宿主机没装 pg_restore；pg_restore 不接受 stdin），因此这里只做
# **结构级**校验：pg_dump 退出码 + PGDMP 魔数 + 体积下限。
# “可恢复性”要靠还原演练验证，那是另一件事，需要单独授权（会在库上建临时库）。
set -euo pipefail

BACKUP_DIR=/home/eric/enghub_backups/db
KEEP_DAYS="${KEEP_DAYS:-14}"
MIN_MB="${MIN_MB:-50}"
CONTAINER=docker-postgres-1
LOG=/home/eric/enghub_backups/backup.log
STAMP="$(date +%Y%m%d_%H%M%S)"
TARGET="$BACKUP_DIR/enghub_${STAMP}.dump"
PART="$BACKUP_DIR/.enghub_${STAMP}.dump.part"

mkdir -p "$BACKUP_DIR"
say() { printf '%s %s\n' "$(date '+%F %T')" "$*" | tee -a "$LOG"; }
fail() { rm -f "$PART"; say "FAIL: $*"; exit 1; }

say "backup start: enghub_${STAMP}.dump"

if ! docker exec "$CONTAINER" pg_dump -U enghub -d enghub -Fc > "$PART" 2>>"$LOG"; then
  fail "pg_dump 非零退出（历史高发点：purchase_requests 大表 COPY 时连接被终止）"
fi

[ "$(head -c 5 "$PART")" = "PGDMP" ] || fail "产出文件头不是 PGDMP custom archive"

MB=$(( $(stat -c%s "$PART") / 1048576 ))
[ "$MB" -ge "$MIN_MB" ] || fail "产出仅 ${MB}MB，低于下限 ${MIN_MB}MB，疑为截断"

mv "$PART" "$TARGET"
chmod 644 "$TARGET"
say "backup ok: enghub_${STAMP}.dump (${MB}MB, 结构校验通过)"

# 保留策略：先把待删名单写进日志再删，可审计
mapfile -t OLD < <(find "$BACKUP_DIR" -maxdepth 1 -name 'enghub_*.dump' -mtime "+${KEEP_DAYS}" | sort)
if [ "${#OLD[@]}" -gt 0 ]; then
  say "retention: 将删除 ${#OLD[@]} 份超过 ${KEEP_DAYS} 天的 dump"
  printf '  - %s\n' "${OLD[@]}" >> "$LOG"
  printf '%s\0' "${OLD[@]}" | xargs -0 rm -f
fi

say "backup done: 现存 $(find "$BACKUP_DIR" -maxdepth 1 -name 'enghub_*.dump' | wc -l) 份，合计 $(du -sh "$BACKUP_DIR" | cut -f1)"
