-- 019: QMS 质量管理增强
-- 检验项明细 + SPC 控制图 + 8D 报告

-- 检验项明细（每个检验单包含多个检测项）
CREATE TABLE IF NOT EXISTS qms_inspection_items (
  id VARCHAR(36) PRIMARY KEY,
  inspection_id VARCHAR(36) NOT NULL REFERENCES quality_inspections(id),
  item_name VARCHAR(100) NOT NULL,
  item_code VARCHAR(50),
  spec_lower FLOAT,
  spec_upper FLOAT,
  target_value FLOAT,
  measured_value FLOAT,
  result VARCHAR(10),
  measurement_method VARCHAR(50),
  remark VARCHAR(200)
);
CREATE INDEX IF NOT EXISTS idx_qii_inspection ON qms_inspection_items(inspection_id);

-- SPC 控制图数据点
CREATE TABLE IF NOT EXISTS qms_spc_points (
  id VARCHAR(36) PRIMARY KEY,
  factory_id VARCHAR(50) NOT NULL,
  characteristic_code VARCHAR(50) NOT NULL,
  characteristic_name VARCHAR(100),
  work_order_id VARCHAR(36),
  station_id VARCHAR(50),
  measured_value FLOAT NOT NULL,
  sample_group INT,
  ucl FLOAT,
  lcl FLOAT,
  cl FLOAT,
  is_out_of_control BOOLEAN DEFAULT FALSE,
  measured_at TIMESTAMP DEFAULT NOW(),
  measured_by VARCHAR(50)
);
CREATE INDEX IF NOT EXISTS idx_spc_char ON qms_spc_points(factory_id, characteristic_code, measured_at);

-- 8D 报告
CREATE TABLE IF NOT EXISTS qms_8d_reports (
  id VARCHAR(36) PRIMARY KEY,
  report_code VARCHAR(50) UNIQUE NOT NULL,
  factory_id VARCHAR(50) NOT NULL,
  defect_record_id VARCHAR(36) REFERENCES defect_records(id),
  title VARCHAR(200) NOT NULL,
  severity VARCHAR(20) DEFAULT 'major',
  status VARCHAR(20) DEFAULT 'open',
  d1_team TEXT,
  d2_problem_description TEXT,
  d3_containment_action TEXT,
  d4_root_cause TEXT,
  d5_corrective_action TEXT,
  d6_implementation TEXT,
  d7_preventive_action TEXT,
  d8_congratulations TEXT,
  opened_by VARCHAR(50),
  closed_by VARCHAR(50),
  due_date TIMESTAMP,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_8d_factory ON qms_8d_reports(factory_id, status);
