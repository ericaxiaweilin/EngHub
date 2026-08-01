"""
CrewAI 推理层（组织层多Agent协商）
====================================
核心理念：确定性执行用事件引擎，复杂决策用LLM推理。

架构：
- 组织层（本服务）：多个Agent角色协商复杂决策
- 个人层（personal_knowledge）：个人经验沉淀，被组织层咨询
- 执行层（8个智能体）：确定性规则执行

Crew定义：
- 每个Crew = 一个复杂决策场景
- 每个Crew有多个Agent角色（从系统数据中获取各自视角）
- LLM综合多视角给出结构化建议
- 建议回到执行层由对应智能体执行

不依赖crewai库，用相同模式自建（轻量+可控+可审计）。
后续如需替换为crewai库，接口不变。
"""
import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

_logger = logging.getLogger("crew_orchestration")

# ═══════════════════════════════════════════════════════════
# Crew 定义（组织层决策场景）
# ═══════════════════════════════════════════════════════════

CREWS = {
    "rush_order_evaluation": {
        "name": "紧急插单评估",
        "goal": "评估一个紧急订单能否插入当前生产计划，给出可行性和影响分析",
        "process": "sequential",  # sequential/hierarchical
        "agents": [
            {
                "role": "排产分析师",
                "goal": "评估当前产能是否有余量插入新单",
                "data_source": "scheduling",  # 从哪个智能体获取数据
                "backstory": "你是资深生产计划员，熟悉产线负荷和排程约束",
            },
            {
                "role": "物料分析师",
                "goal": "评估物料是否齐套，采购周期是否来得及",
                "data_source": "warehouse",
                "backstory": "你是供应链管理专家，熟悉物料采购周期和库存状况",
            },
            {
                "role": "交期分析师",
                "goal": "评估插单对现有订单交期的影响",
                "data_source": "delivery",
                "backstory": "你是客户服务经理，关注客户交期承诺和违约风险",
            },
        ],
        "output_format": {
            "feasible": "bool - 是否可行",
            "confidence": "0-100 - 信心度",
            "impact_summary": "str - 影响摘要",
            "conditions": "list - 可行条件（如需加班/需提前采购）",
            "risks": "list - 风险点",
            "recommendation": "str - 最终建议",
        },
    },
    "quality_root_cause": {
        "name": "质量根因分析",
        "goal": "对一个质量问题进行多因素根因分析，给出最可能的原因和纠正措施",
        "process": "sequential",
        "agents": [
            {
                "role": "工艺分析师",
                "goal": "从工艺参数和操作方法角度分析可能原因",
                "data_source": "process",
                "backstory": "你是工艺工程师，精通加工参数、刀具、夹具对质量的影响",
            },
            {
                "role": "设备分析师",
                "goal": "从设备状态和精度角度分析可能原因",
                "data_source": "equipment",
                "backstory": "你是设备维护专家，熟悉设备磨损、精度漂移对产品质量的影响",
            },
            {
                "role": "物料分析师",
                "goal": "从来料质量和批次变化角度分析可能原因",
                "data_source": "material",
                "backstory": "你是来料品质工程师，熟悉不同供应商/批次材料的质量波动",
            },
            {
                "role": "人员分析师",
                "goal": "从操作人员技能和状态角度分析可能原因",
                "data_source": "personnel",
                "backstory": "你是班组长，了解操作人员技能水平和近期状态",
            },
        ],
        "output_format": {
            "most_likely_cause": "str - 最可能原因",
            "confidence": "0-100",
            "contributing_factors": "list - 贡献因素",
            "immediate_action": "str - 立即措施",
            "corrective_action": "str - 纠正措施",
            "preventive_action": "str - 预防措施",
            "need_expert": "str|null - 需要咨询的专家（个人层）",
        },
    },
    "supplier_selection": {
        "name": "供应商选择",
        "goal": "综合评估多个供应商，给出最优选择建议",
        "process": "hierarchical",
        "agents": [
            {
                "role": "成本分析师",
                "goal": "比较各供应商的总拥有成本（单价+运费+质量成本）",
                "data_source": "cost",
                "backstory": "你是采购成本分析师，关注TCO而非单纯单价",
            },
            {
                "role": "质量分析师",
                "goal": "比较各供应商的历史质量表现",
                "data_source": "quality",
                "backstory": "你是供应商质量工程师，关注来料合格率和质量稳定性",
            },
            {
                "role": "交付分析师",
                "goal": "比较各供应商的交期表现和产能",
                "data_source": "delivery",
                "backstory": "你是供应链计划员，关注交期准时率和供应稳定性",
            },
        ],
        "output_format": {
            "recommended_supplier": "str - 推荐供应商",
            "score_breakdown": "dict - 各维度评分",
            "reasoning": "str - 选择理由",
            "risks": "list - 风险点",
            "negotiation_points": "list - 谈判要点",
        },
    },
}


class CrewOrchestration:
    """CrewAI推理层 - 组织层多Agent协商"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_crews(self) -> Dict[str, Any]:
        """列出所有可用的Crew"""
        return {
            "total": len(CREWS),
            "crews": [{
                "key": k,
                "name": v["name"],
                "goal": v["goal"],
                "process": v["process"],
                "agents": [a["role"] for a in v["agents"]],
                "output_format": list(v["output_format"].keys()),
            } for k, v in CREWS.items()],
        }

    async def execute_crew(
        self, crew_key: str, factory_id: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        执行一个Crew（多Agent协商决策）
        1. 各Agent角色从系统获取数据
        2. 汇总多视角数据
        3. LLM综合推理
        4. 返回结构化建议
        """
        crew = CREWS.get(crew_key)
        if not crew:
            return {"error": f"未知Crew: {crew_key}", "available": list(CREWS.keys())}

        _logger.info(f"[crew] 启动 {crew['name']}: {context}")

        # 1. 各Agent获取数据
        agent_inputs = []
        for agent_def in crew["agents"]:
            data = await self._gather_agent_data(agent_def["data_source"], factory_id, context)
            agent_inputs.append({
                "role": agent_def["role"],
                "goal": agent_def["goal"],
                "backstory": agent_def["backstory"],
                "data": data,
            })

        # 2. 构建prompt
        prompt = self._build_crew_prompt(crew, agent_inputs, context)

        # 3. 调用LLM推理
        llm_response = await self._call_llm(prompt)

        # 4. 解析结构化输出
        result = self._parse_output(llm_response, crew["output_format"])

        # 5. 记录决策（可审计）
        await self._record_decision(factory_id, crew_key, context, result)

        return {
            "crew": crew["name"],
            "crew_key": crew_key,
            "factory_id": factory_id,
            "context": context,
            "agent_inputs": [{
                "role": a["role"],
                "data_summary": self._summarize_data(a["data"]),
            } for a in agent_inputs],
            "decision": result,
            "timestamp": datetime.utcnow().isoformat(),
        }

    # ═══════════════════════════════════════════════════════════
    # 数据获取（各Agent角色从系统获取数据）
    # ═══════════════════════════════════════════════════════════

    async def _gather_agent_data(
        self, source: str, factory_id: str, context: Dict
    ) -> Dict[str, Any]:
        """根据数据源类型获取相关数据"""
        try:
            if source == "scheduling":
                return await self._get_scheduling_data(factory_id)
            elif source == "warehouse":
                return await self._get_warehouse_data(factory_id)
            elif source == "delivery":
                return await self._get_delivery_data(factory_id)
            elif source == "equipment":
                return await self._get_equipment_data(factory_id)
            elif source == "quality":
                return await self._get_quality_data(factory_id)
            elif source == "personnel":
                return await self._get_personnel_data(factory_id, context)
            elif source == "material":
                return await self._get_material_data(factory_id, context)
            elif source == "process":
                return await self._get_process_data(factory_id, context)
            elif source == "cost":
                return await self._get_cost_data(factory_id, context)
            else:
                return {"note": f"数据源 {source} 暂未接入"}
        except Exception as e:
            _logger.warning(f"[crew] 获取{source}数据失败: {e}")
            return {"error": str(e)}

    async def _get_scheduling_data(self, factory_id: str) -> Dict:
        result = await self.db.execute(text("""
            SELECT COUNT(*) as pending_orders,
                   SUM(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END) as in_progress,
                   AVG(CASE WHEN planned_due IS NOT NULL
                       THEN EXTRACT(EPOCH FROM (planned_due - NOW()))/86400 END) as avg_days_to_due
            FROM work_orders WHERE factory_id = :fid AND status IN ('released','pending','in_progress')
        """), {"fid": factory_id})
        row = dict(result.first()._mapping)

        # 产能利用率
        cap = await self.db.execute(text("""
            SELECT station_id,
                   SUM(EXTRACT(EPOCH FROM (planned_end - planned_start))/3600) as busy_hours
            FROM aps_schedule_tasks t
            JOIN aps_schedules s ON t.schedule_id = s.id
            WHERE s.factory_id = :fid AND s.status IN ('draft','confirmed') AND t.planned_start > NOW()
            GROUP BY station_id
        """), {"fid": factory_id})
        stations = [dict(r) for r in cap.mappings().all()]

        return {
            "pending_orders": row["pending_orders"],
            "in_progress": row["in_progress"],
            "avg_days_to_due": round(row["avg_days_to_due"] or 0, 1),
            "station_loads": [{
                "station": s["station_id"],
                "busy_hours": round(s["busy_hours"], 1),
            } for s in stations[:10]],
        }

    async def _get_warehouse_data(self, factory_id: str) -> Dict:
        result = await self.db.execute(text("""
            SELECT COUNT(DISTINCT material_code) as sku_count,
                   SUM(CASE WHEN available_qty <= COALESCE(reorder_point, 20) THEN 1 ELSE 0 END) as low_stock
            FROM inventory WHERE factory_id = :fid AND available_qty >= 0
        """), {"fid": factory_id})
        row = dict(result.first()._mapping)
        return {
            "sku_count": row["sku_count"],
            "low_stock_items": row["low_stock"],
            "note": "低于安全线的物料数量",
        }

    async def _get_delivery_data(self, factory_id: str) -> Dict:
        result = await self.db.execute(text("""
            SELECT COUNT(*) as total_orders,
                   SUM(CASE WHEN planned_due < NOW() AND status != 'completed' THEN 1 ELSE 0 END) as overdue,
                   SUM(CASE WHEN planned_due < NOW() + INTERVAL '3 days' AND planned_due > NOW() THEN 1 ELSE 0 END) as due_soon
            FROM work_orders WHERE factory_id = :fid AND status IN ('released','pending','in_progress')
        """), {"fid": factory_id})
        row = dict(result.first()._mapping)
        return {
            "total_active_orders": row["total_orders"],
            "overdue": row["overdue"],
            "due_within_3_days": row["due_soon"],
        }

    async def _get_equipment_data(self, factory_id: str) -> Dict:
        result = await self.db.execute(text("""
            SELECT status, COUNT(*) as cnt FROM equipment WHERE factory_id = :fid GROUP BY status
        """), {"fid": factory_id})
        statuses = {r[0]: r[1] for r in result.fetchall()}
        return {"equipment_status": statuses}

    async def _get_quality_data(self, factory_id: str) -> Dict:
        result = await self.db.execute(text("""
            SELECT COUNT(*) as total_inspections,
                   SUM(CASE WHEN result = 'fail' THEN 1 ELSE 0 END) as fail_count
            FROM inspection_records WHERE factory_id = :fid
              AND created_at > NOW() - INTERVAL '30 days'
        """), {"fid": factory_id})
        row = result.first()
        if row:
            total = row[0] or 1
            fail = row[1] or 0
            return {"recent_fail_rate": round(fail / total * 100, 1), "total_30d": total}
        return {"note": "无近期检验记录"}

    async def _get_personnel_data(self, factory_id: str, context: Dict) -> Dict:
        result = await self.db.execute(text("""
            SELECT COUNT(*) as total_workers FROM employees WHERE factory_id = :fid AND status = 'active'
        """), {"fid": factory_id})
        row = result.first()
        return {"active_workers": row[0] if row else 0}

    async def _get_material_data(self, factory_id: str, context: Dict) -> Dict:
        material = context.get("material_code", "")
        if material:
            result = await self.db.execute(text("""
                SELECT available_qty, safety_stock FROM inventory
                WHERE factory_id = :fid AND material_code = :mc
            """), {"fid": factory_id, "mc": material})
            row = result.first()
            if row:
                return {"material": material, "available": row[0], "safety": row[1]}
        return {"note": "未指定物料或无库存记录"}

    async def _get_process_data(self, factory_id: str, context: Dict) -> Dict:
        return {"note": "工艺数据需接入具体产品工艺路线"}

    async def _get_cost_data(self, factory_id: str, context: Dict) -> Dict:
        return {"note": "成本数据需接入ERP"}

    # ═══════════════════════════════════════════════════════════
    # LLM 推理
    # ═══════════════════════════════════════════════════════════

    def _build_crew_prompt(self, crew: Dict, agent_inputs: List[Dict], context: Dict) -> str:
        """构建多Agent协商prompt"""
        parts = [
            f"你是一个制造企业的决策协调系统。当前需要完成的任务是：{crew['goal']}",
            f"\n## 背景信息",
            f"```json\n{json.dumps(context, ensure_ascii=False, default=str)}\n```",
            f"\n## 各分析师的数据和观点",
        ]

        for agent in agent_inputs:
            parts.append(f"\n### {agent['role']}")
            parts.append(f"职责：{agent['goal']}")
            parts.append(f"数据：```json\n{json.dumps(agent['data'], ensure_ascii=False, default=str)}\n```")

        parts.append(f"\n## 要求")
        parts.append(f"请综合以上各分析师的数据，给出结构化决策建议。")
        parts.append(f"输出格式（严格JSON）：")
        parts.append(f"```json\n{json.dumps(crew['output_format'], ensure_ascii=False)}\n```")
        parts.append(f"\n只输出JSON，不要其他文字。")

        return "\n".join(parts)

    async def _call_llm(self, prompt: str) -> str:
        """通过公共模型底座按业务任务动态路由。"""
        try:
            from api.routes.chat_routes import (
                MODEL_STACK_CHAT_TASK_ID, _call_llm, _resolve_model_route,
            )
            route = await _resolve_model_route(
                MODEL_STACK_CHAT_TASK_ID, prompt_tokens=max(1, len(prompt) // 4),
                max_completion_tokens=2000,
            )
            resp = await _call_llm(
                {
                    "model": route["gateway_model"],
                    "messages": [
                        {"role": "system", "content": "你是制造企业的智能决策系统。基于数据给出客观、结构化的分析和建议。"},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.3,
                    "max_tokens": route["max_completion_tokens"],
                },
                request_timeout=route["request_timeout"],
            )
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            _logger.warning(f"[crew] LLM调用失败: {resp.status_code} {resp.text[:200]}")
            return json.dumps({"error": "LLM不可用", "fallback": "请人工决策"})
        except Exception as e:
            _logger.warning(f"[crew] LLM调用异常: {e}")
            return json.dumps({"error": str(e), "fallback": "请人工决策"})

    def _parse_output(self, llm_response: str, output_format: Dict) -> Dict:
        """解析LLM输出为结构化JSON"""
        try:
            # 尝试直接解析
            text = llm_response.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw_response": llm_response, "parse_error": True}

    def _summarize_data(self, data: Dict) -> str:
        """数据摘要（用于返回给前端展示）"""
        if not data:
            return "无数据"
        items = [f"{k}:{v}" for k, v in list(data.items())[:5]]
        return " | ".join(items)

    # ═══════════════════════════════════════════════════════════
    # 决策记录（可审计）
    # ═══════════════════════════════════════════════════════════

    async def _record_decision(
        self, factory_id: str, crew_key: str, context: Dict, result: Dict
    ):
        """记录每次Crew决策（审计追踪）"""
        try:
            await self.db.execute(text("""
                INSERT INTO crew_decisions (id, factory_id, crew_key, crew_name, context, decision, created_at)
                VALUES (gen_random_uuid(), :fid, :ck, :cn, :ctx, :dec, NOW())
            """), {
                "fid": factory_id,
                "ck": crew_key,
                "cn": CREWS[crew_key]["name"],
                "ctx": json.dumps(context, ensure_ascii=False, default=str),
                "dec": json.dumps(result, ensure_ascii=False, default=str),
            })
            await self.db.commit()
        except Exception as e:
            _logger.warning(f"[crew] 记录决策失败: {e}")

    async def get_decision_history(self, factory_id: str, limit: int = 20) -> Dict[str, Any]:
        """获取决策历史"""
        result = await self.db.execute(text("""
            SELECT crew_key, crew_name, context, decision, created_at
            FROM crew_decisions WHERE factory_id = :fid
            ORDER BY created_at DESC LIMIT :lim
        """), {"fid": factory_id, "lim": limit})
        rows = [dict(r) for r in result.mappings().all()]
        return {"total": len(rows), "decisions": rows}
