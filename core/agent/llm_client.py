"""
OpenAI-compatible LLM gateway client used by the manufacturing agent.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from core.config import settings

logger = logging.getLogger(__name__)


class LLMGatewayClient:
    """Thin async client for /v1/chat/completions style gateways."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        self.base_url = (base_url or settings.LLM_GATEWAY_URL).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.LLM_API_KEY
        self.model = model or settings.LLM_MODEL_NAME
        self.timeout = timeout or settings.LLM_TIMEOUT_SECONDS
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=httpx.Timeout(self.timeout),
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        client = await self._get_client()
        payload: Dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "temperature": (
                settings.LLM_TEMPERATURE if temperature is None else temperature
            ),
            "max_tokens": settings.LLM_MAX_TOKENS if max_tokens is None else max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        try:
            response = await client.post("/v1/chat/completions", json=payload)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            logger.warning("LLM gateway request failed: %s", exc)
            return {"error": str(exc), "fallback": True}

    async def health_check(self) -> bool:
        client = await self._get_client()
        try:
            response = await client.get("/health")
            if response.status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        try:
            # Some OpenAI-compatible proxies expose models instead of /health.
            response = await client.get("/v1/models")
            return response.status_code < 500
        except httpx.HTTPError:
            return False
