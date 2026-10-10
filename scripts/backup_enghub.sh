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
# 校验强度说明（2026-10-10 改正）：原来这段写着"宿主与容器都无法对 .part 做 pg_restore -l
# （pg_restore 不接受 stdin）"——**那是没试对**：`docker exec -i` 喂 stdin 是通的（本轮实测
# 用它数出 253 个 TABLE DATA 段）。所以校验从"魔数 + 体积下限"升级成"魔数 + 段数 + 与上一份的比值"。
# 为什么必须升级：库里 purchase_requests 只剩 1,311 行活数据却占着 1.4GB 空页（10-05 vacuum 过、
# 页没还给 OS），pg_database_size 2,473MB 而完整 dump 只有 46MB —— 旧的 200MB 体积下限于是
# 把一份**完整**的备份判成截断（误杀），而真正的截断反而没人管。体积只当"别是空文件"的下限，
# 截断由 TOC 段数与上一份的比值来判。“可恢复性”仍要靠还原演练验证，那是另一件事、需要单独授权。
set -euo pipefail

BACKUP_DIR=/home/eric/enghub_backups/db
KEEP_DAYS="${KEEP_DAYS:-14}"
MIN_MB="${MIN_MB:-30}"   # 只当"别是空文件/截到大半空"的下限；截断判据在下面的 TABLE DATA 段数
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
[ "$MB" -ge "$MIN_MB" ] || fail "产出仅 ${MB}MB，低于下限 ${MIN_MB}MB"

# 两道校验各管各的事，别把它们混成"备份已验证"：
# 1) TABLE DATA 段数：抓"dump 错库 / 连了空库 / 结构缺失"。它**抓不到尾巴被截**——
#    custom 归档的 TOC 排在数据前面，实测把 45.8MB 的备份切成 40MB，
#    pg_restore --list 照样数得出 253 段（2026-10-10 自己证伪过一次，别再当保险用）。
# 2) 相对上一份的体积带：抓截断，也抓"活数据一夜少掉一大块"这种得先有人看一眼的事。
#    确属有意变小（清了一轮测试数据）就带 ALLOW_SHRINK=1 跑一次，别改脚本来路过它。
SECTIONS="$(docker exec -i "$CONTAINER" pg_restore --list < "$PART" 2>>"$LOG" | grep -c 'TABLE DATA' || true)"
[ "${SECTIONS:-0}" -ge 50 ] || fail "TOC 只有 ${SECTIONS} 个 TABLE DATA 段（本库 250+ 张表有数据），像是错库或空库"
say "校验: ${SECTIONS} 个 TABLE DATA 段（只证明结构在，不证明尾巴完整）"

PREV="$(ls -1 "$BACKUP_DIR"/enghub_*.dump 2>/dev/null | sort | tail -1)"
if [ -n "${PREV:-}" ]; then
  PREV_BYTES=$(stat -c%s "$PREV")
  NEW_BYTES=$(stat -c%s "$PART")
  MIN_BYTES=$(( PREV_BYTES * ${SIZE_MIN_PCT:-90} / 100 ))
  if [ "$NEW_BYTES" -lt "$MIN_BYTES" ] && [ "${ALLOW_SHRINK:-0}" != "1" ]; then
    fail "体积 ${MB}MB 不足上一份 $(basename "$PREV")（$(( PREV_BYTES / 1048576 ))MB）的 ${SIZE_MIN_PCT:-90}%——要么截断、要么数据被清过，先让人看一眼；确认是有意变小就带 ALLOW_SHRINK=1 重跑"
  fi
  say "体积带校验: ${MB}MB vs 上一份 $(( PREV_BYTES / 1048576 ))MB（下限 ${SIZE_MIN_PCT:-90}%$([ "${ALLOW_SHRINK:-0}" = "1" ] && echo '，本次由 ALLOW_SHRINK=1 放行')）"
fi

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
