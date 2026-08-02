"""
Pure serialization helpers for Sim-ERP audit responses.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List

from .models import AuditRecord


def record_to_summary_payload(record: AuditRecord) -> Dict[str, Any]:
    return {
        "simulation_id": record.simulation_id,
        "final_status": record.arbiter_result.final_status,
        "legal_blocked": record.arbiter_result.legal_blocked,
        "created_at": record.created_at,
        "total_cost_delta": record.arbiter_result.total_cost_delta,
        "max_required_break_minutes": record.arbiter_result.max_required_break_minutes,
        "blocking_rules": [
            decision.rule_code for decision in record.arbiter_result.blocking_decisions
        ],
        "warnings": [decision.rule_code for decision in record.arbiter_result.warnings],
    }


def entity_to_summary_payload(entity: Any) -> Dict[str, Any]:
    return {
        "simulation_id": entity.simulation_id,
        "final_status": entity.final_status,
        "legal_blocked": entity.legal_blocked,
        "created_at": entity.created_at,
        "total_cost_delta": float(entity.total_cost_delta or Decimal("0")),
        "max_required_break_minutes": entity.max_required_break_minutes,
        "blocking_rules": [
            item["rule_code"] for item in entity.arbiter_result_payload.get("blocking_decisions", [])
        ],
        "warnings": [
            item["rule_code"] for item in entity.arbiter_result_payload.get("warnings", [])
        ],
    }


def entity_to_detail_payload(entity: Any) -> Dict[str, Any]:
    payload = entity_to_summary_payload(entity)
    payload.update(
        {
            "worker_ref": entity.worker_ref,
            "shift_id": entity.shift_id,
            "task_type": entity.task_type,
            "zone_id": entity.zone_id,
            "total_penalty_score": entity.total_penalty_score,
            "snapshot_payload": entity.snapshot_payload,
            "plugin_records_payload": entity.plugin_records_payload,
            "arbiter_result_payload": entity.arbiter_result_payload,
        }
    )
    return payload
