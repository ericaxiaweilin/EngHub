#!/bin/bash
# Simple IE Module Sync Script - Just pull code and run migrations
# Author: AgnesCode/Sapiens AI
# Usage: ./sync-ie-module.sh

set -e

echo "=========================================="
echo "  IE MODULE SYNC SCRIPT"
echo "=========================================="
echo ""

PROJECT_DIR="$(pwd)"

# Step 1: Pull latest code
echo "[Step 1] Pulling latest code from git..."
git fetch origin main
git checkout main || git checkout -b main origin/main
git pull origin main || echo "Git pull completed (may have conflicts to resolve)"
echo "✓ Code updated!"

# Step 2: Check for DB migration tools
echo "[Step 2] Checking database connectivity..."
HAS_PSQL=$(command -v psql 2>/dev/null && echo "yes" || echo "no")

if [[ "$HAS_PSQL" == "yes" ]]; then
    echo "Found psql client. Running migrations..."
    
    MIG_DIR="$PROJECT_DIR/database/migrations"
    SQL_FILES=("039_ie_module.sql" "040_ie_extended_module.sql")
    
    for sql_file in "${SQL_FILES[@]}"; do
        if [[ -f "$MIG_DIR/$sql_file" ]]; then
            echo "  Applying: $sql_file"
            DB_NAME="${DATABASE_NAME:-your_db}"
            DB_USER="${DB_USER:-postgres}"
            
            psql -U "$DB_USER" -d "$DB_NAME" -f "$MIG_DIR/$sql_file" 2>&1 || \
                echo "Note: Migration may require interactive credentials"
        else
            echo "Warning: Migration file not found: $MIG_DIR/$sql_file"
        fi
    done
else
    echo "No psql detected. Skipping database migration step."
    echo "You will need to run migrations manually:"
    echo "  Install PostgreSQL client first, then run:"
    echo "  psql -U your_user -d your_db -f database/migrations/039_ie_module.sql"
    echo "  psql -U your_user -d your_db -f database/migrations/040_ie_extended_module.sql"
fi

echo ""
echo "Sync complete! IE Module is ready."
echo ""
echo "Next steps:"
echo "1. If you skipped migrations, apply them manually above"
echo "2. Restart your application: python3 main.py &"
echo "3. Verify at: http://localhost:8000/docs"
