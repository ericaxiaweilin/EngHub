"""库存流水类型词表（读取侧唯一口径）。

写入方历史上用了不同词汇：WMS 服务写 inbound/outbound/count_diff/transfer，
虚拟工厂脉搏写 production_out 与 scenario_hold。读取侧若只按 'outbound' 过滤，
会静默得到 0 消耗，周转率就变成假数 —— 消耗/收货统计必须走这里的集合。
"""

OUTBOUND_TYPES = ("outbound", "production_out")
INBOUND_TYPES = ("inbound",)
NON_CONSUMING_TYPES = ("transfer", "scenario_hold", "count_diff")

ALL_TYPES = OUTBOUND_TYPES + INBOUND_TYPES + NON_CONSUMING_TYPES
