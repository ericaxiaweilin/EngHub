"""半成品路线只取被它自己子树佐证的工序（用户 10-05 的工厂口径）。

这里同时守 10-05 later 补的三件事：
- 参考路线池里不许有自己推出来的草案（否则草案互相套，出处追到第三层）；
- 工步没有工位编码时按本厂事实解析，解析不出来的工序摘除而不是留空；
- 佐证要 BOM 文本里真写了工序字样，不再用"看到車架就当他要焊接"的代用判据。
"""

from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.unit]

from api.services import routing_from_family as rf

# 机械厂真实登记的工位（站名/产能单位取线上 values）
MECH_STATIONS = [
    {"station_code": "CNC-CENT-01", "station_name": "CNC加工中心", "capacity_unit": "sets/day"},
    {"station_code": "EDM-CENT-02", "station_name": "EDM精加工中心", "capacity_unit": "sets/day"},
    {"station_code": "INJ-MACH-01", "station_name": "注塑试模机", "capacity_unit": "sets/day"},
    {"station_code": "ST-GL-01", "station_name": "滚轮车间", "capacity_unit": "人"},
    {"station_code": "ST-HJ-01", "station_name": "焊接车间", "capacity_unit": "人"},
    {"station_code": "ST-JD-01", "station_name": "機電车间", "capacity_unit": "人"},
    {"station_code": "ST-JG-01", "station_name": "加工车间", "capacity_unit": "人"},
    {"station_code": "ST-PK-01", "station_name": "包装入库站", "capacity_unit": "人"},
    {"station_code": "ST-QC-01", "station_name": "来料检验站", "capacity_unit": "人"},
    {"station_code": "ST-QC-02", "station_name": "成品检验站", "capacity_unit": "人"},
    {"station_code": "ST-TZ-01", "station_name": "涂装车间", "capacity_unit": "人"},
    {"station_code": "ST-ZL-01", "station_name": "组立一线", "capacity_unit": "人"},
    {"station_code": "ST-ZS-01", "station_name": "注塑车间", "capacity_unit": "人"},
    {"station_code": "WIRE-CUT-03", "station_name": "线切割工位", "capacity_unit": "sets/day"},
]
STATION_CODES = {s["station_code"] for s in MECH_STATIONS}

TREAD = [
    {"step_no": 10, "name": "车架焊接", "station": "ST-HJ-01"},
    {"step_no": 20, "name": "表面涂装", "station": "ST-TZ-01"},
    {"step_no": 30, "name": "电控装配", "station": "ST-JD-01"},
    {"step_no": 40, "name": "跑步机总装", "station": "ST-JD-01"},
    {"step_no": 50, "name": "成品检验", "station": "ST-QC-02"},
    {"step_no": 60, "name": "包装入库", "station": "ST-PK-01"},
]
# 厂里的模具线：工序名是真工艺，但工步只写了 station_type，没有工位编码
MOLD = [
    {"step_no": 10, "name": "下料", "station_type": "raw_material"},
    {"step_no": 20, "name": "粗铣", "station_type": "cnc"},
    {"step_no": 30, "name": "精铣", "station_type": "cnc"},
    {"step_no": 70, "name": "试模注塑", "station_type": "injection"},
    {"step_no": 80, "name": "终检", "station_type": "inspection"},
]


WHEEL = [
    {"step_no": 10, "name": "滚轮成型", "station": "ST-GL-01"},
    {"step_no": 20, "name": "健腹轮组装", "station": "ST-ZL-01"},
    {"step_no": 30, "name": "成品检验", "station": "ST-QC-02"},
    {"step_no": 40, "name": "包装入库", "station": "ST-PK-01"},
]

class _Route:
    def __init__(self, id, product_id, steps, created_by="treadmill_flow_seed"):
        self.id = id
        self.product_id = product_id
        self.steps = steps
        self.created_by = created_by


class _Master:
    def __init__(self, code="車架組"):
        self.product_code = code
        self.current_routing_id = None
        self.factory_id = "FAC_MECH_001"


class _Rows:
    def __init__(self, rows, master=None):
        self._rows = list(rows)
        self._master = master

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def scalars(self):
        return self

    def scalar_one_or_none(self):
        return self._master


def _db(routes=(), stations=None, master=None, bom_rows=()):
    """按语句分派的假会话：路线池、工位主数据、产品主档各回各的。"""
    db = MagicMock()
    added = []
    routes = list(routes)
    station_rows = MECH_STATIONS if stations is None else stations

    async def execute(statement, params=None):
        sql = str(statement)
        if "FROM stations" in sql:
            return _Rows(station_rows)
        if "FROM routings" in sql:
            return _Rows(routes, master=master)
        if "FROM enghub_bom_items" in sql:
            return _Rows(bom_rows, master=master)
        return _Rows([], master=master)

    async def get(entity, pk):
        return None

    async def flush():
        return None

    db.execute = execute
    db.get = get
    db.flush = flush
    db.add = lambda obj: added.append(obj)
    db.added = added
    db.master = master if master is not None else _Master()
    return db


@pytest.mark.asyncio
async def test_component_route_keeps_only_corroborated_steps():
    """車架組的子树只写著"焊接/烤漆"，就只能拿到这两道工序，不该被塞进電控/包裝。"""
    db = _db([_Route("rt-tread-004-2026", "FG-TREAD-004", TREAD)],
             master=_Master("車架組"))
    corpus = "車架組;;;焊接;;EP298 烤漆 DM334"
    receipt = await rf.derive_routing_for_component(
        db, "FAC_MECH_001", "車架組", corpus, level=3)

    assert receipt["status"] == "derived", receipt
    created = db.added[0]
    assert [s["name"] for s in created.steps] == ["车架焊接", "表面涂装"]
    assert [s["station"] for s in created.steps] == ["ST-HJ-01", "ST-TZ-01"]
    assert all("standard_time" not in s for s in created.steps), "不替工厂编工时"
    assert db.master.current_routing_id == created.id, "主档要指向新路线，否则工单还是排不动"


@pytest.mark.asyncio
async def test_component_needs_at_least_one_literal_operation():
    """门槛管的是**证据**：子树里一句工序字样都没有，就不建路线。

    原来这条要求"至少 2 道"，把 101 个只写了"烤漆"或"ABS"的件判成做不了 ——
    那是我设的数量门槛，不是工厂的事实，10-05 已改成 1 道。
    """
    db = _db([_Route("rt-tread-004-2026", "FG-TREAD-004", TREAD)], master=_Master("端蓋"))
    receipt = await rf.derive_routing_for_component(
        db, "FAC_MECH_001", "端蓋", "端蓋;車架;左前;鋁合金;白色", level=4
    )
    assert receipt["status"] == "not_derived", receipt
    assert db.added == []
    assert "没有任何工序字样" in receipt["reason"]


@pytest.mark.asyncio
async def test_one_corroborated_operation_is_enough_for_a_component_route():
    """只写了"烤漆"的子件就该拿到一道表面涂装工序，而不是被判成没人能做的东西。"""
    db = _db([_Route("rt-tread-004-2026", "FG-TREAD-004", TREAD)], master=_Master("固定片"))
    receipt = await rf.derive_routing_for_component(
        db, "FAC_MECH_001", "固定片", "固定片;電磁鐵;;SPHC;鐵板;;;烤漆;DM334", level=4)
    assert receipt["status"] == "derived", receipt
    created = db.added[0]
    assert [s["name"] for s in created.steps] == ["表面涂装"]
    assert created.steps[0]["station"] == "ST-TZ-01"


@pytest.mark.asyncio
async def test_process_proxy_words_are_no_longer_accepted_as_evidence():
    """看到"車架"就当他要焊接 —— 这类代用判据 10-05 起不算佐证。

    旧断言是"車架組 烤漆 電控板 組立 包裝"能证明焊接这道工序；那是替工厂编工艺。
    现在要文本里真的出现工序字样（焊接/熔接/點焊…）才算。
    """
    assert not rf._matches("车架焊接", "車架組 烤漆 電控板 組立 包裝")
    assert rf._matches("车架焊接", "車架組 焊接 烤漆")
    assert rf._matches("表面涂装", "車架組 焊接 烤漆")
    assert not rf._matches("注塑成型", "車架組 焊接 烤漆")


@pytest.mark.asyncio
async def test_derived_drafts_are_not_reference_routes():
    """自己推出来的草案不能当参考：否则半成品之间互相套，覆盖率还显得特别好看。"""
    derived = _Route("rt-bom-1000473168", "1000473168", TREAD[:4],
                     created_by=rf.CREATED_BY)
    house = _Route("rt-tread-004-2026", "FG-TREAD-004", TREAD)
    db = _db([derived, house])
    pool = await rf._reference_routings(db, "FAC_MECH_001")
    assert [r.id for r in pool] == ["rt-tread-004-2026"]


@pytest.mark.asyncio
async def test_steps_without_station_codes_get_placed_on_real_stations():
    """模具线那种只写 station_type 的工序：按本厂事实解析工位，解析不出的摘除。

    留一个空工位或本厂不存在的编码，APS 只会把它列进"跨厂借用/无产能记录"告警。
    """
    db = _db([_Route("rt-mold-2026", "FG-MOLD-01", MOLD)], master=_Master("側板"))
    corpus = "側板 鑄鋁 加工 車削 ABS 注塑 檢驗"
    receipt = await rf.derive_routing_for_component(
        db, "FAC_MECH_001", "側板", corpus, level=3)

    assert receipt["status"] == "derived", receipt
    created = db.added[0]
    by_name = {s["name"]: s["station"] for s in created.steps}
    assert by_name["试模注塑"] == "ST-ZS-01", "注塑工序落到有人力配置的注塑车间，不是那台 1 套/天的试模机"
    assert by_name["粗铣"] == "ST-JG-01" and by_name["精铣"] == "ST-JG-01"
    assert all(code in STATION_CODES for code in by_name.values()), "工位必须是本厂登记的"
    assert receipt["reference_steps_unplaceable"] == 1, "下料这道工序本厂没有对应工位，该摘掉"
    assert "下料" in created.remark and "已摘除" in created.remark
    assert "标准工时未经 IE 确认" in created.remark


@pytest.mark.asyncio
async def test_the_same_operation_name_already_placed_by_the_factory_wins():
    """厂区自己的路线把"成品检验"绑在 ST-QC-02 —— 照抄，别按站名重挑一个。"""
    db = _db([_Route("rt-tread-004-2026", "FG-TREAD-004", TREAD)])
    homes = await rf._station_homes(db, "FAC_MECH_001", await rf._reference_routings(
        db, "FAC_MECH_001"))
    item, dropped = rf._place_step({"step_no": 50, "name": "成品检验"}, 4, homes)
    assert dropped is None
    assert item["station"] == "ST-QC-02"
    assert "已有路线把工序" in item["station_basis"], "出处要写清是哪条路线的哪个事实"
    # 没有同名配对时，"检验"这族活按站名认领；两个检验站里按编码取稳定的那个
    other, _ = rf._place_step({"step_no": 50, "name": "終檢"}, 4, homes)
    assert other["station"] == "ST-QC-02", "两个检验站里选厂区路线真的在用那个，不是编码最小的"


@pytest.mark.asyncio
async def test_a_family_home_comes_from_the_station_name_not_an_unrelated_product():
    """滚轮线的"滚轮成型"绑在滚轮车间，不代表整个注塑族的家是滚轮车间。

    10-05 实测就是这个顺序把 ABS 端蓋派去滚轮车间的；厂里明明有注塑车间。
    """
    db = _db([_Route("rt-wheel-2026", "FG-WHEEL-01", WHEEL)])
    homes = await rf._station_homes(db, "FAC_MECH_001", await rf._reference_routings(
        db, "FAC_MECH_001"))
    item, dropped = rf._place_step({"step_no": 70, "name": "试模注塑"}, 6, homes)
    assert dropped is None and item["station"] == "ST-ZS-01"
    assert "站名" in item["station_basis"]
    machining, _ = rf._place_step({"step_no": 20, "name": "粗铣"}, 1, homes)
    assert machining["station"] == "ST-JG-01", "机加工序落到加工车间"
    assembly, _ = rf._place_step({"step_no": 60, "name": "組立"}, 5, homes)
    assert assembly["station"] == "ST-ZL-01", "装配不能派去哑铃组装线：那是具体产品的线，不是工序族的家"


@pytest.mark.asyncio
async def test_no_station_master_is_an_honest_blocker():
    """厂区一个工位都没登记时不能说"推不出路线"，要说清是主数据缺。"""
    db = _db([_Route("rt-tread-004-2026", "FG-TREAD-004", TREAD)], stations=[],
             master=_Master("車架組"))
    receipt = await rf.derive_routing_for_component(
        db, "FAC_MECH_001", "車架組", "車架組 焊接 烤漆", level=3)
    assert receipt["status"] == "no_station_master"
    assert db.added == []


def test_component_gate_is_documented_separately_from_model_gate():
    """型号级要覆盖整条产线的一半；半成品级按子集，两个门槛不能混成一个数。"""
    assert rf.MIN_COVERAGE == 0.5
    assert rf.MIN_COMPONENT_STEPS == 1, "地板是有没有工序证据，不是数量"

@pytest.mark.asyncio
async def test_model_route_keeps_the_line_but_drops_unplaceable_operations():
    """整机型：覆盖率达到一半就套整条线，但落不到工位的工序照样摘除。"""
    db = _db(
        [_Route("rt-mold-2026", "FG-MOLD-01", MOLD)],
        master=_Master("FG-MOLD-02"),
        bom_rows=[{"description": "模架;加工;車削", "l3_context": None},
                  {"description": "型芯;ABS;注塑成形", "l3_context": None},
                  {"description": "成品;檢驗", "l3_context": None}],
    )
    receipt = await rf.derive_routing_for_product(db, "FAC_MECH_001", "FG-MOLD-02")
    assert receipt["status"] == "derived", receipt
    created = db.added[0]
    assert [s["name"] for s in created.steps] == ["粗铣", "精铣", "试模注塑", "终检"]
    assert receipt["coverage"] == 1.0, "覆盖率按能落地的工序算，不是按参考路线的原始行数"
    assert receipt["reference_steps_unplaceable"] == 1
    assert all("standard_time" not in s for s in created.steps)
