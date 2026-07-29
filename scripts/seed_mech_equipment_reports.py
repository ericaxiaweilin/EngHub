"""为机械厂(FAC_MECH_001)添加设备和生产报工种子数据"""
import asyncio
import asyncpg
import os
import uuid
from datetime import datetime

DB_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@db:5432/enghub").replace("+asyncpg", "")
FID = "FAC_MECH_001"

async def main():
    conn = await asyncpg.connect(DB_URL)
    
    # ━━ 1. 设备数据 ━━━
    print("=== 1. 创建机械设备 ===")
    await conn.execute("DELETE FROM equipment WHERE factory_id = $1", FID)
    
    EQUIPMENT_LIST = [
        ("EQ-CNC-001", "CNC加工中心-01", "ST-JJG-01", "cnc", "running"),
        ("EQ-CNC-002", "CNC加工中心-02", "ST-JJG-01", "cnc", "running"),
        ("EQ-CNC-003", "CNC加工中心-03", "ST-JJG-01", "cnc", "available"),
        ("EQ-WLD-001", "焊接机器人-01", "ST-HJ-01", "welder", "running"),
        ("EQ-WLD-002", "焊接机器人-02", "ST-HJ-01", "welder", "maintenance"),
        ("EQ-INJ-001", "注塑机-01", "ST-ZS-01", "injection", "running"),
        ("EQ-INJ-002", "注塑机-02", "ST-ZS-01", "injection", "available"),
        ("EQ-PNT-001", "涂装线-01", "ST-TZ-01", "coating", "running"),
        ("EQ-ASM-001", "组装线-01", "ST-ZL-01", "assembly", "running"),
        ("EQ-ASM-002", "组装线-02", "ST-ZL-02", "assembly", "available"),
        ("EQ-TST-001", "检测仪-01", "ST-QC-02", "tester", "running"),
        ("EQ-PKG-001", "包装机-01", "ST-PK-01", "packaging", "available"),
    ]
    
    for eq_code, eq_name, station_id, eq_type, status in EQUIPMENT_LIST:
        await conn.execute("""
            INSERT INTO equipment (code, equipment_code, equipment_name, factory_id, station_id, 
                equipment_type, status, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, NOW(), NOW())
        """, eq_code, eq_code, eq_name, FID, station_id, eq_type, status)
    print(f"  已创建 {len(EQUIPMENT_LIST)} 台设备")

    # ━━━ 2. 生产报工数据 ━━━
    print("\n=== 2. 创建生产报工记录 ===")
    
    # 获取机械工厂的在制工单
    work_orders = await conn.fetch("""
        SELECT id, work_order_code FROM work_orders 
        WHERE factory_id = $1 AND status = 'in_progress'
        LIMIT 10
    """, FID)
    
    if work_orders:
        report_count = 0
        stations = ["ST-JJG-01", "ST-HJ-01", "ST-ZS-01", "ST-TZ-01", "ST-ZL-01"]
        
        for wo in work_orders[:5]:
            for i in range(2):
                rpt_id = str(uuid.uuid4())
                rpt_code = f"RPT-MECH-{report_count+1:04d}"
                station = stations[report_count % len(stations)]
                good_qty = 100 + (report_count * 37) % 500
                defect_qty = (report_count * 7) % 20
                
                await conn.execute("""
                    INSERT INTO production_reports (id, report_code, factory_id, work_order_id,
                        station_id, good_qty, defect_qty, scrap_qty, report_type, shift,
                        operator_id, created_by, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, 0, 'normal', 'day', 'OP-001', 'admin', NOW(), NOW())
                    ON CONFLICT DO NOTHING
                """, rpt_id, rpt_code, FID, wo['id'], station, good_qty, defect_qty)
                report_count += 1
        print(f"  已创建 {report_count} 条报工记录")
    else:
        print("  ⚠️ 未找到在制工单，跳过报工数据")

    await conn.close()
    print("\n✅ 所有种子数据写入完成！")

if __name__ == "__main__":
    asyncio.run(main())
