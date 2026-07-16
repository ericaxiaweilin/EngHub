"""
Central application settings.
"""

from __future__ import annotations

import os
from typing import Optional


def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


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

    # ---- Existing model bases -------------------------------------------------
    # model-engineering-base: OpenAI-compatible platform (/v1/chat/completions)
    # model-stack: MES domain gateway (/api/v1/chat|optimize|predict|analyze)
    # Defaults keep historical EngHub gateway host for both until split deploys.
    _DEFAULT_MODEL_HOST = "http://100.96.188.77:14041"

    MODEL_BASE_PROVIDER: str = _env(
        "MODEL_BASE_PROVIDER",
        default="auto",  # auto | model-engineering-base | model-stack
    )
    MODEL_ENGINEERING_BASE_URL: str = _env(
        "MODEL_ENGINEERING_BASE_URL",
        "LLM_GATEWAY_URL",
        "MODEL_GATEWAY_URL",
        default=_DEFAULT_MODEL_HOST,
    )
    MODEL_STACK_URL: str = _env(
        "MODEL_STACK_URL",
        "MODEL_GATEWAY_URL",
        "LLM_GATEWAY_URL",
        default=_DEFAULT_MODEL_HOST,
    )

    # Backward-compatible aliases
    LLM_GATEWAY_URL: str = _env(
        "LLM_GATEWAY_URL",
        "MODEL_ENGINEERING_BASE_URL",
        "MODEL_GATEWAY_URL",
        default=_DEFAULT_MODEL_HOST,
    )
    MODEL_GATEWAY_URL: str = _env(
        "MODEL_GATEWAY_URL",
        "MODEL_STACK_URL",
        "LLM_GATEWAY_URL",
        default=_DEFAULT_MODEL_HOST,
    )
    CHATBOT_URL: str = os.getenv("CHATBOT_URL", "http://100.96.188.77:3000")

    LLM_API_KEY: Optional[str] = os.getenv("LLM_API_KEY")
    LLM_MODEL_NAME: str = os.getenv("LLM_MODEL_NAME", "qwen-max")
    LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.3"))
    LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "2048"))
    LLM_TIMEOUT_SECONDS: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
    AGENT_MAX_TOOL_ROUNDS: int = int(os.getenv("AGENT_MAX_TOOL_ROUNDS", "6"))

    # ---- Luaguage (ERP master / engflow) --------------------------------------
    # Luaguage is the ERP system for BOM/PPAP/material master data — not an LLM.
    # Agent tools can still call it to enrich manufacturing answers.
    LUAGUAGE_BASE_URL: str = os.getenv("LUAGUAGE_BASE_URL", "http://localhost:8080")
    LUAGUAGE_API_KEY: Optional[str] = os.getenv("LUAGUAGE_API_KEY")
    LUAGUAGE_TIMEOUT_SECONDS: float = float(
        os.getenv("LUAGUAGE_TIMEOUT_SECONDS", "10")
    )
    LUAGUAGE_ENABLED: bool = os.getenv("LUAGUAGE_ENABLED", "true").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    # MCP server identity
    MCP_SERVER_NAME: str = os.getenv("MCP_SERVER_NAME", "enghub-mes")
    MCP_SERVER_VERSION: str = os.getenv("MCP_SERVER_VERSION", "1.0.0")
    MCP_PROTOCOL_VERSION: str = os.getenv("MCP_PROTOCOL_VERSION", "2024-11-05")
    DEFAULT_FACTORY_ID: str = os.getenv("DEFAULT_FACTORY_ID", "factory-001")

    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")


settings = Settings()
