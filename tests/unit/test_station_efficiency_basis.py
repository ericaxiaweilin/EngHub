"""工位效率的口径只有一个：填了用填报值，没填按不打折并标明是上界。

以前同一个"没填"在一条排程链上被兜了三个数 —— aps_service 两个分支各兜 0.85 与 0.9、
capacity_math 兜 1.0 —— 于是可用工时看代码走到哪个分支而定，而界面只显示算出来的利用率。
更常见的情形是 station_capacity 的行由工位档案自动带出（source=derived_station_master、
efficiency_rate=1），那是占位不是实测：排程按 100% 效率跑，利用率看着有余量、交期看着宽裕。
"""
from core.mes.capacity_math import (StationModel, classify_oee, efficiency_basis_buckets,
                                    efficiency_basis_from_models, resolve_oee)


def test_unset_efficiency_is_neutral_and_says_it_is_a_ceiling():
    oee, basis = resolve_oee({"station_id": "ST-A", "efficiency_rate": None})
    assert oee == 1.0
    assert "未填" in basis and "上界" in basis
    assert classify_oee({"efficiency_rate": None}) == "unset"
    assert classify_oee({"efficiency_rate": 0}) == "unset"


def test_placeholder_source_is_not_read_as_a_measurement():
    oee, basis = resolve_oee({"efficiency_rate": 1.0, "source": "derived_station_master"})
    assert oee == 1.0 and classify_oee({"efficiency_rate": 1.0, "source": "derived_station_master"}) == "placeholder"
    assert "自动带出" in basis and "未验证" in basis


def test_verified_at_moves_a_row_into_measured_and_values_are_kept():
    row = {"efficiency_rate": 0.82, "source": "ie_survey",
           "created_at": "2026-08-01 00:00:00", "verified_at": "2026-10-08 00:00:00"}
    oee, basis = resolve_oee(row)
    assert oee == 0.82
    assert classify_oee(row) == "verified" and "0.82" in basis
    assert classify_oee({"efficiency_rate": 0.9, "source": "ie_survey"}) == "declared"


def test_insert_time_stamp_is_not_a_verification():
    """station_capacity 38 行实测 verified_at == created_at，且 note 写着"需业务确认"。

    只看 verified_at 非空会把这批占位值读成"量过的"，催办整格消失 —— 那是假绿，
    比不分类更糟，所以这条单独锁住。
    """
    same = {"efficiency_rate": 1.0, "source": "derived_station_master",
            "created_at": "2026-08-07 08:35:41", "verified_at": "2026-08-07 08:35:41"}
    assert classify_oee(same) == "placeholder"
    _, basis = resolve_oee(same)
    assert "自动带出" in basis and "未验证" in basis
    out = efficiency_basis_buckets([dict(same, station_id=f"ST-{i}") for i in range(9)])
    assert out["verified"] == 0 and out["placeholder"] == 9 and out["all_unverified"] is True


def test_census_buckets_all_unverified_and_names_the_used_values():
    rows = [{"station_id": f"ST-{i}", "efficiency_rate": 1.0, "source": "derived_station_master"}
            for i in range(7)]
    rows.append({"station_id": "ST-X", "efficiency_rate": None})
    out = efficiency_basis_buckets(rows)
    assert out["active_stations"] == 8
    assert out["placeholder"] == 7 and out["unset"] == 1
    assert out["verified"] == 0 and out["all_unverified"] is True
    assert out["used_values"] == [1.0]
    assert "100%" in out["consequence"]           # 占位=按 100% 效率排产，这句必须能被念出来


def test_one_verified_row_stops_calling_the_factory_unmeasured():
    rows = [{"station_id": "ST-1", "efficiency_rate": 0.8, "source": "ie", "verified_at": "2026-10-01"},
            {"station_id": "ST-2", "efficiency_rate": 1.0, "source": "derived_station_master"}]
    out = efficiency_basis_buckets(rows)
    assert out["all_unverified"] is False and out["verified"] == 1
    assert out["used_values"] == [0.8, 1.0]


def test_models_path_uses_the_stored_kind_instead_of_re_guessing_strings():
    models = {
        "ST-1": StationModel(station_id="ST-1", oee=1.0, oee_kind="placeholder"),
        "ST-2": StationModel(station_id="ST-2", oee=0.85, oee_kind="verified",
                             oee_source="填报 0.85 验证过"),
    }
    out = efficiency_basis_from_models(models)
    assert out["placeholder"] == 1 and out["verified"] == 1
    assert out["all_unverified"] is False
    assert out["basis"].startswith("StationModel.oee_kind")


def test_empty_station_capacity_does_not_report_a_full_rate():
    """空集合不是"通过"：没有行就没有效率依据，不能算 all_unverified=False 而不出声。"""
    out = efficiency_basis_buckets([])
    assert out["active_stations"] == 0
    assert out["all_unverified"] is False          # 没有行可判，不能说"全是占位"
    assert "没有这个厂区的活跃行" in out["reading"]


def test_watchdog_gaps_only_while_no_efficiency_is_verified():
    from api.services.engine_watchdog import MIN_STATIONS_FOR_EFFICIENCY_GAP, gap_readings

    base = {"gen": {}, "sup": {}, "ready": {}, "pending": [], "mp": {}, "cons": {}}
    all_placeholder = efficiency_basis_buckets(
        [{"station_id": f"ST-{i}", "efficiency_rate": 1.0, "source": "derived_station_master"}
         for i in range(MIN_STATIONS_FOR_EFFICIENCY_GAP)])
    ev = set()
    found = gap_readings(eff=all_placeholder, evaluated_out=ev, **base)
    keys = {(f["loop"], f["kind"]) for f in found}
    assert ("station_efficiency_basis", "efficiency_all_placeholder") in keys
    assert "station_efficiency_basis" in ev

    ev2 = set()
    mixed = efficiency_basis_buckets(
        [{"station_id": "ST-1", "efficiency_rate": 0.8, "source": "ie", "verified_at": "2026-10-01"},
         {"station_id": "ST-2", "efficiency_rate": 1.0, "source": "derived_station_master"}])
    found2 = gap_readings(eff=mixed, evaluated_out=ev2, **base)
    assert ("station_efficiency_basis", "efficiency_all_placeholder") not in {(f["loop"], f["kind"]) for f in found2}
    assert "station_efficiency_basis" in ev2       # 查过要留痕，别把"没挂催办"当成"没查"


def test_no_fallback_constants_left_in_the_scheduling_path():
    """0.85 与 0.9 这两个兜底不许再回来：同一个缺值只能有一个口径。"""
    import inspect

    from api.services import aps_service
    from core.mes import capacity_math

    for module in (aps_service, capacity_math):
        src = inspect.getsource(module).replace(" ", "")
        assert "efficiency_rateor0.85" not in src, module.__name__
        assert "efficiency_rateor0.9" not in src, module.__name__
        assert "efficiency_rateor1.0" not in src, module.__name__
