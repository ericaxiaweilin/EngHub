#!/usr/bin/env python3
"""Apply schema fixes using synchronous psycopg2 connection (avoiding async issues)."""

import os
import sys
import psycopg2
from dotenv import load_dotenv

load_dotenv()
db_url = os.getenv("DATABASE_URL")
if not db_url:
    print("ERROR: DATABASE_URL not set in .env file")
    sys.exit(1)

# Convert asyncpg URL to psycopg2 format (replace driver name)
psycopg2_url = db_url.replace("+asyncpg", "")
print(f"Connecting via psycopg2: {psycopg2_url}")

try:
    conn = psycopg2.connect(psycopg2_url)
    cur = conn.cursor()
    
    schema_fixes = [
        ("inventory", ["expiry_date TIMESTAMPTZ", "storage_location VARCHAR(255)", "qualified_status VARCHAR(20)", "unit_cost DECIMAL(10,2)"]),
        ("work_orders", ["current_stage VARCHAR(50)", "in_progress_status BOOLEAN DEFAULT FALSE", "partial_completion_percentage DECIMAL(5,2) DEFAULT 0.0", "next_station_id VARCHAR(50)", "assigned_to VARCHAR(50)", "work_center VARCHAR(100)", "routing_template_id VARCHAR(50)", "remark TEXT", "released_by VARCHAR(50)", "completed_by VARCHAR(50)"]),
        ("production_reports", ["station_code VARCHAR(50)", "operation_name VARCHAR(100)"]),
        ("products", ["uom VARCHAR(20)"])
    ]
    
    success_count = 0
    failed = []
    
    for table_name, column_defs in schema_fixes:
        col_defs = ", ".join(f"ADD COLUMN IF NOT EXISTS {col}" for col in column_defs)
        sql = f"ALTER TABLE {table_name} {col_defs};"
        
        try:
            cur.execute(sql)
            conn.commit()
            print(f"✓ Applied fixes to '{table_name}' ({len(column_defs)} column(s))")
            success_count += 1
        except Exception as e:
            print(f"✗ Failed on '{table_name}': {e}")
            failed.append((table_name, str(e)))
    
    cur.close()
    conn.close()
    
    print(f"\nSummary: {success_count}/{len(schema_fixes)} tables updated")
    if not failed:
        print("All schema fixes applied successfully!")
        sys.exit(0)
    else:
        print(f"Failed: {[f[0] for f in failed]}")
        sys.exit(1)
        
except Exception as e:
    print(f"Failed to connect to database: {e}")
    sys.exit(1)