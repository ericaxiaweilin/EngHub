

"""
v2.5 - Work Order Template Engine
程序工单模板引擎 — NCR/MAINT/ECR/FAI/SCRAP 5大行业标准模板 + JSON Schema 动态渲染
"""

import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/work-order-templates", tags=["work-order-templates"])


# ==================== 模板 Schema 定义 ====================

WORK_ORDER_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "NCR": {
        "name": "品质异常单",
        "description": "关联缺陷代码、8D 报告、处置方式（返工/报废）",
        "schema": {
            "fields": [
                {"key": "defect_code", "label": "缺陷代码", "type": "string", "required": True},
                {"key": "defect_description", "label": "缺陷描述", "type": "text", "required": True},
                {"key": "severity", "label": "严重等级", "type": "select", "options": ["critical", "major", "minor"], "required": True},
                {"key": "disposition", "label": "处置方式", "type": "select", "options": ["rework", "scrap", "repair", "concession"], "required": True},
                {"key": "disposition_qty", "label": "处置数量", "type": "integer", "required": True},
                {"key": "root_cause", "label": "根本原因", "type": "text", "required": False},
                {"key": "corrective_action", "label": "纠正措施", "type": "text", "required": False},
                {"key": "preventive_action", "label": "预防措施", "type": "text", "required": False},
                {"key": "verification_result", "label": "验证结果", "type": "text", "required": False},
                {"key": "eight_d_report_url", "label": "8D报告URL", "type": "string", "required": False},
            ]
        },
        "auto_create_defect_record": True,
    },
    "MAINT": {
        "name": "设备维修工单",
        "description": "记录故障现象、备件消耗、MTTR 计算",
        "schema": {
            "fields": [
                {"key": "equipment_id", "label": "设备ID", "type": "string", "required": True},
                {"key": "fault_symptom", "label": "故障现象", "type": "text", "required": True},
                {"key": "fault_type", "label": "故障类型", "type": "select", "options": ["mechanical", "electrical", "hydraulic", "pneumatic", "software", "other"], "required": True},
                {"key": "spare_parts", "label": "备件消耗", "type": "json_array", "required": False},
                {"key": "maintenance_hours", "label": "维修耗时(小时)", "type": "float", "required": True},
                {"key": "maintenance_result", "label": "维修结果", "type": "select", "options": ["completed", "partial", "failed"], "required": True},
                {"key": "preventive_maintenance_due", "label": "下次预防性维护日期", "type": "date", "required": False},
            ]
        },
        "auto_create_tms_task": True,
    },
    "ECR": {
        "name": "工艺变更申请",
        "description": "风险评估、受影响工单自动关联",
        "schema": {
            "fields": [
                {"key": "change_description", "label": "变更描述", "type": "text", "required": True},
                {"key": "current_process", "label": "当前工艺", "type": "string", "required": True},
                {"key": "proposed_process", "label": "拟议工艺", "type": "string", "required": True},
                {"key": "risk_level", "label": "风险等级", "type": "select", "options": ["low", "medium", "high"], "required": True},
                {"key": "affected_work_orders", "label": "受影响工单", "type": "array", "required": False},
                {"key": "approval_required", "label": "是否需要审批", "type": "boolean", "required": True},
                {"key": "effective_date", "label": "生效日期", "type": "date", "required": False},
            ]
        },
        "auto_link_affected_work_orders": True,
    },
    "FAI": {
        "name": "首件检验单",
        "description": "关键尺寸实测值与公差自动对比",
        "schema": {
            "fields": [
                {"key": "work_order_id", "label": "工单ID", "type": "string", "required": True},
                {"key": "product_id", "label": "产品ID", "type": "string", "required": True},
                {"key": "inspector_id", "label": "检验员", "type": "string", "required": True},
                {"key": "inspection_steps", "label": "检验步骤", "type": "json_array", "required": True},
                {"key": "first_pass_rate", "label": "一次合格率", "type": "float", "required": False},
                {"key": "dimensions", "label": "关键尺寸实测值", "type": "json_object", "required": True},
                {"key": "tolerances", "label": "公差范围", "type": "json_object", "required": True},
                {"key": "pass_fail", "label": "判定结果", "type": "select", "options": ["pass", "fail"], "required": True},
            ]
        },
        "auto_compare_tolerance": True,
    },
    "SCRAP": {
        "name": "报废申请单",
        "description": "成本估算、财务审批流",
        "schema": {
            "fields": [
                {"key": "work_order_id", "label": "关联工单", "type": "string", "required": True},
                {"key": "material_id", "label": "物料ID", "type": "string", "required": True},
                {"key": "scrap_quantity", "label": "报废数量", "type": "integer", "required": True},
                {"key": "unit_cost", "label": "单位成本", "type": "float", "required": True},
                {"key": "total_cost", "label": "总成本估算", "type": "float", "required": True},
                {"key": "scrap_reason", "label": "报废原因", "type": "text", "required": True},
                {"key": "approval_required", "label": "需财务审批", "type": "boolean", "required": True},
            ]
        },
        "auto_calculate_cost": True,
    },
}


# ==================== Request Models ====================

class TemplateCreateRequest(BaseModel):
    factory_id: str
    template_code: str = Field(..., description="NCR/MAINT/ECR/FAI/SCRAP")
    title: str = Field(..., min_length=1, max_length=200)
    priority: str = Field(default="medium")
    data: Dict[str, Any] = Field(default_factory=dict)
    work_order_id: Optional[str] = None
    metadata_: dict = Field(default_factory=dict)


# ==================== Routes ====================

@router.get("/", summary="获取所有模板定义")
async def list_templates():
    """返回5大行业模板的JSON Schema定义"""
    return {
        "templates": [
            {code: {k: v for k, v in tpl.items() if k != "auto_create_*"}}
            for code, tpl in WORK_ORDER_TEMPLATES.items()
        ]
    }


@router.post("/preview/{template_code}", summary="预览模板字段")
async def preview_template(template_code: str):
    """预览指定模板的表单字段"""
    if template_code not in WORK_ORDER_TEMPLATES:
        raise HTTPException(status_code=404, detail=f"模板不存在: {template_code}")
    return WORK_ORDER_TEMPLATES[template_code]["schema"]


@router.post("/create", status_code=201, summary="基于模板创建程序工单")
async def create_work_order_from_template(payload: TemplateCreateRequest):
    """
    基于预设模板创建正式程序工单，继承上下文信息。
    模板包括：NCR(品质异常)、MAINT(设备维修)、ECR(工艺变更)、FAI(首件检验)、SCRAP(报废申请)
    """
    from database.models import WorkOrder
    from database.db_config import get_db

    db = next(get_db())

    # 校验模板存在
    if payload.template_code not in WORK_ORDER_TEMPLATES:
        raise HTTPException(status_code=400, detail=f"未知模板: {payload.template_code}")

    template = WORK_ORDER_TEMPLATES[payload.template_code]
    wo_code = f"{payload.template_code}-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:6].upper()}"

    # 创建结构化程序工单
    wo = WorkOrder(
        work_order_code=f"WO-{wo_code}",
        factory_id=payload.factory_id,
        product_id=None,
        planned_qty=0,
        priority=payload.priority,
        remark=f"Template: {template['name']}\nData: {payload.data}",
        created_by="api_user",
    )
    wo.metadata_ = payload.metadata_.copy()
    wo.metadata_["template_code"] = payload.template_code
    wo.metadata_["template_data"] = payload.data
    wo.metadata_["title"] = payload.title

    db.add(wo)
    await db.commit()
    await db.refresh(wo)

    return {
        "success": True,
        "data": {
            "id": wo.id,
            "work_order_code": wo.work_order_code,
            "template_name": template["name"],
            "status": "draft",
        }
    }


__all__ = ["router", "WORK_ORDER_TEMPLATES"]


