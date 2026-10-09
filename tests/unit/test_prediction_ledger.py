"""交期留痕账本：记账的日期算法、配对取哪一条、样本不够时的说法。

只测纯函数（predicted_finish_for / summarize）—— 动库那两条（record/pair）
在 /api/v1/pmc/delivery-accuracy 的预演里看得到。
"""
import pytest
from datetime import date

from api.services.prediction_ledger import (
    BASIS,
    MIN_PAIRS_FOR_MAPE,
    predicted_finish_for,
    summarize,
)


def test_partial_day_rounds_up_not_down():
    # 0.11 天不能说成"当天交"：那是把预计说早，配对时会凭空多出误差
    assert predicted_finish_for(date(2026, 10, 8), 0.11) == date(2026, 10, 9)
    assert predicted_finish_for(date(2026, 10, 8), 1.0) == date(2026, 10, 9)
    assert predicted_finish_for(date(2026, 10, 8), 1.2) == date(2026, 10, 10)
    assert predicted_finish_for(date(2026, 10, 8), 3.9) == date(2026, 10, 12)


def test_summarize_refuses_to_score_an_unpaired_ledger():
    out = summarize({"paired": 0, "mape": None, "orders_recorded": 349, "rows_recorded": 349,
                     "still_open": 349, "first_day": date(2026, 10, 8),
                     "last_day": date(2026, 10, 8)}, {}, MIN_PAIRS_FOR_MAPE)
    assert out["state"] == "reported"
    assert out["mape"] is None
    assert "成对样本 0 对" in out["missing"]
    # 记账量与配对量是两个数，别把它们并成一个"覆盖率"
    assert out["orders_recorded"] == 349 and out["paired"] == 0


def test_summarize_passes_only_with_enough_pairs_and_low_error():
    ok = summarize({"paired": 12, "mape": 0.11, "mae_days": 1.4, "orders_recorded": 349,
                    "rows_recorded": 400, "still_open": 388,
                    "first_day": date(2026, 10, 8), "last_day": date(2026, 10, 20)},
                   {"c. 准（±2 天）": 9, "d. 晚 3-7 天": 3}, MIN_PAIRS_FOR_MAPE)
    assert ok["state"] == "pass" and ok["missing"] is None
    bad = summarize({"paired": 12, "mape": 0.44, "orders_recorded": 349, "rows_recorded": 400,
                     "still_open": 388, "mae_days": 5.0,
                     "first_day": date(2026, 10, 8), "last_day": date(2026, 10, 20)}, {}, 10)
    assert bad["state"] == "fail"


def test_enough_pairs_but_no_value_still_counts_as_not_judged():
    # 配对数够了但 MAPE 算不出（误差全为空的脏数据）→ 不能当"通过"
    out = summarize({"paired": 15, "mape": None, "orders_recorded": 40, "rows_recorded": 40,
                     "still_open": 25, "first_day": date(2026, 10, 8),
                     "last_day": date(2026, 10, 22)}, {}, 10)
    assert out["state"] == "reported" and "成对样本" not in (out["missing"] or "成对样本")


def test_basis_is_a_single_named_method():
    """口径名要固定：账本里混进第二种预计口径，配对就变成两套尺互相打。"""
    assert BASIS == "time_basis_flow"


def test_error_bands_are_carried_into_the_summary():
    out = summarize({"paired": 3, "mape": None, "orders_recorded": 10, "rows_recorded": 12,
                     "still_open": 9, "first_day": date(2026, 10, 8),
                     "last_day": date(2026, 10, 9)},
                    {"e. 晚 8 天以上": 2, "c. 准（±2 天）": 1}, 10)
    assert out["error_bands"] == {"e. 晚 8 天以上": 2, "c. 准（±2 天）": 1}


def test_pairing_missing_names_the_population_not_the_clock():
    """账本 550 张、成对 0 对、已完工单里 0 张在账本里 —— 这种等多久都是 0。"""
    from api.services.prediction_ledger import pairing_missing

    pop = {"completed_total": 28, "completed_dated_past": 3, "completed_on_ledger_models": 0,
           "completed_in_ledger": 0, "ledger_models": 1}
    txt = pairing_missing(0, 10, pop)
    assert "从来没被留痕" in txt and "缺的不是天数" in txt
    assert "28 张" in txt and "未来日期 25 张" in txt, "文案里的数要能从读数复算出来"


def test_pairing_missing_when_completions_are_being_recorded():
    """账本里已有完工单才说"下一轮会配上" —— 两种情况不许混成同一句。"""
    from api.services.prediction_ledger import pairing_missing

    pop = {"completed_total": 28, "completed_dated_past": 12, "completed_on_ledger_models": 5,
           "completed_in_ledger": 4, "ledger_models": 2}
    txt = pairing_missing(2, 10, pop)
    assert "已有 4 张单完工" in txt and "从来没被留痕" not in txt


def test_pairing_missing_without_any_completion_says_so():
    from api.services.prediction_ledger import pairing_missing

    assert "还没有一张已完工单" in pairing_missing(0, 10, {"completed_total": 0})
    assert "还没有一张已完工单" in pairing_missing(0, 10, None), "查不动人群时不许编归因"


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _PagedDb:
    """OPEN_SQL 按 off 分页返回；其它语句回空。"""

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    async def execute(self, stmt, params=None):
        p = params or {}
        self.calls.append(p)
        if "off" in p:
            return _Rows(self.pages.get(int(p["off"]), []))
        return _Rows([])

    async def rollback(self):
        return None

    async def commit(self):
        raise AssertionError("预演（apply=False）不能提交")


class _Basis:
    line_by_model = {"A-50-04-F": {}}

    def order_flow_estimate(self, *, model, qty, steps):
        return {"estimated_days": 3.0, "line_code": "LINE-TREAD-01"}


async def _noop_ensure(db):
    return None


@pytest.mark.asyncio
async def test_record_predictions_pages_past_the_page_size(monkeypatch):
    """limit 是页大小不是本轮上限：726 张那种量级不能再静默只记 600 张。"""
    from api.services import prediction_ledger as pl

    db = _PagedDb({0: [{"work_order_id": f"w{i}", "work_order_code": f"C{i}",
                        "model_code": "A-50-04-F", "units": 10, "planned_due": None,
                        "route_steps": 2} for i in range(2)],
                   2: [{"work_order_id": f"w{i}", "work_order_code": f"C{i}",
                        "model_code": "A-50-04-F", "units": 10, "planned_due": None,
                        "route_steps": 2} for i in range(2, 4)],
                   4: [{"work_order_id": "w4", "work_order_code": "C4",
                        "model_code": "A-50-04-F", "units": 10, "planned_due": None,
                        "route_steps": 2}]})
    monkeypatch.setattr(pl, "ensure_schema", _noop_ensure)
    monkeypatch.setattr("api.services.time_basis.load_time_basis", _async(_Basis()))
    receipt = await pl.record_predictions(db, "FAC", limit=2, apply=False, today=date(2026, 10, 9))
    assert receipt["open_orders"] == 5 and receipt["pages_read"] == 3
    assert receipt["recorded"] == 5 and receipt["truncated_after"] is None
    assert receipt["apply"] is False, "预演不能写库"


@pytest.mark.asyncio
async def test_record_predictions_reports_truncation_instead_of_hiding_it(monkeypatch):
    from api.services import prediction_ledger as pl

    full = [{"work_order_id": f"w{i}", "work_order_code": f"C{i}", "model_code": "A-50-04-F",
             "units": 10, "planned_due": None, "route_steps": 2} for i in range(4)]
    db = _PagedDb({0: full[:2], 2: full[2:]})          # 每页都满，页数用完仍没读完
    monkeypatch.setattr(pl, "ensure_schema", _noop_ensure)
    monkeypatch.setattr(pl, "MAX_LEDGER_PAGES", 2)
    monkeypatch.setattr("api.services.time_basis.load_time_basis", _async(_Basis()))
    receipt = await pl.record_predictions(db, "FAC", limit=2, apply=False, today=date(2026, 10, 9))
    assert receipt["pages_read"] == 2 and receipt["truncated_after"] == 4
    assert receipt["open_orders"] == 4, "截断过也要把读了多少报出来，不能只报记了几张"


def _async(value):
    import asyncio

    async def _v(*a, **k):
        return value
    return _v


def test_capacity_gap_note_names_models_and_refuses_to_invent():
    from api.services.prediction_ledger import capacity_gap_note

    gap = {"models": [{"model_code": "A-30-04-F", "orders": 16, "units": 712.0},
                      {"model_code": "MPL0113-00", "orders": 15, "units": 718.0}],
           "orders": 31, "units": 1430.0}
    text = capacity_gap_note(gap)
    assert "A-30-04-F（16 张/712 台）" in text and "MPL0113-00" in text
    assert "31 张在流程单（1430 台）" in text
    assert "不会替它们编一个完工日" in text, "缺依据时要把不写假承诺这件事说出口"
    assert capacity_gap_note({"models": []}) is None
    assert capacity_gap_note(None) is None


def test_pairing_missing_appends_the_capacity_gap_when_there_is_one():
    from api.services.prediction_ledger import pairing_missing

    pop = {"completed_total": 28, "completed_dated_past": 3, "completed_on_ledger_models": 0,
           "completed_in_ledger": 0, "ledger_models": 1}
    gap = {"models": [{"model_code": "VF-CMECH001-40HQ", "orders": 36, "units": 10800.0}],
           "orders": 36, "units": 10800.0}
    text = pairing_missing(0, 10, pop, gap)
    assert "从来没被留痕" in text and "25 张" in text
    assert "VF-CMECH001-40HQ（36 张/10800 台）" in text
    assert "line_profiles" in text, "要指到人能改的那张表，不是只说算不出"


def test_sub_day_orders_are_not_reported_as_lacking_a_capacity_basis():
    """10-09 实测：7 张 1 台的单流水线口径算出 0.0 天，以前被混进"没落到线上"那格。"""
    import asyncio

    from api.services import prediction_ledger as pl

    class _ZeroBasis(_Basis):
        def order_flow_estimate(self, *, model, qty, steps):
            return {"estimated_days": 0.0, "line_code": "LINE-TREAD-01"}

    rows = [{"work_order_id": "w1", "work_order_code": "C1", "model_code": "A-50-04-F",
             "units": 1, "planned_due": None, "route_steps": 2}]
    db = _PagedDb({0: rows})
    monkeypatch = _Monkey()
    monkeypatch.setattr(pl, "ensure_schema", _noop_ensure)
    monkeypatch.setattr("api.services.time_basis.load_time_basis", _async(_ZeroBasis()))
    receipt = asyncio.run(pl.record_predictions(db, "FAC", limit=400, apply=False,
                                                today=date(2026, 10, 9)))
    assert receipt["recorded"] == 1 and receipt["same_day"] == 1
    assert receipt["no_line_capacity"] == 0, "当天能做完 ≠ 没有产能依据"
    assert "不足一个班日按今天交的 1 张" in receipt["message"]


class _Monkey:
    """不用 pytest 的 monkeypatch fixture（纯函数用例里手搓一个够用的）。"""

    def __init__(self):
        self._saved = []

    _MISS = object()

    def setattr(self, target, name=_MISS, value=_MISS):
        import importlib

        if isinstance(target, str):
            # 字符串形式按 pytest 的约定：setattr("pkg.mod.attr", value)
            mod_name, attr = target.rsplit(".", 1)
            holder = importlib.import_module(mod_name)
            new_value = name
        else:
            holder, attr, new_value = target, name, value
        self._saved.append((holder, attr, getattr(holder, attr)))
        setattr(holder, attr, new_value)
