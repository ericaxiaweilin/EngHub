import asyncio
from sqlalchemy import text
from database.db_config import db_config

async def main():
    async with db_config.session_factory() as db:
        for t in ["products", "work_orders", "production_reports", "equipment", "stations",
                  "defects", "qms_defects", "inventory", "wms_inventory", "hr_employees"]:
            try:
                cnt = (await db.execute(text(f'SELECT COUNT(*) FROM "{t}"'))).scalar()
                print(f"{t}: {cnt}")
            except Exception as e:
                await db.rollback()
                print(f"{t}: (no table)")
        # work_orders 列
        cols = (await db.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name='work_orders' ORDER BY ordinal_position"
        ))).fetchall()
        print("\nwork_orders 列:", [c[0] for c in cols])
        # 工单样例
        r = (await db.execute(text("SELECT work_order_code, product_id, factory_id FROM work_orders LIMIT 3"))).fetchall()
        print("\n工单样例:")
        for row in r:
            print("  ", row[0], "| product_id:", row[1], "| factory:", row[2])
        # products 按厂区
        try:
            r2 = (await db.execute(text("SELECT factory_id, COUNT(*) FROM products GROUP BY factory_id"))).fetchall()
            print("\nproducts 按厂区:", r2)
        except Exception as e:
            print("\nproducts 查询失败:", e)

asyncio.run(main())
