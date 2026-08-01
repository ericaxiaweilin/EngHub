"""
Chatbot 快速命令 + 智能体调度服务
==================================
1. 快速命令 CRUD：预设语句 + 用户自定义，存 chat_quick_commands 表
2. 智能体自动归类：用户新增快速命令后，立即归类到对应智能体
   - 优先关键词规则（快、确定性）
   - 无法命中时走 LLM 分类（网关可用时）
3. Agent 调度提示词：chatbot 会话指定 agent_key 时，注入该智能体的职责/工具偏好
"""
import logging
import re
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.agent_supervisor_service import AGENTS

_logger = logging.getLogger("quick_command")


def _gen_id():
    return str(uuid.uuid4())


# ═══════════════════════════════════════════════════════════
# 智能体归类：关键词规则（命中即归类，顺序即优先级）
# ═══════════════════════════════════════════════════════════

AGENT_KEYWORD_RULES: List[tuple] = [
    ("scheduling_agent", r"排产|排程|插单|重排|产能|what-?if|模拟排"),
    ("dispatch_agent", r"派工|派单|工位|开工|在制工单|派发"),
    ("procurement_agent", r"采购|供应商|下单|比价|PO|MRP|跟催|请购"),
    ("quality_agent", r"质量|品质|不良|IQC|IPQC|FQC|OQC|检验|SPC|缺陷|良率"),
    ("delivery_agent", r"交期|订单|超期|延期|倒计时|准交|逾期"),
    ("escalation_agent", r"异常|升级|安灯|andon|预警|报警|告警"),
    ("equipment_agent", r"设备|PM|保养|维修|维保|故障|停机|OEE"),
    ("warehouse_agent", r"库存|补货|仓库|仓储|呆滞|齐套|库位|物料|出入库|盘点"),
]

# 各智能体在 chatbot 会话中的工具偏好（用于调度提示词）
AGENT_TOOL_HINTS: Dict[str, str] = {
    "dispatch_agent": "query_work_orders / get_work_order_detail / release_work_order / query_skill_matrix",
    "procurement_agent": "query_inventory / query_shortage_alerts / run_workflow",
    "quality_agent": "query_defects / query_spc_anomalies / query_ocap_tasks / get_inspection_form",
    "delivery_agent": "query_work_orders / get_production_summary / query_alert_reviews",
    "escalation_agent": "get_pending_alerts / acknowledge_alert / run_alert_patrol",
    "equipment_agent": "query_equipment / query_downtime / query_maintenance_due",
    "scheduling_agent": "query_work_orders / query_routing / run_workflow / split_work_order",
    "warehouse_agent": "query_inventory / query_stagnant / query_shortage_alerts",
}


def classify_by_keywords(command_text: str) -> Optional[str]:
    """关键词规则归类：返回 agent_key，未命中返回 None。"""
    for agent_key, pattern in AGENT_KEYWORD_RULES:
        if re.search(pattern, command_text, re.IGNORECASE):
            return agent_key
    return None


async def classify_by_llm(command_text: str) -> Optional[str]:
    """LLM 归类兜底：让模型把命令归到某个智能体（网关不可用时静默返回 None）。"""
    try:
        # 懒加载，避免与 chat_routes 循环导入
        from api.routes.chat_routes import (
            MODEL_STACK_CHAT_TASK_ID, _call_llm, _resolve_model_route,
        )
        route = await _resolve_model_route(MODEL_STACK_CHAT_TASK_ID, prompt_tokens=200, max_completion_tokens=20)
        agent_menu = "\n".join(
            f"- {k}: {v['name']}（{v['description']}）" for k, v in AGENTS.items()
        )
        payload = {
            "model": route["gateway_model"],
            "messages": [
                {"role": "system", "content": (
                    "你是意图分类器。把用户命令归类到最匹配的智能体，只输出智能体 key，"
                    "无法归类时输出 none。可选智能体：\n" + agent_menu
                )},
                {"role": "user", "content": command_text},
            ],
            "temperature": 0,
            "max_tokens": 20,
        }
        resp = await _call_llm(payload, request_timeout=route["request_timeout"])
        if resp.status_code >= 400:
            return None
        content = (
            resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        ).strip().lower()
        for key in AGENTS:
            if key in content:
                return key
        return None
    except Exception as exc:  # noqa: BLE001
        _logger.info(f"[quick_command] LLM 归类不可用，跳过: {type(exc).__name__}")
        return None


async def classify_command(command_text: str) -> Dict[str, Any]:
    """归类命令 → 智能体。返回 {agent_key, agent_name, classify_source}。"""
    agent_key = classify_by_keywords(command_text)
    source = "keyword"
    if not agent_key:
        agent_key = await classify_by_llm(command_text)
        source = "llm"
    if not agent_key:
        return {"agent_key": None, "agent_name": None, "classify_source": "auto"}
    return {
        "agent_key": agent_key,
        "agent_name": AGENTS[agent_key]["name"],
        "classify_source": source,
    }


# ═══════════════════════════════════════════════════════════
# Agent 调度提示词（chatbot 会话指定 agent 时注入 system prompt）
# ═══════════════════════════════════════════════════════════

def build_agent_system_prompt(agent_key: str) -> Optional[str]:
    """构造指定智能体的调度提示词；agent_key 无效时返回 None。"""
    agent = AGENTS.get(agent_key)
    if not agent:
        return None
    hints = AGENT_TOOL_HINTS.get(agent_key, "")
    return (
        f"【智能体调度】用户已指定由「{agent['name']}」处理本次会话。"
        f"该智能体职责：{agent['description']}（触发场景：{agent['trigger']}）。"
        f"请以该智能体的身份和专业视角回答，优先执行其职责范围内的查询与操作"
        + (f"（优先工具：{hints}）" if hints else "")
        + f"。执行完成后遵循其闭环验证要求：{agent['verify']}。"
        "若用户请求明显超出该智能体职责，可正常处理但需说明已超出当前智能体范围。"
    )


async def record_agent_dispatch(
    db: AsyncSession, factory_id: str, agent_key: str, user_text: str,
) -> None:
    """chatbot 调度智能体时记录心跳，让「智能体监督」页面可见（失败不影响会话）。"""
    if agent_key not in AGENTS:
        return
    try:
        from api.services.agent_supervisor_service import AgentSupervisor
        await AgentSupervisor(db).record_heartbeat(
            factory_id=factory_id,
            agent_key=agent_key,
            action_taken=f"chatbot调度: {user_text[:120]}",
            trigger_type="chatbot",
            result_summary="由AI助手会话触发",
        )
    except Exception as exc:  # noqa: BLE001
        _logger.warning(f"[quick_command] 心跳记录失败: {exc}")


# ═══════════════════════════════════════════════════════════
# 快速命令 CRUD
# ═══════════════════════════════════════════════════════════

async def _ensure_table(db: AsyncSession) -> None:
    """兜底建表（未跑 058 迁移时保证功能可用）。"""
    await db.execute(text("""
        CREATE TABLE IF NOT EXISTS chat_quick_commands (
            id VARCHAR(36) PRIMARY KEY,
            factory_id VARCHAR(64),
            created_by VARCHAR(64),
            command_text VARCHAR(500) NOT NULL,
            agent_key VARCHAR(64),
            agent_name VARCHAR(64),
            classify_source VARCHAR(16) DEFAULT 'auto',
            is_preset BOOLEAN DEFAULT FALSE,
            sort_order INTEGER DEFAULT 100,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    """))


def _row_to_dict(row) -> Dict[str, Any]:
    d = dict(row._mapping)
    if d.get("created_at"):
        d["created_at"] = str(d["created_at"])
    d.pop("updated_at", None)
    return d


async def list_quick_commands(db: AsyncSession, factory_id: str) -> List[Dict[str, Any]]:
    """列出快速命令：全局预置 + 当前工厂自定义。"""
    await _ensure_table(db)
    result = await db.execute(text("""
        SELECT id, factory_id, created_by, command_text, agent_key, agent_name,
               classify_source, is_preset, sort_order, created_at
        FROM chat_quick_commands
        WHERE factory_id IS NULL OR factory_id = :fid
        ORDER BY sort_order, created_at
    """), {"fid": factory_id})
    return [_row_to_dict(r) for r in result.fetchall()]


async def create_quick_command(
    db: AsyncSession,
    factory_id: str,
    created_by: str,
    command_text: str,
    agent_key: Optional[str] = None,
) -> Dict[str, Any]:
    """新增快速命令：未手动指定 agent 时立即自动归类到对应智能体。"""
    await _ensure_table(db)
    command_text = command_text.strip()
    if not command_text:
        return {"error": "命令内容不能为空"}

    # 同工厂去重
    dup = await db.execute(text("""
        SELECT id FROM chat_quick_commands
        WHERE command_text = :ct AND (factory_id IS NULL OR factory_id = :fid)
    """), {"ct": command_text, "fid": factory_id})
    if dup.first():
        return {"error": "该命令已存在"}

    if agent_key and agent_key in AGENTS:
        classified = {
            "agent_key": agent_key,
            "agent_name": AGENTS[agent_key]["name"],
            "classify_source": "manual",
        }
    else:
        classified = await classify_command(command_text)

    cmd_id = _gen_id()
    await db.execute(text("""
        INSERT INTO chat_quick_commands
            (id, factory_id, created_by, command_text, agent_key, agent_name, classify_source, is_preset, sort_order)
        VALUES (:id, :fid, :cb, :ct, :ak, :an, :cs, FALSE, 200)
    """), {
        "id": cmd_id, "fid": factory_id, "cb": created_by, "ct": command_text,
        "ak": classified["agent_key"], "an": classified["agent_name"],
        "cs": classified["classify_source"],
    })
    await db.commit()
    return {
        "id": cmd_id,
        "factory_id": factory_id,
        "created_by": created_by,
        "command_text": command_text,
        "agent_key": classified["agent_key"],
        "agent_name": classified["agent_name"],
        "classify_source": classified["classify_source"],
        "is_preset": False,
        "sort_order": 200,
    }


async def update_quick_command(
    db: AsyncSession,
    factory_id: str,
    command_id: str,
    command_text: Optional[str] = None,
    agent_key: Optional[str] = None,
) -> Dict[str, Any]:
    """更新快速命令：改文本且未指定 agent 时自动重新归类。"""
    await _ensure_table(db)
    existing = await db.execute(text("""
        SELECT id, command_text, is_preset, factory_id FROM chat_quick_commands
        WHERE id = :id AND (factory_id IS NULL OR factory_id = :fid)
    """), {"id": command_id, "fid": factory_id})
    row = existing.first()
    if not row:
        return {"error": "命令不存在"}
    if row[2]:  # is_preset
        return {"error": "系统预置命令不可修改"}

    new_text = (command_text or row[1]).strip()
    if agent_key is not None:
        if agent_key and agent_key not in AGENTS:
            return {"error": f"无效的智能体: {agent_key}"}
        classified = {
            "agent_key": agent_key or None,
            "agent_name": AGENTS[agent_key]["name"] if agent_key else None,
            "classify_source": "manual",
        }
    elif command_text and command_text.strip() != row[1]:
        classified = await classify_command(new_text)
    else:
        classified = None

    params: Dict[str, Any] = {"id": command_id, "ct": new_text}
    sets = ["command_text = :ct", "updated_at = NOW()"]
    if classified is not None:
        sets += ["agent_key = :ak", "agent_name = :an", "classify_source = :cs"]
        params.update({
            "ak": classified["agent_key"], "an": classified["agent_name"],
            "cs": classified["classify_source"],
        })
    await db.execute(text(f"UPDATE chat_quick_commands SET {', '.join(sets)} WHERE id = :id"), params)
    await db.commit()

    result = await db.execute(text("""
        SELECT id, factory_id, created_by, command_text, agent_key, agent_name,
               classify_source, is_preset, sort_order, created_at
        FROM chat_quick_commands WHERE id = :id
    """), {"id": command_id})
    return _row_to_dict(result.first())


async def delete_quick_command(db: AsyncSession, factory_id: str, command_id: str) -> Dict[str, Any]:
    """删除快速命令（系统预置不可删）。"""
    await _ensure_table(db)
    result = await db.execute(text("""
        DELETE FROM chat_quick_commands
        WHERE id = :id AND factory_id = :fid AND is_preset = FALSE
        RETURNING id
    """), {"id": command_id, "fid": factory_id})
    deleted = result.first()
    await db.commit()
    if not deleted:
        return {"error": "命令不存在或为系统预置，不可删除"}
    return {"success": True, "id": command_id}
