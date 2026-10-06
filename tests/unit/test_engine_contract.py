"""引擎对外契约的单测：接口与模型无关这件事必须能被判出来，不是写在注释里。"""

import asyncio
import json

import pytest

from api.services import engine_contract as ec


def run(coro):
    return asyncio.run(coro)


# ---------- 词表与单位 ----------

def test_every_public_input_declares_units_range_step_and_basis():
    for name, spec in ec.INPUTS.items():
        assert spec["units"], name
        assert spec["default_unit"] in spec["units"], name
        assert spec["range"][0] <= spec["range"][1], name
        assert spec["step"] > 0, name
        assert spec["basis"] and spec["moves"], name
        assert spec["translate"][0] in ("perturb", "policy", "scope", "scenario"), name


def test_internal_names_are_all_forbidden_on_the_contract_face():
    # 词表翻译到的内部名，一个都不许出现在响应里 —— 否则 agent 会照内部名传参
    internals = {v["translate"][1] for v in ec.INPUTS.values()}
    internals |= {"changeover_hours", "attendance"}
    missing = sorted(k for k in internals if k not in ec.INTERNAL_ONLY_KEYS)
    assert missing == [], f"内部名没进禁泄漏清单：{missing}"


def test_unknown_parameter_is_rejected_not_ignored():
    with pytest.raises(ec.ContractError) as exc:
        ec._parse({"inputs": {"hours_multiplier": 1.2}})
    assert exc.value.allowed == sorted(ec.INPUTS)
    assert "内部" in exc.value.message


def test_unknown_unit_and_out_of_range_and_bad_date_are_rejected():
    with pytest.raises(ec.ContractError):
        ec._parse({"inputs": {"purchase_lead_time": {"value": 5, "unit": "days"}}})
    with pytest.raises(ec.ContractError):
        ec._parse({"inputs": {"crew_attendance": {"value": 3.0, "unit": "fraction_present"}}})
    with pytest.raises(ec.ContractError):
        ec._parse({"as_of": "10/06/2026"})
    with pytest.raises(ec.ContractError):
        ec._parse({"conditions": {"weather": "台风"}})


def test_bare_number_is_accepted_once_and_marked_assumed():
    parsed = ec._parse({"inputs": {"purchase_lead_time": 50}})
    echo = parsed["echo"][0]
    assert echo["unit"] == "percent_of_record" and echo["unit_assumed"] is True
    assert parsed["inputs"]["purchase_lead_time"]["value"] == 50.0


def test_count_units_must_be_integers():
    with pytest.raises(ec.ContractError):
        ec._parse({"inputs": {"lines_in_parallel": {"value": 1.5, "unit": "count"}}})


# ---------- 翻译：业务词 → 内部参数（内部名只活在返回值里） ----------

def test_translation_keeps_internal_names_out_of_public_objects():
    parsed = ec._parse({"inputs": {"unit_work_hours": 120, "extra_crew": 0.1,
                                   "start_before_full_kit": {"value": 0, "unit": "flag"},
                                   "promise_margin": 1.4}})
    scope, perturb, policy, attendance, equip = ec._translate(parsed)
    assert perturb["hours_multiplier"] == 1.2          # 内部名照旧传给推演
    assert policy["crew_bonus"] == 0.1 and policy["allow_partial"] is False
    assert scope["lead_margin"] == 1.4 and equip is None
    assert attendance == 0.97                          # 默认好天档
    # 但对外信封里不能出现这些键
    for key in ("hours_multiplier", "crew_bonus", "allow_partial", "lead_margin"):
        assert key in ec.INTERNAL_ONLY_KEYS


def test_weather_maps_to_attendance_and_equipment_is_relative_to_ledger():
    parsed = ec._parse({"conditions": {"weather": "storm"},
                        "inputs": {"equipment_availability": 120}})
    scope, perturb, _pol, att, equip = ec._translate(parsed)
    assert att == 0.70 and equip == 120 and "equip_rate" not in perturb


# ---------- 约束项翻译 ----------

def test_all_internal_binding_terms_have_business_labels():
    from api.services import virtual_run as vr
    import inspect

    src = inspect.getsource(vr.run_target)
    for internal in ("material_arrival", "group_queue", "work_content_hours", "work_duration"):
        assert internal in src, f"推演里用到的约束项 {internal} 需要业务说法"
        assert internal in ec.TERM_LABEL, internal
    assert all(v[0] not in ec.INTERNAL_ONLY_KEYS for v in ec.TERM_LABEL.values())
    assert all(v[0] not in ec.INTERNAL_ONLY_KEYS for v in ec.CAPACITY_LABEL.values())


# ---------- 信封纪律与泄漏扫描 ----------

def fake_metrics(**kw):
    base = {"finish_date": "2026-11-19", "days_late_worst": 21, "on_time_models": 1,
            "first_batch_units": 51.0, "waiting_for_material_units": 5949.0,
            "labor_cost_usd": 173250.0, "expedite_cost_usd": 0.0,
            "line_activation_cost_usd": 0.0, "binding_terms": ["material_arrival"],
            "attendance": 0.97, "promise_margin": 1.15, "blocked_models": [],
            "detail": [{"model_code": "A-50-04-F", "line": "LINE-BIKE-01", "units": 2400.0,
                        "finish_date": "2026-11-19", "due_date": "2026-10-29", "days_late": 21,
                        "status": "simulated", "batch_a_units": 18, "batch_b_units": 2382,
                        "binding_terms": ["material_arrival", "group_queue"],
                        "capacity_binding": "line_declared", "capacity_line_declared": 335.8,
                        "bottleneck_part": {"material_code": "RM-ELEC-036",
                                            "lead_time_days": 10, "supplier": "某供应商"},
                        "why": None}]}
    base.update(kw)
    return base


@pytest.mark.parametrize("nothing", [False, True])
def test_simulate_envelope_has_no_leaks_and_names_missing_data(monkeypatch, nothing):
    rows = fake_metrics()["detail"]

    async def fake_measure(db, fid, parsed, override=None, models=None):
        return fake_metrics(detail=[] if nothing else rows,
                            finish_date=None if nothing else "2026-11-19",
                            binding_terms=[] if nothing else ["material_arrival"])

    monkeypatch.setattr(ec, "_measure", fake_measure)
    out = run(ec.simulate(None, "FAC_MECH_001", {"n_models": 2}))
    assert ec.leak_paths(out) == []
    assert ec.envelope_violations(out) == []
    if nothing:
        assert out["unavailable"] and out["unavailable"][0]["missing"]
        assert out["answers"]["portfolio_completion_date"] is None
    else:
        assert out["answers"]["orders"][0]["constrained_by"][0]["code"] == "waiting_for_material"
        assert out["answers"]["orders"][0]["daily_output_limited_by"][0]["code"] == "line_declared_rate"
    assert out["provenance"]["sandbox_only"] is True and out["provenance"]["external_write"] is False
    assert json.dumps(out, ensure_ascii=False)  # 可序列化


def test_leak_paths_finds_nested_internal_keys():
    payload = {"answers": {"orders": [{"hours_multiplier": 1.2, "line_code": "X"}]}}
    found = ec.leak_paths(payload)
    assert {f["key"] for f in found} == {"hours_multiplier", "line_code"}


def test_envelope_violations_catches_unitless_number_and_blank_unavailable():
    bad = {"metrics": [{"name": "交期", "value": 5, "unit": "", "basis": "x"}],
           "unavailable": [{"name": "y", "state": "not_computable", "reason": "算不出"}]}
    v = ec.envelope_violations(bad)
    assert any("没有单位" in x for x in v) and any("没点名缺什么" in x for x in v)


def test_spec_describes_every_interface_and_input():
    s = ec.spec()
    assert [i["name"] for i in s["interfaces"]] == ["simulate", "sensitivity", "attribution"]
    assert {i["name"] for i in s["inputs"]} == set(ec.INPUTS)
    assert any("0 冒充" in x for x in s["invariants"])
    assert any("不写" in x or "external_write" in x or "沙箱" in x for x in s["invariants"])


def test_demand_changer_is_flagged_and_excluded_from_optimisation_language():
    sizes = [i for i in ec.spec()["inputs"] if i["name"] == "order_size_days_of_output"]
    assert sizes and sizes[0]["changes_demand"] is True
    assert "不能当优化杠杆" in sizes[0]["moves"]


# ---------- 方向合理性：斜率与业务常识相反时不许当改善建议 ----------

def test_every_actionable_input_declares_a_physical_direction():
    for name, spec in ec.INPUTS.items():
        if spec["kind"] == "scope":
            continue
        assert spec.get("physics") in ("gte", "lte"), (name, spec.get("physics"))


def test_relief_state_splits_measured_no_effect_and_suspicious():
    assert ec.relief_state("purchase_lead_time", 2.0)[0] == "measured"
    assert ec.relief_state("purchase_lead_time", 0.0)[0] == "no_effect_measured"
    # 提前期加大一档却把交期提前了 —— 物理上说不通，读数不可信
    st, why = ec.relief_state("purchase_lead_time", -1.5)
    assert st == "suspicious_direction" and "相反" in why
    # 到岗率加大一档应该更早（lte）
    assert ec.relief_state("crew_attendance", -0.8)[0] == "measured"
    assert ec.relief_state("crew_attendance", 0.9)[0] == "suspicious_direction"


def test_spec_lists_every_interface_with_the_same_request_shape():
    """自述是给机器读的：三个接口的 request 必须是同一种形状，不能一个 dict 一个字符串。

    之前 sensitivity 写的是"与 simulate 相同（…）"这种人话 —— 人看得懂，
    agent 按 dict 解析就当场崩，等于接口没有自述。"""
    sp = ec.spec()
    by_name = {i["name"]: i for i in sp["interfaces"]}
    assert set(by_name) == {"simulate", "sensitivity", "attribution"}
    common = set(by_name["simulate"]["request"])
    for name, item in by_name.items():
        assert isinstance(item["request"], dict), name
        assert common <= set(item["request"]), (name, sorted(common - set(item["request"])))
        assert item.get("request_note"), name
    assert "compare" in by_name["attribution"]["request"]
