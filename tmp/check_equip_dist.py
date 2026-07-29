import asyncio
from sqlalchemy import text
from database.db_config import db_config

async def main():
    async with db_config.session_factory() as db:
        print("=== equipment 按厂区 ===")
        for r in (await db.execute(text("SELECT factory_id, COUNT(*) FROM equipment GROUP BY factory_id"))).fetchall():
            print("  ", r[0], r[1])
        print("=== stations 按厂区 ===")
        for r in (await db.execute(text("SELECT factory_id, COUNT(*) FROM stations GROUP BY factory_id"))).fetchall():
            print("  ", r[0], r[1])
        print("=== production_reports 按厂区+日期 ===")
        for r in (await db.execute(text("SELECT factory_id, DATE(created_at), COUNT(*) FROM production_reports GROUP BY factory_id, DATE(created_at) ORDER BY 2 DESC"))).fetchall():
            print("  ", r[0], r[1], r[2])
        print("=== 今天日期 ===")
        print("  ", (await db.execute(text("SELECT CURRENT_DATE"))).scalar())

asyncio.run(main())
