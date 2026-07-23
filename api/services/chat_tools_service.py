"""
Chatbot MES 工具服务（Tool Calling）

让 AI 助手能通过自然语言实际执行 MES 操作：
- 查询类：工单 / 库存 / 不良品 / 设备 / 工位 / 生产统计
- 操作类：创建工单 / 下达工单 / 生产报工

工具定义为 OpenAI function-calling 标准格式，执行器直连数据库。
写操作会记录操作人（当前登录用户），并返回结构化结果供前端展示。
"""

from __future__ import annotations

import uuid
from datetime import datetime, date
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from database.models import (
    WorkOrder, ProductionReport, Station, Equipment, Product,
    Inventory, DefectRecord,
)


# ==================== 工具定义（OpenAI function-calling 格式） ====================

TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "query_work_orders",
            "description": "查询生产工单列表。可按状态过滤（pending待下达/released已下达/in_progress生产中/completed已完成），返回工单号、产品、计划数量、完成进度、状态。",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["pending", "released", "in_progress", "completed", "cancelled", "on_hold"],
                        "description": "工单状态过滤，不传则返回全部",
                    },
                    "limit": {"type": "integer", "description": "返回条数，默认10", "default": 10},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_work_order_detail",
            "description": "根据工单号查询单个工单的详细信息，包含数量、良率、进度、工位、时间等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "work_order_code": {"type": "string", "description": "工单号，如 WO-20260722-001"},
                },
                "required": ["work_order_code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_production_summary",
            "description": "获取今日生产统计汇总：今日良品产出、不良数、良品率、在制工单数、设备稼动率、今日报工次数。用于回答'今天生产情况怎么样'类问题。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_inventory",
            "description": "查询库存水平。可按物料编码过滤，返回物料、仓库、总数量、可用数量。",
            "parameters": {
                "type": "object",
                "properties": {
                    "material_keyword": {"type": "string", "description": "物料编码或名称关键词，可选"},
                    "limit": {"type": "integer", "description": "返回条数，默认10", "default": 10},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_defects",
            "description": "查询不良品/缺陷记录。返回缺陷单号、类型、严重等级、数量、处置状态、根因分类。",
            "parameters": {
                "type": "object",
                "properties": {
                    "severity": {
                        "type": "string",
                        "enum": ["critical", "major", "minor"],
                        "description": "严重等级过滤，可选",
                    },
                    "limit": {"type": "integer", "description": "返回条数，默认10", "default": 10},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_equipment",
            "description": "查询设备状态列表。返回设备编码、名称、状态（running运行/available可用/fault故障/maintenance保养）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["running", "available", "fault", "maintenance", "idle"],
                        "description": "设备状态过滤，可选",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_work_order",
            "description": "创建新的生产工单。需要提供产品ID、计划数量、计划完成日期。创建成功后返回工单号。",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "string", "description": "产品ID"},
                    "planned_qty": {"type": "integer", "description": "计划生产数量"},
                    "planned_due": {"type": "string", "description": "计划完成日期，格式 YYYY-MM-DD"},
                    "priority": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "urgent"],
                        "description": "优先级，默认medium",
                        "default": "medium",
                    },
                },
                "required": ["product_id", "planned_qty", "planned_due"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "release_work_order",
            "description": "下达工单（将待下达工单释放到产线）。只有 pending 状态的工单可以下达。",
            "parameters": {
                "type": "object",
                "properties": {
                    "work_order_code": {"type": "string", "description": "工单号"},
                },
                "required": ["work_order_code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_production_report",
            "description": "生产报工：为指定工单提交一条报工记录（良品数/不良数）。报工成功后自动累加工单完成数量。",
            "parameters": {
                "type": "object",
                "properties": {
                    "work_order_id": {"type": "string", "description": "工单ID（36位UUID）"},
                    "station_id": {"type": "string", "description": "工位ID"},
                    "good_qty": {"type": "integer", "description": "良品数量"},
                    "defect_qty": {"type": "integer", "description": "不良数量，默认0", "default": 0},
                    "shift": {"type": "string", "enum": ["day", "night"], "description": "班次，默认day", "default": "day"},
                },
                "required": ["work_order_id", "station_id", "good_qty"],
            },
        },
    },
]


# ==================== 工具执行器 ====================

def _wo_to_dict(wo: WorkOrder, product_name: str = "") -> Dict[str, Any]:
    progress = round(wo.completed_qty / wo.planned_qty * 100, 1) if wo.planned_qty else 0
    return {
        "id": wo.id,
        "work_order_code": wo.work_order_code,
        "product_id": wo.product_id,
        "product_name": product_name,
        "planned_qty": wo.planned_qty,
        "completed_qty": wo.completed_qty,
        "good_qty": wo.good_qty,
        "defect_qty": wo.defect_qty,
        "progress_pct": progress,
        "status": wo.status,
        "priority": wo.priority,
        "planned_due": wo.planned_due.strftime("%Y-%m-%d") if wo.planned_due else None,
    }


async def _tool_query_work_orders(db: AsyncSession, args: Dict[str, Any]) -> Dict[str, Any]:
    limit = min(int(args.get("limit", 10)), 50)
    stmt = select(WorkOrder).order_by(WorkOrder.created_at.desc()).limit(limit)
    if args.get("status"):
        stmt = stmt.where(WorkOrder.status == args["status"])
    rows = (await db.execute(stmt)).scalars().all()

    product_ids = list({wo.product_id for wo in rows if wo.product_id})
    pname_map: Dict[str, str] = {}
    if product_ids:
        pres = await db.execute(select(Product).where(Product.id.in_(product_ids)))
        pname_map = {p.id: p.product_name for p in pres.scalars().all()}

    items = [_wo_to_dict(wo, pname_map.get(wo.product_id, "")) for wo in rows]
    return {"count": len(items), "work_orders": items}


async def _tool_get_work_order_detail(db: AsyncSession, args: Dict[str, Any]) -> Dict[str, Any]:
    code = args.get("work_order_code", "")
    stmt = select(WorkOrder).where(WorkOrder.work_order_code == code)
    wo = (await db.execute(stmt)).scalar_one_or_none()
    if not wo:
        # 模糊匹配
        stmt = select(WorkOrder).where(WorkOrder.work_order_code.ilike(f"%{code}%")).limit(1)
        wo = (await db.execute(stmt)).scalar_one_or_none()
    if not wo:
        return {"error": f"未找到工单 {code}"}

    pname = ""
    if wo.product_id:
        p = (await db.execute(select(Product).where(Product.id == wo.product_id))).scalar_one_or_none()
        pname = p.product_name if p else ""

    detail = _wo_to_dict(wo, pname)
    detail.update({
        "station_id": wo.assigned_station_id,
        "routing_step": wo.current_routing_step,
        "scrap_qty": wo.scrap_qty,
        "created_at": wo.created_at.strftime("%Y-%m-%d %H:%M") if wo.created_at else None,
        "actual_start": wo.actual_start.strftime("%Y-%m-%d %H:%M") if wo.actual_start else None,
        "remark": wo.remark,
    })
    return detail


async def _tool_get_production_summary(db: AsyncSession, args: Dict[str, Any]) -> Dict[str, Any]:
    today_start = datetime.combine(date.today(), datetime.min.time())

    # 今日报工
    rpt_stmt = select(ProductionReport).where(ProductionReport.created_at >= today_start)
    reports = (await db.execute(rpt_stmt)).scalars().all()
    today_good = sum(r.good_qty for r in reports)
    today_defect = sum(r.defect_qty for r in reports)
    total_out = today_good + today_defect
    yield_rate = round(today_good / total_out * 100, 1) if total_out else 100.0

    # 工单统计
    wo_all = (await db.execute(select(WorkOrder))).scalars().all()
    active = len([wo for wo in wo_all if wo.status == "in_progress"])
    pending = len([wo for wo in wo_all if wo.status == "pending"])

    # 设备
    eq_all = (await db.execute(select(Equipment))).scalars().all()
    running = len([e for e in eq_all if e.status == "running"])
    fault = len([e for e in eq_all if e.status == "fault"])
    utilization = round(running / len(eq_all) * 100, 1) if eq_all else 0

    return {
        "date": date.today().strftime("%Y-%m-%d"),
        "today_good_output": today_good,
        "today_defect": today_defect,
        "yield_rate_pct": yield_rate,
        "today_report_count": len(reports),
        "active_work_orders": active,
        "pending_work_orders": pending,
        "total_work_orders": len(wo_all),
        "equipment_total": len(eq_all),
        "equipment_running": running,
        "equipment_fault": fault,
        "equipment_utilization_pct": utilization,
    }


async def _tool_query_inventory(db: AsyncSession, args: Dict[str, Any]) -> Dict[str, Any]:
    limit = min(int(args.get("limit", 10)), 50)
    stmt = select(Inventory).order_by(Inventory.updated_at.desc()).limit(limit)
    kw = args.get("material_keyword")
    if kw:
        stmt = stmt.where(
            (Inventory.material_code.ilike(f"%{kw}%")) | (Inventory.material_id.ilike(f"%{kw}%"))
        )
    rows = (await db.execute(stmt)).scalars().all()
    items = [
        {
            "material_id": inv.material_id,
            "material_code": inv.material_code,
            "warehouse_id": inv.warehouse_id,
            "batch_code": inv.batch_code,
            "total_qty": inv.total_qty,
            "available_qty": inv.available_qty,
            "reserved_qty": inv.reserved_qty,
            "status": inv.status,
        }
        for inv in rows
    ]
    return {"count": len(items), "inventory": items}


async def _tool_query_defects(db: AsyncSession, args: Dict[str, Any]) -> Dict[str, Any]:
    limit = min(int(args.get("limit", 10)), 50)
    stmt = select(DefectRecord).order_by(DefectRecord.created_at.desc()).limit(limit)
    if args.get("severity"):
        stmt = stmt.where(DefectRecord.severity == args["severity"])
    rows = (await db.execute(stmt)).scalars().all()
    items = [
        {
            "record_code": d.record_code,
            "defect_type": d.defect_type,
            "severity": d.severity,
            "quantity": d.quantity,
            "disposition": d.disposition or "未处置",
            "ocap_status": d.ocap_status,
            "root_cause_category": d.root_cause_category,
            "description": (d.description or "")[:80],
            "created_at": d.created_at.strftime("%Y-%m-%d %H:%M") if d.created_at else None,
        }
        for d in rows
    ]
    return {"count": len(items), "defects": items}


async def _tool_query_equipment(db: AsyncSession, args: Dict[str, Any]) -> Dict[str, Any]:
    stmt = select(Equipment)
    if args.get("status"):
        stmt = stmt.where(Equipment.status == args["status"])
    rows = (await db.execute(stmt)).scalars().all()
    items = [
        {
            "equipment_code": e.equipment_code,
            "equipment_name": e.equipment_name,
            "equipment_type": e.equipment_type,
            "status": e.status,
            "station_id": e.station_id,
        }
        for e in rows
    ]
    return {"count": len(items), "equipment": items}


async def _tool_create_work_order(db: AsyncSession, args: Dict[str, Any], operator: str) -> Dict[str, Any]:
    product_id = args.get("product_id", "")
    planned_qty = int(args.get("planned_qty", 0))
    planned_due_str = args.get("planned_due", "")
    priority = args.get("priority", "medium")

    if planned_qty <= 0:
        return {"error": "计划数量必须大于0"}

    # 校验产品存在
    product = (await db.execute(select(Product).where(Product.id == product_id))).scalar_one_or_none()
    if not product:
        # 尝试按编码/名称模糊匹配
        product = (await db.execute(
            select(Product).where(
                (Product.product_code.ilike(f"%{product_id}%")) | (Product.product_name.ilike(f"%{product_id}%"))
            ).limit(1)
        )).scalar_one_or_none()
    if not product:
        return {"error": f"未找到产品 {product_id}，请确认产品ID或编码"}

    try:
        planned_due = datetime.strptime(planned_due_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        return {"error": f"日期格式错误：{planned_due_str}，应为 YYYY-MM-DD"}

    wo_code = f"WO-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:6].upper()}"
    wo = WorkOrder(
        id=str(uuid.uuid4()),
        work_order_code=wo_code,
        factory_id=product.factory_id,
        product_id=product.id,
        planned_qty=planned_qty,
        planned_due=planned_due,
        priority=priority,
        status="pending",
        created_by=operator,
    )
    db.add(wo)
    await db.commit()
    await db.refresh(wo)
    return {
        "success": True,
        "message": f"工单创建成功",
        "work_order_code": wo.work_order_code,
        "id": wo.id,
        "product_name": product.product_name,
        "planned_qty": planned_qty,
        "planned_due": planned_due_str,
        "status": "pending（待下达）",
    }


async def _tool_release_work_order(db: AsyncSession, args: Dict[str, Any], operator: str) -> Dict[str, Any]:
    code = args.get("work_order_code", "")
    wo = (await db.execute(select(WorkOrder).where(WorkOrder.work_order_code == code))).scalar_one_or_none()
    if not wo:
        wo = (await db.execute(select(WorkOrder).where(WorkOrder.work_order_code.ilike(f"%{code}%")).limit(1))).scalar_one_or_none()
    if not wo:
        return {"error": f"未找到工单 {code}"}
    if wo.status != "pending":
        return {"error": f"工单 {wo.work_order_code} 当前状态为 {wo.status}，只有待下达(pending)工单可以下达"}

    wo.status = "released"
    wo.updated_by = operator
    wo.updated_at = datetime.utcnow()
    await db.commit()
    return {
        "success": True,
        "message": f"工单 {wo.work_order_code} 已下达",
        "work_order_code": wo.work_order_code,
        "status": "released（已下达）",
    }


async def _tool_create_production_report(db: AsyncSession, args: Dict[str, Any], operator: str) -> Dict[str, Any]:
    wo_id = args.get("work_order_id", "")
    station_id = args.get("station_id", "")
    good_qty = int(args.get("good_qty", 0))
    defect_qty = int(args.get("defect_qty", 0))
    shift = args.get("shift", "day")

    wo = (await db.execute(select(WorkOrder).where(WorkOrder.id == wo_id))).scalar_one_or_none()
    if not wo:
        return {"error": f"未找到工单ID {wo_id}"}
    if wo.status not in ("released", "in_progress"):
        return {"error": f"工单 {wo.work_order_code} 状态为 {wo.status}，需先下达才能报工"}

    station = (await db.execute(select(Station).where(Station.id == station_id))).scalar_one_or_none()
    if not station:
        return {"error": f"未找到工位ID {station_id}"}

    report_code = f"RPT-{datetime.now().strftime('%Y%m%d%H%M%S')}-{str(uuid.uuid4())[:4].upper()}"
    report = ProductionReport(
        id=str(uuid.uuid4()),
        report_code=report_code,
        factory_id=wo.factory_id,
        work_order_id=wo.id,
        station_id=station_id,
        good_qty=good_qty,
        defect_qty=defect_qty,
        shift=shift,
        operator_id=operator,
        created_by=operator,
    )
    db.add(report)

    # 累加工单进度
    wo.completed_qty = (wo.completed_qty or 0) + good_qty + defect_qty
    wo.good_qty = (wo.good_qty or 0) + good_qty
    wo.defect_qty = (wo.defect_qty or 0) + defect_qty
    if wo.status == "released":
        wo.status = "in_progress"
        wo.actual_start = wo.actual_start or datetime.utcnow()
    wo.updated_at = datetime.utcnow()

    await db.commit()
    await db.refresh(report)
    return {
        "success": True,
        "message": f"报工成功",
        "report_code": report_code,
        "work_order_code": wo.work_order_code,
        "station_name": station.station_name,
        "good_qty": good_qty,
        "defect_qty": defect_qty,
        "wo_completed_qty": wo.completed_qty,
        "wo_planned_qty": wo.planned_qty,
    }


# 执行器注册表
_TOOL_EXECUTORS = {
    "query_work_orders": _tool_query_work_orders,
    "get_work_order_detail": _tool_get_work_order_detail,
    "get_production_summary": _tool_get_production_summary,
    "query_inventory": _tool_query_inventory,
    "query_defects": _tool_query_defects,
    "query_equipment": _tool_query_equipment,
    "create_work_order": _tool_create_work_order,
    "release_work_order": _tool_release_work_order,
    "create_production_report": _tool_create_production_report,
}

# 写操作工具（需要记录操作人）
WRITE_TOOLS = {"create_work_order", "release_work_order", "create_production_report"}

# 工具的中文标签（供前端展示）
TOOL_LABELS = {
    "query_work_orders": "查询工单",
    "get_work_order_detail": "工单详情",
    "get_production_summary": "生产统计",
    "query_inventory": "查询库存",
    "query_defects": "查询不良品",
    "query_equipment": "查询设备",
    "create_work_order": "创建工单",
    "release_work_order": "下达工单",
    "create_production_report": "生产报工",
}


# ==================== 确定性意图路由（业务底座） ====================
# 参考 luaguage chatbot 的 capability catalog / business rule 思路：
# 不依赖模型自由决策，命中业务关键词即强制调用对应工具，从根本上杜绝
# “建议你进入看板/日报中心查看”这类推诿性模糊回答。
# 仅对单步查询类工具做强制路由；写操作/多步操作仍交由模型 auto 编排。
INTENT_RULES: List[Dict[str, Any]] = [
    {
        "tool": "get_production_summary",
        "keywords": [
            "生产情况", "生产统计", "今日生产", "今天生产", "生产汇总", "生产概览",
            "产量", "稼动率", "生产数据", "生产怎么样", "生产怎样", "今天生产怎么",
            "良品率", "报工情况", "生产概况",
        ],
    },
    {
        "tool": "query_work_orders",
        "keywords": [
            "在制工单", "工单列表", "查工单", "查询工单", "工单状态", "工单进度",
            "有哪些工单", "工单情况", "工单汇总", "待下达工单", "生产工单",
        ],
    },
    {
        "tool": "query_inventory",
        "keywords": [
            "库存", "物料水平", "库存水平", "查库存", "库存量", "物料库存",
            "库存情况", "库存怎么样", "库存怎样", "原料库存",
        ],
    },
    {
        "tool": "query_defects",
        "keywords": [
            "不良品", "缺陷", "不良", "质量问题", "不良率", "缺陷类型",
            "不良情况", "不良汇总", "质量异常",
        ],
    },
    {
        "tool": "query_equipment",
        "keywords": [
            "设备状态", "设备运行", "设备情况", "查设备", "设备故障", "机器状态",
            "设备怎么样", "设备怎样", "设备汇总", "设备稼动",
        ],
    },
]


def detect_intent_tool(message: str) -> Optional[str]:
    """确定性意图识别：命中业务关键词则返回应强制调用的工具名，否则返回 None（交给模型 auto 决策）。"""
    if not message:
        return None
    for rule in INTENT_RULES:
        if any(kw in message for kw in rule["keywords"]):
            return rule["tool"]
    return None


def resolve_intent(message: str) -> Optional[Dict[str, Any]]:
    """确定性意图解析：命中业务关键词返回 {"tool", "args"}，否则 None。

    后端可据此直接执行工具取真实数据（不依赖模型决策），args 通过轻量关键词规则提取。
    写操作/多步操作不走此路径，仍由模型 auto 编排。"""
    tool = detect_intent_tool(message)
    if not tool:
        return None
    args: Dict[str, Any] = {}
    if tool == "query_work_orders":
        if any(k in message for k in ["在制", "生产中", "进行中", "在做", "在产"]):
            args["status"] = "in_progress"
        elif any(k in message for k in ["待下达", "未下达"]):
            args["status"] = "pending"
        elif "已下达" in message:
            args["status"] = "released"
        elif any(k in message for k in ["已完成", "完工"]):
            args["status"] = "completed"
    return {"tool": tool, "args": args}


async def execute_tool(
    db: AsyncSession,
    tool_name: str,
    arguments: Dict[str, Any],
    operator: str = "ai_assistant",
) -> Dict[str, Any]:
    """执行指定工具，返回结构化结果。未知工具或异常时返回 error 字段。"""
    executor = _TOOL_EXECUTORS.get(tool_name)
    if not executor:
        return {"error": f"未知工具：{tool_name}"}
    try:
        if tool_name in WRITE_TOOLS:
            return await executor(db, arguments, operator)
        return await executor(db, arguments)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"工具执行失败：{type(exc).__name__}: {exc}"}


__all__ = ["TOOL_DEFINITIONS", "TOOL_LABELS", "WRITE_TOOLS", "execute_tool", "detect_intent_tool", "resolve_intent", "INTENT_RULES"]
