"""
LLM client backed by company model bases (model-engineering-base / model-stack).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.model_base import ModelBaseClient, get_model_base_client


class LLMGatewayClient:
    """
    Agent-facing LLM client.

    Delegates to ModelBaseClient so EngHub can use:
    - model-engineering-base for OpenAI-compatible tool calling
    - model-stack for MES domain chat / optimize / predict APIs
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        model_base: Optional[ModelBaseClient] = None,
    ) -> None:
        if model_base is not None:
            self._model_base = model_base
        else:
            # Allow overrides while still sharing dual-backend behavior.
            self._model_base = ModelBaseClient(
                engineering_base_url=base_url,
                model_stack_url=base_url,
                api_key=api_key,
                model=model,
                timeout=timeout,
            ) if any(v is not None for v in (base_url, api_key, model, timeout)) else get_model_base_client()

    @property
    def model(self) -> str:
        return self._model_base.model

    @property
    def base_url(self) -> str:
        return self._model_base.engineering_base_url

    async def close(self) -> None:
        await self._model_base.close()

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await self._model_base.chat_completion(
            messages=messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model,
        )

    async def health_check(self) -> bool:
        status = await self._model_base.health()
        return bool(
            status["model_engineering_base"]["ok"] or status["model_stack"]["ok"]
        )

    async def backend_status(self) -> Dict[str, Any]:
        return await self._model_base.health()
