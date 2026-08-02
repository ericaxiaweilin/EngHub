"""
个人知识层（Personal Knowledge）
================================
核心理念：完全无人不可行。每个人有独特的经验沉淀，系统要能：
1. 记录每个人的决策历史（做了什么决定、为什么）
2. 沉淀个人知识（技巧、教训、专长）
3. 在组织层需要时，知道该问谁（专家路由）
4. 个人助手：代替本人回答其专长范围内的问题

两层关系：
- 组织层（CrewAI）：公司级决策，多Agent协商
- 个人层（本服务）：个人经验，被组织层咨询
- 当CrewAI推理结果信心度低时 → 路由到个人层找专家

交流协议：
- Agent→Agent：事件驱动，自动（组织层内部）
- Agent→人：通知/升级/咨询（组织层→个人层）
- 人→Agent：指令/覆盖/教学（个人层→组织层）
- 人→人：协作/指导（个人层内部，系统辅助匹配）
"""
import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

_logger = logging.getLogger("personal_knowledge")


class PersonalKnowledgeService:
    """个人知识层 - 经验沉淀+专家路由+个人助手"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ═══════════════════════════════════════════════════════════
    # 知识沉淀
    # ═══════════════════════════════════════════════════════════

    async def add_knowledge(
        self,
        factory_id: str,
        employee_id: str,
        category: str,
        title: str,
        content: str,
        tags: List[str] = None,
        source: str = "manual",  # manual/auto_extract/decision_log
    ) -> Dict[str, Any]:
        """
        沉淀一条个人知识
        category: tip(技巧)/lesson(教训)/expertise(专长)/decision(决策依据)/trick(窍门)
        """
        result = await self.db.execute(text("""
            INSERT INTO personal_knowledge (id, factory_id, employee_id, category, title, content, tags, source, created_at)
            VALUES (gen_random_uuid(), :fid, :eid, :cat, :title, :content, :tags, :src, NOW())
            RETURNING id
        """), {
            "fid": factory_id, "eid": employee_id, "cat": category,
            "title": title, "content": content,
            "tags": json.dumps(tags or [], ensure_ascii=False),
            "src": source,
        })
        kid = result.scalar()
        await self.db.commit()

        # 更新员工专长标签
        if tags:
            await self._update_expertise_tags(factory_id, employee_id, tags)

        return {"success": True, "knowledge_id": str(kid), "category": category}

    async def get_person_knowledge(
        self, factory_id: str, employee_id: str, category: str = None
    ) -> Dict[str, Any]:
        """获取某人的所有知识"""
        sql = "SELECT * FROM personal_knowledge WHERE factory_id = :fid AND employee_id = :eid"
        params = {"fid": factory_id, "eid": employee_id}
        if category:
            sql += " AND category = :cat"
            params["cat"] = category
        sql += " ORDER BY created_at DESC LIMIT 50"

        result = await self.db.execute(text(sql), params)
        rows = [dict(r) for r in result.mappings().all()]
        return {
            "employee_id": employee_id,
            "total": len(rows),
            "knowledge": [{
                "id": r["id"],
                "category": r["category"],
                "title": r["title"],
                "content": r["content"],
                "tags": json.loads(r["tags"]) if r.get("tags") else [],
                "source": r.get("source", "manual"),
                "created_at": str(r["created_at"]),
            } for r in rows],
        }

    # ═══════════════════════════════════════════════════════════
    # 决策历史
    # ═══════════════════════════════════════════════════════════

    async def record_decision(
        self,
        factory_id: str,
        employee_id: str,
        decision_type: str,
        situation: str,
        decision: str,
        reasoning: str = "",
        outcome: str = None,  # 后续补充结果
    ) -> Dict[str, Any]:
        """记录一个人的决策（经验积累）"""
        result = await self.db.execute(text("""
            INSERT INTO personal_decisions (id, factory_id, employee_id, decision_type,
                situation, decision, reasoning, outcome, created_at)
            VALUES (gen_random_uuid(), :fid, :eid, :dtype, :sit, :dec, :reason, :out, NOW())
            RETURNING id
        """), {
            "fid": factory_id, "eid": employee_id, "dtype": decision_type,
            "sit": situation, "dec": decision, "reason": reasoning, "out": outcome,
        })
        did = result.scalar()
        await self.db.commit()
        return {"success": True, "decision_id": str(did)}

    async def get_decision_history(
        self, factory_id: str, employee_id: str = None, decision_type: str = None
    ) -> Dict[str, Any]:
        """获取决策历史"""
        sql = "SELECT * FROM personal_decisions WHERE factory_id = :fid"
        params = {"fid": factory_id}
        if employee_id:
            sql += " AND employee_id = :eid"
            params["eid"] = employee_id
        if decision_type:
            sql += " AND decision_type = :dtype"
            params["dtype"] = decision_type
        sql += " ORDER BY created_at DESC LIMIT 50"

        result = await self.db.execute(text(sql), params)
        rows = [dict(r) for r in result.mappings().all()]
        return {"total": len(rows), "decisions": rows}

    # ═══════════════════════════════════════════════════════════
    # 专家路由（组织层咨询个人层）
    # ═══════════════════════════════════════════════════════════

    async def find_expert(
        self, factory_id: str, topic: str, tags: List[str] = None
    ) -> Dict[str, Any]:
        """
        找专家：给定一个主题，找到最相关的人
        用于：CrewAI信心度低时 → 找真人专家
        """
        # 1. 从知识库匹配
        search_term = f"%{topic}%"
        result = await self.db.execute(text("""
            SELECT pk.employee_id, e.name as employee_name, e.position,
                   COUNT(*) as knowledge_count,
                   MAX(pk.created_at) as last_contribution
            FROM personal_knowledge pk
            JOIN hr_employees e ON pk.employee_id = e.id
            WHERE pk.factory_id = :fid
              AND (pk.title ILIKE :term OR pk.content ILIKE :term OR pk.tags::text ILIKE :term)
            GROUP BY pk.employee_id, e.name, e.position
            ORDER BY knowledge_count DESC
            LIMIT 5
        """), {"fid": factory_id, "term": search_term})
        experts = [dict(r) for r in result.mappings().all()]

        # 2. 从决策历史匹配
        result2 = await self.db.execute(text("""
            SELECT pd.employee_id, e.name as employee_name, e.position,
                   COUNT(*) as decision_count
            FROM personal_decisions pd
            JOIN hr_employees e ON pd.employee_id = e.id
            WHERE pd.factory_id = :fid
              AND (pd.situation ILIKE :term OR pd.decision_type ILIKE :term)
            GROUP BY pd.employee_id, e.name, e.position
            ORDER BY decision_count DESC
            LIMIT 5
        """), {"fid": factory_id, "term": search_term})
        decision_experts = [dict(r) for r in result2.mappings().all()]

        # 3. 合并排序
        expert_map = {}
        for e in experts:
            eid = e["employee_id"]
            expert_map[eid] = {
                "employee_id": eid,
                "name": e["employee_name"],
                "position": e.get("position", ""),
                "knowledge_count": e["knowledge_count"],
                "decision_count": 0,
                "relevance_score": e["knowledge_count"] * 2,
            }
        for e in decision_experts:
            eid = e["employee_id"]
            if eid in expert_map:
                expert_map[eid]["decision_count"] = e["decision_count"]
                expert_map[eid]["relevance_score"] += e["decision_count"]
            else:
                expert_map[eid] = {
                    "employee_id": eid,
                    "name": e["employee_name"],
                    "position": e.get("position", ""),
                    "knowledge_count": 0,
                    "decision_count": e["decision_count"],
                    "relevance_score": e["decision_count"],
                }

        sorted_experts = sorted(expert_map.values(), key=lambda x: x["relevance_score"], reverse=True)

        return {
            "topic": topic,
            "experts_found": len(sorted_experts),
            "experts": sorted_experts[:5],
            "recommendation": f"建议咨询 {sorted_experts[0]['name']}（{sorted_experts[0]['position']}）" if sorted_experts else "未找到相关专家",
        }

    # ═══════════════════════════════════════════════════════════
    # 个人助手（代替本人回答）
    # ═══════════════════════════════════════════════════════════

    async def personal_assistant_query(
        self, factory_id: str, employee_id: str, question: str
    ) -> Dict[str, Any]:
        """
        个人助手：基于某人的知识沉淀回答问题
        场景：张三不在，但有人问"张三之前那个模具问题怎么处理的？"
        """
        # 获取该人的相关知识
        knowledge = await self.get_person_knowledge(factory_id, employee_id)
        decisions = await self.get_decision_history(factory_id, employee_id)

        # 获取员工信息
        emp_result = await self.db.execute(text(
            "SELECT name, position FROM hr_employees WHERE id = :eid AND factory_id = :fid"
        ), {"eid": employee_id, "fid": factory_id})
        emp = emp_result.first()
        emp_name = emp[0] if emp else "未知"
        emp_pos = emp[1] if emp else ""

        # 构建上下文
        context_items = []
        for k in knowledge.get("knowledge", [])[:10]:
            context_items.append(f"[{k['category']}] {k['title']}: {k['content']}")
        for d in decisions.get("decisions", [])[:10]:
            context_items.append(f"[决策] {d['decision_type']}: {d['situation']} → {d['decision']}")

        if not context_items:
            return {
                "employee": emp_name,
                "position": emp_pos,
                "answer": f"{emp_name}暂无沉淀的知识记录，建议直接联系本人。",
                "confidence": 0,
            }

        # 调用LLM基于个人知识回答
        import os, httpx
        prompt = f"""你是{emp_name}（{emp_pos}）的个人知识助手。基于以下{emp_name}的知识和决策记录回答问题。
如果知识中没有相关内容，诚实说"这个问题超出{emp_name}已记录的知识范围"。

## {emp_name}的知识库：
{chr(10).join(context_items)}

## 问题：
{question}

请用{emp_name}的视角和经验回答，简洁实用。"""

        try:
            from api.routes.chat_routes import (
                MODEL_STACK_CHAT_TASK_ID, _call_llm, _resolve_model_route,
            )
            route = await _resolve_model_route(
                MODEL_STACK_CHAT_TASK_ID, prompt_tokens=max(1, len(prompt) // 4),
                max_completion_tokens=500,
            )
            resp = await _call_llm(
                {
                    "model": route["gateway_model"],
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.5,
                    "max_tokens": route["max_completion_tokens"],
                },
                request_timeout=route["request_timeout"],
            )
            if resp.status_code == 200:
                answer = resp.json()["choices"][0]["message"]["content"]
                return {
                    "employee": emp_name,
                    "position": emp_pos,
                    "answer": answer,
                    "confidence": min(80, len(context_items) * 10),
                    "knowledge_used": len(context_items),
                }
        except Exception as e:
            _logger.warning(f"[personal] LLM调用失败: {e}")

        # fallback: 直接返回最相关的知识
        return {
            "employee": emp_name,
            "position": emp_pos,
            "answer": f"LLM不可用。{emp_name}的相关知识：{context_items[0] if context_items else '无'}",
            "confidence": 30,
            "fallback": True,
        }

    # ═══════════════════════════════════════════════════════════
    # 交流协议
    # ═══════════════════════════════════════════════════════════

    async def route_communication(
        self, factory_id: str, from_type: str, to_type: str, message: Dict
    ) -> Dict[str, Any]:
        """
        交流路由器：决定消息如何传递
        from_type/to_type: agent/person/organization
        """
        route_key = f"{from_type}_to_{to_type}"

        routes = {
            "agent_to_agent": {
                "protocol": "event_bus",
                "description": "Agent间通过事件总线自动传递，无需人介入",
                "example": "质量Agent发现异常→通知设备Agent检查",
            },
            "agent_to_person": {
                "protocol": "notification+escalation",
                "description": "Agent通知人（信息）或升级（需决策）",
                "levels": {
                    "info": "仅通知，不需回复",
                    "confirm": "需确认（如：排程已更新，是否同意？）",
                    "decision": "需人做决定（如：这批料让步接收还是退？）",
                    "consult": "咨询专家意见（信心度不足时）",
                },
            },
            "person_to_agent": {
                "protocol": "command+override+teach",
                "description": "人对Agent的三种交互",
                "levels": {
                    "command": "下达指令（如：把这个工单优先级调到最高）",
                    "override": "覆盖Agent决定（如：Agent说暂停，人说继续做）",
                    "teach": "教学（如：以后这种情况不用暂停，直接降速就行）→沉淀为知识",
                },
            },
            "person_to_person": {
                "protocol": "collaboration+mentoring",
                "description": "系统辅助人与人协作",
                "features": {
                    "expert_match": "自动匹配最合适的咨询对象",
                    "knowledge_share": "将个人知识共享为组织知识",
                    "mentoring": "新人→老师傅配对",
                },
            },
        }

        route = routes.get(route_key)
        if not route:
            return {"error": f"未知路由: {route_key}", "available": list(routes.keys())}

        return {
            "route": route_key,
            "message": message,
            **route,
        }

    # ═══════════════════════════════════════════════════════════
    # 内部方法
    # ═══════════════════════════════════════════════════════════

    async def _update_expertise_tags(self, factory_id: str, employee_id: str, tags: List[str]):
        """更新员工专长标签"""
        try:
            # 获取现有标签
            result = await self.db.execute(text(
                "SELECT expertise_tags FROM hr_employees WHERE id = :eid AND factory_id = :fid"
            ), {"eid": employee_id, "fid": factory_id})
            row = result.first()
            existing = []
            if row and row[0]:
                try:
                    existing = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                except (json.JSONDecodeError, TypeError):
                    existing = []

            # 合并
            merged = list(set(existing + tags))
            await self.db.execute(text(
                "UPDATE hr_employees SET expertise_tags = :tags WHERE id = :eid AND factory_id = :fid"
            ), {"tags": json.dumps(merged, ensure_ascii=False), "eid": employee_id, "fid": factory_id})
            await self.db.commit()
        except Exception as e:
            _logger.warning(f"[personal] 更新专长标签失败: {e}")
