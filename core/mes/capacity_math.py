"""工位产能负荷的唯一算法。

为什么要单独一个模块：负荷/利用率此前在 4 个读路径各写一遍，且写法都不一样——

1. `aps_service.get_capacity_load`：负荷用 `planned_end - planned_start` 的墙钟时长，
   分母用 `station_capacity.available_hours_per_day`（该列实际含义是"一天可完成几件产品"）。
   跨班次连续排产之后一道工序的墙钟跨度含夜间与周末，是实际工时的 3~5 倍，于是界面上
   出现 ST-QC-02 利用率 439.6%。
2. `aps_routes.delivery-promise`：同样墙钟时长，全厂日产能把"件/天"当小时相加。
3. `api/services/pmc_control_tower_service._capacity`：墙钟时长 + 把该厂**所有** draft /
   confirmed / released 方案的行全部累加（库里 draft 有几百版），负荷被放大几十倍。
4. `scheduling_agent_service.capacity_balance`：SQL 里直接 SUM 墙钟小时并按 status IN
   ('draft','confirmed') 跨全部版本累加 —— 实测单个工位报 26379 小时/833 行，
   而那个工位当月总共只有约 264 个班次小时。

本模块只定义两件事，各处都从这里取：
- 分子：任务窗口与班次求交得到的**实际工时**（按天分摊，跨夜班/周末不再虚增）。
- 分母：工厂日历得到的**可用工时**（班次小时 × OEE；具体工厂没配日历时回落到
  `factory_id='default'` 的平台班次表，最后才用代码兜底值，并把来源标出来）。
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from database.models import ApsHoliday, ApsSchedule, ApsWorkCalendar, Station

Slot = Tuple[datetime.time, datetime.time]

# 工位效率只有一个口径：台账填了就用填的值；没填按"不打折"(1.0) 计并把这是占位读法写进出处。
# 以前同一个"没填"在一条排程链上被兜了三个数 —— aps_service 的两个分支各兜 0.85 与 0.9，
# 本模块兜 1.0 —— 于是可用工时看代码走到哪个分支而定，界面只显示算出来的利用率。
# 本厂没有实测效率（要 IE 量），所以这里不猜一个数代替：占位就是占位，读数里说清楚。
NEUTRAL_OEE = 1.0
PLACEHOLDER_SOURCES = frozenset({"derived_station_master", "auto", "system", "seed"})


def _is_verified_later(row: Dict[str, Any]) -> bool:
    """verified_at 只有在**晚于建行时间**时才算验证过。

    实测：station_capacity 38 行的 verified_at 与 created_at 逐行相等（38/38），
    source 全是 derived_station_master、note 写着"由 stations.capacity 推导；需业务确认" ——
    那个时间戳是建行时一起写的。要是只看"verified_at 非空"，占位值会被读成"量过的"，
    催办整格消失，这比不分类更糟。
    """
    stamp, created = row.get("verified_at"), row.get("created_at")
    if not stamp:
        return False
    if created and stamp == created:
        return False
    return True


def classify_oee(row: Optional[Dict[str, Any]]) -> str:
    """这一行的效率是哪一类：verified / declared / placeholder / unset。分桶与读数都从这里取，
    不在别处用字符串猜 —— 字符串一变分类就静默变错，那种错没人看得见。"""
    data = row or {}
    raw = data.get("efficiency_rate")
    try:
        value = float(raw) if raw not in (None, "") else 0.0
    except (TypeError, ValueError):
        value = 0.0
    if value <= 0:
        return "unset"
    if _is_verified_later(data):
        return "verified"
    if str(data.get("source") or "").strip() in PLACEHOLDER_SOURCES:
        return "placeholder"
    return "declared"


def resolve_oee(row: Optional[Dict[str, Any]]) -> Tuple[float, str]:
    """(效率, 出处)。出处要能被界面念出来：占位值不等于实测值。"""
    data = row or {}
    raw = data.get("efficiency_rate")
    try:
        value = float(raw) if raw not in (None, "") else 0.0
    except (TypeError, ValueError):
        value = 0.0
    kind = classify_oee(data)
    if kind == "unset":
        return NEUTRAL_OEE, "efficiency_rate 未填 → 按不打折 1.0 计（这是产能上界，不是量出来的效率）"
    if kind == "verified":
        return value, (f"station_capacity 填报 {value:g}，"
                       f"{str(data.get('verified_at'))[:10]} 事后确认过（晚于建行时间）")
    if kind == "placeholder":
        return value, (f"station_capacity 的 {value:g} 是工位档案自动带出来的"
                       f"（source={str(data.get('source') or '').strip()}）、未验证 → 只能当上界读")
    return value, f"station_capacity 填报 {value:g}（没有验证标记）"


def efficiency_basis_buckets(rows: Optional[Iterable[Dict[str, Any]]]) -> Dict[str, Any]:
    """把 station_capacity 的行按"这个效率是怎么来的"分四类 —— 分桶口径只有这一处。

    负荷与利用率的分母都来自这些数，所以"1.0"到底是量过的还是自动带的必须分得开：
    排程按 100% 效率跑本身不算错，错在界面上没人知道那个 100% 是谁定的。
    """
    listed = [dict(r) for r in (rows or [])]
    buckets: Dict[str, List[str]] = {"verified": [], "declared": [], "placeholder": [], "unset": []}
    used: List[float] = []
    for row in listed:
        value, _ = resolve_oee(row)
        key = classify_oee(row)
        buckets[key].append(str(row.get("station_id") or "?"))
        used.append(round(value, 4))
    total = len(listed)
    unverified = len(buckets["placeholder"]) + len(buckets["unset"])
    return {
        "active_stations": total,
        "verified": len(buckets["verified"]),
        "declared": len(buckets["declared"]),
        "placeholder": len(buckets["placeholder"]),
        "unset": len(buckets["unset"]),
        "all_unverified": bool(total) and unverified == total,
        "used_values": sorted(set(used)),
        "placeholder_stations": sorted(buckets["placeholder"])[:12],
        "reading": (f"{unverified}/{total} 个在册工位的排程效率不是量过的"
                    f"（档案自动带的占位 {len(buckets['placeholder'])}、没填按不打折 1.0 计 {len(buckets['unset'])}）"
                    f"；负荷分母实际用到的效率值只有 {sorted(set(used))}" if total
                    else "station_capacity 里没有这个厂区的活跃行 → 负荷分母没有效率依据"),
        "consequence": ("占位与未填都等于按 100% 效率排产：那是产能上界，不是可达产能 —— "
                        "利用率因此偏低（看着还有余量）、交期因此偏乐观。"
                        "本厂没有实测效率，引擎不猜一个数代替"),
        "basis": ("resolve_oee()：efficiency_rate 填了用填报值；"
                  "verified_at 要**晚于 created_at** 才算事后确认过（建行时一起写的时间戳不算验证）；"
                  f"source 在 {sorted(PLACEHOLDER_SOURCES)} 里算档案自动生成的占位；"
                  "没填按 1.0 并标明是上界"),
    }


async def efficiency_basis_census(db: AsyncSession, factory_id: str) -> Dict[str, Any]:
    """按厂区读 station_capacity 再分桶（口径见 efficiency_basis_buckets）。"""
    try:
        rows = [dict(r) for r in (await db.execute(text(
            "SELECT station_id, efficiency_rate, source, verified_at, created_at "
            "FROM station_capacity "
            "WHERE factory_id = :fid AND is_active = TRUE"
        ), {"fid": factory_id})).mappings().all()]
    except SQLAlchemyError:
        rows = []
    return efficiency_basis_buckets(rows)


def _slot(start: datetime.time, end: datetime.time) -> Slot:
    return (start, end)

# 兜底班次：仅在工厂和平台都没有任何日历配置时使用，并通过 calendar_source 如实标出
_FALLBACK_SLOTS: Dict[int, List[Slot]] = {
    dow: [(datetime.time(8, 0), datetime.time(20, 0))] for dow in range(6)
}


@dataclass
class StationModel:
    """一个工位的产能口径：班次、OEE、 concurrency、以及"件/天"的日产量配置。"""

    station_id: str
    slots_by_weekday: Dict[int, List[Slot]] = field(default_factory=dict)
    blocked_dates: Set[datetime.date] = field(default_factory=set)
    working_dates: Set[datetime.date] = field(default_factory=set)
    oee: float = NEUTRAL_OEE
    oee_kind: str = "unset"
    oee_source: str = "没有 station_capacity 行 → 按不打折 1.0 计（上界，不是实测）"
    max_concurrent: int = 1
    daily_pieces: Optional[float] = None
    calendar_source: str = 'aps_work_calendars'

    def slots_on(self, day: datetime.date) -> List[Slot]:
        if day in self.working_dates:
            return self.slots_by_weekday.get(day.weekday()) or _FALLBACK_SLOTS.get(day.weekday(), [])
        if day in self.blocked_dates:
            return []
        return self.slots_by_weekday.get(day.weekday(), [])

    def is_working_day(self, day: datetime.date) -> bool:
        return bool(self.slots_on(day))

    def capacity_hours_on(self, day: datetime.date) -> float:
        """该工位当天的可用工时 = 班次总时长 × OEE。"""
        seconds = sum((e.hour * 3600 + e.minute * 60) - (s.hour * 3600 + s.minute * 60)
                      for s, e in self.slots_on(day))
        return round(seconds / 3600.0 * (self.oee or 1.0), 3)

    def work_seconds_between(self, start: datetime.datetime, end: datetime.datetime) -> float:
        """start→end 之间真正落在班次里的工作秒数（夜间、休息日不计）。"""
        if not start or not end or end <= start:
            return 0.0
        total = 0.0
        day = start.date()
        while day <= end.date():
            for slot_start, slot_end in self.slots_on(day):
                win_from = datetime.datetime.combine(day, slot_start)
                win_to = datetime.datetime.combine(day, slot_end)
                lo, hi = max(start, win_from), min(end, win_to)
                if hi > lo:
                    total += (hi - lo).total_seconds()
            day += datetime.timedelta(days=1)
        return total

    def work_hours_by_day(self, start: datetime.datetime, end: datetime.datetime) -> Dict[str, float]:
        """把一段任务窗口按实际工时分摊到每一天，键为 YYYY-MM-DD。"""
        out: Dict[str, float] = {}
        if not start or not end or end <= start:
            return out
        day = start.date()
        while day <= end.date():
            for slot_start, slot_end in self.slots_on(day):
                win_from = datetime.datetime.combine(day, slot_start)
                win_to = datetime.datetime.combine(day, slot_end)
                lo, hi = max(start, win_from), min(end, win_to)
                if hi > lo:
                    key = day.strftime('%Y-%m-%d')
                    out[key] = out.get(key, 0.0) + (hi - lo).total_seconds() / 3600.0
            day += datetime.timedelta(days=1)
        return {k: round(v, 4) for k, v in out.items()}


async def live_schedule_id(db: AsyncSession, factory_id: str) -> Optional[str]:
    """当前生效版本：优先 is_current，否则取版本号最新的一版。

    负荷统计必须锁定在某一版上。跨全部 draft 累加会把同一工单重复计几十次。
    """
    return (await db.execute(
        select(ApsSchedule.id)
        .where(ApsSchedule.factory_id == factory_id)
        .order_by(ApsSchedule.is_current.desc(), ApsSchedule.version_number.desc(),
                  ApsSchedule.created_at.desc())
        .limit(1)
    )).scalars().first()


async def load_station_models(
    db: AsyncSession,
    factory_id: str,
    station_ids: Iterable[str],
    window_start: datetime.datetime,
    window_end: datetime.datetime,
) -> Dict[str, StationModel]:
    """按工位组装产能口径。资源级日历优先于工厂级('*')，工厂没配则回落到平台 'default'。"""
    # 本函数只用窗口的日期部分（日历生效区间与假期都按日比较），所以也接受 date
    if isinstance(window_start, datetime.date) and not isinstance(window_start, datetime.datetime):
        window_start = datetime.datetime.combine(window_start, datetime.time.min)
    if isinstance(window_end, datetime.date) and not isinstance(window_end, datetime.datetime):
        window_end = datetime.datetime.combine(window_end, datetime.time.min)
    wanted = [str(s) for s in station_ids if s]
    models: Dict[str, StationModel] = {
        sid: StationModel(station_id=sid) for sid in wanted
    }
    if not wanted:
        return models

    calendar_scopes = [factory_id, 'default']
    try:
        calendar_rows = list((await db.execute(
            select(ApsWorkCalendar).where(
                ApsWorkCalendar.factory_id.in_(calendar_scopes),
                ApsWorkCalendar.resource_id.in_(wanted + ['*']),
                ApsWorkCalendar.is_active.is_(True),
                or_(ApsWorkCalendar.effective_from.is_(None),
                    ApsWorkCalendar.effective_from <= window_end.date()),
                or_(ApsWorkCalendar.effective_to.is_(None),
                    ApsWorkCalendar.effective_to >= window_start.date()),
            ).order_by(ApsWorkCalendar.resource_id, ApsWorkCalendar.day_of_week)
        )).scalars().all())
    except SQLAlchemyError:
        calendar_rows = []

    factory_rows = [r for r in calendar_rows if r.factory_id == factory_id]
    platform_rows = [r for r in calendar_rows if r.factory_id != factory_id]
    for sid, model in models.items():
        chosen = [r for r in factory_rows if r.resource_id in (sid, '*')] or \
                 [r for r in platform_rows if r.resource_id in (sid, '*')]
        from_factory = [r for r in chosen if r.factory_id == factory_id]
        source = ('aps_work_calendars' if from_factory
                  else 'platform_default_calendar' if chosen
                  else 'code_fallback')
        if not chosen:
            model.slots_by_weekday = {d: list(v) for d, v in _FALLBACK_SLOTS.items()}
            model.calendar_source = source
            continue
        by_weekday: Dict[int, List[Slot]] = {}
        for item in chosen:
            by_weekday.setdefault(item.day_of_week, []).append((item.start_time, item.end_time))
        model.slots_by_weekday = {d: sorted(v) for d, v in by_weekday.items()}
        # 维护了按周日历时，缺失的星期即为休息日（与排程引擎同一口径）
        model.calendar_source = source

    try:
        holiday_rows = list((await db.execute(
            select(ApsHoliday).where(
                ApsHoliday.factory_id.in_([factory_id, 'default']),
                ApsHoliday.is_active.is_(True),
                ApsHoliday.holiday_date >= window_start.date(),
                ApsHoliday.holiday_date <= window_end.date(),
            )
        )).scalars().all())
    except SQLAlchemyError:
        holiday_rows = []
    for model in models.values():
        model.blocked_dates = {h.holiday_date for h in holiday_rows if not h.is_working_day}
        model.working_dates = {h.holiday_date for h in holiday_rows if h.is_working_day}

    try:
        # station_capacity 表没有 ORM 模型，各处一直用裸 SQL —— 各写一遍也正是
        # 负荷口径分叉的起点，这里统一读一次。
        capacity_rows = [row for row in (await db.execute(text(
            "SELECT station_id, available_hours_per_day, efficiency_rate, max_concurrent_orders, "
            "source, verified_at, created_at FROM station_capacity "
            "WHERE factory_id = :fid AND is_active = TRUE"
        ), {"fid": factory_id})).mappings().all() if str(row['station_id']) in set(wanted)]
    except SQLAlchemyError:
        capacity_rows = []
    for row in capacity_rows:
        model = models.get(str(row['station_id']))
        if not model:
            continue
        model.oee, model.oee_source = resolve_oee(dict(row))
        model.oee_kind = classify_oee(dict(row))
        model.max_concurrent = int(row['max_concurrent_orders'] or 1)
        # 这列的名字写着 hours_per_day，用户确认它实际维护的是"一天可完成几件产品"，
        # 所以只能作为产量口径展示，不能当小时参与利用率计算。
        model.daily_pieces = float(row['available_hours_per_day'] or 0) or None

    if not capacity_rows:
        try:
            station_rows = list((await db.execute(
                select(Station).where(Station.factory_id == factory_id)
            )).scalars().all())
        except SQLAlchemyError:
            station_rows = []
        alias: Dict[str, Station] = {}
        for st in station_rows:
            for key in (str(st.id), str(st.station_code or '')):
                if key:
                    alias[key] = st
        for sid, model in models.items():
            st = alias.get(sid)
            if st and st.capacity_per_hour:
                model.daily_pieces = float(st.capacity_per_hour)

    return models


def summarize_load(
    models: Dict[str, StationModel],
    tasks: Iterable[Tuple[str, datetime.datetime, datetime.datetime]],
    window_start: datetime.datetime,
    days: int,
) -> Dict[str, Dict[str, float]]:
    """按工位聚合：实际工时、按天分摊、以及窗口内可用工时。"""
    per_station: Dict[str, Dict[str, float]] = {}
    dates = [(window_start.date() + datetime.timedelta(offset)).strftime('%Y-%m-%d')
             for offset in range(max(1, days))]
    for station_id, start, end in tasks:
        model = models.get(str(station_id))
        if not model:
            continue
        bucket = per_station.setdefault(str(station_id), {'by_day': {}, 'work_hours': 0.0, 'wall_hours': 0.0})
        hours_by_day = model.work_hours_by_day(start, end)
        bucket['work_hours'] += sum(hours_by_day.values())
        bucket['wall_hours'] += max(0.0, (end - start).total_seconds() / 3600.0)
        for key, value in hours_by_day.items():
            bucket['by_day'][key] = bucket['by_day'].get(key, 0.0) + value
    for station_id, bucket in per_station.items():
        bucket['by_day'] = {k: round(v, 2) for k, v in bucket['by_day'].items() if k in dates}
        bucket['work_hours'] = round(bucket['work_hours'], 2)
        bucket['wall_hours'] = round(bucket['wall_hours'], 2)
    return per_station


def efficiency_basis_from_models(models: Optional[Dict[str, StationModel]]) -> Dict[str, Any]:
    """已经算好产能口径的那批工位，按效率出处分桶（排程/负荷路径上不必再回表查一次）。

    直接读 StationModel.oee_kind —— 不在这里伪造 source/verified_at 再让 classify_oee 猜一遍，
    那种往返会把口径的真相藏进自己的字符串里。
    """
    buckets: Dict[str, List[str]] = {"verified": [], "declared": [], "placeholder": [], "unset": []}
    used: List[float] = []
    for sid, model in (models or {}).items():
        kind = str(getattr(model, "oee_kind", "unset") or "unset")
        buckets.setdefault(kind, []).append(str(sid))
        used.append(round(float(getattr(model, "oee", NEUTRAL_OEE) or NEUTRAL_OEE), 4))
    total = sum(len(v) for v in buckets.values())
    unverified = len(buckets["placeholder"]) + len(buckets["unset"])
    return {
        "active_stations": total,
        "verified": len(buckets["verified"]), "declared": len(buckets["declared"]),
        "placeholder": len(buckets["placeholder"]), "unset": len(buckets["unset"]),
        "all_unverified": bool(total) and unverified == total,
        "used_values": sorted(set(used)),
        "placeholder_stations": sorted(buckets["placeholder"])[:12],
        "reading": (f"{unverified}/{total} 个工位的排程效率不是量过的"
                    f"（档案自动带的占位 {len(buckets['placeholder'])}、没填按不打折 1.0 计 {len(buckets['unset'])}）"
                    f"；负荷分母实际用到的效率值只有 {sorted(set(used))}" if total
                    else "这一版排程没有拿到任何工位产能口径 → 负荷分母没有效率依据"),
        "consequence": ("占位与未填都等于按 100% 效率排产：那是产能上界，不是可达产能 —— "
                        "利用率因此偏低（看着还有余量）、交期因此偏乐观"),
        "basis": "StationModel.oee_kind（load_station_models 里由 classify_oee 判定），与 resolve_oee 同一口径",
    }
