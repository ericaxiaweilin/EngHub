"""
多智能体并行编排器（Parallel Orchestrator）
==========================================
核心理念：一个命令 → 意图解析 → 多Agent并行执行 → 结果聚合 → 结构化输出

架构：
- 用户发出复合指令（如"评估这个紧急订单能不能插"）
- Orchestrator 解析意图 → 拆成多个并行子任务
- 各Agent通过 AgentRuntime.execute_parallel 并发执行
- 结果聚合（LLM综合/投票/取首成功）
- 返回结构化报告

不依赖外部框架，基于现有 AgentRuntime + EventBus 自建。
"""
import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Coroutine, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

_logger = logging.getLogger("parallel_orchestrator")


# ═══════════════════════════════════════════════════════════
# 扩展智能体注册表（岗位级 + 功能级）
# ═══════════════════════════════════════════════════════════

AGENT_REGISTRY = {
    # ─── 原有 8 个执行智能体 ───
    "scheduling_agent": {
        "name": "排产智能体", "role": "PMC计划员",
        "domain": "production", "category": "execution",
        "tools": ["check_capacity", "auto_reschedule", "what_if_insert", "capacity_balance"],
    },
    "dispatch_agent": {
        "name": "派工智能体", "role": "产线组长",
        "domain": "production", "category": "execution",
        "tools": ["dispatch_work_order", "check_station_status", "match_operator"],
    },
    "procurement_agent": {
        "name": "采购智能体", "role": "采购员",
        "domain": "supply_chain", "category": "execution",
        "tools": ["check_mrp", "create_purchase_order", "track_supplier"],
    },
    "warehouse_agent": {
        "name": "仓储智能体", "role": "仓管员",
        "domain": "supply_chain", "category": "execution",
        "tools": ["check_stock", "kit_check", "reorder_alert", "location_optimize"],
    },
    "quality_agent": {
        "name": "质量智能体", "role": "品质工程师",
        "domain": "quality", "category": "execution",
        "tools": ["spc_monitor", "defect_analysis", "iqc_check", "ocap_dispatch"],
    },
    "equipment_agent": {
        "name": "设备智能体", "role": "设备工程师",
        "domain": "equipment", "category": "execution",
        "tools": ["oee_query", "pm_schedule", "fault_prediction", "repair_dispatch"],
    },
    "delivery_agent": {
        "name": "交期智能体", "role": "业务跟单",
        "domain": "delivery", "category": "execution",
        "tools": ["eta_calculate", "overdue_alert", "customer_notify"],
    },
    "escalation_agent": {
        "name": "异常升级智能体", "role": "值班主管",
        "domain": "management", "category": "execution",
        "tools": ["classify_alert", "sla_notify", "escalate", "close_loop"],
    },

    # ─── 新增：岗位级智能体 ───
    "pmc_agent": {
        "name": "PMC智能体", "role": "PMC经理",
        "domain": "planning", "category": "decision",
        "description": "生产计划与物料控制统筹，协调排产、采购、仓储三方",
        "tools": ["master_plan_review", "material_plan", "capacity_plan", "order_priority"],
        "system_prompt": (
            "你是PMC经理，负责生产计划与物料控制的全局统筹。"
            "你的职责：1)主生产计划制定与滚动 2)物料需求计划(MRP)审核 "
            "3)产能负荷平衡 4)订单优先级仲裁 5)协调采购/仓储/排产三方联动。"
            "你关注的是全局最优而非局部最优。"
        ),
    },
    "process_engineer_agent": {
        "name": "工艺智能体", "role": "工艺工程师",
        "domain": "engineering", "category": "decision",
        "description": "工艺路线优化、SOP管理、工时定额、工艺变更评估",
        "tools": ["route_optimize", "sop_query", "time_standard", "ecn_evaluate"],
        "system_prompt": (
            "你是工艺工程师，精通加工工艺、装配工艺和工艺路线设计。"
            "你的职责：1)工艺路线制定与优化 2)SOP/作业指导书管理 "
            "3)标准工时测定与维护 4)ECN工程变更评估 5)新工艺导入验证。"
            "你关注质量、效率、成本三者的平衡。"
        ),
    },
    "cost_analyst_agent": {
        "name": "成本智能体", "role": "成本会计",
        "domain": "finance", "category": "decision",
        "description": "产品成本核算、工时成本分析、降本建议",
        "tools": ["product_cost", "labor_cost", "overhead_analysis", "cost_reduction"],
        "system_prompt": (
            "你是成本会计，负责制造成本核算与分析。"
            "你的职责：1)产品标准成本维护 2)实际成本归集与差异分析 "
            "3)工时/机时费率计算 4)降本增效建议 5)报价成本支撑。"
            "你关注成本结构透明和差异可追溯。"
        ),
    },
    "hr_agent": {
        "name": "人事智能体", "role": "HR专员",
        "domain": "hr", "category": "decision",
        "description": "人员排班、技能矩阵、培训需求、绩效数据",
        "tools": ["roster_query", "skill_matrix", "training_plan", "attendance_report"],
        "system_prompt": (
            "你是HR专员，负责生产人员管理。"
            "你的职责：1)排班与出勤管理 2)技能矩阵维护与多能工培养 "
            "3)培训需求识别与计划 4)绩效数据采集 5)人力配置建议。"
            "你关注人岗匹配和团队效能。"
        ),
    },

    # ─── 新增：功能级智能体 ───
    "form_agent": {
        "name": "表单智能体", "role": "文员",
        "domain": "admin", "category": "functional",
        "description": "自动填写/生成各类表单：工单、检验报告、8D、请假单、采购申请",
        "tools": ["fill_work_order", "fill_inspection", "fill_8d", "fill_purchase_req", "fill_leave"],
        "system_prompt": (
            "你是表单填写专员，负责自动生成和填写各类制造业表单。"
            "你的能力：1)生产工单创建与填写 2)检验报告生成 3)8D报告填写 "
            "4)采购申请填写 5)请假/加班单 6)设备维修申请单。"
            "你根据上下文自动填充字段，不确定的字段标注[待确认]。"
        ),
    },
    "report_agent": {
        "name": "报表智能体", "role": "统计员",
        "domain": "analytics", "category": "functional",
        "description": "自动生成日报/周报/月报、KPI汇总、异常统计",
        "tools": ["daily_report", "weekly_summary", "kpi_dashboard", "defect_pareto"],
        "system_prompt": (
            "你是生产统计员，负责各类报表的自动生成。"
            "你的能力：1)生产日报/周报/月报 2)KPI达成率汇总 "
            "3)质量Pareto分析 4)设备OEE报表 5)交期达成统计。"
            "你输出结构化数据+文字摘要，支持图表数据格式。"
        ),
    },
    "safety_agent": {
        "name": "安全智能体", "role": "安全员",
        "domain": "safety", "category": "functional",
        "description": "安全隐患排查、作业许可、事故记录、合规检查",
        "tools": ["hazard_check", "permit_review", "incident_record", "compliance_audit"],
        "system_prompt": (
            "你是工厂安全员，负责EHS(环境健康安全)管理。"
            "你的职责：1)安全隐患排查与整改跟踪 2)危险作业许可审批 "
            "3)事故/未遂事件记录与分析 4)合规性检查 5)安全培训提醒。"
            "安全一票否决：发现重大隐患必须立即上报。"
        ),
    },
    "document_agent": {
        "name": "文控智能体", "role": "文控员",
        "domain": "admin", "category": "functional",
        "description": "文件版本管理、受控发放、到期提醒、体系文件维护",
        "tools": ["version_control", "doc_search", "review_remind", "obsolete_check"],
        "system_prompt": (
            "你是文控员，负责体系文件与记录管理。"
            "你的职责：1)文件版本控制与受控发放 2)文件到期复审提醒 "
            "3)作废文件回收 4)体系文件检索 5)外审/内审文件准备。"
            "你确保现场使用的都是最新受控版本。"
        ),
    },
}


# ═══════════════════════════════════════════════════════════
# 意图 → 并行任务模板
# ═══════════════════════════════════════════════════════════

INTENT_TEMPLATES = {
    "rush_order_evaluation": {
        "name": "紧急插单评估",
        "agents": ["scheduling_agent", "warehouse_agent", "delivery_agent", "pmc_agent"],
        "aggregation": "llm_synthesis",
        "description": "评估紧急订单能否插入当前计划",
    },
    "quality_root_cause": {
        "name": "质量根因分析",
        "agents": ["quality_agent", "process_engineer_agent", "equipment_agent", "hr_agent"],
        "aggregation": "llm_synthesis",
        "description": "多因素质量根因分析",
    },
    "production_status": {
        "name": "生产全景",
        "agents": ["scheduling_agent", "dispatch_agent", "equipment_agent", "quality_agent", "delivery_agent"],
        "aggregation": "llm_synthesis",
        "description": "一键获取生产全景状态",
    },
    "cost_estimation": {
        "name": "成本估算",
        "agents": ["cost_analyst_agent", "procurement_agent", "process_engineer_agent"],
        "aggregation": "llm_synthesis",
        "description": "产品/订单成本快速估算",
    },
    "new_product_readiness": {
        "name": "新品导入评估",
        "agents": ["process_engineer_agent", "procurement_agent", "equipment_agent", "hr_agent", "quality_agent"],
        "aggregation": "llm_synthesis",
        "description": "新产品导入准备度评估",
    },
    "shift_handover": {
        "name": "交接班报告",
        "agents": ["scheduling_agent", "quality_agent", "equipment_agent", "dispatch_agent"],
        "aggregation": "llm_synthesis",
        "description": "自动生成班次交接报告",
    },
    "supplier_evaluation": {
        "name": "供应商评估",
        "agents": ["procurement_agent", "quality_agent", "delivery_agent", "cost_analyst_agent"],
        "aggregation": "llm_synthesis",
        "description": "供应商综合评估",
    },
    "capacity_expansion": {
        "name": "产能扩展分析",
        "agents": ["scheduling_agent", "equipment_agent", "hr_agent", "cost_analyst_agent"],
        "aggregation": "llm_synthesis",
        "description": "产能瓶颈分析与扩展方案",
    },
    "form_generation": {
        "name": "表单生成",
        "agents": ["form_agent"],
        "aggregation": "first_success",
        "description": "自动生成各类表单",
    },
    "daily_report": {
        "name": "日报生成",
        "agents": ["report_agent", "scheduling_agent", "quality_agent", "equipment_agent"],
        "aggregation": "llm_synthesis",
        "description": "自动汇总生成生产日报",
    },
}

# 关键词 → 意图映射（快速路由）
KEYWORD_INTENT_MAP = {
    "插单": "rush_order_evaluation",
    "紧急订单": "rush_order_evaluation",
    "能不能插": "rush_order_evaluation",
    "根因": "quality_root_cause",
    "原因分析": "quality_root_cause",
    "为什么不良": "quality_root_cause",
    "生产状态": "production_status",
    "全景": "production_status",
    "现在什么情况": "production_status",
    "总体情况": "production_status",
    "生产情况": "production_status",
    "什么情况": "production_status",
    "现状": "production_status",
    "概览": "production_status",
    "成本": "cost_estimation",
    "多少钱": "cost_estimation",
    "报价": "cost_estimation",
    "新品": "new_product_readiness",
    "导入": "new_product_readiness",
    "NPI": "new_product_readiness",
    "交接": "shift_handover",
    "交接班": "shift_handover",
    "供应商": "supplier_evaluation",
    "产能": "capacity_expansion",
    "瓶颈": "capacity_expansion",
    "扩产": "capacity_expansion",
    "填表": "form_generation",
    "填写": "form_generation",
    "生成报告": "form_generation",
    "日报": "daily_report",
    "周报": "daily_report",
    "汇报": "daily_report",
    # 指挥官模式（特殊处理，不走普通编排）
    "指挥官": "__commander__",
    "工厂指挥": "__commander__",
    "接单": "__commander__",
    "投产": "__commander__",
    "开工": "__commander__",
    "安排生产": "__commander__",
    "工厂态势": "__commander__",
    "订单模式": "__commander__",
}


@dataclass
class SubTaskResult:
    """子任务执行结果"""
    agent_key: str
    agent_name: str
    status: str = "pending"  # pending / running / success / error
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    duration_ms: float = 0
    started_at: Optional[float] = None
    finished_at: Optional[float] = None


@dataclass
class OrchestrationResult:
    """编排执行总结果"""
    command_id: str
    intent: str
    intent_name: str
    factory_id: str
    status: str = "running"  # running / completed / partial / failed
    sub_tasks: List[SubTaskResult] = field(default_factory=list)
    synthesis: Optional[Dict[str, Any]] = None
    total_duration_ms: float = 0
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "command_id": self.command_id,
            "intent": self.intent,
            "intent_name": self.intent_name,
            "factory_id": self.factory_id,
            "status": self.status,
            "sub_tasks": [{
                "agent_key": t.agent_key,
                "agent_name": t.agent_name,
                "status": t.status,
                "result": t.result,
                "error": t.error,
                "duration_ms": round(t.duration_ms, 1),
            } for t in self.sub_tasks],
            "synthesis": self.synthesis,
            "total_duration_ms": round(self.total_duration_ms, 1),
            "created_at": self.created_at,
        }


class ParallelOrchestrator:
    """多智能体并行编排器"""

    # 全局执行记录（内存环形缓冲）
    _history: List[OrchestrationResult] = []
    _history_max = 100

    def __init__(self, db: AsyncSession):
        self.db = db

    # ═══════════════════════════════════════════════════════════
    # 意图识别
    # ═══════════════════════════════════════════════════════════

    def resolve_intent(self, user_message: str) -> Optional[str]:
        """从用户消息中识别并行编排意图"""
        for keyword, intent in KEYWORD_INTENT_MAP.items():
            if keyword in user_message:
                return intent
        return None

    def list_intents(self) -> Dict[str, Any]:
        """列出所有可用的并行编排意图"""
        return {
            "total": len(INTENT_TEMPLATES),
            "intents": [{
                "key": k,
                "name": v["name"],
                "description": v["description"],
                "agents": [AGENT_REGISTRY[a]["name"] for a in v["agents"]],
                "aggregation": v["aggregation"],
            } for k, v in INTENT_TEMPLATES.items()],
        }

    def list_agents(self) -> Dict[str, Any]:
        """列出所有注册的智能体"""
        categories = {}
        for key, agent in AGENT_REGISTRY.items():
            cat = agent["category"]
            if cat not in categories:
                categories[cat] = []
            categories[cat].append({
                "key": key,
                "name": agent["name"],
                "role": agent["role"],
                "domain": agent["domain"],
                "description": agent.get("description", ""),
                "tools": agent.get("tools", []),
            })
        return {"total": len(AGENT_REGISTRY), "categories": categories}

    # ═══════════════════════════════════════════════════════════
    # 核心：并行编排执行
    # ═══════════════════════════════════════════════════════════

    async def execute(
        self,
        intent: str,
        factory_id: str,
        context: Dict[str, Any],
        user_message: str = "",
    ) -> OrchestrationResult:
        """
        执行并行编排：
        1. 解析意图 → 获取参与的Agent列表
        2. 各Agent并行执行数据采集/分析
        3. 结果聚合（LLM综合/投票/取首成功）
        4. 返回结构化结果
        """
        template = INTENT_TEMPLATES.get(intent)
        if not template:
            result = OrchestrationResult(
                command_id=str(uuid.uuid4()),
                intent=intent,
                intent_name="未知意图",
                factory_id=factory_id,
                status="failed",
            )
            result.synthesis = {"error": f"未知意图: {intent}", "available": list(INTENT_TEMPLATES.keys())}
            return result

        command_id = str(uuid.uuid4())
        start_time = time.time()

        orch_result = OrchestrationResult(
            command_id=command_id,
            intent=intent,
            intent_name=template["name"],
            factory_id=factory_id,
            status="running",
        )

        _logger.info(f"[orchestrator] 启动并行编排: {template['name']} | agents={template['agents']} | cmd={command_id[:8]}")

        # 初始化子任务
        for agent_key in template["agents"]:
            agent_info = AGENT_REGISTRY.get(agent_key, {})
            orch_result.sub_tasks.append(SubTaskResult(
                agent_key=agent_key,
                agent_name=agent_info.get("name", agent_key),
                status="pending",
            ))

        # 并行执行所有子任务
        tasks = []
        for i, agent_key in enumerate(template["agents"]):
            tasks.append(self._execute_agent_task(orch_result.sub_tasks[i], factory_id, context, user_message))

        await asyncio.gather(*tasks, return_exceptions=True)

        # 聚合结果
        aggregation = template["aggregation"]
        if aggregation == "llm_synthesis":
            orch_result.synthesis = await self._llm_synthesize(template, orch_result.sub_tasks, context, user_message)
        elif aggregation == "first_success":
            for t in orch_result.sub_tasks:
                if t.status == "success" and t.result:
                    orch_result.synthesis = t.result
                    break
        elif aggregation == "vote":
            orch_result.synthesis = self._vote_aggregate(orch_result.sub_tasks)

        # 确定最终状态
        success_count = sum(1 for t in orch_result.sub_tasks if t.status == "success")
        if success_count == len(orch_result.sub_tasks):
            orch_result.status = "completed"
        elif success_count > 0:
            orch_result.status = "partial"
        else:
            orch_result.status = "failed"

        orch_result.total_duration_ms = (time.time() - start_time) * 1000

        # 记录历史
        self._history.append(orch_result)
        if len(self._history) > self._history_max:
            self._history = self._history[-self._history_max:]

        _logger.info(
            f"[orchestrator] 完成: {template['name']} | status={orch_result.status} | "
            f"{success_count}/{len(orch_result.sub_tasks)} agents | {orch_result.total_duration_ms:.0f}ms"
        )

        # 持久化到数据库
        await self._persist_result(orch_result)

        return orch_result

    async def _execute_agent_task(
        self,
        sub_task: SubTaskResult,
        factory_id: str,
        context: Dict[str, Any],
        user_message: str,
    ):
        """执行单个Agent的子任务"""
        sub_task.status = "running"
        sub_task.started_at = time.time()

        try:
            result = await self._agent_collect_data(sub_task.agent_key, factory_id, context)
            sub_task.result = result
            sub_task.status = "success"
        except Exception as e:
            sub_task.error = str(e)
            sub_task.status = "error"
            _logger.warning(f"[orchestrator] {sub_task.agent_key} 执行失败: {e}")
        finally:
            sub_task.finished_at = time.time()
            sub_task.duration_ms = (sub_task.finished_at - sub_task.started_at) * 1000

    # ═══════════════════════════════════════════════════════════
    # Agent 数据采集（各Agent从DB获取自己领域的数据）
    # ═══════════════════════════════════════════════════════════

    async def _agent_collect_data(
        self, agent_key: str, factory_id: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """根据Agent类型采集对应领域数据"""
        collector = getattr(self, f"_collect_{agent_key}", None)
        if collector:
            return await collector(factory_id, context)
        return {"agent": agent_key, "note": "该智能体数据采集器待实现", "domain": AGENT_REGISTRY.get(agent_key, {}).get("domain")}

    async def _collect_scheduling_agent(self, factory_id: str, ctx: Dict) -> Dict:
        result = await self.db.execute(text("""
            SELECT COUNT(*) as total_orders,
                   SUM(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END) as in_progress,
                   SUM(CASE WHEN status IN ('released','pending') THEN 1 ELSE 0 END) as waiting,
                   AVG(CASE WHEN planned_due IS NOT NULL AND status != 'completed'
                       THEN EXTRACT(EPOCH FROM (planned_due - NOW()))/86400 END) as avg_days_to_due
            FROM work_orders WHERE factory_id = :fid AND status != 'completed'
        """), {"fid": factory_id})
        row = dict(result.first()._mapping)

        # 产能负荷
        cap = await self.db.execute(text("""
            SELECT t.station_id,
                   COUNT(*) as task_count,
                   SUM(EXTRACT(EPOCH FROM (t.planned_end - t.planned_start))/3600) as busy_hours
            FROM aps_schedule_tasks t
            JOIN aps_schedules s ON t.schedule_id = s.id
            WHERE s.factory_id = :fid AND s.status IN ('draft','confirmed') AND t.planned_start > NOW()
            GROUP BY t.station_id ORDER BY busy_hours DESC
        """), {"fid": factory_id})
        stations = [dict(r) for r in cap.mappings().all()]

        return {
            "role": "排产智能体(PMC计划员)",
            "orders": {"total": row["total_orders"], "in_progress": row["in_progress"], "waiting": row["waiting"]},
            "avg_days_to_due": round(row["avg_days_to_due"] or 0, 1),
            "station_load": [{"station": s["station_id"], "tasks": s["task_count"], "hours": round(s["busy_hours"] or 0, 1)} for s in stations[:8]],
            "capacity_note": "产能利用率基于未来排程任务计算",
        }

    async def _collect_warehouse_agent(self, factory_id: str, ctx: Dict) -> Dict:
        result = await self.db.execute(text("""
            SELECT COUNT(DISTINCT material_code) as sku_count,
                   SUM(CASE WHEN available_qty <= COALESCE(reorder_point, 20) THEN 1 ELSE 0 END) as low_stock,
                   SUM(available_qty * COALESCE(unit_cost, 0)) as total_value
            FROM inventory WHERE factory_id = :fid
        """), {"fid": factory_id})
        row = dict(result.first()._mapping)
        return {
            "role": "仓储智能体(仓管员)",
            "sku_count": row["sku_count"],
            "low_stock_items": row["low_stock"],
            "inventory_value": round(row["total_value"] or 0, 0),
            "kit_status": "需指定工单进行齐套检查",
        }

    async def _collect_delivery_agent(self, factory_id: str, ctx: Dict) -> Dict:
        result = await self.db.execute(text("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN planned_due < NOW() AND status != 'completed' THEN 1 ELSE 0 END) as overdue,
                   SUM(CASE WHEN planned_due BETWEEN NOW() AND NOW() + INTERVAL '3 days' THEN 1 ELSE 0 END) as due_soon,
                   SUM(CASE WHEN planned_due BETWEEN NOW() AND NOW() + INTERVAL '7 days' THEN 1 ELSE 0 END) as due_7d
            FROM work_orders WHERE factory_id = :fid AND status IN ('released','pending','in_progress')
        """), {"fid": factory_id})
        row = dict(result.first()._mapping)
        return {
            "role": "交期智能体(业务跟单)",
            "active_orders": row["total"],
            "overdue": row["overdue"],
            "due_3_days": row["due_soon"],
            "due_7_days": row["due_7d"],
        }

    async def _collect_quality_agent(self, factory_id: str, ctx: Dict) -> Dict:
        try:
            result = await self.db.execute(text("""
                SELECT COUNT(*) as total_insp,
                       SUM(CASE WHEN result = 'fail' THEN 1 ELSE 0 END) as fail_count
                FROM inspection_records WHERE factory_id = :fid AND created_at > NOW() - INTERVAL '30 days'
            """), {"fid": factory_id})
            row = result.first()
            total = (row[0] or 0) if row else 0
            fail = (row[1] or 0) if row else 0
        except Exception:
            total, fail = 0, 0

        # 8D 状态
        try:
            d8 = await self.db.execute(text("""
                SELECT status, COUNT(*) as cnt FROM eight_d_reports WHERE factory_id = :fid GROUP BY status
            """), {"fid": factory_id})
            d8_status = {r[0]: r[1] for r in d8.fetchall()}
        except Exception:
            d8_status = {}

        return {
            "role": "质量智能体(品质工程师)",
            "inspection_30d": {"total": total, "fail": fail, "fail_rate": round(fail / max(total, 1) * 100, 1)},
            "8d_reports": d8_status,
        }

    async def _collect_equipment_agent(self, factory_id: str, ctx: Dict) -> Dict:
        result = await self.db.execute(text("""
            SELECT status, COUNT(*) as cnt FROM equipment WHERE factory_id = :fid GROUP BY status
        """), {"fid": factory_id})
        statuses = {r[0]: r[1] for r in result.fetchall()}

        # 近期维修
        maint = await self.db.execute(text("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending
            FROM maintenance_orders WHERE factory_id = :fid AND created_at > NOW() - INTERVAL '30 days'
        """), {"fid": factory_id})
        m = maint.first()

        return {
            "role": "设备智能体(设备工程师)",
            "equipment_status": statuses,
            "maintenance_30d": {"total": m[0] if m else 0, "pending": m[1] if m else 0},
        }

    async def _collect_dispatch_agent(self, factory_id: str, ctx: Dict) -> Dict:
        result = await self.db.execute(text("""
            SELECT status, COUNT(*) as cnt FROM work_orders
            WHERE factory_id = :fid AND status IN ('released','in_progress','pending')
            GROUP BY status
        """), {"fid": factory_id})
        wo_status = {r[0]: r[1] for r in result.fetchall()}
        return {
            "role": "派工智能体(产线组长)",
            "work_order_status": wo_status,
        }

    async def _collect_pmc_agent(self, factory_id: str, ctx: Dict) -> Dict:
        # PMC 综合视角：计划达成 + 物料 + 产能
        plan = await self.db.execute(text("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN status = 'completed' AND actual_end <= planned_due THEN 1 ELSE 0 END) as on_time,
                   SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed
            FROM work_orders WHERE factory_id = :fid AND created_at > NOW() - INTERVAL '30 days'
        """), {"fid": factory_id})
        p = plan.first()
        completed = (p[2] or 0) if p else 0
        on_time = (p[1] or 0) if p else 0

        return {
            "role": "PMC智能体(PMC经理)",
            "plan_achievement": {
                "completed_30d": completed,
                "on_time": on_time,
                "on_time_rate": round(on_time / max(completed, 1) * 100, 1),
            },
            "coordination_note": "PMC统筹排产、采购、仓储三方联动",
        }

    async def _collect_procurement_agent(self, factory_id: str, ctx: Dict) -> Dict:
        result = await self.db.execute(text("""
            SELECT COUNT(*) as total_po,
                   SUM(CASE WHEN status IN ('pending','approved') THEN 1 ELSE 0 END) as open_po
            FROM purchase_orders WHERE factory_id = :fid
        """), {"fid": factory_id})
        row = result.first()
        return {
            "role": "采购智能体(采购员)",
            "purchase_orders": {"total": row[0] if row else 0, "open": row[1] if row else 0},
        }

    async def _collect_process_engineer_agent(self, factory_id: str, ctx: Dict) -> Dict:
        result = await self.db.execute(text("""
            SELECT COUNT(*) as route_count FROM routing_headers WHERE factory_id = :fid
        """), {"fid": factory_id})
        row = result.first()
        return {
            "role": "工艺智能体(工艺工程师)",
            "routing_count": row[0] if row else 0,
            "note": "工艺路线、SOP、标准工时数据",
        }

    async def _collect_cost_analyst_agent(self, factory_id: str, ctx: Dict) -> Dict:
        return {
            "role": "成本智能体(成本会计)",
            "note": "成本数据来源于ERP集成",
            "capabilities": ["产品标准成本", "工时费率", "制造费用分摊", "差异分析"],
        }

    async def _collect_hr_agent(self, factory_id: str, ctx: Dict) -> Dict:
        result = await self.db.execute(text("""
            SELECT COUNT(*) as total, SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) as active
            FROM hr_employees WHERE factory_id = :fid
        """), {"fid": factory_id})
        row = result.first()
        return {
            "role": "人事智能体(HR专员)",
            "headcount": {"total": row[0] if row else 0, "active": row[1] if row else 0},
        }

    async def _collect_form_agent(self, factory_id: str, ctx: Dict) -> Dict:
        return {
            "role": "表单智能体(文员)",
            "capabilities": ["工单", "检验报告", "8D报告", "采购申请", "请假单", "维修申请"],
            "context": ctx,
            "note": "根据上下文自动填充表单字段",
        }

    async def _collect_report_agent(self, factory_id: str, ctx: Dict) -> Dict:
        # 汇总今日生产数据
        today = await self.db.execute(text("""
            SELECT COUNT(*) as wo_completed FROM work_orders
            WHERE factory_id = :fid AND status = 'completed' AND actual_end >= CURRENT_DATE
        """), {"fid": factory_id})
        row = today.first()
        return {
            "role": "报表智能体(统计员)",
            "today_completed": row[0] if row else 0,
            "report_types": ["日报", "周报", "月报", "KPI汇总", "Pareto分析"],
        }

    async def _collect_safety_agent(self, factory_id: str, ctx: Dict) -> Dict:
        return {
            "role": "安全智能体(安全员)",
            "capabilities": ["隐患排查", "作业许可", "事故记录", "合规检查"],
        }

    async def _collect_document_agent(self, factory_id: str, ctx: Dict) -> Dict:
        return {
            "role": "文控智能体(文控员)",
            "capabilities": ["版本控制", "受控发放", "到期提醒", "体系文件检索"],
        }

    # ═══════════════════════════════════════════════════════════
    # 结果聚合
    # ═══════════════════════════════════════════════════════════

    async def _llm_synthesize(
        self, template: Dict, sub_tasks: List[SubTaskResult], context: Dict, user_message: str
    ) -> Dict[str, Any]:
        """LLM 综合多Agent数据给出结构化建议"""
        # 构建 prompt
        parts = [
            f"你是制造企业的智能决策协调系统。当前任务：{template['name']}",
            f"\n用户原始指令：{user_message or template['description']}",
            f"\n## 各智能体并行采集的数据",
        ]
        for t in sub_tasks:
            if t.status == "success" and t.result:
                parts.append(f"\n### {t.agent_name}")
                parts.append(f"```json\n{json.dumps(t.result, ensure_ascii=False, default=str)[:2000]}\n```")
            elif t.status == "error":
                parts.append(f"\n### {t.agent_name}\n⚠️ 数据采集失败: {t.error}")

        parts.append("\n## 要求")
        parts.append("综合以上各智能体数据，给出：")
        parts.append("1. 总体判断（一句话）")
        parts.append("2. 关键发现（3-5条）")
        parts.append("3. 风险点")
        parts.append("4. 建议行动（按优先级排序）")
        parts.append("5. 需要人工决策的事项（如有）")
        parts.append("\n输出JSON格式：")
        parts.append('{"summary": "...", "findings": [...], "risks": [...], "actions": [...], "need_human": [...]}')

        prompt = "\n".join(parts)

        try:
            from api.routes.chat_routes import MODEL_STACK_CHAT_TASK_ID, _call_llm, _resolve_model_route
            route = await _resolve_model_route(MODEL_STACK_CHAT_TASK_ID, prompt_tokens=max(1, len(prompt) // 4), max_completion_tokens=2000)
            resp = await _call_llm(
                {
                    "model": route["gateway_model"],
                    "messages": [
                        {"role": "system", "content": "你是制造企业的智能决策系统。基于多智能体并行采集的数据，给出客观、结构化的综合分析和行动建议。只输出JSON。"},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.3,
                    "max_tokens": route["max_completion_tokens"],
                },
                request_timeout=route["request_timeout"],
            )
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"]
                # 解析 JSON
                text_clean = content.strip()
                if text_clean.startswith("```"):
                    text_clean = text_clean.split("\n", 1)[1].rsplit("```", 1)[0]
                return json.loads(text_clean)
            return {"summary": "LLM调用失败", "raw_status": resp.status_code}
        except json.JSONDecodeError as e:
            return {"summary": "LLM输出解析失败", "raw": str(e)}
        except Exception as e:
            _logger.warning(f"[orchestrator] LLM综合失败: {e}")
            # 降级：直接返回各Agent原始数据
            return {
                "summary": "LLM不可用，以下为各智能体原始数据",
                "degraded": True,
                "agent_data": {t.agent_key: t.result for t in sub_tasks if t.result},
            }

    def _vote_aggregate(self, sub_tasks: List[SubTaskResult]) -> Dict[str, Any]:
        """投票聚合（多数决）"""
        results = [t.result for t in sub_tasks if t.status == "success" and t.result]
        return {"vote_results": results, "total_voters": len(results)}

    # ═══════════════════════════════════════════════════════════
    # 持久化 + 历史
    # ═══════════════════════════════════════════════════════════

    async def _persist_result(self, result: OrchestrationResult):
        """持久化编排结果到数据库"""
        try:
            await self.db.execute(text("""
                INSERT INTO orchestration_logs (id, factory_id, intent, intent_name, status,
                    sub_tasks, synthesis, total_duration_ms, created_at)
                VALUES (:id, :fid, :intent, :iname, :status, :tasks, :syn, :dur, NOW())
            """), {
                "id": result.command_id,
                "fid": result.factory_id,
                "intent": result.intent,
                "iname": result.intent_name,
                "status": result.status,
                "tasks": json.dumps([{
                    "agent": t.agent_key, "status": t.status, "ms": round(t.duration_ms)
                } for t in result.sub_tasks], ensure_ascii=False),
                "syn": json.dumps(result.synthesis, ensure_ascii=False, default=str)[:5000] if result.synthesis else None,
                "dur": round(result.total_duration_ms),
            })
            await self.db.commit()
        except Exception as e:
            _logger.debug(f"[orchestrator] 持久化失败(表可能不存在): {e}")
            try:
                await self.db.rollback()
            except Exception:
                pass

    def get_history(self, limit: int = 20) -> Dict[str, Any]:
        """获取编排历史"""
        recent = self._history[-limit:]
        return {
            "total": len(self._history),
            "showing": len(recent),
            "records": [r.to_dict() for r in reversed(recent)],
        }
