"""职位训练器接口。

训练器页面只负责呈现和提交；职位、题目、答案和成绩均由接口/数据库提供，
避免把某个职位的小测试绑定在业务驾驶舱或前端代码里。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.process_knowledge_service import POSITION_SOPS
from core.auth.security import get_current_user
from database.db_config import get_db
from database.models import User


router = APIRouter(prefix="/api/v1/trainer", tags=["职位训练器"])


_IDLE_QUESTION_LIMIT = 10  # 空闲答题模式随机抽取题数


POSITION_CODE_MAP = {
    "pmc": "pmc_planner",
    "pmc_planner": "pmc_planner",
    "operator": "operator",
    "ipqc": "ipqc",
    "equipment_engineer": "equipment_engineer",
    "production_supervisor": "production_supervisor",
    "warehouse_keeper": "warehouse_keeper",
}


class TrainingAttemptRequest(BaseModel):
    position_code: str = Field(..., description="职位训练编码，例如 pmc")
    factory_id: Optional[str] = None
    level: Optional[int] = Field(1, description="实操演练难度: 1基础/2缺料/3综合")
    answers: Dict[str, List[str]] = Field(default_factory=dict)


def _factory_id(user: User, requested: Optional[str]) -> Optional[str]:
    return requested or getattr(user, "active_factory_id", None) or getattr(user, "factory_id", None)


def _user_id(user: User) -> str:
    return str(getattr(user, "id", None) or getattr(user, "username", None) or "unknown")


def _position_key(position_code: str) -> Optional[str]:
    return POSITION_CODE_MAP.get((position_code or "").strip().lower())


def _position_summary(position_code: str) -> Dict[str, Any]:
    key = _position_key(position_code)
    sop = POSITION_SOPS.get(key) if key else None
    if not sop:
        raise HTTPException(status_code=404, detail=f"训练职位不存在: {position_code}")
    return {
        "code": position_code,
        "title": sop["title"],
        "aliases": sop.get("aliases", []),
        "duties": sop.get("duties", ""),
        "daily_flow": sop.get("daily_flow", []),
        "escalation": sop.get("escalation", ""),
        "related_tools": sop.get("related_tools", ""),
    }


@router.get("/positions", summary="获取可训练职位")
async def list_training_positions(
    current_user: User = Depends(get_current_user),
):
    """返回职位训练器的职位目录；页面不维护职位列表。"""
    del current_user
    return {
        "positions": [
            {
                "code": code,
                "title": POSITION_SOPS[key]["title"],
                "duties": POSITION_SOPS[key].get("duties", ""),
            }
            for code, key in POSITION_CODE_MAP.items()
            if code == "pmc" or (code == key and code != "pmc_planner")
        ]
    }


@router.get("/pack", summary="获取职位训练包")
async def get_training_pack(
    position_code: str = Query("pmc", description="职位训练编码"),
    factory_id: Optional[str] = Query(None),
    mode: str = Query("focus", description="答题模式: focus 专注(全量) / idle 空闲(随机抽题)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    mode = (mode or "focus").strip().lower()
    if mode not in {"focus", "idle"}:
        raise HTTPException(status_code=400, detail="mode 仅支持 focus(专注) / idle(空闲)")
    position = _position_summary(position_code)
    canonical_code = position["code"]

    if mode == "idle":
        rows = (
            await db.execute(
                text(
                    """
                    SELECT id, question_code, skill, difficulty, question_type,
                           prompt, options, reference_terms, points
                    FROM position_training_questions
                    WHERE position_code = :position_code AND is_active = true
                    ORDER BY random()
                    LIMIT :limit
                    """
                ),
                {"position_code": canonical_code, "limit": _IDLE_QUESTION_LIMIT},
            )
        ).mappings().all()
    else:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT id, question_code, skill, difficulty, question_type,
                           prompt, options, reference_terms, points
                    FROM position_training_questions
                    WHERE position_code = :position_code AND is_active = true
                    ORDER BY difficulty, question_code
                    """
                ),
                {"position_code": canonical_code},
            )
        ).mappings().all()

    mode_label = "专注答题" if mode == "focus" else "空闲答题"
    return {
        "position": position,
        "factory_id": _factory_id(current_user, factory_id),
        "mode": mode,
        "mode_label": mode_label,
        "mission": (
            "先按职位流程核对输入、判断标准和交付物，再进入岗位小测试。"
            if mode == "focus"
            else "空闲模式随机抽取题目，适合碎片时间快速练习。"
        ),
        "quiz": {
            "title": f"{position['title']}{'专注学习' if mode == 'focus' else '空闲快测'}",
            "pass_score": 80,
            "total": len(rows),
            "questions": [dict(row) for row in rows],
        },
    }


@router.post("/attempts", summary="提交职位训练测试")
async def submit_training_attempt(
    payload: TrainingAttemptRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    position = _position_summary(payload.position_code)
    canonical_code = position["code"]
    if not payload.answers:
        raise HTTPException(status_code=400, detail="至少回答一道题")

    rows = (
        await db.execute(
            text(
                """
                SELECT id, question_code, skill, question_type, prompt, answer, explanation, points
                FROM position_training_questions
                WHERE position_code = :position_code AND is_active = true
                  AND id = ANY(:ids)
                """
            ),
            {"position_code": canonical_code, "ids": list(payload.answers.keys())},
        )
    ).mappings().all()
    if not rows:
        raise HTTPException(status_code=400, detail="没有匹配的训练题目")

    total_points = 0
    earned_points = 0
    details: List[Dict[str, Any]] = []
    for row in rows:
        expected_raw = [str(value) for value in (row["answer"] or [])]
        actual_raw = [str(value) for value in (payload.answers.get(row["id"]) or [])]
        qtype = (row["question_type"] or "single").lower()
        points = int(row["points"] or 1)
        if qtype == "order":
            correct = actual_raw == expected_raw
        elif qtype == "fill":
            norm = lambda v: re.sub(r"\s+", "", v).lower().strip()
            correct = any(norm(a) == norm(e) for a in actual_raw for e in expected_raw)
        elif qtype == "calc":
            def _num(v):
                try:
                    return float(re.sub(r"[^0-9.+-]", "", v))
                except (ValueError, TypeError):
                    return None
            correct = bool(actual_raw) and any(
                _num(a) is not None and abs(_num(a) - _num(e)) < 1e-6
                for a in actual_raw for e in expected_raw
            )
        else:
            expected = sorted(expected_raw)
            actual = sorted(actual_raw)
            correct = expected == actual
        total_points += points
        earned_points += points if correct else 0
        details.append(
            {
                "id": row["id"],
                "question_code": row["question_code"],
                "skill": row["skill"],
                "correct": correct,
                "selected": actual_raw,
                "answer": expected_raw,
                "explanation": row["explanation"],
                "points": points,
            }
        )

    score = round(earned_points / total_points * 100, 1) if total_points else 0
    attempt_id = str(uuid4())
    await db.execute(
        text(
            """
            INSERT INTO position_training_attempts
                (id, position_code, user_id, factory_id, answers, score,
                 earned_points, total_points, details)
            VALUES (:id, :position_code, :user_id, :factory_id,
                    CAST(:answers AS JSONB), :score, :earned_points,
                    :total_points, CAST(:details AS JSONB))
            """
        ),
        {
            "id": attempt_id,
            "position_code": canonical_code,
            "user_id": _user_id(current_user),
            "factory_id": _factory_id(current_user, payload.factory_id),
            "answers": json.dumps(payload.answers, ensure_ascii=False),
            "score": score,
            "earned_points": earned_points,
            "total_points": total_points,
            "details": json.dumps(details, ensure_ascii=False),
        },
    )
    await db.commit()
    return {
        "attempt_id": attempt_id,
        "position_code": canonical_code,
        "score": score,
        "earned_points": earned_points,
        "total_points": total_points,
        "passed": score >= 80,
        "details": details,
    }


@router.get("/review", summary="错题本：按技能聚合历史错题")
async def get_review_book(
    position_code: str = Query("pmc", description="职位训练编码"),
    factory_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """从该用户的历史答题中聚合错题，按技能分组，附解析与重练建议。"""
    position = _position_summary(position_code)
    canonical_code = position["code"]
    uid = _user_id(current_user)
    fid = _factory_id(current_user, factory_id)

    # 取最近 200 次答题记录，展开 details，筛出错误项
    rows = (
        await db.execute(
            text(
                """
                SELECT details, created_at
                FROM position_training_attempts
                WHERE position_code = :position_code
                  AND user_id = :user_id
                  AND (factory_id = :factory_id OR :factory_id IS NULL)
                ORDER BY created_at DESC
                LIMIT 200
                """
            ),
            {"position_code": canonical_code, "user_id": uid, "factory_id": fid},
        )
    ).mappings().all()

    wrong_by_skill: Dict[str, List[Dict[str, Any]]] = {}
    wrong_ids: List[str] = []
    total_wrong = 0
    for row in rows:
        try:
            details = json.loads(row["details"]) if isinstance(row["details"], str) else (row["details"] or [])
        except (TypeError, ValueError):
            details = []
        for item in details:
            if item.get("correct"):
                continue
            qid = item.get("id") or item.get("question_code") or ""
            if not qid:
                continue
            total_wrong += 1
            if qid in wrong_ids:
                continue
            wrong_ids.append(qid)
            skill = item.get("skill") or "未分类"
            wrong_by_skill.setdefault(skill, []).append(
                {
                    "id": qid,
                    "question_code": item.get("question_code", qid),
                    "skill": skill,
                    "selected": item.get("selected") or [],
                    "answer": item.get("answer") or [],
                    "explanation": item.get("explanation") or "",
                    "points": item.get("points") or 1,
                }
            )

    # 补充题目信息（prompt/type/difficulty/reference_terms）——若题目仍有效
    if wrong_ids:
        q_rows = (
            await db.execute(
                text(
                    """
                    SELECT id, question_code, skill, difficulty, question_type,
                           prompt, options, reference_terms
                    FROM position_training_questions
                    WHERE id = ANY(:ids)
                    """
                ),
                {"ids": wrong_ids},
            )
        ).mappings().all()
        qinfo = {row["id"]: dict(row) for row in q_rows}
    else:
        qinfo = {}

    skills_out: List[Dict[str, Any]] = []
    for skill, items in wrong_by_skill.items():
        enriched = []
        for it in items:
            info = qinfo.get(it["id"], {})
            enriched.append({**it, **info})
        skills_out.append({"skill": skill, "count": len(items), "questions": enriched})

    skills_out.sort(key=lambda s: -s["count"])

    return {
        "position": position,
        "factory_id": fid,
        "total_attempts": len(rows),
        "distinct_wrong": len(wrong_ids),
        "total_wrong_instances": total_wrong,
        "skills": skills_out,
        "mission": "错题按技能聚合，优先复习错误率最高的技能；解析已给出标准答案。",
    }


@router.get("/mastery", summary="掌握度：按技能与难度计算熟练度雷达")
async def get_mastery(
    position_code: str = Query("pmc", description="职位训练编码"),
    factory_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """基于全部题库 + 历史答题，计算每个技能的作答次数/正确率/掌握度。"""
    position = _position_summary(position_code)
    canonical_code = position["code"]
    uid = _user_id(current_user)
    fid = _factory_id(current_user, factory_id)

    bank = (
        await db.execute(
            text(
                """
                SELECT id, skill, difficulty, points
                FROM position_training_questions
                WHERE position_code = :position_code AND is_active = true
                """
            ),
            {"position_code": canonical_code},
        )
    ).mappings().all()

    attempts = (
        await db.execute(
            text(
                """
                SELECT details
                FROM position_training_attempts
                WHERE position_code = :position_code
                  AND user_id = :user_id
                  AND (factory_id = :factory_id OR :factory_id IS NULL)
                ORDER BY created_at DESC
                LIMIT 500
                """
            ),
            {"position_code": canonical_code, "user_id": uid, "factory_id": fid},
        )
    ).mappings().all()

    # 每道题累计 答对/答错 次数
    question_stats: Dict[str, Dict[str, int]] = {}
    for row in attempts:
        try:
            details = json.loads(row["details"]) if isinstance(row["details"], str) else (row["details"] or [])
        except (TypeError, ValueError):
            details = []
        for item in details:
            qid = item.get("id") or item.get("question_code") or ""
            if not qid:
                continue
            st = question_stats.setdefault(qid, {"correct": 0, "wrong": 0})
            if item.get("correct"):
                st["correct"] += 1
            else:
                st["wrong"] += 1

    bank_by_skill: Dict[str, Dict[str, Any]] = {}
    skill_qids: Dict[str, set] = {}
    for row in bank:
        skill = row["skill"]
        b = bank_by_skill.setdefault(skill, {"total": 0, "points": 0, "difficulty_sum": 0})
        b["total"] += 1
        b["points"] += int(row["points"] or 1)
        b["difficulty_sum"] += int(row["difficulty"] or 1)
        skill_qids.setdefault(skill, set()).add(row["id"])

    skills_out: List[Dict[str, Any]] = []
    for skill, b in bank_by_skill.items():
        skill_attempts = 0
        skill_correct = 0
        qids = skill_qids.get(skill, set())
        for qid, st in question_stats.items():
            if qid in qids:
                skill_attempts += st["correct"] + st["wrong"]
                skill_correct += st["correct"]
        accuracy = round(skill_correct / skill_attempts * 100, 1) if skill_attempts else None
        mastery = round(skill_correct / (b["total"] * 2) * 100, 1)  # 全对一次=50%，两次全对=100%
        mastery = min(mastery, 100)
        skills_out.append(
            {
                "skill": skill,
                "bank_size": b["total"],
                "attempts": skill_attempts,
                "accuracy": accuracy,
                "mastery": mastery,
                "avg_difficulty": round(b["difficulty_sum"] / b["total"], 1),
                "status": (
                    "suggest_review"
                    if (accuracy is None or accuracy < 60)
                    else "practice"
                    if accuracy < 80
                    else "solid"
                ),
            }
        )

    skills_out.sort(key=lambda s: (s["mastery"], -s["bank_size"]))

    return {
        "position": position,
        "factory_id": fid,
        "skills": skills_out,
        "legend": {
            "suggest_review": "建议复盘（正确率<60% 或未练习）",
            "practice": "需要练习（正确率 60%-80%）",
            "solid": "掌握扎实（正确率≥80%）",
        },
    }


@router.get("/drills", summary="实操演练：真实业务数据场景题（难度梯度）")
async def get_drills(
    position_code: str = Query("pmc", description="职位训练编码"),
    factory_id: Optional[str] = Query(None),
    level: int = Query(1, description="难度梯度: 1基础/2缺料/3综合"),
    limit: int = Query(3, ge=1, le=10),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """从真实数据(销售订单/工单缺料/库存)生成场景判断题，答案来自系统真实状态。"""
    position = _position_summary(position_code)
    canonical_code = position["code"]
    fid = _factory_id(current_user, factory_id)

    level = int(level)
    if level not in {1, 2, 3}:
        raise HTTPException(status_code=400, detail="level 仅支持 1/2/3")

    drills: List[Dict[str, Any]] = []

    if level == 1:
        # L1: 真实销售订单 -> 判断该订单的核心风险/评审关注点
        rows = (
            await db.execute(
                text(
                    """
                    SELECT order_code, product_name, quantity, delivery_date,
                           priority, status, material_ready, review_status, risk_level
                    FROM sales_orders
                    WHERE factory_id = :factory_id OR :factory_id IS NULL
                    ORDER BY delivery_date NULLS LAST
                    LIMIT :limit
                    """
                ),
                {"factory_id": fid, "limit": limit},
            )
        ).mappings().all()
        for row in rows:
            order = dict(row)
            rdd = order.get("delivery_date")
            review = order.get("review_status")
            risk = order.get("risk_level")
            approved = review == "approved"
            conditional = review == "conditional"
            # 标准答案基于真实评审状态
            if conditional:
                answer = "conditional"
                correct_label = "条件承诺（存在风险，需跟踪缺口与责任人后再承诺）"
            elif approved:
                answer = "approved"
                correct_label = "评审通过，可正常纳入排程"
            elif risk in ("high", "critical"):
                answer = "block"
                correct_label = "阻塞（高风险订单，不得直接承诺交期）"
            else:
                answer = "pending"
                correct_label = "待评审（先核对BOM/版本/物料与产能证据）"
            drills.append(
                {
                    "id": order['order_code'],
                    "level": 1,
                    "type": "order_review",
                    "scene": f"销售订单 {order['order_code']}",
                    "data": {
                        "product": order.get("product_name"),
                        "qty": order.get("quantity"),
                        "rdd": str(rdd) if rdd else "未定",
                        "priority": order.get("priority"),
                        "status": order.get("status"),
                        "material_ready": "已齐套" if order.get("material_ready") else "未齐套",
                    },
                    "prompt": "该订单应采取的评审结论是？",
                    "options": [
                        {"value": "approved", "label": "评审通过，正常纳入排程"},
                        {"value": "conditional", "label": "条件承诺，跟踪缺口后承诺"},
                        {"value": "block", "label": "阻塞，不得直接承诺交期"},
                        {"value": "pending", "label": "待评审，先核对证据"},
                    ],
                    "answer": [answer],
                    "explanation": f"真实评审状态={review or '未评审'}，风险={risk or '未知'}。{correct_label}。",
                    "skill": "订单评审",
                    "reference_terms": ["订单评审", "RDD", "条件承诺"],
                }
            )

    elif level == 2:
        # L2: 真实工单缺料 -> 选择正确处置动作
        rows = (
            await db.execute(
                text(
                    """
                    SELECT wom.work_order_id,
                           wom.material_code, wom.material_name,
                           wom.required_qty, wom.available_qty, wom.shortage_qty
                    FROM work_order_materials wom
                    WHERE wom.shortage_qty > 0
                    ORDER BY wom.shortage_qty DESC
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            )
        ).mappings().all()
        for row in rows:
            mat = dict(row)
            drills.append(
                {
                    "id": f"{mat['work_order_id']}|{mat['material_code']}",
                    "level": 2,
                    "type": "shortage_action",
                    "scene": f"工单 {mat['work_order_id']}",
                    "data": {
                        "material": f"{mat.get('material_code')} {mat.get('material_name')}",
                        "required": mat.get("required_qty"),
                        "available": mat.get("available_qty"),
                        "shortage": mat.get("shortage_qty"),
                    },
                    "prompt": "该物料缺料时，PMC 的正确处置顺序是？",
                    "options": [
                        {"value": "a", "label": "先Pull In/替代料追料，追不上就调整生产计划，绝不让线上等料"},
                        {"value": "b", "label": "产线停下来等料到齐"},
                        {"value": "c", "label": "直接取消该工单"},
                        {"value": "d", "label": "不通知生产，自己默默处理"},
                    ],
                    "answer": ["a"],
                    "explanation": (
                        f"真实缺口={mat['shortage_qty']}件（需求{mat['required_qty']}/可用{mat['available_qty']}）。"
                        "先追料（Pull In/替代），追不上调整计划前后置换，保证产能不空转。"
                    ),
                    "skill": "物料短缺控制",
                    "reference_terms": ["欠料", "Pull In", "替代料"],
                }
            )

    else:
        # L3: 综合排程 —— 近交期的真实订单 + 缺料情况，选择最优排程
        so_rows = (
            await db.execute(
                text(
                    """
                    SELECT order_code, product_name, quantity, delivery_date, priority
                    FROM sales_orders
                    WHERE delivery_date IS NOT NULL
                    ORDER BY delivery_date
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            )
        ).mappings().all()
        shortage_rows = (
            await db.execute(
                text(
                    """
                    SELECT material_code, material_name, SUM(shortage_qty) AS total_shortage
                    FROM work_order_materials
                    WHERE shortage_qty > 0
                    GROUP BY material_code, material_name
                    ORDER BY total_shortage DESC
                    LIMIT 5
                    """
                ),
            )
        ).mappings().all()
        for row in so_rows:
            order = dict(row)
            has_shortage = len(shortage_rows) > 0
            shortage_desc = [
                f"{m['material_code']}缺口{m['total_shortage']}" for m in shortage_rows[:3]
            ] if has_shortage else []
            drills.append(
                {
                    "id": order['order_code'],
                    "level": 3,
                    "type": "schedule_priority",
                    "scene": f"排程决策 {order['order_code']}",
                    "data": {
                        "product": order.get("product_name"),
                        "qty": order.get("quantity"),
                        "rdd": str(order.get("delivery_date")),
                        "priority": order.get("priority"),
                        "system_shortages": shortage_desc,
                    },
                    "prompt": "面对该订单交期与系统内已知缺料，PMC 应优先做什么？",
                    "options": [
                        {"value": "a", "label": "先核对缺料对这张单的影响，缺料涉及则升级并调整排程优先级"},
                        {"value": "b", "label": "先排最近交期的单，缺料后补"},
                        {"value": "c", "label": "先承诺客户交期，再想办法"},
                        {"value": "d", "label": "只按优先级排序，不查缺料"},
                    ],
                    "answer": ["a"],
                    "explanation": (
                        f"该单RDD={order['delivery_date']}，优先级={order['priority']}；"
                        f"系统已知缺料：{'、'.join(shortage_desc) if shortage_desc else '暂无'}。"
                        "排程必须先把缺料与交期对齐——缺料会拖交期，先承诺后补救是错的。"
                    ),
                    "skill": "综合排程",
                    "reference_terms": ["排程", "缺料", "RDD", "优先级"],
                }
            )

    return {
        "position": position,
        "factory_id": fid,
        "level": level,
        "level_label": {1: "基础判断", 2: "缺料决策", 3: "综合排程"}[level],
        "drills": drills,
        "mission": "以下场景来自系统真实数据（销售订单/工单缺料），答案依据真实评审状态与实操原则判定。",
    }


@router.post("/drills/attempts", summary="提交实操演练答案")
async def submit_drill_attempt(
    payload: TrainingAttemptRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """实操演练答案提交：复用题库评分逻辑（single 类型）。"""
    position = _position_summary(payload.position_code)
    canonical_code = position["code"]
    if not payload.answers:
        raise HTTPException(status_code=400, detail="至少回答一道题")

    # 从销售订单/工单缺料中取场景题答案进行评分（只取单题答案的 first）
    level = payload.level or 1
    # L1 按真实订单评审状态推导；L2/L3 按固定标准答案(a)
    if level != 1:
        review_map: Dict[str, Dict[str, Any]] = {}
    else:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT order_code, review_status, risk_level
                    FROM sales_orders
                    WHERE order_code = ANY(:codes)
                    """
                ),
                {"codes": list(payload.answers.keys())},
            )
        ).mappings().all()
        review_map = {row["order_code"]: dict(row) for row in rows}

    total = 0
    earned = 0
    details: List[Dict[str, Any]] = []
    for code, answer_list in payload.answers.items():
        selected = sorted(str(v) for v in (answer_list or []))
        actual = selected[0] if selected else ""
        review = review_map.get(code)
        if level == 1 and review:
            if review["review_status"] == "conditional":
                expected = "conditional"
            elif review["review_status"] == "approved":
                expected = "approved"
            elif review["risk_level"] in ("high", "critical"):
                expected = "block"
            else:
                expected = "pending"
        else:
            # 非订单码题目(L2缺料/L3排程)按固定标准答案 a
            expected = "a"
        correct = actual == expected
        total += 1
        earned += 1 if correct else 0
        details.append(
            {
                "id": code,
                "correct": correct,
                "selected": [actual] if actual else [],
                "answer": [expected],
            }
        )

    score = round(earned / total * 100, 1) if total else 0
    attempt_id = str(uuid4())
    await db.execute(
        text(
            """
            INSERT INTO position_training_attempts
                (id, position_code, user_id, factory_id, answers, score,
                 earned_points, total_points, details)
            VALUES (:id, :position_code, :user_id, :factory_id,
                    CAST(:answers AS JSONB), :score, :earned_points,
                    :total_points, CAST(:details AS JSONB))
            """
        ),
        {
            "id": attempt_id,
            "position_code": canonical_code,
            "user_id": _user_id(current_user),
            "factory_id": _factory_id(current_user, payload.factory_id),
            "answers": json.dumps(payload.answers, ensure_ascii=False),
            "score": score,
            "earned_points": earned,
            "total_points": total,
            "details": json.dumps(details, ensure_ascii=False),
        },
    )
    await db.commit()
    return {
        "attempt_id": attempt_id,
        "position_code": canonical_code,
        "score": score,
        "earned_points": earned,
        "total_points": total,
        "passed": score >= 80,
        "details": details,
    }


__all__ = ["router"]
