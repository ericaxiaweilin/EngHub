"""
机械厂(FAC_MECH_001) 车间工位 + 工艺路线种子数据
基于人力档案的部门/工序结构：
  关键零件一部: 精加工, 滚轮, 注塑, 浸塑
  生产一部: 加工, 焊接, 涂装, 组立
  生产二部: 线材, 仪表, 機電
  哑铃(成品线)
"""
import asyncio
import asyncpg
import os
import uuid

DB_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@db:5432/enghub").replace("+asyncpg", "")
FID = "FAC_MECH_001"

# ━━━ 1. 工位/工作中心 ━━━
STATIONS = [
    # (station_code, station_name, station_type, department, capacity)
    ("ST-JJG-01", "精加工车间", "production", "关键零件一部", 66),
    ("ST-GL-01", "滚轮车间", "production", "关键零件一部", 14),
    ("ST-ZS-01", "注塑车间", "production", "关键零件一部", 26),
    ("ST-JS-01", "浸塑车间", "production", "关键零件一部", 13),
    ("ST-JG-01", "加工车间", "production", "生产一部", 164),
    ("ST-HJ-01", "焊接车间", "production", "生产一部", 218),
    ("ST-TZ-01", "涂装车间", "coating", "生产一部", 91),
    ("ST-ZL-01", "组立一线", "assembly", "生产一部", 110),
    ("ST-ZL-02", "组立二线", "assembly", "生产一部", 110),
    ("ST-ZL-03", "组立三线", "assembly", "生产一部", 110),
    ("ST-XC-01", "线材车间", "production", "生产二部", 50),
    ("ST-YB-01", "仪表车间", "assembly", "生产二部", 14),
    ("ST-JD-01", "機電车间", "assembly", "生产二部", 38),
    ("ST-YL-01", "哑铃组装线", "assembly", "哑铃", 20),
    ("ST-QC-01", "来料检验站", "test", "品质部", 8),
    ("ST-QC-02", "成品检验站", "test", "品质部", 6),
    ("ST-PK-01", "包装入库站", "packing", "物流部", 10),
]

# ━━━ 2. 工艺路线模板 ━━━
# 机械厂典型产品：哑铃、滚轮、注塑件、线材组件
ROUTINGS = [
    {
        "name": "哑铃标准工艺",
        "product_type": "哑铃",
        "steps": [
            ("精加工", "ST-JJG-01", 10, "铸铁件精加工成型"),
            ("焊接", "ST-HJ-01", 15, "握杆与铃片焊接"),
            ("涂装", "ST-TZ-01", 20, "防锈涂装+烤漆"),
            ("组立", "ST-ZL-01", 25, "组装配重+紧固"),
            ("成品检", "ST-QC-02", 30, "外观+重量全检"),
            ("包装", "ST-PK-01", 35, "包装入库"),
        ],
    },
    {
        "name": "滚轮组件工艺",
        "product_type": "滚轮",
        "steps": [
            ("注塑", "ST-ZS-01", 10, "轮体注塑成型"),
            ("精加工", "ST-JJG-01", 15, "轴承孔精加工"),
            ("浸塑", "ST-JS-01", 20, "表面浸塑处理"),
            ("组立", "ST-ZL-02", 25, "轴承+轮体组装"),
            ("成品检", "ST-QC-02", 30, "转动+尺寸检验"),
            ("包装", "ST-PK-01", 35, "包装入库"),
        ],
    },
    {
        "name": "线材组件工艺",
        "product_type": "线材",
        "steps": [
            ("线材加工", "ST-XC-01", 10, "线材裁切+剥皮"),
            ("焊接", "ST-HJ-01", 15, "端子焊接"),
            ("機電组装", "ST-JD-01", 20, "接插件组装"),
            ("仪表检测", "ST-YB-01", 25, "导通+绝缘测试"),
            ("成品检", "ST-QC-02", 30, "电气性能全检"),
            ("包装", "ST-PK-01", 35, "包装入库"),
        ],
    },
    {
        "name": "注塑件通用工艺",
        "product_type": "注塑件",
        "steps": [
            ("注塑", "ST-ZS-01", 10, "注塑成型"),
            ("加工", "ST-JG-01", 15, "去毛刺+CNC加工"),
            ("涂装", "ST-TZ-01", 20, "表面喷涂"),
            ("组立", "ST-ZL-03", 25, "零件组装"),
            ("成品检", "ST-QC-02", 30, "尺寸+外观检"),
            ("包装", "ST-PK-01", 35, "包装入库"),
        ],
    },
    {
        "name": "機電仪表工艺",
        "product_type": "仪表",
        "steps": [
            ("加工", "ST-JG-01", 10, "壳体机加工"),
            ("機電组装", "ST-JD-01", 15, "PCB+传感器安装"),
            ("仪表校准", "ST-YB-01", 20, "校准+标定"),
            ("组立", "ST-ZL-03", 25, "总装+接线"),
            ("成品检", "ST-QC-02", 30, "精度+功能检"),
            ("包装", "ST-PK-01", 35, "包装入库"),
        ],
    },
]


async def main():
    conn = await asyncpg.connect(DB_URL)

    # --- 清理工位（仅 FAC_MECH_001）---
    await conn.execute("DELETE FROM stations WHERE factory_id = $1", FID)
    print(f"[1] 已清理 {FID} 旧工位")

    # --- 插入工位 ---
    station_id_map = {}  # station_code -> id
    for code, name, stype, dept, cap in STATIONS:
        sid = str(uuid.uuid4())
        station_id_map[code] = sid
        await conn.execute("""
            INSERT INTO stations (id, factory_id, station_code, station_name, station_type, capacity, capacity_unit, equipment_count, status, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, '人', $7, 'active', NOW(), NOW())
        """, sid, FID, code, name, stype, cap, max(1, cap // 10))
    print(f"[2] 已创建 {len(STATIONS)} 个工位")

    # --- 清理旧工艺路线（仅 FAC_MECH_001）---
    old_rts = await conn.fetch("SELECT id FROM routing_templates WHERE factory_id = $1", FID)
    for ort in old_rts:
        await conn.execute("DELETE FROM routing_steps WHERE routing_id = $1", ort["id"])
    await conn.execute("DELETE FROM routing_templates WHERE factory_id = $1", FID)
    print(f"[3] 已清理 {FID} 旧工艺路线")

    # --- 插入工艺路线模板（工序步骤存入 description JSON） ---
    for idx, rt in enumerate(ROUTINGS, 1):
        rt_id = str(uuid.uuid4())
        tcode = f"RT-MECH-{idx:03d}"
        steps_desc = " → ".join(s[0] for s in rt["steps"])
        await conn.execute("""
            INSERT INTO routing_templates (id, template_code, template_name, factory_id, description, is_active, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, true, NOW(), NOW())
        """, rt_id, tcode, rt["name"], FID, f"产品类型: {rt['product_type']} | 工序: {steps_desc}")
    print(f"[4] 已创建 {len(ROUTINGS)} 条工艺路线")

    # --- 验证 ---
    st_count = await conn.fetchval("SELECT count(*) FROM stations WHERE factory_id = $1", FID)
    rt_count = await conn.fetchval("SELECT count(*) FROM routing_templates WHERE factory_id = $1", FID)
    print(f"\n✅ 完成: {FID} 工位={st_count}, 工艺路线={rt_count}")

    # ━━━ 3. 设备数据 ━━━
    print("\n=== 3. 创建机械设备 ===")
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
        eq_id = str(uuid.uuid4())
        await conn.execute("""
            INSERT INTO equipment (id, equipment_code, equipment_name, factory_id, station_id, 
                equipment_type, status, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, NOW(), NOW())
        """, eq_id, eq_code, eq_name, FID, station_id, eq_type, status)
    print(f"  已创建 {len(EQUIPMENT_LIST)} 台设备")

    # ━━━ 4. 生产报工数据 ━━
    print("\n=== 4. 创建生产报工记录 ===")
    
    # 获取今天的日期
    from datetime import datetime, timedelta
    today = datetime.utcnow().date()
    
    # 获取机械工厂的工单
    work_orders = await conn.fetch("""
        SELECT id, work_order_code FROM work_orders 
        WHERE factory_id = $1 AND status = 'in_progress'
        LIMIT 10
    """, FID)
    
    if work_orders:
        report_count = 0
        for wo in work_orders[:5]:  # 取前5个工单
            # 每个工单创建2-3条报工记录
            for i in range(2):
                rpt_id = str(uuid.uuid4())
                rpt_code = f"RPT-MECH-{report_count+1:04d}"
                # 随机选择工位
                station = STATIONS[i % len(STATIONS)][0]
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
