"""Quality Skill - 质量域只读工具。

当前迁移：
- query_defects          查询不良记录
- query_spc_anomalies    查询 SPC 失控点

两项工具均只读，并在 Skill 层显式应用工厂作用域；其返回结构与
``chat_tools_service`` 的原实现保持一致，便于 Chat V2 渐进切换。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from core.skills.base import BaseSkill
from core.skills.work_order.skill import _td


class QualitySkill(BaseSkill):
    """质量域技能。"""

    @property
    def name(self) -> str:
        return "quality"

    @property
    def module(self) -> str:
        return "quality"

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        return [
            _td(
                "query_defects",
                "查询不良记录，支持按工厂和严重度过滤，返回处置、OCAP 和根因状态",
                {
                    "factory_id": {"type": "string", "description": "工厂ID"},
                    "severity": {
                        "type": "string",
                        "enum": ["critical", "major", "minor", "observation"],
                        "description": "严重度过滤",
                    },
                    "limit": {"type": "integer", "description": "返回数量上限"},
                },
            ),
            _td(
                "query_spc_anomalies",
                "查询 SPC 失控点，返回测量值、控制限、偏差、工位和测量时间",
                {
                    "factory_id": {"type": "string", "description": "工厂ID"},
                    "limit": {"type": "integer", "description": "返回数量上限"},
                },
            ),
        ]

    async def execute(
        self,
        tool_name: str,
        args: Dict[str, Any],
        *,
        db: Any = None,
        operator: str = "ai_assistant",
        factory_id: Optional[str] = None,
        ctx: Any = None,
    ) -> Dict[str, Any]:
        if tool_name == "query_defects":
            return await self._query_defects(db, args, factory_id)
        if tool_name == "query_spc_anomalies":
            return await self._query_spc_anomalies(db, args, factory_id)
        return {"error": f"quality skill 未实现工具：{tool_name}"}

    async def _query_defects(
        self, db: Any, args: Dict[str, Any], factory_id: Optional[str],
    ) -> Dict[str, Any]:
        from sqlalchemy import select

        from database.models import DefectRecord

        fid = args.get("factory_id") or factory_id
        limit = max(1, min(int(args.get("limit") or 10), 50))
        stmt = select(DefectRecord).order_by(DefectRecord.created_at.desc()).limit(limit)
        if fid:
            stmt = stmt.where(DefectRecord.factory_id == fid)
        if args.get("severity"):
            stmt = stmt.where(DefectRecord.severity == args["severity"])

        rows = (await db.execute(stmt)).scalars().all()
        items = [
            {
                "record_code": defect.record_code,
                "defect_type": defect.defect_type,
                "severity": defect.severity,
                "quantity": defect.quantity,
                "disposition": defect.disposition or "未处置",
                "ocap_status": defect.ocap_status,
                "root_cause_category": defect.root_cause_category,
                "description": (defect.description or "")[:80],
                "created_at": self._format_datetime(defect.created_at),
            }
            for defect in rows
        ]
        return {"count": len(items), "defects": items}

    async def _query_spc_anomalies(
        self, db: Any, args: Dict[str, Any], factory_id: Optional[str],
    ) -> Dict[str, Any]:
        from sqlalchemy import func, select

        from database.models import QmsSpcPoint

        fid = args.get("factory_id") or factory_id or "FAC_ELEC_DEMO_2026"
        limit = max(1, min(int(args.get("limit") or 20), 50))
        base = (
            QmsSpcPoint.factory_id == fid,
            QmsSpcPoint.is_out_of_control.is_(True),
        )
        stmt = select(QmsSpcPoint).where(*base).order_by(QmsSpcPoint.measured_at.desc()).limit(limit)
        rows = (await db.execute(stmt)).scalars().all()

        total_stmt = select(func.count()).select_from(QmsSpcPoint).where(
            *base,
            QmsSpcPoint.measured_at
            >= datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7),
        )
        total_7d = int((await db.execute(total_stmt)).scalar_one_or_none() or 0)

        items = [self._spc_to_dict(point) for point in rows]
        return {
            "factory_id": fid,
            "anomaly_count": len(items),
            "total_7d": total_7d,
            "anomalies": items,
        }

    @staticmethod
    def _format_datetime(value: Any) -> Optional[str]:
        if value is None:
            return None
        if hasattr(value, "strftime"):
            return value.strftime("%Y-%m-%d %H:%M")
        return str(value)[:16]

    @classmethod
    def _spc_to_dict(cls, point: Any) -> Dict[str, Any]:
        value = getattr(point, "measured_value", None)
        ucl = getattr(point, "ucl", None)
        lcl = getattr(point, "lcl", None)
        deviation = None
        if value is not None and ucl is not None and value > ucl:
            deviation = round(value - ucl, 3)
        elif value is not None and lcl is not None:
            deviation = round(value - lcl, 3)
        return {
            "characteristic": getattr(point, "characteristic_name", None)
            or getattr(point, "characteristic_code", None),
            "measured_value": round(value, 3) if value is not None else None,
            "ucl": ucl,
            "lcl": lcl,
            "cl": getattr(point, "cl", None),
            "deviation": deviation,
            "station": getattr(point, "station_id", None),
            "measured_at": cls._format_datetime(getattr(point, "measured_at", None)),
            "measured_by": getattr(point, "measured_by", None),
        }


SKILL = QualitySkill()


def build_skill() -> BaseSkill:
    return QualitySkill()
