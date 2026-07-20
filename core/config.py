"""
配置管理模块
集中管理系统所有配置项
"""
import os
from typing import Optional


class Settings:
    """系统配置类"""
    
    # 数据库配置
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql+asyncpg://mesuser:mespassword@postgres:5432/mesdb")
    
    # 安全配置
    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-secret-key-change-in-prod")
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))
    
    # AI 服务配置 (支持 Docker 网络)
    # Docker 内访问宿主机服务：使用 host.docker.internal (需在 docker-compose 添加 extra_hosts)
    # 或直接使用 IP 地址 (如果网络可达)
    MODEL_GATEWAY_URL: str = os.getenv("MODEL_GATEWAY_URL", "http://100.96.188.77:14041")
    CHATBOT_URL: str = os.getenv("CHATBOT_URL", "http://100.96.188.77:3000")
    
    # 系统配置
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "production")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")


# 全局配置实例
settings = Settings()
