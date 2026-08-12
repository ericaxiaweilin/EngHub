"""
Test script for Quality Red Tag API
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from database.db_config import async_engine
from core.qms.red_tag_service import RedTagService
from sqlalchemy import text


async def test_red_tag_api():
    """Test the red tag API"""
    
    async with async_engine.connect() as conn:
        # Check if table exists
        result = await conn.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = 'quality_red_tag'
            )
        """))
        table_exists = result.scalar()
        
        if not table_exists:
            print("❌ Table quality_red_tag does not exist!")
            print("Please run: python3 scripts/apply_migration.py")
            return False
        
        print("✓ Table quality_red_tag exists")
        
        # Create a test red tag
        service = RedTagService(conn)
        
        try:
            red_tag = await service.create_red_tag(
                factory_id="test-factory",
                defect_id="test-defect-1",
                red_tag_type="INCOMING",
                defect_description="Test defect for red tag",
                nonconforming_qty=10.0,
                severity="MAJOR",
                created_by="test-user"
            )
            print(f"✓ Created red tag: {red_tag.red_tag_no}")
            
            # Get the red tag
            red_tag_data = await service.get_red_tag(red_tag.id)
            print(f"✓ Retrieved red tag: {red_tag_data['red_tag_no']}")
            print(f"  - Type: {red_tag_data['red_tag_type']}")
            print(f"  - Severity: {red_tag_data['severity']}")
            print(f"  - Status: {red_tag_data['quarantine_status']}")
            
            # List red tags
            list_result = await service.list_red_tags(factory_id="test-factory")
            print(f"✓ Listed {list_result['total']} red tags")
            
            # Get statistics
            stats = await service.get_statistics("test-factory")
            print(f"✓ Statistics: {stats['total']} total red tags")
            
            # Clean up
            await service.delete_red_tag(red_tag.id)
            print("✓ Cleaned up test red tag")
            
            return True
            
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
            return False


if __name__ == "__main__":
    result = asyncio.run(test_red_tag_api())
    sys.exit(0 if result else 1)
