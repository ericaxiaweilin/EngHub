"""引擎对外契约：agent 只说业务名词，不知道模型内部长什么样。

设计约束（用户 2026-10-06 定稿）：接口稳定、实现隐藏。输入输出只用业务概念
（机种、日期、受控词表里的参数名 + 单位），内部 kwarg 名、节点/边/工位/线组标识
一律不许出现在契约面上。引擎内部换算法、加层、重排图，agent 和前端都不用跟着改。

三个接口对应三类问题，共用同一个信封：
  simulate      ——「这些条件下几号能交、延几天、卡在哪一项」
  sensitivity   ——「哪个业务输入最能动结果，动一档值几天，这个答案现在可信到几成」
  attribution   ——「为什么是这个答案 / 换个条件为什么会变，各项各占几天」

信封的三条硬规则不是文档措辞，self_check() 会把它们算成数：
1. 每个数带 unit 与 basis；算不出来就进 unavailable 并点名缺什么，不返回 0 冒充算过。
2. 请求是封闭词表：词表外的参数名一律结构化拒绝并回可选项，不静默忽略。
3. 响应里不出现内部标识（INTERNAL_ONLY_KEYS），泄漏数必须为 0。
"""

from __future__ import annotations

import time
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from api.services import sim_sensitivity as ss
from api.services import virtual_run as vr

CONTRACT_VERSION = "1"

# 契约面禁止出现的内部标识。值里出现产线/料号这类**主数据编码**是允许的（工厂自己就这么叫），
# 但键名一旦是内部 kwarg，就说明实现漏进了接口 —— agent 会照那个名字传参，内部改名它就崩。
INTERNAL_ONLY_KEYS = {
    "hours_multiplier", "lead_multiplier", "stock_multiplier", "equip_rate", "crew_bonus",
    "allow_partial", "days_of_output", "lead_margin", "batches", "changeover_hours",
    "parallel_lines", "expedite_lead_days", "ignore_backlog", "displaces_committed_work",
    "perturb", "policy", "scenarios", "attendance", "capacity_binding", "binding_terms",
    "binding_per_model", "capacity_basis", "line_group", "line_code", "routing_template_id",
    "station_id", "work_center", "nodes", "edges", "kwargs", "sql", "traceback",
}

# 推演内部约束项 → 业务说法。计划员看的是"等料"还是"排队"，不是 material_arrival。
TERM_LABEL = {
    "material_arrival": ("waiting_for_material", "等料：瓶颈件按提前期还没到"),
    "group_queue": ("queued_behind_orders", "排队：同组产线被更前面的单占着"),
    "work_content_hours": ("limited_by_work_content", "做不完：人数×班次 ÷ 单件工时是上限"),
    "work_duration": ("limited_by_shift_hours", "日历：受班次与休息日限制"),
}
# 归因时"松掉这一项"能解开的约束是哪一类（不是先入为主，只是同一份占用关系换个说法）
RELIEF_TERMS = {
    "purchase_lead_time": ("waiting_for_material",),
    "available_stock": ("waiting_for_material",),
    "expedite_bottleneck_to_days": ("waiting_for_material",),
    "start_before_full_kit": ("waiting_for_material",),
    "lines_in_parallel": ("queued_behind_orders",),
    "batches_per_order": ("queued_behind_orders",),
    "unit_work_hours": ("limited_by_work_content",),
    "crew_attendance": ("limited_by_work_content",),
    "extra_crew": ("limited_by_work_content",),
    "equipment_availability": ("limited_by_work_content",),
}
CAPACITY_LABEL = {
    "line_declared": ("line_declared_rate", "产线声明的日产量"),
    "ie_hours": ("crew_and_work_hours", "班组按单件工时做得完的台数"),
    "no_capacity": ("no_capacity_basis", "没有可比的产能依据"),
}
WEATHER = {"fair": 0.97, "rain": 0.92, "storm": 0.70}

# 受控词表：业务输入 → 单位、档位、它改什么、翻译成内部要怎么传。翻译只发生在 _split 一处。
INPUTS: Dict[str, Dict[str, Any]] = {
    "unit_work_hours": {
        "label": "单件工时", "kind": "input",
        "units": {"percent_of_record": "相对台账现值的百分比（100=不改）"},
        "default_unit": "percent_of_record", "range": (10, 400), "step": 10,
        "physics": "gte",
        "translate": ("perturb", "hours_multiplier", 0.01),
        "moves": "交期与用工；当产线声明的台/天是上限时可能不动（看 constrained_by）",
        "basis": "IE 路线标准工时；缺则借同族路线，再缺按产线节拍反推 —— 各自允许误差见 data_confidence",
    },
    "purchase_lead_time": {
        "label": "外购件提前期", "kind": "input",
        "units": {"percent_of_record": "相对台账提前期的百分比（100=不改，50=压一半）"},
        "default_unit": "percent_of_record", "range": (10, 300), "step": 25,
        "physics": "gte",
        "translate": ("perturb", "lead_multiplier", 0.01),
        "moves": "开工日：到货日往前挪，首批能开几台、组合完工日提前几天",
        "basis": "materials.lead_time_days（外购料号台账实测有值）",
    },
    "available_stock": {
        "label": "账上可用库存", "kind": "input",
        "units": {"percent_of_record": "相对库存台账可用量的百分比"},
        "default_unit": "percent_of_record", "range": (0, 400), "step": 50,
        "physics": "lte",
        "translate": ("perturb", "stock_multiplier", 0.01),
        "moves": "现料先开一批能开几台",
        "basis": "库存台账可用量；料号在台账里没有行按 0 算，不假设有货",
    },
    "crew_attendance": {
        "label": "到岗比例", "kind": "input",
        "units": {"fraction_present": "到岗人数占应到人数的比例（0.70=暴雨档）"},
        "default_unit": "fraction_present", "range": (0.3, 1.0), "step": 0.05,
        "physics": "lte",
        "translate": ("scenario", "attendance", 1.0),
        "moves": "人力绑定的那条线一天出几台",
        "basis": "外生条件；系统标定的好天档是 0.97",
    },
    "equipment_availability": {
        "label": "设备可用率", "kind": "input",
        "units": {"percent_of_record": "相对台账实测可用率的百分比（100=台账值）"},
        "default_unit": "percent_of_record", "range": (20, 130), "step": 10,
        "physics": "lte",
        "translate": ("perturb", "equip_rate", 1.0),
        "moves": "停机台数折进日产能之后的交期与用工",
        "basis": "设备台账：可用台数 ÷ 总台数（实测，不是假设）",
    },
    "batches_per_order": {
        "label": "同一张单拆几批投放（总量不变）", "kind": "input",
        "units": {"count": "批数"},
        "default_unit": "count", "range": (1, 8), "step": 1,
        "physics": "gte",
        "translate": ("perturb", "batches", 1.0),
        "moves": "只计换型工时；搬运/清线/再齐套没建模，所以只能证伪「拆批免费」，不能证明它",
        "basis": f"换型取系统里唯一数字 {vr.SIM_CHANGEOVER_HOURS:g} 小时/次（APS 默认 300 秒）",
    },
    "lines_in_parallel": {
        "label": "同组并联开线条数", "kind": "input",
        "units": {"count": "条数"},
        "default_unit": "count", "range": (1, 4), "step": 1,
        "physics": "lte",
        "translate": ("policy", "parallel_lines", 1.0),
        "moves": "换几天交期；开线代价按实际激活台数计入",
        "basis": "产能取该线组**声明的合并产能**，不是单线×条数（跑步机组 300 台/天，bike 两线合并 700 不是 800）",
    },
    "extra_crew": {
        "label": "加班加人比例", "kind": "input",
        "units": {"fraction_added": "在应到人数上追加的比例（0.15=加 15%）"},
        "default_unit": "fraction_added", "range": (0.0, 0.5), "step": 0.05,
        "physics": "lte",
        "translate": ("policy", "crew_bonus", 1.0),
        "moves": "工时上限松开之后的交期与人工成本",
        "basis": "库里没有薪资列，人工按标定 $30/人日，只到量级",
    },
    "start_before_full_kit": {
        "label": "现料先开一批（不等齐套）", "kind": "input",
        "units": {"flag": "true/false"},
        "default_unit": "flag", "range": (0, 1), "step": 1,
        "physics": "lte",
        "translate": ("policy", "allow_partial", 1.0),
        "moves": "先开量与交期：true=现料够的先做，false=等齐套才开工",
        "basis": "齐套口径来自多层 BOM 展开 + 库存台账",
    },
    "expedite_bottleneck_to_days": {
        "label": "瓶颈件加急到几天", "kind": "input",
        "units": {"days": "目标提前期（天）"},
        "default_unit": "days", "range": (1, 30), "step": 1,
        "physics": "gte",
        "translate": ("policy", "expedite_lead_days", 1.0),
        "moves": "把最慢那个外购件的到货压到 N 天，提前几天交、加急费多少",
        "basis": "瓶颈件与提前期从 BOM+台账解析，不写死料号",
    },
    "promise_margin": {
        "label": "承诺交期系数", "kind": "scope",
        "units": {"multiple_of_bottleneck_lead": "承诺交期 = 瓶颈件提前期 × 该系数"},
        "default_unit": "multiple_of_bottleneck_lead", "range": (1.0, 2.5), "step": 0.15,
        "translate": ("scope", "lead_margin", 1.0),
        "moves": "改的是「算不算误期」的口径，不改产能：放宽系数不会让任何东西变快",
        "basis": f"标定上限 {vr.PROMISE_LEAD_MARGIN:g}（超出即只作诊断，不进稳健推荐）",
    },
    "order_size_days_of_output": {
        "label": "订单大小（每台单下几天产量）", "kind": "scope",
        "units": {"days": "该线几天的产量"},
        "default_unit": "days", "range": (1, 20), "step": 1,
        "translate": ("scope", "days_of_output", 1.0),
        "moves": "改的是**要多少台**，不是怎么排：少下单当然又快又省，不能当优化杠杆引用",
        "basis": "场景自标定：批量小到一天就能做完时，产能/人力/线这些维度全都没有区分度",
        "changes_demand": True,
    },
}
QUESTIONS = {
    "simulate": "这些条件下几号能交、延几天、卡在哪一项",
    "sensitivity": "哪个业务输入最能动结果、动一档值几天，这个答案现在可信到几成",
    "attribution": "为什么是这个答案；换个条件为什么会变，各项各占几天",
}


class ContractError(ValueError):
    """请求不符合契约。带 field/allowed，让调用方自己改对，而不是拿 500 猜。"""

    def __init__(self, field: str, message: str, *, allowed: Any = None) -> None:
        super().__init__(message)
        self.field = field
        self.message = message
        self.allowed = allowed

    def as_dict(self) -> Dict[str, Any]:
        return {"error": "invalid_request", "contract_version": CONTRACT_VERSION,
                "field": self.field, "message": self.message, "allowed": self.allowed,
                "ask": "改用 allowed 里的名字与单位重发"}


def _flag(raw: Any) -> int:
    if isinstance(raw, str):
        return 1 if raw.strip().lower() in ("1", "true", "yes", "y", "是") else 0
    return 1 if bool(raw) else 0


def _coerce(name: str, raw: Any) -> Tuple[float, str, bool]:
    """把请求里的值压成 (数值, 单位, 单位是否为代填)。"""
    spec = INPUTS[name]
    if isinstance(raw, dict):
        if raw.get("value") is None:
            raise ContractError(name, f"{spec['label']} 需要 value")
        unit = str(raw.get("unit") or spec["default_unit"])
        assumed = not raw.get("unit")
        val = raw.get("value")
    else:
        unit, assumed, val = spec["default_unit"], True, raw
    if unit not in spec["units"]:
        raise ContractError(name, f"{spec['label']} 的单位 «{unit}» 不在契约里",
                            allowed=sorted(spec["units"]))
    val = _flag(val) if unit == "flag" else float(val)
    if unit in ("count", "days") and abs(val - round(val)) > 1e-9:
        raise ContractError(name, f"{spec['label']} 按 {unit} 必须是整数，收到 {val:g}")
    lo, hi = spec["range"]
    if not (lo <= val <= hi):
        raise ContractError(name, f"{spec['label']}={val:g} {unit} 超出契约范围 [{lo:g}, {hi:g}]")
    return val, unit, assumed


def _holder(name: str, raw: Any) -> Dict[str, Any]:
    val, unit, assumed = _coerce(name, raw)
    spec = INPUTS[name]
    return {"name": name, "label": spec["label"], "value": val, "unit": unit,
            "unit_assumed": assumed, "moves": spec["moves"], "basis": spec["basis"]}


def _parse(request: Dict[str, Any]) -> Dict[str, Any]:
    """封闭词表：契约不认识的一律拒绝并列出可选项，绝不静默忽略。"""
    given = dict(request.get("scope") or {})
    given.update(request.get("inputs") or {})
    unknown = sorted(k for k in given if k not in INPUTS)
    if unknown:
        raise ContractError("inputs",
                            f"这些名字不在契约里：{unknown}。引擎内部的参数名不能当接口用",
                            allowed=sorted(INPUTS))
    # 内部键只在这份 dict 里活着一层，对外一律用 INPUTS 里的业务名
    spec = {"days_of_output": 6.0, "lead_margin": vr.PROMISE_LEAD_MARGIN,
            "weather": "fair", "as_of": None,
            "models": ([str(m) for m in request.get("models") or []]) or None}
    n_models = max(1, min(8, int(request.get("n_models") or 5)))
    echo: List[Dict[str, Any]] = []
    inputs: Dict[str, Any] = {}
    for key in ("order_size_days_of_output", "promise_margin"):
        src = (request.get("scope") or {}).get(key, (request.get("inputs") or {}).get(key))
        if src is not None:
            h = _holder(key, src)
            spec[{"order_size_days_of_output": "days_of_output",
                  "promise_margin": "lead_margin"}[key]] = h["value"]
            echo.append(h)
    as_of = request.get("as_of") or (request.get("scope") or {}).get("as_of")
    if as_of:
        try:
            spec["as_of"] = date.fromisoformat(str(as_of)[:10])
        except ValueError:
            raise ContractError("as_of", f"日期 «{as_of}» 不是 YYYY-MM-DD",
                                allowed=["YYYY-MM-DD"])
    weather = str((request.get("conditions") or {}).get("weather") or "")
    if weather:
        if weather not in WEATHER:
            raise ContractError("conditions.weather", f"天气档 «{weather}» 不在契约里",
                                allowed=sorted(WEATHER))
        spec["weather"] = weather
    for key, raw in (request.get("inputs") or {}).items():
        h = _holder(key, raw)
        inputs[key] = h
        echo.append(h)
    return {"scope": spec, "n_models": n_models, "inputs": inputs, "echo": echo}


def _translate(parsed: Dict[str, Any], *, override: Optional[Dict[str, Any]] = None
               ) -> Tuple[Dict[str, Any], Dict[str, float], Dict[str, Any], float,
                          Optional[float]]:
    """业务词表 → 推演的四路内部参数。内部名只活在这一个函数里。"""
    inputs = dict(parsed["inputs"])
    if override:
        inputs.update(override)
    scope = dict(parsed["scope"])
    perturb: Dict[str, float] = {}
    policy: Dict[str, Any] = {"name": "契约请求的政策", "allow_partial": True}
    attendance = WEATHER.get(str(scope.get("weather") or "fair"), 0.97)
    equip_percent: Optional[float] = None
    for key, holder in inputs.items():
        where, internal, scale = INPUTS[key]["translate"]
        val = float(holder["value"])
        if where == "scope":
            scope[internal] = val
        elif where == "scenario":
            attendance = val
        elif where == "policy":
            policy[internal] = bool(_flag(val)) if internal == "allow_partial" else val
        elif internal == "equip_rate":
            equip_percent = val          # 相对台账实测，不把绝对值暴露给调用方
        else:
            perturb[internal] = round(val * scale, 6)
            if internal == "batches":
                perturb["changeover_hours"] = float(vr.SIM_CHANGEOVER_HOURS)
    return scope, perturb, policy, attendance, equip_percent


async def _measure(db: AsyncSession, factory_id: str, parsed: Dict[str, Any],
                   override: Optional[Dict[str, Any]] = None,
                   models: Optional[List[str]] = None) -> Dict[str, Any]:
    scope, perturb, policy, attendance, equip_percent = _translate(parsed, override=override)
    chosen = models if models is not None else (
        scope.get("models") or await vr.default_models(db, factory_id,
                                                       int(parsed["n_models"])))
    if equip_percent is not None:
        base_eq = float((await vr.equipment_rate(db, factory_id)).get("rate") or 1.0)
        perturb["equip_rate"] = round(base_eq * equip_percent / 100.0, 4)
    else:
        base_eq = float((await vr.equipment_rate(db, factory_id)).get("rate") or 1.0)
        if base_eq:
            perturb["equip_rate"] = base_eq
    targets = await vr.derive_targets(db, factory_id, chosen,
                                      days_of_output=float(scope.get("days_of_output") or 6.0),
                                      lead_margin=float(scope.get("lead_margin")
                                                       or vr.PROMISE_LEAD_MARGIN))
    scen = "请求场景"
    scan = await vr.scan_policies(db, factory_id, targets, policies=[policy],
                                  scenarios=[{"name": scen, "attendance": attendance}],
                                  perturb=perturb)
    metrics = ss._metrics(scan, scen)
    sols = ((scan.get("by_scenario") or {}).get(scen) or {}).get("solutions") or []
    metrics["detail"] = (sols[0].get("detail") or []) if sols else []
    metrics["attendance"] = attendance
    metrics["promise_margin"] = float(scope.get("lead_margin") or vr.PROMISE_LEAD_MARGIN)
    metrics["models"] = list(chosen or [])
    return metrics


def relief_state(name: str, days_per_step: float) -> Tuple[str, str]:
    """把实测斜率分成"可用的改善建议 / 测不出效果 / 方向与常识相反"。

    方向反了不是精度问题，是这一档根本没跨过门槛或读数是噪声 —— 拿它建议"降低设备可用率"
    就是把模型缺陷传给计划员。所以这里只标注、不替他决定信不信。
    """
    expected = INPUTS[name].get("physics")
    gain = float(days_per_step or 0)
    if abs(gain) < 1e-9:
        return ("no_effect_measured",
                "这一档测不出效果：要么它不是当前约束，要么档位没跨过门槛（看 days_gained_at_steepest_step）")
    if not expected:
        return ("unknown_expectation", "词表没声明这一项的物理方向，无法判读")
    ok = gain >= 0 if expected == "gte" else gain <= 0
    if ok:
        return ("measured", f"方向符合业务常识（{expected}）")
    return ("suspicious_direction",
            f"实测方向与业务常识相反（{INPUTS[name]['label']} 加大一档应当 {expected}，"
            "却读出相反）—— 这一项不能当改善建议引用")


def _metric(name: str, value: Any, unit: str, basis: str, *,
            confidence: Optional[float] = None, ci: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"name": name, "value": value, "unit": unit, "basis": basis,
            "confidence": confidence, "ci": ci}


def _unavailable(name: str, reason: str, missing: str, ask: str) -> Dict[str, Any]:
    return {"name": name, "state": "not_computable", "reason": reason,
            "missing": missing, "ask": ask}


def _public_terms(codes: Any) -> List[Dict[str, str]]:
    out = []
    for c in codes or []:
        pub, label = TERM_LABEL.get(str(c), (str(c), "未归类的约束项"))
        if pub not in [x["code"] for x in out]:
            out.append({"code": pub, "label": label})
    return out


def _orders(metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for d in metrics.get("detail") or []:
        rows.append({
            "model": d.get("model_code"),
            "on_line": d.get("line"),
            "status": d.get("status"),
            "units": d.get("units"),
            "completion_date": d.get("finish_date"),
            "due_date": d.get("due_date"),
            "days_late": d.get("days_late"),
            "first_batch_units": d.get("batch_a_units"),
            "waiting_for_material_units": d.get("batch_b_units"),
            "wait_days_for_material": d.get("wait_days_for_material"),
            "queue_days_before_this_order": d.get("queue_days_before_this_order"),
            "bottleneck_part": d.get("bottleneck_part"),
            "constrained_by": _public_terms(d.get("binding_terms")),
            "daily_output_limited_by": [dict(zip(("code", "label"),
                                                 CAPACITY_LABEL.get(str(d.get("capacity_binding")),
                                                                    ("other", "其它产能依据"))))],
            "declared_daily_output": d.get("capacity_line_declared"),
            "why_not": d.get("why"),
        })
    return rows


def _envelope(interface: str, parsed: Dict[str, Any], *, answers: Dict[str, Any],
              metrics: List[Dict[str, Any]], unavailable: List[Dict[str, Any]],
              caveats: List[str], started: float) -> Dict[str, Any]:
    scope = parsed["scope"]
    return {
        "contract_version": CONTRACT_VERSION,
        "interface": interface,
        "question": QUESTIONS[interface],
        "scope": {"models": scope.get("models"), "as_of": str(scope.get("as_of") or date.today()),
                  "order_size_days_of_output": scope.get("days_of_output"),
                  "promise_margin": scope.get("lead_margin"),
                  "weather": scope.get("weather"),
                  "weather_meaning": f"到岗 {WEATHER.get(str(scope.get('weather')), 0.97):g}"},
        "inputs_echo": parsed["echo"],
        "answers": answers,
        "metrics": metrics,
        "unavailable": unavailable,
        "caveats": caveats,
        "provenance": {"computed_at": datetime.now().isoformat(timespec="seconds"),
                       "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                       "sandbox_only": True, "external_write": False,
                       "how_it_was_computed": "与政策扫描同一条推演路径，不另建第二套算法"},
    }


async def simulate(db: AsyncSession, factory_id: str,
                   request: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    started = time.perf_counter()
    parsed = _parse(request or {})
    m = await _measure(db, factory_id, parsed)
    orders = _orders(m)
    dated = [o for o in orders if o.get("completion_date")]
    days_late = [int(o.get("days_late") or 0) for o in dated]
    unavailable: List[Dict[str, Any]] = []
    if not dated:
        unavailable.append(_unavailable(
            "completion_date", "没有任何一台推出完工日",
            "这批机种在当前输入下排不出时间线",
            "看 answers.orders[].why_not，或改用 sensitivity 查哪一维最卡"))
    answers = {
        "portfolio_completion_date": max((o["completion_date"] for o in dated), default=None),
        "earliest_completion_date": min((o["completion_date"] for o in dated), default=None),
        "worst_days_late": max(days_late) if days_late else None,
        "on_time_orders": sum(1 for x in days_late if x <= 0),
        "orders_total": len(orders),
        "units_first_batch": m.get("first_batch_units"),
        "units_waiting_for_material": m.get("waiting_for_material_units"),
        "constrained_by": _public_terms(m.get("binding_terms")),
        "orders": orders,
        "blocked_models": m.get("blocked_models"),
    }
    metrics = [
        _metric("组合完工日", answers["portfolio_completion_date"], "日历日",
                f"{len(dated)}/{len(orders)} 台推出时间线，取最晚那一台"),
        _metric("最晚延误", answers["worst_days_late"], "天",
                f"承诺交期=瓶颈件提前期×{m.get('promise_margin'):g}，到岗 {m.get('attendance'):g}"),
        _metric("准点单数", answers["on_time_orders"], "单",
                f"分母 {len(orders)} 单（含推不出日期的，那些不算准点）"),
        _metric("首批可开工台数", m.get("first_batch_units"), "台", "按库存台账现料，够的先开"),
        _metric("等料台数", m.get("waiting_for_material_units"), "台",
                "要等外购件到货才能开工的那部分"),
        _metric("人工成本", m.get("labor_cost_usd"), "USD",
                "库里没有薪资列，按标定 $30/人日，只到量级"),
        _metric("加急成本", m.get("expedite_cost_usd"), "USD", "只对政策里真加急的料计"),
        _metric("开线成本", m.get("line_activation_cost_usd"), "USD", "并联开线的激活代价"),
    ]
    caveats = ["沙箱读数：不写业务表、不回写外部系统；要落地得计划员确认后另走单据",
               "收益侧未建模（延误罚则/客户违约成本没有数），这里的钱只是成本差值，用于排序"]
    caveats.append(f"批量按「{parsed['scope'].get('days_of_output'):g} 天产量」下单 —— "
                   "它改的是要多少台，不是怎么排；引用交期时别把它当优化结果")
    return _envelope("simulate", parsed, answers=answers, metrics=metrics,
                     unavailable=unavailable, caveats=caveats, started=started)


ACCURACY_LABELS = {"hours": "unit_work_hours", "lead_time": "purchase_lead_time",
                   "supplier": "supplier", "stock": "available_stock",
                   "make_or_buy": "in_house_or_purchased", "price": "unit_price"}


def _public_input_for(internal: str) -> Optional[str]:
    for name, spec in INPUTS.items():
        if spec["translate"][1] == internal:
            return name
    return None


async def sensitivity(db: AsyncSession, factory_id: str,
                      request: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    started = time.perf_counter()
    parsed = _parse(request or {})
    models = parsed["scope"].get("models") or await vr.default_models(
        db, factory_id, int(parsed["n_models"]))
    rep = await ss.report(db, factory_id, models,
                          days_of_output=float(parsed["scope"].get("days_of_output") or 6.0),
                          lead_margin=float(parsed["scope"].get("lead_margin")
                                            or vr.PROMISE_LEAD_MARGIN),
                          attendance=WEATHER.get(str(parsed["scope"].get("weather") or "fair"), 0.97))
    sens, acc, unc = rep["sensitivity"], rep["accuracy"], rep["uncertainty"]

    rows: List[Dict[str, Any]] = []
    unavailable: List[Dict[str, Any]] = []
    for lever in sens.get("levers") or []:
        internal = str(lever.get("key"))
        pub = _public_input_for(internal)
        if not pub:
            continue
        sl = lever.get("slope") or {}
        if not sl.get("computable"):
            unavailable.append(_unavailable(
                pub, str(sl.get("why") or "曲线取不到局部斜率"),
                "这一维的档位结果不足（基准档或对比档缺失）",
                "换更小批量或多取几台机种，让这一维有区分度"))
            continue
        rows.append({
            "input": pub, "label": lever.get("label"),
            "measures": lever.get("reads_as"),
            "one_step": {"value": INPUTS[pub]["step"], "unit": INPUTS[pub]["default_unit"]},
            "days_per_step": sl.get("days_per_step"),
            "labor_usd_per_step": sl.get("labor_usd_per_step"),
            "on_time_models_per_step": sl.get("on_time_models_per_step"),
            "days_per_step_average_fit": sl.get("days_per_step_fit"),
            "days_at_steepest_step": sl.get("steepest_days_per_step"),
            "steepest_at": sl.get("steepest_at_level"),
            "step_like": bool(sl.get("nonlinear")),
            "citation_rule": sl.get("shape_note"),
            "changes_demand": bool(lever.get("not_a_scheduling_lever")),
            "curve_points": sum(1 for r in lever.get("curve") or [] if r.get("finish_date")),
        })
    citable = [r for r in rows if not r["changes_demand"]]
    ranked = sorted(citable, key=lambda r: -abs(float(r.get("days_per_step") or 0)))
    per_model = unc.get("per_model") or []
    band_sum = round(max((float(r.get("uncertainty_days_sum") or 0) for r in per_model),
                         default=0.0), 2) or None
    base = sens.get("base") or {}
    answers = {
        "base": {"portfolio_completion_date": base.get("finish_date"),
                 "days_late": base.get("days_late_worst"),
                 "constrained_by": _public_terms(base.get("binding_terms")),
                 "worst_weather": {"portfolio_completion_date": (base.get("worst_weather") or {}).get(
                     "finish_date"),
                     "days_late": (base.get("worst_weather") or {}).get("days_late_worst"),
                     "labor_cost_usd": (base.get("worst_weather") or {}).get("labor_cost_usd"),
                     "meaning": "同一政策在暴雨（到岗 0.70）那一档的结果，只报好天的数就是挑好看的看"}},
        "inputs": rows,
        "ranking": [{"input": r["input"], "label": r["label"],
                     "days_per_step": r["days_per_step"], "step_like": r["step_like"]}
                    for r in ranked if abs(float(r["days_per_step"] or 0)) > 0],
        "answer_confidence": {
            "uncertainty_days_worst_single_input": round(
                max((float(x.get("uncertainty_days_now") or 0) for r in per_model
                     for x in r.get("items") or []), default=0.0), 2),
            "uncertainty_days_sum": band_sum,
            "after_repair_days": round(min((float(r.get("uncertainty_days_after_repair") or 0)
                                            for r in per_model), default=0.0), 2) or None,
            "value_of_repair": unc.get("value_of_repair"),
            "method": unc.get("method"),
        },
        "data_confidence": {
            "overall": acc.get("overall_accuracy"), "weights": acc.get("weights"),
            "per_input": [{"input": ACCURACY_LABELS.get(str(d.get("input")), str(d.get("input"))),
                           "coverage": d.get("coverage"), "basis": d.get("basis")}
                          for r in per_model for d in (r.get("drags") or [])][:12],
            "economic_readiness": rep.get("economic_readiness"),
        },
    }
    metrics = [
        _metric("可测输入占比", round(len([r for r in citable if r["curve_points"] > 1]) /
                                     max(1, len(citable)), 3), "比例",
                f"{len(citable)} 个业务输入的档位曲线里，跨过基准档两侧才有局部斜率"),
        _metric("交期不确定天数", band_sum, "天", str(unc.get("method"))),
        _metric("映射精度", acc.get("overall_accuracy"), "百分分（0-100）",
                "只统计输入有没有真依据，不给结果打分；权重 工时30/提前期25/供应商15/库存15/"
                "自制外购10/单价5 是本系统口径，改口径改 sim_sensitivity.ACCURACY_WEIGHTS"),
        _metric("台阶型输入数", sum(1 for r in rows if r["step_like"]), "个",
                "近处 0 天、跨门槛那档才跳的曲线；按平均斜率引用会低报"),
    ]
    caveats = ["斜率只取基准两侧最近档：台阶型要看 days_at_steepest_step 并说明门槛在哪",
               str((rep.get("economic_readiness") or {}).get("usable_for") or ""),
               "订单大小那一格改的是要多少台，不进 ranking，也不能引用成优化收益"]
    caveats = [c for c in caveats if c]
    return _envelope("sensitivity", parsed, answers=answers, metrics=metrics,
                     unavailable=unavailable, caveats=caveats, started=started)


async def attribution(db: AsyncSession, factory_id: str,
                      request: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    started = time.perf_counter()
    parsed = _parse(request or {})
    models = parsed["scope"].get("models") or await vr.default_models(
        db, factory_id, int(parsed["n_models"]))
    m = await _measure(db, factory_id, parsed, models=models)
    orders = _orders(m)
    unavailable: List[Dict[str, Any]] = []

    # ① 约束归因（确定性）：每台单被哪一项卡住，是这一轮推演直接读出的占用/到货关系
    constraints = [{"model": o.get("model"), "on_line": o.get("on_line"),
                    "constrained_by": o.get("constrained_by")}
                   for o in orders if o.get("constrained_by")]
    binding_codes = {c["code"] for x in constraints for c in x["constrained_by"]}

    # ② 有利方向实测：松掉每一项业务输入一档值几天，斜率来自逐档真跑，不是权重打分
    rep = await ss.report(db, factory_id, models,
                          days_of_output=float(parsed["scope"].get("days_of_output") or 6.0),
                          lead_margin=float(parsed["scope"].get("lead_margin")
                                            or vr.PROMISE_LEAD_MARGIN),
                          attendance=WEATHER.get(str(parsed["scope"].get("weather") or "fair"), 0.97))
    slope_of = {str(l.get("key")): (l.get("slope") or {}) for l in rep["sensitivity"]["levers"]}
    relief: List[Dict[str, Any]] = []
    for name, spec in INPUTS.items():
        if spec.get("changes_demand") or spec["kind"] == "scope":
            continue
        sl = slope_of.get(spec["translate"][1]) or {}
        if not sl.get("computable"):
            unavailable.append(_unavailable(
                name, "这一维测不出斜率，无法归因", "档位曲线里缺基准档或对比档",
                "放宽批量或多选几台机种，让它有区分度"))
            continue
        gain = float(sl.get("days_per_step") or 0)
        # 斜率符号已经说明"加大一档"是提前还是推后；有利的方向就是让交期变早的那边
        helps_when_raised = gain < 0
        state, state_why = relief_state(name, gain)
        relief.append({
            "input": name, "label": spec["label"],
            "state": state, "state_why": state_why,
            "citable_as_action": state == "measured",
            "days_gained_per_step": round(abs(gain), 3),
            "days_gained_at_steepest_step": round(abs(float(sl.get("steepest_days_per_step") or 0)), 3),
            "step": {"value": spec["step"], "unit": spec["default_unit"]},
            # 只有方向可信、效果测得出的项才给动作；否则宁可不写动作，
            # 免得下游把"把设备可用率降低 10%"这种 0 效果项念成建议
            "do_this": (None if state != "measured" else
                        (f"把{spec['label']}提高 {spec['step']:g} {spec['default_unit']}"
                         if helps_when_raised else
                         f"把{spec['label']}降低 {spec['step']:g} {spec['default_unit']}")),
            "step_like": bool(sl.get("nonlinear")),
            "relieves": list(RELIEF_TERMS.get(name, ())),
            "currently_binding_for": [x["model"] for x in constraints
                                      if any(c["code"] in RELIEF_TERMS.get(name, ())
                                              for c in x["constrained_by"])],
            "basis": "逐档真跑的局部斜率（同一套推演路径），不是先入为主的权重",
        })
    relief.sort(key=lambda r: (0 if r["state"] == "measured" else
                               (1 if r["state"] == "no_effect_measured" else 2),
                               -float(r["days_gained_per_step"] or 0)))

    # ③ 不确定归因：现在这个日期只能信到几成，各输入分摊几天
    unc = ss.propagate_uncertainty(rep["sensitivity"], rep["accuracy"])
    spread = [{"model": r.get("model_code"), "input": ACCURACY_LABELS.get(
                   str(x.get("input")), str(x.get("input"))),
               "error_band": x.get("error_band"),
               "uncertainty_days": x.get("uncertainty_days_now"),
               "days_per_step": x.get("days_per_step")}
               for r in (unc.get("per_model") or []) for x in r.get("items") or []]
    answers: Dict[str, Any] = {
        "answer": {"portfolio_completion_date": m.get("finish_date"),
                   "worst_days_late": m.get("days_late_worst"),
                   "constrained_by": _public_terms(m.get("binding_terms"))},
        "constraint_attribution": {
            "per_order": constraints,
            "explained_orders": len(constraints), "orders_total": len(orders),
            "meaning": "每台单当前被哪一项卡住：等料、排队、做不完，还是日历",
        },
        "relief_attribution": relief,
        "uncertainty_attribution": {
            "per_input": spread,
            "insensitive_inputs": [{"model": r.get("model_code"),
                                    "input": ACCURACY_LABELS.get(str(x.get("input")),
                                                                  str(x.get("input"))),
                                    "because": x.get("because")}
                                   for r in (unc.get("per_model") or [])
                                   for x in r.get("insensitive_inputs") or []],
            "method": unc.get("method"), "value_of_repair": unc.get("value_of_repair"),
        },
    }

    # ④ 变更归因：给了 compare 才算。逐项单独动测 d_i，总差值减掉Σ单项就是交互项，
    #    把交互硬塞进单项比例是这轮最容易撒的谎（料到了但线在排队，两项互相挡着）。
    comp = request.get("compare") if isinstance(request, dict) else None
    if isinstance(comp, dict) and (comp.get("baseline") or comp.get("alternative")):
        base_req = _parse({**request, "inputs": comp.get("baseline") or {},
                           "scope": comp.get("baseline_scope") or (request.get("scope") or {})})
        alt_req = _parse({**request, "inputs": comp.get("alternative") or {}})
        bm = await _measure(db, factory_id, base_req, models=models)
        am = await _measure(db, factory_id, alt_req, models=models)
        total = ss._days_between(am.get("finish_date"), bm.get("finish_date"))
        singles: List[Dict[str, Any]] = []
        for name in sorted(set(alt_req["inputs"])):
            one = await _measure(db, factory_id, base_req,
                                 override={name: alt_req["inputs"][name]}, models=models)
            d = ss._days_between(one.get("finish_date"), bm.get("finish_date"))
            singles.append({"input": name, "label": INPUTS[name]["label"],
                            "days": d,
                            "changed_from_baseline_to": alt_req["inputs"][name]["value"],
                            "unit": alt_req["inputs"][name]["unit"]})
        if set(base_req["inputs"]) - set(alt_req["inputs"]):
            singles.append({"input": "(baseline_only_inputs)",
                            "label": "只在基准里出现的输入",
                            "days": None, "note": "对照组把它们退回默认，单项效果要换基准再算一次",
                            "changed_from_baseline_to": None})
        ssum = round(sum(float(x["days"] or 0) for x in singles), 2)
        residual = None if total is None else round(total - ssum, 2)
        answers["change_attribution"] = {
            "baseline_completion_date": bm.get("finish_date"),
            "alternative_completion_date": am.get("finish_date"),
            "total_days": total, "per_input": singles, "sum_of_singles": ssum,
            "interaction_residual_days": residual,
            "meaning": ("各项单独动的效果不可加：残差不是 0 就说明这几项互相挡着。"
                        "引用时给总差值、各项单项效果、残差三个数，不要合成一个百分比"),
        }
        if residual is not None and abs(residual) >= 1:
            unavailable.append(_unavailable(
                "additive_split", "总差值不等于各项之和，不能按单项比例分摊",
                f"交互残差 {residual:g} 天",
                "报三个数（总值/单项/残差），或一次只改一项再逐项引用"))
    else:
        unavailable.append(_unavailable(
            "change_attribution", "请求没给 compare，算不出「为什么变了」",
            "compare.baseline 与 compare.alternative 两组业务输入",
            "问变化就传两组输入；问当前答案的成因看 constraint_attribution"))

    metrics = [
        _metric("约束归因覆盖率", round(len(constraints) / max(1, len(orders)), 3), "比例",
                f"{len(constraints)}/{len(orders)} 台给出了卡住它的那一项"),
        _metric("可归因输入数", len(relief), "个",
                f"{len(INPUTS)} 个业务输入里有实测斜率的才能进归因，其余进 unavailable"),
        _metric("不确定分摊合计", round(sum(float(x.get("uncertainty_days") or 0)
                                            for x in spread), 2), "天",
                str(unc.get("method"))),
    ]
    caveats = ["归因用的是实测反事实（真跑了推演），不是权重打分",
               "relief_attribution 只有 state=measured 的项能当改善建议引用；"
               "no_effect_measured 说明它不是当前约束，suspicious_direction 说明读数不可信",
               "沙箱读数：不写业务表、不回写外部系统"]
    return _envelope("attribution", parsed, answers=answers, metrics=metrics,
                     unavailable=unavailable, caveats=caveats, started=started)


def spec() -> Dict[str, Any]:
    """契约自述：agent 从这一个接口就能学全它能说什么，不需要读代码。"""
    return {
        "contract_version": CONTRACT_VERSION,
        "purpose": "统一虚拟工厂引擎的对外接口：接口稳定、实现隐藏",
        "design_constraint": ("输入输出只用业务概念。模型内部的参数名、节点/边/工位/线组标识不出现在"
                              "这一层，引擎内部怎么改都不动接口"),
        "interfaces": [
            {"name": "simulate", "question": QUESTIONS["simulate"],
             "request": {"factory_id": "必填（厂区代码）",
                         "models": "机种编码列表；不填则引擎自选 BOM 最完整的 n_models 台",
                         "n_models": "1-8，默认 5",
                         "as_of": "YYYY-MM-DD，默认今天",
                         "scope": {"order_size_days_of_output": {"value": "数值", "unit": "days"},
                                    "promise_margin": {"value": "数值",
                                                       "unit": "multiple_of_bottleneck_lead"}},
                         "conditions": {"weather": "fair | rain | storm"},
                         "inputs": {"见 inputs 词表": {"value": "数值", "unit": "词表内单位"}}},
             "response": ["scope", "inputs_echo", "answers", "metrics[]", "unavailable[]",
                          "caveats[]", "provenance"]},
            {"name": "sensitivity", "question": QUESTIONS["sensitivity"],
             "request": "与 simulate 相同（厂、机种、批量、天气、承诺口径），inputs 可以不填",
             "response": ["answers.inputs[]（每个业务输入的实测斜率）", "answers.ranking[]",
                          "answers.answer_confidence", "answers.data_confidence",
                          "metrics[]", "unavailable[]"]},
            {"name": "attribution", "question": QUESTIONS["attribution"],
             "request": {"与 simulate 相同": "", "compare": {
                 "baseline": "inputs 一组", "alternative": "inputs 另一组"}},
             "response": ["answers.constraint_attribution（哪一项卡住每台单）",
                          "answers.relief_attribution（松掉哪一项值几天）",
                          "answers.uncertainty_attribution（现在的数可信到几成）",
                          "answers.change_attribution（给了 compare 才有的变更归因）"]},
        ],
        "inputs": [{"name": k, "label": v["label"], "kind": v["kind"], "units": v["units"],
                    "default_unit": v["default_unit"], "range": list(v["range"]),
                    "step": v["step"], "moves": v["moves"], "basis": v["basis"],
                    "expected_direction": v.get("physics"), "relieves": list(RELIEF_TERMS.get(k, ())),
                    "changes_demand": bool(v.get("changes_demand"))}
                   for k, v in INPUTS.items()],
        "conditions": {"weather": {k: f"到岗 {v:g}" for k, v in WEATHER.items()}},
        "constrained_by": [{"code": pub, "label": label} for pub, label in TERM_LABEL.values()],
        "errors": {"invalid_request": ("未知参数名 / 未知单位 / 超范围 / 坏日期 → 结构化拒绝，"
                                       "回 field、message、allowed，不静默忽略、不 500")},
        "invariants": [
            "每个数带 unit 与 basis；算不出来进 unavailable 并点名缺什么，不返回 0 冒充算过",
            "请求是封闭词表：词表外的参数名结构化拒绝并回 allowed",
            "响应里不出现内部标识（INTERNAL_ONLY_KEYS），泄漏数必须为 0",
            "所有读数都是沙箱推演：sandbox_only=true、external_write=false，永不回写外部系统",
            "交期与成本同时给好天与暴雨两档，只报好看的那个不算交付",
            "钱只有成本侧：收益侧（罚则/违约成本）没建模，差值只能排序，不能作投资决策",
            "斜率与业务常识方向相反时标 suspicious_direction，不冒充改善建议",
        ],
    }


def leak_paths(payload: Any, _path: str = "$") -> List[Dict[str, str]]:
    """找出响应里把内部名当接口名用的键。值里出现主数据编码不算泄漏。"""
    found: List[Dict[str, str]] = []
    if isinstance(payload, dict):
        for k, v in payload.items():
            if str(k) in INTERNAL_ONLY_KEYS:
                found.append({"path": _path, "key": str(k)})
            found += leak_paths(v, f"{_path}.{k}")
    elif isinstance(payload, list):
        for i, v in enumerate(payload):
            found += leak_paths(v, f"{_path}[{i}]")
    return found


def envelope_violations(payload: Any, _path: str = "$") -> List[str]:
    """信封纪律：数必须带单位与依据，算不出必须点名缺什么。"""
    bad: List[str] = []
    if isinstance(payload, dict):
        if "name" in payload and "value" in payload and "unit" in payload:
            if not payload.get("unit"):
                bad.append(f"{_path}: 指标 «{payload.get('name')}» 没有单位")
            if not payload.get("basis"):
                bad.append(f"{_path}: 指标 «{payload.get('name')}» 没有依据")
        if payload.get("state") == "not_computable" and not payload.get("missing"):
            bad.append(f"{_path}: «{payload.get('name')}» 说算不出却没点名缺什么")
        for k, v in payload.items():
            bad += envelope_violations(v, f"{_path}.{k}")
    elif isinstance(payload, list):
        for i, v in enumerate(payload):
            bad += envelope_violations(v, f"{_path}[{i}]")
    return bad


async def self_check(db: AsyncSession, factory_id: str,
                     models: Optional[List[str]] = None) -> Dict[str, Any]:
    """契约自检：三个数，任何一条破了就说明接口已经和实现黏住了。"""
    req = {"n_models": 2, "conditions": {"weather": "storm"}}
    if models:
        req["models"] = models
    leaks: List[Dict[str, str]] = []
    violations: List[str] = []
    payloads: Dict[str, Any] = {}
    for iface, fn in (("simulate", simulate), ("sensitivity", sensitivity),
                      ("attribution", attribution)):
        payload = await fn(db, factory_id, dict(req))
        payloads[iface] = {"metrics": len(payload.get("metrics") or []),
                           "unavailable": len(payload.get("unavailable") or []),
                           "bytes": len(str(payload))}
        leaks += leak_paths(payload)
        violations += envelope_violations(payload)
    rejected, tried = 0, []
    for bad in ("hours_multiplier", "lead_multiplier", "allow_partial", "days_of_output",
                "parallel_lines"):
        tried.append(bad)
        try:
            await simulate(db, factory_id, {"n_models": 2, "inputs": {bad: 1.0}})
        except ContractError:
            rejected += 1
        except Exception:
            pass
    return {"interfaces": ["simulate", "sensitivity", "attribution"],
            "public_inputs": len(INPUTS),
            "internal_token_leaks": len(leaks), "leaked": leaks[:6],
            "envelope_violations": len(violations), "violations": violations[:6],
            "internal_names_rejected": rejected, "internal_names_tried": tried,
            "payload_sizes": payloads}
