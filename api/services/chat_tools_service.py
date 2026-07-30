"""
Chatbot MES 工具服务（Tool Calling）

让 AI 助手能通过自然语言实际执行 MES 操作：
- 查询类：工单 / 库存 / 不良品 / 设备 / 工位 / 生产统计
- 操作类：创建工单 / 下达工单 / 生产报工

工具定义为 OpenAI function-calling 标准格式，执行器直连数据库。
写操作会记录操作人（当前登录用户），并返回结构化结果供前端展示。
"""

from __future__ import annotations

import csv
import io
import json
import re
import uuid
from datetime import datetime, date
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from database.models import (
    WorkOrder, ProductionReport, Station, Equipment, Product,
    Inventory, DefectRecord, User, Routing, FileRecord, QualityInspection,
)
from core.mes.work_order_coding import (
    generate_master_work_order_code,
    derive_operation_work_orders,
)
from api.services.work_order_service import WorkOrderService, WoPermissionError
from api.services.employee_skill_service import EmployeeSkillService
from api.services.sim_erp_audit_service import SimERPAuditService
from core.sim_erp.engine import SimERPEngine
from core.sim_erp.models import (
    ActionType, EnvironmentSnapshot, PhysicalInput, WorkContext,
)
from core.sim_erp.plugins.registry import build_default_registry


# ==================== Sim-ERP 仿真引擎（模块级单例，直连引擎不走 HTTP） ====================
_sim_engine = SimERPEngine()
_sim_registry = build_default_registry()
DEFAULT_SIM_PLUGINS = ["VN_Legal_2024", "Johnson_Global_Standard", "Factory_Policy_Default"]


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
                        "enum": ["draft", "pending", "released", "in_progress", "completed", "cancelled", "on_hold"],
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
    {
        "type": "function",
        "function": {
            "name": "run_compliance_simulation",
            "description": "运行 Sim-ERP 人机工程/劳动合规仿真。输入作业场景（温度/连续作业时长/负重/姿势等），返回合规判定、违规规则、疲劳分、所需休息等。所有参数可选，默认一个标准装配场景。",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_type": {"type": "string", "description": "作业类型，如 assembly装配/inspect检验，默认assembly"},
                    "continuous_work_minutes": {"type": "integer", "description": "连续作业分钟数，默认240"},
                    "temperature_c": {"type": "number", "description": "环境温度（摄氏度），默认30"},
                    "humidity_percent": {"type": "number", "description": "湿度百分比，默认60"},
                    "load_weight_kg": {"type": "number", "description": "负重（公斤），默认0"},
                    "posture_angle_deg": {"type": "number", "description": "姿势角度（0-180），默认0"},
                    "step_count": {"type": "integer", "description": "步数，默认3000"},
                    "action_type": {"type": "string", "enum": ["walk", "lift", "push", "pull", "assemble", "inspect", "idle"], "description": "动作类型，默认walk"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_simulation_audits",
            "description": "查询历史合规仿真审计记录。返回仿真ID、作业场景、最终状态、是否违法阻断、所需休息、罚分、时间。",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "返回条数，默认10", "default": 10},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "complete_work_order",
            "description": "完工工单（需品质角色：厂长/品质经理）。会校验实际产出与父子工单完工约束。",
            "parameters": {
                "type": "object",
                "properties": {
                    "work_order_code": {"type": "string", "description": "工单号或工单ID"},
                    "completed_qty": {"type": "integer", "description": "完工数量（可选，不传则用已有报工数量）"},
                    "good_qty": {"type": "integer", "description": "良品数（可选）"},
                    "defect_qty": {"type": "integer", "description": "不良数（可选）"},
                },
                "required": ["work_order_code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pause_work_order",
            "description": "暂停工单（将生产中工单挂起）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "work_order_code": {"type": "string", "description": "工单号或工单ID"},
                    "reason": {"type": "string", "description": "暂停原因，可选"},
                },
                "required": ["work_order_code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resume_work_order",
            "description": "恢复已暂停的工单。",
            "parameters": {
                "type": "object",
                "properties": {
                    "work_order_code": {"type": "string", "description": "工单号或工单ID"},
                    "reason": {"type": "string", "description": "恢复原因，可选"},
                },
                "required": ["work_order_code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "split_work_order",
            "description": "拆分工单：从主工单拆出指定数量作为子工单（主工单量相应扣减，子工单全部完工后主工单才能完工）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "work_order_code": {"type": "string", "description": "待拆分工单号或ID"},
                    "split_qty": {"type": "integer", "description": "拆分数量（须小于计划量）"},
                    "remark": {"type": "string", "description": "备注，可选"},
                },
                "required": ["work_order_code", "split_qty"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_routing",
            "description": "查询产品工艺路线（加工步骤/工序）。可按工艺编码或产品关键词过滤。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "工艺编码或产品ID关键词，可选"},
                    "limit": {"type": "integer", "description": "返回条数，默认10", "default": 10},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_skill_matrix",
            "description": "查询员工技能矩阵（人员-技能-等级）。可按部门/技能类别过滤，默认查当前工厂。",
            "parameters": {
                "type": "object",
                "properties": {
                    "department": {"type": "string", "description": "部门/厂区，可选（默认当前工厂）"},
                    "skill_category": {"type": "string", "description": "技能类别，可选"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_workflow",
            "description": (
                "运行预置的 Agent 工作流（多工具编排成可复用流程）。可选工作流："
                "daily_production_review(生产日度复盘)、"
                "create_and_release(一键建单下达，需 params={product_id, planned_qty, planned_due})、"
                "quality_alert_triage(质量异常分诊)、"
                "full_compliance_check(全面合规检查)。"
                "当用户请求复合任务（如'帮我复盘今天生产'）时优先调用本工具。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "workflow_name": {
                        "type": "string",
                        "enum": [
                            "daily_production_review", "create_and_release",
                            "quality_alert_triage", "full_compliance_check",
                        ],
                        "description": "工作流名称",
                    },
                    "params": {
                        "type": "object",
                        "description": "工作流用户参数。create_and_release 需要 {product_id, planned_qty, planned_due}；其余工作流可不传。",
                    },
                },
                "required": ["workflow_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_work_order_form",
            "description": "拉取工单完整表单结构：含工单全字段、进度、子工单明细、状态操作日志（审核追溯）。用于「工单表单」类请求。",
            "parameters": {
                "type": "object",
                "properties": {
                    "work_order_code": {"type": "string", "description": "工单号或工单ID"},
                },
                "required": ["work_order_code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_inspection_form",
            "description": "拉取质量检验单表单（IQC/IPQC/FQC/OQC）：检验类型、检验员、抽样数、不良数、判定结果、缺陷明细。可按工单/检验类型过滤。",
            "parameters": {
                "type": "object",
                "properties": {
                    "work_order_code": {"type": "string", "description": "按工单号过滤，可选"},
                    "inspect_type": {"type": "string", "enum": ["IQC", "IPQC", "FQC", "OQC"], "description": "检验类型过滤，可选"},
                    "limit": {"type": "integer", "description": "返回条数，默认10", "default": 10},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_report_file",
            "description": "把生产汇总或工单表单导出为文件（JSON/CSV），写入系统文件表并返回下载链接。用于「导出报告/生成报表」类请求。",
            "parameters": {
                "type": "object",
                "properties": {
                    "report_type": {
                        "type": "string",
                        "enum": ["production_summary", "work_order"],
                        "description": "报告类型：production_summary生产汇总（默认）/ work_order工单表单",
                        "default": "production_summary",
                    },
                    "work_order_code": {"type": "string", "description": "工单号（report_type=work_order 时必填）"},
                    "format": {"type": "string", "enum": ["json", "csv"], "description": "文件格式，默认json", "default": "json"},
                },
            },
        },
    },
    # ---- 预警情报审查工具（017） ----
    {
        "type": "function",
        "function": {
            "name": "get_pending_alerts",
            "description": "获取当前待处理预警汇总：各来源数量、严重度分布、最紧急的预警详情。用于回答'有什么预警''当前异常'类问题。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_alert_reviews",
            "description": "查询 AI 预警审查记录。可按来源（andon/defect/equipment/wo_timeout）和状态（pending/acknowledged/dismissed）过滤。",
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "enum": ["andon", "defect", "equipment", "wo_timeout", "inventory"],
                        "description": "预警来源过滤，可选",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["pending", "acknowledged", "dismissed", "acted"],
                        "description": "审查状态过滤，可选",
                    },
                    "limit": {"type": "integer", "description": "返回条数，默认10", "default": 10},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "acknowledge_alert",
            "description": "确认或驳回某条 AI 预警审查建议。确认后表示已知晓并将处理，驳回表示误报/不需处理。",
            "parameters": {
                "type": "object",
                "properties": {
                    "review_id": {"type": "string", "description": "审查记录 ID"},
                    "action": {
                        "type": "string",
                        "enum": ["acknowledged", "dismissed"],
                        "description": "操作：acknowledged=确认知晓 / dismissed=驳回误报",
                    },
                },
                "required": ["review_id", "action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_ocap_tasks",
            "description": "查询用户待处理的 OCAP（纠正预防措施）任务。显示所有 ocap_status 为 triggered/in_progress 的缺陷，供 chatbot 向用户汇报。",
            "properties": {
                "factory_id": {"type": "string", "description": "工厂ID，可选，默认当前用户工厂"},
                "operator": {"type": "string", "description": "操作用户ID，必填"},
                "limit": {"type": "integer", "description": "返回条数，默认10", "default": 10},
            },
            "required": ["operator"],
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_alert_patrol",
            "description": "主动执行一次预警巡检：扫描工单超时、安灯未响应等异常，自动触发 AI 审查。用于'巡检''扫描异常'类请求。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_hr_roster",
            "description": "查询人力档案/花名册：按部门、工序、状态统计人员分布，或搜索具体员工。用于'人力''花名册''人员分布''多少人'类请求。",
            "parameters": {
                "type": "object",
                "properties": {
                    "department": {"type": "string", "description": "部门筛选（如 生产一部）"},
                    "station": {"type": "string", "description": "工序/岗位筛选（如 焊接）"},
                    "keyword": {"type": "string", "description": "姓名/工号模糊搜索"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_process_knowledge",
            "description": "查询流程知识库：工单全生命周期流程（8阶段）、职位标准作业流程(SOP)、各环节责任归属(RACI)。"
                           "用于'工单流程''品检员做什么''该找谁''SOP'类请求。",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "enum": ["work_order_flow", "position_sop", "who_handles"],
                        "description": "知识类型：work_order_flow=工单流程, position_sop=职位SOP, who_handles=责任归属",
                    },
                    "keyword": {"type": "string", "description": "过滤关键词（阶段名/职位名，如'下达''品检'）"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_collaboration",
            "description": "查询岗位协同规则。可查：1)某事件该谁处理/通知谁/边界在哪 2)某岗位能做什么/不能做什么 3)检查某岗位是否有权执行某动作。用于回答'这个事该谁管''谁能决定''通知谁'类问题。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query_type": {
                        "type": "string",
                        "enum": ["event_rule", "role_boundary", "check_permission"],
                        "description": "event_rule=查事件规则, role_boundary=查岗位边界, check_permission=检查权限",
                    },
                    "event_key": {
                        "type": "string",
                        "description": "事件标识(query_type=event_rule时必填)。可选: quality_incoming_fail/quality_process_fail/equipment_breakdown/material_shortage/delivery_risk/urgent_order/ecn_change/shipment_ready/supplier_delay/safety_incident",
                    },
                    "role_key": {
                        "type": "string",
                        "description": "岗位标识(query_type=role_boundary/check_permission时必填)。可选: operator/team_leader/workshop_manager/qc_inspector/qc_engineer/warehouse_keeper/buyer/planner/sales/maintenance/process_engineer",
                    },
                    "action": {
                        "type": "string",
                        "description": "要检查的动作(query_type=check_permission时必填)，如'让步接收''停机''排产'",
                    },
                },
                "required": ["query_type"],
            },
        },
    },
    # ==================== 5M1E 预警数据工具 ====================
    {
        "type": "function",
        "function": {
            "name": "query_downtime",
            "description": "查询设备停机记录与MTBF统计。返回近期停机事件（类别/时长/原因）及设备平均故障间隔。用于'停机''故障''MTBF''设备利用率'类请求。",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["breakdown", "setup", "adjustment", "waiting", "planned_maint"],
                        "description": "停机类别过滤，可选",
                    },
                    "limit": {"type": "integer", "description": "返回条数，默认15", "default": 15},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_maintenance_due",
            "description": "查询即将到期或已逾期的设备保养计划。返回设备、计划名、周期、上次执行、下次到期、逾期天数。用于'保养到期''维保''预防性维护'类请求。",
            "parameters": {
                "type": "object",
                "properties": {
                    "days_ahead": {"type": "integer", "description": "向前看几天（默认7天内到期）", "default": 7},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_shortage_alerts",
            "description": "查询缺料预警：当前库存低于补货阈值（min_level）的物料清单。返回物料、当前库存、安全库存、最低水位、缺口量。用于'缺料''补货''低于安全库存'类请求。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_stagnant",
            "description": "查询呆滞物料：超过N天无库存流动的物料。返回物料、仓库、数量、最后流动日期、呆滞天数。用于'呆滞''滞料''长期不动'类请求。",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "呆滞天数阈值（默认30天无流动）", "default": 30},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_spc_anomalies",
            "description": "查询SPC失控点：近期超出控制限（UCL/LCL）的质量特性测量。返回特性名、测量值、控制限、工位、时间。用于'SPC''失控''越限''过程能力'类请求。",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "返回条数，默认20", "default": 20},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_environment",
            "description": "查询车间环境状况：当前温度、湿度、风速、降水等（来自当地公共气象数据）。用于'环境''温度''湿度''车间环境''天气'类请求。",
            "parameters": {"type": "object", "properties": {}},
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


async def _tool_query_work_orders(db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None) -> Dict[str, Any]:
    limit = min(int(args.get("limit", 10)), 50)
    stmt = select(WorkOrder).order_by(WorkOrder.created_at.desc()).limit(limit)
    if factory_id:
        stmt = stmt.where(WorkOrder.factory_id == factory_id)
    if args.get("status"):
        stmt = stmt.where(WorkOrder.status == args["status"])
    rows = (await db.execute(stmt)).scalars().all()

    product_ids = list({wo.product_id for wo in rows if wo.product_id})
    pname_map: Dict[str, str] = {}
    if product_ids:
        # 修复：Product.id 是 UUID，应使用 Product.product_code 与 WorkOrder.product_id（字符串）匹配
        pres = await db.execute(
            select(Product.product_code, Product.product_name)
            .where(Product.product_code.in_(product_ids))
        )
        pname_map = {row.product_code: row.product_name for row in pres.all()}

    items = [_wo_to_dict(wo, pname_map.get(wo.product_id, "")) for wo in rows]
    return {"count": len(items), "work_orders": items}


async def _tool_get_work_order_detail(db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None) -> Dict[str, Any]:
    code = args.get("work_order_code", "")
    stmt = select(WorkOrder).where(WorkOrder.work_order_code == code)
    if factory_id:
        stmt = stmt.where(WorkOrder.factory_id == factory_id)
    wo = (await db.execute(stmt)).scalar_one_or_none()
    if not wo:
        # 模糊匹配
        stmt = select(WorkOrder).where(WorkOrder.work_order_code.ilike(f"%{code}%")).limit(1)
        if factory_id:
            stmt = stmt.where(WorkOrder.factory_id == factory_id)
        wo = (await db.execute(stmt)).scalar_one_or_none()
    if not wo:
        return {"error": f"未找到工单 {code}"}

    pname = ""
    if wo.product_id:
        p = (await db.execute(select(Product).where(Product.product_code == wo.product_id))).scalar_one_or_none()
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


async def _tool_get_production_summary(db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None) -> Dict[str, Any]:
    today_start = datetime.combine(date.today(), datetime.min.time())

    # 今日报工
    rpt_stmt = select(ProductionReport).where(ProductionReport.created_at >= today_start)
    if factory_id:
        rpt_stmt = rpt_stmt.where(ProductionReport.factory_id == factory_id)
    reports = (await db.execute(rpt_stmt)).scalars().all()
    today_good = sum(r.good_qty for r in reports)
    today_defect = sum(r.defect_qty for r in reports)
    total_out = today_good + today_defect
    yield_rate = round(today_good / total_out * 100, 1) if total_out else None

    # 工单统计
    wo_stmt = select(WorkOrder)
    if factory_id:
        wo_stmt = wo_stmt.where(WorkOrder.factory_id == factory_id)
    wo_all = (await db.execute(wo_stmt)).scalars().all()
    active = len([wo for wo in wo_all if wo.status == "in_progress"])
    pending = len([wo for wo in wo_all if wo.status == "pending"])

    # 设备
    eq_stmt = select(Equipment)
    if factory_id:
        eq_stmt = eq_stmt.where(Equipment.factory_id == factory_id)
    eq_all = (await db.execute(eq_stmt)).scalars().all()
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


async def _tool_query_inventory(db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None) -> Dict[str, Any]:
    limit = min(int(args.get("limit", 10)), 50)
    stmt = select(Inventory).order_by(Inventory.updated_at.desc()).limit(limit)
    if factory_id:
        stmt = stmt.where(Inventory.factory_id == factory_id)
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


async def _tool_query_defects(db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None) -> Dict[str, Any]:
    limit = min(int(args.get("limit", 10)), 50)
    stmt = select(DefectRecord).order_by(DefectRecord.created_at.desc()).limit(limit)
    if factory_id:
        stmt = stmt.where(DefectRecord.factory_id == factory_id)
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


async def _tool_query_equipment(db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None) -> Dict[str, Any]:
    stmt = select(Equipment)
    if factory_id:
        stmt = stmt.where(Equipment.factory_id == factory_id)
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
    product = (await db.execute(select(Product).where(Product.product_code == product_id))).scalar_one_or_none()
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

    wo_code = await generate_master_work_order_code(db, product.factory_id, wo_type="S")
    wo = WorkOrder(
        id=str(uuid.uuid4()),
        work_order_code=wo_code,
        factory_id=product.factory_id,
        product_id=product.id,
        planned_qty=planned_qty,
        planned_due=planned_due,
        priority=priority,
        status="draft",  # 与服务层建单一致：主工单为草稿态，方可走 release 下达（职责分离门槛）
        created_by=operator,
        wo_type="master",
    )
    db.add(wo)
    await db.flush()  # 拿到主工单 id，供派生工序工单引用
    operations = await derive_operation_work_orders(db, wo, created_by=operator)
    await db.commit()
    await db.refresh(wo)
    return {
        "success": True,
        "message": "工单创建成功" + (f"，已按工艺路线派生 {len(operations)} 道工序工单" if operations else ""),
        "work_order_code": wo.work_order_code,
        "id": wo.id,
        "product_name": product.product_name,
        "planned_qty": planned_qty,
        "planned_due": planned_due_str,
        "status": "draft（草稿，待下达）",
        "operation_count": len(operations),
        "operation_codes": [op.work_order_code for op in operations],
    }


async def _tool_release_work_order(db: AsyncSession, args: Dict[str, Any], operator: str) -> Dict[str, Any]:
    code = args.get("work_order_code", "")
    wo = (await db.execute(select(WorkOrder).where(WorkOrder.work_order_code == code))).scalar_one_or_none()
    if not wo:
        wo = (await db.execute(select(WorkOrder).where(WorkOrder.work_order_code.ilike(f"%{code}%")).limit(1))).scalar_one_or_none()
    if not wo:
        return {"error": f"未找到工单 {code}"}

    # 统一走服务层审核门槛（角色校验 + 职责分离），不允许 AI 助手绕过
    user = (await db.execute(select(User).where(User.username == operator))).scalar_one_or_none()
    try:
        wo = await WorkOrderService(db).release_work_order(wo.id, user)
    except (WoPermissionError, ValueError) as e:
        return {"error": str(e)}
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

    wo = await _resolve_work_order(db, wo_id)
    if not wo:
        return {"error": f"未找到工单 {wo_id}"}
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


# ==================== 仿真 / 扩展操作 工具执行器 ====================

async def _resolve_work_order(db: AsyncSession, code_or_id: str, factory_id: Optional[str] = None) -> Optional[WorkOrder]:
    """按 ID 或工单号（支持模糊）定位工单。"""
    if not code_or_id:
        return None
    # WorkOrder.id 为 uuid, 仅当入参形似 UUID 时才按 id 查, 否则传编码会抛 invalid UUID 异常
    try:
        uuid.UUID(str(code_or_id))
        _is_uuid = True
    except (ValueError, TypeError):
        _is_uuid = False
    if _is_uuid:
        wo = (await db.execute(select(WorkOrder).where(WorkOrder.id == code_or_id))).scalar_one_or_none()
        if wo:
            return wo
    stmt = select(WorkOrder).where(WorkOrder.work_order_code == code_or_id)
    if factory_id:
        stmt = stmt.where(WorkOrder.factory_id == factory_id)
    wo = (await db.execute(stmt)).scalar_one_or_none()
    if wo:
        return wo
    stmt = select(WorkOrder).where(WorkOrder.work_order_code.ilike(f"%{code_or_id}%")).limit(1)
    if factory_id:
        stmt = stmt.where(WorkOrder.factory_id == factory_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def _get_user_by_name(db: AsyncSession, operator: str) -> Optional[User]:
    return (await db.execute(select(User).where(User.username == operator))).scalar_one_or_none()


async def _tool_run_compliance_simulation(db: AsyncSession, args: Dict[str, Any], operator: str) -> Dict[str, Any]:
    """运行 Sim-ERP 合规仿真（直连引擎），落审计记录并返回判定摘要。"""
    task_type = args.get("task_type") or "assembly"
    action_raw = (args.get("action_type") or "walk").lower()
    action = action_raw if action_raw in [a.value for a in ActionType] else "walk"
    try:
        env = EnvironmentSnapshot(
            temperature_c=float(args.get("temperature_c", 30.0)),
            humidity_percent=float(args.get("humidity_percent", 60.0)),
        )
        wc = WorkContext(
            task_type=task_type,
            zone_id=args.get("zone_id") or "line-a",
            shift_id=args.get("shift_id") or "shift-day",
            worker_ref=args.get("worker_ref") or "worker-001",
            action_type=ActionType(action),
        )
        phys = PhysicalInput(
            time_step_minutes=float(args.get("time_step_minutes", 30.0)),
            step_count=int(args.get("step_count", 3000)),
            load_weight_kg=float(args.get("load_weight_kg", 0.0)),
            posture_angle_deg=float(args.get("posture_angle_deg", 0.0)),
            continuous_work_minutes=int(args.get("continuous_work_minutes", 240)),
            environment=env,
            work_context=wc,
        )
    except Exception as exc:  # 参数越界等 pydantic 校验失败
        return {"error": f"仿真参数不合法：{exc}"}

    plugins = _sim_registry.create_many(DEFAULT_SIM_PLUGINS)
    record = _sim_engine.evaluate(phys, plugins)

    # 落审计记录（独立事务，失败不影响返回仿真结果）
    try:
        await SimERPAuditService(db).create_audit_log(record)
        await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()

    arb = record.arbiter_result
    snap = record.snapshot
    return {
        "success": True,
        "message": "合规仿真完成",
        "simulation_id": record.simulation_id,
        "final_status": arb.final_status,
        "legal_blocked": arb.legal_blocked,
        "fatigue_score": round(snap.fatigue_score, 1),
        "energy_kcal": round(snap.energy_kcal, 1),
        "max_required_break_minutes": arb.max_required_break_minutes,
        "total_penalty_score": arb.total_penalty_score,
        "blocking_rules": [d.rule_code for d in arb.blocking_decisions],
        "warnings": [d.rule_code for d in arb.warnings],
        "applied_actions": [
            {"action_code": a.action_code, "description": a.description, "break_minutes": a.break_minutes}
            for a in arb.applied_actions
        ],
        "decision_count": len(arb.decisions),
        "scenario": {
            "task_type": task_type,
            "continuous_work_minutes": snap.continuous_work_minutes,
            "temperature_c": snap.environment.temperature_c,
            "load_weight_kg": snap.load_weight_kg,
            "posture_angle_deg": snap.posture_angle_deg,
        },
    }


async def _tool_query_simulation_audits(db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None) -> Dict[str, Any]:
    """查询历史合规仿真审计记录（审计表无工厂列，不作工厂过滤）。"""
    limit = min(int(args.get("limit", 10)), 50)
    entities, total = await SimERPAuditService(db).list_audit_logs(page=1, page_size=limit)
    items = [
        {
            "simulation_id": e.simulation_id,
            "worker_ref": e.worker_ref,
            "task_type": e.task_type,
            "zone_id": e.zone_id,
            "final_status": e.final_status,
            "legal_blocked": e.legal_blocked,
            "max_required_break_minutes": e.max_required_break_minutes,
            "total_penalty_score": e.total_penalty_score,
            "created_at": e.created_at.strftime("%Y-%m-%d %H:%M") if e.created_at else None,
        }
        for e in entities
    ]
    return {"count": len(items), "total": total, "audits": items}


async def _tool_complete_work_order(db: AsyncSession, args: Dict[str, Any], operator: str) -> Dict[str, Any]:
    ref = args.get("work_order_code") or args.get("work_order_id") or ""
    wo = await _resolve_work_order(db, ref)
    if not wo:
        return {"error": f"未找到工单 {ref}"}
    user = await _get_user_by_name(db, operator)

    def _opt_int(key):
        v = args.get(key)
        if v is None or v == "":
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    try:
        wo = await WorkOrderService(db).complete_work_order(
            wo.id,
            completed_qty=_opt_int("completed_qty"),
            good_qty=_opt_int("good_qty"),
            defect_qty=_opt_int("defect_qty"),
            user=user,
        )
    except (WoPermissionError, ValueError) as e:
        return {"error": str(e)}
    if not wo:
        return {"error": "完工失败"}
    return {
        "success": True,
        "message": f"工单 {wo.work_order_code} 已完工",
        "work_order_code": wo.work_order_code,
        "status": wo.status,
        "completed_qty": wo.completed_qty,
        "good_qty": wo.good_qty,
        "defect_qty": wo.defect_qty,
    }


async def _tool_pause_work_order(db: AsyncSession, args: Dict[str, Any], operator: str) -> Dict[str, Any]:
    ref = args.get("work_order_code") or args.get("work_order_id") or ""
    wo = await _resolve_work_order(db, ref)
    if not wo:
        return {"error": f"未找到工单 {ref}"}
    user = await _get_user_by_name(db, operator)
    try:
        wo = await WorkOrderService(db).pause_work_order(wo.id, reason=args.get("reason") or "", user=user)
    except (WoPermissionError, ValueError) as e:
        return {"error": str(e)}
    if not wo:
        return {"error": "暂停失败（检查工单状态是否为生产中）"}
    return {"success": True, "message": f"工单 {wo.work_order_code} 已暂停", "work_order_code": wo.work_order_code, "status": wo.status}


async def _tool_resume_work_order(db: AsyncSession, args: Dict[str, Any], operator: str) -> Dict[str, Any]:
    ref = args.get("work_order_code") or args.get("work_order_id") or ""
    wo = await _resolve_work_order(db, ref)
    if not wo:
        return {"error": f"未找到工单 {ref}"}
    user = await _get_user_by_name(db, operator)
    try:
        wo = await WorkOrderService(db).resume_work_order(wo.id, reason=args.get("reason") or "", user=user)
    except (WoPermissionError, ValueError) as e:
        return {"error": str(e)}
    if not wo:
        return {"error": "恢复失败（检查工单状态是否为已暂停）"}
    return {"success": True, "message": f"工单 {wo.work_order_code} 已恢复生产", "work_order_code": wo.work_order_code, "status": wo.status}


async def _tool_split_work_order(db: AsyncSession, args: Dict[str, Any], operator: str) -> Dict[str, Any]:
    ref = args.get("work_order_code") or args.get("work_order_id") or ""
    wo = await _resolve_work_order(db, ref)
    if not wo:
        return {"error": f"未找到工单 {ref}"}
    try:
        split_qty = int(args.get("split_qty", 0))
    except (TypeError, ValueError):
        return {"error": "拆分数量不合法"}
    if split_qty <= 0:
        return {"error": "拆分数量必须大于0"}
    user = await _get_user_by_name(db, operator)
    try:
        original, new_wo = await WorkOrderService(db).split_work_order(
            wo.id, split_qty, remark=args.get("remark"), created_by=operator, user=user,
        )
    except (WoPermissionError, ValueError) as e:
        return {"error": str(e)}
    return {
        "success": True,
        "message": f"拆分成功：{original.work_order_code} 拆出子工单 {new_wo.work_order_code}",
        "master_work_order_code": original.work_order_code,
        "master_planned_qty": original.planned_qty,
        "child_work_order_code": new_wo.work_order_code,
        "child_planned_qty": new_wo.planned_qty,
        "child_status": new_wo.status,
    }


async def _tool_query_routing(db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None) -> Dict[str, Any]:
    limit = min(int(args.get("limit", 10)), 50)
    stmt = select(Routing).where(Routing.is_active == True)  # noqa: E712
    if factory_id:
        stmt = stmt.where(Routing.factory_id == factory_id)
    kw = args.get("keyword")
    if kw:
        stmt = stmt.where((Routing.routing_code.ilike(f"%{kw}%")) | (Routing.product_id.ilike(f"%{kw}%")))
    stmt = stmt.order_by(Routing.created_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    items = [
        {
            "routing_code": r.routing_code,
            "product_id": r.product_id,
            "version": r.version,
            "step_count": len(r.steps or []),
            "steps": r.steps,
        }
        for r in rows
    ]
    return {"count": len(items), "routings": items}


async def _tool_query_skill_matrix(db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None) -> Dict[str, Any]:
    # department 参数复用为工厂过滤（get_skill_matrix 按 User.factory_id 筛选）
    department = args.get("department") or factory_id
    matrix = await EmployeeSkillService(db).get_skill_matrix(
        department=department,
        skill_category=args.get("skill_category"),
    )
    items = [m.model_dump() for m in matrix]
    return {"count": len(items), "skill_matrix": items}


async def _tool_run_workflow(db: AsyncSession, args: Dict[str, Any], operator: str) -> Dict[str, Any]:
    """运行预置 Agent 工作流（多工具编排）。

    归属 WRITE_TOOLS 以获得 operator；factory_id 从 operator 对应用户推导，
    供工作流内的查询步骤做工厂隔离。懒加载 workflow_service 避免顶层循环导入。"""
    from api.services.workflow_service import run_workflow  # 懒加载，避免循环导入

    name = args.get("workflow_name") or ""
    params = dict(args.get("params") or {})
    # 参数名兼容：qty → planned_qty（与 create_work_order 参数名对齐）
    if "qty" in params and "planned_qty" not in params:
        params["planned_qty"] = params.pop("qty")

    user = await _get_user_by_name(db, operator)
    factory_id = user.factory_id if user else None
    return await run_workflow(db, name, params, operator=operator, factory_id=factory_id)


# ==================== 系统表单拉取 / 报告导出 工具执行器 ====================

async def _tool_get_work_order_form(db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None) -> Dict[str, Any]:
    """拉取工单完整表单结构（全字段 + 进度 + 子工单 + 状态日志）。"""
    ref = args.get("work_order_code") or args.get("work_order_id") or ""
    wo = await _resolve_work_order(db, ref, factory_id)
    if not wo:
        return {"error": f"未找到工单 {ref}"}
    svc = WorkOrderService(db)
    form = svc.to_dict(wo)
    if wo.product_id:
        p = (await db.execute(select(Product).where(Product.product_code == wo.product_id))).scalar_one_or_none()
        if p:
            form["product_name"] = p.product_name
    form["progress"] = await svc.get_progress(wo)
    children = await svc.get_children_detail(wo.id)
    status_logs = await svc.get_status_logs(wo.id)
    return {
        "form": form,
        "children": children,
        "children_count": len(children),
        "status_logs": status_logs,
        "status_log_count": len(status_logs),
    }


async def _tool_get_inspection_form(db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None) -> Dict[str, Any]:
    """拉取质量检验单表单（可按工单/检验类型过滤）。"""
    limit = min(int(args.get("limit", 10)), 50)
    stmt = select(QualityInspection).order_by(QualityInspection.created_at.desc())
    if factory_id:
        stmt = stmt.where(QualityInspection.factory_id == factory_id)
    if args.get("inspect_type"):
        stmt = stmt.where(QualityInspection.inspect_type == args["inspect_type"])
    wo_ref = args.get("work_order_code")
    if wo_ref:
        wo = await _resolve_work_order(db, wo_ref, factory_id)
        if not wo:
            return {"error": f"未找到工单 {wo_ref}"}
        stmt = stmt.where(QualityInspection.work_order_id == wo.id)
    rows = (await db.execute(stmt.limit(limit))).scalars().all()

    wo_ids = list({r.work_order_id for r in rows if r.work_order_id})
    wo_map: Dict[str, str] = {}
    if wo_ids:
        wos = (await db.execute(select(WorkOrder).where(WorkOrder.id.in_(wo_ids)))).scalars().all()
        wo_map = {w.id: w.work_order_code for w in wos}

    items = [
        {
            "id": r.id,
            "work_order_code": wo_map.get(r.work_order_id, ""),
            "inspect_type": r.inspect_type,
            "inspector_id": r.inspector_id,
            "sample_qty": r.sample_qty,
            "defect_qty": r.defect_qty,
            "result": r.result,
            "defect_details": r.defect_details,
            "remark": r.remark,
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else None,
        }
        for r in rows
    ]
    return {"count": len(items), "inspections": items}


def _to_csv(rows: Any) -> str:
    """把平坦 dict 或 dict 列表转为 CSV 文本（嵌套值 JSON 编码）。"""
    if isinstance(rows, dict):
        rows = [rows]
    if not rows:
        return ""
    keys: List[str] = []
    for r in rows:
        for k in r.keys():
            if k not in keys:
                keys.append(k)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(keys)
    for r in rows:
        out = []
        for k in keys:
            v = r.get(k)
            if isinstance(v, (dict, list)):
                v = json.dumps(v, ensure_ascii=False, default=str)
            out.append(v)
        writer.writerow(out)
    return buf.getvalue()


async def _tool_export_report_file(db: AsyncSession, args: Dict[str, Any], operator: str) -> Dict[str, Any]:
    """把生产汇总/工单表单导出为文件（JSON/CSV），写入 files 表并返回下载链接。"""
    from api.routes.file_routes import UPLOAD_DIR  # 懒加载，复用落盘目录

    report_type = args.get("report_type") or "production_summary"
    fmt = (args.get("format") or "json").lower()
    if fmt not in ("json", "csv"):
        fmt = "json"
    user = await _get_user_by_name(db, operator)
    factory_id = user.factory_id if user else None

    if report_type == "work_order":
        ref = args.get("work_order_code") or ""
        wo = await _resolve_work_order(db, ref, factory_id)
        if not wo:
            return {"error": f"未找到工单 {ref}，导出工单表单需提供工单号"}
        svc = WorkOrderService(db)
        data = {
            "work_order": svc.to_dict(wo),
            "children": await svc.get_children_detail(wo.id),
            "status_logs": await svc.get_status_logs(wo.id),
        }
        csv_rows = data["work_order"]
        filename_base = f"work_order_{wo.work_order_code}"
        related_type, related_id = "work_order", wo.id
    else:
        data = await _tool_get_production_summary(db, {}, factory_id)
        csv_rows = data
        filename_base = f"production_summary_{date.today().strftime('%Y%m%d')}"
        related_type, related_id = "report", "production_summary"

    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    if fmt == "csv":
        content = _to_csv(csv_rows)
        ext, content_type = "csv", "text/csv"
    else:
        content = json.dumps(data, ensure_ascii=False, indent=2, default=str)
        ext, content_type = "json", "application/json"

    file_id = str(uuid.uuid4())
    filename = f"{filename_base}_{ts}.{ext}"
    storage_path = UPLOAD_DIR / f"{file_id}_{filename}"
    storage_path.write_text(content, encoding="utf-8")

    record = FileRecord(
        id=file_id,
        filename=filename,
        content_type=content_type,
        size=len(content.encode("utf-8")),
        storage_path=str(storage_path),
        uploaded_by=operator,
        factory_id=factory_id,
        related_type=related_type,
        related_id=related_id,
    )
    db.add(record)
    await db.commit()

    return {
        "success": True,
        "message": f"报告已导出：{filename}",
        "file_id": file_id,
        "filename": filename,
        "download_url": f"/api/v1/files/{file_id}",
        "format": fmt,
        "size": len(content.encode("utf-8")),
    }


# ==================== 预警情报审查工具执行器（017） ====================

async def _tool_get_pending_alerts(db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None) -> Dict[str, Any]:
    from api.services.alert_intelligence_service import get_pending_alerts_summary
    if not factory_id:
        return {"error": "缺少工厂ID"}
    return await get_pending_alerts_summary(db, factory_id)


async def _tool_query_alert_reviews(db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None) -> Dict[str, Any]:
    from api.services.alert_intelligence_service import list_reviews
    if not factory_id:
        return {"error": "缺少工厂ID"}
    limit = min(int(args.get("limit", 10)), 50)
    items = await list_reviews(db, factory_id, source=args.get("source"), status=args.get("status"), limit=limit)
    return {"count": len(items), "reviews": items}


async def _tool_acknowledge_alert(db: AsyncSession, args: Dict[str, Any], operator: str) -> Dict[str, Any]:
    from api.services.alert_intelligence_service import acknowledge_review
    review_id = args.get("review_id", "")
    action = args.get("action", "acknowledged")
    if action not in ("acknowledged", "dismissed"):
        return {"error": f"action 须为 acknowledged 或 dismissed，当前值: {action}"}
    result = await acknowledge_review(db, review_id, action, operator)
    if not result:
        return {"error": f"未找到审查记录 {review_id}"}
    if "error" in result:
        return result
    return {"success": True, "message": f"审查记录已{('确认' if action == 'acknowledged' else '驳回')}", "review": result}


async def _tool_run_alert_patrol(db: AsyncSession, args: Dict[str, Any], operator: str) -> Dict[str, Any]:
    from api.services.alert_intelligence_service import patrol
    user = await _get_user_by_name(db, operator)
    factory_id = user.factory_id if user else None
    if not factory_id:
        return {"error": "无法确定工厂ID"}
    result = await patrol(db, factory_id)
    result["message"] = f"巡检完成：发现 {result.get('alerts_found', 0)} 条预警，创建 {result.get('reviews_created', 0)} 条AI审查"
    return result


async def _tool_query_ocap_tasks(db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None) -> Dict[str, Any]:
    """查询用户待处理的 OCAP 任务 - 集成到 chatbot
    
    返回当前用户（operator参数）在指定工厂下，状态为 triggered/in_progress 的缺陷列表。
    
    Args:
        factory_id: 工厂ID（可选）
        operator: 操作用户ID（必选）
        
    Returns:
        {count: int, tasks: List[{defect_code, defect_type, severity, ocap_status, trigger_reason}]}
    """
    from database.models import DefectRecord
    
    current_factory = factory_id or "FAC_ELEC_DEMO_2026"  # 默认工厂，实际应从 auth context 获取
    operator_id = args.get("operator")
    
    if not operator_id:
        return {"error": "缺少 operator 参数"}
    
    # 查询用户的 OCAP 待办：ocap_status 为 triggered 或 in_progress
    stmt = select(DefectRecord).where(
        DefectRecord.factory_id == current_factory,
        DefectRecord.ocap_status.in_(['triggered', 'in_progress']),
    )
    
    result = await db.execute(stmt)
    defects = result.scalars().all()
    
    tasks = []
    for d in defects:
        tasks.append({
            "defect_code": d.defect_code or d.id,
            "defect_type": d.defect_type or "",
            "severity": d.severity or "",
            "ocap_status": d.ocap_status or "pending",
            "trigger_reason": d.ocap_trigger_reason or "未说明",
            "created_at": d.created_at.isoformat() if d.created_at else "",
        })
    
    return {
        "count": len(tasks),
        "tasks": tasks,
    }


async def _tool_query_hr_roster(db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None) -> Dict[str, Any]:
    """查询人力档案：按部门/工序统计 + 人员搜索"""
    from sqlalchemy import text as sa_text
    fid = factory_id or "FAC_MECH_001"
    department = args.get("department")
    station = args.get("station")
    keyword = args.get("keyword")

    # 统计概览
    conditions = ["factory_id = :fid"]
    params: Dict[str, Any] = {"fid": fid}
    if department:
        conditions.append("department = :dept")
        params["dept"] = department
    if station:
        conditions.append("station = :station")
        params["station"] = station
    if keyword:
        conditions.append("(name ILIKE :kw OR employee_code ILIKE :kw)")
        params["kw"] = f"%{keyword}%"
    where = " AND ".join(conditions)

    total = (await db.execute(sa_text(f"SELECT count(*) FROM hr_employees WHERE {where}"), params)).scalar()
    active = (await db.execute(sa_text(f"SELECT count(*) FROM hr_employees WHERE {where} AND status='active'"), params)).scalar()

    # 按部门+工序统计
    dept_rows = (await db.execute(sa_text(f"""
        SELECT department, station, count(*) as cnt, count(*) FILTER (WHERE status='active') as act
        FROM hr_employees WHERE {where}
        GROUP BY department, station ORDER BY department, cnt DESC
    """), params)).fetchall()

    distribution = [
        {"department": r[0], "station": r[1], "total": r[2], "active": r[3]}
        for r in dept_rows
    ]

    # 如果有搜索关键词，返回具体人员列表（前20条）
    employees = []
    if keyword:
        params["limit"] = 20
        emp_rows = (await db.execute(sa_text(f"""
            SELECT employee_code, name, gender, department, station, position, shift, skill_level, status
            FROM hr_employees WHERE {where} ORDER BY department, station LIMIT :limit
        """), params)).fetchall()
        employees = [
            {"code": r[0], "name": r[1], "gender": r[2], "department": r[3], "station": r[4],
             "position": r[5], "shift": r[6], "skill": r[7], "status": r[8]}
            for r in emp_rows
        ]

    return {
        "factory_id": fid,
        "total": total,
        "active": active,
        "distribution": distribution,
        "employees": employees,
    }


# ==================== 5M1E 预警数据工具执行器 ====================

async def _tool_query_downtime(db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None) -> Dict[str, Any]:
    """设备停机记录 + MTBF 统计"""
    from sqlalchemy import text as sa_text
    fid = factory_id or "FAC_ELEC_DEMO_2026"
    limit = min(int(args.get("limit", 15)), 50)
    category = args.get("category")

    conditions = ["d.factory_id = :fid"]
    params: Dict[str, Any] = {"fid": fid}
    if category:
        conditions.append("d.downtime_category = :cat")
        params["cat"] = category
    where = " AND ".join(conditions)

    rows = (await db.execute(sa_text(f"""
        SELECT d.equipment_id, e.equipment_code, e.equipment_name,
               d.start_time, d.end_time, d.duration_minutes,
               d.downtime_category, d.reason_code, d.description
        FROM equipment_downtime d
        LEFT JOIN equipment e ON e.id = d.equipment_id
        WHERE {where}
        ORDER BY d.start_time DESC LIMIT :lim
    """), {**params, "lim": limit})).fetchall()

    events = [
        {
            "equipment_code": r[1], "equipment_name": r[2],
            "start": str(r[3]) if r[3] else None,
            "end": str(r[4]) if r[4] else None,
            "duration_min": round(r[5], 1) if r[5] else None,
            "category": r[6], "reason": r[7], "description": r[8],
        }
        for r in rows
    ]

    # MTBF 统计（近30天 breakdown 类）
    mtbf_rows = (await db.execute(sa_text("""
        SELECT e.equipment_code, e.equipment_name,
               count(*) as fault_count,
               COALESCE(sum(d.duration_minutes), 0) as total_min
        FROM equipment_downtime d
        LEFT JOIN equipment e ON e.id = d.equipment_id
        WHERE d.factory_id = :fid AND d.downtime_category = 'breakdown'
          AND d.start_time >= now() - interval '30 days'
        GROUP BY e.equipment_code, e.equipment_name
        ORDER BY fault_count DESC LIMIT 10
    """), {"fid": fid})).fetchall()

    mtbf = [
        {
            "equipment_code": r[0], "equipment_name": r[1],
            "fault_count_30d": r[2],
            "total_downtime_min": round(r[3], 1),
            "mtbf_hours": round((30 * 24) / max(r[2], 1), 1),
        }
        for r in mtbf_rows
    ]

    return {"factory_id": fid, "events": events, "event_count": len(events), "mtbf_30d": mtbf}


async def _tool_query_maintenance_due(db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None) -> Dict[str, Any]:
    """保养到期/逾期预警"""
    from sqlalchemy import text as sa_text
    fid = factory_id or "FAC_ELEC_DEMO_2026"
    days_ahead = int(args.get("days_ahead", 7))

    rows = (await db.execute(sa_text("""
        SELECT p.plan_name, p.frequency_days, p.last_executed_at, p.next_due_at,
               e.equipment_code, e.equipment_name, e.status as eq_status,
               (p.next_due_at - now()) as remaining
        FROM maintenance_plans p
        LEFT JOIN equipment e ON e.id = p.equipment_id
        WHERE p.factory_id = :fid AND p.is_active = true
          AND p.next_due_at <= now() + (:days || ' days')::interval
        ORDER BY p.next_due_at ASC
    """), {"fid": fid, "days": str(days_ahead)})).fetchall()

    items = []
    for r in rows:
        remaining = r[7]
        overdue_days = -int(remaining.total_seconds() // 86400) if remaining and remaining.total_seconds() < 0 else 0
        items.append({
            "plan_name": r[0], "frequency_days": r[1],
            "last_executed": str(r[2])[:10] if r[2] else None,
            "next_due": str(r[3])[:10] if r[3] else None,
            "equipment_code": r[4], "equipment_name": r[5],
            "equipment_status": r[6],
            "overdue_days": overdue_days,
            "status": "逾期" if overdue_days > 0 else "即将到期",
        })

    overdue = [i for i in items if i["overdue_days"] > 0]
    return {
        "factory_id": fid, "days_ahead": days_ahead,
        "total_due": len(items), "overdue_count": len(overdue),
        "plans": items,
    }


async def _tool_query_shortage_alerts(db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None) -> Dict[str, Any]:
    """缺料预警：库存 < 补货阈值 min_level"""
    from sqlalchemy import text as sa_text
    fid = factory_id or "FAC_ELEC_DEMO_2026"

    rows = (await db.execute(sa_text("""
        SELECT rt.material_id, rt.min_level, rt.safety_stock, rt.max_level,
               rt.reorder_lot_size, rt.reorder_lead_time_hours,
               COALESCE(inv.total_qty, 0) as current_qty,
               COALESCE(inv.material_code, rt.material_id) as material_code
        FROM replenishment_thresholds rt
        LEFT JOIN (
            SELECT material_id, material_code, sum(total_qty) as total_qty
            FROM inventory WHERE factory_id = :fid
            GROUP BY material_id, material_code
        ) inv ON inv.material_id = rt.material_id
        WHERE rt.factory_id = :fid AND rt.active = true
          AND COALESCE(inv.total_qty, 0) < rt.min_level
        ORDER BY (rt.min_level - COALESCE(inv.total_qty, 0)) DESC
    """), {"fid": fid})).fetchall()

    items = [
        {
            "material_id": r[0], "material_name": r[7],
            "current_qty": r[6], "min_level": r[1],
            "safety_stock": r[2], "max_level": r[3],
            "gap": r[1] - r[6],
            "reorder_lot": r[4], "lead_time_hours": r[5],
            "severity": "critical" if r[6] < r[2] else "warning",
        }
        for r in rows
    ]
    critical = [i for i in items if i["severity"] == "critical"]
    return {
        "factory_id": fid, "shortage_count": len(items),
        "critical_count": len(critical), "items": items,
    }


async def _tool_query_stagnant(db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None) -> Dict[str, Any]:
    """呆滞物料：超过 N 天无库存流动"""
    from sqlalchemy import text as sa_text
    fid = factory_id or "FAC_ELEC_DEMO_2026"
    days = int(args.get("days", 30))

    rows = (await db.execute(sa_text("""
        SELECT i.material_code, i.total_qty,
               i.updated_at, i.created_at,
               w.warehouse_name,
               COALESCE(EXTRACT(DAY FROM now() - i.updated_at), 0) as stagnant_days
        FROM inventory i
        LEFT JOIN warehouses w ON w.id = i.warehouse_id
        WHERE i.factory_id = :fid AND i.total_qty > 0
          AND i.updated_at < now() - (:days || ' days')::interval
        ORDER BY stagnant_days DESC
        LIMIT 30
    """), {"fid": fid, "days": str(days)})).fetchall()

    items = [
        {
            "material_code": r[0], "material_name": r[0],
            "qty": r[1],
            "last_movement": str(r[2])[:10] if r[2] else str(r[3])[:10],
            "warehouse": r[4],
            "stagnant_days": int(r[5]),
        }
        for r in rows
    ]
    return {"factory_id": fid, "threshold_days": days, "stagnant_count": len(items), "items": items}


async def _tool_query_spc_anomalies(db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None) -> Dict[str, Any]:
    """SPC 失控点：超出 UCL/LCL 的测量"""
    from sqlalchemy import text as sa_text
    fid = factory_id or "FAC_ELEC_DEMO_2026"
    limit = min(int(args.get("limit", 20)), 50)

    rows = (await db.execute(sa_text("""
        SELECT characteristic_code, characteristic_name, measured_value,
               ucl, lcl, cl, station_id, measured_at, measured_by
        FROM qms_spc_points
        WHERE factory_id = :fid AND is_out_of_control = true
        ORDER BY measured_at DESC LIMIT :lim
    """), {"fid": fid, "lim": limit})).fetchall()

    items = [
        {
            "characteristic": r[1] or r[0],
            "measured_value": round(r[2], 3) if r[2] is not None else None,
            "ucl": r[3], "lcl": r[4], "cl": r[5],
            "deviation": round(r[2] - r[3], 3) if r[2] is not None and r[3] is not None and r[2] > r[3]
                         else round(r[2] - r[4], 3) if r[2] is not None and r[4] is not None else None,
            "station": r[6], "measured_at": str(r[7])[:16] if r[7] else None,
            "measured_by": r[8],
        }
        for r in rows
    ]

    # 汇总：近7天失控总数
    total_7d = (await db.execute(sa_text("""
        SELECT count(*) FROM qms_spc_points
        WHERE factory_id = :fid AND is_out_of_control = true
          AND measured_at >= now() - interval '7 days'
    """), {"fid": fid})).scalar() or 0

    return {"factory_id": fid, "anomaly_count": len(items), "total_7d": total_7d, "anomalies": items}


# 工厂坐标配置（默认越南胡志明市工业区，可按 factory_id 扩展）
_FACTORY_COORDS = {
    "FAC_ELEC_DEMO_2026": (10.8231, 106.6297),  # 胡志明市
    "FAC_MECH_001": (10.8231, 106.6297),
}
_DEFAULT_COORDS = (10.8231, 106.6297)


async def _tool_query_environment(db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None) -> Dict[str, Any]:
    """车间环境状况：调用 Open-Meteo 免费公共气象 API（无需 key）"""
    import httpx
    fid = factory_id or "FAC_ELEC_DEMO_2026"
    lat, lon = _FACTORY_COORDS.get(fid, _DEFAULT_COORDS)

    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&current=temperature_2m,relative_humidity_2m,apparent_temperature,"
        f"precipitation,wind_speed_10m,surface_pressure"
        f"&timezone=Asia/Ho_Chi_Minh"
    )
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            data = resp.json()
    except Exception as e:  # noqa: BLE001
        return {"error": f"气象数据获取失败: {e}", "factory_id": fid}

    cur = data.get("current", {})
    temp = cur.get("temperature_2m")
    humidity = cur.get("relative_humidity_2m")
    feels = cur.get("apparent_temperature")
    precip = cur.get("precipitation")
    wind = cur.get("wind_speed_10m")
    pressure = cur.get("surface_pressure")

    # 环境评估（车间接标准）
    alerts = []
    if temp is not None and temp > 35:
        alerts.append(f"高温预警：当前 {temp}°C，超过车间接标准 35°C，建议加强通风/开启降温")
    if temp is not None and temp < 10:
        alerts.append(f"低温提示：当前 {temp}°C，注意员工保暖")
    if humidity is not None and humidity > 85:
        alerts.append(f"湿度偏高：{humidity}%，注意电子元器件防潮/金属件防锈")
    if humidity is not None and humidity < 30:
        alerts.append(f"湿度偏低：{humidity}%，注意静电防护(ESD)")
    if wind is not None and wind > 40:
        alerts.append(f"大风预警：风速 {wind} km/h，注意室外作业安全")

    return {
        "factory_id": fid,
        "source": "当地公共气象数据(Open-Meteo)",
        "current": {
            "temperature_c": temp,
            "feels_like_c": feels,
            "humidity_pct": humidity,
            "precipitation_mm": precip,
            "wind_speed_kmh": wind,
            "pressure_hpa": pressure,
        },
        "assessment": "正常" if not alerts else "注意",
        "alerts": alerts,
        "observation_time": cur.get("time", ""),
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
    "run_compliance_simulation": _tool_run_compliance_simulation,
    "query_simulation_audits": _tool_query_simulation_audits,
    "complete_work_order": _tool_complete_work_order,
    "pause_work_order": _tool_pause_work_order,
    "resume_work_order": _tool_resume_work_order,
    "split_work_order": _tool_split_work_order,
    "query_routing": _tool_query_routing,
    "query_skill_matrix": _tool_query_skill_matrix,
    "run_workflow": _tool_run_workflow,
    "get_work_order_form": _tool_get_work_order_form,
    "get_inspection_form": _tool_get_inspection_form,
    "export_report_file": _tool_export_report_file,
    "get_pending_alerts": _tool_get_pending_alerts,
    "query_ocap_tasks": _tool_query_ocap_tasks,  # OCAP待办任务查询（chatbot集成）
    "query_alert_reviews": _tool_query_alert_reviews,
    "acknowledge_alert": _tool_acknowledge_alert,
    "run_alert_patrol": _tool_run_alert_patrol,
    "query_hr_roster": _tool_query_hr_roster,
    "query_process_knowledge": None,  # 占位，下方单独定义（不依赖数据库）
    # 5M1E 预警数据工具
    "query_downtime": _tool_query_downtime,
    "query_maintenance_due": _tool_query_maintenance_due,
    "query_shortage_alerts": _tool_query_shortage_alerts,
    "query_stagnant": _tool_query_stagnant,
    "query_spc_anomalies": _tool_query_spc_anomalies,
    "query_environment": _tool_query_environment,
}


async def _tool_query_process_knowledge(db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None) -> Dict[str, Any]:
    """流程知识查询（纯知识库，不访问数据库）。"""
    from api.services.process_knowledge_service import query_knowledge
    return query_knowledge(topic=args.get("topic", ""), keyword=args.get("keyword", ""))


_TOOL_EXECUTORS["query_process_knowledge"] = _tool_query_process_knowledge


async def _tool_query_collaboration(db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None) -> Dict[str, Any]:
    """岗位协同规则查询（事件规则/岗位边界/权限检查）。"""
    from api.services.collaboration_service import CollaborationService
    svc = CollaborationService(db)
    query_type = args.get("query_type", "event_rule")

    if query_type == "event_rule":
        event_key = args.get("event_key", "")
        if not event_key:
            return {"error": "请提供 event_key", "available_events": [
                "quality_incoming_fail", "quality_process_fail", "equipment_breakdown",
                "material_shortage", "delivery_risk", "urgent_order",
                "ecn_change", "shipment_ready", "supplier_delay", "safety_incident",
            ]}
        return await svc.query_event_rule(event_key)

    elif query_type == "role_boundary":
        role_key = args.get("role_key", "")
        if not role_key:
            return {"error": "请提供 role_key", "available_roles": [
                "operator", "team_leader", "workshop_manager", "qc_inspector",
                "qc_engineer", "warehouse_keeper", "buyer", "planner",
                "sales", "maintenance", "process_engineer",
            ]}
        return await svc.get_role_boundaries(role_key)

    elif query_type == "check_permission":
        role_key = args.get("role_key", "")
        action = args.get("action", "")
        if not role_key or not action:
            return {"error": "请提供 role_key 和 action"}
        return await svc.check_permission(role_key, action)

    return {"error": f"未知 query_type: {query_type}"}


_TOOL_EXECUTORS["query_collaboration"] = _tool_query_collaboration

# 写操作工具（需要记录操作人）
WRITE_TOOLS = {
    "create_work_order", "release_work_order", "create_production_report",
    "complete_work_order", "pause_work_order", "resume_work_order", "split_work_order",
    "run_compliance_simulation",
    "run_workflow",
    "export_report_file",
    "acknowledge_alert", "run_alert_patrol",
}

# 仿真类工具（前端展示用「仿真」色标，区别于写绿/查蓝）
SIM_TOOLS = {"run_compliance_simulation", "query_simulation_audits"}

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
    "run_compliance_simulation": "合规仿真",
    "query_simulation_audits": "仿真审计记录",
    "complete_work_order": "完工工单",
    "pause_work_order": "暂停工单",
    "resume_work_order": "恢复工单",
    "split_work_order": "拆分工单",
    "query_routing": "工艺路线",
    "query_skill_matrix": "技能矩阵",
    "run_workflow": "工作流编排",
    "get_work_order_form": "工单表单",
    "get_inspection_form": "检验单表单",
    "export_report_file": "导出报告",
    "get_pending_alerts": "预警汇总",
    "query_alert_reviews": "预警审查记录",
    "acknowledge_alert": "确认预警",
    "run_alert_patrol": "预警巡检",
    "query_ocap_tasks": "OCAP待办任务",
    "query_hr_roster": "人力档案",
    "query_process_knowledge": "流程知识",
    # 5M1E 预警数据工具
    "query_downtime": "停机记录",
    "query_maintenance_due": "保养到期",
    "query_shortage_alerts": "缺料预警",
    "query_stagnant": "呆滞物料",
    "query_spc_anomalies": "SPC失控",
    "query_environment": "车间环境",
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
    {
        # 仅对「查仿真记录」做确定性路由；「跑一次仿真」类参数需模型提取，交给 auto 循环
        "tool": "query_simulation_audits",
        "keywords": [
            "仿真记录", "仿真审计", "审计记录", "仿真历史", "查仿真", "最近仿真",
        ],
    },
    {
        "tool": "get_inspection_form",
        "keywords": [
            "检验单", "检验记录", "检验表单", "质检记录", "质检单", "质量检验单",
        ],
    },
    {
        "tool": "export_report_file",
        "keywords": [
            "导出报告", "导出报表", "生成报告", "生成报表", "报告导出", "导出生产报告",
            "导出成文件", "导出文件", "导出成", "导出为文件", "生成文件", "导出成csv",
        ],
    },
    {
        # 工单表单需工单号：resolve_intent 尝试轻量提取，提不到则交 auto 让模型提取
        "tool": "get_work_order_form",
        "keywords": [
            "工单表单", "工单完整表单", "完整工单表单", "工单全量信息",
        ],
    },
    # ==================== 5M1E 预警数据意图路由（具体优先于通用预警） ====================
    {
        "tool": "query_downtime",
        "keywords": [
            "停机", "停机记录", "故障记录", "MTBF", "设备利用率", "设备故障率",
            "停机时间", "故障次数", "设备停机", "停机原因",
        ],
    },
    {
        "tool": "query_maintenance_due",
        "keywords": [
            "保养到期", "维保", "预防性维护", "保养计划", "维护到期",
            "设备保养", "逾期保养", "PM到期", "维护计划",
        ],
    },
    {
        "tool": "query_shortage_alerts",
        "keywords": [
            "缺料", "补货", "低于安全库存", "缺料预警", "物料不足",
            "库存不足", "低于最低水位", "补货预警", "缺料清单",
        ],
    },
    {
        "tool": "query_stagnant",
        "keywords": [
            "呆滞", "滞料", "呆滞物料", "长期不动", "库存积压",
            "无流动", "呆滞料", "滞库", "积压物料",
        ],
    },
    {
        "tool": "query_spc_anomalies",
        "keywords": [
            "SPC", "失控", "越限", "过程能力", "控制图", "超出控制限",
            "SPC异常", "质量失控", "UCL", "LCL", "过程异常",
        ],
    },
    {
        "tool": "query_environment",
        "keywords": [
            "环境", "温度", "湿度", "车间环境", "天气", "风速",
            "降温", "静电", "ESD", "环境温度", "车间温度",
        ],
    },
    {
        "tool": "query_routing",
        "keywords": [
            "工艺路线", "工序", "加工步骤", "工艺流程", "产品工艺",
            "工艺查询", "路线查询", "工序查询",
        ],
    },
    {
        "tool": "query_skill_matrix",
        "keywords": [
            "技能矩阵", "技能等级", "技能分布", "员工技能", "技能断层",
            "谁会", "技能情况", "多能工", "技能覆盖",
        ],
    },
    # ==================== 通用预警/巡检（放在 5M1E 具体规则之后） ====================
    {
        "tool": "get_pending_alerts",
        "keywords": [
            "预警", "告警", "警报", "异常汇报", "待处理预警", "当前异常",
            "有什么预警", "预警情况", "告警情况", "预警汇总",
        ],
    },
    {
        "tool": "run_alert_patrol",
        "keywords": [
            "巡检", "扫描异常", "主动巡检", "预警巡检", "扫描预警",
        ],
    },
    {
        "tool": "query_hr_roster",
        "keywords": [
            "人力", "花名册", "人员分布", "多少人", "人力档案", "员工",
            "人事", "部门人数", "工序人数", "人力统计", "人员配置",
            "编制", "人力配置", "车间人数",
        ],
    },
    {
        "tool": "query_process_knowledge",
        "keywords": [
            # 工单流
            "工单流程", "工单生命周期", "工单流转", "下达流程", "报工流程",
            "完工流程", "工单状态流转", "工单各阶段", "工单环节",
            # 职位流
            "品检员做什么", "操作员职责", "PMC流程", "主管职责", "仓管员职责",
            "设备工程师职责", "日常工作流", "SOP", "标准作业", "岗位职责",
            "职位流程", "工作流程是什么", "每天做什么",
            # 责任归属
            "该找谁", "谁负责", "卡在", "超时找谁", "责任归属", "谁审批", "谁执行",
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


# 工单码轻量提取正则：形如 WO-SPK-DEMO_2026 / ELEC-S20260723-001（大写字母数字开头 + 连字符段）
_WO_CODE_RE = re.compile(r"\b[A-Z][A-Z0-9]+-[A-Za-z0-9_-]+")


def _extract_wo_code(message: str) -> Optional[str]:
    """从消息中轻量提取工单码候选（用于确定性路由的工单表单/导出）。提不到返回 None。"""
    if not message:
        return None
    m = _WO_CODE_RE.search(message)
    return m.group(0) if m else None


def resolve_intent(message: str) -> Optional[Dict[str, Any]]:
    """确定性意图解析：命中业务关键词返回 {"tool", "args"}，否则 None。

    后端可据此直接执行工具取真实数据（不依赖模型决策），args 通过轻量关键词规则提取。
    写操作/多步操作不走此路径，仍由模型 auto 编排。

    优先级：工作流触发词（复合任务）> 单步查询工具。"""
    # 优先匹配工作流（复合任务，如「帮我复盘今天生产」→ daily_production_review）
    # 懒加载避免与 workflow_service 的顶层循环导入；match_workflow 仅返回无需参数的工作流
    from api.services.workflow_service import match_workflow  # 懒加载，避免循环导入
    wf_name = match_workflow(message)
    if wf_name:
        return {"tool": "run_workflow", "args": {"workflow_name": wf_name, "params": {}}}

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
    elif tool == "get_work_order_form":
        # 工单表单需工单号：轻量提取形如 WO-xxx / ELEC-S20260723-001 的工单码；提不到则交 auto 让模型提取
        wo_code = _extract_wo_code(message)
        if not wo_code:
            return None
        args["work_order_code"] = wo_code
    elif tool == "get_inspection_form":
        # 检验单：可选按工单过滤（提到工单号则带上）
        wo_code = _extract_wo_code(message)
        if wo_code:
            args["work_order_code"] = wo_code
    elif tool == "export_report_file":
        # 默认导出生产汇总；消息含工单号且提及工单 → 导出工单表单
        wo_code = _extract_wo_code(message)
        if wo_code and "工单" in message:
            args["report_type"] = "work_order"
            args["work_order_code"] = wo_code
        else:
            args["report_type"] = "production_summary"
        args["format"] = "csv" if any(k in message for k in ["csv", "CSV", "表格"]) else "json"
    elif tool == "query_process_knowledge":
        # 轻量提取 topic 与 keyword：
        # 1) 责任归属类："该找谁/谁负责/卡在/超时找谁" → who_handles + 阶段关键词
        if any(k in message for k in ["该找谁", "谁负责", "卡在", "超时找谁", "责任归属", "谁审批", "谁执行"]):
            args["topic"] = "who_handles"
            for stage_kw in ["创建", "下达", "审批", "派工", "执行", "报工", "质检", "完工", "入库", "关闭"]:
                if stage_kw in message:
                    args["keyword"] = stage_kw
                    break
        # 2) 职位流类：消息含职位关键词 → position_sop
        elif any(k in message for k in [
            "品检", "操作员", "PMC", "计划员", "主管", "仓管", "设备工程",
            "机修", "质检员", "IPQC", "生管", "岗位职责", "SOP", "标准作业",
            "日常工作流", "每天做什么", "职位流程", "工作职责",
        ]):
            args["topic"] = "position_sop"
            for pos_kw in ["品检", "操作员", "PMC", "计划员", "主管", "仓管", "设备工程", "机修", "质检", "IPQC", "生管"]:
                if pos_kw in message:
                    args["keyword"] = pos_kw
                    break
        # 3) 工单流类
        elif any(k in message for k in [
            "工单流程", "工单生命周期", "工单流转", "下达流程", "报工流程",
            "完工流程", "工单状态流转", "工单各阶段", "工单环节",
        ]):
            args["topic"] = "work_order_flow"
            for stage_kw in ["创建", "下达", "审批", "派工", "执行", "报工", "质检", "完工", "入库", "关闭"]:
                if stage_kw in message:
                    args["keyword"] = stage_kw
                    break
    return {"tool": tool, "args": args}


async def execute_tool(
    db: AsyncSession,
    tool_name: str,
    arguments: Dict[str, Any],
    operator: str = "ai_assistant",
    factory_id: Optional[str] = None,
) -> Dict[str, Any]:
    """执行指定工具，返回结构化结果。未知工具或异常时返回 error 字段。

    factory_id：当前用户所属工厂。查询类工具据此过滤，保证与页面口径一致（多工厂数据隔离）；
    写操作工具自行从产品/工单推导工厂，不受此参数影响。"""
    executor = _TOOL_EXECUTORS.get(tool_name)
    if not executor:
        return {"error": f"未知工具：{tool_name}"}
    try:
        if tool_name in WRITE_TOOLS:
            return await executor(db, arguments, operator)
        return await executor(db, arguments, factory_id)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"工具执行失败：{type(exc).__name__}: {exc}"}


__all__ = ["TOOL_DEFINITIONS", "TOOL_LABELS", "WRITE_TOOLS", "SIM_TOOLS", "execute_tool", "detect_intent_tool", "resolve_intent", "INTENT_RULES"]
