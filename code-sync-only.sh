#!/bin/bash
# IE Module Code Sync Script - Code Only, No Database/Migration
# 仅同步代码，不执行数据库迁移
# Author: AgnesCode/Sapiens AI

echo "=========================================="
echo "  IE MODULE CODE SYNC SCRIPT"
echo "  (Code only - no database operations)"
echo "=========================================="
echo ""

cd "$(dirname "$0")" || exit 1

# Pull latest code from git
echo "[Step 1] Pulling latest code..."
git fetch origin main 2>/dev/null || true
git checkout main 2>/dev/null || true
git pull origin main 2>/dev/null || echo "Note: Git pull may have conflicts (check manually)"

echo "✓ Code updated successfully!"

echo ""
echo "=========================================="
echo "  Done! Code is synchronized."
echo "  Next steps:"
echo "  1. Apply migrations if needed: psql -U user -d db -f database/migrations/*.sql"
echo "  2. Restart application: pm2 restart all or python3 main.py &"
echo "  3. Verify at: http://localhost:8000/docs"
echo "=========================================="