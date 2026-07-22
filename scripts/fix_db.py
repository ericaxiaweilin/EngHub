"""
DB 修复迁移脚本（在 backend 容器内执行: python -m scripts.fix_db 或 python scripts/fix_db.py）

背景：线上旧库业务表主键为 VARCHAR，新 models.py 用 UUID，且缺大量新表。
本脚本做四件事：
1. 给已存在的表补上 models.py 期望但线上缺失的列（纯 ADD COLUMN，零风险）
2. 创建缺失的表：UUID 列统一转为 String(36)、剥离外键约束（绕过 uuid/varchar FK 类型不兼容）
   —— ORM 的 UUID(as_uuid=True) 读写 varchar 列完全兼容，JOIN 时 varchar=varchar 也成立
3. 注册演示工厂 + admin 工厂对齐 + 重置 admin 密码为 admin123
4. ORM 读取自检（WorkOrder/Station/Routing/User）
"""
import asyncio

import bcrypt
from sqlalchemy import String, text, inspect, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from database.models import Base
from database.db_config import db_config


def _hash(password: str) -> str:
    """与 core/auth/security.get_password_hash 一致的 bcrypt 哈希"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


# 1) 补列（IF NOT EXISTS 保证幂等）
ALTER_STATEMENTS = [
    # users: role_id 必须存在（否则 SELECT users 失败），保持 NULL 以不触发 roles 关联查询
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS role_id VARCHAR(36)",
    # stations: 模型期望 capacity_per_hour / equipment_ids
    "ALTER TABLE stations ADD COLUMN IF NOT EXISTS capacity_per_hour INTEGER DEFAULT 0",
    "ALTER TABLE stations ADD COLUMN IF NOT EXISTS equipment_ids JSONB DEFAULT '[]'::jsonb",
    # routings: 模型期望 routing_code / steps / is_active
    "ALTER TABLE routings ADD COLUMN IF NOT EXISTS routing_code VARCHAR(50)",
    "ALTER TABLE routings ADD COLUMN IF NOT EXISTS steps JSONB DEFAULT '[]'::jsonb",
    "ALTER TABLE routings ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE",
    # 回填 routing_code，避免 NULL（模型声明 unique not null，但此处不强制约束）
    "UPDATE routings SET routing_code = 'RT-' || substr(id, 1, 24) WHERE routing_code IS NULL",
]


async def main():
    engine = db_config.engine

    # ---- 1. 补缺列 ----
    async with engine.begin() as conn:
        for stmt in ALTER_STATEMENTS:
            await conn.execute(text(stmt))
    print("[1/4] 已补齐缺失列 (users.role_id / stations / routings)")

    # ---- 2. 创建缺失表 ----
    async with engine.connect() as conn:
        existing = set(await conn.run_sync(lambda sc: inspect(sc).get_table_names()))
    missing = [t for name, t in Base.metadata.tables.items() if name not in existing]
    print(f"      线上已有 {len(existing)} 张表；缺失 {len(missing)} 张: {sorted(t.name for t in missing)}")

    for table in missing:
        # 剥离外键约束（含列级与表级）
        for fk in list(table.foreign_key_constraints):
            table.constraints.discard(fk)
        for col in table.columns:
            col.foreign_keys.clear()
            # UUID -> String(36)，与旧库 varchar 主键风格统一，保证 JOIN 类型一致
            if isinstance(col.type, UUID):
                col.type = String(36)

    async with engine.begin() as conn:
        # checkfirst=True（默认）：已存在的表自动跳过
        await conn.run_sync(Base.metadata.create_all)
    print("[2/4] 缺失表创建完成（无 FK，id 统一 varchar(36)）")

    # ---- 3. 演示工厂 + 用户对齐 + admin 密码 ----
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO factories (id, name, is_active, created_at) "
            "SELECT 'FAC_MECH_DEMO_2026', '精密机械厂', TRUE, NOW() "
            "WHERE NOT EXISTS (SELECT 1 FROM factories WHERE id = 'FAC_MECH_DEMO_2026')"
        ))
        await conn.execute(text(
            "INSERT INTO factories (id, name, is_active, created_at) "
            "SELECT 'FAC_ELEC_DEMO_2026', '电子SMT厂', TRUE, NOW() "
            "WHERE NOT EXISTS (SELECT 1 FROM factories WHERE id = 'FAC_ELEC_DEMO_2026')"
        ))
        # admin 对齐到电子SMT厂（有 3 张在制工单，便于看板展示）
        await conn.execute(text(
            "UPDATE users SET factory_id = 'FAC_ELEC_DEMO_2026' WHERE username = 'admin'"
        ))
        # 重置 admin 密码为 admin123
        await conn.execute(
            text("UPDATE users SET hashed_password = :pw WHERE username = 'admin'"),
            {"pw": _hash("admin123")},
        )
    print("[3/4] 演示工厂已注册；admin.factory_id -> FAC_ELEC_DEMO_2026；admin 密码已重置为 admin123")

    # ---- 4. ORM 读取自检 ----
    from database.models import WorkOrder, Station, Routing, User
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as s:
        wos = (await s.execute(select(WorkOrder).limit(3))).scalars().all()
        print(f"[4/4] WorkOrder ORM OK: 取样 {len(wos)} 条"
              + (f"，首条={wos[0].work_order_code} / {wos[0].factory_id} / {wos[0].status}" if wos else ""))
        sts = (await s.execute(select(Station).limit(3))).scalars().all()
        print(f"      Station  ORM OK: 取样 {len(sts)} 条")
        rts = (await s.execute(select(Routing).limit(3))).scalars().all()
        print(f"      Routing  ORM OK: 取样 {len(rts)} 条")
        us = (await s.execute(select(User).where(User.username == "admin"))).scalars().all()
        if us:
            print(f"      User     ORM OK: admin.factory_id={us[0].factory_id}, superuser={us[0].is_superuser}")

    await db_config.close()
    print("\n全部完成 ✅")


if __name__ == "__main__":
    asyncio.run(main())
