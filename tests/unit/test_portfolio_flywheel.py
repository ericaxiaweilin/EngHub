"""飞轮记账的口径：分数只有可比才有意义，瓶颈没换就不许再发待办。

灌行是这个系统历史上真出事的地方（890 万条重复采购申请），所以这里的去重条件
写在纯函数里并被单测钉住：同一天、同瓶颈、分数没实质变化 → 不写卡；
未关闭待办里已有同一瓶颈 → 不再发。
"""

import json
from datetime import datetime, timedelta

import pytest

pytestmark = [pytest.mark.unit]

from api.services import portfolio_flywheel as pf


def _sim(score=26.2, constraint="算不出货期", models=5):
    return {
        "portfolio_score": score, "models_simulated": models,
        "weights": {"delivery": 0.4, "labor": 0.25, "kit": 0.2, "equipment": 0.1, "basis": 0.05},
        "shift_weekdays": [1, 2, 3, 4, 5, 6], "attendance_factor": 0.97,
        "equipment_available_rate": 0.8765, "hr_active_people": 1005, "caveat": "推演读数",
        "levers": [{"constraint": constraint, "orders": 4, "avg_score": 19.1,
                    "models": ["M-A"], "potential_lift": 64.7}],
        "orders": [{"model_code": "M-A", "binding_constraint": constraint,
                    "estimated_finish": None, "time_basis": "no_time_basis"}],
    }


class _Res:
    def __init__(self, first=None, all_rows=None):
        self._first, self._all = first, all_rows

    def mappings(self):
        return self

    def first(self):
        return self._first

    def all(self):
        return self._all or []


class _FakeDB:
    def __init__(self, last=None, open_tasks=()):
        self.last = last
        self.open_tasks = list(open_tasks)
        self.inserts = []
        self.commits = 0

    async def execute(self, statement, params=None):
        sql = str(statement)
        if "INSERT INTO simulation_scorecards" in sql:
            self.inserts.append(params)
            return _Res()
        if "FROM simulation_scorecards" in sql:
            return _Res(first=self.last)
        if "FROM followup_tasks" in sql:
            return _Res(all_rows=self.open_tasks)
        return _Res()

    async def commit(self):
        self.commits += 1


def test_same_day_same_score_does_not_write_another_card():
    last = {"portfolio_score": 26.2, "top_constraint": "算不出货期",
            "engine_date": datetime.utcnow().date(), "created_at": None}
    assert pf.should_write_card(last, 26.3, "算不出货期") is False      # 抖 0.1 不算新情况
    assert pf.should_write_card(last, 62.0, "算不出货期") is True       # 涨 36 分必须留痕
    assert pf.should_write_card(last, 26.2, "缺料，等采购提前期") is True  # 瓶颈换了要留痕
    assert pf.should_write_card(None, 26.2, "算不出货期") is True          # 第一张卡


def test_yesterday_card_is_always_superseded():
    last = {"portfolio_score": 26.2, "top_constraint": "算不出货期",
            "engine_date": (datetime.utcnow() - timedelta(days=1)).date(), "created_at": None}
    assert pf.should_write_card(last, 26.2, "算不出货期") is True


@pytest.mark.asyncio
async def test_first_cycle_writes_card_and_opens_bottleneck_task():
    db = _FakeDB()
    opened = {}

    async def fake_create_task(db_, factory_id, created_by, title, **kw):
        opened["title"] = title
        opened["kw"] = kw
        return {"task_id": "t1"}

    import api.services.followup_task_service as fts
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(fts, "create_task", fake_create_task)

    out = await pf.record_cycle(db, _sim(), factory_id="FAC_MECH_001",
                                trials={"ie_hours": {"delta": 36.0, "portfolio_score": 62.2}},
                                apply=True)
    assert out["card_written"] is True and len(db.inserts) == 1
    assert out["task"]["action"] == "opened"
    assert "仿真瓶颈｜算不出货期" in opened["title"]
    payload = json.loads(opened["kw"]["payload"])
    assert payload["category"] == "simulation_bottleneck"
    assert payload["lever_deltas"]["ie_hours"] == 36.0        # 接手的人看得见哪条杠杆有效
    monkeypatch.undo()


@pytest.mark.asyncio
async def test_same_bottleneck_already_open_does_not_spam_tasks():
    db = _FakeDB(last={"portfolio_score": 26.2, "top_constraint": "别的瓶颈",
                       "engine_date": datetime.utcnow().date(), "created_at": None},
                 open_tasks=[{"id": "t9", "status": "open", "slot_constraint": "算不出货期"}])
    monkeypatch = pytest.MonkeyPatch()

    async def boom(*a, **kw):
        raise AssertionError("同一瓶颈已有一条未关闭待办，不该再发")

    import api.services.followup_task_service as fts
    monkeypatch.setattr(fts, "create_task", boom)
    out = await pf.record_cycle(db, _sim(), factory_id="FAC_MECH_001", trials={}, apply=True)
    assert out["task"]["action"] == "same_bottleneck_already_open"
    monkeypatch.undo()


@pytest.mark.asyncio
async def test_bottleneck_is_reopened_after_someone_closes_the_task():
    """待办被关掉不等于瓶颈解决了：没有未关闭待办时，同一个瓶颈要能再次发出来。"""
    import api.services.followup_task_service as fts
    db = _FakeDB(last={"portfolio_score": 26.2, "top_constraint": "算不出货期",
                       "engine_date": (datetime.utcnow() - timedelta(days=1)).date(),
                       "created_at": None}, open_tasks=[])
    monkeypatch = pytest.MonkeyPatch()

    async def fake_create_task(db_, factory_id, created_by, title, **kw):
        return {"task_id": "t-reopen"}

    monkeypatch.setattr(fts, "create_task", fake_create_task)
    out = await pf.record_cycle(db, _sim(score=62.2), factory_id="FAC_MECH_001", trials={}, apply=True)
    assert out["card_written"] is True
    assert out["task"]["action"] == "opened"
    monkeypatch.undo()


@pytest.mark.asyncio
async def test_preview_mode_computes_without_writing():
    db = _FakeDB()
    out = await pf.record_cycle(db, _sim(), factory_id="FAC_MECH_001", trials={}, apply=False)
    assert db.inserts == [] and db.commits == 0
    assert out["task"]["action"] == "would_open"


def test_signature_detects_a_change_beyond_the_first_200_characters():
    """短指纹要能看见"催的料号换了"。

    老写法把长串直接 [:200] 截断，而各场景计数那段本身就超过 200 字 ——
    尾巴上的动作清单被切掉，卡与待办因此永远算"没变"。
    """
    view = {f"场景{i}": {"recommended": "政策" * 24, "frontier_size": 7, "eliminated": 6,
                         "no_feasible": False, "feasible_ratio": 0.54,
                         "runner_up_regret_gap": 0.375} for i in range(3)}
    a = pf.tradeoff_signature("加急到 10 天", view, ["expedite_purchase:RM-A"])
    b = pf.tradeoff_signature("加急到 10 天", view, ["expedite_purchase:RM-B"])
    assert len(a[0]) <= 200 and len(b[0]) <= 200
    assert a[0] != b[0]
    assert pf.tradeoff_signature("加急到 10 天", view, ["expedite_purchase:RM-A"])[0] == a[0]
    # 上一轮建议的落地状态也是"变没变"的一部分：有人压了提前期就得重算交期、换一条建议
    assert pf.tradeoff_signature("加急到 10 天", view, ["expedite_purchase:RM-A"], "ft:2-of-2")[0] != a[0]


class _Row(dict):
    """mappings().first() 返回的就是类 dict 行，直接继承 dict 即可。"""


class _OneResult:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def first(self):
        return self._row


class _ReadDB:
    def __init__(self, row):
        self.row = row

    async def execute(self, sql, params=None):
        return _OneResult(self._materialize(self.row))

    @staticmethod
    def _materialize(row):
        if row is None:
            return None
        return _Row(row)


@pytest.mark.asyncio
async def test_no_card_says_so_instead_of_returning_empty_readings():
    out = await pf.latest_tradeoff_state(_ReadDB(None), "FAC_MECH_001")
    assert out["status"] == "no_card" and "15 分钟" in out["message"]


@pytest.mark.asyncio
async def test_jsonb_columns_are_read_whether_the_driver_gives_str_or_dict():
    """asyncpg 有的路径给 str、有的给 dict：两种都要能读出来。

    踩过一次：按 str 解析失败被 except 吞掉，工具于是回"没有推荐、没有动作"，
    而卡里明明有 17 条动作 —— 空读数比报错更坏。
    """
    card = {"portfolio_score": 100.0, "engine_date": "2026-10-06", "created_at": "x",
            "models_simulated": 5,
            "weights": json.dumps({"rule": "minimax", "score_meaning": "稳健度",
                                   "objectives": {"days_late_worst": 0}}),
            "levers": {"policy": "加急到 10 天"},      # dict 形态
            "detail": json.dumps({"actions": [{"type": "expedite_purchase", "material_code": "M-1"}],
                                  "by_scenario": {"好天": {"recommended": "加急到 10 天",
                                                          "informative": True}},
                                  "followthrough": {"verdict": "建议还没落地"}})}
    out = await pf.latest_tradeoff_state(_ReadDB(card), "FAC_MECH_001")
    assert out["status"] == "ok" and out["models_simulated"] == 5
    assert out["robust_recommendation"]["policy"] == "加急到 10 天"
    assert out["actions"][0]["material_code"] == "M-1"
    assert out["by_scenario"]["好天"]["informative"] is True
    assert out["followthrough"]["verdict"] == "建议还没落地"


@pytest.mark.asyncio
async def test_unparsable_detail_does_not_become_a_fake_empty_recommendation():
    card = {"portfolio_score": 0.0, "created_at": "x", "models_simulated": 0,
            "weights": "不是 json", "levers": None, "detail": "{坏数据"}
    out = await pf.latest_tradeoff_state(_ReadDB(card), "FAC_MECH_001")
    assert out["status"] == "ok" and out["actions"] == [] and out["robust_recommendation"] == {}


def test_task_key_ignores_the_floats_that_move_every_tick():
    """待办的"变没变"只看推荐政策、有没有准点、点名到哪些料号。

    前沿宽度与后悔差随台账动，把它们放进待办判据就会每 15 分钟新挂一条又取消上一条 ——
    人会直接把这个agent的待办全关掉。
    """
    acts_a = [{"type": "expedite_purchase", "material_code": "RM-1"},
              {"type": "start_first_batch", "model_code": "M-1", "units": 18}]
    acts_b = [{"type": "expedite_purchase", "material_code": "RM-1"},
              {"type": "start_first_batch", "model_code": "M-1", "units": 999}]
    assert pf.tradeoff_task_key("加急到 10 天", 3, 3, acts_a) == \
        pf.tradeoff_task_key("加急到 10 天", 3, 3, acts_b)
    assert pf.tradeoff_task_key("加急到 10 天", 0, 3, acts_a) != \
        pf.tradeoff_task_key("加急到 10 天", 3, 3, acts_a)
    assert pf.tradeoff_task_key("加急到 10 天", 3, 3, [{"type": "expedite_purchase",
                                                       "material_code": "RM-2"}]) != \
        pf.tradeoff_task_key("加急到 10 天", 3, 3, acts_a)


def test_as_dict_treats_json_null_as_empty_not_as_a_crash():
    """jsonb->text 可能是字面量 'null'，解析成 None 后不能一路当 dict 用。"""
    assert pf._as_dict(None) == {}
    assert pf._as_dict("null") == {}
    assert pf._as_dict("[1,2]") == {}
    assert pf._as_dict('{"a": 1}') == {"a": 1}
    assert pf._as_dict({"a": 1}) == {"a": 1}
    assert pf._as_dict("坏 json") == {}
