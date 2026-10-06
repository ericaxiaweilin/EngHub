"""

APS 排程服务 - 桥接 DB 数据与 HybridScheduler 核心算法

"""

import hashlib

import uuid

import logging

from datetime import datetime, timedelta, time as dtime, date as ddate

from typing import Optional, List, Dict, Any

from sqlalchemy import select, func, and_, or_, text

from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (

    WorkOrder, Equipment, Routing, RoutingTemplate, RoutingTemplateStep,

    ApsSchedule, ApsScheduleTask,
    ApsPlanEvent, Station,

)

from core.mes.capacity_math import load_station_models, summarize_load  # 工位日历与负荷的唯一口径

from api.services.idle_capacity import crew_by_station as crew_by_station_map
from api.services.schedule_objective import normalize_objective, order_rank
from api.services.time_basis import declared_step_seconds, load_time_basis, BASIS_NONE

from core.mes.hybrid_scheduler import (

    HybridScheduler, SchedulingMode, SchedulingPriority,

)

logger = logging.getLogger(__name__)

# ── 输入指纹（写量刹车）───────────────────────────────────────────────
# 排程算法是确定性的：同样的输入必给同样的输出。线上每次"再跑一遍"都要新写
# 21~459 行 aps_schedule_tasks，而 304 份草案里 95% 从未被确认——写的全是重复。
# 所以先把"这一版计划由哪些事实决定"哈希成一个指纹：指纹没变就把那份还没归档的方案
# 交回去（回 reused=true，一行都不写），指纹变了才重排。
# 复用不要求它还是 draft：确认/下达过的方案同样代表这一组输入，再逼出一版新草案
# 只会让"逐单门把方案置为 released"变成自激环（每轮多写 ~961 行）。
# 这里只哈希排程真正读到的东西，且每段都回报它实际覆盖了多少行，
# 免得"没比对"被当成"比对通过"。
OPEN_WO_SCOPE = """
    wo.factory_id = :fid
      AND wo.wo_type IN ('master', 'component')
      AND wo.status IN ('released', 'in_progress', 'pending')
"""

FINGERPRINT_SQL: Dict[str, str] = {
    # 工单池：哪些单要排、各排多少、什么时候要、绑的是哪条路线。
    # 状态取"在不在池子里"这个桶而不是原值：released/in_progress/pending 三态对排程等价
    # （订单约束那段完全不读状态），拿原值的话逐单门每放行一张都会把指纹打散、逼出一版新草案。
    "orders": f"""
        SELECT COALESCE(md5(string_agg(r, '#' ORDER BY r)), '') AS fp, count(*) AS rows_in FROM (
            SELECT concat(wo.id, '|', CASE WHEN wo.status IN ('released', 'in_progress', 'pending')
                                           THEN 'open' ELSE wo.status END, '|', wo.wo_type, '|', wo.product_id, '|',
                           wo.planned_qty, '|', wo.good_qty, '|', wo.priority, '|',
                           to_char(wo.planned_start, 'IYYYIWIDTHH24MISS'), '|',
                           to_char(wo.planned_due, 'IYYYIWIDTHH24MISS'), '|',
                           wo.routing_template_id, '|', wo.routing_id) AS r
            FROM work_orders wo WHERE {OPEN_WO_SCOPE}
        ) s
    """,
    # 工艺路线：模板工步（顺序/工时/允许工位）与旧版 routings.steps JSON
    "routes": f"""
        SELECT COALESCE(md5(string_agg(r, '#' ORDER BY r)), '') AS fp, count(*) AS rows_in FROM (
            SELECT concat('T|', s.template_id, '|', s.seq, '|', s.operation_name, '|',
                           s.work_center, '|', s.standard_hours) AS r
            FROM routing_template_steps s
            WHERE s.template_id IN (
                SELECT DISTINCT wo.routing_template_id FROM work_orders wo
                WHERE {OPEN_WO_SCOPE} AND wo.routing_template_id IS NOT NULL
            )
            UNION ALL
            SELECT concat('R|', rt.id, '|', md5(rt.steps::text)) AS r
            FROM routings rt
            WHERE rt.id IN (
                SELECT DISTINCT wo.routing_id FROM work_orders wo
                WHERE {OPEN_WO_SCOPE} AND wo.routing_id IS NOT NULL
            )
        ) x
    """,
    # 工位产能：并发、OEE、换型、日可完成件数
    "capacity": """
        SELECT COALESCE(md5(string_agg(r, '#' ORDER BY r)), '') AS fp, count(*) AS rows_in FROM (
            SELECT concat(sc.station_id, '|', sc.available_hours_per_day, '|', sc.efficiency_rate, '|',
                           sc.setup_time_minutes, '|', sc.max_concurrent_orders, '|', sc.required_skills) AS r
            FROM station_capacity sc WHERE sc.factory_id = :fid AND sc.is_active = TRUE
        ) c
    """,
    # 设备：按工位聚合"还剩几台可用"（与 is_broken 的判据同一口径）
    "equipment": """
        SELECT COALESCE(md5(string_agg(r, '#' ORDER BY r)), '') AS fp, count(*) AS rows_in FROM (
            SELECT concat(g.home, '|', g.total, '|', g.usable) AS r FROM (
                SELECT COALESCE(eq.station_id, eq.equipment_code) AS home, count(*) AS total,
                       count(*) FILTER (WHERE eq.status NOT IN ('broken', 'maintenance')) AS usable
                FROM equipment eq WHERE eq.factory_id = :fid GROUP BY 1
            ) g
        ) e
    """,
    # 班次日历（本厂 + 平台 default 回落）与计划期内的假期/补班
    "calendar": """
        SELECT COALESCE(md5(string_agg(r, '#' ORDER BY r)), '') AS fp, count(*) AS rows_in FROM (
            SELECT concat('S|', cal.factory_id, '|', cal.resource_id, '|', cal.day_of_week, '|',
                           cal.start_time, '|', cal.end_time, '|', cal.is_active) AS r
            FROM aps_work_calendars cal
            WHERE cal.factory_id IN (:fid, 'default') AND cal.is_active = TRUE
            UNION ALL
            SELECT concat('H|', h.holiday_date, '|', h.is_working_day) AS r
            FROM aps_holidays h
            WHERE h.factory_id IN (:fid, 'default') AND COALESCE(h.is_active, TRUE) = TRUE
              AND h.holiday_date BETWEEN :hs_date AND :he_date
        ) k
    """,
    # 齐套就绪：排程只用到"这张单有没有缺口"这一个布尔（不是每行物料）
    "material_readiness": f"""
        SELECT COALESCE(md5(string_agg(r, '#' ORDER BY r)), '') AS fp, count(*) AS rows_in FROM (
            SELECT concat(wo.id, '|', CASE WHEN COALESCE(m.shortage_rows, 0) > 0 THEN 1 ELSE 0 END) AS r
            FROM work_orders wo
            LEFT JOIN (
                SELECT work_order_id,
                       SUM(CASE WHEN COALESCE(shortage_qty, 0) > 0 THEN 1 ELSE 0 END) AS shortage_rows
                FROM work_order_materials GROUP BY work_order_id
            ) m ON m.work_order_id = wo.id
            WHERE {OPEN_WO_SCOPE}
        ) mm
    """,
    # 计划员钉住的工序：跨版本取每道工序最新一行（与 load_pinned_tasks 同口径）
    "pinned_steps": """
        SELECT COALESCE(md5(string_agg(r, '#' ORDER BY r)), '') AS fp, count(*) AS rows_in FROM (
            WITH latest_per_op AS (
                SELECT DISTINCT ON (t.work_order_id, t.operation_seq)
                       t.work_order_id, t.operation_seq, t.station_id,
                       t.planned_start, t.planned_end, t.is_locked
                FROM aps_schedule_tasks t
                JOIN aps_schedules s ON s.id = t.schedule_id
                WHERE s.factory_id = :fid AND COALESCE(t.status, '') NOT IN ('completed', 'cancelled')
                ORDER BY t.work_order_id, t.operation_seq, s.version_number DESC, t.created_at DESC
            )
            SELECT concat(p.work_order_id, '|', p.operation_seq, '|', p.station_id, '|',
                           to_char(p.planned_start, 'IYYYIWIDTHH24MISS'), '|',
                           to_char(p.planned_end, 'IYYYIWIDTHH24MISS')) AS r
            FROM latest_per_op p
            WHERE p.is_locked = TRUE AND p.planned_end >= :now
        ) l
    """,
}

REUSE_SQL = text("""
    SELECT id, schedule_code, version_number, created_at, created_by, status, total_tasks,
           unscheduled_count, on_time_rate, avg_utilization, avg_cycle_hours,
           total_setup_minutes
    FROM aps_schedules
    WHERE factory_id = :fid AND mode = :mode AND optimize_for = :optimize_for
      AND status <> 'archived'
      AND horizon_start = :hs AND horizon_end = :he
      AND input_fingerprint = :fp
    ORDER BY created_at DESC
    LIMIT 1
""")

SNAPSHOT_SQL = text("""
    SELECT payload FROM aps_plan_events
    WHERE schedule_id = :sid AND event_type = 'schedule_generated'
    ORDER BY created_at DESC LIMIT 1
""")

# 诊断明细留在事件里：一份草案的未排清单可能有上百条，留前 N 条足够复核，
# 超出部分记 truncated 与总数，不假装完整。
SNAPSHOT_LIMIT = 60


# 优先级映射

PRIORITY_MAP = {

    "low": SchedulingPriority.LOW,

    "medium": SchedulingPriority.NORMAL,

    "high": SchedulingPriority.HIGH,

    "urgent": SchedulingPriority.URGENT,

    "emergency": SchedulingPriority.EMERGENCY,

}

class ApsService:

    """APS 排程服务"""

        

    

    async def reschedule_incremente(
        self,
        factory_id: str,
        affected_wo_ids: List[str],
        created_by: str = "system",
    ) -> Dict[str, Any]:
        """增量重排：仅对受影响的工单进行局部重算
        
        Args:
            factory_id: 工厂ID
            affected_wo_ids: 需要重新排程的工单ID列表（受影响的部分）
            created_by: 操作用户
        
        Returns:
            {
                "success": bool,
                "schedule_id": Optional[str],
                "affected_wo_count": int,
                "tasks_processed": int,
                "message": str,
                "diff_report": Dict,
                "metrics": Dict,
            }
        """
        if not affected_wo_ids:
            return {
                "success": True,
                "schedule_id": None,
                "affected_wo_count": 0,
                "tasks_processed": 0,
                "message": "无工单需要重排",
                "diff_report": {},
                "metrics": {},
            }

        # 现阶段使用同一主引擎做全量重算，并明确标记受影响工单；
        # 不再返回内存拼造的“增量任务”，避免前端看到不存在于数据库的计划。
        result = await self.reschedule(
            factory_id=factory_id,
            created_by=created_by,
            change_reason=f"incremental:{','.join(affected_wo_ids)}",
        )
        result["affected_wo_count"] = len(affected_wo_ids)
        result["tasks_processed"] = result.get("total_tasks", 0)
        return result

    def __init__(self, db: AsyncSession):

        self.db = db

    @staticmethod
    def _routing_step_seconds(step: Dict[str, Any]) -> float:
        """统一旧 Routing JSON 与模板路线的工时单位；没有声明就是 0，不补默认值。"""
        return declared_step_seconds(step) or 0.0

    async def _load_calendar_constraints(
        self,
        factory_id: str,
        resource_id: str,
        horizon_start: datetime,
        horizon_end: datetime,
    ) -> Dict[str, Any]:
        """读取工厂/资源日历和日期级假期，不在算法内写死班次。

        口径统一走 core.mes.capacity_math：具体工厂没配日历时先回落到平台班次表
        （aps_work_calendars 里 factory_id='default' 那 6 行），最后才用代码兜底值。
        以前这里只查 factory_id=具体工厂，那 6 行维护的班次从来没被读到，
        只是恰好和代码兜底值相同才没露馅。
        """
        models = await load_station_models(
            self.db, factory_id, [resource_id], horizon_start, horizon_end
        )
        model = models.get(str(resource_id))
        if not model or not model.slots_by_weekday:
            # 与排程引擎一致的兼容默认：周一~周六 08:00-20:00，且仅在没有任何日历时生效
            return {
                "calendar_by_weekday": {dow: [(dtime(8, 0), dtime(20, 0))] for dow in range(6)},
                "blocked_dates": set(),
                "working_dates": set(),
                "calendar_source": "code_fallback",
            }
        return {
            "calendar_by_weekday": model.slots_by_weekday,
            "blocked_dates": model.blocked_dates,
            "working_dates": model.working_dates,
            "calendar_source": model.calendar_source,
        }

    async def _input_fingerprint(
        self,
        factory_id: str,
        *,
        mode: str,
        optimize_for: str,
        horizon_days: int,
        horizon_start: datetime,
        horizon_end: datetime,
        excluded: set,
    ) -> tuple:
        """把这一版计划的全部输入压成一个指纹，并回报每段覆盖了多少行。

        空字符串的段（比如本厂没有钉住工序）照样参与拼接，但会标 rows=0，
        这样"比对了、确实没有"和"没比对"在回执里是分得开的。
        """
        params = {
            "fid": factory_id, "hs": horizon_start, "he": horizon_end,
            "hs_date": horizon_start.date(), "he_date": horizon_end.date(),
            "now": datetime.utcnow(),
        }
        parts: Dict[str, Dict[str, Any]] = {}
        for name, sql in FINGERPRINT_SQL.items():
            row = (await self.db.execute(text(sql), params)).mappings().first()
            parts[name] = {
                "fingerprint": str((row["fp"] if row else "") or ""),
                "rows": int(row["rows_in"] if row else 0),
            }
        request = "|".join([
            str(mode), str(optimize_for), str(int(horizon_days)),
            horizon_start.isoformat(), ",".join(sorted(excluded)),
        ])
        parts["request"] = {"fingerprint": hashlib.md5(request.encode("utf-8")).hexdigest(),
                            "rows": 1}
        digest = hashlib.md5("#".join(
            f"{key}:{parts[key]['fingerprint']}" for key in sorted(parts)
        ).encode("utf-8")).hexdigest()
        return digest, parts

    async def _reused_draft(
        self,
        draft: Any,
        *,
        fingerprint: str,
        parts: Dict[str, Dict[str, Any]],
        horizon_days: int,
        horizon_start: datetime,
        horizon_end: datetime,
        created_by: str,
        change_reason: str,
    ) -> Dict[str, Any]:
        """输入没变就交回已有草案：一行都不写，但把当初的结论原样带回来。

        未排清单与约束原因不重算，而是读那份草案生成时写进 aps_plan_events 的快照；
        快照是这次改动之前写的（没有诊断明细）就如实说"明细未留存"，不补一份新的冒充。
        """
        schedule_id = str(draft["id"])
        plan_status = str(draft["status"] or "draft")
        task_rows = int((await self.db.execute(text(
            "SELECT count(*) FROM aps_schedule_tasks WHERE schedule_id = :sid"
        ), {"sid": schedule_id})).scalar() or 0)
        locked_rows = int((await self.db.execute(text(
            "SELECT count(*) FROM aps_schedule_tasks WHERE schedule_id = :sid AND COALESCE(is_locked, FALSE)"
        ), {"sid": schedule_id})).scalar() or 0)
        event = (await self.db.execute(SNAPSHOT_SQL, {"sid": schedule_id})).mappings().first()
        snapshot = event["payload"] if event and isinstance(event["payload"], dict) else {}
        unscheduled = snapshot.get("unscheduled_orders")
        diagnostics = snapshot.get("diagnostics") or {}
        age_seconds = (datetime.utcnow() - (draft["created_at"] or datetime.utcnow())).total_seconds()
        state = "草案" if plan_status == "draft" else f"{plan_status}计划"
        message = (
            f"输入未变，复用{state} {draft['schedule_code']}（v{draft['version_number']}，"
            f"{age_seconds / 60:.0f} 分钟前生成，{task_rows} 行任务）：本次不新增写入。"
        )
        if not snapshot:
            message += " 注意：该草案没有留存的诊断快照，未排原因只能到界面重新触发一次才能看到。"
        logger.info(
            "[aps] 复用草案 %s（指纹 %s，输入未变）：跳过 %s 行任务写入",
            schedule_id, fingerprint[:8], task_rows,
        )
        return {
            "success": bool(snapshot.get("success", True)),
            "reused": True,
            "schedule_id": schedule_id,
            "schedule_code": draft["schedule_code"],
            "schedule_status": plan_status,
            "version_number": draft["version_number"],
            "created_by": draft["created_by"],
            "generated_at": draft["created_at"].isoformat() if draft["created_at"] else None,
            "total_tasks": task_rows,
            "pinned_tasks": locked_rows,
            "unscheduled_orders": unscheduled if unscheduled is not None else [],
            "unscheduled_count": int(draft["unscheduled_count"] or 0),
            "constraint_violation_count": int(snapshot.get("constraint_violation_count") or 0),
            "horizon_days": horizon_days,
            "horizon": f"{horizon_days}天",
            "horizon_start": horizon_start.isoformat(),
            "horizon_end": horizon_end.isoformat(),
            "input_summary": {
                "input_fingerprint": fingerprint,
                "fingerprint_parts": parts,
                "reused_schedule_id": schedule_id,
                "requested_by": created_by,
                "change_reason": change_reason,
                "new_rows_written": {"aps_schedules": 0, "aps_schedule_tasks": 0},
            },
            "diagnostics": {
                "unscheduled": diagnostics.get("unscheduled") or [],
                "unscheduled_total": int(diagnostics.get("unscheduled_total") or 0),
                "constraint_violations": diagnostics.get("constraint_violations") or [],
                "violations_total": int(diagnostics.get("violations_total") or 0),
                "data_integrity": diagnostics.get("data_integrity") or [],
                "snapshot_available": bool(snapshot),
                "snapshot_capped_at": int(diagnostics.get("snapshot_limit") or SNAPSHOT_LIMIT),
            },
            "station_loads": snapshot.get("station_loads") or [],
            "rule_explanation": snapshot.get("rule_explanation") or "",
            "metrics": {
                "on_time_delivery_rate": draft["on_time_rate"],
                "avg_resource_utilization": draft["avg_utilization"],
                "avg_manufacturing_cycle": draft["avg_cycle_hours"],
                "total_setup_time": draft["total_setup_minutes"],
            },
            "message": message,
        }

    async def _shortage_order_ids(self, factory_id: str) -> set:
        """有物料缺口的工单 id。排产顺序要认它：缺料的排后面，别占着工位时隙。

        口径与就绪门一致（`work_order_materials.shortage_qty > 0`），不另立一套：
        两处判断不一致时，会出现"排产以为它能干、门说不能干"的空转。
        """
        rows = (await self.db.execute(text("""
            SELECT DISTINCT m.work_order_id
            FROM work_order_materials m
            JOIN work_orders w ON w.id = m.work_order_id
            WHERE w.factory_id = :fid
              AND COALESCE(m.shortage_qty, 0) > 0
        """), {"fid": factory_id})).all()
        return {str(r[0]) for r in rows}

    async def generate_schedule(

        self,

        factory_id: str,

        mode: str = "hybrid",

        horizon_days: int = 30,

        optimize_for: str = "delivery",

        created_by: str = "system",

        change_reason: str = "manual_generation",

        exclude_resources: Optional[List[str]] = None,

        force: bool = False,

    ) -> Dict[str, Any]:

        """生成排程方案
        exclude_resources 用于"某工位今天停用/设备故障"这类约束：这些工位不进本轮资源，
        受影响工序只会被排到工艺路线允许的其他工位上，排不进就带着原因报出来，
        而不是被随手塞到任意空闲工位。

        force=True 才绕过输入指纹强制重排。默认走指纹门：算法是确定性的，输入没变
        再跑一遍只会多写几百行任务明细，那些行和上一版一模一样。
        """

        # 目标词汇只留一套：API 历史上的 delivery/cost 等别名先进 cost_model 的目标名，
        # 否则同一个目标会因为写法不同被存成两版、被指纹当成两回事。
        optimize_for = normalize_objective(optimize_for)

        excluded = {str(x).strip() for x in (exclude_resources or []) if str(x).strip()}

        now = datetime.utcnow()

        horizon_start = now.replace(hour=8, minute=0, second=0, microsecond=0)

        horizon_end = horizon_start + timedelta(days=horizon_days)

        fingerprint, fp_parts = await self._input_fingerprint(
            factory_id, mode=mode, optimize_for=optimize_for, horizon_days=horizon_days,
            horizon_start=horizon_start, horizon_end=horizon_end, excluded=excluded,
        )
        if not force:
            draft = (await self.db.execute(REUSE_SQL, {
                "fid": factory_id, "mode": mode, "optimize_for": optimize_for,
                "hs": horizon_start, "he": horizon_end, "fp": fingerprint,
            })).mappings().first()
            if draft is not None:
                return await self._reused_draft(
                    draft, fingerprint=fingerprint, parts=fp_parts,
                    horizon_days=horizon_days, horizon_start=horizon_start,
                    horizon_end=horizon_end, created_by=created_by, change_reason=change_reason,
                )

        # 1. 加载待排工单（已下达/执行中的主工单）

        wo_stmt = select(WorkOrder).where(

            WorkOrder.factory_id == factory_id,

            # 子装配件工单和主工单一起排：它们有各自的路线与工位，
            # 只排 master 的话半成品工单永远没有任务，车间还是开不了工
            WorkOrder.wo_type.in_(["master", "component"]),

            WorkOrder.status.in_(["released", "in_progress", "pending"]),

        ).order_by(WorkOrder.priority.desc(), WorkOrder.planned_due.asc().nullslast())

        wo_result = await self.db.execute(wo_stmt)

        work_orders = list(wo_result.scalars().all())

        if not work_orders:

            return {"success": False, "message": "无待排程工单", "schedule_id": None}

        # 排产顺序由目标函数决定（见下面第 4 格 order_rank），不在这里再排一遍：
        # 两处各排一次，会出现"排产以为它能干、门说不能干"那种对不上的账。
        shortage_ids = await self._shortage_order_ids(factory_id)

        # 2. 加载工艺路线约束

        scheduler = HybridScheduler()

        for _excluded in sorted(excluded):
            scheduler.unavailable_notes[_excluded] = "该工位本轮被停用（设备故障或人工排除），不参与排程"

        product_routings: Dict[str, List[Dict]] = {}
        unrouted_orders: List[str] = []
        # 有路线但一道工序工时都没有的单：不进排程，理由要和"没路线"分开点名
        no_hours_orders: List[str] = []
        # 单件工时必须有名有姓：工步自己声明 > 厂里声明的线产能 > 工位主档产能，
        # 三条都给不出就记 no_time_basis，绝不回落到"5 分钟换型"那种编的数。
        time_basis = await load_time_basis(self.db, factory_id)
        step_basis: Dict[str, str] = {}

        for wo in work_orders:

            if wo.routing_template_id:

                if wo.product_id not in product_routings:
                    routing_template_id = str(wo.routing_template_id)

                    steps_stmt = select(RoutingTemplateStep).where(

                        RoutingTemplateStep.template_id == routing_template_id

                    ).order_by(RoutingTemplateStep.seq)

                    steps_result = await self.db.execute(steps_stmt)

                    steps = list(steps_result.scalars().all())

                    if steps:

                        template_ops = []

                        for s in steps:

                            seconds, used = time_basis.seconds_per_piece(

                                model=str(wo.product_id),

                                station=str(s.work_center or ""),

                                step={"standard_hours": float(s.standard_hours or 0) or None},

                            )

                            template_ops.append({

                                "sequence": s.seq * 10,

                                "name": s.operation_name,

                                "standard_time": seconds or 0.0,

                                "setup_time": 0.0,  # 模板路线没有换型声明，不补 5 分钟

                                "allowed_stations": [s.work_center] if s.work_center else [],

                                "required_skills": [],

                            })

                            step_basis[f"{wo.product_id}|{s.seq * 10}"] = used

                        product_routings[wo.product_id] = template_ops

            elif wo.routing_id:
                # 兼容旧版 routings.steps JSON；新工单优先使用模板路线，
                # 但历史工单没有模板绑定时也必须进入同一套 APS 引擎。
                routing = await self.db.get(Routing, str(wo.routing_id))
                if routing and isinstance(routing.steps, list) and routing.steps:
                    json_ops = []
                    for idx, step in enumerate(routing.steps):
                        sequence = int(step.get("sequence", step.get("seq", (idx + 1) * 10)))
                        station = str(step.get("station") or step.get("work_center") or "")
                        seconds, used = time_basis.seconds_per_piece(
                            model=str(wo.product_id), station=station, step=step
                        )
                        json_ops.append({
                            "sequence": sequence,
                            "name": step.get("name", step.get("operation_name", f"工序{idx + 1}")),
                            "standard_time": seconds or 0.0,
                            "setup_time": float(step.get("setup_time") or 0),
                            "allowed_stations": [station] if station else [],
                            "required_skills": step.get("required_skills", []),
                        })
                        step_basis[f"{wo.product_id}|{sequence}"] = used
                    product_routings[wo.product_id] = json_ops

            # 如果产品有工艺路线，加载到排程器。
            # 但"有路线"不等于"有工时"：一条路线里如果每道工序都没有 IE 给的单件工时，
            # 就不许进排程 —— 以前它们会落到"0 秒/件 + 300 秒换型"的兜底，
            # 账面排满、交期看着宽裕，车间实际拿到的是假时间。
            if wo.product_id in product_routings:
                ops = product_routings[wo.product_id]
                has_ie_hours = any(
                    step_basis.get(f"{wo.product_id}|{op.get('sequence')}") not in (None, BASIS_NONE)
                    for op in ops
                )
                if has_ie_hours:
                    scheduler.load_process_constraints(wo.product_id, ops)
                else:
                    no_hours_orders.append(str(wo.id))
            else:
                unrouted_orders.append(str(wo.id))

        products_with_ie_hours = {
            key.split("|", 1)[0] for key, used in step_basis.items() if used != BASIS_NONE
        }
        no_hours_products = sorted({
            str(wo.product_id) for wo in work_orders
            if wo.product_id in product_routings and str(wo.product_id) not in products_with_ie_hours
        })

        # 3. 加载资源约束（设备/工位、真实产能、班次和假期）

        capacity_result = await self.db.execute(text("""
            SELECT station_id, available_hours_per_day, efficiency_rate,
                   setup_time_minutes, max_concurrent_orders
            FROM station_capacity
            WHERE factory_id = :factory_id AND is_active = TRUE
        """), {"factory_id": factory_id})
        capacity_map = {row["station_id"]: dict(row) for row in capacity_result.mappings().all()}

        eq_stmt = select(Equipment).where(

            Equipment.factory_id == factory_id,

        )

        eq_result = await self.db.execute(eq_stmt)

        equipments = list(eq_result.scalars().all())

        # 收集所有需要的工位

        needed_stations = set()

        for ops in product_routings.values():

            for op in ops:

                needed_stations.update(op.get("allowed_stations", []))

        # 工艺路线里的 work_center 必须是本厂登记的工位。跨厂借用（机械厂的工序
        # 指向电子厂的台账）不会报错，但负荷、设备归属、产能全部对不上，必须显式报给计划员。
        used_station_codes = sorted({str(code) for code in needed_stations if code})
        station_ownership: Dict[str, str] = {}
        if used_station_codes:
            ownership_result = await self.db.execute(
                select(Station.station_code, Station.factory_id).where(
                    Station.station_code.in_(used_station_codes)
                )
            )
            station_ownership = {
                str(row[0]): str(row[1]) for row in ownership_result.all() if row[0]
            }

        data_integrity_warnings: List[Dict[str, Any]] = []
        for code in used_station_codes:
            owner = station_ownership.get(code)
            if owner is None:
                data_integrity_warnings.append({
                    "station_code": code,
                    "issue": "not_registered",
                    "severity": "warning",
                    "detail": (
                        f"工艺路线引用工位 {code}，但 stations 主数据里没有这个编码，"
                        "排程只能把它当虚拟资源用，没有设备、没有日历来源。"
                    ),
                })
            elif owner != factory_id:
                data_integrity_warnings.append({
                    "station_code": code,
                    "issue": "owned_by_other_factory",
                    "severity": "error",
                    "owner_factory_id": owner,
                    "detail": (
                        f"工艺路线引用工位 {code}，但它登记在工厂 {owner} 名下，"
                        f"本厂（{factory_id}）并没有该工位；工序会排到别的厂的台账上。"
                    ),
                })
            if code not in capacity_map:
                data_integrity_warnings.append({
                    "station_code": code,
                    "issue": "no_capacity_record",
                    "severity": "warning",
                    "detail": (
                        f"工位 {code} 在本厂没有 station_capacity 记录，"
                        "排程按默认 OEE 与单件流估算，产能数字不可信。"
                    ),
                })

        # 加载设备作为资源：按工位聚合其下所有设备，只要还有可用设备该工位就可排，
        # 避免扫到哪台设备就决定整个工位健康度。
        station_equipment: Dict[str, List] = {}
        for eq in equipments:
            resource_id = eq.station_id or eq.equipment_code
            if resource_id:
                station_equipment.setdefault(resource_id, []).append(eq)

        loaded_resources = set()

        for resource_id, eq_rows in station_equipment.items():

            if resource_id in excluded:

                continue

            if resource_id not in loaded_resources:

                is_broken = all(
                    eq.status in ("broken", "maintenance") for eq in eq_rows
                )
                capacity = capacity_map.get(resource_id, {})
                calendar = await self._load_calendar_constraints(
                    factory_id, resource_id, horizon_start, horizon_end
                )

                scheduler.load_resource_constraints(

                    resource_id=resource_id,

                    available_from=horizon_start,

                    available_to=horizon_end,

                    capacity=int(capacity.get("max_concurrent_orders") or 1),

                    oee=float(capacity.get("efficiency_rate") or 0.85),

                    calendar_by_weekday=calendar["calendar_by_weekday"],

                    blocked_dates=calendar["blocked_dates"],

                    working_dates=calendar["working_dates"],

                    is_broken=is_broken,

                )

                loaded_resources.add(resource_id)

        # 如果没有设备数据，用工艺路线中的工位创建虚拟资源

        for station in needed_stations:

            if station in excluded:

                continue

            if station and station not in loaded_resources:
                capacity = capacity_map.get(station, {})
                calendar = await self._load_calendar_constraints(
                    factory_id, station, horizon_start, horizon_end
                )

                scheduler.load_resource_constraints(

                    resource_id=station,

                    available_from=horizon_start,

                    available_to=horizon_end,

                    capacity=int(capacity.get("max_concurrent_orders") or 1),

                    oee=float(capacity.get("efficiency_rate") or 0.9),

                    calendar_by_weekday=calendar["calendar_by_weekday"],

                    blocked_dates=calendar["blocked_dates"],

                    working_dates=calendar["working_dates"],

                )

                loaded_resources.add(station)

        # 如果设备和工艺路线工位都没有，回退使用工厂工位表

        if not loaded_resources:

            st_stmt = select(Station).where(

                Station.factory_id == factory_id,

                Station.status == "active",

            )

            st_result = await self.db.execute(st_stmt)

            for st in st_result.scalars().all():

                rid = st.station_code or str(st.id)

                if rid in excluded:

                    continue

                if rid not in loaded_resources:
                    capacity = capacity_map.get(rid, {})
                    calendar = await self._load_calendar_constraints(
                        factory_id, rid, horizon_start, horizon_end
                    )

                    scheduler.load_resource_constraints(

                        resource_id=rid,

                        available_from=horizon_start,

                        available_to=horizon_end,

                        capacity=int(capacity.get("max_concurrent_orders") or 1),

                        oee=float(capacity.get("efficiency_rate") or 0.9),

                        calendar_by_weekday=calendar["calendar_by_weekday"],

                        blocked_dates=calendar["blocked_dates"],

                        working_dates=calendar["working_dates"],

                    )

                    loaded_resources.add(rid)

        if not loaded_resources:

            return {"success": False, "message": "无可用资源（设备/工位）", "schedule_id": None}

        # 4. 排产目标函数：谁先占产能由 objective 算出来，不再由排程器内部写死的分支决定。
        #    人力项要站得到人：路线工步的工位 → stations 主档名称 → HR 在岗人数，
        #    对不上就是 0 人·时（宁可这项不成立，也不给每台机器假设站 3 个人）。
        crew_by_station = await crew_by_station_map(self.db, factory_id)

        order_features: List[Dict[str, Any]] = []
        for wo in work_orders:
            ops = product_routings.get(wo.product_id) or []
            qty = max(1, int(wo.planned_qty or 1))
            work_hours = sum(float(o.get("standard_time") or 0) * qty for o in ops) / 3600.0
            person_hours = sum(
                float(o.get("standard_time") or 0) * qty / 3600.0
                * crew_by_station.get(str((o.get("allowed_stations") or [""])[0] or ""), 0)
                for o in ops
            )
            due = wo.planned_due or horizon_end
            order_features.append({
                "order_id": str(wo.id),
                "blocked": str(wo.id) in shortage_ids,
                "work_hours": work_hours,
                "person_hours": person_hours,
                "hours_to_due": max(0.0, (due - horizon_start).total_seconds() / 3600.0),
            })
        ranking = order_rank(
            order_features, optimize_for, horizon_hours=float(horizon_days) * 24.0
        )

        # 5. 加载订单约束

        for wo in work_orders:

            if wo.product_id not in product_routings:

                continue  # 无工艺路线的跳过

            priority = PRIORITY_MAP.get(wo.priority, SchedulingPriority.NORMAL)

            release = max(wo.planned_start or horizon_start, horizon_start)

            due = wo.planned_due or horizon_end

            scheduler.load_order_constraints(

                order_id=wo.id,

                product_code=wo.product_id,

                quantity=wo.planned_qty or 1,

                release_date=release,

                due_date=due,

                priority=priority,

            )

        # 4.5 PMC 手动钉住的工序先占回时间轴，本次重排只动没钉住的部分

        pinned_rows = await self.db.execute(
            text("""
                WITH latest_per_op AS (
                    SELECT DISTINCT ON (t.work_order_id, t.operation_seq)
                           t.id AS task_id,
                           t.work_order_id AS order_id,
                           t.operation_seq AS operation_sequence,
                           t.operation_name,
                           t.station_id,
                           t.planned_start AS start_time,
                           t.planned_end AS end_time,
                           t.setup_seconds AS setup_time,
                           t.run_seconds AS run_time,
                           t.quantity,
                           t.status,
                           t.is_locked
                    FROM aps_schedule_tasks t
                    JOIN aps_schedules s ON s.id = t.schedule_id
                    WHERE s.factory_id = :factory_id
                      AND COALESCE(t.status, '') NOT IN ('completed', 'cancelled')
                    ORDER BY t.work_order_id, t.operation_seq,
                             s.version_number DESC, t.created_at DESC
                )
                SELECT task_id, order_id, operation_sequence, operation_name, station_id,
                       start_time, end_time, setup_time, run_time, quantity, status
                FROM latest_per_op
                WHERE is_locked = true AND end_time >= :now
            """),
            {"factory_id": factory_id, "now": now},
        )

        pinned_count = scheduler.load_pinned_tasks(
            [dict(row) for row in pinned_rows.mappings().all()]
        )

        # 5. 执行排程

        sched_mode = SchedulingMode(mode) if mode in ("forward", "backward", "hybrid") else SchedulingMode.HYBRID

        result = scheduler.schedule_hybrid(sched_mode, optimize_for, order_rank=ranking["rank"])

        for _d in getattr(scheduler, "pinned_dropped", None) or []:
            result.constraint_violations.append(
                {"order_id": str(_d.get("order_id") or ""),
                 "reason": "[锁定工序] 工位 %s 本轮不可用（故障停用/未注册），钉住的 %s~%s 已放弃，请复核"
                 % (_d.get("station_id"), _d.get("start_time"), _d.get("end_time"))}
            )

        # 锁定行不改时刻，只把衔接冲突报给计划员复核
        for task in result.schedule:
            for note in getattr(task, "constraint_violations", None) or []:
                result.constraint_violations.append(
                    {"order_id": str(task.order_id), "reason": f"[锁定工序] {note}"}
                )

        if unrouted_orders:
            result.unscheduled_orders = list(dict.fromkeys(
                result.unscheduled_orders + unrouted_orders + no_hours_orders
            ))
            result.constraint_violations.extend(
                {"order_id": wo_id, "reason": "工单没有可用工艺路线"}
                for wo_id in unrouted_orders
            )
            result.constraint_violations.extend(
                {"order_id": wo_id, "reason": "路线里没有任何 IE 给的单件工时（也没落到声明过产能的线上）："
                                             "不给它编预计时间，等 IE 量过再排"}
                for wo_id in no_hours_orders
            )
            result.success = False
            result.message = (
                f"有 {len(unrouted_orders)} 个工单缺少可用工艺路线"
                + (f"；{len(no_hours_orders)} 个工单有路线但没有 IE 工时、暂不排时"
                   if no_hours_orders else "")
            )

        # 生成可解释结果：把“算法跑完”拆成输入、排入、未排和约束原因，供前端审阅。
        work_order_map = {str(wo.id): wo for wo in work_orders}
        scheduled_order_ids = {str(task.order_id) for task in result.schedule}
        violation_by_order: Dict[str, List[str]] = {}
        for violation in result.constraint_violations:
            order_id = str(violation.get("order_id") or "")
            reason = str(violation.get("reason") or "未满足排程约束")
            violation_by_order.setdefault(order_id, []).append(reason)

        unscheduled_details = []
        for order_id in result.unscheduled_orders:
            key = str(order_id)
            wo = work_order_map.get(key)
            due_date = getattr(wo, "planned_due", None) if wo else None
            unscheduled_details.append({
                "order_id": key,
                "work_order_code": getattr(wo, "work_order_code", None) if wo else None,
                "product_id": getattr(wo, "product_id", None) if wo else None,
                "priority": getattr(wo, "priority", None) if wo else None,
                "due_date": due_date.isoformat() if due_date else None,
                "reasons": violation_by_order.get(key, ["未生成排程任务"]),
            })

        violation_details = []
        for violation in result.constraint_violations:
            key = str(violation.get("order_id") or "")
            wo = work_order_map.get(key)
            violation_details.append({
                "order_id": key,
                "work_order_code": getattr(wo, "work_order_code", None) if wo else None,
                "reason": str(violation.get("reason") or "未满足排程约束"),
            })

        station_load_map: Dict[str, Dict[str, Any]] = {}
        for task in result.schedule:
            station_id = str(task.station_id)
            load = station_load_map.setdefault(station_id, {
                "station_id": station_id,
                "task_count": 0,
                "order_ids": set(),
                "load_minutes": 0.0,
                "first_start": task.start_time,
                "last_end": task.end_time,
            })
            load["task_count"] += 1
            load["order_ids"].add(str(task.order_id))
            load["load_minutes"] += max(0.0, (task.end_time - task.start_time).total_seconds() / 60)
            load["first_start"] = min(load["first_start"], task.start_time)
            load["last_end"] = max(load["last_end"], task.end_time)

        station_loads = []
        for load in station_load_map.values():
            load["order_count"] = len(load.pop("order_ids"))
            load["load_minutes"] = round(load["load_minutes"], 1)
            load["load_hours"] = round(load["load_minutes"] / 60, 2)
            load["first_start"] = load["first_start"].isoformat()
            load["last_end"] = load["last_end"].isoformat()
            station_loads.append(load)
        station_loads.sort(key=lambda item: item["load_minutes"], reverse=True)

        rule_explanations = {
            ranking["objective"]: (
                f"目标「{ranking['objective_label']}」："
                f"权重 人力 {ranking['weights']['labor']} / 交期 {ranking['weights']['delivery']}；"
                f"缺料单 {ranking['blocked_last']} 张一律靠后（料不齐开不了工，不该占工位时隙）；"
                f"{ranking['orders_with_person_hours']} 张单能数出在岗人数，"
                f"其余按 0 人·时参与（对不上工位就按 0 算，不假设每台机器都站着人）。"
                f"{ranking['note']}"
            ),
        }
        basis_counts: Dict[str, int] = {}
        for task in result.schedule:
            key = step_basis.get(f"{task.product_code}|{task.operation_sequence}") or BASIS_NONE
            basis_counts[key] = basis_counts.get(key, 0) + 1

        input_summary = {
            "total_orders": len(work_orders),
            "routable_orders": len(work_orders) - len(unrouted_orders),
            "skipped_orders": len(unrouted_orders),
            "orders_without_ie_hours": len(no_hours_orders),
            "products_without_ie_hours": len(no_hours_products),
            "scheduled_orders": len(scheduled_order_ids),
            "unscheduled_orders": len(result.unscheduled_orders),
            "scheduled_tasks": len(result.schedule),
            # 每条任务行的时长来自哪一类出处，必须能在方案上看见；no_time_basis
            # 不为零就是"这些工序的预计时间没有依据"，要报给 IE 补，而不是靠默认值蒙。
            "duration_basis_counts": basis_counts,
            "tasks_without_time_basis": basis_counts.get(BASIS_NONE, 0),
            "objective": ranking["objective"],
            "objective_label": ranking["objective_label"],
            "objective_weights": ranking["weights"],
            "orders_ranked": len(ranking["rank"]),
            "orders_blocked_last": ranking["blocked_last"],
            "orders_with_person_hours": ranking["orders_with_person_hours"],
            "pinned_tasks": pinned_count,
            "excluded_resources": sorted(excluded),
            "data_integrity_warning_count": len(data_integrity_warnings),
            "data_integrity_checked_stations": used_station_codes,
            # 只排进了部分工序（其余工序被产能挡住，但钉住的行按计划员意愿保留）
            "partial_orders": len(scheduled_order_ids & {str(o) for o in result.unscheduled_orders}),
            # 这版计划由哪些输入决定；下次同样输入会被指纹门复用
            "input_fingerprint": fingerprint,
            "fingerprint_parts": fp_parts,
            "new_rows_written": {"aps_schedules": 1, "aps_schedule_tasks": len(result.schedule)},
        }

        # 6. 持久化排程方案

        schedule_id = str(uuid.uuid4())

        schedule_code = f"APS-{factory_id[:6]}-{now.strftime('%Y%m%d%H%M%S')}-{str(uuid.uuid4())[:4].upper()}"

        current_result = await self.db.execute(
            select(ApsSchedule)
            .where(
                ApsSchedule.factory_id == factory_id,
                ApsSchedule.is_current.is_(True),
            )
            .order_by(ApsSchedule.created_at.desc())
            .limit(1)
        )
        current_schedule = current_result.scalar_one_or_none()
        version_result = await self.db.execute(
            select(func.max(ApsSchedule.version_number)).where(ApsSchedule.factory_id == factory_id)
        )
        next_version = int(version_result.scalar() or 0) + 1

        material_ready_map: Dict[str, bool] = {}
        if work_orders:
            material_result = await self.db.execute(
                text("""
                    SELECT work_order_id,
                           SUM(CASE WHEN COALESCE(shortage_qty, 0) > 0 THEN 1 ELSE 0 END) AS shortage_count
                    FROM work_order_materials
                    WHERE work_order_id IN (
                        SELECT id FROM work_orders
                        WHERE factory_id = :factory_id
                          AND wo_type IN ('master', 'component')
                          AND status IN ('released', 'in_progress', 'pending')
                    )
                    GROUP BY work_order_id
                """),
                {"factory_id": factory_id},
            )
            material_ready_map = {
                str(row["work_order_id"]): int(row["shortage_count"] or 0) == 0
                for row in material_result.mappings().all()
            }

        aps_schedule = ApsSchedule(

            id=schedule_id,

            schedule_code=schedule_code,

            factory_id=factory_id,

            mode=mode,

            optimize_for=optimize_for,

            status="draft",

            horizon_start=horizon_start,

            horizon_end=horizon_end,

            on_time_rate=result.performance_metrics.get("on_time_delivery_rate"),

            avg_utilization=result.performance_metrics.get("avg_resource_utilization"),

            total_setup_minutes=result.performance_metrics.get("total_setup_time"),

            avg_cycle_hours=result.performance_metrics.get("avg_manufacturing_cycle"),

            total_tasks=len(result.schedule),

            unscheduled_count=len(result.unscheduled_orders),

            created_by=created_by,
            version_number=next_version,
            is_current=False,
            supersedes_schedule_id=current_schedule.id if current_schedule else None,
            change_reason=change_reason,
            input_fingerprint=fingerprint,

        )

        self.db.add(aps_schedule)

        # 7. 持久化排程任务

        wo_map = {wo.id: wo for wo in work_orders}

        for task in result.schedule:

            wo = wo_map.get(task.order_id)

            # 使用工单已有的work_order_code，若不存在则标记为未知

            order_code = wo.work_order_code if wo and wo.work_order_code else None

            aps_task = ApsScheduleTask(

                id=str(uuid.uuid4()),

                schedule_id=schedule_id,

                work_order_id=str(task.order_id),

                order_code=order_code,

                product_code=task.product_code,

                operation_seq=task.operation_sequence,

                operation_name=task.operation_name or f"工序{task.operation_sequence}",

                station_id=task.station_id,

                planned_start=task.start_time,

                planned_end=task.end_time,

                setup_seconds=task.setup_time,

                run_seconds=task.run_time,

                duration_basis=step_basis.get(

                    f"{task.product_code}|{task.operation_sequence}"

                ),

                quantity=task.quantity,

                status=(task.status.lower() if task.is_locked and task.status else "planned"),

                is_locked=bool(task.is_locked),

                priority=PRIORITY_MAP.get(wo.priority if wo else "medium", SchedulingPriority.NORMAL).value,
                material_ready=material_ready_map.get(str(task.order_id), True),

            )

            self.db.add(aps_task)

        await self._record_event(
            factory_id=factory_id,
            event_type="schedule_generated",
            actor=created_by,
            schedule_id=schedule_id,
            reason=change_reason,
            payload={
                "version_number": next_version,
                "total_tasks": len(result.schedule),
                "unscheduled_orders": result.unscheduled_orders,
                "input_fingerprint": fingerprint,
                "fingerprint_parts": fp_parts,
                # 诊断明细留一份快照：复用草案时靠它把"哪几单没排、为什么"原样带回，
                # 不重算也不编。超出 SNAPSHOT_LIMIT 就明说截断了多少条。
                "success": bool(result.success),
                "message": result.message,
                "constraint_violation_count": len(result.constraint_violations),
                "diagnostics": {
                    "unscheduled": unscheduled_details[:SNAPSHOT_LIMIT],
                    "unscheduled_total": len(unscheduled_details),
                    "constraint_violations": violation_details[:SNAPSHOT_LIMIT],
                    "violations_total": len(violation_details),
                    "data_integrity": data_integrity_warnings,
                    "snapshot_limit": SNAPSHOT_LIMIT,
                },
                "station_loads": station_loads,
                "rule_explanation": rule_explanations.get(ranking["objective"], ""),
            },
        )
        await self.db.commit()

        logger.info(

            "排程完成: code=%s, tasks=%d, unscheduled=%d, on_time=%.1f%%",

            schedule_code, len(result.schedule), len(result.unscheduled_orders),

            result.performance_metrics.get("on_time_delivery_rate", 0),

        )

        return {

            "success": result.success,

            "reused": False,

            "version_number": next_version,

            "schedule_id": schedule_id,

            "schedule_code": schedule_code,

            "total_tasks": len(result.schedule),

            "pinned_tasks": pinned_count,

            "unscheduled_orders": result.unscheduled_orders,

            "unscheduled_count": len(result.unscheduled_orders),

            "constraint_violation_count": len(result.constraint_violations),

            "horizon_days": horizon_days,

            "horizon": f"{horizon_days}天",

            "horizon_start": horizon_start.isoformat(),

            "horizon_end": horizon_end.isoformat(),

            "input_summary": input_summary,

            "diagnostics": {
                "unscheduled": unscheduled_details,
                "constraint_violations": violation_details,
                "data_integrity": data_integrity_warnings,
            },

            "station_loads": station_loads,

            "rule_explanation": rule_explanations.get(ranking["objective"], ""),

            "metrics": result.performance_metrics,

            "message": result.message,

        }

    async def override_task_schedule(
        self,
        task_id: str,
        actor: str,
        station_id: Optional[str] = None,
        planned_start: Optional[datetime] = None,
        planned_end: Optional[datetime] = None,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        """PMC 手工改派一道工序的工位/时刻。

        改完自动置 is_locked：计划员的干预是决定，不能被下一轮算法重排悄悄冲掉。
        拒绝而不是纠正非法输入，理由原样返回，让计划员知道系统为什么不照做。
        """
        task = await self.db.get(ApsScheduleTask, task_id)
        if not task:
            return {"success": False, "message": f"排程任务 {task_id} 不存在"}
        schedule = await self.db.get(ApsSchedule, task.schedule_id)
        if not schedule:
            return {"success": False, "message": "该任务没有归属方案，无法改派"}

        new_station = str(station_id).strip() if station_id else str(task.station_id)
        new_start = planned_start or task.planned_start
        new_end = planned_end or task.planned_end
        if new_end <= new_start:
            return {"success": False, "message": "完工时刻必须晚于开工时刻"}

        if new_station != str(task.station_id):
            known = (await self.db.execute(
                select(Station.id).where(
                    Station.factory_id == schedule.factory_id,
                    or_(Station.station_code == new_station, Station.id == new_station),
                )
            )).first()
            if not known:
                return {"success": False,
                        "message": f"工位 {new_station} 不属于工厂 {schedule.factory_id}，不能改到该工位"}

        cal = await self._load_calendar_constraints(schedule.factory_id, new_station, new_start, new_end)
        if new_start.date() in cal["blocked_dates"] and new_start.date() not in cal["working_dates"]:
            return {"success": False, "message": f"{new_start:%Y-%m-%d} 是厂里登记的假期，不能安排开工"}
        slots = sorted(cal["calendar_by_weekday"].get(new_start.weekday(), []))
        if not slots:
            return {"success": False,
                    "message": f"{new_start:%Y-%m-%d}（周{'一二三四五六日'[new_start.weekday()]}）"
                               f"工厂日历没有排班次，按休息日处理，不能安排开工"}
        if not any(shift_start <= new_start.time() <= shift_end for shift_start, shift_end in slots):
            shifts = "、".join(f"{s:%H:%M}-{e:%H:%M}" for s, e in slots)
            return {"success": False,
                    "message": f"开工时刻 {new_start:%m-%d %H:%M} 不在 {new_station} 的班次内（当日班次 {shifts}）"}

        clash_stmt = select(ApsScheduleTask).where(
            ApsScheduleTask.schedule_id == task.schedule_id,
            ApsScheduleTask.id != task.id,
            ApsScheduleTask.station_id == new_station,
            ApsScheduleTask.planned_start < new_end,
            ApsScheduleTask.planned_end > new_start,
        ).limit(3)
        clashes = list((await self.db.execute(clash_stmt)).scalars().all())
        if clashes:
            detail = "；".join(
                f"{c.order_code or c.work_order_id} 工序{c.operation_seq}({c.operation_name or '-'}) "
                f"{c.planned_start:%m-%d %H:%M}-{c.planned_end:%H:%M}"
                for c in clashes
            )
            return {
                "success": False,
                "message": f"{new_station} 在 {new_start:%m-%d %H:%M}-{new_end:%H:%M} 已有占用：{detail}",
                "conflicts": [str(c.id) for c in clashes],
            }

        before = {
            "station_id": task.station_id,
            "planned_start": task.planned_start.isoformat() if task.planned_start else None,
            "planned_end": task.planned_end.isoformat() if task.planned_end else None,
            "is_locked": bool(task.is_locked),
        }
        task.station_id = new_station
        task.planned_start = new_start
        task.planned_end = new_end
        task.is_locked = True
        await self._record_event(
            factory_id=schedule.factory_id,
            event_type="task_overridden",
            actor=actor,
            schedule_id=task.schedule_id,
            work_order_id=task.work_order_id,
            reason=note or "PMC 手工改派工序",
            payload={
                "task_id": task_id,
                "operation_seq": task.operation_seq,
                "operation_name": task.operation_name,
                "before": before,
                "after": {
                    "station_id": task.station_id,
                    "planned_start": task.planned_start.isoformat(),
                    "planned_end": task.planned_end.isoformat(),
                    "is_locked": True,
                },
            },
        )
        await self.db.commit()
        return {
            "success": True,
            "message": "已改派并自动钉住，重排时保持不动",
            "task_id": task_id,
            "before": before,
            "after": {
                "station_id": task.station_id,
                "planned_start": task.planned_start.isoformat(),
                "planned_end": task.planned_end.isoformat(),
                "is_locked": True,
            },
        }

    async def backfill_missing_routings(
        self,
        factory_id: str,
        dry_run: bool = True,
        actor: str = "system",
    ) -> Dict[str, Any]:
        """给没绑工艺路线的工单补上"同产品其他工单已经在用的那一条"。

        判据只来自库里已有的主数据，不猜：同一产品在本厂的其他 master 工单必须
        指向唯一一条模板路线，且那条模板真的有工序行。只要有一个分歧就交回计划员选，
        绝不替客户编一条工艺路线 —— 排产喂假路线比排不出来更糟。
        """
        rows = (await self.db.execute(text("""
            WITH bound AS (
                SELECT w.product_id,
                       COUNT(DISTINCT w.routing_template_id::text) AS variants,
                       MIN(w.routing_template_id::text) AS template_id
                FROM work_orders w
                WHERE w.factory_id = :fid
                  AND COALESCE(w.wo_type, 'master') = 'master'
                  AND w.routing_template_id IS NOT NULL
                GROUP BY w.product_id
            )
            SELECT w.id AS work_order_id, w.work_order_code, w.product_id, w.status,
                   COALESCE(b.variants, 0) AS variants,
                   b.template_id,
                   rt.template_code, rt.template_name,
                   (SELECT COUNT(*) FROM routing_template_steps s
                     WHERE s.template_id = b.template_id) AS step_count
            FROM work_orders w
            LEFT JOIN bound b ON b.product_id = w.product_id
            LEFT JOIN routing_templates rt ON rt.id::text = b.template_id
            WHERE w.factory_id = :fid
              AND COALESCE(w.wo_type, 'master') = 'master'
              AND w.status IN ('pending', 'released', 'in_progress')
              AND w.routing_template_id IS NULL
              AND w.routing_id IS NULL
            ORDER BY w.product_id, w.work_order_code
        """), {"fid": factory_id})).mappings().all()

        fillable, ambiguous, no_evidence = [], [], []
        for row in rows:
            item = {
                "work_order_id": str(row["work_order_id"]),
                "work_order_code": row["work_order_code"],
                "product_id": row["product_id"],
                "status": row["status"],
                "template_id": row["template_id"],
                "template_code": row["template_code"],
                "template_name": row["template_name"],
                "step_count": int(row["step_count"] or 0),
                "sibling_template_variants": int(row["variants"] or 0),
            }
            if item["sibling_template_variants"] == 1 and item["step_count"] >= 1:
                fillable.append(item)
            elif item["sibling_template_variants"] > 1:
                item["reason"] = f"同产品在用 {item['sibling_template_variants']} 条不同模板路线，需人工选定"
                ambiguous.append(item)
            else:
                item["reason"] = (
                    "该产品在本厂没有任何工单绑定模板路线"
                    if not item["sibling_template_variants"]
                    else "候选模板没有工序行，补了也排不进"
                )
                no_evidence.append(item)

        applied = 0
        if not dry_run:
            for item in fillable:
                wo = await self.db.get(WorkOrder, item["work_order_id"])
                if not wo:
                    continue
                wo.routing_template_id = item["template_id"]
                wo.updated_at = datetime.utcnow()
                await self._record_event(
                    factory_id=factory_id,
                    event_type="routing_backfilled",
                    actor=actor,
                    work_order_id=item["work_order_id"],
                    reason=f"按同产品在用模板补挂工艺路线 {item['template_code'] or item['template_id']}",
                    payload={
                        "product_id": item["product_id"],
                        "template_id": item["template_id"],
                        "template_code": item["template_code"],
                        "step_count": item["step_count"],
                        "basis": "sibling_orders_same_unique_template",
                    },
                )
                applied += 1
            await self.db.commit()

        return {
            "success": True,
            "factory_id": factory_id,
            "dry_run": dry_run,
            "unrouted_total": len(rows),
            "fillable_count": len(fillable),
            "ambiguous_count": len(ambiguous),
            "no_evidence_count": len(no_evidence),
            "applied_count": applied,
            "fillable": fillable,
            "ambiguous": ambiguous,
            "no_evidence": no_evidence,
            "message": (
                f"预览：可安全补挂 {len(fillable)} 张（同产品只用一条模板且有工序行），"
                f"{len(ambiguous)} 张需人工选路线，{len(no_evidence)} 张没有可推导依据"
                if dry_run
                else f"已补挂 {applied} 张工单的工艺路线；"
                     f"{len(ambiguous)} 张需人工选路线，{len(no_evidence)} 张没有依据不代填"
            ),
        }

    async def set_task_lock(
        self,
        task_id: str,
        locked: bool,
        actor: str,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        """PMC 手动钉住/放开一道工序：锁定行在后续重排中原样保留。"""
        task = await self.db.get(ApsScheduleTask, task_id)
        if not task:
            return {"success": False, "message": f"排程任务 {task_id} 不存在"}
        if not task.schedule_id:
            return {"success": False, "message": "该任务没有归属方案，无法记录锁定"}
        schedule = await self.db.get(ApsSchedule, task.schedule_id)
        task.is_locked = locked
        await self._record_event(
            factory_id=schedule.factory_id,
            event_type="task_locked" if locked else "task_unlocked",
            actor=actor,
            schedule_id=task.schedule_id,
            work_order_id=task.work_order_id,
            reason=note or ("PMC 锁定工序" if locked else "PMC 解锁工序"),
            payload={
                "task_id": task_id,
                "operation_seq": task.operation_seq,
                "operation_name": task.operation_name,
                "station_id": task.station_id,
                "planned_start": task.planned_start.isoformat() if task.planned_start else None,
                "planned_end": task.planned_end.isoformat() if task.planned_end else None,
            },
        )
        await self.db.commit()
        return {
            "success": True,
            "task_id": task_id,
            "is_locked": locked,
            "station_id": task.station_id,
            "operation_seq": task.operation_seq,
            "operation_name": task.operation_name,
            "message": "已锁定，重排时保持不动" if locked else "已解锁，可参与重排",
        }

    async def _record_event(
        self,
        *,
        factory_id: str,
        event_type: str,
        actor: str,
        schedule_id: Optional[str] = None,
        plan_id: Optional[str] = None,
        work_order_id: Optional[str] = None,
        reason: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.db.add(ApsPlanEvent(
            id=str(uuid.uuid4()),
            factory_id=factory_id,
            event_type=event_type,
            actor=actor,
            schedule_id=schedule_id,
            plan_id=plan_id,
            work_order_id=work_order_id,
            reason=reason,
            payload=payload or {},
        ))

    async def confirm_schedule(self, schedule_id: str, confirmed_by: str) -> Dict[str, Any]:

        """确认排程方案 → 回写工单计划时间"""

        schedule = await self.db.get(ApsSchedule, schedule_id)

        if not schedule:

            return {"success": False, "message": "排程方案不存在"}

        if schedule.status != "draft":

            return {"success": False, "message": f"状态 {schedule.status} 不可确认"}

        # 加载任务

        tasks_stmt = select(ApsScheduleTask).where(ApsScheduleTask.schedule_id == schedule_id)

        tasks_result = await self.db.execute(tasks_stmt)

        tasks = list(tasks_result.scalars().all())

        # aps_schedule_tasks.station_id 存的是工位编码（ST-JG-01），而
        # work_orders.assigned_station_id 是指向 stations.id(UUID) 的外键；
        # 直接把编码写进去会撞外键，整个确认接口 500。
        codes = sorted({str(t.station_id) for t in tasks if t.station_id})
        station_id_by_code: Dict[str, str] = {}
        if codes:
            mapped = await self.db.execute(
                select(Station.id, Station.station_code).where(
                    Station.factory_id == schedule.factory_id,
                    Station.station_code.in_(codes),
                )
            )
            station_id_by_code = {str(code): str(sid) for sid, code in mapped.all()}

        # 按工单聚合：取最早开始和最晚结束

        wo_times: Dict[str, Dict] = {}

        for t in tasks:

            if not t.work_order_id:

                continue

            if t.work_order_id not in wo_times:

                wo_times[t.work_order_id] = {"start": t.planned_start, "end": t.planned_end, "station": t.station_id}

            else:

                if t.planned_start < wo_times[t.work_order_id]["start"]:

                    wo_times[t.work_order_id]["start"] = t.planned_start

                    # 工单上记的工位应是首道工序（最早开工）的，原来留的是遍历到的任意一行
                    wo_times[t.work_order_id]["station"] = t.station_id

                if t.planned_end > wo_times[t.work_order_id]["end"]:

                    wo_times[t.work_order_id]["end"] = t.planned_end

        # 回写工单

        updated_count = 0

        unmapped_stations: List[str] = []

        for wo_id, times in wo_times.items():

            wo = await self.db.get(WorkOrder, wo_id)

            if wo:

                # planned_due 是 MPS/销售承诺交期，不能被 APS 预计完工覆盖。
                # APS 任务的 planned_end 保留实际排程结果，工单只补齐计划开始时间。
                if wo.planned_start is None:
                    wo.planned_start = times["start"]

                mapped_station = station_id_by_code.get(str(times["station"]))
                if mapped_station:
                    wo.assigned_station_id = mapped_station
                else:
                    unmapped_stations.append(str(times["station"]))

                wo.updated_at = datetime.utcnow()

                updated_count += 1

        # 更新任务状态

        for t in tasks:

            t.status = "confirmed"

        schedule.status = "confirmed"

        schedule.confirmed_by = confirmed_by
        schedule.approved_by = confirmed_by
        schedule.is_current = False

        schedule.updated_at = datetime.utcnow()
        await self._record_event(
            factory_id=schedule.factory_id,
            event_type="schedule_confirmed",
            actor=confirmed_by,
            schedule_id=schedule.id,
            reason="APS 方案确认",
            payload={
                "updated_orders": updated_count,
                "unmapped_station_codes": sorted(set(unmapped_stations)),
            },
        )

        await self.db.commit()

        message = f"已确认，回写 {updated_count} 个工单"
        if unmapped_stations:
            message += f"；{len(set(unmapped_stations))} 个工位编码在 stations 表查不到，已跳过工位回写"
        return {
            "success": True,
            "message": message,
            "updated_orders": updated_count,
            "unmapped_station_codes": sorted(set(unmapped_stations)),
        }

    async def release_schedule(
        self,
        schedule_id: str,
        released_by: str = "system",
        allow_partial: bool = False,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:

        """下达排程 → 工单状态 released

        allow_partial 是计划员对"这版还有工单没排进去/物料没齐"的显式认可：
        下达的是已排产部分，未排进的工单留在池子里，不能默默当成已下达。
        """
        schedule = await self.db.get(ApsSchedule, schedule_id)

        if not schedule:

            return {"success": False, "message": "排程方案不存在"}

        if schedule.status != "confirmed":

            return {"success": False, "message": "需先确认再下达"}

        tasks_stmt = select(ApsScheduleTask).where(ApsScheduleTask.schedule_id == schedule_id)

        tasks_result = await self.db.execute(tasks_stmt)

        tasks = list(tasks_result.scalars().all())

        not_ready = [t for t in tasks if t.material_ready is False]
        blockers = []
        if not_ready:
            blockers.append(f"{len(not_ready)} 条排程任务物料未齐套")
        if schedule.unscheduled_count:
            blockers.append(f"{schedule.unscheduled_count} 个工单未排产")
        if blockers and not allow_partial:
            return {
                "success": False,
                "message": "、".join(blockers) + "，不能下达；确认风险后可传 allow_partial=true 只下达已排产部分",
                "blockers": blockers,
                "material_shortage_tasks": len(not_ready),
                "unscheduled_count": schedule.unscheduled_count,
                "partial_releasable": True,
            }

        # 先把旧版退下来，再动这一版：一厂只许一版生效是**部分唯一索引**
        # （factory_id WHERE is_current），走 ORM 两条 UPDATE 的先后顺序不保证，
        # 实测新行先更新就撞"同一个厂两版同时生效"，整笔事务回滚、下达看上去失败。
        demote = await self.db.execute(text("""
            UPDATE aps_schedules
            SET is_current = FALSE,
                status = CASE WHEN status = 'released' THEN 'archived' ELSE status END,
                updated_at = NOW()
            WHERE factory_id = :fid AND is_current = TRUE AND id <> :sid
        """), {"fid": schedule.factory_id, "sid": schedule.id})
        demoted_versions = int(demote.rowcount or 0)
        await self.db.flush()

        # 版本下达 ≠ 逐单放行。哪些单能进"已下达"，只认就绪门那一套判据
        # （排进本版 + 工序排齐 + 任务行齐套 + 齐套表有领料依据 + 首道工位可映射）。
        # 原来这里是"版里出现过就 released"，等于在就绪门外又开了一条更弱的口子：
        # 缺料的单会跟着整版一起变成已下达，而 audit_false_releases 只回收
        # released_by 是门的那批，这条路放出去的自己看不见。
        from api.services.plan_commit_gate import evaluate_commit_gate

        gate = await evaluate_commit_gate(
            self.db, schedule.factory_id, full=True, schedule_id=schedule.id
        )
        releasable = {str(oid) for oid in (gate.get("ready_ids") or [])}

        wo_ids = set(t.work_order_id for t in tasks if t.work_order_id)

        released = 0


        already_released = 0


        held_by_gate = 0

        released_order_ids: set = set()

        for wo_id in wo_ids:

            wo = await self.db.get(WorkOrder, wo_id)

            if wo is None:
                continue

            if wo.status == "pending" and str(wo_id) not in releasable:
                # 没门依据的单保持待下达；已下达/在制的一律不动（收回是就绪门那条路的事）
                held_by_gate += 1
                continue

            if wo.status == "pending":

                wo.status = "released"

                wo.updated_at = datetime.utcnow()

                released += 1

            elif wo.status == "released":

                # 本来就已下达的，这次只是继续留在生效版里 —— 不许报成"我下达了它"

                already_released += 1

            released_order_ids.add(str(wo_id))

        for t in tasks:

            # 任务行状态跟着它自己那张单走：单没过门，工序行不许写"已下达"

            if t.work_order_id is None or str(t.work_order_id) in released_order_ids:

                t.status = "released"

        schedule.status = "released"
        schedule.is_current = True
        schedule.released_by = released_by
        schedule.released_at = datetime.utcnow()
        schedule.updated_at = datetime.utcnow()
        await self._record_event(
            factory_id=schedule.factory_id,
            event_type="schedule_released",
            actor=released_by,
            schedule_id=schedule.id,
            reason=("APS 方案部分下达" if blockers else "APS 方案下达") + (f"：{note}" if note else ""),
            payload={
                "released_orders": released,
                "held_by_kit_gate": held_by_gate,
                "previous_current_demoted": demoted_versions,
                "allow_partial": allow_partial,
                "blockers": blockers,
                "unscheduled_count": schedule.unscheduled_count,
                "material_shortage_tasks": len(not_ready),
            },
        )

        await self.db.commit()

        return {
            "success": True,
            "message": f"方案已生效；按就绪门下达 {released} 个工单"
                       + (f"，另有 {held_by_gate} 张没过逐单就绪门、保持待下达" if held_by_gate else "")
                       + (f"；未下达：{'、'.join(blockers)}" if blockers else ""),
            "schedule_id": schedule.id,
            "version_number": schedule.version_number,
            "released_orders": released,
            "held_by_kit_gate": held_by_gate,
            "is_current": True,
            "blockers": blockers,
        }

    

    async def reschedule(
        self,
        factory_id: str,
        insert_wo_id: Optional[str] = None,
        created_by: str = "system",
        change_reason: Optional[str] = None,
        optimize_for: Optional[str] = None,
    ) -> Dict[str, Any]:

        """插单/重排：校验插单归属后生成新版本，并保留审计原因。"""
        if insert_wo_id:
            insert_wo = await self.db.get(WorkOrder, insert_wo_id)
            if not insert_wo or insert_wo.factory_id != factory_id:
                return {"success": False, "message": "插入工单不存在或不属于当前工厂", "schedule_id": None}
            if insert_wo.status not in ("pending", "released", "in_progress"):
                return {"success": False, "message": f"工单状态 {insert_wo.status} 不允许进入 APS 重排", "schedule_id": None}

        result = await self.generate_schedule(
            factory_id,
            mode="hybrid",
            optimize_for=optimize_for or "delivery",
            created_by=created_by,
            change_reason=change_reason or (f"insert:{insert_wo_id}" if insert_wo_id else "manual_reschedule"),
        )
        if result.get("schedule_id"):
            await self._record_event(
                factory_id=factory_id,
                event_type="schedule_rescheduled",
                actor=created_by,
                schedule_id=result["schedule_id"],
                work_order_id=insert_wo_id,
                reason=change_reason or "APS 重排",
                payload={"insert_wo_id": insert_wo_id},
            )
            await self.db.commit()
        return result

        

    

    async def get_gantt_data(self, schedule_id: str) -> Dict[str, Any]:

        """获取甘特图数据（按工位分组）"""

        schedule = await self.db.get(ApsSchedule, schedule_id)

        if not schedule:

            return {"error": "排程方案不存在"}

        tasks_stmt = select(ApsScheduleTask).where(

            ApsScheduleTask.schedule_id == schedule_id

        ).order_by(ApsScheduleTask.planned_start)

        tasks_result = await self.db.execute(tasks_stmt)

        tasks = list(tasks_result.scalars().all())

        # 按工位分组 - 从WorkOrder表fallback获取order_code

        from database.models import WorkOrder

        gantt: Dict[str, List[Dict]] = {}

        for t in tasks:

            # 若order_code为空，尝试从WorkOrder表获取

            order_code = t.order_code

            if not order_code and t.work_order_id:

                wo_stmt = select(WorkOrder).where(WorkOrder.id == t.work_order_id)

                wo_result = await self.db.execute(wo_stmt)

                wo = wo_result.scalar_one_or_none()

                if wo and wo.work_order_code:

                    order_code = wo.work_order_code

            if not order_code:

                order_code = f"UNKNOWN-{t.work_order_id[:8]}" if t.work_order_id else "UNKNOWN"

            if t.station_id not in gantt:

                gantt[t.station_id] = []

            gantt[t.station_id].append({

                "id": t.id,

                "work_order_id": t.work_order_id,

                "order_code": order_code,

                "product_code": t.product_code,

                "operation_seq": t.operation_seq,

                "operation_name": t.operation_name,

                "start": t.planned_start.isoformat(),

                "end": t.planned_end.isoformat(),

                "planned_start": t.planned_start.isoformat(),

                "planned_end": t.planned_end.isoformat(),

                "setup_seconds": t.setup_seconds,

                "run_seconds": t.run_seconds,

                "quantity": t.quantity,

                "status": t.status,

                "material_ready": t.material_ready,

                "is_locked": t.is_locked,

                "priority": t.priority,

            })

        return {

            "schedule_id": schedule_id,

            "schedule_code": schedule.schedule_code,

            "status": schedule.status,

            "horizon_start": schedule.horizon_start.isoformat(),

            "horizon_end": schedule.horizon_end.isoformat(),

            "resources": gantt,

            "total_tasks": len(tasks),

        }

    async def get_capacity_load(self, factory_id: str, days: int = 7) -> Dict[str, Any]:
        """产能负荷分析：分子是实际工时，分母是工厂日历可用工时。

        以前这里把 planned_end - planned_start 的墙钟时长整段记到开工日，分母又用
        station_capacity.available_hours_per_day（该列实际维护的是"一天可完成几件产品"）。
        跨班次连续排产之后，墙钟跨度含夜间与周末，是实际工时的 3~5 倍，于是界面上
        出现 ST-QC-02 利用率 439.6% 这种不可能数字。口径统一到 core.mes.capacity_math。
        """
        now = datetime.utcnow()
        horizon_end = now + timedelta(days=max(1, days))

        current_schedule = (await self.db.execute(
            select(ApsSchedule)
            .where(
                ApsSchedule.factory_id == factory_id,
                ApsSchedule.is_current.is_(True),
            )
            .order_by(ApsSchedule.created_at.desc())
            .limit(1)
        )).scalar_one_or_none()

        tasks = []
        if current_schedule:
            tasks_result = await self.db.execute(
                select(ApsScheduleTask).where(
                    ApsScheduleTask.schedule_id == current_schedule.id,
                    ApsScheduleTask.planned_start <= horizon_end,
                    ApsScheduleTask.planned_end >= now,
                    ApsScheduleTask.status.in_(["planned", "confirmed", "released"]),
                )
            )
            tasks = list(tasks_result.scalars().all())

        capacity_rows = [
            dict(row) for row in (await self.db.execute(text("""
                SELECT station_id, available_hours_per_day
                FROM station_capacity
                WHERE factory_id = :factory_id AND is_active = TRUE
            """), {"factory_id": factory_id})).mappings().all()
        ]

        active_stations = list((await self.db.execute(
            select(Station).where(
                Station.factory_id == factory_id,
                Station.status == "active",
            )
        )).scalars().all())
        aliases: Dict[str, str] = {}
        for station in active_stations:
            canonical = str(station.station_code or station.id)
            aliases[str(station.id)] = canonical
            aliases[canonical] = canonical

        station_ids = set(aliases.values())
        station_ids.update(str(row["station_id"]) for row in capacity_rows if row.get("station_id"))
        for task in tasks:
            if task.station_id:
                station_ids.add(aliases.get(str(task.station_id), str(task.station_id)))

        models = await load_station_models(self.db, factory_id, sorted(station_ids), now, horizon_end)
        load = summarize_load(
            models,
            [
                (aliases.get(str(t.station_id), str(t.station_id)), t.planned_start, t.planned_end)
                for t in tasks if t.station_id and t.planned_start and t.planned_end
            ],
            now,
            days,
        )

        horizon_dates = [
            (now + timedelta(days=offset)).strftime("%Y-%m-%d") for offset in range(max(1, days))
        ]

        resources = []
        for station_id in sorted(station_ids):
            model = models.get(station_id)
            bucket = load.get(station_id) or {"by_day": {}, "work_hours": 0.0, "wall_hours": 0.0}
            daily = []
            for date_key in horizon_dates:
                day = datetime.strptime(date_key, "%Y-%m-%d").date()
                capacity_hours = model.capacity_hours_on(day) if model else 0.0
                hours = bucket["by_day"].get(date_key, 0.0)
                utilization = hours / capacity_hours * 100 if capacity_hours else None
                daily.append({
                    "date": date_key,
                    "load_hours": round(hours, 1),
                    "capacity_hours": round(capacity_hours, 1),
                    "utilization": round(utilization, 1) if utilization is not None else None,
                    "is_rest_day": capacity_hours <= 0,
                    "overloaded": bool(utilization is not None and utilization > 100),
                })
            capacity_window = sum(d["capacity_hours"] for d in daily)
            work_window = round(float(bucket["work_hours"]), 2)
            avg_util = round(work_window / capacity_window * 100, 1) if capacity_window else 0.0
            resources.append({
                "station_id": station_id,
                "avg_utilization": avg_util,
                "is_bottleneck": avg_util > 85,
                "daily_load": daily,
                "capacity_hours_per_day": max((d["capacity_hours"] for d in daily), default=0.0),
                "work_hours_in_window": work_window,
                "wall_clock_hours_in_window": round(float(bucket["wall_hours"]), 2),
                "capacity_hours_in_window": round(capacity_window, 2),
                "oee": round(model.oee, 3) if model else None,
                "max_concurrent_orders": model.max_concurrent if model else None,
                "daily_capacity_pieces": model.daily_pieces if model else None,
                "calendar_source": model.calendar_source if model else "unconfigured",
            })

        resources.sort(key=lambda x: (-x["avg_utilization"], x["station_id"]))

        # 负荷表里混进"别的厂的工位"时，利用率看着正常但归属是错的，必须单列告警
        load_station_codes = [r["station_id"] for r in resources]
        ownership: Dict[str, str] = {}
        if load_station_codes:
            own_rows = await self.db.execute(
                select(Station.station_code, Station.factory_id).where(
                    Station.station_code.in_(load_station_codes)
                )
            )
            ownership = {str(row[0]): str(row[1]) for row in own_rows.all() if row[0]}
        integrity_warnings = [
            {
                "station_code": code,
                "issue": "owned_by_other_factory",
                "owner_factory_id": ownership[code],
                "detail": (
                    f"工位 {code} 登记在工厂 {ownership[code]} 名下，"
                    f"不属于本厂（{factory_id}），它的负荷不应计入本厂产能。"
                ),
            }
            for code in load_station_codes
            if ownership.get(code) and ownership[code] != factory_id
        ] + [
            {
                "station_code": code,
                "issue": "not_registered",
                "detail": f"工位 {code} 在 stations 主数据里没有登记，产能取自默认日历估算。",
            }
            for code in load_station_codes
            if code not in ownership
        ]

        return {
            "factory_id": factory_id,
            "horizon_days": days,
            "daily_capacity_hours": round(sum(r["capacity_hours_per_day"] for r in resources), 2),
            "resources": resources,
            "data_integrity": integrity_warnings,
            "bottleneck_count": sum(1 for r in resources if r["is_bottleneck"]),
            "load_basis": (
                f"生效方案 {current_schedule.schedule_code}（V{current_schedule.version_number}）"
                if current_schedule
                else "工厂没有已下达(is_current)的方案，负荷按 0 显示"
            ),
            "load_hours_basis": "任务窗口与班次求交得到的实际工时，不含夜间与休息日",
        }
