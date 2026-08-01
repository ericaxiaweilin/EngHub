#!/usr/bin/env python3
"""Seed complete demo coverage for the two EngHub mock factories.

This script is intentionally dependency-free. It runs SQL through the Postgres
Docker container and only upserts deterministic demo rows for:
- RCC command center tables and tasks
- WMS warehouses
- PP plans
- routing template steps
- IE basic and advanced modules
- HR attendance/leave/rest and equipment engineer ownership
- TPM maintenance plans/orders/downtime and recent OEE production pulse
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import uuid
from typing import Any


PG_CONTAINER = os.getenv("PG_CONTAINER", "docker-postgres-1")
PG_USER = os.getenv("PG_USER", "enghub")
PG_DB = os.getenv("PG_DB", "enghub")
DEFAULT_FACTORIES = ["FAC_ELEC_DEMO_2026", "FAC_MECH_001"]
UUID_NS = uuid.uuid5(uuid.NAMESPACE_URL, "enghub-demo-module-coverage")


class Expr(str):
    pass


def stable_id(*parts: str) -> str:
    return str(uuid.uuid5(UUID_NS, ":".join(parts)))


def q(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def sql_json(value: Any, cast: str = "jsonb") -> Expr:
    return Expr(q(json.dumps(value, ensure_ascii=False)) + f"::{cast}")


def sql_value(value: Any) -> str:
    if isinstance(value, Expr):
        return str(value)
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return q(str(value))


def upsert(table: str, values: dict[str, Any], conflict: str = "id") -> str:
    columns = list(values)
    insert_values = ", ".join(sql_value(values[c]) for c in columns)
    update_columns = [c for c in columns if c != conflict]
    updates = ", ".join(f"{c}=EXCLUDED.{c}" for c in update_columns)
    return (
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({insert_values}) "
        f"ON CONFLICT ({conflict}) DO UPDATE SET {updates};"
    )


def product_expr(factory_id: str, offset: int = 0) -> Expr:
    return Expr(
        "(SELECT product_code FROM products "
        f"WHERE factory_id={q(factory_id)} ORDER BY product_code LIMIT 1 OFFSET {offset})"
    )


def product_id_expr(factory_id: str, offset: int = 0) -> Expr:
    return Expr(
        "(SELECT id FROM products "
        f"WHERE factory_id={q(factory_id)} ORDER BY product_code LIMIT 1 OFFSET {offset})"
    )


def station_expr(factory_id: str, offset: int = 0) -> Expr:
    return Expr(
        "(SELECT station_code FROM stations "
        f"WHERE factory_id={q(factory_id)} ORDER BY station_code LIMIT 1 OFFSET {offset})"
    )


def work_order_id_expr(factory_id: str, offset: int = 0) -> Expr:
    return Expr(
        "(SELECT id FROM work_orders "
        f"WHERE factory_id={q(factory_id)} ORDER BY created_at DESC NULLS LAST, id LIMIT 1 OFFSET {offset})"
    )


def equipment_id_expr(factory_id: str, offset: int = 0) -> Expr:
    return Expr(
        "(SELECT id FROM equipment "
        f"WHERE factory_id={q(factory_id)} ORDER BY equipment_code NULLS LAST, id LIMIT 1 OFFSET {offset})"
    )


def org_id(factory_id: str) -> str:
    return stable_id("rcc-org", factory_id)


def base_schema_sql() -> list[str]:
    return [
        "CREATE EXTENSION IF NOT EXISTS pgcrypto;",
        """
        CREATE TABLE IF NOT EXISTS org_units (
            id VARCHAR(36) PRIMARY KEY,
            code VARCHAR(50),
            name VARCHAR(200),
            parent_id VARCHAR(36),
            level_type VARCHAR(20) DEFAULT 'operational',
            factory_id VARCHAR(50),
            metadata_ JSONB DEFAULT '{}'::jsonb,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS position_capabilities (
            id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
            cap_code VARCHAR(50) UNIQUE,
            cap_name VARCHAR(200),
            skill_level_min VARCHAR(10),
            skill_level_max VARCHAR(10),
            org_unit_id VARCHAR(36),
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS rcc_organizations (
            id VARCHAR(36) PRIMARY KEY,
            org_type VARCHAR(20) NOT NULL DEFAULT 'rcc',
            resource_pool JSONB DEFAULT '{}'::jsonb,
            capacity_model JSONB DEFAULT '{}'::jsonb,
            dispatch_rules JSONB DEFAULT '[]'::jsonb,
            auto_dispatch_enabled BOOLEAN DEFAULT FALSE,
            human_approval_required BOOLEAN DEFAULT TRUE,
            approval_threshold_pct DOUBLE PRECISION DEFAULT 80.0,
            last_sync_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS rcc_tasks (
            id VARCHAR(36) PRIMARY KEY,
            task_code VARCHAR(50) UNIQUE NOT NULL,
            org_unit_id VARCHAR(36),
            task_type VARCHAR(30) NOT NULL,
            title VARCHAR(200) NOT NULL,
            description TEXT,
            affected_params JSONB DEFAULT '[]'::jsonb,
            affected_entities JSONB DEFAULT '[]'::jsonb,
            expected_impact_summary TEXT,
            status VARCHAR(20) DEFAULT 'pending',
            approved_by VARCHAR(50),
            approved_at TIMESTAMP,
            rejected_by VARCHAR(50),
            rejection_reason TEXT,
            executed_at TIMESTAMP,
            completed_at TIMESTAMP,
            requested_by VARCHAR(50),
            request_context JSONB DEFAULT '{}'::jsonb,
            source_ticket_id VARCHAR(36),
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS rcc_approval_records (
            id VARCHAR(36) PRIMARY KEY,
            rcc_task_id VARCHAR(36),
            approver_role VARCHAR(50) NOT NULL,
            approver_name VARCHAR(100),
            decision VARCHAR(20) NOT NULL,
            decision_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            comment TEXT,
            escalation_level INTEGER DEFAULT 0
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS chatbot_tickets (
            id VARCHAR(36) PRIMARY KEY,
            ticket_code VARCHAR(50) UNIQUE NOT NULL,
            requester_id VARCHAR(50) NOT NULL,
            requester_org_unit VARCHAR(36),
            ticket_type VARCHAR(30) NOT NULL,
            raw_message TEXT NOT NULL,
            parsed_intents JSONB DEFAULT '{}'::jsonb,
            parsed_slots JSONB DEFAULT '{}'::jsonb,
            requested_resource JSONB DEFAULT '{}'::jsonb,
            requested_time_window JSONB DEFAULT '{}'::jsonb,
            related_param_id VARCHAR(36),
            related_rcc_task_id VARCHAR(36),
            related_andon_id VARCHAR(36),
            related_work_order_id VARCHAR(36),
            status VARCHAR(20) DEFAULT 'open',
            priority VARCHAR(20) DEFAULT 'medium',
            routed_to_org_unit VARCHAR(36),
            routed_to_position VARCHAR(50),
            resolved_by VARCHAR(50),
            resolution TEXT,
            resolved_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS chatbot_ticket_approval_flow (
            id VARCHAR(36) PRIMARY KEY,
            ticket_id VARCHAR(36),
            step INTEGER NOT NULL,
            role_required VARCHAR(50),
            approver_id VARCHAR(50),
            decision VARCHAR(20),
            decision_at TIMESTAMP,
            comment TEXT
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS deterministic_logic_chains (
            id VARCHAR(36) PRIMARY KEY,
            chain_code VARCHAR(50) UNIQUE NOT NULL,
            chain_name VARCHAR(100) NOT NULL,
            org_unit_id VARCHAR(36),
            position_cap_id VARCHAR(36),
            trigger_event VARCHAR(100) NOT NULL,
            conditions JSONB NOT NULL DEFAULT '[]'::jsonb,
            action_sequence JSONB NOT NULL DEFAULT '[]'::jsonb,
            enabled BOOLEAN DEFAULT TRUE,
            execution_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS logic_chain_execution_log (
            id VARCHAR(36) PRIMARY KEY,
            chain_id VARCHAR(36),
            triggered_by VARCHAR(50),
            trigger_payload JSONB DEFAULT '{}'::jsonb,
            conditions_matched BOOLEAN DEFAULT TRUE,
            actions_executed JSONB DEFAULT '[]'::jsonb,
            action_results JSONB DEFAULT '[]'::jsonb,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS global_adjustable_params (
            id VARCHAR(36) PRIMARY KEY,
            param_code VARCHAR(100) UNIQUE NOT NULL,
            param_name VARCHAR(100) NOT NULL,
            org_unit_id VARCHAR(36),
            position_cap_id VARCHAR(36),
            category VARCHAR(20) NOT NULL,
            param_type VARCHAR(20) NOT NULL,
            default_value VARCHAR,
            current_value VARCHAR,
            effective_from TIMESTAMP DEFAULT NOW(),
            target_value VARCHAR,
            min_value DOUBLE PRECISION,
            max_value DOUBLE PRECISION,
            step_value DOUBLE PRECISION,
            unit VARCHAR(50),
            options JSONB DEFAULT '[]'::jsonb,
            sensitivity VARCHAR(20) DEFAULT 'normal',
            affects_logic_chains JSONB DEFAULT '[]'::jsonb,
            rollback_allowed BOOLEAN DEFAULT TRUE,
            rollback_window_minutes INTEGER DEFAULT 60,
            changed_by VARCHAR(50),
            change_reason TEXT,
            previous_value VARCHAR,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );
        """,
        "ALTER TABLE global_adjustable_params ADD COLUMN IF NOT EXISTS sensitivity VARCHAR(20) DEFAULT 'normal';",
        "ALTER TABLE global_adjustable_params ADD COLUMN IF NOT EXISTS affects_logic_chains JSONB DEFAULT '[]'::jsonb;",
        "ALTER TABLE global_adjustable_params ADD COLUMN IF NOT EXISTS rollback_allowed BOOLEAN DEFAULT TRUE;",
        "ALTER TABLE global_adjustable_params ADD COLUMN IF NOT EXISTS rollback_window_minutes INTEGER DEFAULT 60;",
        "ALTER TABLE global_adjustable_params ADD COLUMN IF NOT EXISTS changed_by VARCHAR(50);",
        "ALTER TABLE global_adjustable_params ADD COLUMN IF NOT EXISTS change_reason TEXT;",
        "ALTER TABLE global_adjustable_params ADD COLUMN IF NOT EXISTS previous_value VARCHAR;",
        """
        CREATE TABLE IF NOT EXISTS im_groups (
            id VARCHAR(36) PRIMARY KEY,
            factory_id VARCHAR(50),
            name VARCHAR(100) NOT NULL,
            description VARCHAR(500),
            group_type VARCHAR(30) DEFAULT 'ops',
            org_node_id VARCHAR(50),
            owner_id VARCHAR(50),
            avatar_color VARCHAR(20) DEFAULT '#1677ff',
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS im_messages (
            id VARCHAR(36) PRIMARY KEY,
            group_id VARCHAR(36),
            sender_id VARCHAR(50),
            sender_name VARCHAR(100),
            msg_type VARCHAR(20) DEFAULT 'text',
            content TEXT NOT NULL,
            command_type VARCHAR(50),
            command_payload JSONB DEFAULT '{}'::jsonb,
            reply_to_id VARCHAR(36),
            created_at TIMESTAMP DEFAULT NOW()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS item_traceability (
            id VARCHAR(36) PRIMARY KEY,
            item_code VARCHAR(50) UNIQUE NOT NULL,
            item_type VARCHAR(20) DEFAULT 'finished',
            factory_id VARCHAR(50) NOT NULL,
            work_order_id VARCHAR(36),
            product_id VARCHAR(36),
            material_batch_id VARCHAR(50),
            material_supplier_id VARCHAR(50),
            station_id VARCHAR(50),
            equipment_id VARCHAR(36),
            operator_id VARCHAR(50),
            quality_check_result VARCHAR(20),
            serial_number VARCHAR(50),
            next_item_code VARCHAR(50),
            inspection_record_id VARCHAR(36),
            metadata JSONB DEFAULT '{}'::jsonb,
            created_by VARCHAR(50),
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );
        """,
    ]


def rcc_sql(factory_id: str, label: str) -> list[str]:
    root = org_id(factory_id)
    capacity = 300 if factory_id == "FAC_MECH_001" else 240
    task_a = stable_id("rcc-task", factory_id, "monthly-pulse")
    task_b = stable_id("rcc-task", factory_id, "ie-bottleneck")
    return [
        upsert("org_units", {
            "id": root,
            "code": f"RCC-{factory_id}",
            "name": f"{label} RCC资源指挥中心",
            "parent_id": None,
            "level_type": "strategic",
            "factory_id": factory_id,
            "metadata_": sql_json({"type": "rcc", "factory_id": factory_id}),
            "updated_at": Expr("NOW()"),
        }),
        upsert("rcc_organizations", {
            "id": root,
            "org_type": "rcc",
            "resource_pool": sql_json({"monthly_container_capacity": capacity, "factories": [factory_id]}),
            "capacity_model": sql_json({"container_per_month": capacity, "daily_pulse": round(capacity / 26, 2), "order_lead_time_days": 90}),
            "dispatch_rules": sql_json([
                {"rule_id": "bottleneck_over_85pct", "action": "open_rcc_task", "threshold": 0.85},
                {"rule_id": "delivery_risk_over_7d", "action": "resequence_work_orders", "threshold_days": 7},
            ]),
            "auto_dispatch_enabled": True,
            "human_approval_required": True,
            "approval_threshold_pct": 82.0,
            "last_sync_at": Expr("NOW()"),
            "updated_at": Expr("NOW()"),
        }),
        upsert("rcc_tasks", {
            "id": task_a,
            "task_code": f"RCC-{factory_id[-4:]}-PULSE",
            "org_unit_id": root,
            "task_type": "scheduling",
            "title": f"{label}月度出货节奏校核",
            "description": f"按{capacity}柜/月的产能节奏校核订单、工单、出货和瓶颈资源，不允许秒下单秒完工。",
            "affected_params": sql_json(["monthly_container_capacity", "daily_dispatch_pulse"]),
            "affected_entities": sql_json(["sales_orders", "work_orders", "aps_schedules", "shipments"]),
            "expected_impact_summary": "维持90天订单脉动，按日释放、按周复盘。",
            "status": "in_progress",
            "approved_by": "RCC",
            "approved_at": Expr("NOW() - INTERVAL '2 days'"),
            "requested_by": "virtual_factory_agent",
            "request_context": sql_json({"factory_id": factory_id, "monthly_container_capacity": capacity}),
            "created_at": Expr("NOW() - INTERVAL '3 days'"),
            "updated_at": Expr("NOW()"),
        }),
        upsert("rcc_tasks", {
            "id": task_b,
            "task_code": f"RCC-{factory_id[-4:]}-IE",
            "org_unit_id": root,
            "task_type": "dispatch",
            "title": f"{label}IE瓶颈工位重排决策",
            "description": "基于IE标准工时、时间研究和线平衡数据识别瓶颈，生成可执行调度建议。",
            "affected_params": sql_json(["line_balance_threshold", "standard_time_variance"]),
            "affected_entities": sql_json(["standard_operation_times", "line_balance_analyses", "stations"]),
            "expected_impact_summary": "瓶颈工位负荷降至85%以下，维持出货节奏。",
            "status": "pending",
            "requested_by": "ie_agent",
            "request_context": sql_json({"factory_id": factory_id, "reason": "IE module coverage guard"}),
            "created_at": Expr("NOW() - INTERVAL '1 day'"),
            "updated_at": Expr("NOW()"),
        }),
        upsert("rcc_approval_records", {
            "id": stable_id("rcc-approval", factory_id),
            "rcc_task_id": task_a,
            "approver_role": "factory_manager",
            "approver_name": "RCC自动审批",
            "decision": "approved",
            "decision_at": Expr("NOW() - INTERVAL '2 days'"),
            "comment": "按月度产能脉动执行，异常进入RCC任务中心。",
            "escalation_level": 1,
        }),
        upsert("global_adjustable_params", {
            "id": stable_id("rcc-param", factory_id, "container_capacity"),
            "param_code": f"{factory_id}_monthly_container_capacity",
            "param_name": f"{label}月出货柜数上限",
            "org_unit_id": root,
            "category": "capacity",
            "param_type": "number",
            "default_value": str(capacity),
            "current_value": str(capacity),
            "min_value": 60,
            "max_value": 450,
            "step_value": 10,
            "unit": "柜/月",
            "sensitivity": "high",
            "affects_logic_chains": sql_json(["ORDER_TO_WORK_ORDER_PULSE"]),
            "rollback_allowed": True,
            "rollback_window_minutes": 120,
            "updated_at": Expr("NOW()"),
        }),
        upsert("deterministic_logic_chains", {
            "id": stable_id("logic-chain", factory_id, "order-pulse"),
            "chain_code": f"LC-{factory_id[-4:]}-PULSE",
            "chain_name": f"{label}订单到工单节奏链",
            "org_unit_id": root,
            "trigger_event": "sales_order_confirmed",
            "conditions": sql_json([
                {"field": "factory_id", "op": "eq", "value": factory_id},
                {"field": "lead_time_days", "op": "gte", "value": 30},
            ]),
            "action_sequence": sql_json([
                {"action": "decompose_order", "cadence": "weekly"},
                {"action": "release_work_orders", "cadence": "daily"},
                {"action": "rcc_review", "threshold": "capacity_load>85%"},
            ]),
            "enabled": True,
            "execution_order": 10,
            "updated_at": Expr("NOW()"),
        }),
    ]


def warehouse_plan_sql(factory_id: str, label: str) -> list[str]:
    short = "ELEC" if factory_id == "FAC_ELEC_DEMO_2026" else "MECH"
    return [
        upsert("warehouses", {
            "id": stable_id("warehouse", factory_id, "raw"),
            "warehouse_code": f"WH-{short}-RAW",
            "warehouse_name": f"{label}原材料仓",
            "factory_id": factory_id,
            "warehouse_type": "raw_material",
            "address": f"{label}厂区A栋",
            "status": "active",
            "created_by": "seed_guard",
            "created_at": Expr("NOW() - INTERVAL '20 days'"),
            "updated_at": Expr("NOW()"),
        }),
        upsert("warehouses", {
            "id": stable_id("warehouse", factory_id, "fg"),
            "warehouse_code": f"WH-{short}-FG",
            "warehouse_name": f"{label}成品仓",
            "factory_id": factory_id,
            "warehouse_type": "finished_goods",
            "address": f"{label}出货月台",
            "status": "active",
            "created_by": "seed_guard",
            "created_at": Expr("NOW() - INTERVAL '20 days'"),
            "updated_at": Expr("NOW()"),
        }),
        upsert("plans", {
            "id": stable_id("plan", factory_id, "rcc-pulse"),
            "plan_code": f"PLAN-{short}-RCC-PULSE",
            "factory_id": factory_id,
            "product_id": product_expr(factory_id),
            "sales_order_id": None,
            "quantity": 1200 if short == "ELEC" else 900,
            "required_date": Expr("NOW() + INTERVAL '45 days'"),
            "plan_type": "MTO",
            "customer_level": "A",
            "priority": 2,
            "status": "released",
            "due_date": Expr("NOW() + INTERVAL '45 days'"),
            "priority_score": 86,
            "released_by": "RCC",
            "released_at": Expr("NOW() - INTERVAL '3 days'"),
            "created_at": Expr("NOW() - INTERVAL '7 days'"),
            "updated_at": Expr("NOW()"),
            "created_by": "seed_guard",
        }),
    ]


def routing_sql(factory_id: str) -> list[str]:
    if factory_id == "FAC_ELEC_DEMO_2026":
        tid = stable_id("routing-template", factory_id, "elec-main")
        steps = [
            ("SMT", "SMT贴片", "SMT-LINE", 1.2, True),
            ("AOI", "AOI检测", "AOI", 0.4, True),
            ("ASSY", "总装", "ASSY-LINE", 2.6, False),
            ("FLASH", "烧录检测", "FLASH", 0.8, True),
            ("AUDIO", "声学全检", "AUDIO-TEST", 1.1, True),
            ("PACK", "包装入库", "PACK", 0.7, False),
        ]
        sql = [
            upsert("routing_templates", {
                "id": tid,
                "template_code": "RT-ELEC-001",
                "template_name": "智能音箱标准工艺",
                "factory_id": factory_id,
                "description": "SMT -> AOI -> 总装 -> 烧录 -> 声学全检 -> 包装",
                "is_active": True,
                "created_by": "seed_guard",
                "updated_at": Expr("NOW()"),
            })
        ]
    else:
        tid = None
        steps = []
        sql = []
        mech_steps = {
            "RT-MECH-001": [("CUT", "下料", "ST-JG-01", 1.5, False), ("CNC", "精加工", "ST-JJG-01", 3.5, False), ("WELD", "焊接", "ST-HJ-01", 2.0, False), ("PAINT", "涂装", "ST-TZ-01", 1.8, False), ("QC", "成品检", "ST-QC-02", 0.8, True), ("PACK", "包装", "ST-PK-01", 0.6, False)],
            "RT-MECH-002": [("INJ", "注塑", "ST-ZS-01", 2.4, False), ("CNC", "精加工", "ST-JJG-01", 2.8, False), ("DIP", "浸塑", "ST-JS-01", 1.6, False), ("ASSY", "组立", "ST-ZL-01", 1.9, False), ("QC", "成品检", "ST-QC-02", 0.7, True), ("PACK", "包装", "ST-PK-01", 0.5, False)],
            "RT-MECH-003": [("WIRE", "线材加工", "ST-XC-01", 1.1, False), ("WELD", "焊接", "ST-HJ-01", 1.7, False), ("ELEC", "機電组装", "ST-JD-01", 2.2, False), ("METER", "仪表检测", "ST-YB-01", 1.0, True), ("QC", "成品检", "ST-QC-02", 0.8, True), ("PACK", "包装", "ST-PK-01", 0.5, False)],
            "RT-MECH-004": [("INJ", "注塑", "ST-ZS-01", 2.1, False), ("TRIM", "加工", "ST-JG-01", 1.8, False), ("PAINT", "涂装", "ST-TZ-01", 1.3, False), ("ASSY", "组立", "ST-ZL-02", 1.6, False), ("QC", "成品检", "ST-QC-02", 0.7, True), ("PACK", "包装", "ST-PK-01", 0.4, False)],
            "RT-MECH-005": [("CNC", "加工", "ST-JG-01", 2.3, False), ("ELEC", "機電组装", "ST-JD-01", 2.4, False), ("CAL", "仪表校准", "ST-YB-01", 1.2, True), ("ASSY", "组立", "ST-ZL-03", 1.5, False), ("QC", "成品检", "ST-QC-02", 0.8, True), ("PACK", "包装", "ST-PK-01", 0.5, False)],
        }
        for code, rows in mech_steps.items():
            for idx, (process_code, name, work_center, hours, qc_gate) in enumerate(rows, start=1):
                sql.append(
                    "INSERT INTO routing_template_steps "
                    "(id, template_id, seq, process_code, operation_name, work_center, standard_hours, is_qc_gate, remark) "
                    "SELECT "
                    f"{q(stable_id('routing-step', factory_id, code, str(idx)))}, id, {idx}, "
                    f"{q(process_code)}, {q(name)}, {q(work_center)}, {hours}, {str(qc_gate).lower()}, "
                    f"{q('demo coverage seed')} FROM routing_templates "
                    f"WHERE factory_id={q(factory_id)} AND template_code={q(code)} "
                    "ON CONFLICT (id) DO UPDATE SET "
                    "operation_name=EXCLUDED.operation_name, work_center=EXCLUDED.work_center, "
                    "standard_hours=EXCLUDED.standard_hours, is_qc_gate=EXCLUDED.is_qc_gate;"
                )
        return sql

    for idx, (process_code, name, work_center, hours, qc_gate) in enumerate(steps, start=1):
        sql.append(upsert("routing_template_steps", {
            "id": stable_id("routing-step", factory_id, "RT-ELEC-001", str(idx)),
            "template_id": tid,
            "seq": idx,
            "process_code": process_code,
            "operation_name": name,
            "work_center": work_center,
            "standard_hours": hours,
            "is_parallel": False,
            "is_qc_gate": qc_gate,
            "remark": "demo coverage seed",
        }))
    return sql


def ie_sql(factory_id: str, label: str) -> list[str]:
    short = "ELEC" if factory_id == "FAC_ELEC_DEMO_2026" else "MECH"
    if short == "ELEC":
        operations = ["SMT贴片", "AOI复判", "总装锁附", "烧录检测", "声学全检", "包装扫码"]
    else:
        operations = ["CNC开粗", "EDM精加工", "慢走丝割镶件", "钳工合模", "试模参数确认", "成品检验"]

    sql: list[str] = []
    for idx, operation in enumerate(operations, start=1):
        standard_min = round(0.9 + idx * (0.28 if short == "ELEC" else 0.55), 2)
        sql.append(upsert("standard_operation_times", {
            "id": stable_id("std-time", factory_id, str(idx)),
            "factory_id": factory_id,
            "product_id": product_expr(factory_id, idx % 2),
            "routing_step": f"OP{idx * 10:02d}",
            "operation_seq": idx,
            "operation_name": operation,
            "station_id": station_expr(factory_id, idx - 1),
            "work_center": f"{short}-WC-{idx:02d}",
            "standard_time_min": standard_min,
            "unit_time_type": "per_unit",
            "setup_time_min": round(8 + idx * 1.5, 2),
            "setup_before_start_time_min": round(3 + idx * 0.5, 2),
            "post_operation_time_min": round(1 + idx * 0.2, 2),
            "batch_size": 120 if short == "ELEC" else 40,
            "rating_factor": 1.0,
            "allowance_rate": 0.12,
            "effective_standard_time": round(standard_min * 1.12, 2),
            "version": "v2026.08",
            "is_active": True,
            "validity_start": Expr("CURRENT_DATE - INTERVAL '30 days'"),
            "validity_end": Expr("CURRENT_DATE + INTERVAL '365 days'"),
            "created_by": "seed_guard",
            "created_at": Expr("NOW() - INTERVAL '10 days'"),
            "updated_at": Expr("NOW()"),
        }))
        avg = round(standard_min * 60 * (0.96 + idx * 0.01), 2)
        sql.append(upsert("time_study_records", {
            "id": stable_id("time-study", factory_id, str(idx)),
            "factory_id": factory_id,
            "product_id": product_expr(factory_id, idx % 2),
            "station_id": station_expr(factory_id, idx - 1),
            "operation_name": operation,
            "operator_id": f"OP-{short}-{100 + idx}",
            "observer_id": f"IE-{short}-01",
            "observation_date": Expr(f"NOW() - INTERVAL '{idx} days'"),
            "observed_cycles": sql_json([round(avg + n * 1.7, 2) for n in range(5)], "json"),
            "cycle_count": 5,
            "average_time": avg,
            "rating_factor": 1.0,
            "normal_time": avg,
            "allowed_time": round(avg * 1.12, 2),
            "allowance_rate": 0.12,
            "method": "stopwatch",
            "status": "approved" if idx % 3 else "pending",
            "created_by": "seed_guard",
            "created_at": Expr(f"NOW() - INTERVAL '{idx} days'"),
            "updated_at": Expr("NOW()"),
        }))

    for idx, rate in enumerate([0.82, 0.88, 0.76], start=1):
        sql.append(upsert("line_balance_analyses", {
            "id": stable_id("line-balance", factory_id, str(idx)),
            "factory_id": factory_id,
            "product_id": product_expr(factory_id, idx % 2),
            "line_id": f"{short}-LINE-{idx}",
            "analysis_date": Expr(f"NOW() - INTERVAL '{idx * 3} days'"),
            "takt_time_min": round(4.5 + idx, 2),
            "cycle_time_max": round(5.8 + idx, 2),
            "cycle_time_avg": round(4.9 + idx * 0.7, 2),
            "balance_rate": round(rate * 100, 2),
            "idle_time_total": round((1 - rate) * 18, 2),
            "workstation_count": 6 + idx,
            "is_balanced": rate >= 0.85,
            "workstation_details": sql_json([{"station": f"{short}-{n}", "load": round(rate - 0.08 + n * 0.02, 2)} for n in range(1, 5)], "json"),
            "bottleneck_station": f"{short}-LINE-{idx}-BN",
            "bottleneck_time": round(6.2 + idx, 2),
            "recommendations": sql_json(["拆分瓶颈动作", "增加并行工位", "RCC复核派工顺序"], "json"),
            "created_by": "seed_guard",
            "created_at": Expr(f"NOW() - INTERVAL '{idx * 3} days'"),
            "updated_at": Expr("NOW()"),
        }))

    for idx, operation in enumerate(operations[:4], start=1):
        sql.append(upsert("action_studies", {
            "id": stable_id("action-study", factory_id, str(idx)),
            "factory_id": factory_id,
            "product_id": product_expr(factory_id, idx % 2),
            "operation_name": operation,
            "station_id": station_expr(factory_id, idx - 1),
            "operator_id": f"OP-{short}-{200 + idx}",
            "study_date": Expr(f"NOW() - INTERVAL '{idx * 2} days'"),
            "method_type": "mtm",
            "recorded_by": f"IE-{short}-02",
            "motions": sql_json([
                {"motion": "reach", "distance_cm": 22 + idx, "time_units": 2},
                {"motion": "grasp", "distance_cm": 8, "time_units": 1},
                {"motion": "position", "distance_cm": 14, "time_units": 3},
            ]),
            "total_time_cycles": round(18 + idx * 2.4, 2),
            "analysis_result": sql_json({"method_improvement": "缩短取料距离并增加定位治具", "estimated_time_reduction": 8 + idx}),
            "duration_min": round(0.4 + idx * 0.08, 2),
            "energy_consumption": round(0.12 + idx * 0.03, 2),
            "fatigue_level": 2 + idx,
            "improvement_suggestion": "物料盒前移，减少转身与跨步。",
            "motion_analysis_result": sql_json({"waste_motion_count": idx, "ergonomic_risk": "medium" if idx > 2 else "low"}),
            "ergonomic_score": 88 - idx * 5,
            "recommended_improvement_suggestion": "改用双手对称动作并固定工具位置。",
            "is_optimized": idx % 2 == 0,
            "created_by": "seed_guard",
            "created_at": Expr(f"NOW() - INTERVAL '{idx * 2} days'"),
            "updated_at": Expr("NOW()"),
        }))

    for idx, operation in enumerate(operations[:3], start=1):
        standard = 10 + idx * 2
        saving = 1.5 + idx
        sql.append(upsert("method_studies", {
            "id": stable_id("method-study", factory_id, str(idx)),
            "factory_id": factory_id,
            "product_id": product_expr(factory_id, idx % 2),
            "original_operation": operation,
            "version": "v2026.08",
            "is_basement_method": idx == 1,
            "is_optimal_method": idx == 3,
            "description": f"{operation}方法改善对比",
            "old_method_description": "人工取放、单件流确认，等待时间偏长。",
            "improved_operation": "治具定位、批次校核、异常自动呼叫RCC。",
            "expected_time_saving_calculation_detail": sql_json({"saving_min": saving, "saving_pct": round(saving / standard * 100, 1), "proposed_method": "并行动作+治具定位"}),
            "action_sequence": sql_json([{"step": 1, "action": "备料定位"}, {"step": 2, "action": "双手同步作业"}, {"step": 3, "action": "自动校验"}]),
            "required_resources": sql_json([{"resource": "定位治具", "qty": 1}, {"resource": "扫码枪", "qty": 1}]),
            "setup_time_min": 3.0 + idx,
            "cycle_time_min": standard - saving,
            "total_standard_time_min": standard,
            "validity_start": Expr("CURRENT_DATE - INTERVAL '15 days'"),
            "validity_end": Expr("CURRENT_DATE + INTERVAL '180 days'"),
            "approved_by": "IE主管",
            "status": "implemented" if idx == 3 else "approved",
            "expected_time_saving_min": saving,
            "cost_impact": -round(1200 * saving, 2),
            "implementation_status": "done" if idx == 3 else "pilot",
            "implementer_id": f"IE-{short}-03",
            "implementation_date": Expr(f"NOW() - INTERVAL '{idx * 4} days'"),
            "verification_result": "节拍稳定，等待时间下降。",
            "created_by": "seed_guard",
            "created_at": Expr(f"NOW() - INTERVAL '{idx * 6} days'"),
            "updated_at": Expr("NOW()"),
        }))

    for idx in range(1, 4):
        sql.append(upsert("work_cell_layouts", {
            "id": stable_id("work-cell", factory_id, str(idx)),
            "factory_id": factory_id,
            "work_cell_id": f"{short}-CELL-{idx}",
            "product_family_id": "智能装配" if short == "ELEC" else "精密模具",
            "layout_diagram_url": f"/static/demo/{short.lower()}-cell-{idx}.png",
            "material_flow_path": sql_json(["来料", "备料", "加工", "检验", "入库"], "json"),
            "operator_movement_path": sql_json(["取料", "作业", "扫码", "放行"], "json"),
            "takt_time_alignment": "aligned" if idx != 2 else "watch",
            "storage_location_type": "line_side",
            "description": f"{label}工作单元{idx}，按日节拍释放工单。",
            "created_by": "seed_guard",
            "created_at": Expr(f"NOW() - INTERVAL '{idx * 5} days'"),
            "updated_at": Expr("NOW()"),
        }))

    for idx in range(1, 5):
        sql.append(upsert("kanban_systems", {
            "id": stable_id("kanban", factory_id, str(idx)),
            "factory_id": factory_id,
            "kanban_id": f"KB-{short}-{idx:03d}",
            "kanban_type": "withdrawal" if idx % 2 else "production",
            "upstream_station": station_expr(factory_id, max(0, idx - 1)),
            "downstream_station": station_expr(factory_id, idx),
            "product_id": product_expr(factory_id, idx % 2),
            "part_number": f"MAT-{short}-{idx:03d}",
            "min_stock_level": 80,
            "max_stock_level": 240,
            "max_card_count": 6,
            "current_card_count": 3 + idx % 3,
            "safety_stock_level": 2,
            "card_status": "available" if idx != 4 else "empty",
            "last_used_at": Expr(f"NOW() - INTERVAL '{idx} hours'"),
            "reorder_quantity": 120,
            "lead_time_days": 2 + idx % 2,
            "trigger_rule_type": "min_max",
            "min_max_stock_levels_detail": sql_json({"min": 80, "max": 240, "reorder": 120}),
            "status": "active" if idx != 4 else "empty",
            "created_by": "seed_guard",
            "created_at": Expr(f"NOW() - INTERVAL '{idx * 3} days'"),
            "updated_at": Expr("NOW()"),
        }))

    for idx, base in enumerate([86, 78, 91, 83], start=1):
        sql.append(upsert("five_s_audits", {
            "id": stable_id("5s", factory_id, str(idx)),
            "factory_id": factory_id,
            "work_center_id": f"{short}-WC-{idx}",
            "audit_date": Expr(f"NOW() - INTERVAL '{idx * 4} days'"),
            "auditor_id": f"IE-{short}-5S",
            "seiri_score": base,
            "seiton_score": max(60, base - 3),
            "seiso_score": min(98, base + 2),
            "seiketsu_score": max(60, base - 4),
            "shitsuke_score": max(60, base - 2),
            "improvement_items": sql_json(["通道标识补强", "工装定置照片更新"], "json"),
            "next_audit_date": Expr("NOW() + INTERVAL '14 days'"),
            "total_score": base,
            "created_by": "seed_guard",
            "created_at": Expr(f"NOW() - INTERVAL '{idx * 4} days'"),
            "updated_at": Expr("NOW()"),
        }))

    return sql


def hr_equipment_tpm_sql(factory_id: str) -> list[str]:
    """Seed the operational records that make HR/TPM/RCC mutually traceable."""
    short = "ELEC" if factory_id == "FAC_ELEC_DEMO_2026" else "MEC"
    label = "电子厂" if short == "ELEC" else "机械厂"
    engineer_specs = [
        ("01", "设备工程师", "白班", "L5", ["OEE", "TPM", "PLC"]),
        ("02", "设备工程师", "夜班", "L4", ["TPM", "EQ-MNT", "安全"]),
    ]
    sql: list[str] = []

    for code, position, shift, level, tags in engineer_specs:
        employee_id = stable_id("equipment-engineer", factory_id, code)
        employee_code = f"{short}-EQ-{code}"
        sql.append(upsert("hr_employees", {
            "id": employee_id,
            "factory_id": factory_id,
            "employee_code": employee_code,
            "name": ("陈设备" if short == "ELEC" else "李设备") + code,
            "gender": "男" if code == "01" else "女",
            "department": "设备工程部",
            "station": "设备维护",
            "position": position,
            "shift": shift,
            "hire_date": Expr("CURRENT_DATE - INTERVAL '420 days'"),
            "status": "active",
            "skill_level": level,
            "phone": f"1390000{short[-1]}{code}",
            "expertise_tags": sql_json(tags),
            "remarks": f"{label} TPM/OEE责任人，负责设备状态、停机和维护闭环。",
            "height_cm": 172.0 if code == "01" else 165.0,
            "weight_kg": 68.0 if code == "01" else 55.0,
            "updated_at": Expr("NOW()"),
        }))
        for skill_code, skill_level in [("EQ-MNT", level), ("PLC", "L4" if code == "01" else "L3")]:
            sql.append(upsert("hr_employee_skills", {
                "id": stable_id("equipment-engineer-skill", factory_id, code, skill_code),
                "hr_employee_id": employee_id,
                "skill_id": Expr(f"(SELECT id FROM skills WHERE code={q(skill_code)} LIMIT 1)"),
                "level": skill_level,
                "certified_date": Expr("CURRENT_DATE - INTERVAL '180 days'"),
                "expiry_date": Expr("CURRENT_DATE + INTERVAL '185 days'"),
                "updated_at": Expr("NOW()"),
            }))

    # Repair the legacy demo factory key and connect operators to the current HR roster.
    sql.extend([
        "UPDATE operators SET factory_id='FAC_MECH_001', employee_id='MEC-' || LPAD(SUBSTRING(employee_id FROM 'EMP-M([0-9]+)-DEMO_2026'), 4, '0') WHERE factory_id='FAC_MECH_DEMO_2026';",
        "UPDATE operators SET employee_id='ELEC-' || LPAD(SUBSTRING(employee_id FROM 'EMP-E([0-9]+)-DEMO_2026'), 4, '0') WHERE factory_id='FAC_ELEC_DEMO_2026' AND employee_id LIKE 'EMP-E%-DEMO_2026';",
        "DELETE FROM attendance WHERE factory_id IN ('FAC_ELEC_DEMO_2026','FAC_MECH_DEMO_2026','FAC_MECH_001');",
        """
        WITH ranked AS (
            SELECT o.id, o.factory_id, ROW_NUMBER() OVER (PARTITION BY o.factory_id ORDER BY o.employee_id) AS rn
            FROM operators o
            WHERE o.factory_id IN ('FAC_ELEC_DEMO_2026', 'FAC_MECH_001')
        )
        INSERT INTO attendance (id, factory_id, operator_id, date, check_in, check_out, shift, status, created_at)
        SELECT md5(factory_id || id || CURRENT_DATE::text), factory_id, id, CURRENT_DATE::text,
               CASE WHEN rn % 5 IN (0, 1) THEN NULL
                    WHEN rn % 5 = 2 THEN CURRENT_DATE + TIME '08:20'
                    ELSE CURRENT_DATE + TIME '07:50' END,
               CASE WHEN rn % 5 IN (0, 1) THEN NULL ELSE CURRENT_DATE + TIME '19:00' END,
               CASE WHEN rn % 2 = 0 THEN '夜班' ELSE '白班' END,
               CASE rn % 5 WHEN 0 THEN 'rest' WHEN 1 THEN 'leave' WHEN 2 THEN 'late' ELSE 'present' END,
               NOW()
        FROM ranked;
        """,
    ])

    # Bind every asset to one of the two engineers and make actionable statuses visible first.
    sql.append("""
    WITH owners AS (
        SELECT id, factory_id, ROW_NUMBER() OVER (PARTITION BY factory_id ORDER BY employee_code) AS rn
        FROM hr_employees
        WHERE department='设备工程部' AND position='设备工程师'
    ), ranked_equipment AS (
        SELECT id, factory_id, ROW_NUMBER() OVER (PARTITION BY factory_id ORDER BY equipment_code) AS rn
        FROM equipment
    )
    UPDATE equipment e
       SET responsible_engineer_id = o.id,
           updated_at = NOW()
      FROM ranked_equipment re
      JOIN owners o ON o.factory_id = re.factory_id AND o.rn = ((re.rn - 1) % 2) + 1
     WHERE e.id = re.id;
    """)
    sql.append("""
    WITH ranked AS (
        SELECT id, ROW_NUMBER() OVER (PARTITION BY factory_id ORDER BY equipment_code) AS rn
        FROM equipment
        WHERE factory_id IN ('FAC_ELEC_DEMO_2026', 'FAC_MECH_001')
    )
    UPDATE equipment e SET status = CASE WHEN r.rn = 1 THEN 'broken' WHEN r.rn = 2 THEN 'maintenance' ELSE e.status END,
                           updated_at = NOW()
      FROM ranked r WHERE e.id = r.id;
    """)

    maintenance = [
        ("01", 0, "emergency", "high", "open", "主轴振动异常，已触发故障预警。", 2, 90),
        ("02", 1, "corrective", "medium", "in_progress", "冷却系统压力偏低，正在更换滤芯。", 1, 55),
        ("03", 2, "preventive", "low", "completed", "按周期完成润滑与精度点检。", -4, 35),
    ]
    for code, eq_offset, mtype, priority, status, description, day_offset, downtime in maintenance:
        order_id = stable_id("maintenance-order", factory_id, code)
        engineer_id = stable_id("equipment-engineer", factory_id, "01" if code != "02" else "02")
        start_expr = Expr(f"NOW() - INTERVAL '{abs(day_offset)} days'") if day_offset < 0 else Expr("NOW() + INTERVAL '2 hours'")
        end_expr = Expr(f"NOW() - INTERVAL '{abs(day_offset)} days' + INTERVAL '2 hours'") if status == "completed" else None
        sql.append(upsert("maintenance_orders", {
            "id": order_id,
            "order_code": f"MO-{short}-{code}-202608",
            "factory_id": factory_id,
            "equipment_id": equipment_id_expr(factory_id, eq_offset),
            "maintenance_type": mtype,
            "order_type": mtype,
            "priority": priority,
            "status": status,
            "description": description,
            "planned_date": start_expr,
            "scheduled_start": start_expr,
            "scheduled_end": end_expr or Expr("NOW() + INTERVAL '4 hours'"),
            "started_at": start_expr if status in ("in_progress", "completed") else None,
            "actual_start": start_expr if status in ("in_progress", "completed") else None,
            "completed_at": end_expr,
            "actual_end": end_expr,
            "assigned_to": engineer_id,
            "result_summary": "已恢复设备稳定运行" if status == "completed" else None,
            "downtime_minutes": downtime,
            "created_by": "seed_guard",
            "created_at": Expr("NOW() - INTERVAL '2 days'"),
            "updated_at": Expr("NOW()"),
        }))

    for code, eq_offset, freq, due_offset in [("01", 0, 7, -1), ("02", 1, 14, 3), ("03", 2, 30, 18)]:
        sql.append(upsert("maintenance_plans", {
            "id": stable_id("maintenance-plan", factory_id, code),
            "plan_code": f"PM-{short}-{code}-202608",
            "factory_id": factory_id,
            "equipment_id": equipment_id_expr(factory_id, eq_offset),
            "plan_type": "preventive",
            "plan_name": f"{label}设备{code}点检保养",
            "frequency": f"每{freq}天",
            "frequency_days": freq,
            "next_run_date": Expr(f"CURRENT_DATE + INTERVAL '{due_offset} days'"),
            "next_due_at": Expr(f"NOW() + INTERVAL '{due_offset} days'"),
            "last_run_date": Expr(f"CURRENT_DATE - INTERVAL '{freq} days'"),
            "last_executed_at": Expr(f"NOW() - INTERVAL '{freq} days'"),
            "checklist": "润滑、点检、精度、急停、安全防护",
            "description": "TPM周期保养计划，逾期进入RCC预警。",
            "is_active": True,
            "created_by": "seed_guard",
            "created_at": Expr("NOW() - INTERVAL '10 days'"),
            "updated_at": Expr("NOW()"),
        }))

    for code, eq_offset, category, duration, day_offset in [
        ("01", 0, "breakdown", 90, 1), ("02", 1, "maintenance", 55, 2), ("03", 2, "material_shortage", 25, 3)
    ]:
        sql.append(upsert("equipment_downtime", {
            "id": stable_id("equipment-downtime", factory_id, code),
            "equipment_id": equipment_id_expr(factory_id, eq_offset),
            "factory_id": factory_id,
            "start_time": Expr(f"NOW() - INTERVAL '{day_offset} days'"),
            "end_time": Expr(f"NOW() - INTERVAL '{day_offset} days' + INTERVAL '{duration} minutes'"),
            "duration_minutes": duration,
            "downtime_category": category,
            "reason_code": "主轴振动" if category == "breakdown" else "TPM-PLAN" if category == "maintenance" else "MAT-HOLD",
            "description": "设备故障/维护/待料记录，供OEE和RCC联动。",
            "reported_by": stable_id("equipment-engineer", factory_id, "01"),
            "created_by": "seed_guard",
            "created_at": Expr(f"NOW() - INTERVAL '{day_offset} days'")
        }))

    # Recent reports make the OEE calculation reflect a real operating pulse.
    for idx in range(1, 7):
        sql.append(upsert("production_reports", {
            "id": stable_id("oee-production-report", factory_id, str(idx)),
            "report_code": f"PR-OEE-{short}-{idx:02d}-202608",
            "factory_id": factory_id,
            "work_order_id": work_order_id_expr(factory_id, idx % 3),
            "station_id": station_expr(factory_id, idx % 3),
            "good_qty": 2400 - idx * 25,
            "defect_qty": 8 + idx % 3,
            "scrap_qty": 4,
            "report_type": "normal",
            "shift": "day" if idx % 2 else "night",
            "operator_id": f"{short}-OP-{idx:03d}",
            "operation_seq": idx,
            "operation_name": "设备产出报工",
            "machine_id": equipment_id_expr(factory_id, idx % 3),
            "start_time": Expr(f"NOW() - INTERVAL '{idx} hours'"),
            "end_time": Expr(f"NOW() - INTERVAL '{idx} hours' + INTERVAL '50 minutes'"),
            "cycle_time_sec": 7.5 + idx * 0.2,
            "quality_check_passed": True,
            "created_by": "virtual_factory_agent",
            "created_at": Expr(f"NOW() - INTERVAL '{idx} hours'"),
            "updated_at": Expr("NOW()"),
        }))
    return sql


def im_group_sql(factory_id: str) -> list[str]:
    short = "ELEC" if factory_id == "FAC_ELEC_DEMO_2026" else "MECH"
    suffix = factory_id[-4:].replace("_", "")
    groups = [
        ("rcc-command", "RCC指挥调度群", "厂长/RCC/计划/生产/设备/质量联动，承接指挥中心决策和异常升级。", "rcc", "#1677ff"),
        ("prod-exception", "生产异常处理群", "报工异常、设备停机、物料短缺、安灯呼叫统一在 Chatbot 内闭环。", "exception", "#fa8c16"),
        ("quality-linkage", "质量联动群", "IQC/IPQC/OQC/SPC/8D 质量问题拉通生产、IE 和仓储。", "quality", "#722ed1"),
    ]
    sql: list[str] = []
    for idx, (code, name, desc, group_type, color) in enumerate(groups, start=1):
        gid = f"im-{suffix}-{code}"
        sql.append(upsert("im_groups", {
            "id": gid,
            "factory_id": factory_id,
            "name": f"{short}-{name}",
            "description": desc,
            "group_type": group_type,
            "org_node_id": code,
            "owner_id": "chatbot",
            "avatar_color": color,
            "is_active": True,
            "created_at": Expr(f"NOW() - INTERVAL '{idx} hours'"),
            "updated_at": Expr("NOW()"),
        }))
        sql.append(upsert("im_messages", {
            "id": f"{gid}-welcome",
            "group_id": gid,
            "sender_id": "system",
            "sender_name": "系统",
            "msg_type": "system",
            "content": f"{short}-{name}已建立，Chatbot 可把任务、预警和RCC决策同步到本群。",
            "command_type": "group_bootstrap",
            "command_payload": sql_json({"factory_id": factory_id, "group_type": group_type}),
            "reply_to_id": None,
            "created_at": Expr(f"NOW() - INTERVAL '{idx} hours'"),
        }))
    return sql


def traceability_sql(factory_id: str) -> list[str]:
    short = "ELEC" if factory_id == "FAC_ELEC_DEMO_2026" else "MECH"
    rows = [
        ("fg", "finished", "FG", "pass", 2),
        ("semi", "semi_finished", "SF", "pass", 1),
        ("raw", "raw_material", "RM", "pass", 0),
    ]
    item_codes = {
        key: f"TRACE-{short}-{code}-001"
        for key, _item_type, code, _quality, _offset in rows
    }
    sql: list[str] = []
    for key, item_type, code, quality, offset in rows:
        sql.append(upsert("item_traceability", {
            "id": stable_id("item-trace", factory_id, key),
            "item_code": item_codes[key],
            "item_type": item_type,
            "factory_id": factory_id,
            "work_order_id": work_order_id_expr(factory_id, offset),
            "product_id": product_id_expr(factory_id, offset % 2),
            "material_batch_id": f"BATCH-{short}-202608-{offset + 1:02d}",
            "material_supplier_id": f"SUP-{short}-A",
            "station_id": station_expr(factory_id, offset),
            "equipment_id": equipment_id_expr(factory_id, offset),
            "operator_id": f"OP-{short}-{300 + offset}",
            "quality_check_result": quality,
            "serial_number": f"SN-{short}-20260801-{offset + 1:04d}",
            "next_item_code": item_codes["semi"] if key == "raw" else item_codes["fg"] if key == "semi" else None,
            "inspection_record_id": None,
            "metadata": sql_json({
                "trace_stage": key,
                "source": "demo_module_coverage_seed",
                "links": ["work_order", "product", "station", "equipment", "quality"],
            }),
            "created_by": "seed_guard",
            "created_at": Expr(f"NOW() - INTERVAL '{6 - offset} hours'"),
            "updated_at": Expr("NOW()"),
        }, conflict="item_code"))
    return sql


def build_sql(factories: list[str]) -> str:
    labels = {"FAC_ELEC_DEMO_2026": "电子厂", "FAC_MECH_001": "机械厂"}
    statements = ["BEGIN;", *base_schema_sql()]
    statements.append("UPDATE plans SET factory_id='FAC_MECH_001' WHERE factory_id='FAC_MECH_DEMO_2026';")
    statements.append("UPDATE pp_plans SET factory_id='FAC_MECH_001' WHERE factory_id='FAC_MECH_DEMO_2026';")
    for factory_id in factories:
        label = labels.get(factory_id, factory_id)
        statements.extend(rcc_sql(factory_id, label))
        statements.extend(warehouse_plan_sql(factory_id, label))
        statements.extend(routing_sql(factory_id))
        statements.extend(ie_sql(factory_id, label))
        statements.extend(hr_equipment_tpm_sql(factory_id))
        statements.extend(im_group_sql(factory_id))
        statements.extend(traceability_sql(factory_id))
    statements.append("COMMIT;")
    return "\n".join(statements)


def run_psql(sql: str) -> None:
    cmd = ["docker", "exec", "-i", PG_CONTAINER, "psql", "-U", PG_USER, "-d", PG_DB, "-v", "ON_ERROR_STOP=1"]
    proc = subprocess.run(cmd, input=sql, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr)
        raise SystemExit(proc.returncode)
    print(proc.stdout)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed demo module coverage for mock factories")
    parser.add_argument("--factory", action="append", default=[], help="Factory id to seed")
    parser.add_argument("--print-sql", action="store_true", help="Print SQL without executing")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    factories = args.factory or DEFAULT_FACTORIES
    sql = build_sql(factories)
    if args.print_sql:
        print(sql)
        return 0
    run_psql(sql)
    print("Demo module coverage seed completed for: " + ", ".join(factories))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
