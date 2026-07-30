-- Business completeness fields identified by the MES/IE/QMS/WMS audit.
-- Every statement is idempotent so this migration can be applied during deployment.

ALTER TABLE IF EXISTS work_orders
    ADD COLUMN IF NOT EXISTS current_stage VARCHAR(100),
    ADD COLUMN IF NOT EXISTS next_station VARCHAR(100),
    ADD COLUMN IF NOT EXISTS in_progress_status VARCHAR(30),
    ADD COLUMN IF NOT EXISTS partial_completion_percentage DOUBLE PRECISION DEFAULT 0;

ALTER TABLE IF EXISTS production_reports
    ADD COLUMN IF NOT EXISTS assistant_operator_ids JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS quality_check_passed BOOLEAN,
    ADD COLUMN IF NOT EXISTS operation_seq INTEGER,
    ADD COLUMN IF NOT EXISTS operation_name VARCHAR(100),
    ADD COLUMN IF NOT EXISTS machine_id VARCHAR(50),
    ADD COLUMN IF NOT EXISTS start_time TIMESTAMP,
    ADD COLUMN IF NOT EXISTS end_time TIMESTAMP;

ALTER TABLE IF EXISTS quality_inspections
    ADD COLUMN IF NOT EXISTS inspection_phase VARCHAR(30),
    ADD COLUMN IF NOT EXISTS sampling_method VARCHAR(100),
    ADD COLUMN IF NOT EXISTS check_tool_id VARCHAR(50);

ALTER TABLE IF EXISTS standard_operation_times
    ADD COLUMN IF NOT EXISTS operation_seq INTEGER,
    ADD COLUMN IF NOT EXISTS setup_before_start_time_min DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS post_operation_time_min DOUBLE PRECISION;

ALTER TABLE IF EXISTS action_studies
    ADD COLUMN IF NOT EXISTS recorded_by VARCHAR(50),
    ADD COLUMN IF NOT EXISTS motions JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS total_time_cycles DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS analysis_result JSONB DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS motion_analysis_result JSONB DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS ergonomic_score DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS recommended_improvement_suggestion TEXT;

ALTER TABLE IF EXISTS method_studies
    ADD COLUMN IF NOT EXISTS old_method_description TEXT,
    ADD COLUMN IF NOT EXISTS improved_method_diagram_url VARCHAR(500),
    ADD COLUMN IF NOT EXISTS expected_time_saving_calculation_detail JSONB DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS action_sequence JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS required_resources JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS setup_time_min DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS cycle_time_min DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS total_standard_time_min DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS validity_start TIMESTAMP,
    ADD COLUMN IF NOT EXISTS validity_end TIMESTAMP,
    ADD COLUMN IF NOT EXISTS approved_by VARCHAR(50),
    ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'draft';

ALTER TABLE IF EXISTS kanban_systems
    ADD COLUMN IF NOT EXISTS kanban_card_image_url VARCHAR(500),
    ADD COLUMN IF NOT EXISTS trigger_rule_type VARCHAR(50),
    ADD COLUMN IF NOT EXISTS min_max_stock_levels_detail JSONB DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS max_card_count INTEGER,
    ADD COLUMN IF NOT EXISTS current_card_count INTEGER,
    ADD COLUMN IF NOT EXISTS safety_stock_level INTEGER,
    ADD COLUMN IF NOT EXISTS card_status VARCHAR(20),
    ADD COLUMN IF NOT EXISTS last_used_at TIMESTAMP;

ALTER TABLE IF EXISTS equipment
    ADD COLUMN IF NOT EXISTS manufacturer_model VARCHAR(100),
    ADD COLUMN IF NOT EXISTS serial_number VARCHAR(100),
    ADD COLUMN IF NOT EXISTS purchase_date DATE,
    ADD COLUMN IF NOT EXISTS warranty_expiry DATE,
    ADD COLUMN IF NOT EXISTS maintenance_interval_days INTEGER;

ALTER TABLE IF EXISTS maintenance_orders
    ADD COLUMN IF NOT EXISTS parts_used JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS labor_hours DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS cost_analysis JSONB DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS failure_root_cause_code VARCHAR(50);

ALTER TABLE IF EXISTS locations
    ADD COLUMN IF NOT EXISTS aisle VARCHAR(30),
    ADD COLUMN IF NOT EXISTS rack VARCHAR(30),
    ADD COLUMN IF NOT EXISTS level VARCHAR(30),
    ADD COLUMN IF NOT EXISTS bin_code VARCHAR(30);

ALTER TABLE IF EXISTS inventory
    ADD COLUMN IF NOT EXISTS expiry_date DATE,
    ADD COLUMN IF NOT EXISTS storage_location VARCHAR(100),
    ADD COLUMN IF NOT EXISTS qualified_status VARCHAR(20) DEFAULT 'qualified';

ALTER TABLE IF EXISTS inventory_transactions
    ADD COLUMN IF NOT EXISTS reference_doc_no VARCHAR(100),
    ADD COLUMN IF NOT EXISTS reason_code VARCHAR(50);

ALTER TABLE IF EXISTS products
    ADD COLUMN IF NOT EXISTS current_routing_id VARCHAR(50),
    ADD COLUMN IF NOT EXISTS engineering_lead_time_days DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS manufacturing_lead_time_days DOUBLE PRECISION;

ALTER TABLE IF EXISTS routing_template_steps
    ADD COLUMN IF NOT EXISTS quality_requirement TEXT,
    ADD COLUMN IF NOT EXISTS sop_document_url VARCHAR(500),
    ADD COLUMN IF NOT EXISTS tooling_requirement JSONB DEFAULT '{}'::jsonb;

ALTER TABLE IF EXISTS pp_plans
    ADD COLUMN IF NOT EXISTS planning_cycle VARCHAR(30),
    ADD COLUMN IF NOT EXISTS release_status VARCHAR(20) DEFAULT 'unreleased',
    ADD COLUMN IF NOT EXISTS planner_id VARCHAR(50);

ALTER TABLE IF EXISTS aps_schedules
    ADD COLUMN IF NOT EXISTS priority_level VARCHAR(20),
    ADD COLUMN IF NOT EXISTS constraint_type VARCHAR(50),
    ADD COLUMN IF NOT EXISTS feasibility_status VARCHAR(20);

ALTER TABLE IF EXISTS aps_schedule_tasks
    ADD COLUMN IF NOT EXISTS actual_start TIMESTAMP,
    ADD COLUMN IF NOT EXISTS actual_end TIMESTAMP,
    ADD COLUMN IF NOT EXISTS deviation_reason TEXT;

ALTER TABLE IF EXISTS defect_records
    ADD COLUMN IF NOT EXISTS defect_classification VARCHAR(50),
    ADD COLUMN IF NOT EXISTS failure_mode VARCHAR(100),
    ADD COLUMN IF NOT EXISTS rpn_value INTEGER,
    ADD COLUMN IF NOT EXISTS corrective_action_link VARCHAR(500);

ALTER TABLE IF EXISTS capa_cases
    ADD COLUMN IF NOT EXISTS effectiveness_check_date TIMESTAMP,
    ADD COLUMN IF NOT EXISTS verification_result TEXT,
    ADD COLUMN IF NOT EXISTS preventive_scope TEXT;

ALTER TABLE IF EXISTS qms_spc_points
    ADD COLUMN IF NOT EXISTS control_chart_type VARCHAR(30),
    ADD COLUMN IF NOT EXISTS calculation_method VARCHAR(50),
    ADD COLUMN IF NOT EXISTS subgroup_count INTEGER;

ALTER TABLE IF EXISTS employee_skills
    ADD COLUMN IF NOT EXISTS training_record_link VARCHAR(500),
    ADD COLUMN IF NOT EXISTS competency_assessment_score NUMERIC(5, 2),
    ADD COLUMN IF NOT EXISTS skill_level_date DATE;

ALTER TABLE IF EXISTS training_records
    ADD COLUMN IF NOT EXISTS notes TEXT;
