#!/usr/bin/env python3
"""Deployment data guard for EngHub.

The guard records row-count watermarks before deployment and verifies them after
deployment. It is intentionally dependency-free and talks to Postgres through
the running Docker container, so it can run on the production host.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

PG_CONTAINER = os.getenv("PG_CONTAINER", "docker-postgres-1")
PG_USER = os.getenv("PG_USER", "enghub")
PG_DB = os.getenv("PG_DB", "enghub")

DEFAULT_FACTORIES = [
    f.strip()
    for f in os.getenv("DATA_GUARD_FACTORIES", "FAC_ELEC_DEMO_2026,FAC_MECH_001").split(",")
    if f.strip()
]

TABLES: dict[str, dict[str, Any]] = {
    "users": {"min": 1, "max_drop_pct": 0.0},
    "factories": {"min": 1, "max_drop_pct": 0.0},
    "products": {"min": 1, "max_drop_pct": 0.05},
    "work_orders": {"min": 1, "factory_min": 1, "max_drop_pct": 0.05},
    "sales_orders": {"min": 1, "factory_min": 1, "max_drop_pct": 0.05},
    "pp_plans": {"min": 1, "factory_min": 1, "max_drop_pct": 0.05},
    "production_reports": {"min": 1, "factory_min": 1, "max_drop_pct": 0.05},
    "quality_inspections": {"min": 1, "factory_min": 1, "max_drop_pct": 0.0},
    "defect_records": {"min": 1, "factory_min": 1, "max_drop_pct": 0.0},
    "qms_spc_points": {"min": 1, "factory_min": 1, "max_drop_pct": 0.0},
    "qms_8d_reports": {"min": 1, "factory_min": 1, "max_drop_pct": 0.0},
    "inventory": {"min": 1, "factory_min": 1, "max_drop_pct": 0.05},
    "equipment": {"min": 1, "factory_min": 1, "max_drop_pct": 0.05},
    "stations": {"min": 1, "factory_min": 1, "max_drop_pct": 0.05},
    "hr_employees": {"min": 5, "factory_min": 1, "max_drop_pct": 0.05},
    "skills": {"min": 5, "max_drop_pct": 0.05},
    "work_order_templates": {"min": 1, "factory_min": 1, "max_drop_pct": 0.05},
    "routing_templates": {"min": 1, "factory_min": 0, "max_drop_pct": 0.05},
    "aps_schedules": {"min": 1, "factory_min": 1, "max_drop_pct": 0.10},
    "aps_schedule_tasks": {"min": 1, "max_drop_pct": 0.10},
    "standard_operation_times": {"min": 1, "factory_min": 1, "max_drop_pct": 0.05},
}


def _validate_ident(value: str) -> str:
    if not IDENT_RE.match(value):
        raise ValueError(f"Unsafe SQL identifier: {value}")
    return value


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def psql_scalar(sql: str) -> str:
    cmd = [
        "docker",
        "exec",
        PG_CONTAINER,
        "psql",
        "-U",
        PG_USER,
        "-d",
        PG_DB,
        "-t",
        "-A",
        "-q",
        "-c",
        sql,
    ]
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"psql failed: {sql}")
    return proc.stdout.strip()


def table_exists(table: str) -> bool:
    table = _validate_ident(table)
    sql = (
        "SELECT 1 FROM information_schema.tables "
        f"WHERE table_schema='public' AND table_name={_sql_string(table)};"
    )
    return psql_scalar(sql) == "1"


def has_column(table: str, column: str) -> bool:
    table = _validate_ident(table)
    column = _validate_ident(column)
    sql = (
        "SELECT 1 FROM information_schema.columns "
        f"WHERE table_schema='public' AND table_name={_sql_string(table)} "
        f"AND column_name={_sql_string(column)};"
    )
    return psql_scalar(sql) == "1"


def count_rows(table: str, factory_id: str | None = None) -> int:
    table = _validate_ident(table)
    if factory_id is None:
        sql = f"SELECT count(*) FROM {table};"
    else:
        sql = f"SELECT count(*) FROM {table} WHERE factory_id={_sql_string(factory_id)};"
    raw = psql_scalar(sql)
    return int(raw or 0)


def take_snapshot(factories: list[str]) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "version": 1,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "pg_container": PG_CONTAINER,
        "pg_db": PG_DB,
        "factories": factories,
        "tables": {},
        "factory_tables": {},
    }

    for table, cfg in TABLES.items():
        if not table_exists(table):
            snapshot["tables"][table] = {"exists": False, "count": 0}
            continue

        total = count_rows(table)
        snapshot["tables"][table] = {"exists": True, "count": total, "min": cfg.get("min", 0)}

        if cfg.get("factory_min") is not None and has_column(table, "factory_id"):
            snapshot["factory_tables"][table] = {}
            for factory_id in factories:
                snapshot["factory_tables"][table][factory_id] = count_rows(table, factory_id)

    return snapshot


def _baseline_count(baseline: dict[str, Any], table: str) -> int | None:
    item = baseline.get("tables", {}).get(table)
    if not isinstance(item, dict) or not item.get("exists", False):
        return None
    return int(item.get("count") or 0)


def verify_snapshot(
    current: dict[str, Any],
    baseline: dict[str, Any] | None,
    factories: list[str],
) -> tuple[list[str], list[str]]:
    failures: list[str] = []
    warnings: list[str] = []

    for table, cfg in TABLES.items():
        item = current["tables"].get(table, {})
        count = int(item.get("count") or 0)
        min_rows = int(cfg.get("min") or 0)

        if not item.get("exists", False):
            failures.append(f"{table}: table missing")
            continue

        if count < min_rows:
            failures.append(f"{table}: {count} rows, minimum {min_rows}")

        if baseline:
            before = _baseline_count(baseline, table)
            if before is not None and before > 0:
                max_drop_pct = float(cfg.get("max_drop_pct", 0.05))
                floor = int(before * (1 - max_drop_pct))
                if count < floor:
                    failures.append(
                        f"{table}: dropped from {before} to {count} "
                        f"(allowed drop {max_drop_pct:.0%})"
                    )

        factory_min = cfg.get("factory_min")
        if factory_min is None:
            continue

        by_factory = current.get("factory_tables", {}).get(table, {})
        for factory_id in factories:
            if factory_id not in by_factory:
                warnings.append(f"{table}/{factory_id}: no factory_id count available")
                continue
            factory_count = int(by_factory.get(factory_id) or 0)
            if factory_count < int(factory_min):
                failures.append(
                    f"{table}/{factory_id}: {factory_count} rows, minimum {factory_min}"
                )

            if baseline:
                before_factory = (
                    baseline.get("factory_tables", {})
                    .get(table, {})
                    .get(factory_id)
                )
                if before_factory is not None and int(before_factory) > 0:
                    max_drop_pct = float(cfg.get("max_drop_pct", 0.05))
                    floor = int(int(before_factory) * (1 - max_drop_pct))
                    if factory_count < floor:
                        failures.append(
                            f"{table}/{factory_id}: dropped from {before_factory} to {factory_count} "
                            f"(allowed drop {max_drop_pct:.0%})"
                        )

    return failures, warnings


def write_json(path: str, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def load_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def print_summary(snapshot: dict[str, Any]) -> None:
    print(f"Data guard snapshot: {snapshot['checked_at']}")
    for table in sorted(snapshot["tables"]):
        item = snapshot["tables"][table]
        marker = "ok" if item.get("exists") else "missing"
        print(f"  {table}: {marker}, rows={item.get('count', 0)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="EngHub deployment data guard")
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("snapshot", "verify", "report"):
        p = sub.add_parser(name)
        p.add_argument("--factory", action="append", default=[], help="Factory id to guard")
        p.add_argument("--output", help="Write current snapshot to this JSON file")
        p.add_argument("--baseline", help="Compare against a previous snapshot JSON")

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    factories = args.factory or DEFAULT_FACTORIES
    current = take_snapshot(factories)

    if args.output:
        write_json(args.output, current)

    if args.command == "snapshot":
        print_summary(current)
        if args.output:
            print(f"Snapshot written: {args.output}")
        return 0

    baseline = load_json(args.baseline) if args.baseline else None
    failures, warnings = verify_snapshot(current, baseline, factories)

    if args.command == "report":
        print_summary(current)
        return 0

    for warning in warnings:
        print(f"WARN: {warning}")
    if failures:
        print("DATA GUARD FAILED", file=sys.stderr)
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        if args.output:
            print(f"Current snapshot written: {args.output}", file=sys.stderr)
        return 1

    print("DATA GUARD PASSED")
    if args.output:
        print(f"Current snapshot written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
