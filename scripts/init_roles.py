"""
初始化角色权限数据脚本
用于首次部署时创建默认角色和权限记录
"""
import asyncio
import sys
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# 数据库连接 URL (根据实际情况修改)
DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/mes_db"


async def init_roles_and_permissions():
    """初始化角色和权限"""
    
    # 创建数据库引擎
    engine = create_async_engine(DATABASE_URL, echo=True)
    
    # 创建会话
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        # 导入需要的模块
        from database.models import Base, Role, Permission
        from core.auth.roles import ROLE_DEFINITIONS, SYSTEM_ROLES, MODULES, ACTIONS
        
        # 创建表（如果不存在）
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        # 1. 初始化权限记录
        print("正在初始化权限记录...")
        perm_count = 0
        for module, module_name in MODULES.items():
            for action, action_name in ACTIONS.items():
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
        
        # 2. 初始化系统角色
        print("正在初始化系统角色...")
        system_role_count = 0
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
            system_role_count += 1
        
        await session.commit()
        print(f"✓ 已创建 {system_role_count} 条系统角色")
        
        # 3. 初始化业务角色
        print("正在初始化业务角色...")
        business_role_count = 0
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
            business_role_count += 1
        
        await session.commit()
        print(f"✓ 已创建 {business_role_count} 条业务角色")
        
        # 4. 汇总统计
        total_roles = await session.execute(Role.__table__.select())
        total_perms = await session.execute(Permission.__table__.select())
        print("\n" + "=" * 50)
        print(f"初始化完成!")
        print(f"  角色总数: {len(total_roles.scalars().all())}")
        print(f"  权限总数: {len(total_perms.scalars().all())}")
        print("=" * 50)


if __name__ == "__main__":
    print("=" * 50)
    print("MES System - 角色权限初始化")
    print("=" * 50)
    
    try:
        asyncio.run(init_roles_and_permissions())
    except Exception as e:
        print(f"✗ 初始化失败: {e}")
        sys.exit(1)
