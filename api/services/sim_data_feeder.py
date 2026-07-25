"""
仿真引擎数据喂入服务（live 数据桥）
====================================

从真实 DB 拉取 人力(hr_employees + hr_employee_skills + skills) / 设备(stations) /
工艺(routing_templates + routing_template_steps)，构建 ``FactorySimConfig`` 喂给
``core/sim_factory`` 负荷仿真引擎，替代硬编码场景参数。

接入深度（与引擎 Part1 对齐）：
- 各工段人数由 HR 在职人数驱动（``SectionConfig.workers``）；
- 真实花名册（``real_workers``）：姓名/技能等级/班次/性别/身高/体重，技能影响产能；
- 工艺路线工序来自 ``routing_template_steps``（不再解析 description 字符串），
  且仅引用已存在的工段；无可映射工艺时回退在真实工段上合成一条工艺链，保证 run-live 始终可运行；
- 模拟订单规模基于真实人数/产能推算（不再依赖不存在的 inventory 表）。
"""

from __future__ import annotations

from math import ceil
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from core.sim_factory.models import (
    FactorySimConfig,
    OrderInput,
    Priority,
    ProductionStrategy,
    RealWorkerSeed,
    RoutingDef,
    RoutingOperation,
    SectionConfig,
    WorkshopConfig,
)

# 技能等级词汇 → 1~5（兼容 L 码 / 中文等级 / 数字）
_SKILL_LEVEL_MAP = {
    "L1": 1, "L2": 2, "L3": 3, "L4": 4, "L5": 5,
    "初级": 1, "中级": 2, "高级": 3, "技师": 4, "高级技师": 5,
}

# 班次词汇 → 班次序号
_SHIFT_MAP = {"白班": 1, "夜班": 2, "中班": 2, "两班倒": 1}


def _parse_skill_level(val: Any) -> int:
    """把技能等级（L1-L5 / 中文 / 数字）归一化为 1~5，未知回退 3。"""
    if val is None:
        return 3
    s = str(val).strip()
    if s in _SKILL_LEVEL_MAP:
        return _SKILL_LEVEL_MAP[s]
    try:
        return max(1, min(5, int(float(s))))
    except (TypeError, ValueError):
        return 3


def _to_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        f = float(val)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _match_section_id(token: Optional[str], name_to_sid: Dict[str, str]) -> Optional[str]:
    """把工艺工序名/工序组编码模糊匹配到已存在的工段 id。"""
    if not token:
        return None
    token = token.strip()
    for name, sid in name_to_sid.items():
        if token == name or token in name or name in token:
            return sid
    return None


async def build_live_config(db: AsyncSession, factory_id: str, horizon_days: int = 14) -> FactorySimConfig:
    """从 DB 真实数据构建仿真配置。

    :raises ValueError: 工厂无在职员工（无法构建任何工段）时抛出。
    """
    # ━━━ 1. 在职员工（含身高体重）━━━
    emp_rows = (await db.execute(sa_text("""
        SELECT id, name, gender, department, station, position, shift,
               skill_level, height_cm, weight_kg
        FROM hr_employees
        WHERE factory_id = :fid AND status = 'active'
        ORDER BY department, station, id
    """), {"fid": factory_id})).fetchall()

    if not emp_rows:
        raise ValueError(f"工厂 {factory_id} 无在职员工，无法构建实时仿真配置")

    # ━━━ 2. 员工技能等级（取每人最高等级）━━━
    skill_rows = (await db.execute(sa_text("""
        SELECT hes.hr_employee_id, hes.level
        FROM hr_employee_skills hes
        JOIN hr_employees e ON e.id = hes.hr_employee_id
        WHERE e.factory_id = :fid
    """), {"fid": factory_id})).fetchall()
    emp_max_skill: Dict[str, int] = {}
    for emp_id, level in skill_rows:
        lv = _parse_skill_level(level)
        emp_max_skill[emp_id] = max(emp_max_skill.get(emp_id, 0), lv)

    # ━━━ 3. 设备：工位设备台数（模糊匹配工段）━━━
    st_rows = (await db.execute(sa_text("""
        SELECT station_name, station_type, capacity, equipment_count
        FROM stations
        WHERE factory_id = :fid AND status = 'active'
    """), {"fid": factory_id})).fetchall()
    station_machines: Dict[str, int] = {}
    station_type_map: Dict[str, str] = {}
    for name, stype, _cap, eq in st_rows:
        station_machines[name] = eq or 0
        station_type_map[name] = stype or "production"

    # ━━━ 4. 按 (department, station) 聚合工段 + 真实花名册 ━━━
    workshops: List[WorkshopConfig] = []
    sections: List[SectionConfig] = []
    dept_seen: Dict[str, str] = {}
    name_to_sid: Dict[str, str] = {}

    grouped: Dict[Tuple[str, str], List[Any]] = {}
    for row in emp_rows:
        grouped.setdefault((row[2 + 1], row[3 + 1]), []).append(row)  # (department, station)

    for (dept, station_name), rows in grouped.items():
        if not station_name:
            continue
        # 车间（按部门）
        if dept not in dept_seen:
            ws_id = f"WS-{dept}"
            dept_seen[dept] = ws_id
            workshops.append(WorkshopConfig(workshop_id=ws_id, name=dept or "生产车间"))
        ws_id = dept_seen[dept]

        # 班次：含夜班/两班倒 → 两班
        has_multi_shift = any((r[6] in ("夜班", "两班倒", "中班")) for r in rows)
        shifts_per_day = 2 if has_multi_shift else 1
        headcount = len(rows)

        # 真实花名册
        real_workers: List[RealWorkerSeed] = []
        for i, r in enumerate(rows):
            emp_id, name, gender = r[0], r[1], r[2]
            shift_raw = r[6]
            shift = _SHIFT_MAP.get(shift_raw, 1)
            if shift_raw == "两班倒":
                shift = (i % 2) + 1
            skill = emp_max_skill.get(emp_id) or _parse_skill_level(r[7])
            real_workers.append(RealWorkerSeed(
                name=name or f"员工{i + 1}",
                skill_level=skill,
                shift=shift,
                gender=gender,
                height_cm=_to_float(r[8]),
                weight_kg=_to_float(r[9]),
                role=r[5] or station_name,
            ))

        # 设备模糊匹配
        machines = 0
        for st_name, m_count in station_machines.items():
            if station_name in st_name or st_name.replace("车间", "") in station_name:
                machines = max(machines, m_count)

        # 生产策略：加工/备料类 MTS，组装/检测类 MTO
        stype = station_type_map.get(station_name, "production")
        strategy = ProductionStrategy.MTS if stype == "production" else ProductionStrategy.MTO

        sid = f"SEC-{station_name}"
        name_to_sid[station_name] = sid
        sections.append(SectionConfig(
            section_id=sid,
            name=station_name,
            workshop_id=ws_id,
            strategy=strategy,
            workers=max(1, round(headcount / shifts_per_day)),  # 单班人数
            machines=machines,
            shifts_per_day=shifts_per_day,
            hours_per_shift=8.0,
            efficiency=0.85,
            max_overtime_pct=0.2,
            yield_rate=0.97,
            role_name=station_name,
            description=f"{dept} | 在职{headcount}人 | 设备{machines}台",
            real_workers=real_workers,
        ))

    if not sections:
        raise ValueError(f"工厂 {factory_id} 无可用工段（员工缺少 station 信息）")

    # ━━━ 5. 工艺路线（routing_template_steps，仅引用已存在工段）━━━
    routings = await _build_routings(db, factory_id, name_to_sid)

    # 回退：无可映射工艺 → 在真实工段上合成一条工艺链，保证 run-live 可运行
    if not routings:
        routings = [_synthesize_fallback_routing(sections)]

    # ━━━ 6. 模拟订单（基于真实人数/产能推算）━━━
    total_workers = sum(len(s.real_workers) for s in sections)
    orders = _build_orders(routings, total_workers, horizon_days)

    return FactorySimConfig(
        horizon_days=horizon_days,
        seed=42,
        workshops=workshops,
        sections=sections,
        routings=routings,
        orders=orders,
        factory_id=factory_id,
        factory_name=f"实时数据仿真 ({factory_id})",
        data_source="live_db",
    )


async def _build_routings(db: AsyncSession, factory_id: str,
                          name_to_sid: Dict[str, str]) -> List[RoutingDef]:
    """从 routing_templates + routing_template_steps 构建工艺路线，工序仅引用已存在工段。"""
    rt_rows = (await db.execute(sa_text("""
        SELECT t.id, t.template_code, t.template_name,
               s.seq, s.operation_name, s.work_center, s.process_code, s.standard_hours
        FROM routing_templates t
        LEFT JOIN routing_template_steps s ON s.template_id = t.id
        WHERE t.factory_id = :fid AND t.is_active = true
        ORDER BY t.id, s.seq
    """), {"fid": factory_id})).fetchall()

    # 按模板聚合
    templates: Dict[str, Dict[str, Any]] = {}
    for tid, code, tname, seq, op_name, work_center, process_code, std_hours in rt_rows:
        t = templates.setdefault(tid, {"code": code, "name": tname, "steps": []})
        if seq is not None:
            t["steps"].append({
                "seq": seq, "op_name": op_name, "work_center": work_center,
                "process_code": process_code, "std_hours": float(std_hours or 0.0),
            })

    routings: List[RoutingDef] = []
    for idx, (tid, t) in enumerate(templates.items(), start=1):
        ops: List[RoutingOperation] = []
        last_sid: Optional[str] = None
        op_no = 0
        for step in sorted(t["steps"], key=lambda x: x["seq"]):
            sid = (_match_section_id(step["op_name"], name_to_sid)
                   or _match_section_id(step["work_center"], name_to_sid)
                   or _match_section_id(step["process_code"], name_to_sid))
            if sid is None or sid == last_sid:
                continue  # 跳过无法映射或连续重复工段
            op_no += 10
            cycle = max(30.0, min(600.0, step["std_hours"] * 60.0)) if step["std_hours"] > 0 else 120.0
            ops.append(RoutingOperation(
                op_no=op_no,
                name=step["op_name"] or step["process_code"] or f"工序{op_no}",
                section_id=sid,
                setup_minutes=30.0,
                cycle_seconds=cycle,
                batch_size=50,
                move_hours=4.0,
            ))
            last_sid = sid
        if ops:
            routings.append(RoutingDef(
                routing_id=f"RT-LIVE-{idx:03d}",
                product_id=f"PRD-LIVE-{idx:03d}",
                product_name=t["name"] or f"产品{idx}",
                operations=ops,
            ))
    return routings


def _synthesize_fallback_routing(sections: List[SectionConfig]) -> RoutingDef:
    """无可用工艺模板时，在真实工段上合成一条工艺链（MTS 在前、MTO 在后）。"""
    ordered = sorted(sections, key=lambda s: (s.strategy != ProductionStrategy.MTS, s.section_id))
    ops = [
        RoutingOperation(
            op_no=(i + 1) * 10,
            name=s.name,
            section_id=s.section_id,
            setup_minutes=30.0,
            cycle_seconds=120.0,
            batch_size=50,
            move_hours=4.0,
        )
        for i, s in enumerate(ordered)
    ]
    return RoutingDef(
        routing_id="RT-LIVE-FALLBACK",
        product_id="PRD-LIVE-FALLBACK",
        product_name="实时合成产品",
        operations=ops,
    )


def _build_orders(routings: List[RoutingDef], total_workers: int, horizon_days: int) -> List[OrderInput]:
    """基于真实人数推算模拟订单规模（人数越多 → 订单量越大）。"""
    base_qty = max(200, total_workers * 15)
    orders: List[OrderInput] = []
    for i, rt in enumerate(routings[:6]):
        orders.append(OrderInput(
            order_id=f"LIVE-ORD-{i + 1:03d}",
            product_id=rt.product_id,
            quantity=base_qty + i * 100,
            release_day=i % max(1, horizon_days // 3),
            due_day=max(2, horizon_days - 2 + i),
            priority=Priority.MEDIUM,
        ))
    return orders


async def get_live_data_summary(db: AsyncSession, factory_id: str) -> Dict[str, Any]:
    """获取喂入仿真引擎的数据摘要（供前端展示"数据已接入"状态）。"""
    hr = (await db.execute(sa_text(
        "SELECT count(*) FILTER (WHERE status='active') FROM hr_employees WHERE factory_id = :fid"
    ), {"fid": factory_id})).scalar() or 0
    st = (await db.execute(sa_text(
        "SELECT count(*), COALESCE(SUM(equipment_count),0) FROM stations WHERE factory_id = :fid AND status='active'"
    ), {"fid": factory_id})).fetchone()
    skill_cnt = (await db.execute(sa_text("""
        SELECT count(*) FROM hr_employee_skills hes
        JOIN hr_employees e ON e.id = hes.hr_employee_id
        WHERE e.factory_id = :fid
    """), {"fid": factory_id})).scalar() or 0
    rt = (await db.execute(sa_text(
        "SELECT count(*) FROM routing_templates WHERE factory_id = :fid AND is_active = true"
    ), {"fid": factory_id})).scalar() or 0

    return {
        "factory_id": factory_id,
        "inputs": {
            "人力": {"active_workers": hr, "source": "hr_employees"},
            "技能": {"employee_skill_records": skill_cnt, "source": "hr_employee_skills+skills"},
            "设备": {"stations": st[0], "equipment_total": st[1], "source": "stations"},
            "工艺": {"routing_count": rt, "source": "routing_templates+steps"},
        },
        "ready": hr > 0,
    }
