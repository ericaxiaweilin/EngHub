"""
Database Configuration and Session Management
数据库配置和会话管理模块
"""
from pathlib import Path
import os
from typing import AsyncGenerator
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
    AsyncEngine,
)

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


class DatabaseConfig:
    """数据库配置类"""
    
    def __init__(self):
        self.database_url = os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://enghub:enghub123@localhost:5432/enghub"
        )
        self.pool_size = int(os.getenv("DB_POOL_SIZE", "10"))
        self.max_overflow = int(os.getenv("DB_MAX_OVERFLOW", "20"))
        self.echo = os.getenv("DB_ECHO", "false").lower() == "true"
        
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None
    
    @property
    def engine(self) -> AsyncEngine:
        """获取数据库引擎 (单例模式)"""
        if self._engine is None:
            engine_kwargs = {
                "echo": self.echo,
            }
            if not self.database_url.startswith("sqlite"):
                engine_kwargs.update(
                    {
                        "pool_pre_ping": True,
                        "pool_size": self.pool_size,
                        "max_overflow": self.max_overflow,
                        "pool_recycle": 3600,
                    }
                )
            self._engine = create_async_engine(self.database_url, **engine_kwargs)
        return self._engine
    
    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        """获取会话工厂 (单例模式)"""
        if self._session_factory is None:
            self._session_factory = async_sessionmaker(
                self.engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autocommit=False,
                autoflush=False,
            )
        return self._session_factory
    
    async def init_db(self) -> None:
        """初始化数据库 (创建表等)"""
        from database.models import Base
        
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    
    async def close(self) -> None:
        """关闭数据库连接"""
        if self._engine:
            await self._engine.dispose()


# 全局数据库配置实例
db_config = DatabaseConfig()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    获取数据库会话的依赖注入函数
    用于 FastAPI 路由
    """
    async with db_config.session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_db_no_commit() -> AsyncGenerator[AsyncSession, None]:
    """
    获取数据库会话 (不自动提交)
    用于需要手动控制事务的场景
    """
    async with db_config.session_factory() as session:
        try:
            yield session
        finally:
            await session.close()
