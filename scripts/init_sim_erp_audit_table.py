"""
Initialize the Sim-ERP audit table for the current DATABASE_URL.
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine

from database.models import SimERPAuditLog


def normalize_database_url(database_url: str) -> str:
    if database_url.startswith("sqlite+aiosqlite:///"):
        return database_url.replace("sqlite+aiosqlite:///", "sqlite:///")
    if database_url.startswith("postgresql+asyncpg://"):
        return database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://")
    return database_url


def main() -> None:
    database_url = os.getenv("DATABASE_URL", "sqlite:///./test.db")
    engine = create_engine(normalize_database_url(database_url))
    SimERPAuditLog.__table__.create(bind=engine, checkfirst=True)
    print("sim_erp_audit_logs table is ready")


if __name__ == "__main__":
    main()
