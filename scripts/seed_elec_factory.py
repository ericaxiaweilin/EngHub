"""
电子厂(FAC_ELEC_DEMO_2026) 人力档案 + 两厂工单模板种子数据

电子厂典型部门/工序：
  SMT一部: SMT-A线, SMT-B线, SMT-C线
  SMT二部: SMT-D线, SMT-E线
  DIP部: DIP-A线, DIP-B线, 波峰焊
  组装部: 组装一线, 组装二线, 组装三线, 包装线
  测试部: ICT测试, FCT测试, 老化房
  品质部: IQC来料检, IPQC巡检, OQC出货检
  仓储物流: 原料仓, 成品仓, 配送

工单模板（两厂通用 + 各厂专用）：
  通用: 生产工单/返工工单/试产工单/样品工单
  机械: 精加工单/焊接单/涂装单/组立单
  电子: SMT贴片单/DIP插件单/组装单/测试单
"""
import asyncio
import asyncpg
import os
import uuid
import random
from datetime import date

DB_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@db:5432/enghub").replace("+asyncpg", "")

ELEC_FID = "FAC_ELEC_DEMO_2026"
MECH_FID = "FAC_MECH_001"

# ━━━ 电子厂人力配置 ━━━
# (department, station, headcount)
ELEC_STAFFING = [
    ("SMT一部", "SMT-A线", 45),
    ("SMT一部", "SMT-B线", 42),
    ("SMT一部", "SMT-C线", 38),
    ("SMT二部", "SMT-D线", 40),
    ("SMT二部", "SMT-E线", 35),
    ("DIP部", "DIP-A线", 55),
    ("DIP部", "DIP-B线", 48),
    ("DIP部", "波峰焊", 22),
    ("组装部", "组装一线", 65),
    ("组装部", "组装二线", 60),
    ("组装部", "组装三线", 55),
    ("组装部", "包装线", 30),
    ("测试部", "ICT测试", 25),
    ("测试部", "FCT测试", 28),
    ("测试部", "老化房", 18),
    ("品质部", "IQC来料检", 15),
    ("品质部", "IPQC巡检", 20),
    ("品质部", "OQC出货检", 12),
    ("仓储物流", "原料仓", 16),
    ("仓储物流", "成品仓", 14),
    ("仓储物流", "配送", 12),
]
# TOTAL = 753

# 中文姓名组件
SURNAMES = list("王李张刘陈杨赵黄周吴徐孙胡朱高林何郭马罗梁宋郑谢韩唐冯于董萧程曹袁邓许傅沈曾彭吕苏卢蒋蔡贾丁魏薛叶阎余潘杜戴夏钟汪田任姜范方石姚谭廖邹熊金陆郝孔白崔康毛邱秦江史顾侯邵孟龙万段漕钱汤尹黎易常武乔贺赖龚文")
GIVEN_M = list("伟强磊军洋勇杰涛超明刚建华志强成康新凯安彬斌波辉鑫鹏飞翔旭东文博浩然宇轩泽楷瑞霖")
GIVEN_F = list("芳娜敏静丽艳霞秀英玲桂淑珍雪琳晶燕蕾洁倩瑶怡欣悦婷妍茜秋珊莎锦黛青")

# ━━━ 工单模板定义 ━━━
# (template_code, template_name, wo_type, description, factory_id or None=通用)
WO_TEMPLATES_COMMON = [
    ("WO-TPL-PROD", "生产工单", "master", "标准生产工单：按BOM和工艺路线执行完整生产流程", None),
    ("WO-TPL-REWORK", "返工工单", "operation", "不良品返工：从指定工序开始重新加工", None),
    ("WO-TPL-TRIAL", "试产工单", "master", "新产品试产：小批量验证工艺可行性", None),
    ("WO-TPL-SAMPLE", "样品工单", "master", "客户样品制作：按客户规格打样", None),
    ("WO-TPL-MAINT", "设备维保单", "operation", "计划性设备维护保养", None),
]

WO_TEMPLATES_MECH = [
    ("WO-TPL-M-JJG", "精加工单", "operation", "关键零件精加工（CNC/车/铣/磨）", MECH_FID),
    ("WO-TPL-M-WELD", "焊接单", "operation", "结构件焊接（CO2/氩弧/点焊）", MECH_FID),
    ("WO-TPL-M-PAINT", "涂装单", "operation", "表面处理（喷涂/电泳/浸塑）", MECH_FID),
    ("WO-TPL-M-ASSY", "组立单", "operation", "零部件组装成成品", MECH_FID),
    ("WO-TPL-M-INJ", "注塑单", "operation", "塑料件注塑成型", MECH_FID),
]

WO_TEMPLATES_ELEC = [
    ("WO-TPL-E-SMT", "SMT贴片单", "operation", "SMT表面贴装（印刷→贴片→回流焊）", ELEC_FID),
    ("WO-TPL-E-DIP", "DIP插件单", "operation", "DIP通孔插件（插件→波峰焊→剪脚）", ELEC_FID),
    ("WO-TPL-E-ASSY", "组装单", "operation", "PCBA与结构件总装", ELEC_FID),
    ("WO-TPL-E-TEST", "测试单", "operation", "ICT/FCT功能测试+老化", ELEC_FID),
    ("WO-TPL-E-PACK", "包装单", "operation", "成品包装入库", ELEC_FID),
]


async def main():
    conn = await asyncpg.connect(DB_URL)

    # ═══════════ 1. 电子厂人力 ═══════════
    await conn.execute("DELETE FROM hr_employees WHERE factory_id = $1", ELEC_FID)
    print(f"[1] 已清理 {ELEC_FID} 旧人力数据")

    random.seed(42)
    emp_count = 0
    for dept, station, hc in ELEC_STAFFING:
        for i in range(hc):
            emp_count += 1
            code = f"ELEC-{emp_count:04d}"
            surname = random.choice(SURNAMES)
            if random.random() < 0.55:
                given = random.choice(GIVEN_M)
                gender = "男"
            else:
                given = random.choice(GIVEN_F)
                gender = "女"
            name = surname + given
            # 随机入职日期 2018-2025
            year = random.randint(2018, 2025)
            month = random.randint(1, 12)
            day = random.randint(1, 28)
            hire_date = date(year, month, day)
            # 95% active, 5% inactive
            status = "active" if random.random() < 0.95 else "inactive"
            skill = random.choice(["初级", "中级", "高级", "技师"])
            shift = random.choice(["白班", "夜班", "常白"])
            position = random.choice(["操作员", "技术员", "组长", "线长"])

            await conn.execute("""
                INSERT INTO hr_employees (id, factory_id, employee_code, name, gender, department, station, position, shift, hire_date, status, skill_level, created_at, updated_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,NOW(),NOW())
            """, str(uuid.uuid4()), ELEC_FID, code, name, gender, dept, station, position, shift, hire_date, status, skill)

    print(f"[2] 已创建电子厂 {emp_count} 名员工")

    # ═══════════ 2. 工单模板表 ═══════════
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS work_order_templates (
            id VARCHAR(36) PRIMARY KEY,
            factory_id VARCHAR(50),
            template_code VARCHAR(50) NOT NULL,
            template_name VARCHAR(100) NOT NULL,
            wo_type VARCHAR(20) DEFAULT 'master',
            description TEXT,
            default_priority INTEGER DEFAULT 3,
            default_routing_template_id VARCHAR(36),
            is_active BOOLEAN DEFAULT true,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)
    print("[3] work_order_templates 表已就绪")

    # 清理旧模板
    await conn.execute("DELETE FROM work_order_templates")

    # 通用模板 → 两个厂各一份
    tpl_count = 0
    for fid in [MECH_FID, ELEC_FID]:
        for code, name, wtype, desc, _ in WO_TEMPLATES_COMMON:
            tpl_count += 1
            await conn.execute("""
                INSERT INTO work_order_templates (id, factory_id, template_code, template_name, wo_type, description, is_active, created_at, updated_at)
                VALUES ($1,$2,$3,$4,$5,$6,true,NOW(),NOW())
            """, str(uuid.uuid4()), fid, code, name, wtype, desc)

    # 机械厂专用
    for code, name, wtype, desc, fid in WO_TEMPLATES_MECH:
        tpl_count += 1
        await conn.execute("""
            INSERT INTO work_order_templates (id, factory_id, template_code, template_name, wo_type, description, is_active, created_at, updated_at)
            VALUES ($1,$2,$3,$4,$5,$6,true,NOW(),NOW())
        """, str(uuid.uuid4()), fid, code, name, wtype, desc)

    # 电子厂专用
    for code, name, wtype, desc, fid in WO_TEMPLATES_ELEC:
        tpl_count += 1
        await conn.execute("""
            INSERT INTO work_order_templates (id, factory_id, template_code, template_name, wo_type, description, is_active, created_at, updated_at)
            VALUES ($1,$2,$3,$4,$5,$6,true,NOW(),NOW())
        """, str(uuid.uuid4()), fid, code, name, wtype, desc)

    print(f"[4] 已创建 {tpl_count} 个工单模板")

    # ═══════════ 3. 验证 ═══════════
    hr_elec = await conn.fetchval("SELECT count(*) FROM hr_employees WHERE factory_id=$1", ELEC_FID)
    hr_mech = await conn.fetchval("SELECT count(*) FROM hr_employees WHERE factory_id=$1", MECH_FID)
    tpl_mech = await conn.fetchval("SELECT count(*) FROM work_order_templates WHERE factory_id=$1", MECH_FID)
    tpl_elec = await conn.fetchval("SELECT count(*) FROM work_order_templates WHERE factory_id=$1", ELEC_FID)
    depts = await conn.fetch("SELECT DISTINCT department FROM hr_employees WHERE factory_id=$1 ORDER BY department", ELEC_FID)

    print(f"\n✅ 完成:")
    print(f"  电子厂人力: {hr_elec} 人, {len(depts)} 个部门")
    print(f"  机械厂人力: {hr_mech} 人")
    print(f"  机械厂工单模板: {tpl_mech} 个")
    print(f"  电子厂工单模板: {tpl_elec} 个")
    print(f"  电子厂部门: {[d[0] for d in depts]}")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
