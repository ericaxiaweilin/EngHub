"""
演示数据种子脚本（在 backend 容器内执行）
为演示厂区 FAC_ELEC_DEMO_2026 补充：
  - 设备数据（SMT 产线设备，部分 running）→ 设备稼动率
  - 生产报工（挂在在制工单上，created_at 为今天）→ 今日良品产出 / 最近报工
全部显式指定 id（避开模型 default="gen_random_uuidid()" 的字面量 bug）。
"""
import asyncio
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from database.models import Equipment, ProductionReport, WorkOrder
from database.db_config import db_config

FACTORY = "FAC_ELEC_DEMO_2026"


def _uid() -> str:
    return str(uuid.uuid4())


EQUIPMENT_SEED = [
    # (code, name, station, type, status)
    ("EQ-SMT-01", "SMT贴片机1号线", "ST-SMT-MASTER", "smt", "running"),
    ("EQ-SMT-02", "SMT贴片机2号线", "ST-SMT-MASTER", "smt", "running"),
    ("EQ-REFLOW-01", "回流焊炉", "ST-SMT-MASTER", "reflow", "running"),
    ("EQ-ASSY-01", "总装流水线", "ST-ASSY-LINE", "assembly", "running"),
    ("EQ-TEST-01", "声学全检仪", "ST-AUDIO-TEST", "test", "idle"),
    ("EQ-FLASH-01", "固件烧录机", "ST-FLASH", "flash", "idle"),
]


async def main():
    session_factory = async_sessionmaker(db_config.engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as s:
        # ---- 设备 ----
        existing_eq = (await s.execute(select(Equipment.equipment_code))).scalars().all()
        added_eq = 0
        for code, name, station, etype, status in EQUIPMENT_SEED:
            if code in existing_eq:
                continue
            s.add(Equipment(
                id=_uid(),
                equipment_code=code,
                equipment_name=name,
                factory_id=FACTORY,
                station_id=station,
                equipment_type=etype,
                status=status,
            ))
            added_eq += 1
        print(f"设备：新增 {added_eq} 台（跳过已存在 {len(EQUIPMENT_SEED) - added_eq}）")

        # ---- 报工（挂在在制工单上，时间为今天）----
        wos = (await s.execute(
            select(WorkOrder).where(WorkOrder.factory_id == FACTORY, WorkOrder.status == "in_progress")
        )).scalars().all()
        existing_rp = (await s.execute(select(ProductionReport.report_code))).scalars().all()
        now = datetime.utcnow()
        added_rp = 0
        for i, wo in enumerate(wos):
            code = f"RPT-{wo.work_order_code}-DEMO"
            if code in existing_rp:
                continue
            good = max(wo.completed_qty - 12, 50)
            s.add(ProductionReport(
                id=_uid(),
                report_code=code,
                factory_id=FACTORY,
                work_order_id=wo.id,
                station_id=wo.assigned_station_id or "ST-SMT-MASTER",
                good_qty=good,
                defect_qty=6 + i,
                scrap_qty=1,
                report_type="normal",
                shift="day",
                operator_id="OP-DEMO",
                remark="演示报工数据",
                created_by="admin",
                created_at=now,
                updated_at=now,
            ))
            added_rp += 1
        print(f"报工：新增 {added_rp} 条（挂在 {len(wos)} 张在制工单上）")

        await s.commit()

    await db_config.close()
    print("演示数据种子完成 ✅")


if __name__ == "__main__":
    asyncio.run(main())
