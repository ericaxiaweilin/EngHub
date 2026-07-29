import asyncio
from sqlalchemy import text
from database.db_config import db_config

async def main():
    async with db_config.session_factory() as db:
        rows = (await db.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
        ))).fetchall()
        empty, nonempty = [], []
        for r in rows:
            t = r[0]
            try:
                cnt = (await db.execute(text(f'SELECT COUNT(*) FROM "{t}"'))).scalar()
            except Exception as e:
                print(f"{t}: ERROR {e}")
                continue
            (empty if cnt == 0 else nonempty).append((t, cnt))
        print("=== 空表 (0 行) ===")
        for t, c in empty:
            print(f"  {t}")
        print(f"\n空表总数: {len(empty)} / 全部 {len(rows)}")

asyncio.run(main())
