#!/bin/bash
# ============================================================
# EngHub 部署验证脚本 (Deploy Verification Checklist)
# 用法: ./scripts/deploy_verify.sh
# 在服务器上运行，或本地通过 SSH 远程执行
# 任何检查失败 → exit 1（部署应视为失败）
# ============================================================
set -uo pipefail

# ─── 配置 ───
PG_CONTAINER="${PG_CONTAINER:-docker-postgres-1}"
PG_USER="${PG_USER:-enghub}"
PG_DB="${PG_DB:-enghub}"
BACKEND_CONTAINER="${BACKEND_CONTAINER:-docker-backend-1}"
BACKEND_PORT="${BACKEND_PORT:-18888}"
FACTORY_ID="${FACTORY_ID:-FAC_ELEC_DEMO_2026}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASS=0
FAIL=0
WARN=0

pass() { echo -e "  ${GREEN}✓${NC} $1"; ((PASS++)); }
fail() { echo -e "  ${RED}✗ FAIL${NC}: $1"; ((FAIL++)); }
warn() { echo -e "  ${YELLOW}⚠ WARN${NC}: $1"; ((WARN++)); }

psql_cmd() {
    docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -t -A -c "$1" 2>/dev/null
}

echo "═══════════════════════════════════════════════════"
echo " EngHub Deploy Verification"
echo " $(date '+%Y-%m-%d %H:%M:%S')"
echo "═══════════════════════════════════════════════════"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. 容器健康检查
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "▶ [1/5] 容器状态"

STATUS=$(docker inspect --format='{{.State.Status}}' "$BACKEND_CONTAINER" 2>/dev/null || echo "missing")
if [ "$STATUS" = "running" ]; then
    pass "后端容器 $BACKEND_CONTAINER 运行中"
else
    fail "后端容器状态: $STATUS"
fi

HEALTH=$(docker inspect --format='{{.State.Health.Status}}' "$BACKEND_CONTAINER" 2>/dev/null || echo "none")
if [ "$HEALTH" = "healthy" ]; then
    pass "健康检查: healthy"
else
    warn "健康检查: $HEALTH"
fi

PG_STATUS=$(docker inspect --format='{{.State.Status}}' "$PG_CONTAINER" 2>/dev/null || echo "missing")
if [ "$PG_STATUS" = "running" ]; then
    pass "数据库容器 $PG_CONTAINER 运行中"
else
    fail "数据库容器状态: $PG_STATUS"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. 必需表存在性检查
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "▶ [2/5] 必需表检查"

REQUIRED_TABLES=(
    users factories products work_orders equipment
    hr_employees skills hr_employee_skills
    stations routings routing_steps
    inventory warehouses locations
    andon_tickets notifications
    production_reports bom_items
    departments roles permissions role_permissions user_roles
    code_tables work_order_templates
    quality_inspections defect_records
    aps_schedules aps_schedule_tasks
    routing_templates
    chat_quick_commands
    im_groups im_messages
    tms_tasks suppliers
    maintenance_orders
    shift_summaries
)

MISSING_TABLES=()
for tbl in "${REQUIRED_TABLES[@]}"; do
    EXISTS=$(psql_cmd "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='$tbl';")
    if [ "$EXISTS" = "1" ]; then
        pass "表 $tbl"
    else
        fail "表 $tbl 不存在!"
        MISSING_TABLES+=("$tbl")
    fi
done

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. 关键列检查（历史高频缺失）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "▶ [3/5] 关键列检查"

check_column() {
    local tbl=$1 col=$2
    EXISTS=$(psql_cmd "SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='$tbl' AND column_name='$col';")
    if [ "$EXISTS" = "1" ]; then
        pass "$tbl.$col"
    else
        fail "$tbl.$col 缺失!"
    fi
}

check_column users password_reset_token
check_column users last_login
check_column work_orders current_stage
check_column work_orders assigned_to
check_column work_orders wo_type
check_column notifications created_by
check_column hr_employees station
check_column hr_employees department
check_column equipment status
check_column equipment factory_id
check_column skills skill_code
check_column skills skill_name
check_column code_tables factory_id
check_column production_reports factory_id
check_column andon_tickets factory_id
check_column defect_records factory_id

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. 种子数据最低量检查
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "▶ [4/5] 种子数据检查"

check_min_rows() {
    local tbl=$1 min=$2 desc=$3
    COUNT=$(psql_cmd "SELECT count(*) FROM $tbl;" 2>/dev/null || echo "0")
    if [ "$COUNT" -ge "$min" ]; then
        pass "$desc ($tbl: ${COUNT}行)"
    else
        fail "$desc 数据不足! ($tbl: ${COUNT}行, 最低要求: ${min})"
    fi
}

check_min_rows users 1 "用户"
check_min_rows factories 1 "工厂"
check_min_rows products 1 "产品"
check_min_rows work_orders 1 "工单"
check_min_rows equipment 1 "设备"
check_min_rows hr_employees 10 "员工档案"
check_min_rows skills 5 "技能定义"
check_min_rows hr_employee_skills 10 "员工技能关联"
check_min_rows stations 5 "工位"
check_min_rows routings 1 "工艺路线"
check_min_rows warehouses 1 "仓库"
check_min_rows inventory 1 "库存"
check_min_rows departments 3 "部门"
check_min_rows roles 1 "角色"
check_min_rows code_tables 5 "码表"
check_min_rows work_order_templates 3 "工单模板"
check_min_rows routing_templates 1 "工艺模板"

if [ -f "$(dirname "$0")/data_guard.py" ]; then
    if PG_CONTAINER="$PG_CONTAINER" PG_USER="$PG_USER" PG_DB="$PG_DB" DATA_GUARD_FACTORIES="$FACTORY_ID" \
        python3 "$(dirname "$0")/data_guard.py" verify >/tmp/enghub_data_guard_verify.log 2>&1; then
        pass "数据水位守卫"
    else
        fail "数据水位守卫失败"
        sed 's/^/    /' /tmp/enghub_data_guard_verify.log
    fi
else
    warn "数据水位守卫脚本缺失"
fi

# 工厂级数据
FAC_WO=$(psql_cmd "SELECT count(*) FROM work_orders WHERE factory_id='$FACTORY_ID';")
if [ "$FAC_WO" -ge 1 ]; then
    pass "工厂 $FACTORY_ID 有工单 (${FAC_WO})"
else
    warn "工厂 $FACTORY_ID 无工单"
fi

FAC_EMP=$(psql_cmd "SELECT count(*) FROM hr_employees WHERE factory_id='$FACTORY_ID';")
if [ "$FAC_EMP" -ge 5 ]; then
    pass "工厂 $FACTORY_ID 有员工 (${FAC_EMP})"
else
    warn "工厂 $FACTORY_ID 员工不足 (${FAC_EMP})"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5. API 端点可达性
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "▶ [5/5] API 端点检查"

# 登录获取 token
LOGIN_RESP=$(curl -s -X POST "http://localhost:${BACKEND_PORT}/api/v1/auth/login" \
    -d "username=eric&password=admin123456" 2>/dev/null)
TOKEN=$(echo "$LOGIN_RESP" | python3 -c "import sys,json;print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null || echo "")

if [ -n "$TOKEN" ]; then
    pass "登录成功 (eric)"
else
    fail "登录失败! 响应: ${LOGIN_RESP:0:100}"
fi

check_api() {
    local path=$1 desc=$2
    CODE=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $TOKEN" \
        "http://localhost:${BACKEND_PORT}/api/v1/${path}" 2>/dev/null)
    if [ "$CODE" = "200" ]; then
        pass "$desc ($CODE)"
    else
        fail "$desc 返回 $CODE"
    fi
}

if [ -n "$TOKEN" ]; then
    check_api "mes/work-orders?factory_id=${FACTORY_ID}&page=1&page_size=1" "工单列表"
    check_api "equipment?factory_id=${FACTORY_ID}" "设备列表"
    check_api "hr/employees?factory_id=${FACTORY_ID}&page=1&page_size=1" "员工列表"
    check_api "wms/inventory?factory_id=${FACTORY_ID}" "库存"
    check_api "aps/schedules?factory_id=${FACTORY_ID}" "APS排程"
    check_api "qms/inspections?factory_id=${FACTORY_ID}" "质量检验"
    check_api "andon/tickets?factory_id=${FACTORY_ID}" "安灯工单"
    check_api "rcc/overview?factory_id=${FACTORY_ID}" "RCC总览"
    check_api "org-panel/org-nodes?factory_id=${FACTORY_ID}" "组织节点"
    check_api "collaboration/network?factory_id=${FACTORY_ID}" "协同网络"
    check_api "ie/standard-times?factory_id=${FACTORY_ID}&limit=1" "IE标准工时"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 汇总
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "═══════════════════════════════════════════════════"
echo -e " 结果: ${GREEN}${PASS} 通过${NC} | ${RED}${FAIL} 失败${NC} | ${YELLOW}${WARN} 警告${NC}"
echo "═══════════════════════════════════════════════════"

if [ "$FAIL" -gt 0 ]; then
    echo -e "${RED}部署验证失败！请修复上述问题后重新部署。${NC}"
    exit 1
else
    echo -e "${GREEN}部署验证通过。${NC}"
    exit 0
fi
