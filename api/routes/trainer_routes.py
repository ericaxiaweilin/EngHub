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


__all__ = ["router"]
