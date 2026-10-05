"""旧草案把整条产线套在子件上，收窄回它自己子树佐证的工序。

守的底线：只往少了改、路线 id 不动（工单与 APS 的引用不能断）、
佐证不足 2 道工序时交工艺部而不是再套一条更假的路线。
"""

import json

import pytest

pytestmark = [pytest.mark.unit]

from api.services import routing_backfill as rb

HOUSE = [
    {"step_no": 10, "name": "车架焊接", "station": "ST-HJ-01"},
    {"step_no": 20, "name": "表面涂装", "station": "ST-TZ-01"},
    {"step_no": 30, "name": "电控装配", "station": "ST-JD-01"},
    {"step_no": 40, "name": "跑步机总装", "station": "ST-JD-01"},
    {"step_no": 50, "name": "成品检验", "station": "ST-QC-02"},
    {"step_no": 60, "name": "包装入库", "station": "ST-PK-01"},
]
STATIONS = [
    {"station_code": "ST-HJ-01", "station_name": "焊接车间", "capacity_unit": "人"},
    {"station_code": "ST-TZ-01", "station_name": "涂装车间", "capacity_unit": "人"},
    {"station_code": "ST-JD-01", "station_name": "機電车间", "capacity_unit": "人"},
    {"station_code": "ST-QC-02", "station_name": "成品检验站", "capacity_unit": "人"},
    {"station_code": "ST-PK-01", "station_name": "包装入库站", "capacity_unit": "人"},
]


class _Route:
    def __init__(self, steps, product_id="FG-TREAD-004"):
        self.id = "rt-tread-004-2026"
        self.product_id = product_id
        self.steps = steps
        self.created_by = "treadmill_flow_seed"


class _Rows:
    def __init__(self, rows):
        self._rows = list(rows)

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def scalars(self):
        return self


class _Db:
    """按语句分派的假会话：待修的草案路线、BOM 镜像行、UPDATE 计数。"""

    def __init__(self, overclaimed, bom_rows):
        self.overclaimed = overclaimed
        self.bom_rows = bom_rows
        self.updates = []

    async def execute(self, statement, params=None):
        sql = str(statement)
        if "DISTINCT ON (r.id)" in sql:
            return _Rows(self.overclaimed)
        if "UPDATE routings" in sql:
            self.updates.append(params)
            return _Rows([])
        if "FROM enghub_bom_items" in sql:
            return _Rows(self.bom_rows)
        if "FROM stations" in sql:
            return _Rows(STATIONS)
        if "FROM routings" in sql:
            return _Rows([_Route(HOUSE)])
        return _Rows([])


def _row(code, name, level, row_no, text):
    return {"material_code": code, "material_name": name, "qty_per_unit": 1,
            "unit": "PCS", "level": level, "original_row_number": row_no,
            "source_file": "f.xlsx", "vendor_code": None, "vendor_name": None,
            "attribute_text": text, "l3_context": None}


def _bom(code, finish):
    """整机型 BOM：L1 整机 -> L2 車架組 -> L3 半成品，下层属性串里写着要过的工序。

    行序必须逐层 +1（`build_tree` 靠它重建父子链；跳层它宁可判成结构断了也不猜父级）。
    """
    return [
        _row("A-50-04-F", "跑步機", 1, 1, "跑步機;;;"),
        _row("1000461221", "車架組", 2, 2, "車架組;;;烤漆;;;"),
        _row(code, "側板組", 3, 3, f"側板組;;{finish};;;"),
    ]


@pytest.mark.asyncio
async def test_overclaimed_component_route_is_narrowed_not_deleted():
    db = _Db(
        overclaimed=[{"routing_id": "rt-bom-1000461220", "material_code": "1000461220",
                      "nsteps": 6, "factory_id": "FAC_MECH_001",
                      "model_code": "A-50-04-F"}],
        bom_rows=_bom("1000461220", "焊接;烤漆"),
    )
    receipt = await rb.rederive_overclaimed_routes(db)
    assert receipt["examined"] == 1 and receipt["narrowed"] == 1, receipt
    params = db.updates[0]
    steps = json.loads(params["steps"])
    assert [s["name"] for s in steps] == ["车架焊接", "表面涂装"]
    assert params["routing_id"] == "rt-bom-1000461220", "换 id 会把工单与 APS 的引用打断"
    assert "收窄自 6 道工序" in params["remark"]


@pytest.mark.asyncio
async def test_repair_never_grows_a_route():
    """证据比现有路线更宽时不动：这个函数只负责把编出来的工序摘掉。"""
    db = _Db(
        overclaimed=[{"routing_id": "rt-bom-X", "material_code": "X",
                      "nsteps": 3, "factory_id": "FAC_MECH_001",
                      "model_code": "A-50-04-F"}],
        bom_rows=_bom("X", "焊接;烤漆;電控板;組立;紙箱"),
    )
    receipt = await rb.rederive_overclaimed_routes(db)
    assert receipt["narrowed"] == 0 and db.updates == []
    assert receipt["unchanged"] == 1


@pytest.mark.asyncio
async def test_under_evidenced_parts_go_to_process_engineering():
    """收窄后不足 2 道工序：说清"没人知道这个件怎么做"，而不是留一条假路线不管。"""
    db = _Db(
        overclaimed=[{"routing_id": "rt-bom-Y", "material_code": "Y",
                      "nsteps": 6, "factory_id": "FAC_MECH_001",
                      "model_code": "A-50-04-F"}],
        bom_rows=_bom("Y", "螺絲"),
    )
    receipt = await rb.rederive_overclaimed_routes(db)
    assert db.updates == []
    assert receipt["needs_process_engineering"][0]["material_code"] == "Y"
    assert receipt["needs_process_engineering"][0]["steps_on_route"] == 6


@pytest.mark.asyncio
async def test_dry_run_touches_nothing():
    db = _Db(
        overclaimed=[{"routing_id": "rt-bom-Z", "material_code": "Z",
                      "nsteps": 6, "factory_id": "FAC_MECH_001",
                      "model_code": "A-50-04-F"}],
        bom_rows=_bom("Z", "焊接;烤漆"),
    )
    receipt = await rb.rederive_overclaimed_routes(db, apply=False)
    assert receipt["narrowed"] == 1, "预演要报出会收窄几条"
    assert db.updates == [], "预演不许写库"
