#!/usr/bin/env python3
"""
初始化管理员用户脚本
用于创建默认的 admin 超级管理员账户
"""
import asyncio
import sys
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from database.models import Base, User
from core.auth.user_service import UserService


# 数据库连接 URL (根据实际情况修改)
DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/mes_db"


async def init_admin_user():
    """初始化管理员用户"""
    
    # 创建数据库引擎
    engine = create_async_engine(DATABASE_URL, echo=True)
    
    # 创建表
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # 创建会话
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        user_service = UserService(session)
        
        # 检查是否已存在 admin 用户
        admin = await user_service.get_user_by_username("admin")
        
        if admin:
            print("✓ Admin user already exists")
            return
        
        # 创建 admin 用户
        try:
            admin_user = await user_service.create_user(
                username="admin",
                email="admin@example.com",
                password="admin123",  # 请在使用后修改密码
                full_name="System Administrator",
                role="admin",
                is_superuser=True,
            )
            
            print(f"✓ Admin user created successfully!")
            print(f"  Username: admin")
            print(f"  Password: admin123")
            print(f"  Email: admin@example.com")
            print(f"\n⚠️  WARNING: Please change the default password after first login!")
            
        except Exception as e:
            print(f"✗ Failed to create admin user: {e}")
            sys.exit(1)


if __name__ == "__main__":
    print("=" * 50)
    print("MES System - Admin User Initialization")
    print("=" * 50)
    
    asyncio.run(init_admin_user())
