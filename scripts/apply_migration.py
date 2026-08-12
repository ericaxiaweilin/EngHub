#!/usr/bin/env python3
"""
Quality Red Tag Implementation Script
Applies the migration and initializes the red tag service
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.db_config import async_engine
from sqlalchemy import text


async def apply_migration():
    """Apply the quality red tag migration"""
    
    migration_sql_path = Path(__file__).parent.parent / "database" / "migrations" / "063_quality_red_tag.sql"
    
    if not migration_sql_path.exists():
        print(f"Migration file not found: {migration_sql_path}")
        return False
    
    migration_sql = migration_sql_path.read_text()
    
    async with async_engine.connect() as conn:
        # Execute migration
        await conn.execute(text(migration_sql))
        await conn.commit()
        print(f"✓ Successfully applied migration: {migration_sql_path.name}")
        
        # Verify tables were created
        result = await conn.execute(text("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name IN ('quality_red_tag', 'quality_red_tag_attachments')
        """))
        
        tables = [row[0] for row in result.fetchall()]
        print(f"✓ Created tables: {tables}")
    
    return True


async def main():
    print("=" * 60)
    print("Quality Red Tag - Database Migration")
    print("=" * 60)
    
    result = await apply_migration()
    
    if result:
        print("\n✓ Migration completed successfully!")
        print("\nNext steps:")
        print("1. Backend API is ready at /api/v1/qms/red-tags/")
        print("2. Frontend components: RedTagList.tsx, RedTagDetail.tsx, RedTagCreate.tsx")
        print("3. API routes are registered in api/routes/__init__.py")
    else:
        print("\n✗ Migration failed!")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
