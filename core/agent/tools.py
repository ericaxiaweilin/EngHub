"""
Manufacturing data tools shared by the AI agent and MCP server.

Tools prefer live database reads when a session factory is available,
and fall back to deterministic demo payloads so Codex / MCP clients
can still inspect schemas and sample manufacturing data offline.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from core.agent.models import ToolDefinition
from core.config import settings

logger = logging.getLogger(__name__)

ToolHandler = Callable[..., Awaitable[Dict[str, Any]]]


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _serialize_model(obj: Any) -> Dict[str, Any]:
    """Best-effort conversion of SQLAlchemy models / plain objects to dict."""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    data: Dict[str, Any] = {}
    for key in getattr(obj, "__table__", None).columns.keys() if hasattr(obj, "__table__") else []:
        value = getattr(obj, key, None)
        if isinstance(value, datetime):
            data[key] = value.isoformat()
        else:
            data[key] = str(value) if value is not None and not isinstance(value, (str, int, float, bool, list, dict)) else value
    if data:
        return data
    if hasattr(obj, "__dict__"):
        return {
            k: v
            for k, v in vars(obj).items()
            if not k.startswith("_")
        }
    return {"value": str(obj)}


class ToolRegistry:
    """Registry of MES read tools exposed to agents and MCP clients."""

    def __init__(self, factory_id: Optional[str] = None) -> None:
        self.factory_id = factory_id or settings.DEFAULT_FACTORY_ID
        self._handlers: Dict[str, ToolHandler] = {}
        self._definitions: Dict[str, ToolDefinition] = {}
        self._session_factory: Optional[Callable[[], Any]] = None
        self._register_builtin_tools()

    def set_session_factory(self, session_factory: Optional[Callable[[], Any]]) -> None:
        """Optional async SQLAlchemy session factory for live reads."""
        self._session_factory = session_factory

    def register(
        self,
        name: str,
        handler: ToolHandler,
        description: str,
        input_schema: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._handlers[name] = handler
        self._definitions[name] = ToolDefinition(
            name=name,
            description=description,
            input_schema=input_schema
            or {"type": "object", "properties": {}},
        )

    def list_definitions(self) -> List[ToolDefinition]:
        return list(self._definitions.values())

    def get_definition(self, name: str) -> Optional[ToolDefinition]:
        return self._definitions.get(name)

    def openai_tools(self) -> List[Dict[str, Any]]:
        return [item.to_openai_tool() for item in self.list_definitions()]

    def mcp_tools(self) -> List[Dict[str, Any]]:
        return [item.to_mcp_tool() for item in self.list_definitions()]

    async def call(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        handler = self._handlers.get(name)
        if handler is None:
            return {"error": f"Unknown tool: {name}"}
        args = arguments or {}
        try:
            result = await handler(**args)
            if not isinstance(result, dict):
                return {"result": result}
            return result
        except TypeError as exc:
            return {"error": f"Invalid arguments for {name}: {exc}"}
        except Exception as exc:  # noqa: BLE001 - surface tool failures to LLM/MCP
            logger.exception("Tool %s failed", name)
            return {"error": str(exc), "tool": name}

    async def _with_db(self, callback: Callable[[Any], Awaitable[Any]]) -> Optional[Any]:
        if self._session_factory is None:
            return None
        session = self._session_factory()
        try:
            # Support both context-manager factories and plain sessions.
            if hasattr(session, "__aenter__"):
                async with session as db:
                    return await callback(db)
            return await callback(session)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Live DB tool path failed, using demo data: %s", exc)
            return None
        finally:
            close = getattr(session, "close", None)
            if callable(close) and not hasattr(session, "__aenter__"):
                maybe = close()
                if hasattr(maybe, "__await__"):
                    await maybe

    def _register_builtin_tools(self) -> None:
        self.register(
            "list_work_orders",
            self.list_work_orders,
            "List manufacturing work orders for a factory, optionally filtered by status.",
            {
                "type": "object",
                "properties": {
                    "factory_id": {
                        "type": "string",
                        "description": "Factory identifier. Defaults to configured factory.",
                    },
                    "status": {
                        "type": "string",
                        "description": "Optional status filter (draft/pending/released/in_progress/completed).",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max rows to return (default 20).",
                        "default": 20,
                    },
                },
            },
        )
        self.register(
            "get_work_order",
            self.get_work_order,
            "Get a single work order by code or id, including progress quantities.",
            {
                "type": "object",
                "properties": {
                    "work_order_code": {
                        "type": "string",
                        "description": "Human-readable work order code (preferred).",
                    },
                    "work_order_id": {
                        "type": "string",
                        "description": "Work order UUID if code is unknown.",
                    },
                },
            },
        )
        self.register(
            "list_stations",
            self.list_stations,
            "List production stations/work cells for a factory.",
            {
                "type": "object",
                "properties": {
                    "factory_id": {"type": "string"},
                    "station_type": {"type": "string"},
                    "status": {"type": "string"},
                    "limit": {"type": "integer", "default": 20},
                },
            },
        )
        self.register(
            "get_station",
            self.get_station,
            "Get details for one station by id or station_code.",
            {
                "type": "object",
                "properties": {
                    "station_id": {"type": "string"},
                    "station_code": {"type": "string"},
                },
            },
        )
        self.register(
            "list_equipment",
            self.list_equipment,
            "List equipment assets and their operational status.",
            {
                "type": "object",
                "properties": {
                    "factory_id": {"type": "string"},
                    "status": {"type": "string"},
                    "limit": {"type": "integer", "default": 20},
                },
            },
        )
        self.register(
            "get_inventory",
            self.get_inventory,
            "Query inventory levels, optionally filtered by material or warehouse.",
            {
                "type": "object",
                "properties": {
                    "factory_id": {"type": "string"},
                    "material_id": {"type": "string"},
                    "warehouse_id": {"type": "string"},
                    "limit": {"type": "integer", "default": 20},
                },
            },
        )
        self.register(
            "get_production_summary",
            self.get_production_summary,
            "Summarize production output, yield, and open work orders for a factory.",
            {
                "type": "object",
                "properties": {
                    "factory_id": {"type": "string"},
                },
            },
        )
        self.register(
            "get_oee_snapshot",
            self.get_oee_snapshot,
            "Return an OEE-style availability/performance/quality snapshot for a station.",
            {
                "type": "object",
                "properties": {
                    "station_code": {
                        "type": "string",
                        "description": "Station code to evaluate.",
                    },
                    "time_range": {
                        "type": "string",
                        "description": "Lookback window such as 24h, 7d.",
                        "default": "24h",
                    },
                },
                "required": ["station_code"],
            },
        )
        self.register(
            "search_mes_entities",
            self.search_mes_entities,
            "Keyword search across work orders, stations, and equipment demo/live catalogs.",
            {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Free-text search query.",
                    },
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            },
        )
        self.register(
            "get_system_status",
            self.get_system_status,
            "Return EngHub agent/MCP capability status and configured defaults.",
            {"type": "object", "properties": {}},
        )
        # Luaguage ERP master-data tools (context for agent reasoning, not LLM)
        self.register(
            "get_luaguage_bom",
            self.get_luaguage_bom,
            "Fetch product BOM from luaguage ERP (falls back to demo when offline).",
            {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "string",
                        "description": "Product id in luaguage / EngHub.",
                    },
                    "version": {
                        "type": "string",
                        "description": "Optional BOM version.",
                    },
                },
                "required": ["product_id"],
            },
        )
        self.register(
            "get_luaguage_ppap",
            self.get_luaguage_ppap,
            "Fetch material PPAP approval status from luaguage ERP.",
            {
                "type": "object",
                "properties": {
                    "material_id": {"type": "string"},
                },
                "required": ["material_id"],
            },
        )
        self.register(
            "get_luaguage_material",
            self.get_luaguage_material,
            "Fetch material master data from luaguage ERP.",
            {
                "type": "object",
                "properties": {
                    "material_id": {"type": "string"},
                },
                "required": ["material_id"],
            },
        )
        self.register(
            "get_model_base_status",
            self.get_model_base_status,
            "Check connectivity of model-engineering-base and model-stack backends.",
            {"type": "object", "properties": {}},
        )

    # ---- tool implementations -------------------------------------------------

    async def list_work_orders(
        self,
        factory_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 20,
    ) -> Dict[str, Any]:
        factory = factory_id or self.factory_id

        async def _db(db: Any) -> List[Dict[str, Any]]:
            from api.services.work_order_service import WorkOrderService

            service = WorkOrderService(db)
            rows = await service.list_work_orders(
                factory_id=factory,
                status=status,
                skip=0,
                limit=limit,
            )
            return [_serialize_model(row) for row in rows]

        live = await self._with_db(_db)
        if live is not None:
            return {
                "source": "database",
                "factory_id": factory,
                "count": len(live),
                "items": live,
            }

        items = [
            {
                "work_order_code": "WO-20260716-001",
                "product_id": "SKU-A100",
                "status": "in_progress",
                "planned_qty": 1000,
                "completed_qty": 650,
                "priority": "high",
            },
            {
                "work_order_code": "WO-20260716-002",
                "product_id": "SKU-B220",
                "status": "released",
                "planned_qty": 500,
                "completed_qty": 0,
                "priority": "medium",
            },
            {
                "work_order_code": "WO-20260715-018",
                "product_id": "SKU-A100",
                "status": "completed",
                "planned_qty": 800,
                "completed_qty": 800,
                "priority": "medium",
            },
        ]
        if status:
            items = [item for item in items if item["status"] == status]
        return {
            "source": "demo",
            "factory_id": factory,
            "count": len(items[:limit]),
            "items": items[:limit],
            "queried_at": _iso_now(),
        }

    async def get_work_order(
        self,
        work_order_code: Optional[str] = None,
        work_order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not work_order_code and not work_order_id:
            return {"error": "Provide work_order_code or work_order_id"}

        async def _db(db: Any) -> Optional[Dict[str, Any]]:
            from api.services.work_order_service import WorkOrderService

            service = WorkOrderService(db)
            row = None
            if work_order_id:
                row = await service.get_work_order_by_id(work_order_id)
            if row is None and work_order_code:
                row = await service.get_work_order_by_code(work_order_code)
            return _serialize_model(row) if row else None

        live = await self._with_db(_db)
        if live:
            return {"source": "database", "work_order": live}

        code = work_order_code or "WO-20260716-001"
        planned = 1000
        completed = 650
        return {
            "source": "demo",
            "work_order": {
                "work_order_code": code,
                "work_order_id": work_order_id or "demo-wo-001",
                "product_id": "SKU-A100",
                "status": "in_progress",
                "planned_qty": planned,
                "completed_qty": completed,
                "good_qty": 630,
                "defect_qty": 20,
                "progress_percent": round(completed / planned * 100, 2),
                "assigned_station_id": "ST-ASM-01",
                "priority": "high",
                "planned_due": "2026-07-17T16:00:00+00:00",
            },
            "queried_at": _iso_now(),
        }

    async def list_stations(
        self,
        factory_id: Optional[str] = None,
        station_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 20,
    ) -> Dict[str, Any]:
        factory = factory_id or self.factory_id

        async def _db(db: Any) -> List[Dict[str, Any]]:
            from api.services.mes_services import StationService

            rows = await StationService(db).list_stations(
                factory_id=factory,
                station_type=station_type,
                status=status,
                skip=0,
                limit=limit,
            )
            return [_serialize_model(row) for row in rows]

        live = await self._with_db(_db)
        if live is not None:
            return {
                "source": "database",
                "factory_id": factory,
                "count": len(live),
                "items": live,
            }

        items = [
            {
                "station_code": "ST-ASM-01",
                "station_name": "Assembly Line 01",
                "station_type": "assembly",
                "status": "running",
                "capacity_per_hour": 120,
            },
            {
                "station_code": "ST-TEST-02",
                "station_name": "Test Cell 02",
                "station_type": "testing",
                "status": "idle",
                "capacity_per_hour": 80,
            },
        ]
        if station_type:
            items = [i for i in items if i["station_type"] == station_type]
        if status:
            items = [i for i in items if i["status"] == status]
        return {
            "source": "demo",
            "factory_id": factory,
            "count": len(items[:limit]),
            "items": items[:limit],
        }

    async def get_station(
        self,
        station_id: Optional[str] = None,
        station_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not station_id and not station_code:
            return {"error": "Provide station_id or station_code"}

        async def _db(db: Any) -> Optional[Dict[str, Any]]:
            from api.services.mes_services import StationService
            from sqlalchemy import select
            from database.models import Station

            service = StationService(db)
            row = None
            if station_id:
                row = await service.get_station_by_id(station_id)
            if row is None and station_code:
                result = await db.execute(
                    select(Station).where(Station.station_code == station_code)
                )
                row = result.scalar_one_or_none()
            return _serialize_model(row) if row else None

        live = await self._with_db(_db)
        if live:
            return {"source": "database", "station": live}

        code = station_code or "ST-ASM-01"
        return {
            "source": "demo",
            "station": {
                "station_id": station_id or "demo-station-001",
                "station_code": code,
                "station_name": "Assembly Line 01",
                "station_type": "assembly",
                "status": "running",
                "capacity_per_hour": 120,
                "current_wip": 45,
                "queue_length": 12,
            },
        }

    async def list_equipment(
        self,
        factory_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 20,
    ) -> Dict[str, Any]:
        factory = factory_id or self.factory_id

        async def _db(db: Any) -> List[Dict[str, Any]]:
            from api.services.mes_services import EquipmentService

            rows = await EquipmentService(db).list_equipment(
                factory_id=factory,
                status=status,
                skip=0,
                limit=limit,
            )
            return [_serialize_model(row) for row in rows]

        live = await self._with_db(_db)
        if live is not None:
            return {
                "source": "database",
                "factory_id": factory,
                "count": len(live),
                "items": live,
            }

        items = [
            {
                "equipment_code": "EQ-PM-500",
                "equipment_name": "Pick & Place PM-500",
                "status": "running",
                "health_score": 92,
            },
            {
                "equipment_code": "EQ-REFLOW-01",
                "equipment_name": "Reflow Oven 01",
                "status": "maintenance",
                "health_score": 74,
            },
        ]
        if status:
            items = [i for i in items if i["status"] == status]
        return {
            "source": "demo",
            "factory_id": factory,
            "count": len(items[:limit]),
            "items": items[:limit],
        }

    async def get_inventory(
        self,
        factory_id: Optional[str] = None,
        material_id: Optional[str] = None,
        warehouse_id: Optional[str] = None,
        limit: int = 20,
    ) -> Dict[str, Any]:
        factory = factory_id or self.factory_id

        async def _db(db: Any) -> List[Dict[str, Any]]:
            from sqlalchemy import select
            from database.models import Inventory

            query = select(Inventory).where(Inventory.factory_id == factory)
            if material_id:
                query = query.where(Inventory.material_id == material_id)
            if warehouse_id:
                query = query.where(Inventory.warehouse_id == warehouse_id)
            query = query.limit(limit)
            result = await db.execute(query)
            return [_serialize_model(row) for row in result.scalars().all()]

        live = await self._with_db(_db)
        if live is not None:
            return {
                "source": "database",
                "factory_id": factory,
                "count": len(live),
                "items": live,
            }

        items = [
            {
                "material_id": "MAT-PCB-01",
                "warehouse_id": "WH-MAIN",
                "total_qty": 4200,
                "available_qty": 3800,
                "reserved_qty": 400,
                "unit": "pcs",
            },
            {
                "material_id": "MAT-IC-778",
                "warehouse_id": "WH-MAIN",
                "total_qty": 900,
                "available_qty": 120,
                "reserved_qty": 780,
                "unit": "pcs",
                "shortage_risk": True,
            },
        ]
        if material_id:
            items = [i for i in items if i["material_id"] == material_id]
        if warehouse_id:
            items = [i for i in items if i["warehouse_id"] == warehouse_id]
        return {
            "source": "demo",
            "factory_id": factory,
            "count": len(items[:limit]),
            "items": items[:limit],
        }

    async def get_production_summary(
        self,
        factory_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        factory = factory_id or self.factory_id
        orders = await self.list_work_orders(factory_id=factory, limit=100)
        items = orders.get("items", [])
        open_statuses = {"draft", "pending", "released", "in_progress"}
        open_orders = [i for i in items if i.get("status") in open_statuses]
        completed = [i for i in items if i.get("status") == "completed"]
        planned = sum(int(i.get("planned_qty") or 0) for i in items)
        done = sum(int(i.get("completed_qty") or 0) for i in items)
        return {
            "source": orders.get("source", "demo"),
            "factory_id": factory,
            "open_work_orders": len(open_orders),
            "completed_work_orders": len(completed),
            "planned_qty": planned,
            "completed_qty": done,
            "completion_rate_percent": round((done / planned) * 100, 2) if planned else 0.0,
            "queried_at": _iso_now(),
        }

    async def get_oee_snapshot(
        self,
        station_code: str,
        time_range: str = "24h",
    ) -> Dict[str, Any]:
        availability = 92.0
        performance = 88.0
        quality = 97.0
        oee = round((availability * performance * quality) / 10000, 2)
        return {
            "source": "demo",
            "station_code": station_code,
            "time_range": time_range,
            "oee": oee,
            "availability": availability,
            "performance": performance,
            "quality": quality,
            "target_oee": 85.0,
            "status": "good" if oee >= 85 else "needs_improvement",
            "queried_at": _iso_now(),
        }

    async def search_mes_entities(
        self,
        query: str,
        limit: int = 10,
    ) -> Dict[str, Any]:
        needle = (query or "").strip().lower()
        if not needle:
            return {"error": "query is required"}

        bundles = [
            await self.list_work_orders(limit=50),
            await self.list_stations(limit=50),
            await self.list_equipment(limit=50),
        ]
        hits: List[Dict[str, Any]] = []
        for bundle in bundles:
            for item in bundle.get("items", []):
                blob = json.dumps(item, ensure_ascii=False).lower()
                if needle in blob:
                    hits.append(
                        {
                            "entity": item,
                            "source": bundle.get("source"),
                        }
                    )
                if len(hits) >= limit:
                    break
            if len(hits) >= limit:
                break
        return {
            "query": query,
            "count": len(hits),
            "items": hits,
        }

    async def get_system_status(self) -> Dict[str, Any]:
        return {
            "service": "enghub-agent",
            "mcp_server": settings.MCP_SERVER_NAME,
            "mcp_version": settings.MCP_SERVER_VERSION,
            "protocol_version": settings.MCP_PROTOCOL_VERSION,
            "default_factory_id": self.factory_id,
            "tool_count": len(self._definitions),
            "tools": [name for name in self._definitions],
            "model_base_provider": settings.MODEL_BASE_PROVIDER,
            "model_engineering_base_url": settings.MODEL_ENGINEERING_BASE_URL,
            "model_stack_url": settings.MODEL_STACK_URL,
            "llm_gateway": settings.LLM_GATEWAY_URL,
            "llm_model": settings.LLM_MODEL_NAME,
            "luaguage_base_url": settings.LUAGUAGE_BASE_URL,
            "luaguage_enabled": settings.LUAGUAGE_ENABLED,
            "live_db_enabled": self._session_factory is not None,
            "queried_at": _iso_now(),
        }

    async def get_luaguage_bom(
        self,
        product_id: str,
        version: Optional[str] = None,
    ) -> Dict[str, Any]:
        from integrations.luaguage import get_luaguage

        return await get_luaguage().get_bom(product_id=product_id, version=version)

    async def get_luaguage_ppap(self, material_id: str) -> Dict[str, Any]:
        from integrations.luaguage import get_luaguage

        return await get_luaguage().get_ppap_status(material_id)

    async def get_luaguage_material(self, material_id: str) -> Dict[str, Any]:
        from integrations.luaguage import get_luaguage

        return await get_luaguage().get_material_master(material_id)

    async def get_model_base_status(self) -> Dict[str, Any]:
        from core.model_base import get_model_base_client

        return await get_model_base_client().health()


_REGISTRY: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = ToolRegistry()
    return _REGISTRY
