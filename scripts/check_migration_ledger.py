#!/usr/bin/env python3
"""核对迁移台账与仓库里的 .sql 文件是否对得上。

为什么要有这个：2026-10-11 审计发现台账 87 条里有 25 条**源文件不在仓库**
（已应用在生产库，但仓库里查无此文件）—— 意味着这个仓库重建不出生产库，
而这件事在长达数月里**没有任何地方会报出来**。没有告警的漂移就是会一直漂。

判据（三种，分开报，因为处理方式不同）：
  1. 台账有、仓库无  → 危险：新环境建不出这一段。必须要么找回文件，
     要么登记进 database/migrations/ledger_gaps.json（写明原因），否则退出码非 0。
  2. 两边都有但 sha256 不一致 → 危险：有人改过已应用的迁移。
     runner（schema_migrate.py）会在部署时 raise，这里提前报出来。
  3. 仓库有、台账无 → 只对 version >= MIN_MANAGED_VERSION 的报。
     低于阈值的是**故意不管**的（见 schema_migrate.MIN_MANAGED_VERSION），
     报出来是噪音 —— 那 44 个 001–041 就属于这一类。

用法：
    python3 scripts/check_migration_ledger.py            # 只报，按判据给退出码
    python3 scripts/check_migration_ledger.py --quiet     # 只给退出码和一行摘要
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from database.db_config import db_config  # noqa: E402
from scripts.schema_migrate import MIN_MANAGED_VERSION  # noqa: E402

MIGRATIONS = ROOT / "database" / "migrations"
GAPS = MIGRATIONS / "ledger_gaps.json"


def _version(name: str) -> int | None:
    try:
        return int(name.split("_", 1)[0])
    except ValueError:
        return None


def _load_accepted() -> dict:
    if not GAPS.exists():
        return {}
    data = json.loads(GAPS.read_text(encoding="utf-8"))
    return {g["name"]: g for g in data.get("gaps", [])}


async def main() -> int:
    quiet = "--quiet" in sys.argv
    accepted = _load_accepted()

    on_disk = {p.name: p for p in MIGRATIONS.glob("*.sql")}
    async with db_config.engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT migration_name, checksum FROM enghub_schema_migrations"
        ))).all()
    ledger = {r[0]: r[1] for r in rows}

    missing_file = sorted(n for n in ledger if n not in on_disk)
    drifted = sorted(
        n for n, c in ledger.items()
        if n in on_disk and hashlib.sha256(on_disk[n].read_bytes()).hexdigest() != c
    )
    unrecorded_managed = sorted(
        n for n in on_disk
        if n not in ledger and (_version(n) or 0) >= MIN_MANAGED_VERSION
    )

    unaccepted = [n for n in missing_file if n not in accepted]
    stale_accepted = [n for n in accepted if n not in missing_file]

    if not quiet:
        print(f"台账 {len(ledger)} 条 / 仓库 {len(on_disk)} 个 .sql "
              f"（阈值 version >= {MIN_MANAGED_VERSION}）\n")
        print(f"[1] 台账有、仓库无：{len(missing_file)} 条"
              f"（其中已登记 {len(missing_file) - len(unaccepted)} 条）")
        for n in missing_file:
            tag = "已登记" if n in accepted else "**未登记**"
            print(f"      {tag}  {n}")
        print(f"\n[2] 内容与台账 checksum 不一致：{len(drifted)} 条")
        for n in drifted:
            print(f"      {n}")
        print(f"\n[3] 仓库有、台账无（受管范围）：{len(unrecorded_managed)} 条")
        for n in unrecorded_managed:
            print(f"      {n}")
        if stale_accepted:
            print(f"\n[4] ledger_gaps.json 里登记了、但仓库里已经有文件了"
                  f"（可以删掉这条登记）：{len(stale_accepted)} 条")
            for n in stale_accepted:
                print(f"      {n}")

    problems = len(unaccepted) + len(drifted)
    if quiet:
        print(f"迁移台账核对：未登记缺口 {len(unaccepted)}、内容漂移 {len(drifted)}、"
              f"未记录受管文件 {len(unrecorded_managed)}")
    else:
        print(f"\n=== 需要处理 {problems} 项（未登记缺口 + 内容漂移）===")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
