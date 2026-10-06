"""成本模型：把"闲着"换成钱，再按目标排序（人力优先 / 交期优先 / 总成本优先）。

设计前提（用户 10-06 的口径）：
- **一种是硬成本，一种是机会成本**。人力是硬成本 —— 人今天在岗，没活也付钱；
  设备全款的话停着只是折旧（账上有、现金没出去），贷款/租赁才变成硬成本；
  物料资金占用是机会成本；交付延期是损失，但它的"价格"取决于合同，不一定是罚钱。
- **单价没有不代表不能建模**：先用一组默认标定跑起来，每一项都标 `basis=default_calibration`，
  用户给一个数就覆盖一个（`cost_parameters` 表），并把覆盖来源一起报出去。
  这跟"编数据"的区别在于：钱数是从明示参数乘出来的，参数本身看得见、可改、可回溯。
- **目标不同答案就不同**：同一个缺料 3 天，"人力节约"会把人调去别的工艺，
  "交期优先"可能宁可养着闲置也要保住那条线的节拍。所以目标是一个参数，不是我们的偏好。

优先级排序也照他给的次序默认：人力 > 设备 > 物料 > …（`OBJECTIVES` 里的权重就是这句话的数字化）。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from sqlalchemy import text

CURRENCY = os.getenv("COST_MODEL_CURRENCY", "USD")

# 默认标定：每一项都写明单位和"这是标定不是实测"，被 cost_parameters 覆盖时 basis 换成 override。
DEFAULT_RATES: Dict[str, Dict[str, Any]] = {
    "labor_person_day": {"amount": 30.0, "unit": f"{CURRENCY}/人·天", "hard": True,
                         "note": "在岗即付：没活也出去的钱"},
    "equipment_line_day": {"amount": 40.0, "unit": f"{CURRENCY}/线·天", "hard": False,
                           "note": "全款设备停着只是折旧（账上成本，不是现金支出）；"
                                   "若该线有贷款/租赁，把 hard 覆盖成 true"},
    "material_capital_annual_pct": {"amount": 0.08, "unit": "%/年", "hard": False,
                                     "note": "库存占压资金的机会成本"},
    "delay_penalty_daily_pct": {"amount": 0.005, "unit": "%货值·天", "hard": False,
                                "note": "延期每天按货值的比例计损失，封顶见 delay_cap_pct"},
    "delay_cap_pct": {"amount": 0.10, "unit": "%货值", "hard": False,
                      "note": "延期损失封顶，避免算出比货值还大的数"},
    "energy_running_line_day": {"amount": 12.0, "unit": f"{CURRENCY}/线·天", "hard": True,
                               "note": "只有开机才花的变动成本：停线时它是**省下的钱**"},
}

# 目标模式：同一份闲置，在不同目标下得出的动作不一样。权重按"人力 > 设备 > 物料 > 交付"这个
# 常见次序做默认（balanced），另给两种典型取向。
OBJECTIVES: Dict[str, Dict[str, float]] = {
    "labor_first": {"labor": 1.0, "equipment": 0.1, "material": 0.2, "delivery": 0.4,
                    "label": "人力节约优先：宁可换线也不让人空转"},
    "delivery_first": {"labor": 0.5, "equipment": 0.1, "material": 0.2, "delivery": 1.0,
                       "label": "交期优先：保住关键单的节拍，闲置可以忍"},
    "total_cost": {"labor": 0.6, "equipment": 0.4, "material": 0.4, "delivery": 0.3,
                   "label": "总成本最低：四类成本一起比"},
    "balanced": {"labor": 0.5, "equipment": 0.3, "material": 0.3, "delivery": 0.5,
                 "label": "默认标定权重"},
}
DEFAULT_OBJECTIVE = os.getenv("COST_MODEL_OBJECTIVE", "labor_first")

RATE_OVERRIDES_SQL = text("""
    SELECT item_code, amount, is_hard, source, note
    FROM cost_parameters
    WHERE (factory_id = :fid OR factory_id IS NULL)
    ORDER BY factory_id NULLS LAST
""")


def resolve_rates(db_rows: List[Any], objective: str | None = None) -> Dict[str, Any]:
    """默认标定 ← 表里的覆盖，逐项带上 basis，钱数怎么来的必须能查。"""
    rates: Dict[str, Dict[str, Any]] = {
        code: dict(spec, basis="default_calibration") for code, spec in DEFAULT_RATES.items()
    }
    overridden: List[str] = []
    for r in db_rows:
        code = str(r["item_code"])
        if code not in rates:
            continue
        rates[code] = {
            "amount": float(r["amount"]), "unit": rates[code]["unit"],
            "hard": bool(r["is_hard"]) if r["is_hard"] is not None else rates[code]["hard"],
            "note": str(r["note"] or rates[code]["note"]),
            "basis": "override",
            "source": str(r["source"] or "(未写来源)"),
        }
        overridden.append(code)
    key = objective if objective in OBJECTIVES else DEFAULT_OBJECTIVE
    return {"currency": CURRENCY, "rates": rates,
            "objective": key, "objective_label": OBJECTIVES[key]["label"],
            "weights": OBJECTIVES[key], "overridden_items": overridden}


def cost_lines(lines: List[Dict[str, Any]], rates: Dict[str, Any]) -> List[Dict[str, Any]]:
    """把每个工位的闲置/运转换成钱，并按目标权重给一个可比的分数。

    - 闲置人力：估算闲置人时 ÷ 8 → 人·天 × 单价，这是**硬支出**，是"要不要调线"的主项；
    - 设备闲置：拆两笔 —— 折旧（账上有、现金没出去）和硬支出（只有把该项覆盖成 hard 才算）；
      这样"全款设备停着不算亏"这句话就能被机器执行，而不是靠人解释；
    - 能耗/辅料：只有开机才花，所以停线省下的部分参与比较（否则永远得出"多开就是好"）；
    - `objective_score`：目标权重下的排序依据。权重来自 OBJECTIVES，换目标就换排序。
    """
    r = rates["rates"]
    w = rates["weights"]
    out: List[Dict[str, Any]] = []
    for line in lines:
        idle_ph = float(line.get("idle_person_hours_estimated") or 0)
        idle_person_days = round(idle_ph / 8.0, 2)
        runnable_hours = float(line.get("runnable_hours") or 0)
        idle_line_hours = float(line.get("idle_hours") or 0)
        labor_cost = round(idle_person_days * float(r["labor_person_day"]["amount"]), 2)
        idle_line_days = round(idle_line_hours / 24.0, 3)
        running_line_days = round(runnable_hours / 24.0, 3)
        equip_total = round(idle_line_days * float(r["equipment_line_day"]["amount"]), 2)
        equip_hard = equip_total if r["equipment_line_day"]["hard"] else 0.0
        energy_rate = float(r["energy_running_line_day"]["amount"])
        energy_spent = round(running_line_days * energy_rate, 2)
        energy_saved = round(idle_line_days * energy_rate, 2)
        hard_cost_total = round(labor_cost + equip_hard + energy_spent, 2)
        equipment_opportunity = round(equip_total - equip_hard, 2)
        score = round(w["labor"] * labor_cost
                      + w["equipment"] * (equip_hard + equipment_opportunity)
                      + w["delivery"] * 0.0
                      - 0.2 * energy_saved, 2)
        out.append({
            "station_code": line.get("station_code"),
            "station_name": line.get("station_name"),
            "idle_person_days": idle_person_days,
            "labor_idle_cost": labor_cost,
            "equipment_idle_depreciation": equipment_opportunity,
            "equipment_idle_hard": equip_hard,
            "energy_cost_when_running": energy_spent,
            "energy_avoided_by_idle": energy_saved,
            "hard_cost_total": hard_cost_total,
            "objective_score": score,
        })
    return out


def reallocation_options(costed: List[Dict[str, Any]], lines: List[Dict[str, Any]],
                         rates: Dict[str, Any], *, min_idle_ratio: float = 0.3,
                         top: int = 5) -> List[Dict[str, Any]]:
    """缺料的那条线的人力，能不能挪去有活可干的线：给比较结果，不替人拍板。

    收益 = 挪走的人力闲置成本；代价 = 换线时间（station_capacity.setup_time_minutes，有实测）
    + 目标权重下的机会损失。技能是否允许这么挪，库里现在没有依据
    （position_capabilities 0 行、station_capacity.required_skills 0/38），
    所以每条建议都带 `skill_check="需要技能矩阵确认"` —— 不说谎比给个漂亮答案重要。
    """
    by_station = {l["station_code"]: l for l in lines}
    donors = [c for c in costed
              if float(by_station.get(c["station_code"], {}).get("idle_ratio") or 0) >= min_idle_ratio
              and float(by_station.get(c["station_code"], {}).get("headcount_hr") or 0) > 0]
    receivers = [l for l in lines if int(l.get("fillable_kitted_orders") or 0) > 0]
    if not donors or not receivers:
        return []
    labor_rate = float(rates["rates"]["labor_person_day"]["amount"])
    options: List[Dict[str, Any]] = []
    for rec in receivers:
        need_hours = float(rec.get("fillable_need_hours") or 0)
        if need_hours <= 0:
            continue
        for don in sorted(donors, key=lambda c: -c["labor_idle_cost"]):
            donor_line = by_station.get(don["station_code"], {})
            people = int(donor_line.get("headcount_hr") or 0)
            move_people = max(1, min(people, int(round(need_hours / 8.0)) or 1))
            saving_day = round(move_people * labor_rate, 2)
            setup_hours = float(rec.get("setup_time_minutes") or 0) / 60.0
            setup_cost = round(setup_hours / 8.0 * move_people * labor_rate, 2)
            options.append({
                "from_station": don["station_name"],
                "from_station_code": don["station_code"],
                "to_station": rec["station_name"],
                "to_station_code": rec["station_code"],
                "people_to_move": move_people,
                "work_orders_waiting": int(rec.get("fillable_kitted_orders") or 0),
                "need_hours": round(need_hours, 1),
                "labor_idle_saved_per_day": saving_day,
                "changeover_cost": setup_cost,
                "net_benefit_per_day": round(saving_day - setup_cost, 2),
                "skill_check": "需要技能矩阵确认（position_capabilities 为空）",
                "objective": rates["objective"],
            })
    options.sort(key=lambda o: -o["net_benefit_per_day"] * rates["weights"]["labor"])
    return options[:top]
