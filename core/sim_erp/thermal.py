"""热应力估算：WBGT（ISO 7243 型）与职业接触限值（JSOH 2025-2026 按 RMR）。

系数、适用区间和来源全部写在规则包里（core/sim_erp/data/packs/iso7243_jsoh_heat.json），
这里只放公式本身 —— 换标准版次改包，不改代码。
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional

# Stull (2011) 经验式的系数（J. Appl. Meteor. Climatol.；适用 T −20~50℃、RH 5~99%）
STULL = {"a": 0.151977, "b": 8.313659, "c": 1.676331, "d": 0.00391838, "e": 0.023101, "f": 4.686035}


def wet_bulb_c(temperature_c: float, humidity_percent: float, *,
               coefficients: Optional[Dict[str, float]] = None) -> float:
    """由干球温度与相对湿度估算自然湿球温度（Stull 2011）。"""
    k = coefficients or STULL
    rh = max(1.0, min(100.0, float(humidity_percent)))
    t = float(temperature_c)
    return (t * math.atan(k["a"] * math.sqrt(rh + k["b"]))
            + math.atan(t + rh)
            - math.atan(rh - k["c"])
            + k["d"] * rh ** 1.5 * math.atan(k["e"] * rh)
            - k["f"])


def wbgt_c(*, temperature_c: float, humidity_percent: float,
           globe_temperature_c: Optional[float] = None,
           weights: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """室内（无太阳辐射）WBGT = 0.7·Tnwb + 0.3·Tg；没有黑球实测时按标准做法取 Tg≈Td。

    返回值把用了哪个假设写在 `assumptions` 里，读数的人能看出这是估算不是实测。
    """
    w = weights or {"wet_bulb": 0.7, "dry_bulb": 0.3}
    tw = wet_bulb_c(temperature_c, humidity_percent)
    assumptions = []
    if globe_temperature_c is None:
        globe = temperature_c
        assumptions.append("无黑球实测 → Tg≈Td（室内无太阳辐射时的标准简化）")
    else:
        globe = float(globe_temperature_c)
    # 无太阳辐射的形式是 0.7·Tnwb + 0.3·Tg；有太阳辐射时是 0.7/0.2/0.1，权重来自规则包
    value = w.get("wet_bulb", 0.7) * tw + w.get("globe", 0.0) * globe \
        + w.get("dry_bulb", 0.3) * temperature_c
    return {"wbgt_c": round(value, 2), "wet_bulb_c": round(tw, 2), "globe_used_c": round(globe, 2),
            "dry_bulb_c": round(temperature_c, 2), "assumptions": assumptions}


def resolve_metabolic_level(task_type: str, pack: Dict[str, Any],
                    explicit: Optional[str] = None) -> Dict[str, Any]:
    """作业类型 → 代谢强度档（包里给映射，IE 可改；不猜别的名义）。"""
    levels = pack.get("metabolic_levels") or {}
    key = explicit if explicit in levels else (pack.get("task_metabolic_map") or {}).get(
        str(task_type or "").strip().lower())
    if key not in levels:
        key = pack.get("default_metabolic_level") or "moderate"
    row = levels.get(key) or {}
    return {"level": key, "rmr": row.get("rmr"), "kcal_per_hour": row.get("kcal_per_hour"),
            "wbgt_limit_c": row.get("wbgt_limit_c")}


def assess(*, temperature_c: float, humidity_percent: float, task_type: str,
           pack: Dict[str, Any], globe_temperature_c: Optional[float] = None,
           metabolic_level: Optional[str] = None) -> Dict[str, Any]:
    """把环境 + 作业强度折成 WBGT、限值、超限幅度、所需工休与应变系数。"""
    if not pack:
        return {"available": False, "why": "没有热应力规则包（iso7243_jsoh_heat）→ 不折算，也不冒充算过"}
    env = wbgt_c(temperature_c=temperature_c, humidity_percent=humidity_percent,
                 globe_temperature_c=globe_temperature_c,
                 weights=(pack.get("wbgt") or {}).get("indoor_weights"))
    meta = resolve_metabolic_level(task_type, pack, metabolic_level)
    limit = meta.get("wbgt_limit_c")
    strain = pack.get("strain") or {}
    rest = pack.get("work_rest") or {}
    exceedance = round(env["wbgt_c"] - float(limit), 2) if limit is not None else None
    over = max(0.0, exceedance) if exceedance is not None else 0.0
    gain = float(strain.get("fatigue_gain_per_exceedance_c", 0.0))
    rest_fraction = min(float(rest.get("max_rest_fraction", 0.75)),
                        float(rest.get("rest_fraction_per_exceedance_c", 0.0)) * over)
    cf = pack.get("comfort") or {}
    kcal = float(meta.get("kcal_per_hour") or 0.0)
    center = float(cf.get("optimal_c", 21.0)) + float(
        cf.get("optimal_shift_per_100kcal_above_130", 0.0)) * max(0.0, (kcal - 130.0) / 100.0)
    band = float(cf.get("band_c", 2.0))
    upper, lower = center + band, center - band
    pre = float(cf.get("wbgt_pre_limit_c", 0.0))
    wbgt_now = float(env["wbgt_c"])
    limit_for_curve = float(meta["wbgt_limit_c"]) - pre if meta.get("wbgt_limit_c") is not None else None
    dry_hot = max(0.0, float(temperature_c) - upper)
    wbgt_hot = (max(0.0, wbgt_now - limit_for_curve) if limit_for_curve is not None else 0.0)
    # 干热与闷热相加：取大值会让湿度在热天永远被干球遮蔽（实测就是这样）
    hot_deg = min(float(cf.get("hot_deg_cap_c", 20.0)), dry_hot + wbgt_hot)
    # 冷侧不是舒适带下沿，是一条地板线：越南 10℃ 以上偏冷不惩罚（温带假设会误伤真实工况）
    cold_floor = float(cf.get("cold_floor_c", 10.0))
    cold_deg = max(0.0, cold_floor - float(temperature_c))
    energy_cost_multiplier = round(1.0 + float(cf.get("cost_per_deg_hot", 0.0)) * hot_deg
                                   + float(cf.get("cost_per_deg_cold", 0.0)) * cold_deg, 4)
    work_efficiency = round(max(0.5, 1.0
                                - float(cf.get("efficiency_loss_per_deg_hot", 0.0)) * hot_deg
                                - float(cf.get("efficiency_loss_per_deg_cold", 0.0)) * cold_deg), 4)
    comfort_fatigue_gain = round(float(cf.get("cold_fatigue_gain_per_deg", 0.0)) * cold_deg
                                 + float(cf.get("fatigue_gain_per_deg_hot", 0.0)) * hot_deg, 4)
    return {
        "available": True,
        "comfort_center_c": round(center, 2),
        "comfort_band_c": [round(lower, 2), round(upper, 2)],
        "cold_floor_c": round(cold_floor, 2),
        "hot_deg_outside_band": round(hot_deg, 2),
        "hot_deg_from_dry_bulb": round(dry_hot, 2),
        "hot_deg_from_wbgt": round(wbgt_hot, 2),
        "cold_deg_outside_band": round(cold_deg, 2),
        "energy_cost_multiplier": energy_cost_multiplier,
        "work_efficiency": work_efficiency,
        "comfort_fatigue_gain": comfort_fatigue_gain,
        "cold_fatigue_gain": comfort_fatigue_gain,
        "comfort_basis": cf.get("basis"),
        "pack_version": pack.get("version"),
        "wet_bulb_c": env["wet_bulb_c"],
        "globe_used_c": env["globe_used_c"],
        "dry_bulb_c": env["dry_bulb_c"],
        "wbgt_c": env["wbgt_c"],
        "assumptions": env["assumptions"],
        "metabolic_level": meta["level"],
        "metabolic_rmr": meta["rmr"],
        "metabolic_kcal_per_hour": meta["kcal_per_hour"],
        "tlv_wbgt_c": limit,
        "exceedance_c": exceedance,
        "strain_multiplier": round(1.0 + gain * over, 4),
        "rest_metabolic_kcal_per_hour": (pack.get("energy") or {}).get("rest_metabolic_kcal_per_hour"),
        "energy_formula": (pack.get("energy") or {}).get("formula"),
        "energy_basis": (pack.get("energy") or {}).get("basis"),
        "required_rest_fraction": round(rest_fraction, 4),
        "max_allowable_work_minutes_per_hour": round(60 * (1 - rest_fraction), 1),
        "blocking": bool(strain.get("treat_exceedance_as_binding", True))
                    and over >= float(strain.get("blocking_above_exceedance_c", 999)),
        "warning": over > 0,
        "basis": {"wet_bulb": (pack.get("sources") or {}).get("wet_bulb"),
                  "wbgt": (pack.get("sources") or {}).get("wbgt_indoor"),
                  "limit": (pack.get("sources") or {}).get("tlv"),
                  "rest_conversion": (rest or {}).get("basis"),
                  "strain_gain": (strain or {}).get("basis")},
    }
