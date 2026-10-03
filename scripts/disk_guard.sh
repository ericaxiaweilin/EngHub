#!/usr/bin/env bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# EngHub 磁盘守护（cron 每小时）
#
# 原则：只清"明确的临时物"，绝不碰数据资产。
#   会清：/dev/shm 里过期的 EngHub 临时目录、/tmp 的 EngHub 发布中间包、
#         docker 无引用构建缓存（不碰镜像、不碰卷）
#   绝不：pg_dump / 部署备份（回滚保险）、docker image prune -a（里面是
#         其它项目停机待用的本地构建镜像）、任何数据库文件
# 日志放内存盘（tmpfs），磁盘上只留一行状态快照，重启后仍能看到最新结论。
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
set -uo pipefail

WARN_FREE_PCT="${WARN_FREE_PCT:-15}"   # 空闲低于 15% 告警
CRIT_FREE_PCT="${CRIT_FREE_PCT:-8}"    # 空闲低于 8% 开始自动清理
SHM_SCRATCH="/dev/shm/enghub_scratch"
SHM_LOG="/dev/shm/enghub_disk_guard.log"
STATE_FILE="/home/eric/.enghub_disk_guard_state"   # 仓库外，避免把工作区弄脏
SCRATCH_KEEP_DAYS="${SCRATCH_KEEP_DAYS:-1}"

free_pct() { echo $(( 100 - $(df --output=pcent / | tail -1 | tr -dc '0-9') )); }
log() { printf '%s %s\n' "$(date '+%F %T')" "$*" >> "$SHM_LOG"; }

mkdir -p "$SHM_SCRATCH"
# tmpfs 也算资源（撑爆会影响在跑的模型服务），限制日志体量
if [[ -f "$SHM_LOG" ]] && (( $(stat -c%s "$SHM_LOG") > 8 * 1048576 )); then
  tail -n 2000 "$SHM_LOG" > "$SHM_LOG.tmp" && mv "$SHM_LOG.tmp" "$SHM_LOG"
fi

FREE=$(free_pct)
ACTION=none
log "root free ${FREE}% (warn<${WARN_FREE_PCT}% crit<${CRIT_FREE_PCT}%)"

if (( FREE < CRIT_FREE_PCT )); then
  # 1) EngHub 自己的过期临时物
  find "$SHM_SCRATCH" -mindepth 1 -maxdepth 1 -mtime "+${SCRATCH_KEEP_DAYS}" -exec rm -rf {} + 2>/dev/null
  rm -f /tmp/enghub-source-*.tgz /tmp/enghub-frontend-*.tgz 2>/dev/null
  rm -rf /dev/shm/enghub_release_* 2>/dev/null
  ACTION=scratch_cleaned
  FREE=$(free_pct)

  # 2) 仍然紧张才动 docker 构建缓存
  if (( FREE < CRIT_FREE_PCT )); then
    BEFORE=$(df -B1 --output=avail / | tail -1)
    docker builder prune -f >> "$SHM_LOG" 2>&1
    AFTER=$(df -B1 --output=avail / | tail -1)
    log "builder prune 释放 $(( (AFTER - BEFORE) / 1073741824 )) GB"
    ACTION=builder_pruned
    FREE=$(free_pct)
  fi

  if (( FREE < CRIT_FREE_PCT )); then
    log "CRITICAL 空闲仍仅 ${FREE}%：备份与项目镜像需人工判断，脚本不自动删"
    ACTION=critical_need_human
  fi
elif (( FREE < WARN_FREE_PCT )); then
  log "WARN 空闲 ${FREE}%，尚未触发动作"
  ACTION=warn_only
fi

printf 'root_free=%s%% action=%s at=%s\n' "$FREE" "$ACTION" "$(date '+%F %T')" > "$STATE_FILE"
