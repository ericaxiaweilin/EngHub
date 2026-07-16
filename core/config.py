"""
Central application settings.
"""

from __future__ import annotations

import os
from typing import Optional


class Settings:
    """Runtime configuration loaded from environment variables."""

    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://mesuser:mespassword@postgres:5432/mesdb",
    )

    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-secret-key-change-in-prod")
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(
        os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440")
    )

    # OpenAI-compatible LLM gateway (works with Codex / Qwen / local proxies)
    LLM_GATEWAY_URL: str = os.getenv(
        "LLM_GATEWAY_URL",
        os.getenv("MODEL_GATEWAY_URL", "http://100.96.188.77:14041"),
    )
    LLM_API_KEY: Optional[str] = os.getenv("LLM_API_KEY")
    LLM_MODEL_NAME: str = os.getenv("LLM_MODEL_NAME", "qwen-max")
    LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.3"))
    LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "2048"))
    LLM_TIMEOUT_SECONDS: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
    AGENT_MAX_TOOL_ROUNDS: int = int(os.getenv("AGENT_MAX_TOOL_ROUNDS", "6"))

    # Legacy aliases used by older AI gateway proxy code
    MODEL_GATEWAY_URL: str = os.getenv(
        "MODEL_GATEWAY_URL",
        "http://100.96.188.77:14041",
    )
    CHATBOT_URL: str = os.getenv("CHATBOT_URL", "http://100.96.188.77:3000")

    # MCP server identity
    MCP_SERVER_NAME: str = os.getenv("MCP_SERVER_NAME", "enghub-mes")
    MCP_SERVER_VERSION: str = os.getenv("MCP_SERVER_VERSION", "1.0.0")
    MCP_PROTOCOL_VERSION: str = os.getenv("MCP_PROTOCOL_VERSION", "2024-11-05")
    DEFAULT_FACTORY_ID: str = os.getenv("DEFAULT_FACTORY_ID", "factory-001")

    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")


settings = Settings()
