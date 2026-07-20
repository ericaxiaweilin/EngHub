"""
MES 生产专家系统配置模块
"""
from pydantic_settings import BaseSettings
from typing import Optional


class ExpertSystemSettings(BaseSettings):
    """生产专家系统配置"""
    
    # LLM 网关配置
    LLM_GATEWAY_URL: str = "http://100.96.188.77:14041"
    LLM_API_KEY: Optional[str] = None
    LLM_MODEL_NAME: str = "qwen-max"  # 默认模型
    
    # RAG 知识库配置
    VECTOR_STORE_PATH: str = "./data/vector_store"
    CHUNK_SIZE: int = 512
    CHUNK_OVERLAP: int = 50
    
    # 专家系统行为配置
    MAX_CONTEXT_LENGTH: int = 4096
    TEMPERATURE: float = 0.3  # 较低温度保证专业性
    MAX_TOKENS: int = 2048
    
    # 工具调用配置
    ENABLE_TOOL_CALLING: bool = True
    TOOL_TIMEOUT: int = 30  # 秒
    
    # 日志与监控
    LOG_LEVEL: str = "INFO"
    ENABLE_TRACE: bool = True
    
    class Config:
        env_file = ".env"
        case_sensitive = False


settings = ExpertSystemSettings()
