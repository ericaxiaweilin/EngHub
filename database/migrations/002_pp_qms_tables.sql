-- EngHub PP & QMS Database Migration
-- Tables: Production Planning, Quality Management
-- Created: 2026-02-24

-- ============================================
-- PP - Production Planning Tables
-- ============================================

-- 生产计划表 (MPS)
CREATE TABLE IF NOT EXISTS pp_plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    plan_code VARCHAR(50) UNIQUE NOT NULL,
    plan_type VARCHAR(20) NOT NULL DEFAULT 'mps',  -- mps, forecast
    product_id VARCHAR(50) NOT NULL,
    sales_order_id VARCHAR(50),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    required_date DATE NOT NULL,
    due_date DATE,
    customer_level VARCHAR(10) DEFAULT 'b',  -- vip, a, b, c
    priority INTEGER DEFAULT 50,
    priority_score DECIMAL(10, 2),
    status VARCHAR(20) DEFAULT 'draft',  -- draft, confirmed, released, in_progress, completed, cancelled
    
    -- 排产信息
    station_id VARCHAR(50),
    scheduled_start_date DATE,
    scheduled_end_date DATE,
    
    -- 物料需求
    mrp_status VARCHAR(20) DEFAULT 'pending',
    
    created_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT fk_plan_factory FOREIGN KEY (factory_id) REFERENCES factories(id)
);

CREATE INDEX idx_pp_plans_factory ON pp_plans(factory_id);
CREATE INDEX idx_pp_plans_status ON pp_plans(status);
CREATE INDEX idx_pp_plans_product ON pp_plans(product_id);
CREATE INDEX idx_pp_plans_required_date ON pp_plans(required_date);
CREATE INDEX idx_pp_plans_priority ON pp_plans(priority_score DESC);

-- MRP计算结果表
CREATE TABLE IF NOT EXISTS mrp_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    plan_id UUID NOT NULL,
    calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    target_date DATE,
    status VARCHAR(20) DEFAULT 'pending',
    
    total_required DECIMAL(18, 4),
    total_available DECIMAL(18, 4),
    total_shortage DECIMAL(18, 4),
    total_value DECIMAL(18, 2),
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT fk_mrp_result_plan FOREIGN KEY (plan_id) REFERENCES pp_plans(id)
);

CREATE INDEX idx_mrp_results_plan ON mrp_results(plan_id);

-- MRP物料明细表
CREATE TABLE IF NOT EXISTS mrp_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mrp_result_id UUID NOT NULL,
    material_id VARCHAR(50) NOT NULL,
    material_code VARCHAR(50),
    material_name VARCHAR(200),
    
    required_qty DECIMAL(18, 4) NOT NULL,
    available_qty DECIMAL(18, 4),
    reserved_qty DECIMAL(18, 4),
    on_order_qty DECIMAL(18, 4),
    shortage_qty DECIMAL(18, 4),
    
    unit VARCHAR(20),
    unit_cost DECIMAL(18, 4),
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT fk_mrp_item_result FOREIGN KEY (mrp_result_id) REFERENCES mrp_results(id)
);

CREATE INDEX idx_mrp_items_material ON mrp_items(material_id);

-- 采购建议表
CREATE TABLE IF NOT EXISTS purchase_suggestions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    mrp_item_id UUID,
    material_id VARCHAR(50) NOT NULL,
    material_code VARCHAR(50),
    material_name VARCHAR(200),
    
    required_qty DECIMAL(18, 4),
    suggested_qty DECIMAL(18, 4),
    suggested_date DATE,
    priority VARCHAR(20) DEFAULT 'normal',  -- urgent, high, normal, low
    
    estimated_cost DECIMAL(18, 2),
    supplier_id VARCHAR(50),
    supplier_name VARCHAR(200),
    
    status VARCHAR(20) DEFAULT 'pending',  -- pending, ordered, partial, received
    
    purchase_order_id VARCHAR(50),
    suggested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT fk_purchase_suggestion_mrp FOREIGN KEY (mrp_item_id) REFERENCES mrp_items(id)
);

CREATE INDEX idx_purchase_suggestions_material ON purchase_suggestions(material_id);
CREATE INDEX idx_purchase_suggestions_status ON purchase_suggestions(status);

-- ============================================
-- QMS - Quality Management Tables
-- ============================================

-- 检验单表
CREATE TABLE IF NOT EXISTS qms_inspections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    inspection_code VARCHAR(50) UNIQUE NOT NULL,
    inspection_type VARCHAR(20) NOT NULL,  -- iqc, ipqc, fqc, oqc
    
    -- 关联信息
    product_id VARCHAR(50),
    material_id VARCHAR(50),
    batch_id VARCHAR(50),
    work_order_id VARCHAR(50),
    
    -- 检验数量
    batch_size INTEGER NOT NULL DEFAULT 0,
    sample_size INTEGER,
    inspected_qty INTEGER DEFAULT 0,
    defective_qty INTEGER DEFAULT 0,
    
    -- AQL设置
    aql_level DECIMAL(4, 2) DEFAULT 1.0,
    inspection_level VARCHAR(20) DEFAULT 'general_ii',
    
    -- 判定结果
    aql_result JSONB,
    status VARCHAR(20) DEFAULT 'pending',  -- pending, in_progress, passed, failed, rejected
    
    inspector_id VARCHAR(50),
    inspected_at TIMESTAMP,
    
    created_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT fk_inspection_factory FOREIGN KEY (factory_id) REFERENCES factories(id)
);

CREATE INDEX idx_qms_inspections_code ON qms_inspections(inspection_code);
CREATE INDEX idx_qms_inspections_type ON qms_inspections(inspection_type);
CREATE INDEX idx_qms_inspections_status ON qms_inspections(status);
CREATE INDEX idx_qms_inspections_work_order ON qms_inspections(work_order_id);
CREATE INDEX idx_qms_inspections_material ON qms_inspections(material_id);
CREATE INDEX idx_qms_inspections_batch ON qms_inspections(batch_id);

-- 检验明细表 (不良项记录)
CREATE TABLE IF NOT EXISTS qms_inspection_defects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    inspection_id UUID NOT NULL,
    defect_type VARCHAR(50) NOT NULL,
    defect_name VARCHAR(200),
    defect_count INTEGER NOT NULL DEFAULT 1,
    severity VARCHAR(20),  -- critical, major, minor, observation
    
    remark TEXT,
    photo_urls JSONB,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT fk_inspection_defect_inspection FOREIGN KEY (inspection_id) REFERENCES qms_inspections(id)
);

CREATE INDEX idx_inspection_defects_type ON qms_inspection_defects(defect_type);

-- 不良品单表 (批次级追溯)
CREATE TABLE IF NOT EXISTS qms_defects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    defect_code VARCHAR(50) UNIQUE NOT NULL,
    
    -- 追溯信息 (批次级)
    defect_type VARCHAR(50) NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    severity VARCHAR(20) NOT NULL,  -- critical, major, minor, observation
    
    -- 来源
    inspection_id UUID,
    work_order_id VARCHAR(50),
    material_id VARCHAR(50),
    batch_id VARCHAR(50),
    station_id VARCHAR(50),
    production_report_id VARCHAR(50),
    
    description TEXT,
    
    -- 处置
    status VARCHAR(20) DEFAULT 'open',  -- open, in_progress, resolved, closed, cancelled
    disposition VARCHAR(20),  -- rework, repair, scrap, concession, return
    disposition_qty INTEGER,
    disposition_by VARCHAR(50),
    disposition_at TIMESTAMP,
    disposition_remark TEXT,
    
    -- OCAP
    ocap_status VARCHAR(20) DEFAULT 'pending',  -- pending, triggered, in_progress, completed
    ocap_id UUID,
    ocap_trigger_reason VARCHAR(500),
    ocap_triggered_at TIMESTAMP,
    
    created_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT fk_defect_factory FOREIGN KEY (factory_id) REFERENCES factories(id),
    CONSTRAINT fk_defect_inspection FOREIGN KEY (inspection_id) REFERENCES qms_inspections(id)
);

CREATE INDEX idx_qms_defects_code ON qms_defects(defect_code);
CREATE INDEX idx_qms_defects_status ON qms_defects(status);
CREATE INDEX idx_qms_defects_type ON qms_defects(defect_type);
CREATE INDEX idx_qms_defects_work_order ON qms_defects(work_order_id);
CREATE INDEX idx_qms_defects_batch ON qms_defects(batch_id);
CREATE INDEX idx_qms_defects_material ON qms_defects(material_id);
CREATE INDEX idx_qms_defects_ocap ON qms_defects(ocap_status);

-- OCAP单表 (纠正措施预防措施)
CREATE TABLE IF NOT EXISTS qms_ocaps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    ocap_code VARCHAR(50) UNIQUE NOT NULL,
    defect_id UUID NOT NULL,
    
    title VARCHAR(500) NOT NULL,
    description TEXT,
    
    -- 原因分析
    root_cause TEXT,
    root_cause_analysis_by VARCHAR(50),
    root_cause_analysis_at TIMESTAMP,
    
    -- 纠正措施
    corrective_action TEXT,
    corrective_action_by VARCHAR(50),
    corrective_action_deadline DATE,
    corrective_action_completed_at TIMESTAMP,
    
    -- 预防措施
    preventive_action TEXT,
    preventive_action_by VARCHAR(50),
    preventive_action_deadline DATE,
    preventive_action_completed_at TIMESTAMP,
    
    status VARCHAR(20) DEFAULT 'pending',  -- pending, in_progress, completed, closed
    
    created_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT fk_ocap_factory FOREIGN KEY (factory_id) REFERENCES factories(id),
    CONSTRAINT fk_ocap_defect FOREIGN KEY (defect_id) REFERENCES qms_defects(id)
);

CREATE INDEX idx_qms_ocaps_code ON qms_ocaps(ocap_code);
CREATE INDEX idx_qms_ocaps_defect ON qms_ocaps(defect_id);
CREATE INDEX idx_qms_ocaps_status ON qms_ocaps(status);

-- 报工Comment表 (报工修改记录)
CREATE TABLE IF NOT EXISTS production_report_comments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(50) NOT NULL,
    report_id UUID NOT NULL,
    
    comment_text TEXT NOT NULL,
    comment_type VARCHAR(20) DEFAULT 'normal',  -- normal, correction, revision
    
    created_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT fk_report_comment_factory FOREIGN KEY (factory_id) REFERENCES factories(id)
);

CREATE INDEX idx_report_comments_report ON production_report_comments(report_id);

-- ============================================
-- Comments
-- ============================================

COMMENT ON TABLE pp_plans IS '生产计划表 (MPS)';
COMMENT ON TABLE mrp_results IS 'MRP计算结果表';
COMMENT ON TABLE mrp_items IS 'MRP物料明细表';
COMMENT ON TABLE purchase_suggestions IS '采购建议表';
COMMENT ON TABLE qms_inspections IS '检验单表';
COMMENT ON TABLE qms_inspection_defects IS '检验明细表';
COMMENT ON TABLE qms_defects IS '不良品单表';
COMMENT ON TABLE qms_ocaps IS 'OCAP单表';
COMMENT ON TABLE production_report_comments IS '报工Comment表';
