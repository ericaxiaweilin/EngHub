"""
MES 角色与权限定义
参考台资/大陆电子制造业组织架构设计

组织架构层级（由上到下）:
  厂长 -> 经理 -> 处长 -> 课长 -> 组长 -> 线长 -> 工程师 -> 专员 -> 操作员

权限设计原则:
  - 高层级可查看所有低层级数据（跨厂区/跨课/跨线）
  - 中层管理者仅管理本模块/本科室数据
  - 基层员工仅执行操作（报工、查看）
  - 每个角色有明确的功能权限（menu/crud/action）和数据范围（factory/workshop/line）
"""

# ============================================================
# 一、职位层级定义
# ============================================================

POSITION_LEVELS = {
    "factory_manager": 100,   # 厂长
    "manager": 200,           # 经理（生产/品质/工程/仓储/人事）
    "director": 300,          # 处长
    "section_chief": 400,     # 课长
    "team_leader": 500,       # 组长
    "line_leader": 600,       # 线长
    "engineer": 700,          # 工程师（工艺/设备/质量/PE/IE）
    "specialist": 800,        # 专员/职员
    "operator": 900,          # 操作员（一线员工）
}

# 职位中文名称
POSITION_NAMES = {
    "factory_manager": "厂长",
    "manager": "经理",
    "director": "处长",
    "section_chief": "课长",
    "team_leader": "组长",
    "line_leader": "线长",
    "engineer": "工程师",
    "specialist": "专员/职员",
    "operator": "操作员",
}

# 部门/模块代码
MODULES = {
    "work_order": "工单管理",
    "production_report": "生产报工",
    "station": "工位管理",
    "routing": "工艺路线",
    "equipment": "设备管理",
    "wms": "仓储管理",
    "qms": "质量管理",
    "pp": "生产计划",
    "cost": "成本核算",
    "hr": "人员管理",
    "simulation": "仿真引擎",
    "tms": "任务管理",
    "ai": "AI助手",
    "system": "系统管理",
}

# CRUD 动作
ACTIONS = {
    "view": "查看",
    "create": "创建",
    "edit": "编辑",
    "delete": "删除",
    "approve": "审批",
    "release": "下达",
    "start": "开工",
    "pause": "暂停",
    "resume": "恢复",
    "inbound": "待入库",
    "complete": "完工",
    "close": "关闭",
    "cancel": "取消",
    "split": "拆分",
    "confirm_report": "确认报工",
    "modify_report": "修改报工",
    "export": "导出",
    "manage": "管理（基础数据维护）",
}


# ============================================================
# 二、预定义角色（职位 + 部门组合）
# ============================================================
# 每个角色包含：
#   code: 角色编码
#   name: 显示名称
#   position: 职位层级
#   department: 所属部门（"all" 表示全厂）
#   permissions: 功能权限列表 [{"module": "...", "actions": ["view", ...]}]
#   data_scope: 数据范围 {"type": "own"|"department"|"factory"|"all"}

ROLE_DEFINITIONS = [
    # ---- 厂长 ----
    {
        "code": "factory_manager",
        "name": "厂长",
        "position": "factory_manager",
        "department": "all",
        "description": "工厂最高管理者，拥有全厂所有模块的完全权限",
        "permissions": [
            {"module": m, "actions": ["view", "create", "edit", "delete", "approve", "release",
                                       "start", "complete", "cancel", "confirm_report", "modify_report",
                                       "export", "manage"]}
            for m in MODULES.keys()
        ],
        "data_scope": {"type": "all"},
    },

    # ---- 经理级 ----
    {
        "code": "production_manager",
        "name": "生产经理",
        "position": "manager",
        "department": "production",
        "description": "生产部最高负责人，管理全部生产相关模块",
        "permissions": [
            {"module": "work_order", "actions": ["view", "create", "edit", "delete", "release", "start", "pause", "resume", "inbound", "complete", "close", "cancel", "split", "export"]},
            {"module": "production_report", "actions": ["view", "create", "confirm_report", "modify_report", "export"]},
            {"module": "station", "actions": ["view", "manage"]},
            {"module": "routing", "actions": ["view", "manage"]},
            {"module": "equipment", "actions": ["view", "manage"]},
            {"module": "pp", "actions": ["view", "create", "edit", "approve", "release", "export"]},
            {"module": "cost", "actions": ["view", "export"]},
            {"module": "simulation", "actions": ["view", "export"]},
            {"module": "tms", "actions": ["view", "approve"]},
            {"module": "ai", "actions": ["view"]},
        ],
        "data_scope": {"type": "factory"},
    },

    {
        "code": "quality_manager",
        "name": "品质经理",
        "position": "manager",
        "department": "quality",
        "description": "品质部最高负责人",
        "permissions": [
            {"module": "qms", "actions": ["view", "create", "edit", "delete", "approve", "export"]},
            {"module": "defect", "actions": ["view", "create", "edit", "delete", "approve", "export"]},
            {"module": "work_order", "actions": ["view", "export"]},
            {"module": "production_report", "actions": ["view", "export"]},
            {"module": "inspection", "actions": ["view", "create", "edit", "approve", "export"]},
            {"module": "simulation", "actions": ["view", "export"]},
            {"module": "ai", "actions": ["view"]},
        ],
        "data_scope": {"type": "factory"},
    },

    {
        "code": "engineering_manager",
        "name": "工程经理",
        "position": "manager",
        "department": "engineering",
        "description": "工程部最高负责人（工艺/设备/PE/IE）",
        "permissions": [
            {"module": "routing", "actions": ["view", "create", "edit", "delete", "manage", "export"]},
            {"module": "equipment", "actions": ["view", "create", "edit", "delete", "manage", "export"]},
            {"module": "station", "actions": ["view", "create", "edit", "delete", "manage", "export"]},
            {"module": "work_order", "actions": ["view", "export"]},
            {"module": "pp", "actions": ["view", "create", "edit", "export"]},
            {"module": "simulation", "actions": ["view", "export"]},
            {"module": "ai", "actions": ["view"]},
        ],
        "data_scope": {"type": "factory"},
    },

    {
        "code": "warehouse_manager",
        "name": "仓储经理",
        "position": "manager",
        "department": "warehouse",
        "description": "仓储部最高负责人",
        "permissions": [
            {"module": "wms", "actions": ["view", "create", "edit", "delete", "approve", "export"]},
            {"module": "inventory", "actions": ["view", "create", "edit", "delete", "export"]},
            {"module": "inbound", "actions": ["view", "create", "edit", "approve", "export"]},
            {"module": "outbound", "actions": ["view", "create", "edit", "approve", "export"]},
            {"module": "work_order", "actions": ["view", "export"]},
            {"module": "ai", "actions": ["view"]},
        ],
        "data_scope": {"type": "factory"},
    },

    {
        "code": "hr_manager",
        "name": "人事经理",
        "position": "manager",
        "department": "hr",
        "description": "人事部最高负责人",
        "permissions": [
            {"module": "hr", "actions": ["view", "create", "edit", "delete", "manage", "export"]},
            {"module": "skill_matrix", "actions": ["view", "create", "edit", "delete", "manage", "export"]},
            {"module": "training", "actions": ["view", "create", "edit", "delete", "manage", "export"]},
            {"module": "work_order", "actions": ["view"]},
            {"module": "production_report", "actions": ["view"]},
            {"module": "ai", "actions": ["view"]},
        ],
        "data_scope": {"type": "factory"},
    },

    # ---- 处长级 ----
    {
        "code": "production_director",
        "name": "生产处长",
        "position": "director",
        "department": "production",
        "description": "生产处最高负责人，管理多个生产课",
        "permissions": [
            {"module": "work_order", "actions": ["view", "create", "edit", "delete", "release", "start", "pause", "resume", "inbound", "complete", "close", "cancel", "split", "export"]},
            {"module": "production_report", "actions": ["view", "create", "confirm_report", "modify_report", "export"]},
            {"module": "station", "actions": ["view", "manage"]},
            {"module": "routing", "actions": ["view", "manage"]},
            {"module": "equipment", "actions": ["view", "manage"]},
            {"module": "pp", "actions": ["view", "create", "edit", "approve", "release", "export"]},
            {"module": "cost", "actions": ["view", "export"]},
            {"module": "simulation", "actions": ["view", "export"]},
            {"module": "tms", "actions": ["view", "approve"]},
            {"module": "ai", "actions": ["view"]},
        ],
        "data_scope": {"type": "factory"},
    },

    # ---- 课长级 ----
    {
        "code": "production_section_chief",
        "name": "生产课长",
        "position": "section_chief",
        "department": "production",
        "description": "生产课长，管理本课产线和班组",
        "permissions": [
            {"module": "work_order", "actions": ["view", "create", "edit", "release", "start", "pause", "resume", "complete", "cancel", "split", "export"]},
            {"module": "production_report", "actions": ["view", "create", "confirm_report", "modify_report", "export"]},
            {"module": "station", "actions": ["view", "manage"]},
            {"module": "routing", "actions": ["view"]},
            {"module": "equipment", "actions": ["view"]},
            {"module": "pp", "actions": ["view"]},
            {"module": "tms", "actions": ["view", "approve"]},
            {"module": "ai", "actions": ["view"]},
        ],
        "data_scope": {"type": "department"},
    },

    {
        "code": "quality_section_chief",
        "name": "品质课长",
        "position": "section_chief",
        "department": "quality",
        "description": "品质课长，管理检验和不良品处理",
        "permissions": [
            {"module": "qms", "actions": ["view", "create", "edit", "delete", "approve", "export"]},
            {"module": "defect", "actions": ["view", "create", "edit", "delete", "approve", "export"]},
            {"module": "inspection", "actions": ["view", "create", "edit", "approve", "export"]},
            {"module": "work_order", "actions": ["view"]},
            {"module": "production_report", "actions": ["view"]},
            {"module": "ai", "actions": ["view"]},
        ],
        "data_scope": {"type": "department"},
    },

    {
        "code": "engineering_section_chief",
        "name": "工程课长",
        "position": "section_chief",
        "department": "engineering",
        "description": "工程课长，管理工艺路线和设备",
        "permissions": [
            {"module": "routing", "actions": ["view", "create", "edit", "delete", "manage", "export"]},
            {"module": "equipment", "actions": ["view", "create", "edit", "delete", "manage", "export"]},
            {"module": "station", "actions": ["view", "manage"]},
            {"module": "work_order", "actions": ["view"]},
            {"module": "pp", "actions": ["view", "create", "edit"]},
            {"module": "simulation", "actions": ["view"]},
            {"module": "ai", "actions": ["view"]},
        ],
        "data_scope": {"type": "department"},
    },

    {
        "code": "warehouse_section_chief",
        "name": "仓储课长",
        "position": "section_chief",
        "department": "warehouse",
        "description": "仓储课长，管理入库出库和库存",
        "permissions": [
            {"module": "wms", "actions": ["view", "create", "edit", "delete", "approve", "export"]},
            {"module": "inventory", "actions": ["view", "create", "edit", "delete", "export"]},
            {"module": "inbound", "actions": ["view", "create", "edit", "approve", "export"]},
            {"module": "outbound", "actions": ["view", "create", "edit", "approve", "export"]},
            {"module": "work_order", "actions": ["view"]},
            {"module": "ai", "actions": ["view"]},
        ],
        "data_scope": {"type": "department"},
    },

    # ---- 组长级 ----
    {
        "code": "production_team_leader",
        "name": "生产组长",
        "position": "team_leader",
        "department": "production",
        "description": "生产组长，管理特定班组的生产活动",
        "permissions": [
            {"module": "work_order", "actions": ["view", "start", "complete", "export"]},
            {"module": "production_report", "actions": ["view", "create", "confirm_report", "modify_report", "export"]},
            {"module": "station", "actions": ["view"]},
            {"module": "equipment", "actions": ["view"]},
            {"module": "tms", "actions": ["view", "approve"]},
            {"module": "ai", "actions": ["view"]},
        ],
        "data_scope": {"type": "department"},
    },

    {
        "code": "quality_team_leader",
        "name": "品质组长",
        "position": "team_leader",
        "department": "quality",
        "description": "品质组长，执行检验管理和不良品判定",
        "permissions": [
            {"module": "qms", "actions": ["view", "create", "edit", "approve"]},
            {"module": "defect", "actions": ["view", "create", "edit", "approve"]},
            {"module": "inspection", "actions": ["view", "create", "edit", "approve"]},
            {"module": "work_order", "actions": ["view"]},
            {"module": "ai", "actions": ["view"]},
        ],
        "data_scope": {"type": "department"},
    },

    # ---- 线长级 ----
    {
        "code": "line_leader",
        "name": "线长",
        "position": "line_leader",
        "department": "production",
        "description": "产线线长，管理单条产线的日常生产",
        "permissions": [
            {"module": "work_order", "actions": ["view", "start", "complete"]},
            {"module": "production_report", "actions": ["view", "create", "confirm_report", "modify_report"]},
            {"module": "station", "actions": ["view"]},
            {"module": "equipment", "actions": ["view"]},
            {"module": "ai", "actions": ["view"]},
        ],
        "data_scope": {"type": "line"},
    },

    # ---- 工程师级 ----
    {
        "code": "process_engineer",
        "name": "工艺工程师",
        "position": "engineer",
        "department": "engineering",
        "description": "工艺工程师，维护工艺路线和参数",
        "permissions": [
            {"module": "routing", "actions": ["view", "create", "edit", "delete", "manage"]},
            {"module": "work_order", "actions": ["view"]},
            {"module": "production_report", "actions": ["view"]},
            {"module": "station", "actions": ["view"]},
            {"module": "simulation", "actions": ["view"]},
            {"module": "ai", "actions": ["view"]},
        ],
        "data_scope": {"type": "department"},
    },

    {
        "code": "equipment_engineer",
        "name": "设备工程师",
        "position": "engineer",
        "department": "engineering",
        "description": "设备工程师，管理设备维护和状态",
        "permissions": [
            {"module": "equipment", "actions": ["view", "create", "edit", "delete", "manage"]},
            {"module": "station", "actions": ["view", "manage"]},
            {"module": "work_order", "actions": ["view"]},
            {"module": "production_report", "actions": ["view"]},
            {"module": "ai", "actions": ["view"]},
        ],
        "data_scope": {"type": "department"},
    },

    {
        "code": "quality_engineer",
        "name": "质量工程师",
        "position": "engineer",
        "department": "quality",
        "description": "质量工程师，执行检验和分析",
        "permissions": [
            {"module": "qms", "actions": ["view", "create", "edit", "approve"]},
            {"module": "defect", "actions": ["view", "create", "edit", "approve"]},
            {"module": "inspection", "actions": ["view", "create", "edit", "approve"]},
            {"module": "work_order", "actions": ["view"]},
            {"module": "production_report", "actions": ["view"]},
            {"module": "ai", "actions": ["view"]},
        ],
        "data_scope": {"type": "department"},
    },

    {
        "code": "pe_engineer",
        "name": "PE工程师",
        "position": "engineer",
        "department": "engineering",
        "description": "生产工程师，协助生产计划和产能分析",
        "permissions": [
            {"module": "pp", "actions": ["view", "create", "edit", "export"]},
            {"module": "work_order", "actions": ["view", "create", "edit"]},
            {"module": "production_report", "actions": ["view", "export"]},
            {"module": "station", "actions": ["view"]},
            {"module": "equipment", "actions": ["view"]},
            {"module": "simulation", "actions": ["view"]},
            {"module": "ai", "actions": ["view"]},
        ],
        "data_scope": {"type": "department"},
    },

    {
        "code": "ie_engineer",
        "name": "IE工程师",
        "position": "engineer",
        "department": "engineering",
        "description": "工业工程师，产能分析和效率改善",
        "permissions": [
            {"module": "pp", "actions": ["view", "export"]},
            {"module": "work_order", "actions": ["view", "create", "edit", "export"]},
            {"module": "production_report", "actions": ["view", "export"]},
            {"module": "station", "actions": ["view", "manage"]},
            {"module": "simulation", "actions": ["view", "export"]},
            {"module": "ai", "actions": ["view"]},
        ],
        "data_scope": {"type": "department"},
    },

    # ---- 专员/职员级 ----
    {
        "code": "production_specialist",
        "name": "生产专员",
        "position": "specialist",
        "department": "production",
        "description": "生产专员，处理生产行政事务",
        "permissions": [
            {"module": "work_order", "actions": ["view", "export"]},
            {"module": "production_report", "actions": ["view", "create", "export"]},
            {"module": "pp", "actions": ["view"]},
            {"module": "ai", "actions": ["view"]},
        ],
        "data_scope": {"type": "department"},
    },

    {
        "code": "warehouse_specialist",
        "name": "仓储专员",
        "position": "specialist",
        "department": "warehouse",
        "description": "仓储专员，处理出入库事务",
        "permissions": [
            {"module": "wms", "actions": ["view", "create", "edit", "approve"]},
            {"module": "inventory", "actions": ["view", "create", "edit", "export"]},
            {"module": "inbound", "actions": ["view", "create", "edit", "approve"]},
            {"module": "outbound", "actions": ["view", "create", "edit", "approve"]},
            {"module": "ai", "actions": ["view"]},
        ],
        "data_scope": {"type": "department"},
    },

    {
        "code": "quality_specialist",
        "name": "品质专员",
        "position": "specialist",
        "department": "quality",
        "description": "品质专员，检验记录和数据分析",
        "permissions": [
            {"module": "qms", "actions": ["view", "create", "edit"]},
            {"module": "defect", "actions": ["view", "create", "edit"]},
            {"module": "inspection", "actions": ["view", "create", "edit"]},
            {"module": "work_order", "actions": ["view"]},
            {"module": "ai", "actions": ["view"]},
        ],
        "data_scope": {"type": "department"},
    },

    {
        "code": "hr_specialist",
        "name": "人事专员",
        "position": "specialist",
        "department": "hr",
        "description": "人事专员，员工技能和培训管理",
        "permissions": [
            {"module": "hr", "actions": ["view", "create", "edit", "delete", "manage"]},
            {"module": "skill_matrix", "actions": ["view", "create", "edit", "delete", "manage"]},
            {"module": "training", "actions": ["view", "create", "edit", "delete", "manage"]},
            {"module": "ai", "actions": ["view"]},
        ],
        "data_scope": {"type": "department"},
    },

    # ---- 操作员级 ----
    {
        "code": "operator",
        "name": "操作员",
        "position": "operator",
        "department": "production",
        "description": "一线操作员，仅能报工和查看自己的工单",
        "permissions": [
            {"module": "work_order", "actions": ["view"]},
            {"module": "production_report", "actions": ["view", "create"]},
            {"module": "ai", "actions": ["view"]},
        ],
        "data_scope": {"type": "own"},
    },

    {
        "code": "inspector",
        "name": "检验员",
        "position": "operator",
        "department": "quality",
        "description": "质检员，执行检验操作",
        "permissions": [
            {"module": "qms", "actions": ["view", "create"]},
            {"module": "inspection", "actions": ["view", "create", "edit"]},
            {"module": "defect", "actions": ["view", "create"]},
            {"module": "work_order", "actions": ["view"]},
            {"module": "ai", "actions": ["view"]},
        ],
        "data_scope": {"type": "own"},
    },

    {
        "code": "warehouse_operator",
        "name": "仓管员",
        "position": "operator",
        "department": "warehouse",
        "description": "仓库操作员，执行出入库操作",
        "permissions": [
            {"module": "wms", "actions": ["view", "create", "edit"]},
            {"module": "inventory", "actions": ["view", "create", "edit"]},
            {"module": "inbound", "actions": ["view", "create", "edit"]},
            {"module": "outbound", "actions": ["view", "create", "edit"]},
            {"module": "ai", "actions": ["view"]},
        ],
        "data_scope": {"type": "own"},
    },
]


# ============================================================
# 三、系统内置角色（非业务角色）
# ============================================================

SYSTEM_ROLES = {
    "admin": {
        "name": "系统管理员",
        "position": "factory_manager",
        "department": "all",
        "description": "超级管理员，拥有系统全部权限，包括用户和角色管理",
        "is_system": True,
        "permissions": "__all__",  # 特殊标记：所有权限
        "data_scope": {"type": "all"},
    },
}


# ============================================================
# 四、辅助函数
# ============================================================

def get_role_by_code(code: str):
    """根据角色编码获取角色定义"""
    for role in ROLE_DEFINITIONS:
        if role["code"] == code:
            return role
    if code in SYSTEM_ROLES:
        return SYSTEM_ROLES[code]
    return None


def get_all_roles():
    """获取所有角色定义（含系统角色）"""
    return ROLE_DEFINITIONS + list(SYSTEM_ROLES.values())


def get_positions():
    """获取所有职位层级（按层级排序）"""
    return sorted(POSITION_LEVELS.items(), key=lambda x: x[1])


def has_permission(user_permissions, module: str, action: str) -> bool:
    """
    检查用户是否有指定模块的操作权限
            {"module": "work_order", "actions": ["view"]}
    """
    for perm in user_permissions:
        if perm.get("module") == module:
            return action in perm.get("actions", [])
    return False


def get_user_permissions(user) -> list:
    """从用户对象中提取权限列表"""
    role_code = getattr(user, "role", None)
    if not role_code:
        return []

    # 系统管理员 / 超管
    if getattr(user, "is_superuser", False) or role_code == "admin":
        return [{"module": m, "actions": list(ACTIONS.keys())} for m in MODULES.keys()]

    role_def = get_role_by_code(role_code)
    if not role_def:
        return []

    return role_def.get("permissions", [])


def get_user_data_scope(user) -> dict:
    """获取用户的数据范围"""
    role_code = getattr(user, "role", None)
    if not role_code:
        return {"type": "own"}

    if getattr(user, "is_superuser", False) or role_code == "admin":
        return {"type": "all"}

    role_def = get_role_by_code(role_code)
    if not role_def:
        return {"type": "own"}

    return role_def.get("data_scope", {"type": "own"})


def get_menu_items_for_user(user) -> list:
    """根据用户角色生成可见菜单项"""
    user_perms = get_user_permissions(user)
    modules_with_access = set(p["module"] for p in user_perms)

    items = []

    # 看板组（二级菜单）- 所有人可见，仅展示真实生产数据（仿真结果不属于看板数据源，在「仿真引擎」中查看）
    # 生产看板 = KPI 概览（人机料法环）；生产数据 = 生产全过程分析（工单/报工/设备/人员）
    items.append({
        "key": "g-dashboard",
        "label": "看板",
        "children": [
            {"key": "/dashboard", "label": "生产看板"},
            {"key": "/production-data", "label": "生产数据"},
        ],
    })

    # 生产制造组
    if any(m in modules_with_access for m in ["work_order", "production_report", "station", "routing", "equipment"]):
        children = []
        if "work_order" in modules_with_access:
            children.append({"key": "/work-orders", "label": "工单管理"})
        if "production_report" in modules_with_access:
            children.append({"key": "/production-report", "label": "生产报工"})
        if any(m in modules_with_access for m in ["station", "routing", "equipment"]):
            children.append({"key": "/base-data", "label": "工位/工艺/设备"})
        if children:
            items.append({
                "key": "g-mfg",
                "label": "生产制造",
                "children": children,
            })

    # 计划物料组
    if any(m in modules_with_access for m in ["pp", "wms", "inventory", "inbound", "outbound"]):
        children = []
        if "pp" in modules_with_access:
            children.append({"key": "/plans", "label": "生产计划"})
        if any(m in modules_with_access for m in ["inventory", "wms"]):
            children.append({"key": "/inventory", "label": "库存管理"})
        if any(m in modules_with_access for m in ["wms", "inbound", "outbound"]):
            children.append({"key": "/warehouses", "label": "仓库管理"})
        if children:
            items.append({
                "key": "g-plan",
                "label": "计划物料",
                "children": children,
            })

    # 质量管理组
    if any(m in modules_with_access for m in ["qms", "defect", "inspection"]):
        children = []
        if "inspection" in modules_with_access or "qms" in modules_with_access:
            children.append({"key": "/inspections", "label": "检验管理"})
        if "defect" in modules_with_access or "qms" in modules_with_access:
            children.append({"key": "/defects", "label": "不良品"})
        if children:
            items.append({
                "key": "g-qms",
                "label": "质量管理",
                "children": children,
            })

    # 人员管理组
    if any(m in modules_with_access for m in ["hr", "skill_matrix", "training"]):
        children = []
        if "skill_matrix" in modules_with_access or "hr" in modules_with_access:
            children.append({"key": "/skill-matrix", "label": "员工技能矩阵"})
        if children:
            items.append({
                "key": "g-hr",
                "label": "人员",
                "children": children,
            })

    # 仿真引擎
    if "simulation" in modules_with_access:
        items.append({
            "key": "/simulation",
            "label": "仿真引擎",
        })

    # TMS 任务管理
    if "tms" in modules_with_access:
        children = []
        if "tms" in modules_with_access:
            children.append({"key": "/tms/approval", "label": "审批中心"})
            children.append({"key": "/tms/distribution", "label": "分发看板"})
            children.append({"key": "/tms/agent", "label": "Agent控制台"})
        if children:
            items.append({
                "key": "g-tms",
                "label": "TMS 任务管理",
                "children": children,
            })

    # v2.5 - Andon 智能工单
    if "andon" in modules_with_access or getattr(user, "is_superuser", False):
        items.append({
            "key": "/andon",
            "label": "安灯小工单",
            "module": "andon",
        })

    # v2.5 - 程序工单模板
    if "work_order_template" in modules_with_access or getattr(user, "is_superuser", False):
        items.append({
            "key": "/work-order-templates",
            "label": "程序工单模板",
            "module": "work_order_template",
        })

    # v2.5 - 数据一致性
    if "reconciliation" in modules_with_access or "traceability" in modules_with_access or "replenishment" in modules_with_access or getattr(user, "is_superuser", False):
        items.append({
            "key": "/data-consistency",
            "label": "数据一致性",
            "module": "reconciliation",
        })

    # v2.5 - 快速工单（所有角色可见）
    items.append({
        "key": "/quick-request",
        "label": "快速工单",
        "module": "quick_request",
    })

    return items


# ============================================================
# 五、默认角色快速映射（用于初始化）
# ============================================================
# 简化版：常见职位 -> 角色编码映射

DEFAULT_ROLE_MAP = {
    # 高层
    "厂长": "factory_manager",
    "总经理": "factory_manager",
    "副总": "factory_manager",

    # 经理
    "生产经理": "production_manager",
    "品质经理": "quality_manager",
    "工程经理": "engineering_manager",
    "仓储经理": "warehouse_manager",
    "人事经理": "hr_manager",

    # 处长
    "生产处长": "production_director",

    # 课长
    "生产课长": "production_section_chief",
    "品质课长": "quality_section_chief",
    "工程课长": "engineering_section_chief",
    "仓储课长": "warehouse_section_chief",

    # 组长
    "生产组长": "production_team_leader",
    "品质组长": "quality_team_leader",

    # 线长
    "线长": "line_leader",
    "拉长": "line_leader",

    # 工程师
    "工艺工程师": "process_engineer",
    "设备工程师": "equipment_engineer",
    "质量工程师": "quality_engineer",
    "PE工程师": "pe_engineer",
    "IE工程师": "ie_engineer",

    # 专员
    "生产专员": "production_specialist",
    "仓储专员": "warehouse_specialist",
    "品质专员": "quality_specialist",
    "人事专员": "hr_specialist",

    # 操作员
    "操作员": "operator",
    "普工": "operator",
    "作业员": "operator",
    "检验员": "inspector",
    "QC": "inspector",
    "QA": "quality_team_leader",
    "仓管员": "warehouse_operator",
}
