"""补充seed: quality_inspections / defect_records / plans (API实际查询的表)"""
import asyncio, uuid, random
from datetime import datetime, timedelta
from database.db_config import db_config
from sqlalchemy import text

FACTORY = 'F01'
ERIC_ID = '94cb8a0d-9727-7e8a-943a-b43c32fe54cf'
NOW = datetime.now()

def uid(): return str(uuid.uuid4())
def ts(d=0, h=0): return NOW - timedelta(days=d, hours=h)

async def seed():
    async with db_config.session_factory() as db:
        # 1. quality_inspections (API: /inspections)
        print('=== quality_inspections ===')
        types = ['IQC', 'IPQC', 'FQC', 'OQC']
        results = ['PASS', 'FAIL', 'PASS', 'PASS', 'FAIL', 'PASS', 'PASS', 'PASS', 'FAIL', 'PASS', 'PASS', 'PASS']
        for i in range(12):
            sample = random.randint(20, 100)
            defect = random.randint(1, 5) if results[i] == 'FAIL' else 0
            details = '{"scratch": 2, "dimension": 1}' if defect > 0 else None
            await db.execute(text(
                "INSERT INTO quality_inspections (id, factory_id, work_order_id, inspect_type, "
                "inspector_id, sample_qty, defect_qty, result, defect_details, created_at) "
                "VALUES (:id, :fid, :wo, :itype, :insp, :sqty, :dqty, :res, :details, :cat)"
            ), {
                "id": uid(), "fid": FACTORY, "wo": f"WO-2026-000{(i%5)+1}",
                "itype": types[i % 4], "insp": ERIC_ID, "sqty": sample,
                "dqty": defect, "res": results[i], "details": details, "cat": ts(i)
            })
        print('  12 rows')

        # 2. defect_records (API: /defects)
        print('=== defect_records ===')
        dtypes = ['scratch', 'dimension', 'crack', 'porosity', 'deformation', 'contamination']
        sevs = ['critical', 'major', 'minor', 'observation']
        for i in range(15):
            await db.execute(text(
                "INSERT INTO defect_records (id, factory_id, work_order_id, defect_code, defect_name, "
                "defect_type, severity, quantity, station_id, description, created_at, updated_at) "
                "VALUES (:id, :fid, :wo, :dcode, :dname, :dtype, :sev, :qty, :st, :desc, :cat, :uat)"
            ), {
                "id": uid(), "fid": FACTORY, "wo": f"WO-2026-000{(i%5)+1}",
                "dcode": f"DEF-2026-{i+1:04d}", "dname": f"{dtypes[i%6]}缺陷",
                "dtype": dtypes[i % 6], "sev": sevs[i % 4],
                "qty": random.randint(1, 20), "st": f"ST-0{(i%6)+1}",
                "desc": f"{dtypes[i%6]}缺陷-工序异常", "cat": ts(i), "uat": ts(i)
            })
        print('  15 rows')

        # 3. plans (API: /plans)
        print('=== plans ===')
        statuses = ['draft', 'confirmed', 'released', 'in_progress', 'completed']
        plan_types = ['make_to_order', 'make_to_stock', 'urgent']
        levels = ['A', 'B', 'C']
        for i in range(8):
            req_date = NOW + timedelta(days=random.randint(3, 30))
            await db.execute(text(
                "INSERT INTO plans (id, plan_code, factory_id, product_id, quantity, required_date, "
                "plan_type, customer_level, priority, status, priority_score, created_at, updated_at, created_by) "
                "VALUES (:id, :pcode, :fid, :pid, :qty, :rdate, :ptype, :clevel, :pri, :status, :pscore, :cat, :uat, :cby)"
            ), {
                "id": uid(), "pcode": f"PP-2026-{i+1:04d}", "fid": FACTORY,
                "pid": f"PRD-00{i%3+1}", "qty": random.randint(100, 2000),
                "rdate": req_date, "ptype": plan_types[i % 3],
                "clevel": levels[i % 3], "pri": random.randint(1, 5),
                "status": statuses[i % 5], "pscore": round(random.uniform(50, 99), 1),
                "cat": ts(i * 2), "uat": ts(i), "cby": ERIC_ID
            })
        print('  8 rows')

        await db.commit()
        print('\n✅ SEED2 COMMITTED')

asyncio.run(seed())
