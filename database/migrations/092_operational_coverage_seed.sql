-- 092: 补齐两家演示工厂的运行数据覆盖
--
-- 仅补缺失的 coverage_seed 记录，不删除或更新已有业务数据。
-- 这些记录用于保证 QMS、追溯、PP 和今日出勤的 API/Chatbot 联调链路有
-- 完整的最小事实来源；所有外键均从当前工厂已有主数据中选择。

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 1. 电子厂缺失一条 PP/MPS 计划；机械厂已有真实计划，不重复插入。
INSERT INTO pp_plans (
    id, factory_id, plan_code, plan_type, product_id, sales_order_id,
    quantity, required_date, due_date, customer_level, priority,
    priority_score, status, release_status, mrp_status, created_by,
    updated_by, released_by, created_at, updated_at, released_at,
    update_reason
)
SELECT
    md5('coverage-pp-plan:' || p.id)::varchar,
    p.factory_id,
    'PP-COVERAGE-ELEC-20260813',
    'mps',
    p.id,
    NULL,
    120,
    CURRENT_DATE + 21,
    CURRENT_DATE + 21,
    'A',
    2,
    86.0,
    'released',
    'released',
    'pending',
    'coverage_seed',
    'coverage_seed',
    'coverage_seed',
    NOW() - INTERVAL '2 days',
    NOW(),
    NOW() - INTERVAL '1 day',
    '092 operational coverage seed'
FROM products p
WHERE p.factory_id = 'FAC_ELEC_DEMO_2026'
  AND NOT EXISTS (
      SELECT 1 FROM pp_plans x
      WHERE x.plan_code = 'PP-COVERAGE-ELEC-20260813'
  )
ORDER BY p.id
LIMIT 1;

-- Shared references used by QMS and traceability rows.  A separate insert is
-- used per factory so every record remains tenant-local.

-- 2. Quality inspection evidence: one PASS and one FAIL per factory.
INSERT INTO quality_inspections (
    id, factory_id, work_order_id, routing_step_id, inspect_type,
    inspection_phase, inspector_id, sample_qty, sampling_method,
    defect_qty, result, defect_details, remark, created_at
)
SELECT
    md5('coverage-quality:' || v.factory_id || ':' || v.result)::varchar,
    v.factory_id,
    wo.id,
    rs.id,
    v.inspect_type,
    v.inspect_phase,
    COALESCE(op.id, 'coverage_seed'),
    v.sample_qty,
    'coverage_seed',
    v.defect_qty,
    v.result,
    CASE WHEN v.defect_qty > 0
         THEN json_build_object('source', 'coverage_seed', 'defect_type', 'dimension')
         ELSE NULL END,
    '092 operational coverage seed',
    NOW() - v.age
FROM (
    VALUES
        ('FAC_ELEC_DEMO_2026', 'IPQC', 'process', 'PASS', 20, 0, INTERVAL '2 hours'),
        ('FAC_ELEC_DEMO_2026', 'FQC',  'final',   'FAIL', 20, 1, INTERVAL '1 hour'),
        ('FAC_MECH_001',       'IPQC', 'process', 'PASS', 20, 0, INTERVAL '2 hours'),
        ('FAC_MECH_001',       'FQC',  'final',   'FAIL', 20, 1, INTERVAL '1 hour')
) AS v(factory_id, inspect_type, inspect_phase, result, sample_qty, defect_qty, age)
JOIN LATERAL (
    SELECT w.id
    FROM work_orders w
    WHERE w.factory_id = v.factory_id
    ORDER BY w.created_at DESC NULLS LAST, w.id
    LIMIT 1
) wo ON TRUE
JOIN LATERAL (
    SELECT rs.id
    FROM routing_steps rs
    JOIN routings r ON r.id = rs.routing_id
    WHERE r.factory_id = v.factory_id
    ORDER BY rs.id
    LIMIT 1
) rs ON TRUE
LEFT JOIN LATERAL (
    SELECT o.id
    FROM operators o
    WHERE o.factory_id = v.factory_id
    ORDER BY o.id
    LIMIT 1
) op ON TRUE
WHERE NOT EXISTS (
    SELECT 1
    FROM quality_inspections qi
    WHERE qi.id = md5('coverage-quality:' || v.factory_id || ':' || v.result)::varchar
);

-- 3. One traceable defect per factory, linked to existing MES records.
INSERT INTO defect_records (
    id, record_code, factory_id, work_order_id, product_id, station_id,
    equipment_id, defect_type, severity, quantity, batch_code,
    disposition, disposition_by, disposition_at, disposition_remark,
    ocap_status, description, defect_source, root_cause_category,
    root_cause, responsible_dept, discovery_stage, discovery_time,
    corrective_action, preventive_action, process_step, review_status,
    created_by, created_at, updated_at, is_finalized
)
SELECT
    md5('coverage-defect:' || v.factory_id)::varchar,
    v.record_code,
    v.factory_id,
    wo.id,
    p.id,
    COALESCE(rs.station_id, 'COVERAGE-STATION'),
    eq.id,
    'dimension',
    'minor',
    1,
    'BATCH-COVERAGE-' || v.short_code,
    'rework',
    'coverage_seed',
    NOW() - INTERVAL '30 minutes',
    'coverage seed；待品质确认后关闭',
    'triggered',
    '联调覆盖用尺寸偏差记录，不代表现场真实异常',
    'process',
    'measurement',
    'coverage seed',
    'QA',
    'IPQC',
    NOW() - INTERVAL '1 hour',
    '复测并确认量具状态',
    '将关键尺寸纳入首件与巡检项目',
    COALESCE(rs.operation_name, 'coverage'),
    'pending',
    'coverage_seed',
    NOW() - INTERVAL '1 hour',
    NOW(),
    FALSE
FROM (
    VALUES
        ('FAC_ELEC_DEMO_2026', 'ELEC', 'DEF-COVERAGE-ELEC-001'),
        ('FAC_MECH_001',       'MECH', 'DEF-COVERAGE-MECH-001')
) AS v(factory_id, short_code, record_code)
JOIN LATERAL (
    SELECT w.id
    FROM work_orders w
    WHERE w.factory_id = v.factory_id
    ORDER BY w.created_at DESC NULLS LAST, w.id
    LIMIT 1
) wo ON TRUE
JOIN LATERAL (
    SELECT p.id
    FROM products p
    WHERE p.factory_id = v.factory_id
    ORDER BY p.id
    LIMIT 1
) p ON TRUE
LEFT JOIN LATERAL (
    SELECT rs.station_id, rs.operation_name
    FROM routing_steps rs
    JOIN routings r ON r.id = rs.routing_id
    WHERE r.factory_id = v.factory_id
    ORDER BY rs.id
    LIMIT 1
) rs ON TRUE
LEFT JOIN LATERAL (
    SELECT e.id
    FROM equipment e
    WHERE e.factory_id = v.factory_id
    ORDER BY e.id
    LIMIT 1
) eq ON TRUE
WHERE NOT EXISTS (
    SELECT 1 FROM defect_records d WHERE d.record_code = v.record_code
);

-- 4. Three-level traceability chain per factory: raw -> semi -> finished.
-- Insert in dependency order because next_item_code is self-referencing.
INSERT INTO item_traceability (
    id, item_code, item_type, factory_id, work_order_id, product_id,
    material_batch_id, material_supplier_id, station_id, equipment_id,
    operator_id, quality_check_result, serial_number, next_item_code,
    metadata, created_by, created_at, updated_at
)
SELECT
    md5('coverage-trace:' || v.factory_id || ':fg')::varchar,
    'TRACE-COVERAGE-' || v.short_code || '-FG-001',
    'finished',
    v.factory_id,
    wo.id,
    p.id,
    'BATCH-COVERAGE-' || v.short_code || '-FG',
    'SUP-COVERAGE-' || v.short_code,
    rs.station_id,
    eq.id,
    op.id,
    'pass',
    'SN-COVERAGE-' || v.short_code || '-FG-001',
    NULL,
    jsonb_build_object('source', 'coverage_seed', 'trace_stage', 'finished'),
    'coverage_seed',
    NOW() - INTERVAL '3 hours',
    NOW()
FROM (VALUES ('FAC_ELEC_DEMO_2026', 'ELEC'), ('FAC_MECH_001', 'MECH')) v(factory_id, short_code)
JOIN LATERAL (SELECT w.id FROM work_orders w WHERE w.factory_id=v.factory_id ORDER BY w.created_at DESC NULLS LAST, w.id LIMIT 1) wo ON TRUE
JOIN LATERAL (SELECT p.id FROM products p WHERE p.factory_id=v.factory_id ORDER BY p.id LIMIT 1) p ON TRUE
LEFT JOIN LATERAL (SELECT rs.station_id FROM routing_steps rs JOIN routings r ON r.id=rs.routing_id WHERE r.factory_id=v.factory_id ORDER BY rs.id LIMIT 1) rs ON TRUE
LEFT JOIN LATERAL (SELECT e.id FROM equipment e WHERE e.factory_id=v.factory_id ORDER BY e.id LIMIT 1) eq ON TRUE
LEFT JOIN LATERAL (SELECT o.id FROM operators o WHERE o.factory_id=v.factory_id ORDER BY o.id LIMIT 1) op ON TRUE
WHERE NOT EXISTS (SELECT 1 FROM item_traceability t WHERE t.item_code='TRACE-COVERAGE-' || v.short_code || '-FG-001');

INSERT INTO item_traceability (
    id, item_code, item_type, factory_id, work_order_id, product_id,
    material_batch_id, material_supplier_id, station_id, equipment_id,
    operator_id, quality_check_result, serial_number, next_item_code,
    metadata, created_by, created_at, updated_at
)
SELECT
    md5('coverage-trace:' || v.factory_id || ':semi')::varchar,
    'TRACE-COVERAGE-' || v.short_code || '-SF-001',
    'semi_finished',
    v.factory_id,
    wo.id,
    p.id,
    'BATCH-COVERAGE-' || v.short_code || '-SF',
    'SUP-COVERAGE-' || v.short_code,
    rs.station_id,
    eq.id,
    op.id,
    'pass',
    'SN-COVERAGE-' || v.short_code || '-SF-001',
    'TRACE-COVERAGE-' || v.short_code || '-FG-001',
    jsonb_build_object('source', 'coverage_seed', 'trace_stage', 'semi_finished'),
    'coverage_seed',
    NOW() - INTERVAL '4 hours',
    NOW()
FROM (VALUES ('FAC_ELEC_DEMO_2026', 'ELEC'), ('FAC_MECH_001', 'MECH')) v(factory_id, short_code)
JOIN LATERAL (SELECT w.id FROM work_orders w WHERE w.factory_id=v.factory_id ORDER BY w.created_at DESC NULLS LAST, w.id LIMIT 1) wo ON TRUE
JOIN LATERAL (SELECT p.id FROM products p WHERE p.factory_id=v.factory_id ORDER BY p.id LIMIT 1) p ON TRUE
LEFT JOIN LATERAL (SELECT rs.station_id FROM routing_steps rs JOIN routings r ON r.id=rs.routing_id WHERE r.factory_id=v.factory_id ORDER BY rs.id LIMIT 1) rs ON TRUE
LEFT JOIN LATERAL (SELECT e.id FROM equipment e WHERE e.factory_id=v.factory_id ORDER BY e.id LIMIT 1) eq ON TRUE
LEFT JOIN LATERAL (SELECT o.id FROM operators o WHERE o.factory_id=v.factory_id ORDER BY o.id LIMIT 1) op ON TRUE
WHERE NOT EXISTS (SELECT 1 FROM item_traceability t WHERE t.item_code='TRACE-COVERAGE-' || v.short_code || '-SF-001');

INSERT INTO item_traceability (
    id, item_code, item_type, factory_id, work_order_id, product_id,
    material_batch_id, material_supplier_id, station_id, equipment_id,
    operator_id, quality_check_result, serial_number, next_item_code,
    metadata, created_by, created_at, updated_at
)
SELECT
    md5('coverage-trace:' || v.factory_id || ':raw')::varchar,
    'TRACE-COVERAGE-' || v.short_code || '-RM-001',
    'raw_material',
    v.factory_id,
    wo.id,
    p.id,
    'BATCH-COVERAGE-' || v.short_code || '-RM',
    'SUP-COVERAGE-' || v.short_code,
    rs.station_id,
    eq.id,
    op.id,
    'pass',
    'SN-COVERAGE-' || v.short_code || '-RM-001',
    'TRACE-COVERAGE-' || v.short_code || '-SF-001',
    jsonb_build_object('source', 'coverage_seed', 'trace_stage', 'raw_material'),
    'coverage_seed',
    NOW() - INTERVAL '5 hours',
    NOW()
FROM (VALUES ('FAC_ELEC_DEMO_2026', 'ELEC'), ('FAC_MECH_001', 'MECH')) v(factory_id, short_code)
JOIN LATERAL (SELECT w.id FROM work_orders w WHERE w.factory_id=v.factory_id ORDER BY w.created_at DESC NULLS LAST, w.id LIMIT 1) wo ON TRUE
JOIN LATERAL (SELECT p.id FROM products p WHERE p.factory_id=v.factory_id ORDER BY p.id LIMIT 1) p ON TRUE
LEFT JOIN LATERAL (SELECT rs.station_id FROM routing_steps rs JOIN routings r ON r.id=rs.routing_id WHERE r.factory_id=v.factory_id ORDER BY rs.id LIMIT 1) rs ON TRUE
LEFT JOIN LATERAL (SELECT e.id FROM equipment e WHERE e.factory_id=v.factory_id ORDER BY e.id LIMIT 1) eq ON TRUE
LEFT JOIN LATERAL (SELECT o.id FROM operators o WHERE o.factory_id=v.factory_id ORDER BY o.id LIMIT 1) op ON TRUE
WHERE NOT EXISTS (SELECT 1 FROM item_traceability t WHERE t.item_code='TRACE-COVERAGE-' || v.short_code || '-RM-001');

-- 5. Today's attendance coverage. Existing attendance rows are untouched.
INSERT INTO attendance (
    id, factory_id, operator_id, date, check_in, check_out,
    shift, status, created_at
)
SELECT
    md5('coverage-attendance:' || o.factory_id || ':' || o.id || ':' || CURRENT_DATE::text)::varchar,
    o.factory_id,
    o.id,
    CURRENT_DATE::text,
    CURRENT_DATE + TIME '08:00',
    NULL,
    '白班',
    'present',
    NOW()
FROM (
    SELECT o.*, ROW_NUMBER() OVER (PARTITION BY o.factory_id ORDER BY o.id) AS rn
    FROM operators o
    WHERE o.factory_id IN ('FAC_ELEC_DEMO_2026', 'FAC_MECH_001')
) o
WHERE o.rn <= 3
  AND NOT EXISTS (
      SELECT 1 FROM attendance a
      WHERE a.id = md5('coverage-attendance:' || o.factory_id || ':' || o.id || ':' || CURRENT_DATE::text)::varchar
  );
