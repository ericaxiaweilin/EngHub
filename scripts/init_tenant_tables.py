"""
初始化多租户相关表并回填数据 (幂等)。
- 创建 factories / user_invitations / users 表 (无跨表外键，checkfirst=True)
- 确保默认租户 F001 存在
- 确保默认管理员 admin 存在并归属 F001

用法: 在后端容器内执行  python /tmp/init_tenant_tables.py
可通过环境变量覆盖: SEED_USERNAME / SEED_PASSWORD / SEED_EMAIL / SEED_FACTORY
"""
import asyncio
import os

from database.db_config import db_config
from database.models import User, Factory, UserInvitation
from core.auth.user_service import UserService


async def main() -> None:
    username = os.getenv("SEED_USERNAME", "admin")
    password = os.getenv("SEED_PASSWORD", "admin123")
    email = os.getenv("SEED_EMAIL", "admin@enghub.local")
    factory = os.getenv("SEED_FACTORY", "F001")

    # 仅创建这几张无跨表外键的表 (checkfirst=True 幂等)
    async with db_config.engine.begin() as conn:
        for table in (Factory.__table__, UserInvitation.__table__, User.__table__):
            await conn.run_sync(table.create, checkfirst=True)
    print("[init] factories / user_invitations / users tables ensured")

    async with db_config.session_factory() as session:
        svc = UserService(session)

        # 确保默认租户存在
        existing_factory = await svc.get_factory(factory)
        if not existing_factory:
            await svc.create_factory(factory, name="默认厂区")
            print(f"[init] created factory '{factory}'")
        else:
            print(f"[init] factory '{factory}' already exists")

        # 确保默认管理员存在 (超管，可跨租户)
        existing = await svc.get_user_by_username(username)
        if existing:
            print(f"[init] user '{username}' already exists, id={existing.id}")
            return
        user = await svc.create_user(
            username=username,
            email=email,
            password=password,
            full_name="系统管理员",
            factory_id=factory,
            role="admin",
            is_superuser=True,
        )
        print(f"[init] created user '{username}' id={user.id} factory={factory}")


if __name__ == "__main__":
    asyncio.run(main())
