"""
Unified adapters for existing company model bases.

Supported backends:
- model-engineering-base: OpenAI-compatible LLM platform
  (/v1/chat/completions, /v1/embeddings, /v1/models)
- model-stack: MES-oriented model gateway used by EngHub
  (/api/v1/chat, /api/v1/optimize, /api/v1/predict, /api/v1/analyze, /health)

Both default to the historically configured host
http://100.96.188.77:14041 and can be overridden independently.
"""

from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import httpx

from core.config import settings

logger = logging.getLogger(__name__)


class ModelBaseProvider(str, Enum):
    AUTO = "auto"
    MODEL_ENGINEERING_BASE = "model-engineering-base"
    MODEL_STACK = "model-stack"


class ModelBaseClient:
    """
    Dual-backend client that prefers model-engineering-base for chat/tool-calling
    and can fall back to model-stack domain APIs.
    """

    def __init__(
        self,
        provider: Optional[str] = None,
        engineering_base_url: Optional[str] = None,
        model_stack_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        probe_timeout: float = 2.0,
    ) -> None:
        raw_provider = (provider or settings.MODEL_BASE_PROVIDER or "auto").lower()
        try:
            self.provider = ModelBaseProvider(raw_provider)
        except ValueError:
            self.provider = ModelBaseProvider.AUTO

        self.engineering_base_url = (
            engineering_base_url or settings.MODEL_ENGINEERING_BASE_URL
        ).rstrip("/")
        self.model_stack_url = (model_stack_url or settings.MODEL_STACK_URL).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.LLM_API_KEY
        self.model = model or settings.LLM_MODEL_NAME
        self.timeout = timeout or settings.LLM_TIMEOUT_SECONDS
        self.probe_timeout = probe_timeout
        self._clients: Dict[str, httpx.AsyncClient] = {}
        self._health_cache: Optional[Tuple[float, Dict[str, Any]]] = None
        self._health_ttl_seconds = 15.0

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def _client_for(
        self,
        base_url: str,
        timeout: Optional[float] = None,
    ) -> httpx.AsyncClient:
        key = f"{base_url}|{timeout or self.timeout}"
        client = self._clients.get(key)
        if client is None or client.is_closed:
            self._clients[key] = httpx.AsyncClient(
                base_url=base_url,
                headers=self._headers(),
                timeout=httpx.Timeout(timeout or self.timeout),
            )
        return self._clients[key]

    async def close(self) -> None:
        for client in self._clients.values():
            if not client.is_closed:
                await client.aclose()
        self._clients.clear()

    async def health(self, use_cache: bool = True) -> Dict[str, Any]:
        now = time.monotonic()
        if (
            use_cache
            and self._health_cache is not None
            and now - self._health_cache[0] < self._health_ttl_seconds
        ):
            return self._health_cache[1]

        engineering = await self._probe_engineering_base()
        stack = await self._probe_model_stack()
        selected = self._select_chat_backend(engineering["ok"], stack["ok"])
        payload = {
            "provider_setting": self.provider.value,
            "selected_chat_backend": selected,
            "model": self.model,
            "model_engineering_base": {
                "url": self.engineering_base_url,
                **engineering,
            },
            "model_stack": {
                "url": self.model_stack_url,
                **stack,
            },
        }
        self._health_cache = (now, payload)
        return payload

    async def _probe_engineering_base(self) -> Dict[str, Any]:
        client = await self._client_for(
            self.engineering_base_url, timeout=self.probe_timeout
        )
        last_error = "unreachable"
        for path in ("/health", "/v1/models"):
            try:
                response = await client.get(path)
                if response.status_code < 500:
                    return {
                        "ok": True,
                        "path": path,
                        "status_code": response.status_code,
                    }
            except httpx.HTTPError as exc:
                last_error = str(exc)
                continue
        return {"ok": False, "error": last_error}

    async def _probe_model_stack(self) -> Dict[str, Any]:
        client = await self._client_for(self.model_stack_url, timeout=self.probe_timeout)
        try:
            response = await client.get("/health")
            if response.status_code < 500:
                try:
                    body: Any = response.json()
                except Exception:
                    body = response.text
                return {
                    "ok": True,
                    "path": "/health",
                    "status_code": response.status_code,
                    "body": body,
                }
            return {"ok": False, "status_code": response.status_code}
        except httpx.HTTPError as exc:
            return {"ok": False, "error": str(exc)}

    def _select_chat_backend(self, engineering_ok: bool, stack_ok: bool) -> str:
        if self.provider == ModelBaseProvider.MODEL_ENGINEERING_BASE:
            return ModelBaseProvider.MODEL_ENGINEERING_BASE.value
        if self.provider == ModelBaseProvider.MODEL_STACK:
            return ModelBaseProvider.MODEL_STACK.value
        if engineering_ok:
            return ModelBaseProvider.MODEL_ENGINEERING_BASE.value
        if stack_ok:
            return ModelBaseProvider.MODEL_STACK.value
        return ModelBaseProvider.MODEL_ENGINEERING_BASE.value

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        # Prefer try/fallback over probing on every chat turn.
        if self.provider == ModelBaseProvider.MODEL_STACK:
            result = await self._chat_via_model_stack(messages)
            result["backend"] = ModelBaseProvider.MODEL_STACK.value
            return result

        result = await self._chat_via_engineering_base(
            messages=messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model,
        )
        if not result.get("fallback"):
            result["backend"] = ModelBaseProvider.MODEL_ENGINEERING_BASE.value
            return result

        if self.provider == ModelBaseProvider.AUTO:
            stack_result = await self._chat_via_model_stack(messages)
            stack_result["backend"] = ModelBaseProvider.MODEL_STACK.value
            return stack_result
        return result

    async def _chat_via_engineering_base(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        client = await self._client_for(self.engineering_base_url)
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
            data = response.json()
            data["backend"] = ModelBaseProvider.MODEL_ENGINEERING_BASE.value
            return data
        except httpx.HTTPError as exc:
            logger.warning("model-engineering-base chat failed: %s", exc)
            return {"error": str(exc), "fallback": True}

    async def _chat_via_model_stack(
        self,
        messages: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        model-stack historically exposes /api/v1/chat rather than tool-calling.
        Convert to an OpenAI-like response so the agent loop can continue.
        """
        client = await self._client_for(self.model_stack_url)
        user_text = ""
        for item in reversed(messages):
            if item.get("role") == "user" and item.get("content"):
                user_text = str(item["content"])
                break
        payload = {
            "user_id": "enghub-agent",
            "message": user_text,
            "context": {"messages": messages, "source": "enghub-agent"},
        }
        try:
            response = await client.post("/api/v1/chat", json=payload)
            response.raise_for_status()
            data = response.json()
            content = (
                data.get("response")
                or data.get("message")
                or data.get("content")
                or data.get("reply")
                or str(data)
            )
            return {
                "id": data.get("id", "model-stack-chat"),
                "model": self.model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "raw": data,
                "backend": ModelBaseProvider.MODEL_STACK.value,
            }
        except httpx.HTTPError as exc:
            logger.warning("model-stack chat failed: %s", exc)
            return {"error": str(exc), "fallback": True}

    async def optimize_schedule(
        self,
        work_orders: List[Dict[str, Any]],
        constraints: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        return await self._stack_task(
            "/api/v1/optimize",
            {
                "task": "schedule_optimization",
                "data": {"work_orders": work_orders, "constraints": constraints},
            },
        )

    async def predict_defects(
        self,
        process_params: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        return await self._stack_task(
            "/api/v1/predict",
            {"task": "defect_prediction", "data": process_params},
        )

    async def analyze_quality(
        self,
        inspection_data: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        return await self._stack_task(
            "/api/v1/analyze",
            {"task": "quality_analysis", "data": inspection_data},
        )

    async def _stack_task(
        self,
        endpoint: str,
        payload: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        client = await self._client_for(self.model_stack_url)
        try:
            response = await client.post(endpoint, json=payload)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict):
                    data["backend"] = ModelBaseProvider.MODEL_STACK.value
                return data
            logger.warning(
                "model-stack %s failed: %s %s",
                endpoint,
                response.status_code,
                response.text[:200],
            )
            return None
        except httpx.HTTPError as exc:
            logger.warning("model-stack %s error: %s", endpoint, exc)
            return None


_CLIENT: Optional[ModelBaseClient] = None


def get_model_base_client() -> ModelBaseClient:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = ModelBaseClient()
    return _CLIENT
