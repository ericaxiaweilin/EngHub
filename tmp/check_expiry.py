import asyncio
from sqlalchemy import text
from database.db_config import db_config

async def main():
    async with db_config.session_factory() as db:
        r = await db.execute(text(
            "SELECT COUNT(*) total, COUNT(expiry_date) with_expiry, "
            "MIN(expiry_date) mn, MAX(expiry_date) mx FROM hr_employee_skills"
        ))
        row = r.one()
        print("总记录:", row[0], "有到期日:", row[1], "最早:", row[2], "最晚:", row[3])
        r2 = await db.execute(text(
            "SELECT COUNT(*) FROM hr_employee_skills WHERE expiry_date IS NOT NULL "
            "AND expiry_date >= CURRENT_DATE "
            "AND expiry_date <= CURRENT_DATE + INTERVAL '365 days'"
        ))
        print("365天内到期:", r2.scalar())

asyncio.run(main())
