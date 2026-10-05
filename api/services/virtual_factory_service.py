"""
Virtual factory pulse service.

This is a deterministic data heartbeat for demos and sandboxes. It creates
sales orders, decomposes them into master/operation work orders, and advances
production reports at a realistic capacity rhythm instead of completing an
order immediately.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import bindparam, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.virtual_factory_clock import get_clock
from api.services.wms_service import InventoryService
from database.models import (
    Notification,
    ProcessAnalysis,
    Product,
    ProductionReport,
    StandardOperationTime,
    Station,
    WorkOrder,
)


def progress_qty(daily_pieces: float, step_hours: float, remaining: int,
                 fallback_daily: int = 1) -> int:
    """这一拍该出多少件：映射到的日产能 × 仿真过了的时间。

    时间在这里是参数，不是"等真实工厂过完一天"：一拍仿真 24 小时就出一天的量，
    仿真 2 小时就出 1/12 天的量。日产能允许是小数（实测 ST-QC-02 配 0.6 件/日），
    但一道工序至少推进 1 件，否则永远出不来；没到剩余量的上限就按上限截断。
    """
    rate = float(daily_pieces) if float(daily_pieces or 0) > 0 else float(max(1, fallback_daily))
    produced = int(round(rate * float(step_hours) / 24.0))
    return max(1, min(int(remaining), produced))


DEFAULT_MONTHLY_CONTAINERS = 300
DEFAULT_ORDER_DAYS = 90
DEFAULT_FACTORY_ID = "FAC_ELEC_DEMO_2026"
VIRTUAL_MARKER = "[virtual_factory]"
# 种子数据（IE 基线）建过一次后，多久内不再重复检查（秒）
SEED_CLAIM_TTL_SECONDS = 24 * 3600
# 同一工单的节奏预警多久内只落一条通知（秒）。
# 原实现每轮都插 Notification，是最典型的写入放大。
ALERT_CLAIM_TTL_SECONDS = 6 * 3600


@dataclass
class PulseConfig:
    factory_id: str = DEFAULT_FACTORY_ID
    monthly_capacity_containers: int = DEFAULT_MONTHLY_CONTAINERS
    order_lead_days: int = DEFAULT_ORDER_DAYS
    target_active_orders: int = 6
    max_new_orders_per_pulse: int = 1
    operator: str = "virtual_factory"
    # 仿真时钟：每次 pulse 推进多少仿真小时。时钟与事件都在内存，不下盘。
    # 这是虚拟工厂的核心参数之一：生产进度按"仿真过了多久 × 映射到的产能"算，
    # 不是陪真实工厂等日历（原来默认 2 小时 + "今天已报过就不再报"，等于一小时只动一点点、
    # 一天只动一次，600 张子工单要跑几周 —— 那是把仿真当真实时间在熬）。
    sim_step_hours: float = max(0.5, float(os.getenv("VF_PULSE_SIM_STEP_HOURS", "24")))
    # 事件队列上界，超出丢最旧的 —— 队列本身不能变成新的写入放大源。
    event_queue_max: int = 200
    # 执行范围。原实现只推进 created_by='virtual_factory' 自己那几张单，
    # 于是 BOM 派生的母单与 500 多张子工单没有任何执行侧输入：完工数从 8-25 起就停在 5，
    # 缺口只增不减 —— 链条发散的真因在这里，不在排产算法。
    # 虚拟工厂是担任务的那一方，真实工厂的数据是映射输入，所以默认担全厂在制单。
    work_scope: str = os.getenv("VF_PULSE_WORK_SCOPE", "all_open")
    # 每次脉搏最多推进几张单（开发尺度：一轮 25 张；同一张单每天最多报一次工，
    # 所以上限只决定"今天轮到谁"，不会把写入撑开）。
    max_work_orders_per_pulse: int = max(1, int(os.getenv("VF_PULSE_MAX_WORK_ORDERS", "25")))

    @property
    def daily_capacity(self) -> int:
        return max(1, round(self.monthly_capacity_containers / 30))


class VirtualFactoryService:
    """Maintain a live-feeling factory data stream."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def pulse(self, config: Optional[PulseConfig] = None) -> Dict[str, Any]:
        cfg = config or PulseConfig()
        clock = get_clock()

        product = await self._ensure_virtual_product(cfg.factory_id, cfg.operator)
        stations = await self._ensure_virtual_stations(cfg.factory_id, cfg.operator)
        # 种子只需建一次：用内存标记挡住每轮的重复查询与潜在插入
        if await clock.claim(cfg.factory_id, "seed:ie", SEED_CLAIM_TTL_SECONDS):
            await self._ensure_ie_baseline(cfg.factory_id, product.product_code, stations, cfg.operator)

        active_orders = await self._active_virtual_masters(cfg.factory_id)
        created_orders: List[Dict[str, Any]] = []
        if len(active_orders) < cfg.target_active_orders:
            for _ in range(min(cfg.max_new_orders_per_pulse, cfg.target_active_orders - len(active_orders))):
                created = await self._create_order_chain(cfg, product, stations)
                created_orders.append(created)

        # 一拍先推进仿真时钟，再用这个时刻去推生产：报工时间、完工时间都用仿真时钟，
        # 事件与读数因此能互相核对（同一 sim_now）。
        sim_now = await clock.advance(cfg.factory_id, cfg.sim_step_hours)
        advanced = await self._advance_open_work(cfg, stations, sim_now)
        alerts = await self._guard_and_notify(cfg)
        await self.db.commit()
        events: List[Dict[str, Any]] = []
        for order in created_orders:
            events.append({
                "type": "order_created",
                "at": sim_now.isoformat(),
                "work_order_code": order.get("work_order_code"),
                "sales_order_code": order.get("sales_order_code"),
            })
        if advanced.get("reports_created"):
            events.append({
                "type": "progress_reported",
                "at": sim_now.isoformat(),
                "reports_created": advanced["reports_created"],
                "containers_reported": advanced["containers_reported"],
            })
            issued_lines = advanced.get("materials_issued_lines", 0)
            if issued_lines:
                events.append({
                    "type": "material_issued",
                    "at": sim_now.isoformat(),
                    "material_lines": issued_lines,
                    "quantity": advanced.get("materials_issued_qty", 0),
                    "bom_sources": advanced.get("bom_sources") or {},
                })
            shortages = advanced.get("material_shortages") or []
            if shortages:
                events.append({
                    "type": "material_shortage",
                    "at": sim_now.isoformat(),
                    "lines": len(shortages),
                    "sample": shortages[:3],
                })
            if advanced.get("orders_without_bom"):
                events.append({
                    "type": "material_not_consumed",
                    "at": sim_now.isoformat(),
                    "work_orders": advanced["orders_without_bom"],
                    "reason": "产品没有上传 BOM（bom_items 无行），不编造物料需求，"
                              "本轮报工不扣库存、成本归集拿不到领料依据",
                })
        for alert in alerts:
            events.append({"type": "rhythm_lag", "at": sim_now.isoformat(), **alert})
        await clock.push_events(cfg.factory_id, events, max_len=cfg.event_queue_max)

        status = await self.status(cfg.factory_id)
        return {
            "success": True,
            "factory_id": cfg.factory_id,
            "pulse_at": datetime.utcnow().isoformat(),
            "sim_now": sim_now.isoformat(),
            "sim_step_hours": cfg.sim_step_hours,
            "clock_backend": clock.backend,
            "events_emitted": len(events),
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

    async def _bom_backed_products(self, factory_id: str, product_codes: List[str]) -> Dict[str, set]:
        """这些产品在两份 BOM 里各覆盖了哪些：engflow 上传的镜像优先，本地 bom_items 兜底。"""
        codes = [c for c in set(product_codes) if c]
        if not codes:
            return {"engflow_mirror": set(), "mes_bom_items": set()}
        mirror = set((await self.db.execute(text("""
            SELECT DISTINCT product_model FROM enghub_bom_items
            WHERE factory_id = :fid AND product_model = ANY(:codes) AND level = 1
              AND quantity IS NOT NULL
        """), {"fid": factory_id, "codes": codes})).scalars().all())
        local = set((await self.db.execute(text("""
            SELECT DISTINCT product_id FROM bom_items
            WHERE factory_id = :fid AND product_id = ANY(:codes) AND level = 1
        """), {"fid": factory_id, "codes": codes})).scalars().all())
        return {"engflow_mirror": mirror, "mes_bom_items": local}

    async def status(self, factory_id: str = DEFAULT_FACTORY_ID) -> Dict[str, Any]:
        active = await self._active_virtual_masters(factory_id)
        codes = [wo.product_id for wo in active if wo.product_id]
        covered = await self._bom_backed_products(factory_id, codes)
        backed = covered["engflow_mirror"] | covered["mes_bom_items"]
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
        clock = get_clock()
        return {
            "factory_id": factory_id,
            "active_virtual_orders": len(active),
            "virtual_sales_orders": int(order_count.scalar() or 0),
            "virtual_report_count": len(report_count.scalars().all()),
            "open_work_orders": open_rows,
            # 仿真时钟与事件队列都在内存（Redis），不落库、不新增表
            "sim_now": (await clock.now(factory_id)).isoformat(),
            "clock_backend": clock.backend,
            "recent_events": await clock.recent_events(factory_id, limit=20),
            # 报工不等于领料：只有上传过 BOM 的产品才扣得到库存，先把它说明白
            "material_consumption": {
                "active_products": len(set(codes)),
                "bom_coverage": {
                    "engflow_mirror": len(covered["engflow_mirror"]),
                    "mes_bom_items": len(covered["mes_bom_items"]),
                },
                "products_without_bom": sorted(set(codes) - backed),
                "note": "领料第一来源是 engflow 上传的 BOM（本地镜像 enghub_bom_items 的 level=1 组件"
                        "× 合格产出），镜像没这个型号才回落本地 bom_items；"
                        "两处都没有就不扣库存、也不编造物料需求。",
            },
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
        # 一次查全部（原来是每个工位一条 SELECT）
        existing = {s.station_code: s for s in (await self.db.execute(select(Station).where(
            Station.factory_id == factory_id,
            Station.station_code.in_([spec[0] for spec in specs]),
        ))).scalars().all()}
        for code, name, stype, cap in specs:
            station = existing.get(code)
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

    async def _open_work_orders(self, cfg: PulseConfig) -> List[WorkOrder]:
        """这一轮要执行哪些单：全厂在制的母单与子工单，由深到浅。

        子工单先做，母单才可能拿到下层供货 —— 顺序反了就会一直"欠料却没人完工"。
        多取几倍候选是因为"今天已报过工的单"要跳过，不能让它们占住本轮额度。
        """
        if cfg.work_scope == "virtual_only":
            return await self._active_virtual_masters(cfg.factory_id)
        rows = (await self.db.execute(select(WorkOrder).where(
            WorkOrder.factory_id == cfg.factory_id,
            WorkOrder.wo_type.in_(["master", "component"]),
            WorkOrder.status.in_(["pending", "released", "in_progress", "on_hold"]),
        ).order_by(
            text("CASE WHEN wo_type = 'component' THEN 0 ELSE 1 END"),
            WorkOrder.planned_due.asc().nullslast(),
            WorkOrder.created_at.asc(),
        ).limit(max(20, cfg.max_work_orders_per_pulse * 4)))).scalars().all()
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

    async def _daily_pieces_by_order(self, factory_id: str, order_ids: List[str]) -> Dict[str, float]:
        """每张单一天能出几件：从它在本厂生效方案里的首道工序工位，取 station_capacity。

        这一列的口径是"一天可完成几件产品"（用户 10-03 确认），所以直接当日产率用；
        映射不到工位的单不猜数字，回落到脉搏的总产能参数并在回执里说明有几张是回落的。
        """
        if not order_ids:
            return {}
        rows = (await self.db.execute(text("""
            SELECT w.id AS work_order_id,
                   COALESCE(sc.available_hours_per_day, 0) AS daily_pieces,
                   f.station_id AS station_code
            FROM work_orders w
            LEFT JOIN (
                SELECT DISTINCT ON (t.work_order_id) t.work_order_id, t.station_id
                FROM aps_schedule_tasks t
                JOIN aps_schedules s ON s.id = t.schedule_id
                WHERE s.factory_id = :fid AND s.is_current = TRUE
                  AND COALESCE(t.status, '') NOT IN ('completed', 'cancelled')
                ORDER BY t.work_order_id, t.operation_seq, t.planned_start
            ) f ON f.work_order_id = w.id
            LEFT JOIN station_capacity sc
              ON sc.station_id = f.station_id AND sc.factory_id = :fid AND sc.is_active = TRUE
            WHERE w.id = ANY(CAST(:ids AS text[]))
        """), {"fid": factory_id, "ids": order_ids})).mappings().all()
        return {str(r["work_order_id"]): float(r["daily_pieces"] or 0) for r in rows}

    async def _advance_open_work(self, cfg: PulseConfig, stations: List[Station],
                                 sim_now: datetime) -> Dict[str, Any]:
        # 仿真时钟给的是带时区的 UTC，而 MES 各表的时间列都是 naive UTC；
        # 直接写会撞 asyncpg 的 DataError（带时区减不带时区），进门就先归一。
        sim_now = sim_now.replace(tzinfo=None)
        masters = await self._open_work_orders(cfg)
        if not masters:
            return {"reports_created": 0, "containers_reported": 0, "work_orders_touched": 0}

        reports_created = 0
        containers_reported = 0
        budget = cfg.max_work_orders_per_pulse
        rates = await self._daily_pieces_by_order(cfg.factory_id, [str(m.id) for m in masters])
        fallback_count = sum(1 for m in masters if rates.get(str(m.id), 0) <= 0)
        per_order_daily = max(1, cfg.daily_capacity // max(1, min(budget, len(masters))))
        station_by_code = {s.station_code: s for s in stations}
        # 订单状态先攒起来，循环结束后按状态各合成一条 UPDATE
        done_order_ids: List[str] = []
        wip_order_ids: List[str] = []
        issued_lines = 0
        issued_qty = 0
        orders_without_bom = 0
        bom_sources: Dict[str, int] = {}
        material_shortages: List[Dict[str, Any]] = []

        sim_start = sim_now - timedelta(hours=max(0.5, cfg.sim_step_hours))
        predicted: List[Dict[str, Any]] = []
        for master in masters:
            if reports_created >= budget:
                break
            remaining = max(0, (master.planned_qty or 0) - (master.completed_qty or 0))
            if remaining <= 0:
                master.status = "completed"
                master.actual_complete = master.actual_complete or sim_now
                continue
            # 这一拍该出多少：映射到的日产能 × 仿真过了多少时间（一天=24 仿真小时）。
            # 映射不到产能的单才回落到脉搏总产能均分，回执里把回落有几张报出来。
            daily = float(rates.get(str(master.id)) or 0)
            rate = daily if daily > 0 else float(per_order_daily)
            qty = progress_qty(daily, cfg.sim_step_hours, remaining, per_order_daily)
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
                operation_name="虚拟工厂节奏报工（按仿真时钟推进）",
                start_time=sim_start,
                end_time=sim_now,
                remark=(f"{VIRTUAL_MARKER} sim_step_hours={cfg.sim_step_hours} "
                        f"daily_pieces={daily if daily > 0 else 'fallback'} "
                        f"rate={rate:.2f}/日 sim_now={sim_now.isoformat()}"),
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
                master.actual_complete = sim_now
            else:
                left = max(0, (master.planned_qty or 0) - (master.completed_qty or 0))
                predicted.append({
                    "work_order_code": master.work_order_code,
                    "remaining": left,
                    "daily_pieces": round(rate, 2),
                    "predicted_completion": (sim_now + timedelta(
                        days=left / rate if rate > 0 else 0)).isoformat(),
                })
            # 销售订单状态只跟着虚拟工厂自己创建的单据走：BOM/ERP 映射进来的需求单是参考数据，
            # 执行结果落在工单上（工单才是担任务的对象），不回写需求侧的原始记录。
            if str(master.created_by or "") == "virtual_factory":
                (done_order_ids if master.status == "completed" else wip_order_ids).append(
                    master.sales_order_id)

            reports_created += 1
            containers_reported += qty

            # 完工入库：合格产出要真的进库存，否则父层齐套门永远等不到下级做完
            # （production_in 以前只存在于枚举里，没有任何代码写过它）
            await InventoryService(self.db).record_production_output(
                factory_id=cfg.factory_id,
                work_order_id=master.id,
                product_code=master.product_id,
                qty=good_qty,
                created_by=cfg.operator,
            )

            # 报工即领料：按他上传的 BOM 扣物料并逐条记流水；欠料只上报，不打回生产
            issue = await InventoryService(self.db).issue_materials_for_production(
                factory_id=cfg.factory_id,
                work_order_id=master.id,
                product_code=master.product_id,
                output_qty=good_qty,
                created_by=cfg.operator,
            )
            issued_lines += issue.get("issued_lines", 0)
            issued_qty += issue.get("issued_qty", 0)
            if issue.get("bom_source") not in (None, "none"):
                bom_sources[issue["bom_source"]] = bom_sources.get(issue["bom_source"], 0) + 1
            if issue.get("reason") == "no_bom" and good_qty > 0:
                orders_without_bom += 1
            for short in issue.get("shortages") or []:
                material_shortages.append({
                    "work_order_code": master.work_order_code,
                    "material_code": short["material_code"],
                    "required": short["required"],
                    "issued": short["issued"],
                    "reason": short["reason"],
                })

        # 原来是每个工单一句 UPDATE，这里按状态各合成一句
        batch_stmt = text("""
            UPDATE sales_orders
            SET status = :status, updated_at = :now
            WHERE id IN :ids
        """).bindparams(bindparam("ids", expanding=True))
        for status_value, ids in (("completed", done_order_ids), ("in_progress", wip_order_ids)):
            ids = [i for i in ids if i]
            if ids:
                await self.db.execute(
                    batch_stmt, {"status": status_value, "now": datetime.utcnow(), "ids": ids}
                )

        return {
            "reports_created": reports_created,
            "containers_reported": containers_reported,
            "work_orders_touched": reports_created,
            "work_scope": cfg.work_scope,
            "candidates": len(masters),
            "per_pulse_budget": budget,
            "sim_step_hours": cfg.sim_step_hours,
            "sim_now": sim_now.isoformat(),
            # 日产能是从 station_capacity（口径=一天可完成几件）映射来的；
            # 映射不到的单回落到脉搏总产能均分，这里报数量不报假来源。
            "rate_mapped_orders": len(masters) - fallback_count,
            "rate_fallback_orders": fallback_count,
            "predicted_completion_samples": predicted[:5],
            "daily_capacity_containers": cfg.daily_capacity,
            # 本轮领料：按 BOM 真扣了多少、哪里欠、哪些产品没 BOM 可扣
            "materials_issued_lines": issued_lines,
            "materials_issued_qty": issued_qty,
            "material_shortages": material_shortages,
            "orders_without_bom": orders_without_bom,
            "bom_sources": bom_sources,
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
                # 同一工单在 TTL 内只落一条通知（原实现每轮都插）
                if not await get_clock().claim(
                    cfg.factory_id, f"alert:rhythm:{wo.id}", ALERT_CLAIM_TTL_SECONDS
                ):
                    alert["notification"] = "suppressed(recent)"
                    continue
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
