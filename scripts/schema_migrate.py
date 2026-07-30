"""Apply and verify EngHub-owned database migrations.

The shared database has its own migration_history table. EngHub deliberately
uses an isolated ledger so deployments cannot silently mistake another
application's migration history for its own.
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


MIGRATIONS = ROOT / "database" / "migrations"
CONTRACT = ROOT / "database" / "schema_contract.json"
MIN_MANAGED_VERSION = 42


async def migrate() -> None:
    async with db_config.engine.begin() as connection:
        await connection.execute(text("""
            CREATE TABLE IF NOT EXISTS enghub_schema_migrations (
                migration_name VARCHAR(255) PRIMARY KEY,
                checksum VARCHAR(64) NOT NULL,
                applied_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """))
        applied = dict((await connection.execute(text(
            "SELECT migration_name, checksum FROM enghub_schema_migrations"
        ))).all())
        for path in sorted(MIGRATIONS.glob("*.sql")):
            if path.name.endswith(" 2.sql"):
                continue
            try:
                version = int(path.name.split("_", 1)[0])
            except ValueError:
                continue
            if version < MIN_MANAGED_VERSION:
                continue
            sql = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql.encode()).hexdigest()
            if path.name in applied:
                if applied[path.name] != checksum:
                    raise RuntimeError(f"applied migration checksum changed: {path.name}")
                continue
            print(f"applying migration: {path.name}", flush=True)
            raw = await connection.get_raw_connection()
            await raw.driver_connection.execute(sql)
            await connection.execute(
                text("""
                    INSERT INTO enghub_schema_migrations(migration_name, checksum)
                    VALUES (:name, :checksum)
                """),
                {"name": path.name, "checksum": checksum},
            )


async def verify() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    missing: list[str] = []
    async with db_config.engine.connect() as connection:
        rows = (await connection.execute(text("""
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
        """))).all()
    actual: dict[str, set[str]] = {}
    for table, column in rows:
        actual.setdefault(table, set()).add(column)
    for table, columns in contract.items():
        if table not in actual:
            missing.append(f"table:{table}")
            continue
        for column in columns:
            if column not in actual[table]:
                missing.append(f"column:{table}.{column}")
    if missing:
        raise RuntimeError("EngHub schema contract failed: " + ", ".join(missing))


async def main() -> None:
    await migrate()
    await verify()
    await db_config.close()
    print("EngHub schema migration and contract verification passed")


if __name__ == "__main__":
    asyncio.run(main())
