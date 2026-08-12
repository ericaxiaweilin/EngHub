#!/usr/bin/env python3
"""
TPM Data Seeder
Populates TPM module with sample data for demonstration
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.db_config import async_engine
from sqlalchemy import text
import uuid


async def seed_equipment():
    """Seed equipment data"""
    
    equipment_data = [
        {
            "id": str(uuid.uuid4()),
            "factory_id": "demo-factory",
            "equipment_name": "CNC Machine A",
            "equipment_type": "CNC",
            "model": "HAAS VF-2",
            "serial_number": "SN-CNC-001",
            "location": "Workshop A - Line 1",
            "status": "OPERATIONAL",
            "oee": 82.5,
            "created_at": datetime.now()
        },
        {
            "id": str(uuid.uuid4()),
            "factory_id": "demo-factory",
            "equipment_name": "Injection Molder B",
            "equipment_type": "INJECTION",
            "model": "ARBURG 290",
            "serial_number": "SN-INJ-001",
            "location": "Workshop B - Line 2",
            "status": "OPERATIONAL",
            "oee": 75.2,
            "created_at": datetime.now()
        },
        {
            "id": str(uuid.uuid4()),
            "factory_id": "demo-factory",
            "equipment_name": "Conveyor System C",
            "equipment_type": "CONVEYOR",
            "model": "Dodge Flexco",
            "serial_number": "SN-CON-001",
            "location": "Assembly Line",
            "status": "MAINTENANCE",
            "oee": 0,
            "created_at": datetime.now()
        },
        {
            "id": str(uuid.uuid4()),
            "factory_id": "demo-factory",
            "equipment_name": "Robot Arm D",
            "equipment_type": "ROBOT",
            "model": "Fanuc M-20i",
            "serial_number": "SN-ROB-001",
            "location": "Packaging Line",
            "status": "OPERATIONAL",
            "oee": 88.3,
            "created_at": datetime.now()
        },
        {
            "id": str(uuid.uuid4()),
            "factory_id": "demo-factory",
            "equipment_name": "Laser Cutter E",
            "equipment_type": "LASER",
            "model": "Trumpf TruLaser",
            "serial_number": "SN-LAS-001",
            "location": "Workshop A - Line 2",
            "status": "DOWN",
            "oee": 0,
            "created_at": datetime.now()
        }
    ]
    
    async with async_engine.connect() as conn:
        for eq in equipment_data:
            await conn.execute(text("""
                INSERT INTO equipment (id, factory_id, equipment_name, equipment_type, model, 
                    serial_number, location, status, oee, created_at)
                VALUES (:id, :factory_id, :equipment_name, :equipment_type, :model,
                    :serial_number, :location, :status, :oee, :created_at)
                ON CONFLICT (id) DO NOTHING
            """), eq)
        
        await conn.commit()
        print(f"✓ Seeded {len(equipment_data)} equipment records")


async def seed_maintenance_tasks():
    """Seed preventive maintenance tasks"""
    
    tasks = [
        {"equipment_id": "eq-001", "task_type": "INSPECTION", "task_name": "Daily Inspection", "frequency": "Daily", "duration_minutes": 30},
        {"equipment_id": "eq-001", "task_type": "LUBRICATION", "task_name": "Lubricate Guides", "frequency": "Weekly", "duration_minutes": 60},
        {"equipment_id": "eq-002", "task_type": "CALIBRATION", "task_name": "Calibrate Sensors", "frequency": "Monthly", "duration_minutes": 120},
        {"equipment_id": "eq-003", "task_type": "REPLACEMENT", "task_name": "Replace Belts", "frequency": "Quarterly", "duration_minutes": 180},
        {"equipment_id": "eq-004", "task_type": "INSPECTION", "task_name": "Weekly Check", "frequency": "Weekly", "duration_minutes": 45}
    ]
    
    async with async_engine.connect() as conn:
        for task in tasks:
            await conn.execute(text("""
                INSERT INTO maintenance_tasks (id, equipment_id, task_type, task_name, 
                    frequency, duration_minutes, status, created_at)
                VALUES (:id, :equipment_id, :task_type, :task_name,
                    :frequency, :duration_minutes, 'PENDING', :created_at)
                ON CONFLICT (id) DO NOTHING
            """), {**task, "id": str(uuid.uuid4()), "created_at": datetime.now()})
        
        await conn.commit()
        print(f"✓ Seeded {len(tasks)} maintenance tasks")


async def seed_downtime_records():
    """Seed downtime records"""
    
    records = [
        {
            "equipment_id": "eq-001",
            "category": "BREAKDOWN",
            "reason": "Spindle motor failure",
            "downtime_start": datetime.now() - timedelta(hours=2),
            "downtime_end": datetime.now() - timedelta(minutes=30),
            "reported_by": "John Doe"
        },
        {
            "equipment_id": "eq-002",
            "category": "SETUP",
            "reason": "Product changeover",
            "downtime_start": datetime.now() - timedelta(hours=4),
            "downtime_end": datetime.now() - timedelta(hours=3),
            "reported_by": "Jane Smith"
        },
        {
            "equipment_id": "eq-003",
            "category": "MAINTENANCE",
            "reason": "Scheduled belt replacement",
            "downtime_start": datetime.now() - timedelta(days=1),
            "downtime_end": datetime.now() - timedelta(hours=8),
            "reported_by": "Mike Johnson"
        }
    ]
    
    async with async_engine.connect() as conn:
        for record in records:
            duration_minutes = int((record["downtime_end"] - record["downtime_start"]).total_seconds() / 60)
            await conn.execute(text("""
                INSERT INTO downtime_records (id, equipment_id, category, reason,
                    downtime_start, downtime_end, duration_minutes, reported_by, status, created_at)
                VALUES (:id, :equipment_id, :category, :reason,
                    :downtime_start, :downtime_end, :duration_minutes, :reported_by, 'RESOLVED', :created_at)
                ON CONFLICT (id) DO NOTHING
            """), {
                **record,
                "id": str(uuid.uuid4()),
                "duration_minutes": duration_minutes,
                "created_at": datetime.now()
            })
        
        await conn.commit()
        print(f"✓ Seeded {len(records)} downtime records")


async def seed_5s_audits():
    """Seed 5S audit records"""
    
    audits = [
        {
            "audit_name": "Workshop A Daily 5S",
            "area": "Workshop A",
            "auditor": "Team Leader",
            "audit_date": datetime.now().date(),
            "score": 85,
            "status": "COMPLETED"
        },
        {
            "audit_name": "Warehouse 5S Check",
            "area": "Warehouse",
            "auditor": "QC Manager",
            "audit_date": datetime.now().date() - timedelta(days=7),
            "score": 72,
            "status": "NEEDS_IMPROVEMENT"
        }
    ]
    
    async with async_engine.connect() as conn:
        for audit in audits:
            await conn.execute(text("""
                INSERT INTO five_s_audits (id, audit_name, area, auditor, audit_date,
                    score, status, created_at)
                VALUES (:id, :audit_name, :area, :auditor, :audit_date,
                    :score, :status, :created_at)
                ON CONFLICT (id) DO NOTHING
            """), {
                **audit,
                "id": str(uuid.uuid4()),
                "created_at": datetime.now()
            })
        
        await conn.commit()
        print(f"✓ Seeded {len(audits)} 5S audit records")


async def main():
    print("=" * 60)
    print("TPM Data Seeder")
    print("=" * 60)
    
    try:
        await seed_equipment()
        await seed_maintenance_tasks()
        await seed_downtime_records()
        await seed_5s_audits()
        
        print("\n✓ All TPM data seeded successfully!")
        print("\nNext steps:")
        print("1. Start backend: python3 main.py")
        print("2. Access TPM module in frontend")
        print("3. Verify data appears in OEE Dashboard, Maintenance, 5S Audit pages")
        
    except Exception as e:
        print(f"\n✗ Error seeding data: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
