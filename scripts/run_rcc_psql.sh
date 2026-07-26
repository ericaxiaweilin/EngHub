#!/bin/bash
# RCC 数据库迁移脚本
export PATH="/opt/homebrew/Cellar/postgresql@15/15.15_1/bin:$PATH"

PSQL="psql -h localhost -U enghub -d enghub -v ON_ERROR_STOP=0"

echo "=== Creating org_units table ==="
$PSQL -c "CREATE TABLE IF NOT EXISTS org_units (id VARCHAR(36) PRIMARY KEY, code VARCHAR(50), name VARCHAR(200), parent_id VARCHAR(36) REFERENCES org_units(id) ON DELETE SET NULL, level_type VARCHAR(20) DEFAULT 'operational', factory_id VARCHAR(50), metadata_ JSONB DEFAULT '{}'::jsonb, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL);"

echo "=== Creating position_capabilities table ==="
$PSQL -c "CREATE TABLE IF NOT EXISTS position_capabilities (id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(), cap_code VARCHAR(50) UNIQUE, cap_name VARCHAR(200), skill_level_min VARCHAR(10), skill_level_max VARCHAR(10), org_unit_id VARCHAR(36) REFERENCES org_units(id), description TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL);"

echo "=== Running migration 009 ==="
$PSQL -f database/migrations/009_v26_rcc_parameterization.sql

echo ""
echo "=== Running migration 038 ==="
$PSQL -f database/migrations/038_rcc_baseline_data.sql

echo ""
echo "=== Verification ==="
$PSQL -c "SELECT tablename FROM pg_tables WHERE schemaname='public' AND (tablename LIKE 'rcc_%' OR tablename IN ('global_adjustable_params','parameter_change_audit','chatbot_tickets','deterministic_logic_chains','logic_chain_execution_log')) ORDER BY tablename;"
$PSQL -tA -c "SELECT 'global_adjustable_params: ' || COUNT(*) FROM global_adjustable_params UNION ALL SELECT 'deterministic_logic_chains: ' || COUNT(*) FROM deterministic_logic_chains UNION ALL SELECT 'rcc_tasks: ' || COUNT(*) FROM rcc_tasks UNION ALL SELECT 'chatbot_tickets: ' || COUNT(*) FROM chatbot_tickets UNION ALL SELECT 'rcc_organizations: ' || COUNT(*) FROM rcc_organizations UNION ALL SELECT 'org_units_total: ' || COUNT(*) FROM org_units"
