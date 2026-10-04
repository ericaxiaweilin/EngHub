"""库存补货与水位的单一口径。

优先级：物料级配置表 safety_stock_config（有启用行时）→ 库存行级字段
（reorder_point / safety_stock / reorder_qty）。

历史上这里有两处各自编数：补货建议用 `reorder_point * 2` 当最大库存，
过量告警用 `reorder_point + reorder_qty`，同一个"该补到多少"给出两个答案。
两边都改调用本模块，系数编造一并去掉。
"""

from typing import Any, Dict, Optional, Tuple

# 与流水词表同源：只有真实消耗（领料/销售/报废等）才算日耗，
# 调拨与冻结不算 —— 否则内部搬移会把需求量虚高。
from api.services.wms_architecture.movements import CONSUMPTION_TYPES

__all__ = ["CONSUMPTION_TYPES", "resolve_target", "policy_provenance"]


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def resolve_target(
    *,
    reorder_point: Optional[float] = None,
    safety_stock: Optional[float] = None,
    reorder_qty: Optional[float] = None,
    max_level: Optional[float] = None,
) -> Tuple[float, str]:
    """返回（应补到的目标量, 口径来源）。

    max_level 只在其配置表真有值时使用；没有值时明确标注用的是
    "再订货点 + 一次补货量"，不再乘 2 编一个上限。
    """
    max_level = _num(max_level)
    if max_level > 0:
        return max_level, "safety_stock_config.max_level"

    point = _num(reorder_point) or _num(safety_stock)
    target = point + _num(reorder_qty)
    if target <= 0:
        return 0.0, "无水位配置（不可判定）"
    source = "inventory 行级：reorder_point + reorder_qty"
    if not _num(reorder_point):
        source = "inventory 行级：safety_stock + reorder_qty"
    return target, source


def policy_provenance(config_rows: int, row_level_rows: int) -> Dict[str, Any]:
    """把本轮到底用了哪套策略说清楚，避免"0 建议"被读成"不需要补货"。"""
    if config_rows:
        source, note = "safety_stock_config", f"启用配置 {config_rows} 行"
    else:
        source, note = "inventory 行级字段", (
            f"safety_stock_config 为 0 行，改用库存行上的 "
            f"reorder_point/safety_stock/reorder_qty（{row_level_rows} 行）"
        )
    return {"policy_source": source, "policy_note": note}
