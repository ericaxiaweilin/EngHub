from database.db_config import db_config
from sqlalchemy import text
import asyncio

async def main():
    async with db_config.session_factory() as s:
        r = await s.execute(text("SELECT username, hashed_password, password_hash FROM users WHERE username = 'eric'"))
        for row in r:
            print(row)

if __name__ == "__main__":
    asyncio.run(main())
