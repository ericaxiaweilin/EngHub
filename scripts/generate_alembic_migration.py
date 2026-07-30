#!/usr/bin/env python3
"""Generate Alembic migration from current SQLAlchemy models."""

import os
import sys
from alembic import context
from sqlalchemy import create_engine
from dotenv import load_dotenv

load_dotenv()
db_url = os.getenv("DATABASE_URL")
if not db_url:
    print("ERROR: DATABASE_URL not set in .env file")
    sys.exit(1)

print(f"Generating Alembic migration using DB: {db_url}")

context.config.set_main_option("sqlalchemy.url", db_url)
context.config.attributes.setdefault('configure_logger', True)

from database.models import Base  # noqa: F401

from alembic.autoscribe import autoscribe

engine = create_engine(db_url, echo=False)

with engine.begin() as conn:
    target_metadata = Base.metadata
    revisions = autoscribe.get_autorevision(conn, target_metadata)
    
    if revisions.needs_migration:
        print("✅ Migration needed - changes detected:")
        for change in list(revisions.up)[:20]:  # Limit output
            print(f"   + {change}")
        if len(revisions.up) > 20:
            print(f"   ... ({len(revisions.up)} total changes)")
    else:
        print("ℹ No schema changes detected - database already in sync with models")

desc = sys.argv[1] if len(sys.argv) > 1 else "schema sync"
print(f"\nTo generate actual migration file, run:")
print(f'  alembic revision --autogenerate -m "{desc}"')
print(f"Then apply with:  alembic head")