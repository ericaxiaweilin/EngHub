"""
Virtual factory pulse service.

This is a deterministic data heartbeat for demos and sandboxes. It creates
sales orders, decomposes them into master/operation work orders, and advances
production reports at a realistic capacity rhythm instead of completing an
order immediately.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    Notification,
    ProcessAnalysis,
    Product,
    ProductionReport,
    StandardOperationTime,
    Station,
    WorkOrder,
)


DEFAULT_MONTHLY_CONTAINERS = 300
DEFAULT_ORDER_DAYS = 90
DEFAULT_FACTORY_ID = "FAC_ELEC_DEMO_2026"
VIRTUAL_MARKER = "[virtual_factory]"


@dataclass
class PulseConfig:
    factory_id: str = DEFAULT_FACTORY_ID
    monthly_capacity_containers: int = DEFAULT_MONTHLY_CONTAINERS
    order_lead_days: int = DEFAULT_ORDER_DAYS
    target_active_orders: int = 6
    max_new_orders_per_pulse: int = 1
    operator: str = "virtual_factory"

    @property
    def daily_capacity(self) -> int:
        return max(1, round(self.monthly_capacity_containers / 30))


class VirtualFactoryService:
    """Maintain a live-feeling factory data stream."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def pulse(self, config: Optional[PulseConfig] = None) -> Dict[str, Any]:
        cfg = config or PulseConfig()
        product = await self._ensure_virtual_product(cfg.factory_id, cfg.operator)
        stations = await self._ensure_virtual_stations(cfg.factory_id, cfg.operator)
        await self._ensure_ie_baseline(cfg.factory_id, product.product_code, stations, cfg.operator)

        active_orders = await self._active_virtual_masters(cfg.factory_id)
        created_orders: List[Dict[str, Any]] = []
        if len(active_orders) < cfg.target_active_orders:
            for _ in range(min(cfg.max_new_orders_per_pulse, cfg.target_active_orders - len(active_orders))):
                created = await self._create_order_chain(cfg, product, stations)
                created_orders.append(created)

        advanced = await self._advance_open_work(cfg, stations)
        alerts = await self._guard_and_notify(cfg)
        await self.db.commit()

        status = await self.status(cfg.factory_id)
        return {
            "success": True,
            "factory_id": cfg.factory_id,
            "pulse_at": datetime.utcnow().isoformat(),
            "rhythm": {
                "monthly_capacity_containers": cfg.monthly_capacity_containers,
                "daily_capacity_containers": cfg.daily_capacity,
                "order_lead_days": cfg.order_lead_days,
            },
            "created_orders": created_orders,
            "advanced": advanced,
            "alerts": alerts,
            "status": status,
        }

    def _factory_token(self, factory_id: str) -> str:
        raw = "".join(ch for ch in (factory_id or "FAC") if ch.isalnum())
        return (raw[-8:] or "FAC").upper()

    async def _table_columns(self, table_name: str) -> set[str]:
        bind = self.db.get_bind()
        dialect = bind.dialect.name if bind is not None else ""
        if dialect == "sqlite":
            rows = (await self.db.execute(text(f"PRAGMA table_info({table_name})"))).fetchall()
            return {str(r[1]) for r in rows}
        rows = (await self.db.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = :table_name
        """), {"table_name": table_name})).fetchall()
        return {str(r[0]) for r in rows}

    async def status(self, factory_id: str = DEFAULT_FACTORY_ID) -> Dict[str, Any]:
        active = await self._active_virtual_masters(factory_id)
        open_rows = [
            {
                "work_order_code": wo.work_order_code,
                "product_id": wo.product_id,
                "planned_qty": wo.planned_qty,
                "completed_qty": wo.completed_qty or 0,
                "progress_pct": round(((wo.completed_qty or 0) / max(wo.planned_qty or 1, 1)) * 100, 1),
                "status": wo.status,
                "planned_start": wo.planned_start.isoformat() if wo.planned_start else None,
                "planned_due": wo.planned_due.isoformat() if wo.planned_due else None,
            }
            for wo in active[:20]
        ]
        order_count = await self.db.execute(text("""
            SELECT COUNT(*) FROM sales_orders
            WHERE factory_id = :fid AND remark LIKE :marker
        """), {"fid": factory_id, "marker": f"%{VIRTUAL_MARKER}%"})
        report_count = await self.db.execute(select(ProductionReport).where(
            ProductionReport.factory_id == factory_id,
            ProductionReport.created_by == "virtual_factory",
        ))
        return {
            "factory_id": factory_id,
            "active_virtual_orders": len(active),
            "virtual_sales_orders": int(order_count.scalar() or 0),
            "virtual_report_count": len(report_count.scalars().all()),
            "open_work_orders": open_rows,
        }

    async def _ensure_virtual_product(self, factory_id: str, operator: str) -> Product:
        product_code = f"VF-{self._factory_token(factory_id)}-40HQ"
        product = (await self.db.execute(select(Product).where(
            Product.factory_id == factory_id,
            Product.product_code == product_code,
        ))).scalar_one_or_none()
        if product:
            return product
        product = Product(
            id=str(uuid.uuid4()),
            factory_id=factory_id,
            product_code=product_code,
            product_name="虚拟40HQ出货柜",
            category="virtual_factory",
            unit="container",
            description="虚拟工厂脉搏订单使用的标准出货单位",
            status="active",
            created_by=operator,
        )
        self.db.add(product)
        await self.db.flush()
        return product

    async def _ensure_virtual_stations(self, factory_id: str, operator: str) -> List[Station]:
        token = self._factory_token(factory_id)
        specs = [
            (f"VF-{token}-PLAN", "订单评审/PMC拆单", "planning", 60),
            (f"VF-{token}-MATL", "备料齐套", "warehouse", 48),
            (f"VF-{token}-ASSY", "主线生产", "production", 24),
            (f"VF-{token}-QC", "终检/OQC", "quality", 36),
            (f"VF-{token}-SHIP", "出货装柜", "warehouse", 30),
        ]
        stations: List[Station] = []
        station_columns = await self._table_columns("stations")
        for code, name, stype, cap in specs:
            station = (await self.db.execute(select(Station).where(
                Station.factory_id == factory_id,
                Station.station_code == code,
            ))).scalar_one_or_none()
            if not station:
                row = {
                    "id": str(uuid.uuid4()),
                    "factory_id": factory_id,
                    "workshop_id": "VIRTUAL_FACTORY",
                    "station_code": code,
                    "station_name": name,
                    "station_type": stype,
                    "capacity": cap,
                    "capacity_unit": "container/day",
                    "equipment_count": 0,
                    "status": "active",
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                    "created_by": operator,
                    "capacity_per_hour": cap,
                    "equipment_ids": json.dumps([]),
                }
                insert_cols = [col for col in row if col in station_columns]
                await self.db.execute(text(f"""
                    INSERT INTO stations ({", ".join(insert_cols)})
                    VALUES ({", ".join(f":{col}" for col in insert_cols)})
                """), {col: row[col] for col in insert_cols})
                await self.db.flush()
                station = (await self.db.execute(select(Station).where(
                    Station.factory_id == factory_id,
                    Station.station_code == code,
                ))).scalar_one()
            stations.append(station)
        return stations

    async def _ensure_ie_baseline(
        self,
        factory_id: str,
        product_code: str,
        stations: List[Station],
        operator: str,
    ) -> None:
        exists = (await self.db.execute(select(StandardOperationTime.id).where(
            StandardOperationTime.factory_id == factory_id,
            StandardOperationTime.product_id == product_code,
        ).limit(1))).scalar_one_or_none()
        if exists:
            return

        now = datetime.utcnow()
        for idx, station in enumerate(stations, start=1):
            standard = [18.0, 42.0, 120.0, 36.0, 28.0][idx - 1]
            self.db.add(StandardOperationTime(
                id=str(uuid.uuid4()),
                factory_id=factory_id,
                product_id=product_code,
                routing_step=f"VF-{idx:02d}",
                operation_seq=idx,
                operation_name=station.station_name,
                station_id=station.id,
                work_center=station.station_code,
                standard_time_min=standard,
                unit_time_type="per_batch",
                setup_time_min=30.0,
                setup_before_start_time_min=15.0,
                post_operation_time_min=10.0,
                batch_size=10,
                rating_factor=1.0,
                allowance_rate=0.12,
                effective_standard_time=standard,
                version="vf-v1",
                is_active=True,
                validity_start=now,
                created_by=operator,
                updated_by=operator,
            ))
            self.db.add(ProcessAnalysis(
                id=str(uuid.uuid4()),
                factory_id=factory_id,
                product_id=product_code,
                operation_code=station.station_code,
                analysis_date=now,
                total_process_time_min=standard + 24,
                va_time_min=standard * 0.72,
                nva_time_min=standard * 0.28 + 24,
                wait_time_min=12,
                move_time_min=8,
                inspect_time_min=4,
                va_ratio=round((standard * 0.72) / max(standard + 24, 1), 4),
                lead_time=standard + 24,
                efficiency_score=round(78 + idx * 2.5, 1),
                created_by=operator,
                updated_by=operator,
            ))

    async def _active_virtual_masters(self, factory_id: str) -> List[WorkOrder]:
        rows = (await self.db.execute(select(WorkOrder).where(
            WorkOrder.factory_id == factory_id,
            WorkOrder.created_by == "virtual_factory",
            WorkOrder.wo_type == "master",
            WorkOrder.status.in_(["pending", "released", "in_progress", "on_hold"]),
        ).order_by(WorkOrder.planned_due.asc(), WorkOrder.created_at.asc()))).scalars().all()
        return list(rows)

    async def _create_order_chain(
        self,
        cfg: PulseConfig,
        product: Product,
        stations: List[Station],
    ) -> Dict[str, Any]:
        now = datetime.utcnow()
        start = datetime.combine(date.today(), time(hour=8))
        due = start + timedelta(days=cfg.order_lead_days)
        qty = cfg.monthly_capacity_containers
        so_id = str(uuid.uuid4())
        so_code = f"SO-VF-{now.strftime('%y%m%d')}-{uuid.uuid4().hex[:4].upper()}"
        wo_code = f"WO-VF-{now.strftime('%m%d')}-{uuid.uuid4().hex[:5].upper()}"
        remark = (
            f"{VIRTUAL_MARKER} lead_days={cfg.order_lead_days}; "
            f"monthly_capacity={cfg.monthly_capacity_containers}; pulse_created={now.isoformat()}"
        )

        await self.db.execute(text("""
            INSERT INTO sales_orders (
                id, order_code, factory_id, customer_name, customer_code, product_id,
                product_name, quantity, unit, delivery_date, priority, status,
                decomposed, decomposed_at, material_ready, material_check_at,
                remark, created_by, created_at, updated_at
            )
            VALUES (
                :id, :order_code, :factory_id, :customer_name, :customer_code, :product_id,
                :product_name, :quantity, :unit, :delivery_date, :priority, :status,
                :decomposed, :decomposed_at, :material_ready, :material_check_at,
                :remark, :created_by, :created_at, :updated_at
            )
        """), {
            "id": so_id,
            "order_code": so_code,
            "factory_id": cfg.factory_id,
            "customer_name": "虚拟客户",
            "customer_code": "VIRTUAL",
            "product_id": product.product_code,
            "product_name": product.product_name,
            "quantity": qty,
            "unit": "container",
            "delivery_date": due.date(),
            "priority": "medium",
            "status": "planning",
            "decomposed": True,
            "decomposed_at": now,
            "material_ready": True,
            "material_check_at": now,
            "remark": remark,
            "created_by": cfg.operator,
            "created_at": now,
            "updated_at": now,
        })

        master = WorkOrder(
            id=str(uuid.uuid4()),
            work_order_code=wo_code,
            factory_id=cfg.factory_id,
            sales_order_id=so_id,
            product_id=product.product_code,
            planned_qty=qty,
            unit="container",
            completed_qty=0,
            good_qty=0,
            defect_qty=0,
            status="released",
            priority="medium",
            planned_start=start,
            planned_due=due,
            actual_start=start,
            assigned_station_id=stations[0].id,
            wo_type="master",
            current_stage="订单已拆单，按90天节奏生产",
            next_station=stations[1].station_name,
            remark=remark,
            created_by=cfg.operator,
        )
        self.db.add(master)
        await self.db.flush()

        op_windows = [
            (0, 5, "ORDER_REVIEW", stations[0]),
            (3, 18, "MATERIAL_KITTING", stations[1]),
            (10, cfg.order_lead_days - 10, "ASSEMBLY", stations[2]),
            (cfg.order_lead_days - 18, cfg.order_lead_days - 4, "OQC", stations[3]),
            (cfg.order_lead_days - 7, cfg.order_lead_days, "SHIPMENT", stations[4]),
        ]
        op_ids: List[str] = []
        for idx, (start_offset, end_offset, process, station) in enumerate(op_windows, start=1):
            op = WorkOrder(
                id=str(uuid.uuid4()),
                work_order_code=f"{wo_code}-OP{idx:02d}",
                factory_id=cfg.factory_id,
                sales_order_id=so_id,
                product_id=product.product_code,
                planned_qty=qty,
                unit="container",
                completed_qty=0,
                good_qty=0,
                defect_qty=0,
                status="released" if start_offset <= 0 else "pending",
                priority="medium",
                planned_start=start + timedelta(days=start_offset),
                planned_due=start + timedelta(days=max(start_offset + 1, end_offset)),
                assigned_station_id=station.id,
                parent_work_order_id=master.id,
                wo_type="operation",
                process_code=process,
                operation_seq=idx,
                work_center=station.station_code,
                current_stage=station.station_name,
                remark=remark,
                created_by=cfg.operator,
            )
            self.db.add(op)
            op_ids.append(op.id)

        await self.db.execute(text("""
            UPDATE sales_orders
            SET work_order_ids = :wo_ids, updated_at = :now
            WHERE id = :id
        """), {"wo_ids": json.dumps([master.id, *op_ids]), "now": now, "id": so_id})

        self.db.add(Notification(
            id=str(uuid.uuid4()),
            factory_id=cfg.factory_id,
            title="虚拟工厂接入新订单",
            content=f"{so_code} 已拆为 {wo_code} 和 {len(op_ids)} 个工序工单，将按 {cfg.order_lead_days} 天节奏推进。",
            severity="info",
            category="virtual_factory",
            recipient=None,
            source_type="virtual_factory",
            source_id=master.id,
            created_by=cfg.operator,
        ))

        return {
            "sales_order_code": so_code,
            "master_work_order_code": wo_code,
            "operation_work_orders": len(op_ids),
            "quantity_containers": qty,
            "planned_start": start.date().isoformat(),
            "planned_due": due.date().isoformat(),
        }

    async def _advance_open_work(self, cfg: PulseConfig, stations: List[Station]) -> Dict[str, Any]:
        today_end = datetime.combine(date.today(), time.max)
        masters = await self._active_virtual_masters(cfg.factory_id)
        if not masters:
            return {"reports_created": 0, "containers_reported": 0, "work_orders_touched": 0}

        reports_created = 0
        containers_reported = 0
        per_order_daily = max(1, cfg.daily_capacity // max(1, len(masters)))
        station_by_code = {s.station_code: s for s in stations}

        for master in masters:
            if master.planned_start and master.planned_start > today_end:
                continue
            last_report_at = (await self.db.execute(select(ProductionReport.created_at).where(
                ProductionReport.work_order_id == master.id,
                ProductionReport.created_by == cfg.operator,
            ).order_by(ProductionReport.created_at.desc()).limit(1))).scalar_one_or_none()
            if last_report_at and last_report_at.date() >= date.today():
                continue
            remaining = max(0, (master.planned_qty or 0) - (master.completed_qty or 0))
            if remaining <= 0:
                master.status = "completed"
                master.actual_complete = master.actual_complete or datetime.utcnow()
                continue
            due_days = max(1, ((master.planned_due or today_end) - datetime.utcnow()).days + 1)
            qty = max(1, min(remaining, per_order_daily, round(remaining / due_days) + 1))
            defect_qty = 1 if qty >= 20 and uuid.uuid4().int % 11 == 0 else 0
            good_qty = max(0, qty - defect_qty)

            station = next((s for s in stations if str(s.station_code).endswith("-ASSY")), stations[0])
            report = ProductionReport(
                id=str(uuid.uuid4()),
                report_code=f"RPT-VF-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}",
                factory_id=cfg.factory_id,
                work_order_id=master.id,
                station_id=station.id,
                good_qty=good_qty,
                defect_qty=defect_qty,
                report_type="virtual_pulse",
                shift="day",
                operator_id=cfg.operator,
                operation_name="虚拟工厂日节奏报工",
                start_time=datetime.combine(date.today(), time(hour=8)),
                end_time=datetime.combine(date.today(), time(hour=17)),
                remark=f"{VIRTUAL_MARKER} daily_capacity={cfg.daily_capacity}",
                created_by=cfg.operator,
            )
            self.db.add(report)

            master.status = "completed" if remaining == qty else "in_progress"
            master.completed_qty = (master.completed_qty or 0) + qty
            master.good_qty = (master.good_qty or 0) + good_qty
            master.defect_qty = (master.defect_qty or 0) + defect_qty
            master.current_stage = "生产中：按日节奏推进"
            master.next_station = "终检/OQC" if (master.completed_qty or 0) > (master.planned_qty or 1) * 0.8 else "主线生产"
            if master.status == "completed":
                master.actual_complete = datetime.utcnow()
                await self.db.execute(text("""
                    UPDATE sales_orders
                    SET status = 'completed', updated_at = :now
                    WHERE id = :id
                """), {"now": datetime.utcnow(), "id": master.sales_order_id})
            else:
                await self.db.execute(text("""
                    UPDATE sales_orders
                    SET status = 'in_progress', updated_at = :now
                    WHERE id = :id
                """), {"now": datetime.utcnow(), "id": master.sales_order_id})

            reports_created += 1
            containers_reported += qty

        return {
            "reports_created": reports_created,
            "containers_reported": containers_reported,
            "work_orders_touched": reports_created,
            "daily_capacity_containers": cfg.daily_capacity,
        }

    async def _guard_and_notify(self, cfg: PulseConfig) -> List[Dict[str, Any]]:
        alerts: List[Dict[str, Any]] = []
        now = datetime.utcnow()
        rows = await self._active_virtual_masters(cfg.factory_id)
        for wo in rows:
            progress = ((wo.completed_qty or 0) / max(wo.planned_qty or 1, 1)) * 100
            elapsed_days = max(0, (now - (wo.planned_start or wo.created_at or now)).days)
            planned_total_days = max(1, ((wo.planned_due or now) - (wo.planned_start or wo.created_at or now)).days)
            expected_progress = min(100, elapsed_days / planned_total_days * 100)
            if expected_progress - progress >= 12:
                alert = {
                    "work_order_code": wo.work_order_code,
                    "severity": "warning",
                    "summary": f"虚拟工厂节奏落后：计划应达 {expected_progress:.1f}%，当前 {progress:.1f}%",
                }
                alerts.append(alert)
                self.db.add(Notification(
                    id=str(uuid.uuid4()),
                    factory_id=cfg.factory_id,
                    title="虚拟工厂节奏预警",
                    content=f"{wo.work_order_code} {alert['summary']}，请检查产能/物料/工序边界。",
                    severity="warning",
                    category="virtual_factory",
                    recipient=None,
                    source_type="virtual_factory",
                    source_id=wo.id,
                    created_by=cfg.operator,
                ))
        return alerts
