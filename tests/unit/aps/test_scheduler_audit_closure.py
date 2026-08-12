from datetime import datetime, time

from core.mes.hybrid_scheduler import HybridScheduler, SchedulingMode, SchedulingPriority


def _scheduler(*, capacity=1, blocked_dates=None):
    scheduler = HybridScheduler()
    start = datetime(2026, 8, 10, 8, 0)  # Monday
    end = datetime(2026, 8, 17, 20, 0)
    scheduler.load_resource_constraints(
        resource_id="WC-01",
        available_from=start,
        available_to=end,
        capacity=capacity,
        oee=1.0,
        calendar_by_weekday={
            0: [(time(8), time(20))],
            1: [(time(8), time(20))],
            2: [(time(8), time(20))],
            3: [(time(8), time(20))],
            4: [(time(8), time(20))],
        },
        blocked_dates=blocked_dates or set(),
    )
    scheduler.load_process_constraints(
        "P-01",
        [{"sequence": 10, "name": "加工", "standard_time": 3600, "allowed_stations": ["WC-01"]}],
    )
    return scheduler, start


def test_hybrid_priority_places_urgent_order_first():
    scheduler, start = _scheduler()
    scheduler.load_order_constraints(
        "WO-LOW", "P-01", 1, start, datetime(2026, 8, 12, 17), SchedulingPriority.LOW
    )
    scheduler.load_order_constraints(
        "WO-URGENT", "P-01", 1, start, datetime(2026, 8, 14, 17), SchedulingPriority.URGENT
    )

    result = scheduler.schedule_hybrid(SchedulingMode.HYBRID)

    assert result.success
    assert [task.order_id for task in result.schedule] == ["WO-URGENT", "WO-LOW"]


def test_calendar_skips_blocked_day_and_capacity_allows_parallel_tasks():
    scheduler, start = _scheduler(capacity=2, blocked_dates={datetime(2026, 8, 10).date()})
    scheduler.load_order_constraints(
        "WO-01", "P-01", 2, start, datetime(2026, 8, 14, 17), SchedulingPriority.NORMAL
    )
    scheduler.load_order_constraints(
        "WO-02", "P-01", 2, start, datetime(2026, 8, 14, 17), SchedulingPriority.NORMAL
    )

    result = scheduler.schedule_hybrid(SchedulingMode.HYBRID)

    assert result.success
    assert all(task.start_time.date() == datetime(2026, 8, 11).date() for task in result.schedule)
    assert result.schedule[0].start_time == result.schedule[1].start_time
