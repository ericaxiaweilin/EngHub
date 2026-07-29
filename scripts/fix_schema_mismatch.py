"""
自动修复数据库 schema 与模型不匹配的问题
在服务器上运行: docker exec enghub python3 scripts/fix_schema_mismatch.py
"""
import asyncio
import sys
sys.path.insert(0, '/app')

from database.db_config import db_config
from database.models import Base
from sqlalchemy import text, Column, String, Integer, Float, Boolean, DateTime, Date, Text, Numeric, JSON
from sqlalchemy.dialects.postgresql import UUID, JSONB

# 列类型映射
TYPE_MAP = {
    String: 'VARCHAR',
    Integer: 'INTEGER',
    Float: 'DOUBLE PRECISION',
    Boolean: 'BOOLEAN',
    DateTime: 'TIMESTAMP',
    Date: 'DATE',
    Text: 'TEXT',
    Numeric: 'NUMERIC',
    JSON: 'JSON',
}

# 需要创建的缺失表（表名 -> 列定义）
MISSING_TABLES = {
    'inspections': [
        ('id', 'VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()'),
        ('factory_id', 'VARCHAR(50) NOT NULL'),
        ('inspection_code', 'VARCHAR(50) UNIQUE NOT NULL'),
        ('inspection_type', 'VARCHAR(50)'),
        ('work_order_id', 'VARCHAR(36)'),
        ('product_id', 'VARCHAR(50)'),
        ('status', 'VARCHAR(20) DEFAULT \'pending\''),
        ('result', 'VARCHAR(20)'),
        ('inspector_id', 'VARCHAR(50)'),
        ('inspected_at', 'TIMESTAMP'),
        ('created_by', 'VARCHAR(50)'),
        ('created_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
        ('updated_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
    ],
    'defects': [
        ('id', 'VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()'),
        ('factory_id', 'VARCHAR(50) NOT NULL'),
        ('defect_code', 'VARCHAR(50) UNIQUE NOT NULL'),
        ('defect_type', 'VARCHAR(50)'),
        ('severity', 'VARCHAR(20)'),
        ('description', 'TEXT'),
        ('work_order_id', 'VARCHAR(36)'),
        ('product_id', 'VARCHAR(50)'),
        ('quantity', 'INTEGER DEFAULT 0'),
        ('disposition', 'VARCHAR(20)'),
        ('created_by', 'VARCHAR(50)'),
        ('created_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
        ('updated_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
    ],
    'training_records': [
        ('id', 'VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()'),
        ('factory_id', 'VARCHAR(50) NOT NULL'),
        ('employee_id', 'VARCHAR(36)'),
        ('skill_id', 'VARCHAR(36)'),
        ('training_date', 'DATE'),
        ('score', 'FLOAT'),
        ('status', 'VARCHAR(20) DEFAULT \'pending\''),
        ('certification_expiry', 'DATE'),
        ('trainer_id', 'VARCHAR(50)'),
        ('notes', 'TEXT'),
        ('created_by', 'VARCHAR(50)'),
        ('created_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
        ('updated_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
    ],
    'quality_defects': [
        ('id', 'VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()'),
        ('factory_id', 'VARCHAR(50) NOT NULL'),
        ('defect_code', 'VARCHAR(50) UNIQUE NOT NULL'),
        ('defect_name', 'VARCHAR(100)'),
        ('category', 'VARCHAR(50)'),
        ('severity', 'VARCHAR(20)'),
        ('description', 'TEXT'),
        ('is_active', 'BOOLEAN DEFAULT TRUE'),
        ('created_by', 'VARCHAR(50)'),
        ('created_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
        ('updated_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
    ],
    'capa_cases': [
        ('id', 'VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()'),
        ('factory_id', 'VARCHAR(50) NOT NULL'),
        ('case_code', 'VARCHAR(50) UNIQUE NOT NULL'),
        ('title', 'VARCHAR(200)'),
        ('description', 'TEXT'),
        ('root_cause', 'TEXT'),
        ('corrective_action', 'TEXT'),
        ('preventive_action', 'TEXT'),
        ('status', 'VARCHAR(20) DEFAULT \'open\''),
        ('priority', 'VARCHAR(20)'),
        ('assigned_to', 'VARCHAR(50)'),
        ('due_date', 'DATE'),
        ('completed_at', 'TIMESTAMP'),
        ('created_by', 'VARCHAR(50)'),
        ('created_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
        ('updated_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
    ],
    'quality_costs': [
        ('id', 'VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()'),
        ('factory_id', 'VARCHAR(50) NOT NULL'),
        ('cost_type', 'VARCHAR(50)'),
        ('amount', 'NUMERIC(12,2)'),
        ('period', 'VARCHAR(20)'),
        ('description', 'TEXT'),
        ('created_by', 'VARCHAR(50)'),
        ('created_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
        ('updated_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
    ],
    'process_capability': [
        ('id', 'VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()'),
        ('factory_id', 'VARCHAR(50) NOT NULL'),
        ('product_id', 'VARCHAR(50)'),
        ('process_name', 'VARCHAR(100)'),
        ('cpk', 'FLOAT'),
        ('cp', 'FLOAT'),
        ('ppk', 'FLOAT'),
        ('pp', 'FLOAT'),
        ('sample_size', 'INTEGER'),
        ('measured_at', 'TIMESTAMP'),
        ('created_by', 'VARCHAR(50)'),
        ('created_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
        ('updated_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
    ],
    'spc_configs': [
        ('id', 'VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()'),
        ('factory_id', 'VARCHAR(50) NOT NULL'),
        ('product_id', 'VARCHAR(50)'),
        ('characteristic', 'VARCHAR(100)'),
        ('ucl', 'FLOAT'),
        ('lcl', 'FLOAT'),
        ('cl', 'FLOAT'),
        ('sample_size', 'INTEGER DEFAULT 5'),
        ('is_active', 'BOOLEAN DEFAULT TRUE'),
        ('created_by', 'VARCHAR(50)'),
        ('created_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
        ('updated_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
    ],
}

# 需要添加的缺失列 (表名 -> [(列名, 类型, 默认值)])
MISSING_COLUMNS = {
    'pp_plans': [
        ('confirmed_by', 'VARCHAR(50)'),
        ('released_by', 'VARCHAR(50)'),
        ('confirmed_at', 'TIMESTAMP'),
        ('released_at', 'TIMESTAMP'),
    ],
    'production_report_comments': [
        ('comment', 'TEXT'),
    ],
    'time_study_records': [
        ('updated_by', 'VARCHAR(50)'),
    ],
    'line_balance_analyses': [
        ('workstation_details', 'JSON DEFAULT \'{}\'::jsonb'),
        ('updated_by', 'VARCHAR(50)'),
    ],
    'process_analyses': [
        ('updated_by', 'VARCHAR(50)'),
    ],
    'action_studies': [
        ('duration_min', 'FLOAT'),
        ('energy_consumption', 'FLOAT'),
        ('fatigue_level', 'VARCHAR(20)'),
        ('improvement_suggestion', 'TEXT'),
        ('is_optimized', 'BOOLEAN DEFAULT FALSE'),
        ('created_by', 'VARCHAR(50)'),
        ('updated_by', 'VARCHAR(50)'),
    ],
    'method_studies': [
        ('product_id', 'VARCHAR(50)'),
        ('original_operation', 'TEXT'),
        ('version', 'VARCHAR(20)'),
        ('is_basement_method', 'BOOLEAN DEFAULT FALSE'),
        ('is_optimal_method', 'BOOLEAN DEFAULT FALSE'),
        ('description', 'TEXT'),
        ('improved_operation', 'TEXT'),
        ('expected_time_saving_min', 'FLOAT'),
        ('cost_impact', 'NUMERIC(12,2)'),
        ('implementation_status', 'VARCHAR(20)'),
        ('implementer_id', 'VARCHAR(50)'),
        ('implementation_date', 'DATE'),
        ('verification_result', 'TEXT'),
        ('created_by', 'VARCHAR(50)'),
        ('updated_by', 'VARCHAR(50)'),
        ('updated_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
    ],
    'work_cell_layouts': [
        ('work_cell_id', 'VARCHAR(36)'),
        ('product_family_id', 'VARCHAR(36)'),
        ('layout_diagram_url', 'VARCHAR(255)'),
        ('material_flow_path', 'TEXT'),
        ('operator_movement_path', 'TEXT'),
        ('takt_time_alignment', 'VARCHAR(50)'),
        ('storage_location_type', 'VARCHAR(50)'),
        ('description', 'TEXT'),
        ('created_by', 'VARCHAR(50)'),
        ('updated_by', 'VARCHAR(50)'),
        ('updated_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
    ],
    'kanban_systems': [
        ('kanban_id', 'VARCHAR(36)'),
        ('kanban_type', 'VARCHAR(50)'),
        ('upstream_station', 'VARCHAR(50)'),
        ('downstream_station', 'VARCHAR(50)'),
        ('product_id', 'VARCHAR(50)'),
        ('min_stock_level', 'INTEGER'),
        ('max_stock_level', 'INTEGER'),
        ('reorder_quantity', 'INTEGER'),
        ('lead_time_days', 'INTEGER'),
        ('holder_id', 'VARCHAR(50)'),
        ('created_by', 'VARCHAR(50)'),
        ('updated_by', 'VARCHAR(50)'),
        ('updated_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
    ],
    'five_s_audits': [
        ('work_center_id', 'VARCHAR(50)'),
        ('auditor_id', 'VARCHAR(50)'),
        ('seiri_score', 'FLOAT'),
        ('seiton_score', 'FLOAT'),
        ('seiso_score', 'FLOAT'),
        ('seiketsu_score', 'FLOAT'),
        ('shitsuke_score', 'FLOAT'),
        ('improvement_items', 'TEXT'),
        ('next_audit_date', 'DATE'),
        ('created_by', 'VARCHAR(50)'),
        ('updated_by', 'VARCHAR(50)'),
        ('updated_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
    ],
    'code_tables': [
        ('created_by', 'VARCHAR(50)'),
        ('updated_by', 'VARCHAR(50)'),
    ],
    'reconciliation_logs': [
        ('net_change', 'INTEGER DEFAULT 0'),
        ('expected_delta', 'INTEGER DEFAULT 0'),
        ('delta', 'INTEGER DEFAULT 0'),
        ('discrepancy_detail', 'TEXT'),
        ('checked_by', 'VARCHAR(50)'),
    ],
    'replenishment_thresholds': [
        ('min_level', 'INTEGER DEFAULT 0'),
        ('max_level', 'INTEGER DEFAULT 0'),
        ('safety_stock', 'INTEGER DEFAULT 0'),
        ('reorder_lot_size', 'INTEGER DEFAULT 0'),
        ('reorder_lead_time_hours', 'INTEGER DEFAULT 24'),
        ('line_side_location', 'VARCHAR(50)'),
        ('active', 'BOOLEAN DEFAULT TRUE'),
    ],
    'qms_inspection_items': [
        ('created_by', 'VARCHAR(50)'),
        ('created_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
        ('updated_by', 'VARCHAR(50)'),
        ('updated_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
    ],
    'quality_goals': [
        ('product_id', 'VARCHAR(50)'),
        ('actual_value', 'FLOAT'),
        ('created_by', 'VARCHAR(50)'),
        ('updated_by', 'VARCHAR(50)'),
    ],
    'quality_goal_reviews': [
        ('reviewer', 'VARCHAR(50)'),
        ('comments', 'TEXT'),
        ('approved', 'BOOLEAN DEFAULT FALSE'),
        ('created_by', 'VARCHAR(50)'),
        ('created_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
        ('updated_by', 'VARCHAR(50)'),
        ('updated_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
    ],
    'qms_spc_points': [
        ('created_by', 'VARCHAR(50)'),
        ('created_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
        ('updated_by', 'VARCHAR(50)'),
        ('updated_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
    ],
    'inventory_count_items': [
        ('created_by', 'VARCHAR(50)'),
        ('created_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
        ('updated_by', 'VARCHAR(50)'),
        ('updated_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
    ],
    'equipment_downtime': [
        ('created_by', 'VARCHAR(50)'),
        ('updated_by', 'VARCHAR(50)'),
        ('updated_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
    ],
    'maintenance_orders': [
        ('order_type', 'VARCHAR(50)'),
        ('scheduled_start', 'TIMESTAMP'),
        ('scheduled_end', 'TIMESTAMP'),
        ('actual_start', 'TIMESTAMP'),
        ('actual_end', 'TIMESTAMP'),
        ('updated_by', 'VARCHAR(50)'),
        ('updated_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
    ],
    'maintenance_plans': [
        ('plan_code', 'VARCHAR(50)'),
        ('plan_type', 'VARCHAR(50)'),
        ('frequency', 'VARCHAR(50)'),
        ('next_run_date', 'DATE'),
        ('last_run_date', 'DATE'),
        ('description', 'TEXT'),
        ('created_by', 'VARCHAR(50)'),
        ('updated_by', 'VARCHAR(50)'),
        ('updated_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
    ],
    'hourly_output_snapshots': [
        ('created_by', 'VARCHAR(50)'),
        ('updated_by', 'VARCHAR(50)'),
        ('updated_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
    ],
    'inventory_counts': [
        ('updated_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
    ],
    'qms_8d_reports': [
        ('created_by', 'VARCHAR(50)'),
        ('updated_by', 'VARCHAR(50)'),
    ],
    # 第二批缺失列
    'permissions': [
        ('module_name', 'VARCHAR(100)'),
        ('action_name', 'VARCHAR(100)'),
        ('created_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
    ],
    'user_roles': [
        ('id', 'VARCHAR(36) DEFAULT gen_random_uuid()'),
        ('is_primary', 'BOOLEAN DEFAULT TRUE'),
        ('assigned_by', 'VARCHAR(50)'),
        ('assigned_at', 'TIMESTAMP'),
        ('expires_at', 'TIMESTAMP'),
    ],
    'role_permissions': [
        ('id', 'VARCHAR(36) DEFAULT gen_random_uuid()'),
        ('created_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
    ],
    'inspections': [
        ('material_id', 'VARCHAR(50)'),
        ('batch_id', 'VARCHAR(50)'),
        ('batch_size', 'INTEGER'),
        ('aql_level', 'VARCHAR(20)'),
        ('inspection_level', 'VARCHAR(20)'),
        ('sample_size', 'INTEGER'),
        ('inspected_qty', 'INTEGER'),
        ('defective_qty', 'INTEGER'),
        ('aql_result', 'VARCHAR(20)'),
        ('remarks', 'TEXT'),
        ('updated_by', 'VARCHAR(50)'),
    ],
    'defects': [
        ('inspection_id', 'VARCHAR(36)'),
        ('material_id', 'VARCHAR(50)'),
        ('batch_id', 'VARCHAR(50)'),
        ('station_id', 'VARCHAR(50)'),
        ('status', 'VARCHAR(20) DEFAULT \'open\''),
        ('disposition_by', 'VARCHAR(50)'),
        ('disposition_at', 'TIMESTAMP'),
        ('disposition_qty', 'INTEGER'),
        ('disposition_remark', 'TEXT'),
        ('ocap_status', 'VARCHAR(20)'),
        ('ocap_triggered_at', 'TIMESTAMP'),
        ('ocap_trigger_reason', 'TEXT'),
        ('updated_by', 'VARCHAR(50)'),
    ],
    'training_records': [
        ('user_id', 'VARCHAR(36)'),
        ('training_type', 'VARCHAR(50)'),
        ('trainer', 'VARCHAR(100)'),
        ('start_date', 'DATE'),
        ('end_date', 'DATE'),
        ('hours', 'FLOAT'),
        ('result', 'VARCHAR(20)'),
        ('certificate_no', 'VARCHAR(100)'),
    ],
    'quality_defects': [
        ('inspection_id', 'VARCHAR(36)'),
        ('defect_category', 'VARCHAR(50)'),
        ('defect_description', 'TEXT'),
        ('operation_seq', 'INTEGER'),
        ('station_id', 'VARCHAR(50)'),
        ('quantity', 'INTEGER'),
    ],
    'capa_cases': [
        ('case_number', 'VARCHAR(50)'),
        ('problem_description', 'TEXT'),
        ('discovery_date', 'DATE'),
        ('defect_severity', 'VARCHAR(20)'),
        ('deadline', 'DATE'),
        ('effectiveness_check_date', 'DATE'),
        ('verification_result', 'TEXT'),
        ('preventive_scope', 'TEXT'),
        ('action_logs', 'JSON DEFAULT \'[]\'::jsonb'),
        ('why_analysis', 'TEXT'),
        ('fishbone_dimensions', 'JSON DEFAULT \'{}\'::jsonb'),
        ('interim_actions_detailed', 'TEXT'),
        ('corrective_action_plans', 'TEXT'),
        ('verification_results', 'TEXT'),
        ('preventive_updates', 'TEXT'),
        ('lessons_learned_doc', 'TEXT'),
    ],
    'quality_costs': [
        ('related_capa_id', 'VARCHAR(36)'),
        ('currency', 'VARCHAR(10) DEFAULT \'CNY\''),
        ('cost_date', 'DATE'),
    ],
    'process_capability': [
        ('station_id', 'VARCHAR(50)'),
        ('operation_name', 'VARCHAR(100)'),
        ('characteristic', 'VARCHAR(100)'),
        ('specification_min', 'FLOAT'),
        ('specification_max', 'FLOAT'),
        ('mean_value', 'FLOAT'),
        ('standard_deviation', 'FLOAT'),
        ('sampling_size', 'INTEGER'),
        ('sample_date', 'DATE'),
        ('status', 'VARCHAR(20) DEFAULT \'active\''),
        ('updated_by', 'VARCHAR(50)'),
    ],
    'spc_configs': [
        ('station_id', 'VARCHAR(50)'),
        ('characteristic_code', 'VARCHAR(100)'),
        ('sample_interval', 'INTEGER'),
        ('control_rule', 'VARCHAR(50)'),
        ('updated_by', 'VARCHAR(50)'),
    ],
}


async def fix_schema():
    async with db_config.session_factory() as db:
        # 1. 创建缺失的表
        print("=== 创建缺失的表 ===")
        for table_name, columns in MISSING_TABLES.items():
            exists = await db.execute(text(
                f"SELECT count(*) FROM information_schema.tables WHERE table_name='{table_name}'"
            ))
            if exists.scalar() > 0:
                print(f"  SKIP {table_name} (已存在)")
                continue
            
            col_defs = ', '.join(f'{c[0]} {c[1]}' for c in columns)
            sql = f"CREATE TABLE {table_name} ({col_defs})"
            try:
                await db.execute(text(sql))
                await db.commit()
                print(f"  OK   {table_name}")
            except Exception as e:
                await db.rollback()
                print(f"  FAIL {table_name}: {e}")

        # 2. 添加缺失的列
        print("\n=== 添加缺失的列 ===")
        for table_name, columns in MISSING_COLUMNS.items():
            for col_name, col_type in columns:
                try:
                    sql = f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {col_name} {col_type}"
                    await db.execute(text(sql))
                    await db.commit()
                    print(f"  OK   {table_name}.{col_name}")
                except Exception as e:
                    await db.rollback()
                    print(f"  FAIL {table_name}.{col_name}: {e}")

        # 3. 验证
        print("\n=== 验证结果 ===")
        issues = []
        metadata = Base.metadata
        for table_name, table in metadata.tables.items():
            exists = await db.execute(text(
                f"SELECT count(*) FROM information_schema.tables WHERE table_name='{table_name}'"
            ))
            if exists.scalar() == 0:
                issues.append(f'TABLE_MISSING: {table_name}')
                continue
            cols = await db.execute(text(
                f"SELECT column_name FROM information_schema.columns WHERE table_name='{table_name}'"
            ))
            db_cols = {row[0] for row in cols.fetchall()}
            for col_name in table.columns.keys():
                if col_name not in db_cols:
                    issues.append(f'{table_name}.{col_name} MISSING')
        
        if issues:
            print(f"  仍有 {len(issues)} 个问题:")
            for i in issues[:20]:
                print(f"    - {i}")
            if len(issues) > 20:
                print(f"    ... 还有 {len(issues) - 20} 个")
        else:
            print("  所有模型列与数据库列完全匹配!")

if __name__ == '__main__':
    asyncio.run(fix_schema())
