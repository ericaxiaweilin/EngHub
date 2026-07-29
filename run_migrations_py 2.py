#!/usr/bin/env python3
"""
Simple Python-based migration runner for IE Module
使用 SQLAlchemy 执行 IE 模块迁移脚本
"""

import sys
import os
import re
from pathlib import Path

# Add project directory to path
project_dir = Path(__file__).parent.resolve()
sys.path.insert(0, str(project_dir))

def get_engine():
    """Get database engine from project configuration"""
    try:
        # Try to import from the actual project
        from database.db_config import get_engine
        return get_engine()
    except ImportError:
        # Fallback: use SQLAlchemy directly with connection string
        from sqlalchemy import create_engine
        
        # Try to get credentials from environment or ask user
        db_user = os.getenv('DB_USER', 'postgres')
        db_password = os.getenv('DB_PASSWORD', 'your_password')
        db_host = os.getenv('DB_HOST', 'localhost')
        db_name = os.getenv('DATABASE_NAME', 'your_mes_db')
        
        connection_string = f"postgresql://{db_user}:{db_password}@{db_host}/{db_name}"
        print(f"Connecting to PostgreSQL: {connection_string}")
        
        engine = create_engine(connection_string, echo=False)
        return engine

def apply_migration(file_path):
    """Apply a single migration SQL file"""
    filename = os.path.basename(file_path)
    print(f"\n📄 Applying migration: {filename}")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        sql_content = f.read()
    
    # Remove comments and split into statements
    # Simple approach: split by semicolon
    statements = [s.strip() for s in re.split(r';\s*', sql_content) if s.strip()]
    
    if not statements:
        print("  ⚠ No statements found in migration file")
        return
    
    print(f"  Found {len(statements)} statement(s)")
    
    engine = get_engine()
    
    try:
        with engine.connect() as conn:
            for i, stmt in enumerate(statements, 1):
                # Skip empty lines and comment lines
                if stmt.startswith('--') or not stmt.strip():
                    continue
                conn.execute(text(stmt))
                print(f"    Statement {i}/{len(statements)} executed")
            
            conn.commit()
        print(f"  ✅ Migration '{filename}' applied successfully!")
    except Exception as e:
        print(f"  ❌ Error applying migration: {e}")
        raise

def main():
    print("=" * 60)
    print("IE Module - Python Migration Runner")
    print("=" * 60)
    
    migrations_dir = project_dir / "database" / "migrations"
    
    if not migrations_dir.exists():
        print(f"Error: Migrations directory not found: {migrations_dir}")
        sys.exit(1)
    
    # Find all IE-related migration files
    migration_files = sorted([
        f for f in migrations_dir.iterdir()
        if f.is_file() and f.suffix == '.sql' and 'ie' in f.name.lower()
    ])
    
    print(f"Found {len(migration_files)} IE-related migration file(s)")
    
    if not migration_files:
        print("No IE migration files found.")
        sys.exit(0)
    
    # Apply each migration
    for mig_file in migration_files:
        try:
            apply_migration(str(mig_file))
        except Exception as e:
            print(f"Critical error: {e}")
            sys.exit(1)
    
    print("\n" + "=" * 60)
    print("✅ All IE module migrations completed successfully!")
    print("=" * 60)

if __name__ == "__main__":
    from sqlalchemy import text
    main()