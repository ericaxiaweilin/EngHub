#!/usr/bin/env python3
"""Reset eric user password to admin123456."""
import asyncio, sys

async def main():
    from database.db_config import db_config
    from core.auth.security import get_password_hash
    from sqlalchemy import text

    new_hash = get_password_hash("admin123456")
    print(f"Generated hash: {new_hash} (length {len(new_hash)})")

    async with db_config.session_factory() as session:
        result = await session.execute(
            text("UPDATE users SET hashed_password = :new_hash WHERE username = 'eric'"),
            {"new_hash": new_hash}
        )
        print(f"Rows updated: {result.rowcount}")
        await session.commit()
        print("Password updated successfully.")
        return True

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
