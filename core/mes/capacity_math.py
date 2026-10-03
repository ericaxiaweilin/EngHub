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
from typing import Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from database.models import ApsHoliday, ApsSchedule, ApsWorkCalendar, Station

Slot = Tuple[datetime.time, datetime.time]


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
    oee: float = 1.0
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
            "SELECT station_id, available_hours_per_day, efficiency_rate, max_concurrent_orders "
            "FROM station_capacity WHERE factory_id = :fid AND is_active = TRUE"
        ), {"fid": factory_id})).mappings().all() if str(row['station_id']) in set(wanted)]
    except SQLAlchemyError:
        capacity_rows = []
    for row in capacity_rows:
        model = models.get(str(row['station_id']))
        if not model:
            continue
        model.oee = float(row['efficiency_rate'] or 1.0)
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
