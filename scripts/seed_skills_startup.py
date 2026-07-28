"""
启动时幂等种子：确保 skills 技能库 + hr_employee_skills 关联数据存在。
即使数据库被重建，应用启动后也会自动恢复。
"""
import logging
from sqlalchemy import text

logger = logging.getLogger("seed_skills")

# 预置分层技能库（7大类 16项）
SKILL_SEEDS = [
    ("ZL-LS", "螺丝组装", "组立", "组立工序-螺丝锁付作业"),
    ("ZL-BZ", "包装",     "组立", "组立工序-包装作业"),
    ("ZL-TS", "组装调试", "组立", "组立工序-组装与调试"),
    ("HJ-DH", "点焊",     "焊接", "焊接工序-点焊作业"),
    ("HJ-HH", "弧焊",     "焊接", "焊接工序-弧焊作业"),
    ("HJ-XH", "锡焊",     "焊接", "焊接工序-锡焊作业"),
    ("JC-WG", "外观检测", "检测", "检测工序-外观检查"),
    ("JC-CC", "尺寸检测", "检测", "检测工序-尺寸测量"),
    ("JC-GN", "功能检测", "检测", "检测工序-功能测试"),
    ("ZS-CX", "注塑成型", "注塑", "注塑工序-注塑成型"),
    ("ZS-JS", "浸塑",     "注塑", "注塑工序-浸塑作业"),
    ("JG-JJ", "精加工",   "加工", "加工工序-精密加工"),
    ("JG-GL", "滚轮加工", "加工", "加工工序-滚轮加工"),
    ("TZ-PT", "喷涂",     "涂装", "涂装工序-喷涂作业"),
    ("BZ-NB", "内包装",   "包装", "包装工序-内包装作业"),
    ("BZ-WB", "外包装",   "包装", "包装工序-外包装作业"),
]

# station → skill_code 映射（用于自动给员工赋技能）
STATION_SKILL_MAP = [
    ("焊接", "HJ-DH"), ("焊接", "HJ-HH"),
    ("组立", "ZL-LS"), ("组立", "ZL-BZ"),
    ("注塑", "ZS-CX"), ("浸塑", "ZS-JS"),
    ("精加工", "JG-JJ"), ("加工", "JG-JJ"),
    ("滚轮", "JG-GL"), ("涂装", "TZ-PT"),
    ("组装一线", "ZL-LS"), ("组装一线", "ZL-TS"),
    ("组装二线", "ZL-LS"), ("组装二线", "ZL-TS"),
    ("组装三线", "ZL-LS"), ("组装三线", "ZL-TS"),
    ("DIP-A线", "HJ-XH"), ("DIP-B线", "HJ-XH"), ("波峰焊", "HJ-XH"),
    ("包装线", "BZ-NB"), ("包装线", "BZ-WB"),
    ("FCT测试", "JC-GN"), ("ICT测试", "JC-GN"), ("老化房", "JC-GN"),
    ("IPQC巡检", "JC-WG"), ("IQC来料检", "JC-WG"), ("OQC出货检", "JC-WG"),
]


async def ensure_skills_seeded(db):
    """幂等：skills 表为空时自动种子"""
    try:
        r = await db.execute(text("SELECT COUNT(*) FROM skills"))
        count = r.scalar()
        if count and count > 0:
            return  # 已有数据，跳过

        logger.info("[seed] skills 表为空，开始自动种子...")

        # 确保 unique 约束存在（ON CONFLICT 需要）
        await db.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'skills_code_key') THEN
                    ALTER TABLE skills ADD CONSTRAINT skills_code_key UNIQUE (code);
                END IF;
            END $$;
        """))

        # 插入技能库（同时填充 skill_code/skill_name 和 code/name 兼容双列）
        for code, name, category, desc in SKILL_SEEDS:
            await db.execute(text("""
                INSERT INTO skills (skill_code, skill_name, code, name, category, description, is_active)
                VALUES (:code, :name, :code, :name, :cat, :desc, TRUE)
                ON CONFLICT (code) DO NOTHING
            """), {"code": code, "name": name, "cat": category, "desc": desc})

        await db.commit()
        logger.info(f"[seed] skills 种子完成: {len(SKILL_SEEDS)} 条")
    except Exception as e:
        await db.rollback()
        logger.warning(f"[seed] skills 种子失败: {e}")


async def ensure_employee_skills_seeded(db):
    """幂等：hr_employee_skills 表为空时，按 station 自动给员工赋技能"""
    try:
        # 检查表是否存在
        r = await db.execute(text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'hr_employee_skills')"
        ))
        if not r.scalar():
            return

        r2 = await db.execute(text("SELECT COUNT(*) FROM hr_employee_skills"))
        count = r2.scalar()
        if count and count > 0:
            return  # 已有数据

        # 检查是否有员工数据
        r3 = await db.execute(text("SELECT COUNT(*) FROM hr_employees"))
        emp_count = r3.scalar()
        if not emp_count or emp_count == 0:
            return  # 无员工，跳过

        logger.info("[seed] hr_employee_skills 为空，按 station 自动赋技能...")

        # 构建 VALUES 子句
        values_parts = ", ".join(
            f"('{station}', '{skill_code}')" for station, skill_code in STATION_SKILL_MAP
        )
        await db.execute(text(f"""
            WITH station_skill AS (
                SELECT * FROM (VALUES {values_parts}) AS m(station, skill_code)
            )
            INSERT INTO hr_employee_skills (hr_employee_id, skill_id, level, certified_date)
            SELECT e.id, s.id,
                   CASE e.skill_level
                       WHEN '初级' THEN 'L1'
                       WHEN '中级' THEN 'L2'
                       WHEN '高级' THEN 'L3'
                       WHEN '技师' THEN 'L4'
                       WHEN '高级技师' THEN 'L5'
                       ELSE COALESCE(e.skill_level, 'L1') END,
                   CURRENT_DATE - (random() * 730)::INT
            FROM hr_employees e
            JOIN station_skill ss ON ss.station = e.station
            JOIN skills s ON s.code = ss.skill_code
            ON CONFLICT (hr_employee_id, skill_id) DO NOTHING
        """))
        await db.commit()

        r4 = await db.execute(text("SELECT COUNT(*) FROM hr_employee_skills"))
        logger.info(f"[seed] 员工技能关联种子完成: {r4.scalar()} 条")
    except Exception as e:
        await db.rollback()
        logger.warning(f"[seed] employee_skills 种子失败: {e}")


async def run_skill_seed():
    """启动入口：依次执行技能库 + 员工技能种子"""
    from database.db_config import db_config
    try:
        async with db_config.session_factory() as db:
            await ensure_skills_seeded(db)
            await ensure_employee_skills_seeded(db)
    except Exception as e:
        logger.warning(f"[seed] 技能种子整体失败（不影响启动）: {e}")
