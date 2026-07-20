"""
初始化数据库缺失表并创建默认管理员用户 (幂等)。
用法: 在后端容器内执行  python /tmp/seed_admin.py
可通过环境变量覆盖: SEED_USERNAME / SEED_PASSWORD / SEED_EMAIL / SEED_FACTORY
"""
import asyncio
import os

from database.db_config import db_config
from database.models import User
from core.auth.user_service import UserService


async def main() -> None:
    username = os.getenv("SEED_USERNAME", "admin")
    password = os.getenv("SEED_PASSWORD", "admin123")
    email = os.getenv("SEED_EMAIL", "admin@enghub.local")
    factory = os.getenv("SEED_FACTORY", "F001")

    # 仅创建 users 表 (无外键，checkfirst=True 幂等)
    async with db_config.engine.begin() as conn:
        await conn.run_sync(User.__table__.create, checkfirst=True)
    print("[seed] users table ensured")

    async with db_config.session_factory() as session:
        svc = UserService(session)
        existing = await svc.get_user_by_username(username)
        if existing:
            print(f"[seed] user '{username}' already exists, id={existing.id}")
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
        print(f"[seed] created user '{username}' id={user.id} factory={factory}")


if __name__ == "__main__":
    asyncio.run(main())
