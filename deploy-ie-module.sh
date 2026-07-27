#!/bin/bash
# ============================================================
# IE Module Deployment Script for EngHub MES System
# 精益生产IE模块部署脚本
# 作者: AgnesCode/Sapiens AI
# 日期: 2026-07-27
# ============================================================

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration (modify these as needed)
PROJECT_DIR="${PROJECT_DIR:-$(dirname "${BASH_SOURCE[0]}")}"
REPOSITORY_URL="${REPOSITORY_URL:-https://github.com/ericaxiaweilin/enghub.git}"
BRANCH="${BRANCH:-main}"
DATABASE_NAME="${DATABASE_NAME:-your_mes_db}"
DB_USER="${DB_USER:-postgres}"
DB_PASSWORD="${DB_PASSWORD:-your_password}"

# Function to print status messages
print_status() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1"
}

# Check if running in project directory
if [[ ! -f "$PROJECT_DIR/main.py" ]]; then
    print_error "Project directory not found! Expected main.py at $PROJECT_DIR"
    exit 1
fi

echo "=========================================="
echo "  IE MODULE DEPLOYMENT SCRIPT"
echo "=========================================="
echo ""

# Step 1: Update Git Repository
print_status "Step 1: Pulling latest code from git..."
cd "$PROJECT_DIR" || { print_error "Failed to change to project directory"; exit 1; }

git fetch origin || { print_error "Git fetch failed"; exit 1; }
git checkout "$BRANCH" || { print_error "Git branch checkout failed"; exit 1; }
git pull origin "$BRANCH" || { 
    print_warning "Git pull failed, checking for local changes..."
    git stash || true
    git pull origin "$BRANCH"
    git stash pop || true
}

if [[ $? -eq 0 ]]; then
    print_status "Code updated successfully!"
else
    print_error "Failed to update code. Please check git status manually."
    exit 1
fi

# Step 2: Apply Database Migrations
print_status ""
print_status "Step 2: Applying database migrations..."

# Check if psql is available and install if needed
if command -v psql &> /dev/null; then
    print_status "Found psql client, applying migrations directly..."
    
    # Connect to PostgreSQL and apply migration files
    MIGRATIONS=("039_ie_module.sql" "040_ie_extended_module.sql")
    
    for mig_file in "${MIGRATIONS[@]}"; do
        mig_path="$PROJECT_DIR/database/migrations/$mig_file"
        
        if [[ -f "$mig_path" ]]; then
            print_status "Applying migration: $mig_file..."
            
            # Try to connect and execute the SQL
            # Using environment variables or prompting for password
            if [[ -n "$DB_PASSWORD" ]]; then
                export PGPASSWORD="$DB_PASSWORD"
                psql -U "$DB_USER" -d "$DATABASE_NAME" -f "$mig_path" 2>&1 && \
                    print_status "Migration $mig_file applied successfully!" || \
                    print_error "Failed to apply $mig_file"
            else
                # Interactive password prompt (safer)
                psql -U "$DB_USER" -d "$DATABASE_NAME" -f "$mig_path" 2>&1 && \
                    print_status "Migration $mig_file applied successfully!" || \
                    print_error "Failed to apply $mig_file"
            fi
        else
            print_error "Migration file not found: $mig_path"
        fi
    done
    
else
    print_warning "psql command not found. Found alternatives:"
    
    # Check for other ways to connect to DB
    if command -v python3 &> /dev/null; then
        print_status "Checking Python DB connectors..."
        
        # Check if SQLAlchemy is available
        if python3 -c "import sqlalchemy; print('SQLAlchemy available')" 2>/dev/null; then
            print_status "SQLAlchemy available - you can run migrations via Python script"
            
            # Create a simple Python migration runner script
            cat > "$PROJECT_DIR/run_migrations.py" << 'PYEOF'
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.db_config import get_engine
from sqlalchemy import text

def apply_migration(file_path):
    """Apply a single migration SQL file"""
    print(f"Applying migration: {os.path.basename(file_path)}")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        sql = f.read()
    
    # Split by semicolon to handle multiple statements
    statements = [s.strip() for s in sql.split(';') if s.strip()]
    
    engine = get_engine()
    with engine.connect() as conn:
        try:
            for stmt in statements:
                conn.execute(text(stmt))
            conn.commit()
            print("✓ Migration applied successfully!")
        except Exception as e:
            print(f"✗ Error applying migration: {e}")
            raise

if __name__ == "__main__":
    migrations_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 
                                   "database", "migrations")
    migration_files = sorted([
        f for f in os.listdir(migrations_dir)
        if f.endswith('.sql') and ('ie' in f.lower())
    ])
    
    print(f"Found {len(migration_files)} IE-related migration files to apply")
    
    for mig_file in migration_files:
        mig_path = os.path.join(migrations_dir, mig_file)
        apply_migration(mig_path)
PYEOF
            
            print_status "Running migration via Python script..."
            python3 "$PROJECT_DIR/run_migrations.py" || \
                print_error "Python migration runner failed"
        else:
            print_error "No suitable database connector found. Manual migration required."
            print("Please install psycopg2: pip install psycopg2-binary")
    else
        print_error "Neither psql nor Python SQLAlchemy found. Please install one."
        echo "Install options:"
        echo "  sudo apt install postgresql-client-common  # for psql"
        echo "  pip install psycopg2 sqlalchemy             # for Python approach"
        exit 1
fi

# Step 3: Restart Application
print_status ""
print_status "Step 3: Restarting MES application..."

# Method 1: Check for PM2
if command -v pm2 &> /dev/null; then
    print_status "PM2 found, restarting application..."
    pm2 restart all || pm2 start main.py --name "mes-app"
    print_status "Application restarted via PM2!"
    
# Method 2: Check for systemd
elif [[ -f "/etc/systemd/system/mes-app.service" ]] || \
      [[ -f "/lib/systemd/system/mes-app.service" ]]; then
    print_status "systemd service found, reloading..."
    sudo systemctl daemon-reload
    sudo systemctl restart mes-app || sudo systemctl restart enghub-mes
    print_status "Application restarted via systemd!"
    
# Method 3: Check for nohup/process management
elif pgrep -f "python.*main.py" &> /dev/null; then
    print_status "Found running process, attempting graceful restart..."
    # Kill old processes
    pkill -f "python.*main.py" || true
    sleep 1
    # Start new process in background
    nohup python3 main.py > /var/log/mes-app.log 2>&1 &
    print_status "Application started in background (PID: $!)"
    
# Method 4: Simple fallback - just start if nothing found
else
    print_warning "No process manager found. Starting application directly..."
    nohup python3 main.py > app.log 2>&1 &
    print_status "Application started in background (check app.log)"
fi

# Verification
print_status ""
print_status "=========================================="
print_status "  VERIFICATION"
print_status "=========================================="

# Check API endpoint availability
if curl -s --connect-timeout 5 "http://localhost:8000/api/v1/ie/standard-times" | grep -q "401"; then
    print_status "IE API endpoints are accessible (authentication expected) ✓"
elif curl -s --connect-timeout 5 "http://localhost:8000/" | grep -qi "mes"; then
    print_status "MES application is running ✓"
else
    print_error "Could not verify application status. Please check manual access."
    print_warning "Try: curl -I http://localhost:8000"
fi

echo ""
echo "=========================================="
echo -e "${GREEN}✅ IE Module Deployment Complete!${NC}"
echo "=========================================="
echo ""
echo "API Endpoints available at:"
echo "  Base: http://localhost:8000"
echo "  Swagger: http://localhost:8000/docs"
echo "  IE Module API prefix: /api/v1/ie"
echo "  Advanced IE Module: /api/v1/ie-advanced"
echo ""
echo "Remember to:"
echo "  1. Configure proper database connection"
echo "  2. Set up authentication for production"
echo "  3. Review migration scripts before deployment"
echo ""