"""OEE 两个读数：尺度要认得出来、窗口要锚在台账上、空集合不许报成 0。

`oee_daily` 里金属厂那 567 行集中在同一个写入时间戳（实测 2026-08-07 08:35:41），
列存的是 0~1 小数，而 `calculate_daily_oee` 当初写的是百分数，
两个读数接口又拿 `world_class: 85` 直接跟列值比 —— 同一列三种尺度，谁都读不对。
"""
from datetime import date, datetime

from api.services.oee_service import OeeService, detect_scale, ledger_profile


def _row(day, oee=0.7, created="2026-08-07 08:35:41", **kw):
    return {"snapshot_date": day, "equipment_id": kw.get("eid", "EQ-1"),
            "availability": kw.get("av", 0.85), "performance": kw.get("pf", 0.85),
            "quality": kw.get("ql", 0.97), "oee": oee, "downtime_minutes": 30,
            "created_at": created}


def test_scale_is_detected_from_the_column_not_assumed():
    assert detect_scale([_row("2026-08-01", 0.43), _row("2026-08-02", 0.82)])["scale"] == "fraction"
    assert detect_scale([_row("2026-08-01", 43.0), _row("2026-08-02", 82.0)])["scale"] == "percent"
    mixed = detect_scale([_row("2026-08-01", 0.43), _row("2026-08-02", 82.0)])
    assert mixed["mixed"] is True and mixed["scale"] == "mixed"
    assert detect_scale([])["scale"] == "unknown"


def test_one_write_timestamp_is_reported_as_a_generated_batch():
    prof = ledger_profile([_row("2026-08-01"), _row("2026-08-02")])
    assert prof["generated_in_one_batch"] is True and prof["write_events"] == 1
    assert "批量生成" in prof["provenance_note"]
    assert prof["window"] == ["2026-08-01", "2026-08-02"]
    two = ledger_profile([_row("2026-08-01", created="2026-08-01 08:00"),
                          _row("2026-08-02", created="2026-08-02 08:00")])
    assert two["generated_in_one_batch"] is False and two["write_events"] == 2
    # 没行不能算"批量生成"，那是"这个厂没读数"
    empty = ledger_profile([])
    assert empty["generated_in_one_batch"] is False and empty["rows"] == 0


class _Res:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return [dict(r) for r in self._rows]


class _Db:
    def __init__(self, rows):
        self.rows = rows
        self.sql = []

    async def execute(self, stmt, params=None):
        self.sql.append((str(stmt), params or {}))
        return _Res(self.rows)


def test_summary_anchors_to_the_last_ledger_day_and_returns_percent():
    import asyncio

    rows = [_row("2026-08-06", 0.70), _row("2026-08-07", 0.60), _row("2026-08-07", 0.80)]
    out = asyncio.run(OeeService(_Db(rows)).get_factory_oee_summary("FAC_MECH_001"))
    assert out["date"] == "2026-08-07"
    assert "今天没有行" in out["date_basis"]
    assert out["unit"] == "percent" and out["avg_oee"] == 70.0   # (0.6+0.8)/2 → 70%
    assert out["equipment_count"] == 2
    assert out["worst_equipment"]["oee"] == 60.0
    assert out["data_status"] == "ready"


def test_empty_ledger_gives_no_average_instead_of_zero():
    """空集合不等于读数：报 avg_oee=0 会被读成"今天 OEE 是零"，那是假话。"""
    import asyncio

    out = asyncio.run(OeeService(_Db([])).get_factory_oee_summary("FAC_ELEC_DEMO_2026"))
    assert out["avg_oee"] is None and out["date"] is None
    assert out["data_status"] == "no_rows" and out["why"]
    assert out["ledger"]["generated_in_one_batch"] is False


def test_trend_window_follows_the_ledger_not_todays_date():
    import asyncio

    rows = [_row("2026-08-01", 0.5), _row("2026-08-02", 0.7)]
    out = asyncio.run(OeeService(_Db(rows)).get_oee_trend("FAC_MECH_001", None, 7))
    assert out["window"] == ["2026-07-27", "2026-08-02"]
    assert "今天没有行不等于 OEE 是 0" in out["window_basis"]
    assert out["avg_oee"] == 60.0 and out["unit"] == "percent"
    assert [t["snapshot_date"] for t in out["trend"]] == ["2026-08-01", "2026-08-02"]


def test_requested_date_is_honoured_and_says_so():
    import asyncio

    rows = [_row("2026-08-01", 0.5), _row("2026-08-02", 0.7)]
    out = asyncio.run(OeeService(_Db(rows)).get_factory_oee_summary("FAC_MECH_001",
                                                                    snapshot_date="2026-08-01"))
    assert out["date"] == "2026-08-01" and out["date_basis"] == "调用方点名的那天"
    assert out["avg_oee"] == 50.0
