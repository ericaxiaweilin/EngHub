#!/usr/bin/env python3
"""
EngHub MES 完整初始化脚本
- 创建数据库表
- 初始化权限和角色
- 创建默认管理员账户
- 创建示例用户（含不同角色）

用法:
    python scripts/init_all.py

环境变量:
    DATABASE_URL: 数据库连接 URL (默认: postgresql+asyncpg://enghub:enghub123@localhost:5432/enghub)
"""
import asyncio
import sys
import os
from datetime import datetime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.models import Base, User, Role, Permission, UserRole
from core.auth.security import get_password_hash
from core.auth.roles import ROLE_DEFINITIONS, SYSTEM_ROLES, DEFAULT_ROLE_MAP, POSITION_NAMES


# 数据库连接 URL (根据实际情况修改)
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://enghub:enghub123@localhost:5432/enghub")


async def init_all():
    """完整初始化流程"""
    
    # 创建数据库引擎
    engine = create_async_engine(DATABASE_URL, echo=False)
    
    # 创建会话
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    print("=" * 60)
    print("EngHub MES - 系统初始化")
    print("=" * 60)
    print(f"数据库: {DATABASE_URL.split('@')[-1] if '@' in DATABASE_URL else 'unknown'}")
    print()
    
    async with async_session() as session:
        # 1. 创建所有表
        print("[1/5] 创建数据库表...")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print("✓ 表创建完成")
        
        # 2. 初始化权限记录
        print("\n[2/5] 初始化权限记录...")
        perm_count = 0
        for module, module_name in __import__('core.auth.roles', fromlist=['MODULES']).MODULES.items():
            for action, action_name in __import__('core.auth.roles', fromlist=['ACTIONS']).ACTIONS.items():
                existing = await session.execute(
                    Permission.__table__.select().where(
                        Permission.module == module,
                        Permission.action == action,
                    )
                )
                if existing.scalar_one_or_none():
                    continue
                
                perm = Permission(
                    module=module,
                    action=action,
                    module_name=module_name,
                    action_name=action_name,
                    description=f"{module_name} - {action_name}",
                )
                session.add(perm)
                perm_count += 1
        
        await session.commit()
        print(f"✓ 已创建 {perm_count} 条权限记录")
        
        # 3. 初始化角色
        print("\n[3/5] 初始化角色...")
        role_count = 0
        
        # 系统角色
        for code, role_def in SYSTEM_ROLES.items():
            existing = await session.execute(
                Role.__table__.select().where(Role.role_code == code)
            )
            if existing.scalar_one_or_none():
                continue
            
            role = Role(
                role_code=code,
                role_name=role_def["name"],
                position=role_def["position"],
                department=role_def.get("department", "all"),
                description=role_def.get("description", ""),
                is_system=True,
                level=role_def.get("level", 100),
                permissions=role_def.get("permissions", []),
                data_scope=role_def.get("data_scope", {"type": "all"}),
            )
            session.add(role)
            role_count += 1
        
        # 业务角色
        for role_def in ROLE_DEFINITIONS:
            existing = await session.execute(
                Role.__table__.select().where(Role.role_code == role_def["code"])
            )
            if existing.scalar_one_or_none():
                continue
            
            role = Role(
                role_code=role_def["code"],
                role_name=role_def["name"],
                position=role_def["position"],
                department=role_def.get("department", "all"),
                description=role_def.get("description", ""),
                is_system=False,
                level=role_def.get("level", 999),
                permissions=role_def.get("permissions", []),
                data_scope=role_def.get("data_scope", {"type": "own"}),
            )
            session.add(role)
            role_count += 1
        
        await session.commit()
        print(f"✓ 已创建 {role_count} 条角色记录")
        
        # 4. 创建默认管理员账户
        print("\n[4/5] 创建默认管理员账户...")
        user_service_check = await session.execute(
            User.__table__.select().where(User.username == "admin")
        )
        if not user_service_check.scalar_one_or_none():
            admin_role = await session.execute(
                Role.__table__.select().where(Role.role_code == "admin")
            )
            admin_role_obj = admin_role.scalar_one_or_none()
            
            admin_user = User(
                username="admin",
                email="admin@enghub.com",
                hashed_password=get_password_hash("admin123"),
                full_name="系统管理员",
                factory_id=None,
                role="admin",
                role_id=admin_role_obj if admin_role_obj else None,
                is_active=True,
                is_superuser=True,
            )
            session.add(admin_user)
            await session.commit()
            print("✓ 管理员账户已创建:")
            print("    用户名: admin")
            print("    密码: admin123")
            print("    角色: 系统管理员 (admin)")
        else:
            print("✓ 管理员账户已存在，跳过")
        
        # 5. 创建示例用户（可选）
        print("\n[5/5] 创建示例用户...")
        
        sample_users = [
            {
                "username": "factory_manager",
                "email": "factory@enghub.com",
                "password": "enghub123",
                "full_name": "王厂长",
                "role": "factory_manager",
                "factory_id": "factory-sh-01",
            },
            {
                "username": "production_manager",
                "email": "pm@enghub.com",
                "password": "enghub123",
                "full_name": "李生产经理",
                "role": "production_manager",
                "factory_id": "factory-sh-01",
            },
            {
                "username": "quality_manager",
                "email": "qm@enghub.com",
                "password": "enghub123",
                "full_name": "张品质经理",
                "role": "quality_manager",
                "factory_id": "factory-sh-01",
            },
            {
                "username": "line_leader_01",
                "email": "ll01@enghub.com",
                "password": "enghub123",
                "full_name": "陈线长",
                "role": "line_leader",
                "factory_id": "factory-sh-01",
            },
            {
                "username": "operator_01",
                "email": "op01@enghub.com",
                "password": "enghub123",
                "full_name": "刘操作员",
                "role": "operator",
                "factory_id": "factory-sh-01",
            },
            {
                "username": "eric",
                "email": "eric@enghub.com",
                "password": "enghub123",
                "full_name": "Eric",
                "role": "operator",
                "factory_id": "factory-sh-01",
            },
        ]
        
        created_count = 0
        for user_data in sample_users:
            existing = await session.execute(
                User.__table__.select().where(User.username == user_data["username"])
            )
            if existing.scalar_one_or_none():
                continue
            
            # 查找对应角色
            role_result = await session.execute(
                Role.__table__.select().where(Role.role_code == user_data["role"])
            )
            role_obj = role_result.scalar_one_or_none()
            
            user = User(
                username=user_data["username"],
                email=user_data["email"],
                hashed_password=get_password_hash(user_data["password"]),
                full_name=user_data["full_name"],
                factory_id=user_data["factory_id"],
                role=user_data["role"],
                role_id=role_obj if role_obj else None,
                is_active=True,
                is_superuser=False,
            )
            session.add(user)
            created_count += 1
        
        await session.commit()
        print(f"✓ 已创建 {created_count} 个示例用户")
        
        # 汇总统计
        total_users = await session.execute(User.__table__.select())
        total_roles = await session.execute(Role.__table__.select())
        total_perms = await session.execute(Permission.__table__.select())
        
        print("\n" + "=" * 60)
        print("初始化完成!")
        print(f"  用户总数: {len(total_users.scalars().all())}")
        print(f"  角色总数: {len(total_roles.scalars().all())}")
        print(f"  权限总数: {len(total_perms.scalars().all())}")
        print("=" * 60)
        
        # 打印登录信息
        print("\n📋 登录信息:")
        print("-" * 60)
        print("管理员:")
        print("  用户名: admin")
        print("  密码: admin123")
        print("  角色: 系统管理员")
        print()
        print("示例用户:")
        for u in sample_users[:5]:
            print(f"  用户名: {u['username']} | 密码: enghub123 | 角色: {u['role']}")
        print("-" * 60)
        print()
        print("⚠️  请在使用后修改默认密码！")
        print()


if __name__ == "__main__":
    try:
        asyncio.run(init_all())
    except Exception as e:
        print(f"\n✗ 初始化失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
