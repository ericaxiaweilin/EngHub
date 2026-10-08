"""工况的出勤代价要乘在真正排班的人头上，不是乘在"按 100 人"这种方便数字上。

台账里金属厂每天排班 1044 人、单个工段 91 人；同一条 40℃ 工况按 100 人折算会把代价
说小十倍以上。这里锁三件事：乘数取自台账、取不到就明说不折算、句子内部括号不裂开。
"""
from core.mes.data_evidence import ATT_HEADCOUNT_BY_SECTION_SQL, ATT_HEADCOUNT_SQL  # noqa: F401
from api.services.chat_tools_service import _absence_headcount_phrase


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def first(self):
        return dict(self._rows[0]) if self._rows else None

    def all(self):
        return [dict(r) for r in self._rows]


class _Db:
    """只回答这两条 headcount SQL，别的都当没查到（避免测试偷偷依赖真库）。"""

    def __init__(self, row=None, section_rows=None):
        self.row = row
        self.section_rows = section_rows or []
        self.calls = []

    async def execute(self, stmt, params=None):
        self.calls.append((str(stmt).strip().splitlines()[0], params or {}))
        if "JOIN hr_employees" in str(stmt):
            return _Rows(self.section_rows)
        return _Rows([self.row] if self.row else [])


def test_phrase_names_the_ledger_headcount_not_a_round_hundred():
    hc = {"available": True, "heads": 1044, "scope": "factory", "basis": "fixture"}
    out = _absence_headcount_phrase(hc, 0.1626, 11.93)
    assert "1044" in out and "169.8" in out and "124.5" in out
    assert "不是按 100 人折算" in out
    assert "每天排班约 100 人" not in out


def test_phrase_for_a_section_says_that_section():
    hc = {"available": True, "heads": 91, "scope": "section", "section": "涂装"}
    out = _absence_headcount_phrase(hc, 0.1626, 11.93)
    assert out.startswith("该段每天排班约 91 人")
    assert "14.8" in out                       # 0.1626 × 91


def test_phrase_refuses_to_convert_without_a_ledger_headcount():
    for bad in (None, {}, {"available": False, "why": "这座厂在 attendance 里 0 行"},
                {"available": True, "heads": 0}):
        out = _absence_headcount_phrase(bad, 0.1626, 11.93)
        assert "没折算人数" in out, out
        assert "人请不到" not in out, out       # 没有人头就不许编人数


def test_parentheses_stay_balanced_so_the_answer_doesnt_read_broken():
    for hc in ({"available": True, "heads": 500, "scope": "factory"},
               {"available": False, "why": "没台账"}):
        out = _absence_headcount_phrase(hc, 0.1, 2.0)
        assert out.count("（") == out.count("）")


def test_headcount_sql_filters_thin_days_and_counts_distinct_people():
    """日级人头按 distinct 工号算，且排班太薄的日子不进平均（个位数那天没有代表性）。"""
    assert "count(DISTINCT a.operator_id)" in str(ATT_HEADCOUNT_SQL)
    assert "HAVING count(DISTINCT a.operator_id) >= :min_heads" in str(ATT_HEADCOUNT_SQL)
    assert "h.station AS section" in str(ATT_HEADCOUNT_BY_SECTION_SQL)


def test_scheduled_headcount_reports_scope_and_refuses_when_absent():
    import asyncio

    from core.mes.data_evidence import scheduled_headcount

    db = _Db(row={"days": 7, "mean_heads": 1044, "peak_heads": 1044, "low_heads": 1044})
    out = asyncio.run(scheduled_headcount(db, "FAC_MECH_001"))
    assert out["available"] and out["heads"] == 1044 and out["scope"] == "factory"
    assert "1044" in out["basis"]

    empty = asyncio.run(scheduled_headcount(_Db(), "FAC_X"))
    assert not empty["available"] and empty["heads"] is None and empty["why"]

    sect = _Db(section_rows=[{"section": "涂装", "days": 7, "mean_heads": 91, "peak_heads": 91}])
    out = asyncio.run(scheduled_headcount(sect, "FAC_MECH_001", section="涂装"))
    assert out["scope"] == "section" and out["heads"] == 91
    miss = asyncio.run(scheduled_headcount(sect, "FAC_MECH_001", section="不存在"))
    assert not miss["available"] and miss["sections_seen"] == ["涂装"]
