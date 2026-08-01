"""Unified drill-through traceability APIs.

These endpoints turn aggregated dashboard numbers into inspectable source
records. They do not replace module-specific detail pages; they provide a
single contract that any dashboard can use to show where a metric came from.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.security import get_current_user
from database.db_config import get_db


router = APIRouter(prefix="/api/v1/traceability", tags=["Traceability"])


TRACE_DOMAINS: Dict[str, Dict[str, Any]] = {
    "people": {
        "title": "人力数据追溯",
        "lineage": ["hr_employees 在册/在岗", "hr_employee_skills 技能矩阵", "RCC 人力基线"],
        "sources": [
            {"table": "hr_employees", "label": "员工档案", "route": "/hr-roster", "columns": ["id", "employee_code", "name", "full_name", "department", "station", "shift", "skill_level", "status", "updated_at", "created_at"]},
            {"table": "hr_employee_skills", "label": "员工技能", "route": "/skill-matrix", "columns": ["id", "employee_id", "skill_id", "level", "certified", "updated_at", "created_at"]},
        ],
    },
    "equipment": {
        "title": "设备数据追溯",
        "lineage": ["equipment 状态/OEE", "maintenance_orders 维修闭环", "production_reports 设备产出", "RCC 设备基线"],
        "sources": [
            {"table": "equipment", "label": "设备台账", "route": "/equipment-center", "columns": ["id", "equipment_code", "equipment_name", "equipment_type", "station_id", "status", "updated_at", "created_at"]},
            {"table": "maintenance_orders", "label": "维修工单", "route": "/equipment/maintenance", "columns": ["id", "order_code", "equipment_id", "priority", "status", "scheduled_start", "actual_start", "actual_end", "updated_at", "created_at"]},
            {"table": "production_reports", "label": "设备/工位产出", "route": "/production-report", "columns": ["id", "report_code", "work_order_id", "station_id", "equipment_id", "good_qty", "defect_qty", "created_at"]},
        ],
    },
    "work_orders": {
        "title": "工单数据追溯",
        "lineage": ["sales_orders/计划需求", "work_orders 工单", "routing/APS 排程", "production_reports 报工", "defect_records/traceability 质量追溯"],
        "sources": [
            {"table": "work_orders", "label": "生产工单", "route": "/work-orders", "columns": ["id", "work_order_code", "product_id", "status", "priority", "planned_qty", "completed_qty", "planned_due", "updated_at", "created_at"]},
            {"table": "production_reports", "label": "生产报工", "route": "/production-report", "columns": ["id", "report_code", "work_order_id", "station_id", "good_qty", "defect_qty", "created_at"]},
            {"table": "defect_records", "label": "不良记录", "route": "/defects", "columns": ["id", "defect_code", "work_order_id", "product_id", "batch_code", "defect_type", "severity", "quantity", "created_at"]},
            {"table": "item_traceability", "label": "一物一码追溯", "route": "/inventory", "columns": ["id", "item_code", "item_type", "work_order_id", "product_id", "material_batch_id", "station_id", "operator_id", "quality_check_result", "created_at"]},
        ],
    },
    "pm": {
        "title": "PM/维修追溯",
        "lineage": ["maintenance_plans PM计划", "maintenance_orders 执行记录", "equipment 状态", "RCC PM逾期指标"],
        "sources": [
            {"table": "maintenance_plans", "label": "PM计划", "route": "/equipment/maintenance", "columns": ["id", "plan_code", "equipment_id", "plan_type", "frequency", "next_due_at", "next_run_date", "last_run_date", "is_active", "updated_at", "created_at"]},
            {"table": "maintenance_orders", "label": "维修工单", "route": "/equipment/maintenance", "columns": ["id", "order_code", "equipment_id", "priority", "status", "scheduled_start", "actual_start", "actual_end", "updated_at", "created_at"]},
        ],
    },
    "process": {
        "title": "工艺/质量追溯",
        "lineage": ["routing_templates 工艺模板", "standard_operation_times 标准工时", "production_reports 实际产出", "defect_records 不良闭环", "RCC 工艺基线"],
        "sources": [
            {"table": "routing_templates", "label": "工艺模板", "route": "/routing-templates", "columns": ["id", "template_code", "template_name", "description", "is_active", "updated_at", "created_at"]},
            {"table": "standard_operation_times", "label": "标准工时", "route": "/ie/standard-times", "columns": ["id", "product_id", "operation_name", "station_id", "standard_time_min", "effective_standard_time", "version", "updated_at", "created_at"]},
            {"table": "process_analyses", "label": "工艺分析", "route": "/ie/process-analyses", "columns": ["id", "product_id", "process_name", "analysis_type", "score", "status", "updated_at", "created_at"]},
            {"table": "defect_records", "label": "不良记录", "route": "/defects", "columns": ["id", "defect_code", "work_order_id", "defect_type", "severity", "quantity", "root_cause_category", "created_at"]},
        ],
    },
    "wms": {
        "title": "仓储/库存追溯",
        "lineage": ["warehouses 仓库", "inventory 库存批次", "inventory_transactions 库存流水", "item_traceability 物料/成品链"],
        "sources": [
            {"table": "warehouses", "label": "仓库", "route": "/warehouses", "columns": ["id", "warehouse_code", "warehouse_name", "warehouse_type", "status", "updated_at", "created_at"]},
            {"table": "inventory", "label": "库存批次", "route": "/inventory", "columns": ["id", "material_id", "material_code", "batch_code", "total_qty", "available_qty", "reserved_qty", "status", "updated_at", "created_at"]},
            {"table": "inventory_transactions", "label": "库存流水", "route": "/inventory", "columns": ["id", "material_id", "batch_code", "transaction_type", "quantity", "before_qty", "after_qty", "operator", "created_at"]},
            {"table": "item_traceability", "label": "一物一码追溯", "route": "/inventory", "columns": ["id", "item_code", "item_type", "work_order_id", "product_id", "material_batch_id", "quality_check_result", "created_at"]},
        ],
    },
    "qms": {
        "title": "质量数据追溯",
        "lineage": ["quality_inspections 检验", "qms_spc_points SPC点", "defect_records 不良", "qms_8d_reports 8D闭环"],
        "sources": [
            {"table": "quality_inspections", "label": "检验记录", "route": "/inspections", "columns": ["id", "inspection_code", "work_order_id", "product_id", "inspection_type", "result", "status", "created_at"]},
            {"table": "qms_spc_points", "label": "SPC点", "route": "/spc-dashboard", "columns": ["id", "characteristic_code", "characteristic_name", "work_order_id", "station_id", "measured_value", "is_out_of_control", "measured_at"]},
            {"table": "defect_records", "label": "不良记录", "route": "/defects", "columns": ["id", "defect_code", "work_order_id", "batch_code", "defect_type", "severity", "quantity", "created_at"]},
            {"table": "qms_8d_reports", "label": "8D报告", "route": "/quality-center", "columns": ["id", "report_code", "defect_id", "status", "owner", "updated_at", "created_at"]},
        ],
    },
    "ie": {
        "title": "IE精益数据追溯",
        "lineage": ["standard_operation_times 标准工时", "time_study_records 时间研究", "line_balance_analyses 线平衡", "action/method/work-cell/kanban/5S 改善闭环"],
        "sources": [
            {"table": "standard_operation_times", "label": "标准工时", "route": "/ie/standard-times", "columns": ["id", "operation_name", "station_id", "standard_time_min", "effective_standard_time", "version", "updated_at", "created_at"]},
            {"table": "time_study_records", "label": "时间研究", "route": "/ie/time-studies", "columns": ["id", "operation_name", "station_id", "operator_id", "average_time", "status", "observation_date", "updated_at"]},
            {"table": "line_balance_analyses", "label": "线平衡", "route": "/ie/line-balance", "columns": ["id", "line_id", "balance_rate", "bottleneck_station", "bottleneck_time", "analysis_date", "updated_at"]},
            {"table": "action_studies", "label": "动作研究", "route": "/ie/action-studies", "columns": ["id", "operation_name", "station_id", "operator_id", "ergonomic_score", "study_date", "updated_at"]},
            {"table": "method_studies", "label": "方法研究", "route": "/ie/method-studies", "columns": ["id", "original_operation", "improved_operation", "status", "expected_time_saving_min", "updated_at"]},
            {"table": "five_s_audits", "label": "5S审核", "route": "/ie/5s-audits", "columns": ["id", "work_center_id", "auditor_id", "total_score", "audit_date", "next_audit_date", "updated_at"]},
        ],
    },
    "rcc": {
        "title": "RCC决策追溯",
        "lineage": ["global_adjustable_params 参数", "deterministic_logic_chains 确定性逻辑链", "rcc_tasks 调度任务", "chatbot_tickets Chatbot工单", "rcc_approval_records 审批"],
        "sources": [
            {"table": "rcc_tasks", "label": "RCC任务", "route": "/rcc", "columns": ["id", "task_code", "task_type", "title", "status", "requested_by", "created_at", "updated_at"]},
            {"table": "chatbot_tickets", "label": "Chatbot工单", "route": "/task-center", "columns": ["id", "ticket_code", "ticket_type", "raw_message", "status", "priority", "created_at", "updated_at"]},
            {"table": "global_adjustable_params", "label": "可调参数", "route": "/rcc?view=decisions", "columns": ["id", "param_code", "param_name", "category", "current_value", "sensitivity", "updated_at"]},
            {"table": "deterministic_logic_chains", "label": "逻辑链", "route": "/rcc?view=analysis", "columns": ["id", "chain_code", "chain_name", "trigger_event", "enabled", "updated_at"]},
            {"table": "rcc_approval_records", "label": "审批记录", "route": "/rcc?view=decisions", "columns": ["id", "rcc_task_id", "approver_role", "approver_name", "decision", "decision_at"]},
        ],
    },
}


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _safe_ident(value: str) -> str:
    if not value.replace("_", "").isalnum() or value[0].isdigit():
        raise ValueError(f"unsafe identifier: {value}")
    return value


async def _table_columns(db: AsyncSession, table_name: str) -> set[str]:
    result = await db.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=:table_name"
        ),
        {"table_name": table_name},
    )
    return {row[0] for row in result.all()}


async def _fetch_source(db: AsyncSession, source: Dict[str, Any], factory_id: str, limit: int) -> Dict[str, Any]:
    table_name = _safe_ident(source["table"])
    try:
        columns = await _table_columns(db, table_name)
        if not columns:
            return {**source, "count": 0, "records": [], "error": "表不存在"}

        selected = [c for c in source["columns"] if c in columns]
        if "id" in columns and "id" not in selected:
            selected.insert(0, "id")
        if not selected:
            selected = sorted(columns)[:6]

        where = ""
        params: Dict[str, Any] = {"limit": limit}
        if "factory_id" in columns:
            where = "WHERE factory_id = :factory_id"
            params["factory_id"] = factory_id

        count_sql = f"SELECT COUNT(*)::int FROM {table_name} {where}"
        count = (await db.execute(text(count_sql), params)).scalar() or 0

        order_col = next((c for c in ["updated_at", "created_at", "measured_at", "audit_date", "observation_date", "decision_at", "id"] if c in columns), selected[0])
        select_sql = (
            f"SELECT {', '.join(_safe_ident(c) for c in selected)} "
            f"FROM {table_name} {where} "
            f"ORDER BY {_safe_ident(order_col)} DESC NULLS LAST "
            "LIMIT :limit"
        )
        rows = (await db.execute(text(select_sql), params)).mappings().all()
        records = [
            {key: _jsonable(value) for key, value in dict(row).items()}
            for row in rows
        ]
        return {
            "key": table_name,
            "label": source["label"],
            "route": source.get("route"),
            "count": count,
            "columns": selected,
            "records": records,
        }
    except Exception as exc:
        await db.rollback()
        return {
            "key": table_name,
            "label": source["label"],
            "route": source.get("route"),
            "count": 0,
            "columns": [],
            "records": [],
            "error": str(exc),
        }


@router.get("/catalog")
async def traceability_catalog(_user=Depends(get_current_user)) -> Dict[str, Any]:
    return {
        "domains": [
            {"key": key, "title": cfg["title"], "sources": [s["label"] for s in cfg["sources"]]}
            for key, cfg in TRACE_DOMAINS.items()
        ]
    }


@router.get("/drill-through")
async def drill_through(
    factory_id: str = Query(..., description="工厂ID"),
    domain: str = Query(..., description="追溯域，如 people/equipment/work_orders/qms/wms/ie/rcc"),
    limit: int = Query(8, ge=1, le=30),
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    cfg = TRACE_DOMAINS.get(domain)
    if not cfg:
        raise HTTPException(status_code=404, detail=f"未知追溯域: {domain}")

    sources = [await _fetch_source(db, source, factory_id, limit) for source in cfg["sources"]]
    total_records = sum(source.get("count", 0) for source in sources)
    return {
        "success": True,
        "factory_id": factory_id,
        "domain": domain,
        "title": cfg["title"],
        "lineage": cfg["lineage"],
        "summary": {
            "source_count": len(sources),
            "total_records": total_records,
            "generated_at": datetime.utcnow().isoformat(),
        },
        "sources": sources,
    }
