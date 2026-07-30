#!/usr/bin/env python3
"""Apply schema fixes to add missing columns referenced in ORM models."""

import os
import sys
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()
db_url = os.getenv("DATABASE_URL")
if not db_url:
    print("ERROR: DATABASE_URL not set in .env file")
    sys.exit(1)

print(f"Connecting to database: {db_url}")
engine = create_engine(db_url, echo=False)

schema_fixes = [
    ("inventory", ["expiry_date TIMESTAMPTZ", "storage_location VARCHAR(255)", "qualified_status VARCHAR(20)", "unit_cost DECIMAL(10,2)"]),
    ("work_orders", ["current_stage VARCHAR(50)", "in_progress_status BOOLEAN DEFAULT FALSE", "partial_completion_percentage DECIMAL(5,2) DEFAULT 0.0", "next_station_id VARCHAR(50)", "assigned_to VARCHAR(50)", "work_center VARCHAR(100)", "routing_template_id VARCHAR(50)", "\"remark\" TEXT", "released_by VARCHAR(50)", "completed_by VARCHAR(50)"]),
    ("production_reports", ["station_code VARCHAR(50)", "operation_name VARCHAR(100)"]),
    ("products", ["uom VARCHAR(20)"])
]

success_count = 0
failed = []

for table_name, column_defs in schema_fixes:
    col_defs = ", ".join(f"ADD COLUMN IF NOT EXISTS {col}" for col in column_defs)
    sql = f"ALTER TABLE {table_name} {col_defs};"
    
    try:
        # Use raw connection for DDL (not session)
        with engine.connect() as conn:
            conn.execute(text(sql))
            conn.commit()
            print(f"✓ Applied fixes to '{table_name}' ({len(column_defs)} column(s))")
            success_count += 1
    except Exception as e:
        print(f"✗ Failed on '{table_name}': {e}")
        failed.append((table_name, str(e)))

print(f"\n{'='*60}")
print(f"Summary: {success_count}/{len(schema_fixes)} tables updated")
if failed:
    print(f"Failed: {[f[0] for f in failed]}")
else:
    print("All schema fixes applied successfully!")
print(f"{'='*60}")

sys.exit(0 if not failed else 1)