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
import asyncio
import io
import json
import re
import uuid
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text

from database.models import (
    WorkOrder, ProductionReport, Station, Equipment, Product,
    Inventory, DefectRecord, User, Routing, FileRecord, QualityInspection, WorkbookRecord,
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
from api.services.workbook_service import (
    apply_workbook_operations,
    build_pivot_summary,
    recalculate_workbook_file,
    scan_formula_dependencies,
    snapshot_to_table,
    workbook_export_basename,
    xlsx_to_workbook_snapshot,
    workbook_snapshot_to_xlsx,
)


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
            "name": "query_order_work_order_status",
            "description": "核对销售订单是否已拆分并下发生产工单。明确区分：订单是否已经生成主工单/工序工单，以及工序工单是否全部为released，不能用普通工单列表代替。",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_code": {"type": "string", "description": "销售订单号，可选，如 SO-VF-260801-CEC6"},
                    "virtual_only": {"type": "boolean", "description": "只核对虚拟工厂订单，可选"},
                    "created_today": {"type": "boolean", "description": "只核对今天创建的订单，可选"},
                    "limit": {"type": "integer", "description": "订单条数，默认20", "default": 20},
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
            "name": "query_pmc_material_supply",
            "description": "PMC供应证据查询：把库存、库存最后流动/账龄、BOM可复用产品、未收货PO、在途数量、PO编号、供应商和ETA关联起来。用于回答‘库存多少、在途多少、PO编号多少、哪些180天呆滞料还能被BOM使用、物料LT/ETA’等问题；只返回真实数据，缺少采购表时明确标记。",
            "parameters": {
                "type": "object",
                "properties": {
                    "material_keyword": {"type": "string", "description": "物料编码或名称关键词，可选"},
                    "days": {"type": "integer", "description": "呆滞阈值，默认180天", "default": 180},
                    "only_stagnant": {"type": "boolean", "description": "只返回超过阈值的呆滞料，可选", "default": False},
                    "limit": {"type": "integer", "description": "返回条数，默认50", "default": 50},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_lead_time_evidence",
            "description": "提前期证据普查（只读）：回答『这个料号的提前期是量出来的还是台账铺的默认值』『台账说 12 天能不能信』『哪批件的提前期最该去实测』。并列四个出处：materials 台账、采购下单→实际到货实测（条数/中位/P90/最长）、仓收实测、供应商声明；每件给 verdict（measured / ledger_default_conflicts_with_measured / unverified_default / ledger_declared_only / no_lead_time_at_all），并摊开台账与实测的冲突。建议值只在 suggested_days，不回填台账。",
            "parameters": {
                "type": "object",
                "properties": {
                    "material_codes": {"type": "string", "description": "逗号分隔的料号；不填就按厂区抽样普查"},
                    "limit": {"type": "integer", "description": "返回行数上限，默认 30", "default": 30},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_pmc_rush_impact",
            "description": "PMC插单影响沙盘：根据现有待排主工单和插单数量，返回VIP/急单预计加工时间、受影响订单、原交期、新预计完工时间和延迟小时。只读不落库。",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "string", "description": "急单产品编码"},
                    "quantity": {"type": "integer", "description": "急单数量"},
                    "due_date": {"type": "string", "description": "急单交期，ISO日期，可选"},
                    "capacity_share": {"type": "number", "description": "急单占用产能比例，默认0.5", "default": 0.5},
                },
                "required": ["quantity"],
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
            "description": "把数据导出为文件（JSON/CSV），写入系统文件表并返回下载链接。用于「导出报告/生成报表/做个表格分享」类请求。支持多种报告类型。",
            "parameters": {
                "type": "object",
                "properties": {
                    "report_type": {
                        "type": "string",
                        "enum": ["production_summary", "work_order", "attendance", "employee_list"],
                        "description": "报告类型：production_summary生产汇总 / work_order工单表单 / attendance考勤统计 / employee_list员工花名册",
                        "default": "production_summary",
                    },
                    "work_order_code": {"type": "string", "description": "工单号（report_type=work_order 时必填）"},
                    "format": {"type": "string", "enum": ["json", "csv"], "description": "文件格式，默认csv", "default": "csv"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scan_online_workbook",
            "description": "扫描在线工作簿全部工作表、任意位置的公式，并返回跨工作表/跨区域引用、依赖关系、被依赖单元格、动态引用和计算引擎状态。公式函数即使暂不被服务器计算，也必须被扫描和关联；不要只扫描前100行或前50列。",
            "parameters": {
                "type": "object",
                "properties": {
                    "workbook_id": {"type": "string", "description": "当前在线工作簿ID；系统会在当前会话上下文中提供"},
                    "sheet_name": {"type": "string", "description": "限定某个工作表，可选；不传扫描全部工作表"},
                },
                "required": ["workbook_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_online_workbook",
            "description": "读取当前绑定的在线工作簿内容，返回指定工作表的表头、行数据、任意位置公式数量和最近计算状态。用户询问当前在线表格内容、公式或数据时使用。只能读取当前用户工厂的工作簿。",
            "parameters": {
                "type": "object",
                "properties": {
                    "workbook_id": {"type": "string", "description": "当前在线工作簿ID；系统会在当前会话上下文中提供"},
                    "sheet_name": {"type": "string", "description": "工作表名称，可选；不传读取第一张工作表"},
                },
                "required": ["workbook_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recalculate_online_workbook",
            "description": "按当前在线工作簿中的全部数据和公式重新计算并把结果写回自己的工作簿快照；不回退、不覆盖用户数据。优先使用真实 Excel 兼容计算引擎，失败时保留公式和原缓存值并返回原因。",
            "parameters": {
                "type": "object",
                "properties": {
                    "workbook_id": {"type": "string", "description": "当前在线工作簿ID；系统会在当前会话上下文中提供"},
                    "sheet_name": {"type": "string", "description": "重算后返回的工作表名称，可选"},
                },
                "required": ["workbook_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reload_online_workbook",
            "description": "从当前在线工作簿绑定的原始上传 XLSX 重新加载全部工作表、公式和数据，恢复为上传文件版本；这是明确的回滚/重载动作，只在用户明确要求重新加载原始文件时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "workbook_id": {"type": "string", "description": "当前在线工作簿ID；系统会在当前会话上下文中提供"},
                },
                "required": ["workbook_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_online_workbook",
            "description": "按用户明确要求修改当前在线工作簿任意工作表、任意单元格。支持 set_cell/set_formula/clear_cell/append_rows/flash_fill；修改后立即保存并重算全部公式，公式文本和跨表引用保留。公式函数不设白名单，用户给出的 Excel 公式原样写入；涉及批量改动、公式改写或删除数据时，只执行用户明确指定的操作。",
            "parameters": {
                "type": "object",
                "properties": {
                    "workbook_id": {"type": "string", "description": "当前在线工作簿ID；系统会在当前会话上下文中提供"},
                    "sheet_name": {"type": "string", "description": "修改后返回的工作表名称，可选"},
                    "operations": {
                        "type": "array",
                        "description": "明确的单元格操作列表。例：[{type:'set_formula',sheet:'MRP',cell:'F2',formula:'=D2-E2'}]",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": ["set_cell", "set_value", "set_formula", "clear_cell", "append_rows", "flash_fill"]},
                                "sheet": {"type": "string"},
                                "cell": {"type": "string"},
                                "value": {},
                                "formula": {"type": "string"},
                                "rows": {"type": "array", "items": {"type": "array", "items": {}}},
                                "start_row": {"type": "integer"},
                                "source_column": {"type": "string", "description": "快速填充源列，例如 A"},
                                "target_column": {"type": "string", "description": "快速填充目标列，例如 B"},
                                "end_row": {"type": "integer"},
                                "overwrite": {"type": "boolean", "default": False},
                            },
                            "required": ["type", "sheet"],
                        },
                    },
                    "edits": {
                        "type": "array",
                        "description": "兼容旧版调用的单元格编辑列表；没有 type/sheet 时默认按 set_cell 和第一张工作表处理",
                        "items": {"type": "object"},
                    },
                    "name": {"type": "string", "description": "可选：修改在线工作簿显示名称/导出文件名"},
                },
                "required": ["workbook_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_online_workbook",
            "description": "把当前绑定的在线工作簿导出为 XLSX 文件。导出保留多个 Sheet、单元格公式和基础样式，并返回下载文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "workbook_id": {"type": "string", "description": "当前在线工作簿ID；系统会在当前会话上下文中提供"},
                },
                "required": ["workbook_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_online_pivot",
            "description": "把当前在线工作簿的明细按指定行字段做基础透视汇总，生成或刷新一个透视汇总 Sheet。支持 sum/count/avg。",
            "parameters": {
                "type": "object",
                "properties": {
                    "workbook_id": {"type": "string"},
                    "sheet": {"type": "string", "description": "明细工作表名称，可选"},
                    "row_field": {"type": "string", "description": "分组行字段，必须是表头名称"},
                    "value_field": {"type": "string", "description": "汇总数值字段，必须是表头名称"},
                    "aggregation": {"type": "string", "enum": ["sum", "count", "avg"], "default": "sum"},
                    "output_sheet_name": {"type": "string", "default": "透视汇总"},
                },
                "required": ["workbook_id", "row_field", "value_field"],
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
            "parameters": {
                "type": "object",
                "properties": {
                    "factory_id": {"type": "string", "description": "工厂ID，可选，默认当前用户工厂"},
                    "operator": {"type": "string", "description": "操作用户ID，必填"},
                    "limit": {"type": "integer", "description": "返回条数，默认10", "default": 10},
                },
                "required": ["operator"],
            },
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
            "name": "query_workflow_diagram",
            "description": "在模型识别出明确流程对象和范围后，由流程引擎生成一张完整连通图。必须区分：独立业务子流程、岗位端到端流程、审批实例；用户点名某个子流程时不得展开其父岗位流程。PMC端到端必须传 scope=position_end_to_end 且 workflow_key=pmc:end_to_end；其他已注册示例：替代料验证=process:alternate_material_validation，生产工单全生命周期=process:work_order_lifecycle，其他岗位=position:<key>。对象不明确时先追问；未知注册键返回目录，严禁回退到PMC或最近DCC审批。",
            "parameters": {
                "type": "object",
                "properties": {
                    "flow_id": {"type": "string", "description": "流程实例ID，可选"},
                    "flow_code": {"type": "string", "description": "流程编码，可选，如 FLOW-20260810-ABC123"},
                    "task_type": {"type": "string", "description": "按关联任务类型筛选，可选"},
                    "position": {"type": "string", "description": "岗位名称或别名，如 PMC、品检员、操作员、生产主管"},
                    "process_name": {"type": "string", "description": "用户点名的独立业务流程名称，如 发起替代料验证；不得填其父岗位名称"},
                    "scope": {"type": "string", "enum": ["standalone_process", "position_end_to_end", "approval_instance"], "description": "用户要求的流程范围"},
                    "workflow_key": {"type": "string", "description": "精确业务流程注册键，如 process:alternate_material_validation、process:work_order_lifecycle、pmc:end_to_end、position:ipqc"},
                    "current_step": {"type": "integer", "minimum": 1, "description": "希望重点查看的当前步骤，按1开始"},
                    "engine_type": {"type": "string", "enum": ["auto", "business", "approval"], "description": "流程来源；岗位流程用business，审批实例用approval，默认auto"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_pmc_work_matrix",
            "description": "查询指定主工单的 PMC 工作矩阵，并可用时间锤、物料锤、生产锤、出货锤、紧急锤做不落库的预排程沙盘重算。返回需求量、RDD、UHN、可加工时间、库存齐套、产能判定、ETA、风险和下一步重点；所有真实数据缺失会明确标记。",
            "parameters": {
                "type": "object",
                "properties": {
                    "work_order_code": {"type": "string", "description": "主工单号，如 WO-ABC-001"},
                    "options": {
                        "type": "object",
                        "description": "可选沙盘开关：skip_vietnam_holidays、shift_mode、iqc_mode、substitute_material_available、yield_rate、line_occupancy、container_hours、customs_mode、enable_air_freight、accept_subcontracting。",
                        "properties": {
                            "skip_vietnam_holidays": {"type": "boolean"},
                            "shift_mode": {"type": "string", "enum": ["single", "double"]},
                            "iqc_mode": {"type": "string", "enum": ["exempt", "sampling", "full"]},
                            "dead_stock_days": {"type": "integer", "minimum": 0, "description": "呆滞阈值，默认180天"},
                            "material_eta_delay_days": {"type": "number", "minimum": 0, "description": "模拟物料ETA延迟天数"},
                            "substitute_material_available": {"type": "boolean"},
                            "yield_rate": {"type": "number", "minimum": 0.5, "maximum": 1.0},
                            "line_occupancy": {"type": "string", "enum": ["exclusive", "shared_50"]},
                            "container_hours": {"type": "number", "minimum": 0},
                            "customs_mode": {"type": "string", "enum": ["none", "random"]},
                            "enable_air_freight": {"type": "boolean"},
                            "accept_subcontracting": {"type": "boolean"},
                        },
                    },
                },
                "required": ["work_order_code"],
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
            "name": "query_pmc_control_tower",
            "description": "PMC统一控制塔事实查询。一次查询可回答：排过多少订单、控过多少物料、Shortage如何处理、库存如何降低、OTD如何保证、产能如何平衡、紧急插单如何排、EC/BOM变更如何处理、supplier delay如何处理。问“交期风险/会不会迟到”用 scope=otd：其中的 at_risk_in_progress_count 是按实际生产速度推算赶不上交期的在制工单数（与交期智能体同一实现），at_risk_high_count 是其中距交期不足 3 天的数量。返回当前工厂真实记录、统计口径、数据缺口和处理流程；只读不修改排程，不把建议说成已执行动作。",
            "parameters": {
                "type": "object",
                "properties": {
                    "scope": {
                        "type": "string",
                        "enum": ["all", "orders", "materials", "shortage", "inventory", "otd", "capacity", "rush", "engineering_change", "supplier_delay"],
                        "description": "问题范围；交期风险/会不会迟到属于 otd；复合问题用 all",
                        "default": "all",
                    },
                    "material_keyword": {"type": "string", "description": "物料编码或名称关键词，可选"},
                    "work_order_code": {"type": "string", "description": "主工单号，可选"},
                    "days": {"type": "integer", "description": "呆滞判定天数，默认180天", "default": 180},
                    "rush_quantity": {"type": "integer", "description": "若询问具体急单，可提供插单数量，触发只读沙盘"},
                    "rush_due_date": {"type": "string", "description": "急单交期，YYYY-MM-DD，可选"},
                    "limit": {"type": "integer", "description": "明细条数上限，默认20", "default": 20},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_manufacturing_intelligence",
            "description": "查询当前工厂的制造智能总览：统一核对 Chatbot/Harness、PMC控制塔、待处理预警和 Sim-ERP 的运行状态，并返回基于真实PMC事实生成的缺料、产能、OTD、供应商延迟、呆滞库存等风险信号。只读，不执行排程或处置动作。",
            "parameters": {"type": "object", "properties": {}},
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
            "name": "query_bom_data_quality",
            "description": "BOM 数据质量自检（只读）：名称就是料号、品名过于笼统、缺物料分类、缺单位、单价形状异常、图纸行当物料、层级断链、同料号多父级。每条带 affected_shortage_qty 并按影响缺口排序。用于 BOM 有什么问题 / 哪些命名不规范 / 该提哪条 ECR / 为什么这版 BOM 推不出自制路线 这类问题。只报问题，不修改任何 BOM 原始行。",
            "parameters": {"type": "object", "properties": {
                "product_model": {"type": "string", "description": "机种型号（= BOM 的 model_name）；不给就用当前厂区行数最多的机种"}
            }},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_chain_convergence",
            "description": "无人链条收敛自检（只读）：工厂这一轮到底有没有往前走。给出开放工单池、子工单数、真的完工了几张、由就绪门放行几张、缺口件数、近 24 小时有没有真实报工，并与上一轮引擎心跳的读数对撞后给出 advancing / diverging / stalled 判定与支撑它的增减量。用于'工厂在推进还是停滞''积压在涨还是消''有没有空转''完工进展''链条卡在哪'类问题。判定规则随结果一起返回，别人可以用同一串数字复算。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_simulation_recommendation",
            "description": (
                "政策×天气推演的最新结论与落地复查（只读）：稳健推荐是哪条政策、它要花多少钱"
                "（加急/开线/人工），引擎准备发出的动作清单（催哪个料号、向哪家供应商、几号前下单、"
                "几号前要到、哪台单先开几台、第二批排在哪天），上一轮建议到底有没有落地"
                "（主档提前期压下来没有、有没有开过采购单、缺供应商的料号补齐没有），"
                "以及三个天气场景各自有没有区分度。用于'引擎在建议什么''要不要加急''该催哪个料'"
                "'上次的建议做了没''推演有没有效果''开第二条线划不划算''哪些机种还推演不了'类问题。"
                "只念记分卡里那张卡，不重跑扫描；不下单、不改排产、不写真实系统。"),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_simulation_sensitivity",
            "description": (
                "仿真引擎的量化读数（只读）：组合完工日、延几天、人工/加急/开线各多少钱；"
                "每个输入动一档的局部斜率（单件工时±10%、外购提前期×0.5、可用库存×1.5、"
                "到岗率±0.05、设备可用率±0.05、批量±1天产量、并联开线、加班加人、承诺交期系数），"
                "换算成'值几天、每天值多少钱、救回几台准点'；映射精度（每项输入有多少真依据、"
                "允许误差多大）；以及误差传导 —— 现在这个交期可信到几成、把哪项数据补到可信能压掉几天。"
                "用于'补 IE 工时值多少''加急值几天''该不该开第二条线''加班划不划算'"
                "'这个交期有多可信''哪个杠杆最值钱''数据补齐能改善多少'类问题。不写任何系统。"),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_engine_attribution",
            "description": (
                "引擎的因果归因（只读，走对外契约接口 attribution）：现在这个完工日被哪一项卡住"
                "（等料 / 排队 / 做不完 / 日历），逐台点名；松掉每一项业务输入一档实测值几天"
                "（斜率是逐档真跑出来的，不是权重打分）；当前交期可信到几成、不确定天数分摊在"
                "哪几项数据上；带 compare（两组业务输入，如提前期 100%→50%、到岗 0.70→1.00）时"
                "给出总差值、各项单项效果与交互残差 —— 残差不为 0 就说明各项互相挡着，"
                "不许按单项比例分摊。用于'为什么交期是这天''这台单卡在哪儿''为什么改条件差这么多'"
                "'该先松哪个约束'类问题。只说业务概念，不暴露模型内部；不写任何系统。"),
            "parameters": {"type": "object", "properties": {
                "models": {"type": "array", "items": {"type": "string"},
                           "description": "机种编码；不填则取 BOM 最完整的 3 台"},
                "weather": {"type": "string", "enum": ["fair", "rain", "storm"]},
                "compare": {"type": "object",
                            "description": "可选 {baseline: {业务输入名: 值}, alternative: {同}}"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_engine_capability_layers",
            "description": (
                "仿真引擎的分层验收（只读）：L1 内核（单轮耗时/可复现率/崩溃率）、"
                "L2A 敏感度（弹性可算覆盖率、已知冲击的方向命中率、弹性置信区间）、"
                "L2B 准确度（瓶颈位置命中率、回测 MAPE、输入映射精度）、"
                "L3 决策（推荐相对基线的再跑差值、人工采纳率、推荐翻转率）、"
                "L4 Agent 接口（问法→工具命中率、回答真调工具比例、数字可回溯率）。"
                "每层判据不同且都是算出来的数；自下而上第一个不过线的层以上，读数标 reportable=false —— "
                "用于「你们引擎到底行不行」「哪层是短板」「这些数字能对外说吗」类问题。"),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_sim_evidence_readiness",
            "description": (
                "仿真精度判据的证据就绪度（只读）：L2B 那两个数（瓶颈件一致率、回测 MAPE）"
                "到底有多少真实样本可比 —— 逐机种报 工单数/齐套行/外购缺口行，把没有齐套行的单"
                "归成四类可行动原因（子工单没自己的 BOM、键在镜像里根本没 BOM 行、出货柜这类伪产品、"
                "种子演示单），并报台账齐套行的**登记世代**（多数单还是旧的单层快照，"
                "同机种多层登记过的能到 680 行、深 9 层）；带 agreement=true 时同时给出"
                "瓶颈件一致率的三种分母：快照口径、同宇宙口径（两边都点到名的单）、"
                "同世代对照（台账行不动、缺口按今天库存重算），以及毛/净需求算法差的行数分布。"
                "用于「先补哪个数据」「样本够不够」「为什么命中率上不去」「这些单为什么没齐套行」"
                "「一致率低是谁的锅」类问题。不改工单、不写台账。"),
            "parameters": {"type": "object", "properties": {
                "agreement": {"type": "boolean",
                              "description": "是否连瓶颈件一致率的三种分母一起算（要多跑一遍展开，默认算）"},
                "limit": {"type": "integer", "description": "参与比对的在流程单数上限，默认 40"}}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_plan_commit_gate",
            "description": "计划逐单下达就绪门（只读）：这一版排程里哪些工单真的能开工、哪些被哪条门压住（没排进本版本/工序没排齐/物料没齐套/首道工位映射不到），以及已经下达过的张数。用于'这版计划能开工几张''还有哪些单卡着''为什么没下达''计划生效了没'类问题。只报判定，不改工单状态、不下达。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_wms_inventory_health",
            "description": "WMS 库存健康度汇总：SKU 数、有单价的库存金额覆盖、周转（按真实消耗口径 production_out/outbound）、呆滞、效期、低库存、过量、补货建议，并同批返回覆盖率与不可计算项（库位容量、满载率、入库流水缺失、效期无值等）。用于'库存健康''周转''呆滞''该补什么''是否过量''库位满载'类问题；不要用 query_inventory 的行级明细替代这个汇总。",
            "parameters": {
                "type": "object",
                "properties": {
                    "dead_stock_days": {"type": "integer", "description": "呆滞天数阈值，默认60", "default": 60},
                    "expiry_warn_days": {"type": "integer", "description": "效期预警提前天数，默认30", "default": 30},
                    "turnover_days": {"type": "integer", "description": "周转统计窗口天数，默认90", "default": 90}
                }
            }
        }
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
            "description": "查询呆滞物料：默认超过180天无库存流动的物料，并关联BOM可复用产品、未收货PO和在途数量。用于'呆滞''滞料''库龄''长期不动'类请求。",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "呆滞天数阈值（默认180天无流动）", "default": 180},
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
    {
        "type": "function",
        "function": {
            "name": "create_followup_task",
            "description": "把暂时无法一次完成的任务挂入任务中心持续跟进（等物料/等审批/等设备恢复/等供应商等场景）。系统会按设定频率定期用工具核实进展，完成/受阻时推送通知。当用户交代的事情当前无法闭环、或用户说'跟进一下''盯着''挂起来''到时候提醒我'时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "任务标题（一句话，如'跟进 WO-20260730-001 缺料到货'）"},
                    "description": {"type": "string", "description": "任务详情/用户原始指令，可选"},
                    "block_reason": {"type": "string", "description": "当前无法完成的原因（如'等供应商交货'），可选"},
                    "follow_interval_minutes": {"type": "integer", "description": "跟进频率（分钟），默认120（2小时），最小15", "default": 120},
                    "agent_key": {"type": "string", "description": "负责跟进的智能体 key（dispatch_agent/procurement_agent/quality_agent/delivery_agent/escalation_agent/equipment_agent/scheduling_agent/warehouse_agent），不传则自动归类"},
                },
                "required": ["title"],
            },
        },
    },
]

TOOL_DEFINITIONS.extend([
    {
        "type": "function",
        "function": {
            "name": "get_virtual_factory_status",
            "description": "查询虚拟工厂脉搏状态：当前虚拟销售订单、主工单、进度、报工数量。用于回答'虚拟工厂现在怎样/数据脉搏/订单节奏'类问题。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_virtual_factory_pulse",
            "description": "主动推进一次虚拟工厂脉搏：按月产能和订单周期创建销售订单、拆主/工序工单、按日节奏报工并生成节奏预警。不是秒完订单。",
            "parameters": {
                "type": "object",
                "properties": {
                    "monthly_capacity_containers": {
                        "type": "integer",
                        "description": "月出货产能（柜/月），默认300",
                        "default": 300,
                    },
                    "order_lead_days": {
                        "type": "integer",
                        "description": "订单周期天数，默认90天",
                        "default": 90,
                    },
                    "target_active_orders": {
                        "type": "integer",
                        "description": "希望维持的虚拟在制主订单数，默认6",
                        "default": 6,
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_entity",
            "description": "全站精确搜索：按编码或名称跨模块查找实体（工位、设备、产品、工单、员工、仓库、库存、用户）。当用户提到具体编码（如 ST-ZL-01、EQ-CNC-01、WO-MECH-001）或问'xxx属于哪个部门/是什么/在哪'时，必须先调用此工具获取精确结果，禁止猜测。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "搜索关键词（编码或名称片段）"},
                },
                "required": ["keyword"],
            },
        },
    },
])


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
    limit = max(1, min(int(args.get("limit", 10)), 50))
    filters = []
    if factory_id:
        filters.append(WorkOrder.factory_id == factory_id)
    if args.get("status"):
        filters.append(WorkOrder.status == args["status"])
    total_result = await db.execute(select(func.count(WorkOrder.id)).where(*filters))
    total = int(total_result.scalar_one() or 0)
    stmt = select(WorkOrder).where(*filters).order_by(WorkOrder.created_at.desc()).limit(limit)
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
    return {
        "count": total,
        "total": total,
        "returned_count": len(items),
        "has_more": total > len(items),
        "work_orders": items,
    }


async def _tool_query_order_work_order_status(
    db: AsyncSession,
    args: Dict[str, Any],
    factory_id: Optional[str] = None,
) -> Dict[str, Any]:
    """核对销售订单到生产工单的完整覆盖与下达状态。"""
    limit = max(1, min(int(args.get("limit", 20)), 50))
    where = ["so.factory_id = :factory_id"]
    params: Dict[str, Any] = {"factory_id": factory_id or "FAC_MECH_001", "limit": limit}

    order_code = str(args.get("order_code") or "").strip()
    if order_code:
        where.append("so.order_code ILIKE :order_pattern")
        params["order_pattern"] = f"%{order_code}%"
    if args.get("virtual_only"):
        where.append("so.remark LIKE :virtual_marker")
        params["virtual_marker"] = "%[virtual_factory]%"
    if args.get("created_today"):
        where.append("so.created_at >= CURRENT_DATE")

    where_sql = " AND ".join(where)
    total_result = await db.execute(
        text(f"SELECT count(*) FROM sales_orders so WHERE {where_sql}"),
        params,
    )
    total = int(total_result.scalar_one() or 0)

    rows_result = await db.execute(text(f"""
        SELECT
            so.id AS sales_order_id,
            so.order_code AS sales_order_code,
            so.status AS sales_order_status,
            so.quantity,
            so.delivery_date,
            so.decomposed,
            so.work_order_ids,
            so.created_at,
            COUNT(wo.id) AS actual_work_order_count,
            COUNT(wo.id) FILTER (WHERE wo.wo_type = 'master') AS master_count,
            MAX(wo.work_order_code) FILTER (WHERE wo.wo_type = 'master') AS master_work_order_code,
            MAX(wo.status) FILTER (WHERE wo.wo_type = 'master') AS master_status,
            COUNT(wo.id) FILTER (WHERE wo.wo_type = 'operation') AS operation_work_order_count,
            COUNT(wo.id) FILTER (WHERE wo.wo_type = 'operation' AND wo.status = 'released') AS released_operation_count,
            COUNT(wo.id) FILTER (WHERE wo.wo_type = 'operation' AND wo.status = 'pending') AS pending_operation_count,
            COUNT(wo.id) FILTER (WHERE wo.wo_type = 'operation' AND wo.status = 'in_progress') AS in_progress_operation_count,
            COUNT(wo.id) FILTER (WHERE wo.wo_type = 'operation' AND wo.status = 'completed') AS completed_operation_count
        FROM sales_orders so
        LEFT JOIN work_orders wo ON wo.sales_order_id IN (so.id, so.order_code)
        WHERE {where_sql}
        GROUP BY so.id, so.order_code, so.status, so.quantity, so.delivery_date,
                 so.decomposed, so.work_order_ids, so.created_at
        ORDER BY so.created_at DESC
        LIMIT :limit
    """), params)
    rows = rows_result.mappings().all()

    orders: List[Dict[str, Any]] = []
    for row in rows:
        try:
            linked_ids = json.loads(row.get("work_order_ids") or "[]")
            linked_count = len(linked_ids) if isinstance(linked_ids, list) else 0
        except (TypeError, ValueError, json.JSONDecodeError):
            linked_count = 0

        actual_count = int(row.get("actual_work_order_count") or 0)
        master_count = int(row.get("master_count") or 0)
        operation_count = int(row.get("operation_work_order_count") or 0)
        released_count = int(row.get("released_operation_count") or 0)
        decomposed_complete = bool(
            row.get("decomposed") and linked_count > 0 and actual_count > 0 and master_count > 0
        )
        all_operations_released = operation_count > 0 and released_count == operation_count
        orders.append({
            "sales_order_id": row.get("sales_order_id"),
            "sales_order_code": row.get("sales_order_code"),
            "sales_order_status": row.get("sales_order_status"),
            "quantity": row.get("quantity"),
            "delivery_date": row.get("delivery_date").isoformat() if row.get("delivery_date") else None,
            "decomposed": bool(row.get("decomposed")),
            "linked_work_order_count": linked_count,
            "actual_work_order_count": actual_count,
            "master_work_order_code": row.get("master_work_order_code"),
            "master_status": row.get("master_status"),
            "operation_work_order_count": operation_count,
            "released_operation_count": released_count,
            "pending_operation_count": int(row.get("pending_operation_count") or 0),
            "in_progress_operation_count": int(row.get("in_progress_operation_count") or 0),
            "completed_operation_count": int(row.get("completed_operation_count") or 0),
            "work_order_coverage_complete": decomposed_complete,
            "all_operation_work_orders_released": all_operations_released,
        })

    total_work_orders = sum(item["actual_work_order_count"] for item in orders)
    total_operation_work_orders = sum(item["operation_work_order_count"] for item in orders)
    released_operation_work_orders = sum(item["released_operation_count"] for item in orders)
    orders_with_work_orders = sum(1 for item in orders if item["work_order_coverage_complete"])
    orders_fully_released = sum(1 for item in orders if item["all_operation_work_orders_released"])
    return {
        "scope": "sales_orders_to_work_orders",
        "total": total,
        "count": len(orders),
        "returned_count": len(orders),
        "has_more": total > len(orders),
        "orders_with_work_orders": orders_with_work_orders,
        "orders_fully_released": orders_fully_released,
        "work_order_coverage_pct": round(orders_with_work_orders / total * 100, 1) if total else 0.0,
        "operation_release_coverage_pct": round(released_operation_work_orders / total_operation_work_orders * 100, 1) if total_operation_work_orders else 0.0,
        "total_work_orders": total_work_orders,
        "total_operation_work_orders": total_operation_work_orders,
        "released_operation_work_orders": released_operation_work_orders,
        "orders": orders,
    }


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
    conds = []
    if factory_id:
        conds.append(Inventory.factory_id == factory_id)
    kw = args.get("material_keyword")
    if kw:
        conds.append(
            (Inventory.material_code.ilike(f"%{kw}%")) | (Inventory.material_id.ilike(f"%{kw}%"))
        )
    stmt = select(Inventory).order_by(Inventory.updated_at.desc()).limit(limit)
    for cond in conds:
        stmt = stmt.where(cond)
    total_stmt = select(func.count()).select_from(Inventory)
    for cond in conds:
        total_stmt = total_stmt.where(cond)
    total_matches = (await db.execute(total_stmt)).scalar() or 0
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
    return {
        "count": len(items),
        "returned": len(items),
        "total_matches": total_matches,
        "truncated": len(items) < total_matches,
        "inventory": items,
        "note": (
            "本工具只返回最近更新的若干行，不是库存全貌。"
            f"本次条件命中 {total_matches} 行、返回 {len(items)} 行。"
            "SKU 总数、金额覆盖、周转、呆滞、低库存、过量、库位与效期可用性请用 "
            "query_wms_inventory_health；不要把返回行数当成物料总数。"
        ),
    }


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
    """把数据导出为文件（JSON/CSV），写入 files 表并返回下载链接。支持多种报告类型。"""
    from api.routes.file_routes import UPLOAD_DIR  # 懒加载，复用落盘目录
    from sqlalchemy import text as sa_text

    report_type = args.get("report_type") or "production_summary"
    fmt = (args.get("format") or "csv").lower()
    if fmt not in ("json", "csv"):
        fmt = "csv"
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

    elif report_type == "attendance":
        # 考勤统计：按部门/工站聚合出勤率，按缺勤率降序
        fid_clause = "WHERE factory_id = :fid" if factory_id else ""
        rows = (await db.execute(sa_text(f"""
            SELECT department, station,
                   COUNT(*)::int AS total,
                   COUNT(*) FILTER (WHERE status='active')::int AS present,
                   COUNT(*) - COUNT(*) FILTER (WHERE status='active')::int AS absent,
                   ROUND((COUNT(*) - COUNT(*) FILTER (WHERE status='active')) * 100.0 / NULLIF(COUNT(*),0), 2) AS absent_rate_pct
            FROM hr_employees
            {fid_clause}
            GROUP BY department, station
            ORDER BY absent_rate_pct DESC
        """), {"fid": factory_id} if factory_id else {})).fetchall()
        csv_rows = [{"department": r[0], "station": r[1], "total": r[2], "present": r[3], "absent": r[4], "absent_rate_pct": float(r[5]) if r[5] else 0} for r in rows]
        data = {"report": "attendance_deficit_rank", "date": str(date.today()), "factory_id": factory_id, "rows": csv_rows}
        filename_base = f"attendance_deficit_rank_{date.today().strftime('%Y%m%d')}"
        related_type, related_id = "report", "attendance"

    elif report_type == "employee_list":
        # 员工花名册
        fid_clause = "WHERE factory_id = :fid" if factory_id else ""
        rows = (await db.execute(sa_text(f"""
            SELECT employee_code, name, department, station, shift, skill_level, status
            FROM hr_employees
            {fid_clause}
            ORDER BY department, station, employee_code
            LIMIT 2000
        """), {"fid": factory_id} if factory_id else {})).fetchall()
        csv_rows = [{"employee_code": r[0], "name": r[1], "department": r[2], "station": r[3], "shift": r[4], "skill_level": r[5], "status": r[6]} for r in rows]
        data = {"report": "employee_list", "date": str(date.today()), "factory_id": factory_id, "rows": csv_rows}
        filename_base = f"employee_list_{date.today().strftime('%Y%m%d')}"
        related_type, related_id = "report", "employee_list"

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


async def _tool_query_online_workbook(
    db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None,
) -> Dict[str, Any]:
    workbook_id = str(args.get("workbook_id") or "").strip()
    if not workbook_id:
        return {"error": "未提供 workbook_id；请先在在线表格中保存并绑定工作簿"}
    record = (await db.execute(select(WorkbookRecord).where(WorkbookRecord.id == workbook_id))).scalar_one_or_none()
    if not record:
        return {"error": f"工作簿不存在: {workbook_id}"}
    if factory_id and record.factory_id and record.factory_id != factory_id:
        return {"error": "无权访问其他工厂的工作簿"}
    requested_sheet = args.get("sheet_name")
    try:
        table = snapshot_to_table(record.snapshot or {}, requested_sheet)
    except ValueError:
        if not requested_sheet:
            raise
        table = snapshot_to_table(record.snapshot or {}, None)
        table["sheet_fallback"] = {
            "requested": requested_sheet,
            "used": table.get("sheet_name"),
        }
    table["workbook_id"] = record.id
    table["workbook_name"] = record.name
    return {"success": True, "workbook_id": record.id, "workbook_name": record.name, "table": table}


async def _get_workbook_source_path(db: AsyncSession, record: WorkbookRecord) -> Optional[Path]:
    if not record.source_file_id:
        return None
    source = (
        await db.execute(select(FileRecord).where(FileRecord.id == record.source_file_id))
    ).scalar_one_or_none()
    if not source or not source.storage_path:
        return None
    path = Path(source.storage_path)
    return path if path.is_file() else None


async def _tool_scan_online_workbook(
    db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None,
) -> Dict[str, Any]:
    workbook_id = str(args.get("workbook_id") or "").strip()
    if not workbook_id:
        return {"error": "未提供 workbook_id；请先在在线表格中保存并绑定工作簿"}
    record = (await db.execute(select(WorkbookRecord).where(WorkbookRecord.id == workbook_id))).scalar_one_or_none()
    if not record:
        return {"error": f"工作簿不存在: {workbook_id}"}
    if factory_id and record.factory_id and record.factory_id != factory_id:
        return {"error": "无权访问其他工厂的工作簿"}
    graph = scan_formula_dependencies(record.snapshot or {}, args.get("sheet_name"))
    return {
        "success": True,
        "workbook_id": record.id,
        "workbook_name": record.name,
        "formula_count": graph["formula_cells"],
        "formula_graph": graph,
    }


async def _tool_recalculate_online_workbook(
    db: AsyncSession, args: Dict[str, Any], operator: str = "ai_assistant", factory_id: Optional[str] = None,
) -> Dict[str, Any]:
    workbook_id = str(args.get("workbook_id") or "").strip()
    if not workbook_id:
        return {"error": "未提供 workbook_id；请先在在线表格中保存并绑定工作簿"}
    record = (await db.execute(select(WorkbookRecord).where(WorkbookRecord.id == workbook_id))).scalar_one_or_none()
    if not record:
        return {"error": f"工作簿不存在: {workbook_id}"}
    if factory_id and record.factory_id and record.factory_id != factory_id:
        return {"error": "无权修改其他工厂的工作簿"}
    source_path = await _get_workbook_source_path(db, record)
    try:
        snapshot, _ = await asyncio.to_thread(
            apply_workbook_operations, record.snapshot or {}, [], source_path,
        )
    except ValueError as exc:
        return {"error": str(exc)}
    record.snapshot = snapshot
    record.updated_by = operator
    await db.commit()
    table = snapshot_to_table(snapshot, args.get("sheet_name"))
    table["workbook_id"] = record.id
    table["workbook_name"] = record.name
    return {
        "success": True,
        "workbook_id": record.id,
        "workbook_name": record.name,
        "calculation": snapshot.get("calculation"),
        "table": table,
    }


async def _tool_reload_online_workbook(
    db: AsyncSession, args: Dict[str, Any], operator: str = "ai_assistant", factory_id: Optional[str] = None,
) -> Dict[str, Any]:
    workbook_id = str(args.get("workbook_id") or "").strip()
    if not workbook_id:
        return {"error": "未提供 workbook_id；请先在在线表格中保存并绑定工作簿"}
    record = (await db.execute(select(WorkbookRecord).where(WorkbookRecord.id == workbook_id))).scalar_one_or_none()
    if not record:
        return {"error": f"工作簿不存在: {workbook_id}"}
    if factory_id and record.factory_id and record.factory_id != factory_id:
        return {"error": "无权修改其他工厂的工作簿"}
    source_path = await _get_workbook_source_path(db, record)
    if not source_path:
        return {"error": "当前工作簿没有可重新加载的原始上传文件"}
    try:
        snapshot = await asyncio.to_thread(xlsx_to_workbook_snapshot, source_path)
        snapshot, _ = await asyncio.to_thread(
            apply_workbook_operations, snapshot, [], source_path,
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": f"重新加载 XLSX 失败：{exc}"}
    record.snapshot = snapshot
    record.updated_by = operator
    await db.commit()
    table = snapshot_to_table(snapshot)
    table["workbook_id"] = record.id
    table["workbook_name"] = record.name
    return {
        "success": True,
        "workbook_id": record.id,
        "workbook_name": record.name,
        "message": "已从原始上传 XLSX 重新加载，当前编辑内容已回退到原文件版本",
        "calculation": snapshot.get("calculation"),
        "table": table,
    }


async def _tool_edit_online_workbook(
    db: AsyncSession, args: Dict[str, Any], operator: str = "ai_assistant", factory_id: Optional[str] = None,
) -> Dict[str, Any]:
    workbook_id = str(args.get("workbook_id") or "").strip()
    if not workbook_id:
        return {"error": "未提供 workbook_id；请先在在线表格中保存并绑定工作簿"}
    record = (await db.execute(select(WorkbookRecord).where(WorkbookRecord.id == workbook_id))).scalar_one_or_none()
    if not record:
        return {"error": f"工作簿不存在: {workbook_id}"}
    if factory_id and record.factory_id and record.factory_id != factory_id:
        return {"error": "无权修改其他工厂的工作簿"}
    source_path = await _get_workbook_source_path(db, record)
    raw_operations = args.get("operations")
    if raw_operations is None:
        raw_operations = args.get("edits")
    if not isinstance(raw_operations, list) or not raw_operations:
        return {"error": "未提供有效的 operations/edits；请至少指定一个单元格操作"}
    sheets = record.snapshot.get("sheets") or {}
    order = record.snapshot.get("sheetOrder") or list(sheets.keys())
    first_sheet = next((sheets.get(sheet_id) for sheet_id in order if sheets.get(sheet_id)), None)
    known_sheets = {
        str(value)
        for sheet in sheets.values()
        for value in ((sheet or {}).get("id"), (sheet or {}).get("name"))
        if value
    }
    operations: List[Dict[str, Any]] = []
    warnings: List[str] = []
    requested_default = args.get("sheet_name")
    default_sheet = requested_default if str(requested_default or "") in known_sheets else (
        (first_sheet or {}).get("name") or (first_sheet or {}).get("id")
    )
    if requested_default and str(requested_default) not in known_sheets and default_sheet:
        warnings.append(f"工作表“{requested_default}”不存在，已使用第一张工作表“{default_sheet}”")
    for raw in raw_operations[:500]:
        if not isinstance(raw, dict):
            continue
        operation = dict(raw)
        if not operation.get("type") and not operation.get("op"):
            operation["type"] = "set_formula" if operation.get("formula") else "set_cell"
        requested = operation.get("sheet") or operation.get("sheet_name")
        if not requested:
            operation["sheet"] = default_sheet
        elif str(requested) not in known_sheets and default_sheet:
            operation["sheet"] = default_sheet
            if f"工作表“{requested}”不存在，已使用第一张工作表“{default_sheet}”" not in warnings:
                warnings.append(f"工作表“{requested}”不存在，已使用第一张工作表“{default_sheet}”")
        operations.append(operation)
    if not operations:
        return {"error": "未提供有效的 operations/edits；请至少指定一个单元格操作"}
    try:
        snapshot, changed = await asyncio.to_thread(
            apply_workbook_operations, record.snapshot or {}, operations, source_path,
        )
    except ValueError as exc:
        return {"error": str(exc)}
    record.snapshot = snapshot
    if args.get("name"):
        record.name = str(args["name"])[:255]
    else:
        derived_name = workbook_export_basename(record.name, snapshot)
        if derived_name != Path(record.name or "").stem:
            record.name = derived_name
    record.updated_by = operator
    await db.commit()
    table = snapshot_to_table(snapshot, default_sheet)
    table["workbook_id"] = record.id
    table["workbook_name"] = record.name
    response = {
        "success": True,
        "workbook_id": record.id,
        "workbook_name": record.name,
        "changed": changed,
        "calculation": snapshot.get("calculation"),
        "table": table,
    }
    if warnings:
        response["warnings"] = warnings
    return response


async def _tool_export_online_workbook(
    db: AsyncSession, args: Dict[str, Any], operator: str = "ai_assistant", factory_id: Optional[str] = None,
) -> Dict[str, Any]:
    from api.routes.file_routes import UPLOAD_DIR

    workbook_id = str(args.get("workbook_id") or "").strip()
    record = (await db.execute(select(WorkbookRecord).where(WorkbookRecord.id == workbook_id))).scalar_one_or_none()
    if not record:
        return {"error": f"工作簿不存在: {workbook_id}"}
    if factory_id and record.factory_id and record.factory_id != factory_id:
        return {"error": "无权导出其他工厂的工作簿"}
    file_id = str(uuid.uuid4())
    export_basename = workbook_export_basename(record.name, record.snapshot or {})
    safe_name = re.sub(r'[\\/:*?"<>|]+', "_", export_basename).strip() or "workbook"
    filename = f"{safe_name}.xlsx"
    storage_path = UPLOAD_DIR / f"{file_id}_{filename}"
    source_path = await _get_workbook_source_path(db, record)
    try:
        await asyncio.to_thread(
            workbook_snapshot_to_xlsx, record.snapshot or {}, storage_path, source_path,
        )
        await asyncio.to_thread(recalculate_workbook_file, storage_path)
    except Exception as exc:  # noqa: BLE001
        storage_path.unlink(missing_ok=True)
        return {"error": f"XLSX 导出失败: {exc}"}
    file_record = FileRecord(
        id=file_id,
        filename=filename,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        size=storage_path.stat().st_size,
        storage_path=str(storage_path),
        uploaded_by=operator,
        factory_id=factory_id or record.factory_id,
        related_type="workbook_export",
        related_id=record.id,
    )
    db.add(file_record)
    await db.commit()
    return {
        "success": True,
        "workbook_id": record.id,
        "filename": filename,
        "file_id": file_id,
        "download_url": f"/api/v1/files/{file_id}",
        "format": "xlsx",
        "formulas_preserved": True,
    }


async def _tool_create_online_pivot(
    db: AsyncSession, args: Dict[str, Any], operator: str = "ai_assistant", factory_id: Optional[str] = None,
) -> Dict[str, Any]:
    workbook_id = str(args.get("workbook_id") or "").strip()
    record = (await db.execute(select(WorkbookRecord).where(WorkbookRecord.id == workbook_id))).scalar_one_or_none()
    if not record:
        return {"error": f"工作簿不存在: {workbook_id}"}
    if factory_id and record.factory_id and record.factory_id != factory_id:
        return {"error": "无权修改其他工厂的工作簿"}
    try:
        snapshot, summary = build_pivot_summary(
            record.snapshot or {},
            args.get("sheet"),
            str(args.get("row_field") or ""),
            str(args.get("value_field") or ""),
            str(args.get("aggregation") or "sum"),
            str(args.get("output_sheet_name") or "透视汇总"),
        )
    except ValueError as exc:
        return {"error": str(exc)}
    record.snapshot = snapshot
    record.updated_by = operator
    await db.commit()
    table = snapshot_to_table(snapshot, summary["output_sheet"])
    table["workbook_id"] = record.id
    table["workbook_name"] = record.name
    return {"success": True, "workbook_id": record.id, "summary": summary, "table": table}


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

    # 出勤率：优先用 attendance 表（覆盖率>=50%时），否则用 active/total
    attendance_rate = round(active / total * 100, 1) if total else 0
    att_row = (await db.execute(sa_text(
        "SELECT count(*)::int AS t, count(*) FILTER (WHERE status IN ('present','late'))::int AS p "
        "FROM attendance WHERE factory_id = :fid AND date = CURRENT_DATE::text"
    ), {"fid": fid})).first()
    if att_row and att_row[0] and att_row[0] >= (active or 0) * 0.5:
        attendance_rate = round(att_row[1] / att_row[0] * 100, 1)

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
        "attendance_rate_pct": attendance_rate,
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
        LEFT JOIN equipment e ON e.id::varchar = d.equipment_id
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
        LEFT JOIN equipment e ON e.id::varchar = d.equipment_id
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
        LEFT JOIN equipment e ON e.id::varchar = p.equipment_id
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


async def _tool_query_bom_data_quality(
    db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None
) -> Dict[str, Any]:
    """BOM 质量自检（只读）：判据只在 bom_data_quality 一处定义，这里负责取厂区与兜型号。

    目的是让机器人能回答"这版 BOM 哪里脏、该先改哪条"，而不是每次靠人肉查库对撞。
    """
    from api.services.bom_data_quality import scan

    fid = factory_id or "FAC_MECH_001"
    model = str(args.get("product_model") or "").strip()
    if not model:
        row = (await db.execute(text("""
            SELECT product_model, count(*) AS lines FROM enghub_bom_items
            WHERE factory_id = :fid GROUP BY 1 ORDER BY lines DESC LIMIT 1
        """), {"fid": fid})).mappings().first()
        model = str(row["product_model"]) if row else ""
    if not model:
        return {"status": "no_data", "factory_id": fid,
                "message": "该厂区镜像里没有 BOM 行，没有质量数据可判：先确认 BOM 是否上传/同步。"}
    data = await scan(db, fid, model)
    findings = data.get("findings") or []
    return {
        "status": "ok" if findings else "clean",
        "factory_id": fid,
        "product_model": model,
        "rows": data.get("rows"),
        "codes": data.get("codes"),
        "rule_count": len(findings),
        "findings": [
            {k: f.get(k) for k in ("rule", "name", "severity", "codes",
                                   "affected_shortage_qty", "sample_codes", "action")}
            for f in findings[:8]
        ],
        "data_note": ("只读自检：系统不改 BOM 原始行。按影响缺口从大到小提 ECR，"
                      "优先做最挡生产的那条。"),
    }


async def _tool_query_simulation_sensitivity(
    db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None
) -> Dict[str, Any]:
    """敏感度与映射精度（只读）：斜率、精度、误差传导都在 sim_sensitivity 一处算。"""
    from api.services.sim_sensitivity import report
    from api.services.virtual_run import default_models

    fid = factory_id or "FAC_MECH_001"
    models = await default_models(db, fid, n=5)
    if not models:
        return {"status": "ok", "factory_id": fid, "has_data": False,
                "message": "厂区里没有可推演的机种（BOM 镜像为空？）"}
    out = await report(db, fid, models)
    sens = out.get("sensitivity") or {}
    base = sens.get("base") or {}
    levers = [{"lever": l["label"], "base_level": l.get("base_level"),
               "slope": l.get("slope"),
               "curve": [{k: c.get(k) for k in ("level", "finish_date", "days_vs_base",
                                                "on_time_models", "labor_delta_usd",
                                                "expedite_delta_usd", "activation_delta_usd")}
                         for c in (l.get("curve") or [])]}
              for l in sens.get("levers") or []]
    acc = out.get("accuracy") or {}
    return {
        "status": "ok", "factory_id": fid, "has_data": True, "models": models,
        "base": {k: base.get(k) for k in ("finish_date", "days_late_worst", "on_time_rate",
                                          "labor_cost_usd", "expedite_cost_usd",
                                          "line_activation_cost_usd", "first_batch_units",
                                          "queued_units", "binding")},
        "targets": sens.get("targets"),
        "levers": levers,
        "accuracy_overall": acc.get("overall_accuracy"),
        "accuracy_per_model": [{"model_code": m["model_code"], "score": m["accuracy_score"],
                                "drags": m["drags"]} for m in acc.get("models") or []],
        "uncertainty": (out.get("uncertainty") or {}).get("per_model"),
        "value_of_repair": (out.get("uncertainty") or {}).get("value_of_repair"),
        "method": ("斜率只取基准两侧最近两档（局部线性，不做全局回归）；"
                   "不确定天数 = |斜率| × (允许误差 ÷ 档位步长)，多项线性相加是保守口径；"
                   "所有档位都走同一条 scan_policies 推演路径，不另建第二套算法。"),
    }


async def _tool_query_engine_attribution(
    db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None
) -> Dict[str, Any]:
    """归因（只读）：走 engine_contract 的对外接口，词表与判据都在契约那一处，这里只转述。"""
    from api.services.engine_contract import ContractError, attribution
    from api.services.virtual_run import default_models

    fid = factory_id or "FAC_MECH_001"
    models = [str(m) for m in (args.get("models") or [])] or await default_models(db, fid, n=3)
    req = {"models": models, "conditions": {"weather": str(args.get("weather") or "storm")}}
    if isinstance(args.get("compare"), dict):
        req["compare"] = args["compare"]
    try:
        out = await attribution(db, fid, req)
    except ContractError as exc:
        return {"status": "rejected", "has_data": False, **exc.as_dict()}
    ans = out.get("answers") or {}
    return {"status": "ok", "factory_id": fid, "has_data": True, "models": models,
            "contract_version": out.get("contract_version"), "answer": ans.get("answer"),
            "constraint_attribution": ans.get("constraint_attribution"),
            "relief_attribution": (ans.get("relief_attribution") or [])[:6],
            "uncertainty_attribution": ans.get("uncertainty_attribution"),
            "change_attribution": ans.get("change_attribution"),
            "unavailable": out.get("unavailable"), "caveats": out.get("caveats"),
            "note": ("归因用的是实测反事实（真跑了推演），不是权重打分；"
                     "算不出的项在 unavailable 里点名缺什么，不折算成 0")}


async def _tool_query_engine_capability_layers(
    db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None
) -> Dict[str, Any]:
    """分层验收（只读）：判据与阈值只在 engine_layers 一处，这里只转述，不改判据。"""
    from api.services.engine_layers import layered_acceptance
    from api.services.virtual_run import default_models

    fid = factory_id or "FAC_MECH_001"
    models = await default_models(db, fid, n=5)
    if not models:
        return {"status": "ok", "factory_id": fid, "has_data": False,
                "message": "没有可推演的机种（BOM 镜像为空？）"}
    out = await layered_acceptance(db, fid, models)
    return {"status": "ok", "factory_id": fid, "has_data": True, "models": models,
            "gate": out.get("gate"), "rule": out.get("rule"),
            "layers": [{k: line.get(k) for k in ("layer", "name", "pass", "reportable",
                                                  "quote_rule", "failed", "not_computable",
                                                  "reported", "metrics")}
                       for line in out.get("layers") or []],
            "note": ("任何 reportable=false 的层，它的数只能内部看；"
                     "not_computable 的项要连缺哪个输入一起说，不许折算成 0 分或别的数")}


async def _tool_query_sim_evidence_readiness(
    db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None
) -> Dict[str, Any]:
    """精度判据的证据就绪度（只读）：判据在 sim_backtest 一处定义，这里只转述、不重判。"""
    from api.services.sim_backtest import bottleneck_agreement, readiness

    fid = factory_id or "FAC_MECH_001"
    out = await readiness(db, fid)
    want_agree = args.get("agreement")
    agreement = None
    if want_agree is not False:
        try:
            limit = max(5, min(120, int(args.get("limit") or 40)))
        except (TypeError, ValueError):
            limit = 40
        agree = await bottleneck_agreement(db, fid, limit=limit)
        agreement = {
            "orders_compared": agree.get("orders_compared"),
            "lead_based": agree.get("lead_based"),
            "quantity_based": agree.get("quantity_based"),
            "top5_overlap_rate": agree.get("top5_overlap_rate"),
            "median_shortage_parts": agree.get("median_shortage_parts"),
            "median_ledger_parts": agree.get("median_ledger_parts"),
            "bom_universe": agree.get("bom_universe"),
        }
    return {"status": "ok", "factory_id": fid, "has_data": True,
            "models_with_orders": out.get("models_with_orders"),
            "bottleneck_comparable_models": out.get("bottleneck_comparable_models"),
            "bottleneck_comparable_list": out.get("bottleneck_comparable_list"),
            "bottleneck_verdict": out.get("bottleneck_verdict"),
            "backtest": out.get("backtest"),
            "kit_gaps": out.get("kit_gaps"),
            "bom_source": out.get("bom_source"),
            "fixable_by_rerun_orders": out.get("fixable_by_rerun_orders"),
            "agreement": agreement,
            "note": out.get("how_to_read"),
            "caveat": ("一致率低有三条可能的解释（料号不同批 / 快照过期 / 需求算法毛净之差），"
                       "这一格把三种分母都摆出来才是可判的；台账齐套行的登记世代没跟上时，"
                       "先重跑齐套登记再谈命中率准不准")}


async def _tool_query_simulation_recommendation(
    db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None
) -> Dict[str, Any]:
    """推演建议与落地复查（只读）：判据在 virtual_run/pareto_eval/portfolio_flywheel 一处定义，
    这里只负责取最近那张卡并转述，不重跑扫描 —— 重跑会给出和记分卡不同的数。"""
    from api.services.portfolio_flywheel import latest_tradeoff_state

    fid = factory_id or "FAC_MECH_001"
    out = await latest_tradeoff_state(db, fid)
    if out.get("status") == "no_card":
        return {"status": "ok", "factory_id": fid, "has_card": False, **out}
    ft = out.get("followthrough") or {}
    return {
        "status": "ok", "factory_id": fid, "has_card": True,
        "as_of": out.get("as_of"), "engine_date": out.get("engine_date"),
        "models_simulated": out.get("models_simulated"),
        "robust_recommendation": out.get("robust_recommendation"),
        "robustness_pct": out.get("robustness_pct"),
        "score_meaning": out.get("score_meaning"),
        "actions": out.get("actions"), "action_total": out.get("action_total"),
        "followthrough": ft,
        "followthrough_verdict": ft.get("verdict") or ft.get("note"),
        "by_scenario": out.get("by_scenario"),
        "scenario_divergence": out.get("scenario_divergence"),
        "promise_conclusion": out.get("promise_conclusion"),
        "robust_pool": out.get("robust_pool"),
        "promise_note": ("推荐只在承诺口径（瓶颈提前期×1.15）之内参与跨场景比较；"
                         "放宽之后的场景只作诊断，它的准点不算能兑现承诺"),
        "calibration_note": ("每个天气场景的批量与交期系数是引擎自己标定的测试口径，"
                             "不是对客户的承诺；标定只决定这一轮有没有区分度。"),
        "note": out.get("note") or (
            "推荐不是打分第一名：交期与产量是硬约束，其余维度取最小最大后悔；"
            "并列时会说明没说哪个最好。动作都在沙箱里，不写 MES/WMS。"),
    }


async def _tool_query_chain_convergence(
    db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None
) -> Dict[str, Any]:
    """链条收敛自检（只读）：判据只在 chain_convergence 一处定义，这里负责取厂区并转述。

    无人跑的系统最怕"心跳一直 tick、工厂一步不动"，所以这个工具的存在意义就是
    让机器人能回答"到底有没有在推进"，并且敢说 diverging / stalled。
    """
    from api.services.chain_convergence import report

    fid = factory_id or "FAC_MECH_001"
    out = await report(db, fid)
    return {
        "status": "ok",
        "factory_id": fid,
        "verdict": out.get("verdict"),
        "reason": out.get("reason"),
        "metrics": out.get("metrics"),
        "previous_metrics": out.get("previous_metrics"),
        "deltas": out.get("deltas"),
        "stalled_ticks": out.get("stalled_ticks"),
        "alert": out.get("alert"),
        "verdict_rules": out.get("verdict_rules"),
        "commit_gate": out.get("commit_gate") or {},
        "counts_note": (
            "metrics.released_by_gate 是累计由就绪门下达的工单数；"
            "metrics.completed_orders 是全厂真的完工过的工单数（含历史）；"
            "deltas 才是与上一轮心跳的差值，判断趋势请看 deltas，不要把累计数当本轮数。"
        ),
        "data_note": "只读：不改工单状态、不改计划；数字来自 work_orders / work_order_materials / "
                     "production_reports / aps_schedules 与引擎心跳本身。",
    }


async def _tool_query_plan_commit_gate(
    db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None
) -> Dict[str, Any]:
    """逐单下达就绪门（只读）：判据只在 plan_commit_gate 一处定义，这里负责取厂区、压成能念的数。

    机器人要能回答"这版计划到底有几张单真能开工"，而不是只会报"排了 961 个任务"。
    """
    from api.services.plan_commit_gate import evaluate_commit_gate

    fid = factory_id or "FAC_MECH_001"
    gate = await evaluate_commit_gate(db, fid)
    plan = gate.get("plan") or {}
    if gate.get("status") == "no_current_draft":
        return {"status": "no_data", "factory_id": fid, "message": gate.get("reason")}
    rules = (gate.get("gate_rules") or {}).get("hold_reason_definitions") or {}
    return {
        "status": "ok",
        "factory_id": fid,
        "schedule_code": plan.get("schedule_code"),
        "plan_version": plan.get("version_number"),
        "plan_status": plan.get("plan_status"),
        "is_current_plan": plan.get("is_current"),
        "plan_generated_at": plan.get("generated_at"),
        "evaluated_orders": gate.get("evaluated_orders"),
        "ready_count": gate.get("ready_count"),
        "held_count": gate.get("held_count"),
        "already_released_count": gate.get("already_released_count"),
        "hold_reason_counts": gate.get("hold_reason_counts"),
        "hold_reason_meanings": {k: rules.get(k) for k in (gate.get("hold_reason_counts") or {})},
        "ready_samples": [
            {k: v.get(k) for k in ("work_order_code", "wo_type", "product_id", "planned_qty",
                                   "plan_rows", "route_steps", "first_station_code")}
            for v in (gate.get("ready") or [])[:6]
        ],
        "held_samples": [
            {k: v.get(k) for k in ("work_order_code", "wo_type", "hold_reasons",
                                   "plan_rows", "route_steps", "short_rows")}
            for v in (gate.get("held") or [])[:6]
        ],
        "gate_rules": (gate.get("gate_rules") or {}).get("requires"),
        # 三桶互斥且相加等于评估数 —— 这个口径必须写在数据里，
        # 不然回答里会出现"399 张被压住，其中 203 张已下达"这种把并列说成包含的说法。
        "counts_note": (
            f"三桶互斥：可开工 {gate.get('ready_count')} + 被压住 {gate.get('held_count')} "
            f"+ 已下达过 {gate.get('already_released_count')} "
            f"= 评估工单 {gate.get('evaluated_orders')}；"
            "\"已下达过\"是状态而不是被压住，别写成\"其中\""
        ),
        "data_note": (
            "只读判定：系统不在这条路径上改工单状态。要机器自己放行得显式打开 "
            "PLAN_COMMIT_APPLY，并且每轮受 PLAN_COMMIT_MAX_ORDERS 限量。"
        ),
    }


async def _tool_query_wms_inventory_health(
    db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None
) -> Dict[str, Any]:
    """库存健康度汇总（只读）：给模型汇总与缺口，不把上万行明细灌进上下文。"""
    from api.services.wms_inventory_health_service import WmsInventoryHealthService

    fid = factory_id or "FAC_ELEC_DEMO_2026"
    data = await WmsInventoryHealthService(db).collect(
        fid,
        dead_stock_days=int(args.get("dead_stock_days") or 60),
        expiry_warn_days=int(args.get("expiry_warn_days") or 30),
        turnover_days=int(args.get("turnover_days") or 90),
    )

    def _top(entry, n=8):
        res = (entry or {}).get("result") or {}
        for key in ("items", "suggestions", "top_items", "zones", "top_cost_items"):
            if isinstance(res.get(key), list):
                return res[key][:n]
        return []

    analyses = data.get("analyses") or {}
    from api.services.wms_inventory_health_service import _json_safe

    return _json_safe({
        "type": "wms_inventory_health",
        "factory_id": data["factory_id"],
        "thresholds": data["thresholds"],
        "headline": data["headline"],
        "coverage": data["coverage"],
        "samples": {
            "low_stock": _top(analyses.get("low_stock") or {}),
            "overstock": _top(analyses.get("overstock") or {}),
            "dead_stock": _top(analyses.get("dead_stock") or {}),
            "turnover": _top(analyses.get("turnover") or {}, 5),
        },
        "reconciliation": data["reconciliation"],
        "not_computable": data["not_computable"],
        "data_note": (
            "结论只能引用本结果里出现的数字。coverage 显示阈值或流水不足时，"
            "必须说明该项不可判定，不能把 0 或全量计数当成业务事实。"
        ),
    })


async def _tool_query_shortage_alerts(db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None) -> Dict[str, Any]:
    """缺料预警：可用量低于再订货点的物料。

    原来只遍历 replenishment_thresholds（该表 0 行），于是永远报"没有缺料"，
    而同一份库存数据按行级水位能算出 371 项低于再订货点 —— 对话与智能体因此
    互相矛盾。现在与补货建议、过量告警共用 policy.resolve_target 同一口径：
    物料级配置表有启用行时优先，否则回落到 inventory 行级 reorder_point/
    safety_stock/reorder_qty。没有水位可判定的物料不参与告警，不做猜测。
    """
    from sqlalchemy import text as sa_text
    from api.services.wms_architecture.policy import (
        CONSUMPTION_TYPES,
        policy_provenance,
        resolve_target,
    )

    fid = factory_id or "FAC_ELEC_DEMO_2026"
    limit = max(1, min(int(args.get("limit") or 50), 200))
    window_days = max(1, int(args.get("consumption_window_days") or 30))

    cfg_rows = (await db.execute(sa_text("""
        SELECT material_code, max_stock, safety_stock, reorder_point
        FROM safety_stock_config
        WHERE factory_id = :fid AND is_active = TRUE
    """), {"fid": fid})).mappings().all()
    configs = {r["material_code"]: dict(r) for r in cfg_rows}

    rows = (await db.execute(sa_text("""
        WITH policy AS (
            SELECT i.material_id, i.material_code,
                   MAX(i.material_name) AS material_name,
                   SUM(COALESCE(i.available_qty, 0)) AS avail,
                   SUM(COALESCE(i.total_qty, 0)) AS total_qty,
                   SUM(COALESCE(i.reserved_qty, 0)) AS reserved_qty,
                   MAX(COALESCE(NULLIF(i.reorder_point, 0), i.safety_stock, 0)) AS reorder_point,
                   MAX(COALESCE(i.safety_stock, 0)) AS safety_stock,
                   MAX(COALESCE(i.reorder_qty, 0)) AS reorder_qty,
                   MAX(i.unit) AS unit
            FROM inventory i
            WHERE i.factory_id = :fid
            GROUP BY i.material_id, i.material_code
        ),
        cons AS (
            SELECT m.material_code, SUM(ABS(t.quantity)) AS consumed
            FROM inventory_transactions t
            JOIN (
                SELECT DISTINCT material_id, material_code
                FROM inventory WHERE factory_id = :fid
            ) m ON m.material_id = t.material_id
            WHERE t.factory_id = :fid
              AND t.transaction_type = ANY(:types)
              AND t.created_at >= NOW() - make_interval(days => :days)
            GROUP BY m.material_code
        )
        SELECT p.material_id, p.material_code, p.material_name, p.avail, p.total_qty,
               p.reserved_qty, p.reorder_point, p.safety_stock, p.reorder_qty, p.unit,
               COALESCE(c.consumed, 0) AS consumed_window,
               COUNT(*) OVER () AS total_below,
               COUNT(*) FILTER (WHERE p.avail <= p.safety_stock) OVER () AS total_critical
        FROM policy p
        LEFT JOIN cons c ON c.material_code = p.material_code
        WHERE p.avail <= p.reorder_point
        ORDER BY (p.reorder_point - p.avail) DESC
        LIMIT :cap
    """), {
        "fid": fid,
        "types": list(CONSUMPTION_TYPES),
        "days": window_days,
        "cap": limit,
    })).mappings().all()

    total_below = int(rows[0]["total_below"]) if rows else 0
    total_critical = int(rows[0]["total_critical"]) if rows else 0
    items = []
    for r in rows:
        cfg = configs.get(r["material_code"]) or {}
        reorder_point = float(cfg.get("reorder_point") or r["reorder_point"] or 0)
        safety_stock = float(cfg.get("safety_stock") or r["safety_stock"] or 0)
        avail = float(r["avail"] or 0)
        target, basis = resolve_target(
            reorder_point=reorder_point,
            safety_stock=safety_stock,
            reorder_qty=r["reorder_qty"],
            max_level=cfg.get("max_stock"),
        )
        if target <= 0 or avail > reorder_point:
            continue
        consumed = float(r["consumed_window"] or 0)
        daily = consumed / window_days
        lot = float(r["reorder_qty"] or 0)
        items.append({
            "material_id": r["material_id"],
            "material_code": r["material_code"],
            "material_name": r["material_name"] or "",
            "current_qty": int(avail),
            "total_qty": int(r["total_qty"] or 0),
            "reserved_qty": int(r["reserved_qty"] or 0),
            "min_level": int(reorder_point),
            "safety_stock": int(safety_stock),
            "max_level": int(target),
            "gap": int(reorder_point - avail),
            "shortage_to_target": int(max(target - avail, 0)),
            "reorder_lot": int(lot),
            "unit": r["unit"] or "",
            "consumed_in_window": int(consumed),
            "daily_consumption": round(daily, 2),
            "cover_days": round(avail / daily, 1) if daily > 0 else None,
            "severity": "critical" if avail <= safety_stock else "warning",
            "policy_basis": basis,
        })

    provenance = policy_provenance(len(configs), len(rows))
    critical = [i for i in items if i["severity"] == "critical"]
    return {
        "factory_id": fid,
        "shortage_count": total_below,
        "returned_count": len(items),
        "critical_count": total_critical,
        "critical_in_returned": len(critical),
        "items": items,
        **provenance,
        "data_note": (
            f"低于再订货点共 {total_below} 项（其中 critical {total_critical} 项），"
            f"按缺口大小返回前 {len(items)} 项；"
            "cover_days 为 null 表示统计窗口内没有真实消耗流水，不编料需求速度。"
        ),
    }


async def _tool_query_stagnant(db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None) -> Dict[str, Any]:
    """呆滞物料：与 PMC 供应快照共用账龄、BOM和PO口径。"""
    from api.services.pmc_work_matrix_service import PmcWorkMatrixService

    fid = factory_id or "FAC_ELEC_DEMO_2026"
    days = int(args.get("days", 180))
    supply = await PmcWorkMatrixService(db).query_material_supply(
        fid,
        material_keyword=args.get("material_keyword"),
        days_threshold=days,
        limit=min(int(args.get("limit", 50)), 200),
        only_stagnant=True,
    )
    # Preserve the existing chatbot response keys while exposing the richer PMC evidence.
    items = []
    for item in supply.get("items", []):
        items.append({
            **item,
            "qty": item.get("available_qty", 0),
            "last_movement": item.get("last_movement_at"),
            "stagnant_days": item.get("aging_days"),
            "bom_reuse_candidates": item.get("bom_reuse_candidates", []),
            "po_codes": item.get("po_codes", []),
            "in_transit_qty": item.get("in_transit_qty", 0),
        })
    return {
        "factory_id": fid,
        "threshold_days": days,
        "stagnant_count": len(items),
        "items": items,
        "purchase_order_data_status": supply.get("purchase_order_data_status"),
        "note": supply.get("note"),
    }


async def _tool_query_lead_time_evidence(
    db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None
) -> Dict[str, Any]:
    """提前期证据普查（只读）：判据只写在 core/mes/data_evidence 一处，这里只转述读数。

    为什么要单独立一个工具：交期、排产、加急建议都吃 `materials.lead_time_days`，
    而这个数在本厂是按类别铺出来的默认值（3 万个外购料号只有 10 个取值）。
    助手回答"12 天能到"之前必须能说清这句有没有实测支撑。
    """
    from core.mes.data_evidence import lead_time_evidence

    fid = factory_id or "FAC_MECH_001"
    codes = [c.strip() for c in str(args.get("material_codes") or "").replace("，", ",").split(",")
             if c.strip()]
    limit = max(1, min(int(args.get("limit") or 30), 200))
    out = await lead_time_evidence(db, fid, codes=codes or None, limit=limit)
    return {
        "type": "lead_time_evidence",
        "factory_id": fid,
        "queried_codes": codes,
        "checked": out["checked"],
        "coverage": out["coverage"],
        "verdict_counts": out["verdict_counts"],
        "lead_time_shape_by_group": out["lead_time_shape_by_group"],
        "make_or_buy_contradiction": out["make_or_buy_contradiction"],
        "items": [{"material_code": r["material_code"], "material_name": r["material_name"],
                   "make_or_buy": r["make_or_buy"], "ledger_days": r["ledger_days"],
                   "verdict": r["verdict"], "evidence": r["evidence"],
                   "group_shape": r["group_shape"], "measured": r["measured"],
                   "receipt_measured": r["receipt_measured"], "supplier": r["supplier"],
                   "suggested_days": r["suggested_days"]} for r in out["rows"][:limit]],
        "conflicts": out["conflict_examples"][:5],
        "name_bridge": out["name_bridge"],
        "basis": out["basis"],
        "reading_hint": ("unverified_default = 同组几十~几千个料号共用同一个众数取值，这个数没被量过；"
                         "ledger_default_conflicts_with_measured = 台账值比实测中位小一半以上，"
                         "拿它算交期会系统性偏乐观；suggested_days 是「要去核对的数」，不是事实。"),
    }


async def _tool_query_pmc_material_supply(
    db: AsyncSession,
    args: Dict[str, Any],
    factory_id: Optional[str] = None,
) -> Dict[str, Any]:
    """PMC material supply evidence for direct chatbot questions."""
    from api.services.pmc_work_matrix_service import PmcWorkMatrixService

    return await PmcWorkMatrixService(db).query_material_supply(
        factory_id or "FAC_ELEC_DEMO_2026",
        material_keyword=args.get("material_keyword"),
        days_threshold=int(args.get("days", 180)),
        limit=min(int(args.get("limit", 50)), 200),
        only_stagnant=bool(args.get("only_stagnant", False)),
    )


async def _tool_query_pmc_rush_impact(
    db: AsyncSession,
    args: Dict[str, Any],
    factory_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Read-only rush-order impact calculation for the PMC chatbot."""
    fid = factory_id or "FAC_ELEC_DEMO_2026"
    quantity = int(args.get("quantity") or 0)
    if quantity <= 0:
        return {"error": "缺少急单数量，无法计算插单影响"}
    try:
        capacity_share = float(args.get("capacity_share", 0.5))
    except (TypeError, ValueError):
        capacity_share = 0.5
    capacity_share = max(0.01, min(1.0, capacity_share))

    efficiency = 0.85
    hours_per_unit = 0.5 / efficiency
    rush_hours = quantity * hours_per_unit
    # This uses the same conservative one-bottleneck approximation as the APS rush endpoint.
    impact_hours = rush_hours

    stmt = select(WorkOrder).where(
        WorkOrder.factory_id == fid,
        WorkOrder.status.in_(["released", "pending"]),
        WorkOrder.wo_type == "master",
    ).order_by(WorkOrder.planned_due.asc())
    existing_result = await db.execute(stmt)
    existing_orders = list(existing_result.scalars().all())

    delayed_orders: List[Dict[str, Any]] = []
    for work_order in existing_orders:
        if not work_order.planned_due:
            continue
        original_due = work_order.planned_due
        new_end = original_due + timedelta(hours=impact_hours)
        delayed_orders.append({
            "work_order_code": work_order.work_order_code,
            "product_id": work_order.product_id,
            "planned_qty": work_order.planned_qty,
            "original_due": original_due.isoformat(),
            "new_estimated_end": new_end.isoformat(),
            "delay_hours": round(impact_hours, 1),
            "delay_days": round(impact_hours / 24, 1),
            "priority": work_order.priority,
        })

    rush_end = datetime.utcnow() + timedelta(hours=rush_hours)
    due_date = None
    if args.get("due_date"):
        try:
            due_date = date.fromisoformat(str(args["due_date"])[:10])
        except ValueError:
            due_date = None
    return {
        "type": "pmc_rush_impact",
        "factory_id": fid,
        "rush_order": {
            "product_id": args.get("product_id"),
            "quantity": quantity,
            "capacity_share": capacity_share,
            "process_hours": round(rush_hours, 1),
            "estimated_end": rush_end.isoformat(),
            "due_date": due_date.isoformat() if due_date else None,
            "due_feasible": rush_end.date() <= due_date if due_date else None,
        },
        "impact": {
            "affected_order_count": len(delayed_orders),
            "impact_hours_per_order": round(impact_hours, 1),
            "delayed_orders": delayed_orders,
        },
        "note": "插单影响为只读沙盘估算，未修改APS排程；正式承诺前仍需执行APS重排并确认物料齐套。",
    }


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


async def _tool_get_virtual_factory_status(
    db: AsyncSession,
    args: Dict[str, Any],
    factory_id: Optional[str] = None,
) -> Dict[str, Any]:
    from api.services.virtual_factory_service import DEFAULT_FACTORY_ID, VirtualFactoryService

    fid = factory_id or DEFAULT_FACTORY_ID
    return await VirtualFactoryService(db).status(fid)


async def _tool_run_virtual_factory_pulse(
    db: AsyncSession,
    args: Dict[str, Any],
    factory_id: Optional[str] = None,
) -> Dict[str, Any]:
    from api.services.virtual_factory_service import DEFAULT_FACTORY_ID, PulseConfig, VirtualFactoryService

    fid = factory_id or DEFAULT_FACTORY_ID
    cfg = PulseConfig(
        factory_id=fid,
        monthly_capacity_containers=int(args.get("monthly_capacity_containers") or 300),
        order_lead_days=int(args.get("order_lead_days") or 90),
        target_active_orders=int(args.get("target_active_orders") or 6),
        operator="virtual_factory",
    )
    return await VirtualFactoryService(db).pulse(cfg)


# 执行器注册表
_TOOL_EXECUTORS = {
    "query_work_orders": _tool_query_work_orders,
    "query_order_work_order_status": _tool_query_order_work_order_status,
    "get_work_order_detail": _tool_get_work_order_detail,
    "get_production_summary": _tool_get_production_summary,
    "query_inventory": _tool_query_inventory,
    "query_lead_time_evidence": _tool_query_lead_time_evidence,
    "query_pmc_material_supply": _tool_query_pmc_material_supply,
    "query_pmc_rush_impact": _tool_query_pmc_rush_impact,
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
    "scan_online_workbook": _tool_scan_online_workbook,
    "query_online_workbook": _tool_query_online_workbook,
    "recalculate_online_workbook": _tool_recalculate_online_workbook,
    "reload_online_workbook": _tool_reload_online_workbook,
    "edit_online_workbook": _tool_edit_online_workbook,
    "export_online_workbook": _tool_export_online_workbook,
    "create_online_pivot": _tool_create_online_pivot,
    "get_pending_alerts": _tool_get_pending_alerts,
    "query_ocap_tasks": _tool_query_ocap_tasks,  # OCAP待办任务查询（chatbot集成）
    "query_alert_reviews": _tool_query_alert_reviews,
    "acknowledge_alert": _tool_acknowledge_alert,
    "run_alert_patrol": _tool_run_alert_patrol,
    "query_hr_roster": _tool_query_hr_roster,
    "query_workflow_diagram": None,  # 流程引擎定义查询，见下方执行器
    "query_pmc_work_matrix": None,  # PMC 工单证据矩阵，见下方执行器
    "query_process_knowledge": None,  # 占位，下方单独定义（不依赖数据库）
    # 5M1E 预警数据工具
    "query_downtime": _tool_query_downtime,
    "query_maintenance_due": _tool_query_maintenance_due,
    "query_wms_inventory_health": _tool_query_wms_inventory_health,
    "query_bom_data_quality": _tool_query_bom_data_quality,
    "query_engine_capability_layers": _tool_query_engine_capability_layers,
    "query_sim_evidence_readiness": _tool_query_sim_evidence_readiness,
    "query_simulation_recommendation": _tool_query_simulation_recommendation,
    "query_simulation_sensitivity": _tool_query_simulation_sensitivity,    "query_engine_attribution": _tool_query_engine_attribution,
    "query_chain_convergence": _tool_query_chain_convergence,
    "query_plan_commit_gate": _tool_query_plan_commit_gate,
    "query_shortage_alerts": _tool_query_shortage_alerts,
    "query_stagnant": _tool_query_stagnant,
    "query_spc_anomalies": _tool_query_spc_anomalies,
    "query_environment": _tool_query_environment,
    "get_virtual_factory_status": _tool_get_virtual_factory_status,
    "run_virtual_factory_pulse": _tool_run_virtual_factory_pulse,
}


async def _tool_search_entity(db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None) -> Dict[str, Any]:
    """全站实体精确搜索 — 复用 search_routes 的模块配置，跨工位/设备/产品/工单/员工/仓库/库存/用户查找。"""
    from api.routes.search_routes import SEARCH_MODULES

    keyword = (args.get("keyword") or "").strip()
    if not keyword:
        return {"error": "缺少搜索关键词"}

    like_pattern = f"%{keyword}%"
    results: List[Dict[str, Any]] = []
    for mod in SEARCH_MODULES:
        conditions = " OR ".join(f"CAST({f} AS TEXT) ILIKE :kw" for f in mod["fields"])
        sql = f"SELECT {mod['select']} FROM {mod['from']} WHERE {conditions} LIMIT 5"
        try:
            rows = (await db.execute(text(sql), {"kw": like_pattern})).mappings().all()
            for row in rows:
                results.append({
                    "source": mod["source"],
                    "source_label": mod["label"],
                    **{k: str(v) for k, v in dict(row).items() if v is not None},
                })
        except Exception:
            continue

    if not results:
        return {"found": False, "message": f"未找到与 '{keyword}' 匹配的实体", "results": []}
    return {"found": True, "count": len(results), "results": results}


_TOOL_EXECUTORS["search_entity"] = _tool_search_entity


async def _tool_query_process_knowledge(db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None) -> Dict[str, Any]:
    """流程知识查询（纯知识库，不访问数据库）。"""
    from api.services.process_knowledge_service import query_knowledge
    return query_knowledge(topic=args.get("topic", ""), keyword=args.get("keyword", ""))


_TOOL_EXECUTORS["query_process_knowledge"] = _tool_query_process_knowledge


async def _tool_query_workflow_diagram(db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None) -> Dict[str, Any]:
    """按选择器查询业务工作流或审批实例，统一返回 diagram 契约。"""
    flow_id = str(args.get("flow_id") or "").strip()
    flow_code = str(args.get("flow_code") or "").strip()
    task_type = str(args.get("task_type") or "").strip()
    position = str(args.get("position") or "").strip()
    process_name = str(args.get("process_name") or "").strip()
    workflow_key = str(args.get("workflow_key") or "").strip()
    engine_type = str(args.get("engine_type") or "auto").strip().lower()
    try:
        current_step = max(0, int(args.get("current_step") or 1) - 1)
    except (TypeError, ValueError):
        current_step = 0

    if engine_type != "approval" and any((workflow_key, process_name, position)):
        from api.services.process_knowledge_service import build_registered_workflow_diagram
        return build_registered_workflow_diagram(
            workflow_key=workflow_key,
            process_name=process_name,
            position=position,
            current_step=current_step,
        )

    # 审批实例必须显式指定；禁止“查最近一条”这种会把PMC误连到DCC的兜底。
    if not any((flow_id, flow_code, task_type)):
        return {
            "type": "workflow_diagram",
            "source": "unified_workflow_engine",
            "error": "缺少工作流选择器，系统不会再用最近一条无关审批实例代替",
            "hint": "独立业务流程请提供 process_name/workflow_key，岗位流程请提供 position，审批实例必须提供 flow_id、flow_code 或 task_type。",
        }

    from core.tms.approval_workflow import ApprovalWorkflowEngine
    from database.models import TMSApprovalFlow, TMSTask

    query = select(TMSApprovalFlow).order_by(TMSApprovalFlow.created_at.desc())
    if flow_id:
        query = query.where(TMSApprovalFlow.id == flow_id)
    elif flow_code:
        query = query.where(TMSApprovalFlow.flow_code == flow_code)
    elif task_type:
        query = query.join(TMSTask, TMSTask.id == TMSApprovalFlow.task_id).where(TMSTask.task_type == task_type)
    query = query.limit(1)
    flow = (await db.execute(query)).scalar_one_or_none()
    if not flow:
        return {
            "type": "workflow_diagram",
            "source": "tms_approval_engine",
            "error": "当前流程引擎没有找到可渲染的流程实例",
            "query": {"flow_id": flow_id or None, "flow_code": flow_code or None, "task_type": task_type or None},
            "hint": "请提供流程ID或流程编码；如果要画销售订单评审，需先在流程引擎中配置并发起对应流程。",
        }

    status = await ApprovalWorkflowEngine(db).get_flow_status(str(flow.id))
    if not status:
        return {"type": "workflow_diagram", "source": "tms_approval_engine", "error": "流程状态读取失败"}
    status["type"] = "workflow_diagram"
    status["source"] = "tms_approval_engine"
    status["title"] = status.get("flow_code") or "流程引擎流程图"
    return status


_TOOL_EXECUTORS["query_workflow_diagram"] = _tool_query_workflow_diagram


async def _tool_query_pmc_work_matrix(db: AsyncSession, args: Dict[str, Any], factory_id: Optional[str] = None) -> Dict[str, Any]:
    """查询 PMC 当前工单矩阵，不在 chatbot 层计算业务结果。"""
    from api.services.pmc_work_matrix_service import PmcWorkMatrixService

    code = str(args.get("work_order_code") or "").strip()
    if not code:
        return {"type": "pmc_work_matrix", "error": "缺少主工单号", "hint": "请提供工单号后再生成 PMC 工作矩阵。"}
    return await PmcWorkMatrixService(db).build(factory_id or "", code, args.get("options"))


_TOOL_EXECUTORS["query_pmc_work_matrix"] = _tool_query_pmc_work_matrix


async def _tool_query_pmc_control_tower(
    db: AsyncSession,
    args: Dict[str, Any],
    factory_id: Optional[str] = None,
) -> Dict[str, Any]:
    """统一 PMC 控制塔事实查询；跨模块只读，缺表/无记录都显式返回。"""
    from api.services.pmc_control_tower_service import PmcControlTowerService

    return await PmcControlTowerService(db).collect(
        factory_id or "FAC_MECH_001",
        scope=str(args.get("scope") or "all"),
        material_keyword=args.get("material_keyword"),
        work_order_code=args.get("work_order_code"),
        days=int(args.get("days") or 180),
        rush_quantity=int(args["rush_quantity"]) if args.get("rush_quantity") is not None else None,
        rush_due_date=args.get("rush_due_date"),
        limit=int(args.get("limit") or 20),
    )


_TOOL_EXECUTORS["query_pmc_control_tower"] = _tool_query_pmc_control_tower


async def _tool_query_manufacturing_intelligence(
    db: AsyncSession,
    _args: Dict[str, Any],
    factory_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Return the same safe intelligence overview exposed by the API."""
    from core.intelligence import get_manufacturing_intelligence_service

    overview = await get_manufacturing_intelligence_service().build_overview(
        db, factory_id or "FAC_MECH_001",
    )
    return {
        "type": "manufacturing_intelligence_overview",
        **overview.model_dump(mode="json"),
    }


_TOOL_EXECUTORS["query_manufacturing_intelligence"] = _tool_query_manufacturing_intelligence


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


async def _tool_create_followup_task(db: AsyncSession, args: Dict[str, Any], operator: str = "ai_assistant", factory_id: Optional[str] = None) -> Dict[str, Any]:
    """挂账跟进任务：写入任务中心，由后台扫描器按频率定期跟进。"""
    from api.services import followup_task_service as followup_svc
    return await followup_svc.create_task(
        db, factory_id or "FAC_MECH_001",
        created_by=operator,
        title=str(args.get("title") or ""),
        description=str(args.get("description") or ""),
        agent_key=args.get("agent_key") or None,
        follow_interval_minutes=int(args.get("follow_interval_minutes") or 120),
        block_reason=str(args.get("block_reason") or ""),
        source="chatbot",
        conversation_hint=str(args.get("description") or args.get("title") or "")[:500],
    )


_TOOL_EXECUTORS["create_followup_task"] = _tool_create_followup_task

# ── 计划清单（to-do 模式）──────────────────────────────────────────────────
# 模型用 update_plan 声明/更新本轮多步任务的执行计划。计划不另建表：它随
# tool_call result 落在 assistant 消息的 tool_calls 上，replay 接口原样返回，
# 因此断线重开/历史回放都能看到当时的计划，无需接 checkpoint 或新增事件词汇。
TOOL_DEFINITIONS.append({
    "type": "function",
    "function": {
        "name": "update_plan",
        "description": (
            "声明或更新本次任务的执行计划清单（to-do）。当你接到需要 3 步以上才能完成的任务"
            "（排查/整改/跨系统核对/汇总分析等），先调用一次列出全部步骤，之后每完成一步再调用"
            "一次更新状态。每次传入完整清单（含已完成项），不是增量。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "计划标题，如「排查 A 线停机原因」"},
                "items": {
                    "type": "array",
                    "description": "计划项（全量）",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "稳定标识，同一项多次调用保持一致，如 step1"},
                            "title": {"type": "string", "description": "这一步要做什么"},
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed", "cancelled"],
                                "description": "状态，默认 pending",
                            },
                        },
                        "required": ["id", "title"],
                    },
                },
            },
            "required": ["items"],
        },
    },
})


async def _tool_update_plan(
    db: AsyncSession,
    args: Dict[str, Any],
    operator: str = "ai_assistant",
    factory_id: Optional[str] = None,
) -> Dict[str, Any]:
    """校验并返回计划清单结构。只读工具：不查库、不写库。"""
    raw = args.get("items")
    if not isinstance(raw, list) or not raw:
        return {"error": "items 必须是非空数组，每项形如 {id, title, status}"}

    valid = ("pending", "in_progress", "completed", "cancelled")
    items: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for idx, it in enumerate(raw[:20]):
        if not isinstance(it, dict):
            continue
        title = str(it.get("title") or "").strip()
        if not title:
            continue
        sid = str(it.get("id") or f"step{idx + 1}").strip() or f"step{idx + 1}"
        if sid in seen:  # id 必须唯一，否则前端打勾会串行
            sid = f"{sid}-{idx + 1}"
        seen.add(sid)
        status = str(it.get("status") or "pending").strip().lower()
        if status not in valid:
            status = "pending"
        items.append({"id": sid, "title": title[:120], "status": status})

    if not items:
        return {"error": "items 里没有可用的计划项（每项至少要有 title）"}

    total = len(items)
    done = sum(1 for i in items if i["status"] == "completed")
    return {
        "type": "plan",
        "title": str(args.get("title") or "").strip()[:120] or "执行计划",
        "items": items,
        "total": total,
        "done": done,
        "in_progress": sum(1 for i in items if i["status"] == "in_progress"),
        "progress_pct": round(done / total * 100),
    }


_TOOL_EXECUTORS["update_plan"] = _tool_update_plan

# 写操作工具（需要记录操作人）
WRITE_TOOLS = {
    "create_work_order", "release_work_order", "create_production_report",
    "complete_work_order", "pause_work_order", "resume_work_order", "split_work_order",
    "run_compliance_simulation",
    "run_workflow",
    "export_report_file",
    "edit_online_workbook",
    "export_online_workbook",
    "create_online_pivot",
    "recalculate_online_workbook",
    "reload_online_workbook",
    "acknowledge_alert", "run_alert_patrol",
    "create_followup_task",
}

# 仿真类工具（前端展示用「仿真」色标，区别于写绿/查蓝）
SIM_TOOLS = {
    "run_compliance_simulation", "query_simulation_audits",
    "get_virtual_factory_status", "run_virtual_factory_pulse",
    "query_pmc_rush_impact",
}

# 工具的中文标签（供前端展示）
TOOL_LABELS = {
    "update_plan": "执行计划",
    "query_work_orders": "查询工单",
    "query_order_work_order_status": "订单-工单下发核对",
    "get_work_order_detail": "工单详情",
    "get_production_summary": "生产统计",
    "query_inventory": "查询库存",
    "query_lead_time_evidence": "提前期证据普查",
    "query_pmc_material_supply": "PMC物料供应证据",
    "query_pmc_rush_impact": "PMC插单影响",
    "query_pmc_control_tower": "PMC控制塔",
    "query_manufacturing_intelligence": "制造智能总览",
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
    "scan_online_workbook": "扫描全部公式依赖",
    "query_online_workbook": "读取在线工作簿",
    "recalculate_online_workbook": "重算在线工作簿",
    "reload_online_workbook": "重新加载原始工作簿",
    "edit_online_workbook": "修改在线工作簿",
    "export_online_workbook": "导出在线工作簿",
    "create_online_pivot": "生成在线透视汇总",
    "get_pending_alerts": "预警汇总",
    "query_alert_reviews": "预警审查记录",
    "acknowledge_alert": "确认预警",
    "run_alert_patrol": "预警巡检",
    "query_ocap_tasks": "OCAP待办任务",
    "query_hr_roster": "人力档案",
    "query_workflow_diagram": "完整业务流程图",
    "query_pmc_work_matrix": "PMC工作矩阵",
    "query_process_knowledge": "流程知识",
    # 5M1E 预警数据工具
    "query_downtime": "停机记录",
    "query_maintenance_due": "保养到期",
    "query_wms_inventory_health": "库存健康度",
    "query_bom_data_quality": "BOM 数据质量自检",
    "query_plan_commit_gate": "计划逐单下达就绪门",
    "query_chain_convergence": "链条收敛自检",
    "query_simulation_recommendation": "推演建议与落地复查",
    "query_engine_capability_layers": "引擎分层验收",
    "query_sim_evidence_readiness": "精度判据就绪度",
    "query_simulation_sensitivity": "建模精度与敏感度",    "query_engine_attribution": "交期为什么是这个数（归因）",
    "query_shortage_alerts": "缺料预警",
    "query_stagnant": "呆滞物料",
    "query_spc_anomalies": "SPC失控",
    "query_environment": "车间环境",
    "get_virtual_factory_status": "虚拟工厂状态",
    "run_virtual_factory_pulse": "虚拟工厂脉搏",
    "create_followup_task": "挂账跟进任务",
}


# ==================== 确定性意图路由（业务底座） ====================
# 参考 luaguage chatbot 的 capability catalog / business rule 思路：
# 不依赖模型自由决策，命中业务关键词即强制调用对应工具，从根本上杜绝
# “建议你进入看板/日报中心查看”这类推诿性模糊回答。
# 仅对单步查询类工具做强制路由；写操作/多步操作仍交由模型 auto 编排。
INTENT_RULES: List[Dict[str, Any]] = [
    {
        "tool": "query_manufacturing_intelligence",
        "keywords": [
            "制造智能总览", "制造智能概览", "工厂智能总览", "工厂智能概览",
            "全局经营风险", "当前总体风险", "智能运行状态", "数字员工状态",
        ],
    },
    {
        "tool": "run_virtual_factory_pulse",
        "keywords": [
            "虚拟工厂脉搏", "跑一下虚拟工厂", "推进虚拟工厂", "生成虚拟订单",
            "主动下订单", "自动下订单", "虚拟下单", "虚拟拆单", "维持数据丰富度",
            "按真实节奏", "300柜", "三个月订单", "3个月订单",
        ],
    },
    {
        "tool": "get_virtual_factory_status",
        "keywords": [
            "虚拟工厂", "数据脉搏", "订单节奏", "虚拟订单状态", "虚拟报工",
            "虚拟工单", "现在虚拟工厂怎样", "虚拟工厂状态",
        ],
    },
    {
        "tool": "get_production_summary",
        "keywords": [
            "生产情况", "生产统计", "今日生产", "今天生产", "生产汇总", "生产概览",
            "产量", "稼动率", "生产数据", "生产怎么样", "生产怎样", "今天生产怎么",
            "良品率", "报工情况", "生产概况",
        ],
    },
    {
        "tool": "query_order_work_order_status",
        "keywords": [
            "订单全部下发", "全部下发生产工单", "下发生产工单了吗", "是否下发生产工单",
            "订单有没有工单", "订单是否有工单", "订单拆单情况", "订单到工单",
            "订单工单关系", "订单对应工单", "订单下发情况",
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
        # PMC九类管理问题统一走控制塔，避免被普通“库存/订单/流程”关键词截断。
        "tool": "query_pmc_control_tower",
        "keywords": [
            "PMC能不能回答", "PMC控制塔", "PMC 控制任务推进", "PMC控制任务推进",
            "PMC任务推进", "PMC整体推进", "排过多少订单", "排了多少订单", "排产过多少订单",
            "控过多少物料", "控制过多少物料", "控制了多少物料", "Shortage怎么处理", "shortage怎么处理", "shortage 怎么处理",
            "缺料怎么处理", "缺料如何处理", "物料短缺怎么处理", "物料缺口怎么处理",
            "库存怎么降", "如何降库存", "怎么降库存", "OTD怎么保证", "OTD 怎么保证", "otd怎么保证", "otd 怎么保证", "如何保证OTD",
            "交期风险", "交付风险", "交期有风险的工单", "会迟到的工单", "准时交付",
            "产能怎么平衡", "产能如何平衡", "如何平衡产能", "紧急插单怎么排", "紧急插单如何排", "急单怎么排", "EC/BOM change", "ec/bom change",
            "EC/BOM变更", "ECN怎么处理", "工程变更怎么处理", "BOM变更怎么处理", "supplier delay",
            "supplier delay怎么处理", "供应商 delay 怎么处理", "供应商延迟怎么处理", "供应商延期怎么处理", "供应延迟怎么处理",
            "需要补齐什么数据", "需要补什么数据", "缺什么数据", "数据缺口", "数据完整性", "补齐数据", "补数清单",
        ],
    },
    {
        # PMC 专项规则必须早于普通“库存”，否则“库存齐套率/在途库存”会被截成普通库存查询。
        "tool": "query_pmc_rush_impact",
        "keywords": ["插单影响", "原有订单会晚多久", "VIP急单", "占50%产能", "占用50%产能"],
    },
    {
        # PMC 专项规则必须早于普通“库存”，否则“库存齐套率/在途库存”会被截成普通库存查询。
        "tool": "query_pmc_work_matrix",
        "keywords": [
            "PMC工作矩阵", "PMC矩阵", "工作矩阵", "预排程沙盘", "时间锤", "物料锤",
            "生产锤", "出货锤", "紧急锤", "重算ETA", "ETA推迟", "ETA延迟", "UHN",
            "可加工时间", "库存齐套", "齐套率",
        ],
    },
    {
        # 「提前期准不准/是不是量出来的」是证据问题，不能被只报台账值的供应查询抢走
        "tool": "query_lead_time_evidence",
        "keywords": [
            "提前期准", "提前期可信", "提前期是不是", "提前期怎么来", "提前期多少天", "提前期几天",
            "是不是量出来", "量出来的", "铺的默认", "默认提前期", "台账默认值", "实测到货",
            "到货天数", "到货要多久", "供应商几天到", "交期靠得住",
        ],
    },
    {
        # 供应证据规则也必须早于普通库存，覆盖“库存+在途+PO+BOM复用”复合问题。
        "tool": "query_pmc_material_supply",
        "keywords": [
            "在途", "PO编号", "采购订单", "采购单", "供应商ETA", "预计到货", "库存账龄", "账龄", "库龄",
            "提前期", "物料LT", "BOM能不能用", "BOM用掉", "BOM复用", "能不能被新订单用",
            "呆滞料能不能", "呆滞料复用",
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
        "tool": "query_online_workbook",
        "keywords": ["在线表格内容", "在线工作簿", "读取表格", "查看表格公式", "表格里有什么", "当前表格"],
    },
    {
        "tool": "edit_online_workbook",
        "keywords": ["修改在线表格", "编辑在线表格", "改表格", "改单元格", "写入表格公式", "在线表格加一行"],
    },
    {
        "tool": "export_online_workbook",
        "keywords": ["导出在线表格", "导出当前表格", "导出工作簿", "表格导出xlsx", "下载当前表格"],
    },
    {
        "tool": "create_online_pivot",
        "keywords": ["在线透视表", "生成透视汇总", "做个透视表", "透视汇总"],
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
            "低于再订货点", "再订货点", "该补多少", "补多少", "水位",
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
        "tool": "query_workflow_diagram",
        "keywords": [
            "流程图", "画流程图", "画成流程图", "绘制流程图", "流程可视化",
            "流程图详细", "画出流程", "流程节点图", "流程引擎",
            "岗位工作流", "完整工作流", "完整流程", "端到端流程", "主流程",
            "正常路径", "fallback", "输入输出物", "输入输出", "关联方", "责任链",
            "PMC流程", "PMC流程图", "PMC完整流程", "PMC全流程", "PMC端到端流程",
            "PMC工作流", "PMC的工作流", "PMC 工作流",
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


_WORKFLOW_DIAGRAM_OBJECT_HINTS = (
    "工作流程", "工作流", "流程图", "端到端流程", "完整流程",
    "流程可视化", "流程节点图", "正常路径", "fallback", "输入输出物",
)
_WORKFLOW_DIAGRAM_RENDER_HINTS = (
    "画", "绘制", "生成", "展示", "查看", "可视化", "流程图", "节点图",
)


def _is_explicit_workflow_diagram_request(message: str) -> bool:
    """Disambiguate business workflow drawings from an SPC control chart.

    A phrase such as ``PMC工作流程控制图`` contains the generic SPC keyword
    ``控制图``.  Object + render evidence must win before the ordered keyword
    catalogue, otherwise the model is given the SPC tool while the system
    prompt tells it to call the workflow-diagram tool.
    """
    normalized = (message or "").strip().casefold()
    return bool(
        normalized
        and any(hint in normalized for hint in _WORKFLOW_DIAGRAM_OBJECT_HINTS)
        and any(hint in normalized for hint in _WORKFLOW_DIAGRAM_RENDER_HINTS)
    )


def detect_intent_tool(message: str) -> Optional[str]:
    """确定性意图识别：命中业务关键词则返回应强制调用的工具名，否则返回 None（交给模型 auto 决策）。"""
    if not message:
        return None
    if _is_explicit_workflow_diagram_request(message):
        return "query_workflow_diagram"
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


def _resolve_intent_keyword(message: str) -> Optional[Dict[str, Any]]:
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
    # 只有同时具备明确对象和绘图动作的请求才允许确定性出图；模糊的
    # “流程图”仍交给模型追问，避免回退到无关 PMC/DCC 流程。
    if tool == "query_workflow_diagram" and not _is_explicit_workflow_diagram_request(message):
        return None
    args: Dict[str, Any] = {}
    if tool == "query_order_work_order_status":
        match = re.search(r"\bSO-[A-Za-z0-9_-]+", message, flags=re.IGNORECASE)
        if match:
            args["order_code"] = match.group(0)
        if "虚拟" in message:
            args["virtual_only"] = True
        if any(k in message for k in ["今天", "这6个订单", "这六个订单", "这几个订单"]):
            args["created_today"] = True
        if any(k in message for k in ["6个订单", "六个订单"]):
            args["limit"] = 6
    elif tool == "query_work_orders":
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
    elif tool == "query_workflow_diagram":
        flow_id = re.search(r"(?:流程ID|flow_id)[:：= ]+([A-Za-z0-9_-]+)", message, flags=re.IGNORECASE)
        flow_code = re.search(r"\bFLOW-[A-Za-z0-9_-]+", message, flags=re.IGNORECASE)
        if flow_id:
            args["flow_id"] = flow_id.group(1)
            args["engine_type"] = "approval"
        elif flow_code:
            args["flow_code"] = flow_code.group(0)
            args["engine_type"] = "approval"
        else:
            from api.services.process_knowledge_service import POSITION_SOPS
            normalized_message = message.lower()
            candidates = [
                (key, sop, alias)
                for key, sop in POSITION_SOPS.items()
                for alias in [sop["title"], *sop.get("aliases", [])]
            ]
            candidates.sort(key=lambda item: len(str(item[2])), reverse=True)
            matched = next((item for item in candidates if str(item[2]).lower() in normalized_message), None)
            if matched:
                args["position"] = matched[1]["title"]
                args["workflow_key"] = (
                    "pmc:end_to_end"
                    if matched[0] == "pmc_planner"
                    else f"position:{matched[0]}"
                )
                args["scope"] = "position_end_to_end"
                args["engine_type"] = "business"
            step_match = re.search(r"(?:第|当前第)\s*(\d+)\s*步", message)
            if step_match:
                args["current_step"] = int(step_match.group(1))
        if not any(args.get(key) for key in (
            "flow_id", "flow_code", "task_type", "position", "process_name", "workflow_key",
        )):
            return None
    elif tool == "query_pmc_control_tower":
        scope_keywords = [
            ("orders", ["排过多少订单", "排了多少订单", "排产过多少订单", "订单排程", "排过订单"]),
            ("materials", ["控过多少物料", "控制过多少物料", "物料控制"]),
            ("shortage", ["shortage", "缺料", "缺口"]),
            ("inventory", ["库存怎么降", "如何降库存", "怎么降库存", "降库存", "呆滞库存"]),
            ("otd", ["otd", "交期怎么保证", "准时交付", "交期风险", "交付风险"]),
            ("capacity", ["产能怎么平衡", "产能如何平衡", "如何平衡产能", "产能平衡", "瓶颈"]),
            ("rush", ["紧急插单", "急单怎么排", "插单怎么排", "插单"]),
            ("engineering_change", ["ec/bom", "ecn", "工程变更", "bom变更", "bom change"]),
            ("supplier_delay", ["supplier delay", "供应商延迟", "供应商延期", "供应延迟"]),
        ]
        matched_scopes = [scope for scope, keywords in scope_keywords if any(keyword.lower() in message.lower() for keyword in keywords)]
        args["scope"] = matched_scopes[0] if len(set(matched_scopes)) == 1 else "all"
        material_match = re.search(r"(?:物料|料号|料\s*编码|material)\s*[:：#]?\s*([A-Za-z0-9][A-Za-z0-9._/-]{2,})", message, flags=re.IGNORECASE)
        if material_match:
            args["material_keyword"] = material_match.group(1)
        wo_code = _extract_wo_code(message)
        if wo_code:
            args["work_order_code"] = wo_code
        days_match = re.search(r"(\d+)\s*(?:天|日)", message)
        if days_match:
            args["days"] = int(days_match.group(1))
        quantity_match = re.search(r"(?:插单|急单).{0,12}?(\d+)\s*(?:台|件|pcs|个|数量)?", message, flags=re.IGNORECASE)
        if quantity_match:
            args["rush_quantity"] = int(quantity_match.group(1))
        due_match = re.search(r"(20\d{2}-\d{2}-\d{2})", message)
        if due_match:
            args["rush_due_date"] = due_match.group(1)
    elif tool == "query_pmc_rush_impact":
        quantity_match = re.search(r"(\d+)\s*(?:台|件|pcs|个|数量)", message, flags=re.IGNORECASE)
        if quantity_match:
            args["quantity"] = int(quantity_match.group(1))
        product_match = re.search(r"(?:产品|product(?:_id)?)\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9._/-]{2,})", message, flags=re.IGNORECASE)
        if product_match:
            args["product_id"] = product_match.group(1)
        due_match = re.search(r"(20\d{2}-\d{2}-\d{2})", message)
        if due_match:
            args["due_date"] = due_match.group(1)
        share_match = re.search(r"(?:占|占用)\s*(\d+(?:\.\d+)?)\s*%\s*(?:产能)?", message)
        args["capacity_share"] = float(share_match.group(1)) / 100 if share_match else 0.5
    elif tool == "query_pmc_work_matrix":
        wo_code = _extract_wo_code(message)
        if not wo_code:
            # “齐套率/库存齐套” without a work order is a supply evidence query,
            # not a matrix query that can be fabricated without an order context.
            if any(k in message for k in ["齐套", "在途", "PO编号", "BOM"]):
                return {"tool": "query_pmc_material_supply", "args": {}}
            return None
        args["work_order_code"] = wo_code
        options: Dict[str, Any] = {}
        if "全检" in message and "IQC" in message.upper():
            options["iqc_mode"] = "full"
        elif "抽检" in message and "IQC" in message.upper():
            options["iqc_mode"] = "sampling"
        elif "免检" in message and "IQC" in message.upper():
            options["iqc_mode"] = "exempt"

        yield_match = re.search(r"(?:良率|直通率)\s*(?:从\s*)?(\d+(?:\.\d+)?)\s*%?", message)
        if yield_match:
            yield_value = float(yield_match.group(1))
            options["yield_rate"] = yield_value / 100 if yield_value > 1 else yield_value

        eta_match = re.search(r"(?:ETA|到货|物料).{0,8}?(?:推迟|延迟|晚到|晚)\s*(\d+(?:\.\d+)?)\s*天", message, flags=re.IGNORECASE)
        if eta_match:
            options["material_eta_delay_days"] = float(eta_match.group(1))

        aging_match = re.search(r"(?:呆滞|库龄|不动).{0,6}?(\d+)\s*天", message)
        if aging_match:
            options["dead_stock_days"] = int(aging_match.group(1))

        if any(k in message for k in ["占50%产能", "占用50%产能", "共享50%", "50%的产能"]):
            options["line_occupancy"] = "shared_50"
        if "空运" in message:
            options["enable_air_freight"] = True
        if "外协" in message:
            options["accept_subcontracting"] = True
        if options:
            args["options"] = options
    elif tool == "query_pmc_material_supply":
        days_match = re.search(r"(\d+)\s*(?:天|日)", message)
        if days_match:
            args["days"] = int(days_match.group(1))
        if any(k in message for k in ["呆滞", "长期不动", "超过180天没动", "超过180日没动"]):
            args["only_stagnant"] = True
        material_match = re.search(r"(?:物料|料号|料\s*编码|material)\s*[:：#]?\s*([A-Za-z0-9][A-Za-z0-9._/-]{2,})", message, flags=re.IGNORECASE)
        if material_match:
            args["material_keyword"] = material_match.group(1)
    elif tool == "query_stagnant":
        days_match = re.search(r"(\d+)\s*(?:天|日)", message)
        args["days"] = int(days_match.group(1)) if days_match else 180
        args["limit"] = 50
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


# 必须由确定性规则给出事实答复的工具（PMC 四类）。概率路由（Laya）不得覆盖。
# chat_routes 的 deterministic_handler / route_not_required 直接引用本集合，
# 不要再在别处内联一份，否则会漂移。
DETERMINISTIC_INTENT_TOOLS = frozenset({
    "query_pmc_control_tower",
    "query_order_work_order_status",
    "query_manufacturing_intelligence",
    "query_workflow_diagram",
})


def resolve_intent(message: str) -> Optional[Dict[str, Any]]:
    """确定性意图解析：关键词路由为主，Laya（System 1 决策引擎）可选介入。

    模式见 ``api/services/laya_intent_service.py``：

    * ``off``      —— 纯关键词，等价于历史行为；
    * ``fallback`` —— 关键词**没命中**时才问 Laya（默认，零回归）；
    * ``primary``  —— 先问 Laya，够自信就用它，否则回退关键词；但 PMC 四类
      （``DETERMINISTIC_INTENT_TOOLS``）是硬性确定性契约，关键词命中即优先，
      Laya 不得覆盖。

    Laya 只提供「意图 → 工具」的映射，args 仍由关键词规则提取；映射表刻意只
    覆盖能一一对应的意图（查库存/查工单/设备状态），其余交回模型编排。任何
    Laya 异常（超时/连不上/熔断）都被吞掉，绝不影响本函数原有的确定性行为。
    """
    from api.services import laya_intent_service as laya  # 懒加载，避免循环导入

    laya_mode = laya.mode() if laya.is_enabled() else "off"

    if laya_mode == "primary":
        # 硬性确定性契约优先：PMC 四类必须由关键词规则给出确定性事实答复
        # （见 chat_routes 的系统提示与 deterministic_handler 白名单）。
        # Laya 是概率路由，不得覆盖这四类：否则「库存怎么降」「控过多少物料」
        # 会被降级成 query_inventory，既答非所问，又落不进确定性执行白名单，
        # 等于把确定性答复整条丢掉。
        kw = _resolve_intent_keyword(message)
        if kw and kw.get("tool") in DETERMINISTIC_INTENT_TOOLS:
            return kw
        hit = laya.resolve_tool(message)
        if hit:
            # Laya 与关键词指向同一个工具时，保留关键词提取的更精确 args
            # （例如「在制工单」-> status=in_progress），只借用 Laya 的意图判定。
            if kw and kw.get("tool") == hit["tool"]:
                return kw
            return {"tool": hit["tool"], "args": hit.get("args") or {}}

    resolved = _resolve_intent_keyword(message)
    if resolved:
        return resolved

    if laya_mode in ("fallback", "primary"):
        hit = laya.resolve_tool(message)
        if hit:
            import logging
            logging.getLogger(__name__).info(
                "[laya] 关键词未命中，Laya 路由 -> %s (intent=%s conf=%s)",
                hit["tool"], hit.get("intent"), hit.get("confidence"),
            )
            return {"tool": hit["tool"], "args": hit.get("args") or {}}

    return None


async def resolve_intent_async(message: str) -> Optional[Dict[str, Any]]:
    """``resolve_intent`` 的 async 包装：把同步实现（可能含最多
    ``LAYA_TIMEOUT_SECONDS`` 的 Laya HTTP 调用）放到线程池执行，避免阻塞事件循环。

    **async 调用点必须用这个**（``chat_routes._handle_kernel_chat`` 等）；同步版
    保留给单元测试与纯同步上下文。线程安全：Laya 客户端的熔断计数由
    ``laya_intent_service._lock`` 保护，可安全跨线程调用。
    """
    return await asyncio.to_thread(resolve_intent, message)


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
        if tool_name == "create_followup_task":
            # 挂账任务同时需要操作人（created_by）和当前工厂（数据隔离）
            return await executor(db, arguments, operator=operator, factory_id=factory_id)
        if tool_name == "edit_online_workbook":
            return await executor(db, arguments, operator=operator, factory_id=factory_id)
        if tool_name in {"recalculate_online_workbook", "reload_online_workbook"}:
            return await executor(db, arguments, operator=operator, factory_id=factory_id)
        if tool_name == "export_online_workbook":
            return await executor(db, arguments, operator=operator, factory_id=factory_id)
        if tool_name == "create_online_pivot":
            return await executor(db, arguments, operator=operator, factory_id=factory_id)
        if tool_name == "update_plan":
            # 只读工具：仍走显式分支，避免落进默认分支把 factory_id 按位置塞给 operator
            return await executor(db, arguments, operator=operator, factory_id=factory_id)
        if tool_name in WRITE_TOOLS:
            return await executor(db, arguments, operator)
        return await executor(db, arguments, factory_id)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"工具执行失败：{type(exc).__name__}: {exc}"}


__all__ = ["TOOL_DEFINITIONS", "TOOL_LABELS", "WRITE_TOOLS", "SIM_TOOLS", "execute_tool", "detect_intent_tool", "resolve_intent", "resolve_intent_async", "INTENT_RULES", "DETERMINISTIC_INTENT_TOOLS"]
