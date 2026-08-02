"""
多工厂仿真场景库
================

提供多个**完整样本工厂**，覆盖不同行业形态与负荷分化特征，用于车间级 / 工段级
有限产能负荷仿真。每个工厂都包含完整的：车间(Workshop) → 工段(Section) →
产品工艺路线(Routing) → 订单(Order) 数据，且工段/车间参数全部可控。

场景库：
1. EngHub 精密机械厂   —— 机械混流，焊接瓶颈（减速机 / 泵组 / 定制工装）
2. 华东汽车车身件厂     —— 冲压→焊装→涂装→总装 四大工艺，涂装瓶颈，大批量
3. 深圳电子 SMT 厂      —— SMT→DIP→组装→测试→包装，多品种小批量，SMT 瓶颈
4. 杭州食品饮料厂       —— 配料→调配→杀菌→灌装→包装，批次生产，杀菌瓶颈
"""

from __future__ import annotations

from typing import Callable, Dict, List

from .models import (
    FactorySimConfig,
    OrderInput,
    Priority,
    ProductionStrategy,
    RoutingDef,
    RoutingOperation,
    SectionConfig,
    WorkshopConfig,
)


# ====================================================================
# 工厂 1：EngHub 精密机械厂（机械混流）
# ====================================================================

def _build_precision_plant() -> FactorySimConfig:
    workshops = [
        WorkshopConfig(
            workshop_id="WS-MACH", name="机加车间", working_days_per_week=6,
            description="下料 / 机加 / 焊接 —— 零件加工为主，备料平准",
        ),
        WorkshopConfig(
            workshop_id="WS-ASSY", name="总装车间", working_days_per_week=6,
            description="涂装 / 组立 / 包装 —— 订单进、订单出",
        ),
    ]
    sections = [
        SectionConfig(
            section_id="SEC-CUT", name="下料/备料", workshop_id="WS-MACH",
            strategy=ProductionStrategy.MTS, workers=4, machines=3,
            shifts_per_day=1, hours_per_shift=8.0, efficiency=0.85, max_overtime_pct=0.2,
            yield_rate=0.99, role_name="下料工",
            description="板材切割下料，面向库存备料，负荷平准",
        ),
        SectionConfig(
            section_id="SEC-MACH", name="机加工段", workshop_id="WS-MACH",
            strategy=ProductionStrategy.MTS, workers=12, machines=12,
            shifts_per_day=2, hours_per_shift=8.0, efficiency=0.85, max_overtime_pct=0.2,
            yield_rate=0.98, role_name="机加操作工",
            description="CNC 机加，零件备料生产，双班运行",
        ),
        SectionConfig(
            section_id="SEC-WELD", name="焊接工段", workshop_id="WS-MACH",
            strategy=ProductionStrategy.MTO, workers=6, machines=6,
            shifts_per_day=1, hours_per_shift=8.0, efficiency=0.85, max_overtime_pct=0.2,
            yield_rate=0.96, role_name="焊工",
            description="结构件焊接，订单驱动，当前产能紧张（瓶颈）",
        ),
        SectionConfig(
            section_id="SEC-PAINT", name="涂装工段", workshop_id="WS-ASSY",
            strategy=ProductionStrategy.MTO, workers=5, machines=0,
            shifts_per_day=1, hours_per_shift=8.0, efficiency=0.80, max_overtime_pct=0.2,
            yield_rate=0.94, role_name="涂装工",
            description="表面处理与涂装",
        ),
        SectionConfig(
            section_id="SEC-ASSY", name="组立工段", workshop_id="WS-ASSY",
            strategy=ProductionStrategy.MTO, workers=15, machines=0,
            shifts_per_day=2, hours_per_shift=8.0, efficiency=0.85, max_overtime_pct=0.3,
            yield_rate=0.98, role_name="装配工",
            description="最终装配线 —— 订单进、订单出，按交期拉动",
        ),
        SectionConfig(
            section_id="SEC-PACK", name="包装发运", workshop_id="WS-ASSY",
            strategy=ProductionStrategy.MTO, workers=3, machines=0,
            shifts_per_day=1, hours_per_shift=8.0, efficiency=0.85, max_overtime_pct=0.2,
            yield_rate=0.995, role_name="包装工",
            description="成品包装与发运",
        ),
    ]
    routings = [
        RoutingDef(
            routing_id="RT-R", product_id="PRD-R", product_name="减速机 R 系列",
            operations=[
                RoutingOperation(op_no=10, name="下料", section_id="SEC-CUT", setup_minutes=20, cycle_seconds=90, batch_size=200, move_hours=4),
                RoutingOperation(op_no=20, name="机加", section_id="SEC-MACH", setup_minutes=45, cycle_seconds=900, batch_size=200, move_hours=8),
                RoutingOperation(op_no=30, name="焊接", section_id="SEC-WELD", setup_minutes=40, cycle_seconds=600, batch_size=200, move_hours=8),
                RoutingOperation(op_no=40, name="涂装", section_id="SEC-PAINT", setup_minutes=30, cycle_seconds=120, batch_size=200, move_hours=8),
                RoutingOperation(op_no=50, name="组立", section_id="SEC-ASSY", setup_minutes=30, cycle_seconds=300, batch_size=100, move_hours=4),
                RoutingOperation(op_no=60, name="包装发运", section_id="SEC-PACK", setup_minutes=15, cycle_seconds=60, batch_size=100, move_hours=0),
            ],
        ),
        RoutingDef(
            routing_id="RT-P", product_id="PRD-P", product_name="泵组 P 系列",
            operations=[
                RoutingOperation(op_no=10, name="下料", section_id="SEC-CUT", setup_minutes=20, cycle_seconds=90, batch_size=200, move_hours=4),
                RoutingOperation(op_no=20, name="机加", section_id="SEC-MACH", setup_minutes=45, cycle_seconds=720, batch_size=200, move_hours=8),
                RoutingOperation(op_no=30, name="涂装", section_id="SEC-PAINT", setup_minutes=30, cycle_seconds=120, batch_size=200, move_hours=8),
                RoutingOperation(op_no=40, name="组立", section_id="SEC-ASSY", setup_minutes=30, cycle_seconds=240, batch_size=100, move_hours=4),
                RoutingOperation(op_no=50, name="包装发运", section_id="SEC-PACK", setup_minutes=15, cycle_seconds=60, batch_size=100, move_hours=0),
            ],
        ),
        RoutingDef(
            routing_id="RT-C", product_id="PRD-C", product_name="定制工装 C 系列",
            operations=[
                RoutingOperation(op_no=10, name="下料", section_id="SEC-CUT", setup_minutes=20, cycle_seconds=90, batch_size=200, move_hours=4),
                RoutingOperation(op_no=20, name="机加", section_id="SEC-MACH", setup_minutes=60, cycle_seconds=1200, batch_size=100, move_hours=8),
                RoutingOperation(op_no=30, name="焊接", section_id="SEC-WELD", setup_minutes=40, cycle_seconds=600, batch_size=100, move_hours=8),
                RoutingOperation(op_no=40, name="组立", section_id="SEC-ASSY", setup_minutes=45, cycle_seconds=360, batch_size=50, move_hours=4),
                RoutingOperation(op_no=50, name="包装发运", section_id="SEC-PACK", setup_minutes=15, cycle_seconds=60, batch_size=50, move_hours=0),
            ],
        ),
    ]
    orders = [
        OrderInput(order_id="SO-2401", product_id="PRD-R", quantity=1200, release_day=0, due_day=9, priority=Priority.HIGH),
        OrderInput(order_id="SO-2402", product_id="PRD-P", quantity=2000, release_day=0, due_day=12, priority=Priority.MEDIUM),
        OrderInput(order_id="SO-2403", product_id="PRD-R", quantity=800, release_day=2, due_day=7, priority=Priority.URGENT),
        OrderInput(order_id="SO-2404", product_id="PRD-C", quantity=400, release_day=1, due_day=6, priority=Priority.HIGH),
        OrderInput(order_id="SO-2405", product_id="PRD-P", quantity=1500, release_day=3, due_day=13, priority=Priority.MEDIUM),
        OrderInput(order_id="SO-2406", product_id="PRD-R", quantity=600, release_day=4, due_day=11, priority=Priority.LOW),
    ]
    return FactorySimConfig(
        horizon_days=14, demand_variability_pct=0.0, overtime_allowed=True, seed=42,
        workshops=workshops, sections=sections, routings=routings, orders=orders,
    )


# ====================================================================
# 工厂 2：华东汽车车身件厂（冲压→焊装→涂装→总装 四大工艺）
# ====================================================================

def _build_auto_body_plant() -> FactorySimConfig:
    workshops = [
        WorkshopConfig(
            workshop_id="WS-STAMP", name="冲压车间", working_days_per_week=7,
            description="大型伺服压机线，连续生产，面向库存备料",
        ),
        WorkshopConfig(
            workshop_id="WS-WELD", name="焊装车间", working_days_per_week=6,
            description="机器人焊装主线 + 补焊工位",
        ),
        WorkshopConfig(
            workshop_id="WS-PAINT", name="涂装车间", working_days_per_week=7,
            description="阴极电泳 + 中涂 + 面漆线，涂装线连续运行",
        ),
        WorkshopConfig(
            workshop_id="WS-GA", name="总装车间", working_days_per_week=6,
            description="内饰线 / 底盘线 / 最终线，订单进订单出",
        ),
    ]
    sections = [
        SectionConfig(
            section_id="SEC-STAMP", name="冲压线", workshop_id="WS-STAMP",
            strategy=ProductionStrategy.MTS, workers=8, machines=4,
            shifts_per_day=2, hours_per_shift=8.0, efficiency=0.90, max_overtime_pct=0.15,
            yield_rate=0.985, role_name="冲压工",
            description="大型伺服压机冲压，备料平准，三班两运转",
        ),
        SectionConfig(
            section_id="SEC-WELD", name="焊装线", workshop_id="WS-WELD",
            strategy=ProductionStrategy.MTO, workers=20, machines=18,
            shifts_per_day=2, hours_per_shift=8.0, efficiency=0.88, max_overtime_pct=0.2,
            yield_rate=0.96, role_name="焊装操作工",
            description="机器人焊装主线，18 台焊接机器人 + 人工补焊",
        ),
        SectionConfig(
            section_id="SEC-PAINT", name="涂装线", workshop_id="WS-PAINT",
            strategy=ProductionStrategy.MTO, workers=10, machines=1,
            shifts_per_day=2, hours_per_shift=8.0, efficiency=0.82, max_overtime_pct=0.15,
            yield_rate=0.93, role_name="涂装操作工",
            description="涂装主线（电泳+中涂+面漆），产能受限的典型瓶颈",
        ),
        SectionConfig(
            section_id="SEC-GA", name="总装线", workshop_id="WS-GA",
            strategy=ProductionStrategy.MTO, workers=30, machines=0,
            shifts_per_day=2, hours_per_shift=8.0, efficiency=0.85, max_overtime_pct=0.25,
            yield_rate=0.97, role_name="总装工",
            description="最终装配线，订单进订单出，按交期拉动",
        ),
        SectionConfig(
            section_id="SEC-INSPECT", name="整车检测", workshop_id="WS-GA",
            strategy=ProductionStrategy.MTO, workers=6, machines=2,
            shifts_per_day=1, hours_per_shift=8.0, efficiency=0.85, max_overtime_pct=0.2,
            yield_rate=0.99, role_name="检测员",
            description="淋雨 / 四轮定位 / 路试检测线",
        ),
    ]
    routings = [
        RoutingDef(
            routing_id="RT-SEDAN", product_id="PRD-SEDAN", product_name="轿车白车身",
            operations=[
                RoutingOperation(op_no=10, name="冲压", section_id="SEC-STAMP", setup_minutes=60, cycle_seconds=45, batch_size=500, move_hours=6),
                RoutingOperation(op_no=20, name="焊装", section_id="SEC-WELD", setup_minutes=40, cycle_seconds=180, batch_size=50, move_hours=6),
                RoutingOperation(op_no=30, name="涂装", section_id="SEC-PAINT", setup_minutes=90, cycle_seconds=240, batch_size=50, move_hours=12),
                RoutingOperation(op_no=40, name="总装", section_id="SEC-GA", setup_minutes=30, cycle_seconds=300, batch_size=20, move_hours=4),
                RoutingOperation(op_no=50, name="整车检测", section_id="SEC-INSPECT", setup_minutes=15, cycle_seconds=180, batch_size=20, move_hours=0),
            ],
        ),
        RoutingDef(
            routing_id="RT-SUV", product_id="PRD-SUV", product_name="SUV 白车身",
            operations=[
                RoutingOperation(op_no=10, name="冲压", section_id="SEC-STAMP", setup_minutes=75, cycle_seconds=60, batch_size=400, move_hours=6),
                RoutingOperation(op_no=20, name="焊装", section_id="SEC-WELD", setup_minutes=50, cycle_seconds=240, batch_size=40, move_hours=6),
                RoutingOperation(op_no=30, name="涂装", section_id="SEC-PAINT", setup_minutes=90, cycle_seconds=300, batch_size=40, move_hours=12),
                RoutingOperation(op_no=40, name="总装", section_id="SEC-GA", setup_minutes=40, cycle_seconds=360, batch_size=20, move_hours=4),
                RoutingOperation(op_no=50, name="整车检测", section_id="SEC-INSPECT", setup_minutes=15, cycle_seconds=210, batch_size=20, move_hours=0),
            ],
        ),
        RoutingDef(
            routing_id="RT-DOOR", product_id="PRD-DOOR", product_name="新能源车门总成",
            operations=[
                RoutingOperation(op_no=10, name="冲压", section_id="SEC-STAMP", setup_minutes=45, cycle_seconds=40, batch_size=600, move_hours=6),
                RoutingOperation(op_no=20, name="焊装", section_id="SEC-WELD", setup_minutes=35, cycle_seconds=150, batch_size=60, move_hours=6),
                RoutingOperation(op_no=30, name="涂装", section_id="SEC-PAINT", setup_minutes=60, cycle_seconds=180, batch_size=60, move_hours=12),
                RoutingOperation(op_no=40, name="总装", section_id="SEC-GA", setup_minutes=25, cycle_seconds=200, batch_size=30, move_hours=0),
            ],
        ),
    ]
    orders = [
        OrderInput(order_id="AO-3101", product_id="PRD-SEDAN", quantity=6000, release_day=0, due_day=11, priority=Priority.HIGH),
        OrderInput(order_id="AO-3102", product_id="PRD-SUV", quantity=4500, release_day=0, due_day=13, priority=Priority.HIGH),
        OrderInput(order_id="AO-3103", product_id="PRD-DOOR", quantity=8000, release_day=1, due_day=10, priority=Priority.MEDIUM),
        OrderInput(order_id="AO-3104", product_id="PRD-SEDAN", quantity=3000, release_day=2, due_day=8, priority=Priority.URGENT),
        OrderInput(order_id="AO-3105", product_id="PRD-SUV", quantity=2500, release_day=3, due_day=14, priority=Priority.MEDIUM),
        OrderInput(order_id="AO-3106", product_id="PRD-DOOR", quantity=5000, release_day=4, due_day=12, priority=Priority.LOW),
        OrderInput(order_id="AO-3107", product_id="PRD-SEDAN", quantity=2000, release_day=5, due_day=15, priority=Priority.LOW),
    ]
    return FactorySimConfig(
        horizon_days=16, demand_variability_pct=0.0, overtime_allowed=True, seed=7,
        workshops=workshops, sections=sections, routings=routings, orders=orders,
    )


# ====================================================================
# 工厂 3：深圳电子 SMT 厂（多品种小批量）
# ====================================================================

def _build_electronics_smt_plant() -> FactorySimConfig:
    workshops = [
        WorkshopConfig(
            workshop_id="WS-SMT", name="SMT 车间", working_days_per_week=7,
            description="高速贴片 + DIP 插件，换线频繁",
        ),
        WorkshopConfig(
            workshop_id="WS-ASSY", name="组装车间", working_days_per_week=6,
            description="板级组装 / 整机装配",
        ),
        WorkshopConfig(
            workshop_id="WS-TEST", name="测试包装车间", working_days_per_week=6,
            description="功能测试 / 老化 / 包装",
        ),
    ]
    sections = [
        SectionConfig(
            section_id="SEC-SMT", name="SMT 贴片", workshop_id="WS-SMT",
            strategy=ProductionStrategy.MTO, workers=6, machines=3,
            shifts_per_day=2, hours_per_shift=8.0, efficiency=0.90, max_overtime_pct=0.2,
            yield_rate=0.97, role_name="贴片操作工",
            description="高速贴片机线（3 台），多品种换线频繁，产能瓶颈",
        ),
        SectionConfig(
            section_id="SEC-DIP", name="DIP 插件", workshop_id="WS-SMT",
            strategy=ProductionStrategy.MTO, workers=15, machines=2,
            shifts_per_day=1, hours_per_shift=8.0, efficiency=0.85, max_overtime_pct=0.2,
            yield_rate=0.96, role_name="插件工",
            description="异形件 / 插件焊接（波峰焊）",
        ),
        SectionConfig(
            section_id="SEC-ASSY", name="整机组装", workshop_id="WS-ASSY",
            strategy=ProductionStrategy.MTO, workers=25, machines=0,
            shifts_per_day=2, hours_per_shift=8.0, efficiency=0.85, max_overtime_pct=0.25,
            yield_rate=0.98, role_name="组装工",
            description="板级与整机组装线，订单进订单出",
        ),
        SectionConfig(
            section_id="SEC-TEST", name="功能测试", workshop_id="WS-TEST",
            strategy=ProductionStrategy.MTO, workers=10, machines=8,
            shifts_per_day=2, hours_per_shift=8.0, efficiency=0.88, max_overtime_pct=0.2,
            yield_rate=0.985, role_name="测试员",
            description="ICT / FCT 功能测试 + 老化房",
        ),
        SectionConfig(
            section_id="SEC-PACK", name="包装出货", workshop_id="WS-TEST",
            strategy=ProductionStrategy.MTO, workers=8, machines=0,
            shifts_per_day=1, hours_per_shift=8.0, efficiency=0.85, max_overtime_pct=0.2,
            yield_rate=0.995, role_name="包装工",
            description="成品包装与出货",
        ),
    ]
    routings = [
        RoutingDef(
            routing_id="RT-MB", product_id="PRD-MB", product_name="工控主板",
            operations=[
                RoutingOperation(op_no=10, name="SMT 贴片", section_id="SEC-SMT", setup_minutes=50, cycle_seconds=30, batch_size=300, move_hours=3),
                RoutingOperation(op_no=20, name="DIP 插件", section_id="SEC-DIP", setup_minutes=30, cycle_seconds=60, batch_size=300, move_hours=4),
                RoutingOperation(op_no=30, name="整机组装", section_id="SEC-ASSY", setup_minutes=25, cycle_seconds=120, batch_size=100, move_hours=4),
                RoutingOperation(op_no=40, name="功能测试", section_id="SEC-TEST", setup_minutes=20, cycle_seconds=90, batch_size=100, move_hours=4),
                RoutingOperation(op_no=50, name="包装出货", section_id="SEC-PACK", setup_minutes=10, cycle_seconds=30, batch_size=100, move_hours=0),
            ],
        ),
        RoutingDef(
            routing_id="RT-GW", product_id="PRD-GW", product_name="智能网关",
            operations=[
                RoutingOperation(op_no=10, name="SMT 贴片", section_id="SEC-SMT", setup_minutes=45, cycle_seconds=24, batch_size=400, move_hours=3),
                RoutingOperation(op_no=20, name="DIP 插件", section_id="SEC-DIP", setup_minutes=25, cycle_seconds=45, batch_size=400, move_hours=4),
                RoutingOperation(op_no=30, name="整机组装", section_id="SEC-ASSY", setup_minutes=20, cycle_seconds=90, batch_size=150, move_hours=4),
                RoutingOperation(op_no=40, name="功能测试", section_id="SEC-TEST", setup_minutes=15, cycle_seconds=70, batch_size=150, move_hours=4),
                RoutingOperation(op_no=50, name="包装出货", section_id="SEC-PACK", setup_minutes=10, cycle_seconds=24, batch_size=150, move_hours=0),
            ],
        ),
        RoutingDef(
            routing_id="RT-VT", product_id="PRD-VT", product_name="车载终端",
            operations=[
                RoutingOperation(op_no=10, name="SMT 贴片", section_id="SEC-SMT", setup_minutes=60, cycle_seconds=36, batch_size=250, move_hours=3),
                RoutingOperation(op_no=20, name="DIP 插件", section_id="SEC-DIP", setup_minutes=35, cycle_seconds=70, batch_size=250, move_hours=4),
                RoutingOperation(op_no=30, name="整机组装", section_id="SEC-ASSY", setup_minutes=30, cycle_seconds=150, batch_size=80, move_hours=4),
                RoutingOperation(op_no=40, name="功能测试", section_id="SEC-TEST", setup_minutes=25, cycle_seconds=120, batch_size=80, move_hours=6),
                RoutingOperation(op_no=50, name="包装出货", section_id="SEC-PACK", setup_minutes=12, cycle_seconds=36, batch_size=80, move_hours=0),
            ],
        ),
    ]
    orders = [
        OrderInput(order_id="EO-5201", product_id="PRD-MB", quantity=2500, release_day=0, due_day=8, priority=Priority.HIGH),
        OrderInput(order_id="EO-5202", product_id="PRD-GW", quantity=4000, release_day=0, due_day=10, priority=Priority.MEDIUM),
        OrderInput(order_id="EO-5203", product_id="PRD-VT", quantity=1500, release_day=1, due_day=7, priority=Priority.URGENT),
        OrderInput(order_id="EO-5204", product_id="PRD-MB", quantity=1800, release_day=2, due_day=9, priority=Priority.MEDIUM),
        OrderInput(order_id="EO-5205", product_id="PRD-GW", quantity=3000, release_day=2, due_day=12, priority=Priority.HIGH),
        OrderInput(order_id="EO-5206", product_id="PRD-VT", quantity=900, release_day=3, due_day=11, priority=Priority.LOW),
        OrderInput(order_id="EO-5207", product_id="PRD-MB", quantity=1200, release_day=4, due_day=13, priority=Priority.LOW),
    ]
    return FactorySimConfig(
        horizon_days=14, demand_variability_pct=0.0, overtime_allowed=True, seed=88,
        workshops=workshops, sections=sections, routings=routings, orders=orders,
    )


# ====================================================================
# 工厂 4：杭州食品饮料厂（批次生产，杀菌瓶颈）
# ====================================================================

def _build_food_bev_plant() -> FactorySimConfig:
    workshops = [
        WorkshopConfig(
            workshop_id="WS-PREP", name="前处理车间", working_days_per_week=7,
            description="配料 / 调配 / 杀菌，连续批次生产",
        ),
        WorkshopConfig(
            workshop_id="WS-FILL", name="灌装车间", working_days_per_week=7,
            description="无菌灌装 / 包装，洁净区",
        ),
    ]
    sections = [
        SectionConfig(
            section_id="SEC-MIX", name="配料工段", workshop_id="WS-PREP",
            strategy=ProductionStrategy.MTS, workers=6, machines=4,
            shifts_per_day=2, hours_per_shift=8.0, efficiency=0.88, max_overtime_pct=0.15,
            yield_rate=0.99, role_name="配料工",
            description="原料称量配料（4 个配料罐），备料平准",
        ),
        SectionConfig(
            section_id="SEC-PROC", name="调配加工", workshop_id="WS-PREP",
            strategy=ProductionStrategy.MTS, workers=8, machines=6,
            shifts_per_day=2, hours_per_shift=8.0, efficiency=0.85, max_overtime_pct=0.2,
            yield_rate=0.985, role_name="调配工",
            description="调配 / 均质 / 标准化（6 个调配罐）",
        ),
        SectionConfig(
            section_id="SEC-STER", name="杀菌工段", workshop_id="WS-PREP",
            strategy=ProductionStrategy.MTO, workers=5, machines=2,
            shifts_per_day=2, hours_per_shift=8.0, efficiency=0.80, max_overtime_pct=0.2,
            yield_rate=0.96, role_name="杀菌操作工",
            description="UHT / 杀菌釜（2 台），批次产能受限的典型瓶颈",
        ),
        SectionConfig(
            section_id="SEC-FILL", name="灌装工段", workshop_id="WS-FILL",
            strategy=ProductionStrategy.MTO, workers=10, machines=2,
            shifts_per_day=2, hours_per_shift=8.0, efficiency=0.88, max_overtime_pct=0.2,
            yield_rate=0.975, role_name="灌装工",
            description="无菌灌装线（2 条），订单进订单出",
        ),
        SectionConfig(
            section_id="SEC-PACK", name="包装工段", workshop_id="WS-FILL",
            strategy=ProductionStrategy.MTO, workers=12, machines=3,
            shifts_per_day=2, hours_per_shift=8.0, efficiency=0.85, max_overtime_pct=0.2,
            yield_rate=0.99, role_name="包装工",
            description="套标 / 装箱 / 码垛",
        ),
    ]
    routings = [
        RoutingDef(
            routing_id="RT-JUICE", product_id="PRD-JUICE", product_name="果蔬汁",
            operations=[
                RoutingOperation(op_no=10, name="配料", section_id="SEC-MIX", setup_minutes=40, cycle_seconds=12, batch_size=1000, move_hours=2),
                RoutingOperation(op_no=20, name="调配", section_id="SEC-PROC", setup_minutes=45, cycle_seconds=15, batch_size=1000, move_hours=3),
                RoutingOperation(op_no=30, name="杀菌", section_id="SEC-STER", setup_minutes=60, cycle_seconds=20, batch_size=800, move_hours=3),
                RoutingOperation(op_no=40, name="灌装", section_id="SEC-FILL", setup_minutes=50, cycle_seconds=8, batch_size=800, move_hours=2),
                RoutingOperation(op_no=50, name="包装", section_id="SEC-PACK", setup_minutes=20, cycle_seconds=6, batch_size=800, move_hours=0),
            ],
        ),
        RoutingDef(
            routing_id="RT-YOGURT", product_id="PRD-YOGURT", product_name="乳酸菌饮料",
            operations=[
                RoutingOperation(op_no=10, name="配料", section_id="SEC-MIX", setup_minutes=50, cycle_seconds=14, batch_size=900, move_hours=2),
                RoutingOperation(op_no=20, name="调配", section_id="SEC-PROC", setup_minutes=55, cycle_seconds=18, batch_size=900, move_hours=4),
                RoutingOperation(op_no=30, name="杀菌", section_id="SEC-STER", setup_minutes=70, cycle_seconds=24, batch_size=700, move_hours=3),
                RoutingOperation(op_no=40, name="灌装", section_id="SEC-FILL", setup_minutes=55, cycle_seconds=10, batch_size=700, move_hours=2),
                RoutingOperation(op_no=50, name="包装", section_id="SEC-PACK", setup_minutes=22, cycle_seconds=7, batch_size=700, move_hours=0),
            ],
        ),
        RoutingDef(
            routing_id="RT-TEA", product_id="PRD-TEA", product_name="茶饮料",
            operations=[
                RoutingOperation(op_no=10, name="配料", section_id="SEC-MIX", setup_minutes=35, cycle_seconds=10, batch_size=1200, move_hours=2),
                RoutingOperation(op_no=20, name="调配", section_id="SEC-PROC", setup_minutes=40, cycle_seconds=13, batch_size=1200, move_hours=3),
                RoutingOperation(op_no=30, name="杀菌", section_id="SEC-STER", setup_minutes=55, cycle_seconds=18, batch_size=1000, move_hours=3),
                RoutingOperation(op_no=40, name="灌装", section_id="SEC-FILL", setup_minutes=45, cycle_seconds=7, batch_size=1000, move_hours=2),
                RoutingOperation(op_no=50, name="包装", section_id="SEC-PACK", setup_minutes=18, cycle_seconds=5, batch_size=1000, move_hours=0),
            ],
        ),
    ]
    orders = [
        OrderInput(order_id="FO-7301", product_id="PRD-JUICE", quantity=18000, release_day=0, due_day=9, priority=Priority.HIGH),
        OrderInput(order_id="FO-7302", product_id="PRD-YOGURT", quantity=12000, release_day=0, due_day=11, priority=Priority.HIGH),
        OrderInput(order_id="FO-7303", product_id="PRD-TEA", quantity=22000, release_day=1, due_day=10, priority=Priority.MEDIUM),
        OrderInput(order_id="FO-7304", product_id="PRD-JUICE", quantity=9000, release_day=2, due_day=7, priority=Priority.URGENT),
        OrderInput(order_id="FO-7305", product_id="PRD-YOGURT", quantity=8000, release_day=3, due_day=12, priority=Priority.MEDIUM),
        OrderInput(order_id="FO-7306", product_id="PRD-TEA", quantity=15000, release_day=4, due_day=13, priority=Priority.LOW),
    ]
    return FactorySimConfig(
        horizon_days=14, demand_variability_pct=0.0, overtime_allowed=True, seed=21,
        workshops=workshops, sections=sections, routings=routings, orders=orders,
    )


# ====================================================================
# 场景注册表
# ====================================================================

SCENARIO_REGISTRY: Dict[str, Dict] = {
    "enghub-precision-plant": {
        "scenario_id": "enghub-precision-plant",
        "scenario_name": "EngHub 精密机械厂",
        "description": (
            "3 类产品 / 6 张订单 / 2 个车间 / 6 个工段。"
            "备料与机加按库存平准生产（负荷均衡），焊接为产能瓶颈，"
            "组立作为最终工段按订单交期拉动（订单进、订单出）。"
        ),
        "tags": ["机械混流", "焊接瓶颈", "MTS/MTO 混合"],
        "hints": [
            "把焊接工段人数从 6 提到 8，观察延期订单是否消失",
            "给机加车间改 5 天工作制，观察备料负荷率变化",
            "新增一张大订单，观察各工段负荷矩阵如何被拉动",
            "将组立策略切到 MTS，对比负荷热力图的脉冲形态",
        ],
        "builder": _build_precision_plant,
    },
    "auto-body-plant": {
        "scenario_id": "auto-body-plant",
        "scenario_name": "华东汽车车身件厂",
        "description": (
            "3 类白车身 / 7 张订单 / 4 个车间 / 5 个工段。"
            "冲压→焊装→涂装→总装四大工艺，冲压备料平准（全周运行），"
            "涂装线产能受限为典型瓶颈，总装按订单交期拉动。"
        ),
        "tags": ["汽车四大工艺", "涂装瓶颈", "大批量"],
        "hints": [
            "涂装线只有 1 条产线，试着增加班次观察瓶颈是否缓解",
            "把冲压车间改双休，观察备料库存对后段的影响",
            "新增一张紧急 SUV 订单，观察涂装与总装的负荷分化",
        ],
        "builder": _build_auto_body_plant,
    },
    "electronics-smt-plant": {
        "scenario_id": "electronics-smt-plant",
        "scenario_name": "深圳电子 SMT 厂",
        "description": (
            "3 类电子产品 / 7 张订单 / 3 个车间 / 5 个工段。"
            "多品种小批量、换线频繁，SMT 高速贴片机为产能瓶颈，"
            "整机组装按订单交期拉动。"
        ),
        "tags": ["电子 SMT", "多品种小批量", "贴片瓶颈"],
        "hints": [
            "SMT 贴片机仅 3 台，增加 1 台设备观察延期改善",
            "把车载终端订单提前投放，观察 SMT 换线压力",
            "将 DIP 插件改双班，观察对组装段供料的影响",
        ],
        "builder": _build_electronics_smt_plant,
    },
    "food-beverage-plant": {
        "scenario_id": "food-beverage-plant",
        "scenario_name": "杭州食品饮料厂",
        "description": (
            "3 类饮料 / 6 张订单 / 2 个车间 / 5 个工段。"
            "配料→调配→杀菌→灌装→包装批次生产，杀菌釜批次产能受限为瓶颈，"
            "灌装按订单交期拉动。"
        ),
        "tags": ["食品饮料", "批次生产", "杀菌瓶颈"],
        "hints": [
            "杀菌工段仅 2 台杀菌釜，增加设备观察瓶颈缓解",
            "把果蔬汁大订单交期提前，观察杀菌与灌装的负荷脉冲",
            "将配料工段改单班，观察备料对连续生产的影响",
        ],
        "builder": _build_food_bev_plant,
    },
}

# 默认场景（向后兼容）
DEFAULT_SCENARIO_ID = "enghub-precision-plant"
SCENARIO_META = {k: v for k, v in SCENARIO_REGISTRY[DEFAULT_SCENARIO_ID].items() if k != "builder"}


def build_default_scenario() -> FactorySimConfig:
    """默认工厂场景（精密机械厂），向后兼容旧接口。"""
    return SCENARIO_REGISTRY[DEFAULT_SCENARIO_ID]["builder"]()


def list_scenarios() -> List[Dict]:
    """返回所有工厂场景的轻量元信息（供前端切换器）。"""
    return [
        {
            "scenario_id": meta["scenario_id"],
            "scenario_name": meta["scenario_name"],
            "description": meta["description"],
            "tags": meta["tags"],
            "hints": meta["hints"],
        }
        for meta in SCENARIO_REGISTRY.values()
    ]


def build_scenario(scenario_id: str) -> FactorySimConfig:
    """按 scenario_id 构建工厂场景，未知 id 回退默认场景。"""
    entry = SCENARIO_REGISTRY.get(scenario_id) or SCENARIO_REGISTRY[DEFAULT_SCENARIO_ID]
    return entry["builder"]()


def get_scenario_meta(scenario_id: str) -> Dict:
    """按 scenario_id 取场景元信息，未知 id 回退默认场景。"""
    entry = SCENARIO_REGISTRY.get(scenario_id) or SCENARIO_REGISTRY[DEFAULT_SCENARIO_ID]
    return {k: v for k, v in entry.items() if k != "builder"}
