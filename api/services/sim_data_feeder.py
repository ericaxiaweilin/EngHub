"""
仿真引擎数据喂入服务

从真实 DB 拉取 人(hr_employees) / 设备(stations) / 物料(inventory) / 工艺(routing_templates)
构建 FactorySimConfig，替代硬编码场景参数。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from core.sim_factory.models import (
    FactorySimConfig,
    OrderInput,
    RoutingDef,
    SectionConfig,
    WorkshopConfig,
    ProductionStrategy,
)


async def build_live_config(db: AsyncSession, factory_id: str, horizon_days: int = 14) -> FactorySimConfig:
    """从 DB 真实数据构建仿真配置。

    数据源：
    - hr_employees → 各工序人数（workers）
    - stations → 设备台数（machines）、产能
    - inventory → 物料可用量（影响订单规模）
    - routing_templates → 工艺路线（工序顺序）
    """

    # ━━━ 1. 人力：按工序统计在职人数 ━━━
    hr_rows = (await db.execute(sa_text("""
        SELECT department, station, count(*) FILTER (WHERE status = 'active') as workers
        FROM hr_employees
        WHERE factory_id = :fid
        GROUP BY department, station
        ORDER BY department, station
    """), {"fid": factory_id})).fetchall()

    # ━━━ 2. 设备：工位设备台数 ━━━
    st_rows = (await db.execute(sa_text("""
        SELECT station_name, station_type, capacity, equipment_count
        FROM stations
        WHERE factory_id = :fid AND status = 'active'
    """), {"fid": factory_id})).fetchall()
    station_machines: Dict[str, int] = {}
    station_type_map: Dict[str, str] = {}
    for r in st_rows:
        station_machines[r[0]] = r[3] or 0
        station_type_map[r[0]] = r[1]

    # ━━━ 3. 物料：库存总量（影响模拟订单规模） ━━━
    inv_row = (await db.execute(sa_text("""
        SELECT COALESCE(SUM(total_qty), 0) as total_qty, count(*) as sku_count
        FROM inventory
        WHERE factory_id = :fid
    """), {"fid": factory_id})).fetchone()
    total_material_qty = inv_row[0] if inv_row else 0
    sku_count = inv_row[1] if inv_row else 0

    # ━━━ 4. 工艺路线 ━━━
    rt_rows = (await db.execute(sa_text("""
        SELECT template_code, template_name, description
        FROM routing_templates
        WHERE factory_id = :fid AND is_active = true
    """), {"fid": factory_id})).fetchall()

    # ━━━ 构建 SectionConfig（每个工序 = 一个工段） ━━━
    # 部门 → 车间映射
    dept_workshop_map: Dict[str, str] = {}
    workshops: List[WorkshopConfig] = []
    sections: List[SectionConfig] = []

    for r in hr_rows:
        dept, station_name, workers = r[0], r[1], r[2]
        if workers == 0:
            continue

        # 车间
        ws_id = f"WS-{dept}"
        if dept not in dept_workshop_map:
            dept_workshop_map[dept] = ws_id
            workshops.append(WorkshopConfig(
                workshop_id=ws_id,
                name=dept,
            ))

        # 匹配设备（模糊匹配工位名）
        machines = 0
        for st_name, m_count in station_machines.items():
            if station_name in st_name or st_name.replace("车间", "") in station_name:
                machines = m_count
                break

        # 生产策略：加工类 MTS，组装类 MTO
        stype = station_type_map.get(station_name, "production")
        strategy = ProductionStrategy.MTS if stype == "production" else ProductionStrategy.MTO

        # 班次：根据人数估算（>100人大概率两班倒）
        shifts = 2 if workers > 100 else 1

        sections.append(SectionConfig(
            section_id=f"SEC-{station_name}",
            name=station_name,
            workshop_id=ws_id,
            strategy=strategy,
            workers=max(1, workers // shifts),  # 单班人数
            machines=machines,
            shifts_per_day=shifts,
            hours_per_shift=8.0,
            efficiency=0.85,
            max_overtime_pct=0.2,
            yield_rate=0.97,
            role_name=station_name,
            description=f"{dept} | 在职{workers}人 | 设备{machines}台",
        ))

    # ━━━ 构建工艺路线 ━━━
    routings: List[RoutingDef] = []
    for idx, rt in enumerate(rt_rows):
        # 从 description 解析工序序列（格式: "产品类型: XX | 工序: A → B → C"）
        desc = rt[2] or ""
        ops_str = ""
        if "工序:" in desc:
            ops_str = desc.split("工序:")[-1].strip()
        elif "工序: " in desc:
            ops_str = desc.split("工序: ")[-1].strip()
        op_names = [o.strip() for o in ops_str.split("→") if o.strip()] if ops_str else []

        if op_names:
            routings.append(RoutingDef(
                routing_id=f"RT-{idx+1:03d}",
                product_name=rt[1],
                operations=[
                    {"operation_id": f"OP-{j+1:02d}", "section_id": f"SEC-{name}", "name": name, "hours": 1.0}
                    for j, name in enumerate(op_names)
                ],
            ))

    # ━━━ 构建模拟订单（基于物料规模推算） ━━━
    orders: List[OrderInput] = []
    if routings:
        # 根据物料总量和 SKU 数推算合理订单量
        base_qty = max(100, int(total_material_qty / max(1, sku_count) * 0.3)) if total_material_qty > 0 else 500
        for i, rt in enumerate(routings[:5]):
            orders.append(OrderInput(
                order_id=f"LIVE-ORD-{i+1:03d}",
                product_name=rt.product_name,
                routing_id=rt.routing_id,
                quantity=base_qty + i * 100,
                due_day=horizon_days - 2 + i,
                priority="medium",
            ))

    # ━━━ 环境/其它变量 ━━━
    # TODO: 可扩展接入温湿度、能耗等环境变量

    config = FactorySimConfig(
        factory_id=factory_id,
        factory_name=f"实时数据仿真 ({factory_id})",
        horizon_days=horizon_days,
        workshops=workshops,
        sections=sections,
        routings=routings,
        orders=orders,
    )
    return config


async def get_live_data_summary(db: AsyncSession, factory_id: str) -> Dict[str, Any]:
    """获取喂入仿真引擎的数据摘要（供前端展示'数据已接入'状态）"""
    hr = (await db.execute(sa_text(
        "SELECT count(*) FILTER (WHERE status='active') FROM hr_employees WHERE factory_id = :fid"
    ), {"fid": factory_id})).scalar()
    st = (await db.execute(sa_text(
        "SELECT count(*), COALESCE(SUM(equipment_count),0) FROM stations WHERE factory_id = :fid AND status='active'"
    ), {"fid": factory_id})).fetchone()
    inv = (await db.execute(sa_text(
        "SELECT count(*), COALESCE(SUM(total_qty),0) FROM inventory WHERE factory_id = :fid"
    ), {"fid": factory_id})).fetchone()
    rt = (await db.execute(sa_text(
        "SELECT count(*) FROM routing_templates WHERE factory_id = :fid AND is_active = true"
    ), {"fid": factory_id})).scalar()

    return {
        "factory_id": factory_id,
        "inputs": {
            "人力": {"active_workers": hr, "source": "hr_employees"},
            "设备": {"stations": st[0], "equipment_total": st[1], "source": "stations"},
            "物料": {"sku_count": inv[0], "total_quantity": inv[1], "source": "inventory"},
            "工艺": {"routing_count": rt, "source": "routing_templates"},
            "环境": {"status": "待接入", "source": "IoT/PLC"},
        },
        "ready": hr > 0 and st[0] > 0,
    }
