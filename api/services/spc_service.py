"""
SPC 统计过程控制服务 - 岗位替代 Phase 4
X-bar/R 控制图 + 过程能力 Cpk + 失控检测（Western Electric Rules）
"""
import uuid
import math
from datetime import datetime
from typing import Optional, Dict, Any, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text


def _gen_id() -> str:
    return str(uuid.uuid4())


# X-bar/R 控制图系数（n=2~10）
A2_TABLE = {2: 1.880, 3: 1.023, 4: 0.729, 5: 0.577, 6: 0.483, 7: 0.419, 8: 0.373, 9: 0.337, 10: 0.308}
D3_TABLE = {2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0.076, 8: 0.136, 9: 0.184, 10: 0.223}
D4_TABLE = {2: 3.267, 3: 2.575, 4: 2.282, 5: 2.115, 6: 2.004, 7: 1.924, 8: 1.864, 9: 1.816, 10: 1.777}
D2_TABLE = {2: 1.128, 3: 1.693, 4: 2.059, 5: 2.326, 6: 2.534, 7: 2.704, 8: 2.847, 9: 2.970, 10: 3.078}


class SpcService:
    """SPC 统计过程控制"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def record_measurement(
        self,
        factory_id: str,
        characteristic_code: str,
        measured_value: float,
        characteristic_name: Optional[str] = None,
        work_order_id: Optional[str] = None,
        station_id: Optional[str] = None,
        sample_group: Optional[int] = None,
        measured_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """记录 SPC 测量值"""
        now = datetime.utcnow()

        # 获取控制限配置
        config = await self.db.execute(text(
            "SELECT ucl, cl, lcl FROM spc_chart_config WHERE factory_id = :fid AND characteristic_code = :code AND is_active = TRUE"
        ), {"fid": factory_id, "code": characteristic_code})
        cfg = config.mappings().first()

        ucl = cfg["ucl"] if cfg else None
        cl = cfg["cl"] if cfg else None
        lcl = cfg["lcl"] if cfg else None

        # 判定是否失控
        is_ooc = False
        if ucl is not None and measured_value > ucl:
            is_ooc = True
        if lcl is not None and measured_value < lcl:
            is_ooc = True

        await self.db.execute(text("""
            INSERT INTO qms_spc_points (id, factory_id, characteristic_code, characteristic_name,
                work_order_id, station_id, measured_value, sample_group, ucl, lcl, cl,
                is_out_of_control, measured_at, measured_by)
            VALUES (:id, :fid, :code, :name, :woid, :sid, :val, :grp, :ucl, :lcl, :cl, :ooc, :now, :by)
        """), {
            "id": _gen_id(), "fid": factory_id, "code": characteristic_code,
            "name": characteristic_name, "woid": work_order_id, "sid": station_id,
            "val": measured_value, "grp": sample_group,
            "ucl": ucl, "lcl": lcl, "cl": cl, "ooc": is_ooc,
            "now": now, "by": measured_by,
        })
        await self.db.commit()

        return {
            "success": True,
            "measured_value": measured_value,
            "is_out_of_control": is_ooc,
            "ucl": ucl, "cl": cl, "lcl": lcl,
        }

    async def get_control_chart(
        self, factory_id: str, characteristic_code: str, limit: int = 50
    ) -> Dict[str, Any]:
        """获取控制图数据"""
        result = await self.db.execute(text("""
            SELECT measured_value, sample_group, ucl, lcl, cl, is_out_of_control, measured_at, station_id
            FROM qms_spc_points
            WHERE factory_id = :fid AND characteristic_code = :code
            ORDER BY measured_at DESC LIMIT :lim
        """), {"fid": factory_id, "code": characteristic_code, "lim": limit})
        points = [dict(r) for r in result.mappings().all()]
        points.reverse()  # 时间正序

        # 获取配置
        config = await self.db.execute(text(
            "SELECT * FROM spc_chart_config WHERE factory_id = :fid AND characteristic_code = :code"
        ), {"fid": factory_id, "code": characteristic_code})
        cfg = config.mappings().first()

        # 计算过程能力
        values = [p["measured_value"] for p in points]
        cpk = None
        if cfg and len(values) >= 10:
            cpk = self._calc_cpk(values, cfg.get("usl"), cfg.get("lsl"))

        return {
            "characteristic_code": characteristic_code,
            "characteristic_name": cfg["characteristic_name"] if cfg else characteristic_code,
            "chart_type": cfg["chart_type"] if cfg else "Xbar-R",
            "points": points,
            "ucl": cfg["ucl"] if cfg else None,
            "cl": cfg["cl"] if cfg else None,
            "lcl": cfg["lcl"] if cfg else None,
            "usl": cfg["usl"] if cfg else None,
            "lsl": cfg["lsl"] if cfg else None,
            "cpk": cpk,
            "total_points": len(points),
            "ooc_count": sum(1 for p in points if p["is_out_of_control"]),
        }

    async def calculate_control_limits(
        self, factory_id: str, characteristic_code: str, subgroup_size: int = 5
    ) -> Dict[str, Any]:
        """根据历史数据计算控制限"""
        result = await self.db.execute(text("""
            SELECT measured_value, sample_group
            FROM qms_spc_points
            WHERE factory_id = :fid AND characteristic_code = :code
            ORDER BY measured_at DESC LIMIT 200
        """), {"fid": factory_id, "code": characteristic_code})
        rows = result.mappings().all()

        if len(rows) < subgroup_size * 5:
            return {"error": f"数据不足（需至少 {subgroup_size * 5} 个点）", "count": len(rows)}

        values = [r["measured_value"] for r in rows]

        # 按子组分组
        groups: Dict[int, List[float]] = {}
        for r in rows:
            grp = r["sample_group"] or (len(groups) + 1)
            if grp not in groups:
                groups[grp] = []
            groups[grp].append(r["measured_value"])

        # 计算 X-bar 和 R
        xbars = []
        ranges = []
        for grp_vals in groups.values():
            if len(grp_vals) >= 2:
                xbars.append(sum(grp_vals) / len(grp_vals))
                ranges.append(max(grp_vals) - min(grp_vals))

        if not xbars:
            return {"error": "无法计算（子组数据不足）"}

        x_double_bar = sum(xbars) / len(xbars)
        r_bar = sum(ranges) / len(ranges) if ranges else 0

        n = min(subgroup_size, 10)
        A2 = A2_TABLE.get(n, 0.577)
        D3 = D3_TABLE.get(n, 0)
        D4 = D4_TABLE.get(n, 2.115)

        # X-bar 控制限
        xbar_ucl = x_double_bar + A2 * r_bar
        xbar_lcl = x_double_bar - A2 * r_bar

        # R 控制限
        r_ucl = D4 * r_bar
        r_lcl = D3 * r_bar

        # 更新配置
        await self.db.execute(text("""
            INSERT INTO spc_chart_config (id, factory_id, characteristic_code, chart_type,
                ucl, cl, lcl, subgroup_size, is_active, created_at, updated_at)
            VALUES (:id, :fid, :code, 'Xbar-R', :ucl, :cl, :lcl, :n, TRUE, :now, :now)
            ON CONFLICT (factory_id, characteristic_code) DO UPDATE SET
                ucl = :ucl, cl = :cl, lcl = :lcl, subgroup_size = :n, updated_at = :now
        """), {
            "id": _gen_id(), "fid": factory_id, "code": characteristic_code,
            "ucl": round(xbar_ucl, 4), "cl": round(x_double_bar, 4), "lcl": round(xbar_lcl, 4),
            "n": n, "now": datetime.utcnow(),
        })
        await self.db.commit()

        return {
            "success": True,
            "xbar_chart": {"ucl": round(xbar_ucl, 4), "cl": round(x_double_bar, 4), "lcl": round(xbar_lcl, 4)},
            "r_chart": {"ucl": round(r_ucl, 4), "cl": round(r_bar, 4), "lcl": round(r_lcl, 4)},
            "subgroups_used": len(xbars),
            "subgroup_size": n,
        }

    async def list_characteristics(self, factory_id: str) -> Dict[str, Any]:
        """列出所有 SPC 特性"""
        result = await self.db.execute(text(
            "SELECT * FROM spc_chart_config WHERE factory_id = :fid ORDER BY characteristic_code"
        ), {"fid": factory_id})
        return {"items": [dict(r) for r in result.mappings().all()]}

    async def upsert_config(
        self, factory_id: str, characteristic_code: str, characteristic_name: str = "",
        chart_type: str = "Xbar-R", ucl: Optional[float] = None, cl: Optional[float] = None,
        lcl: Optional[float] = None, usl: Optional[float] = None, lsl: Optional[float] = None,
        subgroup_size: int = 5,
    ) -> Dict[str, Any]:
        """新增/更新 SPC 配置"""
        await self.db.execute(text("""
            INSERT INTO spc_chart_config (id, factory_id, characteristic_code, characteristic_name,
                chart_type, ucl, cl, lcl, usl, lsl, subgroup_size, is_active, created_at, updated_at)
            VALUES (:id, :fid, :code, :name, :type, :ucl, :cl, :lcl, :usl, :lsl, :n, TRUE, :now, :now)
            ON CONFLICT (factory_id, characteristic_code) DO UPDATE SET
                characteristic_name = :name, chart_type = :type, ucl = :ucl, cl = :cl,
                lcl = :lcl, usl = :usl, lsl = :lsl, subgroup_size = :n, updated_at = :now
        """), {
            "id": _gen_id(), "fid": factory_id, "code": characteristic_code,
            "name": characteristic_name, "type": chart_type,
            "ucl": ucl, "cl": cl, "lcl": lcl, "usl": usl, "lsl": lsl,
            "n": subgroup_size, "now": datetime.utcnow(),
        })
        await self.db.commit()
        return {"success": True, "characteristic_code": characteristic_code}

    # ==================== 内部方法 ====================

    def _calc_cpk(self, values: List[float], usl: Optional[float], lsl: Optional[float]) -> Optional[float]:
        """计算 Cpk"""
        if not usl or not lsl or len(values) < 2:
            return None
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
        std = math.sqrt(variance)
        if std == 0:
            return None
        cpu = (usl - mean) / (3 * std)
        cpl = (mean - lsl) / (3 * std)
        return round(min(cpu, cpl), 3)
