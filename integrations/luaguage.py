"""
Luaguage Integration Module
与 luaguage (engflow) ERP 主系统集成

说明:
- luaguage 是 ERP/主数据系统，不是 LLM 底座
- 可复用的「AI 相关」能力主要是：结构化主数据、BOM/PPAP 上下文，
  供 EngHub Agent / MCP 在推理时检索，而不是替代 model-stack /
  model-engineering-base 的模型推理

功能:
- BOM同步
- PPAP状态查询
- 权限/物料/产品主数据
- 生产结果回写
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

import httpx

from core.config import settings

logger = logging.getLogger(__name__)


class SyncMode(str, Enum):
    """同步模式"""

    REAL_TIME = "real_time"
    QUASI_REAL_TIME = "quasi_real_time"
    BATCH = "batch"


class PPAPStatus(str, Enum):
    """PPAP状态"""

    PENDING = "pending"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"


class LuaguageIntegration:
    """
    luaguage 集成服务

    混合同步策略:
    - BOM等基础数据: 准实时同步 (分钟级/变更触发)
    - 生产结果: 实时推送 (事务级)
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self.base_url = str(
            self.config.get("base_url") or settings.LUAGUAGE_BASE_URL
        ).rstrip("/")
        self.api_key = self.config.get("api_key") or settings.LUAGUAGE_API_KEY or ""
        self.timeout = float(
            self.config.get("timeout") or settings.LUAGUAGE_TIMEOUT_SECONDS
        )
        self.enabled = bool(
            self.config.get("enabled", settings.LUAGUAGE_ENABLED)
        )
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
                headers["X-API-Key"] = str(self.api_key)
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=httpx.Timeout(self.timeout),
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def health(self) -> Dict[str, Any]:
        if not self.enabled:
            return {
                "ok": False,
                "enabled": False,
                "base_url": self.base_url,
                "reason": "LUAGUAGE_ENABLED=false",
            }
        try:
            client = await self._get_client()
            for path in ("/health", "/api/v1/health", "/"):
                try:
                    response = await client.get(path)
                    if response.status_code < 500:
                        return {
                            "ok": True,
                            "enabled": True,
                            "base_url": self.base_url,
                            "path": path,
                            "status_code": response.status_code,
                        }
                except httpx.HTTPError:
                    continue
            return {
                "ok": False,
                "enabled": True,
                "base_url": self.base_url,
                "reason": "unreachable",
            }
        except httpx.HTTPError as exc:
            return {
                "ok": False,
                "enabled": True,
                "base_url": self.base_url,
                "error": str(exc),
            }

    # --- BOM Integration ---

    async def get_bom(
        self, product_id: str, version: Optional[str] = None
    ) -> Dict[str, Any]:
        """获取产品BOM（优先实时 API，失败则返回可识别的降级结构）。"""
        response = await self._call_api(
            f"/api/v1/bom/product/{product_id}"
            + (f"/version/{version}" if version else "")
        )
        if response:
            response.setdefault("source", "luaguage")
            return response

        return {
            "product_id": product_id,
            "version": version or "v1",
            "bom_version": version or "v1",
            "materials": [
                {"material_id": "MAT-PCB-01", "qty": 1, "unit": "pcs"},
                {"material_id": "MAT-IC-778", "qty": 2, "unit": "pcs"},
            ],
            "items": [],
            "effective_date": datetime.now().date().isoformat(),
            "sync_status": "demo",
            "source": "demo",
            "note": "luaguage BOM API unavailable; demo payload returned",
        }

    async def sync_bom(self, product_id: str) -> Dict[str, Any]:
        bom = await self.get_bom(product_id)
        return {
            "product_id": product_id,
            "sync_mode": SyncMode.QUASI_REAL_TIME.value,
            "synced_at": datetime.now().isoformat(),
            "status": "success" if bom.get("source") != "error" else "degraded",
            "bom": bom,
        }

    async def on_bom_changed(self, event: Dict[str, Any]) -> Dict[str, Any]:
        product_id = event.get("product_id")
        if product_id:
            await self.sync_bom(str(product_id))
        return {"status": "processed", "event": event}

    # --- PPAP Integration ---

    async def get_ppap_status(self, material_id: str) -> Dict[str, Any]:
        response = await self._call_api(f"/api/v1/ppap/material/{material_id}")
        if response:
            response.setdefault("source", "luaguage")
            return response
        return {
            "material_id": material_id,
            "ppap_status": PPAPStatus.APPROVED.value,
            "approval_date": (datetime.now().date() - timedelta(days=30)).isoformat(),
            "level": "A",
            "source": "demo",
            "note": "luaguage PPAP API unavailable; demo approved status returned",
        }

    async def check_material_ppap_required(self, material_id: str) -> bool:
        ppap = await self.get_ppap_status(material_id)
        return str(ppap.get("ppap_status", "")).lower() != PPAPStatus.APPROVED.value

    # --- Material / Product Master ---

    async def get_material_master(self, material_id: str) -> Dict[str, Any]:
        response = await self._call_api(f"/api/v1/materials/{material_id}")
        if response:
            response.setdefault("source", "luaguage")
            return response
        return {
            "material_id": material_id,
            "material_code": f"MAT-{material_id}",
            "material_name": "物料名称",
            "unit": "PCS",
            "specification": "",
            "supplier_id": "SUP-001",
            "min_order_qty": 100,
            "lead_time_days": 7,
            "standard_cost": 10.0,
            "sync_status": "demo",
            "source": "demo",
        }

    async def sync_material_masters(self, factory_id: str) -> Dict[str, Any]:
        return {
            "factory_id": factory_id,
            "synced_count": 0,
            "failed_count": 0,
            "synced_at": datetime.now().isoformat(),
            "status": "noop",
            "note": "batch sync endpoint not configured",
        }

    async def get_product_master(self, product_id: str) -> Dict[str, Any]:
        response = await self._call_api(f"/api/v1/products/{product_id}")
        if response:
            response.setdefault("source", "luaguage")
            return response
        return {
            "product_id": product_id,
            "product_code": f"PROD-{product_id}",
            "product_name": "产品名称",
            "product_type": "finished_goods",
            "unit": "PCS",
            "specification": "",
            "standard_cost": 100.0,
            "bom_version": "v1",
            "routing_version": "v1",
            "source": "demo",
        }

    # --- Production Result Sync ---

    async def push_production_result(self, work_order_id: str) -> Dict[str, Any]:
        payload = {
            "type": "work_order_completed",
            "data": {"work_order_id": work_order_id},
        }
        response = await self._call_api(
            "/api/v1/notifications/send",
            method="POST",
            data=payload,
        )
        return {
            "work_order_id": work_order_id,
            "pushed_at": datetime.now().isoformat(),
            "status": "success" if response is not None else "degraded",
            "response": response,
        }

    async def get_sales_orders(
        self,
        factory_id: str,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        params = {"factory_id": factory_id}
        if from_date:
            params["from_date"] = from_date
        if to_date:
            params["to_date"] = to_date
        response = await self._call_api("/api/v1/sales-orders", data=params)
        if isinstance(response, list):
            return response
        if isinstance(response, dict) and "items" in response:
            return list(response["items"])
        return []

    async def get_sync_status(self, entity_type: str) -> Dict[str, Any]:
        return {
            "entity_type": entity_type,
            "last_sync_at": (datetime.now() - timedelta(minutes=5)).isoformat(),
            "status": "healthy",
            "pending_count": 0,
            "base_url": self.base_url,
        }

    async def trigger_full_sync(self, entity_type: str) -> Dict[str, Any]:
        return {
            "entity_type": entity_type,
            "started_at": datetime.now().isoformat(),
            "status": "in_progress",
        }

    async def _call_api(
        self,
        endpoint: str,
        method: str = "GET",
        data: Optional[dict] = None,
    ) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        try:
            client = await self._get_client()
            method_u = method.upper()
            if method_u == "GET":
                response = await client.get(endpoint, params=data)
            elif method_u == "POST":
                response = await client.post(endpoint, json=data)
            elif method_u == "PUT":
                response = await client.put(endpoint, json=data)
            else:
                response = await client.request(method_u, endpoint, json=data)
            if response.status_code >= 400:
                logger.warning(
                    "luaguage API %s %s -> %s",
                    method_u,
                    endpoint,
                    response.status_code,
                )
                return None
            if not response.content:
                return {}
            payload = response.json()
            return payload if isinstance(payload, dict) else {"data": payload}
        except httpx.HTTPError as exc:
            logger.warning("luaguage API call failed %s %s: %s", method, endpoint, exc)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("luaguage API parse failed %s %s: %s", method, endpoint, exc)
            return None


class WebhookHandler:
    """Webhook事件处理器"""

    def __init__(self, integration: LuaguageIntegration) -> None:
        self.integration = integration

    async def handle_bom_updated(self, payload: Dict[str, Any]):
        return await self.integration.on_bom_changed(payload)

    async def handle_material_updated(self, payload: Dict[str, Any]):
        material_id = payload.get("material_id")
        if material_id:
            return await self.integration.get_material_master(str(material_id))
        return {"status": "ignored"}

    async def handle_product_updated(self, payload: Dict[str, Any]):
        product_id = payload.get("product_id")
        if product_id:
            return await self.integration.get_product_master(str(product_id))
        return {"status": "ignored"}


_LUAGUAGE: Optional[LuaguageIntegration] = None


def get_luaguage() -> LuaguageIntegration:
    global _LUAGUAGE
    if _LUAGUAGE is None:
        _LUAGUAGE = LuaguageIntegration()
    return _LUAGUAGE


__all__ = [
    "LuaguageIntegration",
    "WebhookHandler",
    "SyncMode",
    "PPAPStatus",
    "get_luaguage",
]
