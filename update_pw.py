from database.db_config import db_config
from sqlalchemy import text, update
import asyncio

async def main():
    new_hash = '$2b$12$B2/lOa4Erybb9ZT63u4KsurMJKXTDFQDYU5MR9P4fCboLj16jO9LO'
    async with db_config.session_factory() as s:
        r = await s.execute(text("UPDATE users SET hashed_password = :h WHERE username = 'eric'"), {'h': new_hash})
        print('Updated rows:', r.rowcount)
        await s.commit()

if __name__ == "__main__":
    asyncio.run(main())
