-- ============================================================
-- 038 RCC Data Layer Seed — 全局统筹人/物/工单计算
-- RCC = Resource Control Center, 不是UI面板，是数据层
-- 核心：global_adjustable_params seed + baseline计算所需索引 + org结构补全
-- ============================================================

-- ── 1. org_units 中 rcc-root 确保存在 ──
INSERT INTO org_units (id, code, name, parent_id, level_type, factory_id, metadata_)
VALUES (
    'rcc-root', 'RCC_ROOT', '资源控制中心', NULL, 'strategic', NULL,
    '{"type": "rcc", "description": "全局资源控制与调度中枢，提供人/物/工单/环境/工艺基线"}'
)
ON CONFLICT (id) DO UPDATE SET
    updated_at = CURRENT_TIMESTAMP;

-- ── 2. global_adjustable_params 种子数据 ──
-- 注意：global_adjustable_params 表没有 factory_id 列！只有 org_unit_id
-- 所有参数都是全局可调的，不绑定具体工位

DO $$
BEGIN
    -- ═══════════════════════════════════════
    -- 2.1 人力统筹参数
    -- ═══════════════════════════════════════
    INSERT INTO global_adjustable_params (id, param_code, param_name, category, param_type, current_value, default_value, min_value, max_value, unit, sensitivity, affects_logic_chains)
    VALUES
        (gen_random_uuid(), 'personnel_load_rate_threshold', '人力负荷率阈值', 'people', 'percentage', '85', '85', 50, 100, '%', 'high',
         '["load_alert"]'::jsonb),
        (gen_random_uuid(), 'absence_warning_threshold', '缺勤预警线', 'people', 'percentage', '3', '3', 0, 10, '%', 'normal',
         '["attendance_alert"]'::jsonb),
        (gen_random_uuid(), 'shift_ratio_day_night', '白班/夜班配比目标', 'people', 'ratio', '60/40', '60/40', NULL, NULL, NULL, 'strategic',
         '["shift_adjust"]'::jsonb),
        (gen_random_uuid(), 'min_operator_per_station', '每工位最低操作员数', 'people', 'integer', '2', '2', 1, 5, '人', 'high',
         '["staffing_alert"]'::jsonb),
        (gen_random_uuid(), 'skill_level_min_dispatch', '派工最低技能等级', 'people', 'level', 'L2', 'L2', NULL, NULL, NULL, 'high',
         '["dispatch_rule"]'::jsonb)
    ON CONFLICT (param_code) DO UPDATE SET
        current_value = EXCLUDED.current_value,
        target_value = EXCLUDED.default_value,
        updated_at = CURRENT_TIMESTAMP;

    -- ═══════════════════════════════════════
    -- 2.2 设备统筹参数
    -- ═══════════════════════════════════════
    INSERT INTO global_adjustable_params (id, param_code, param_name, category, param_type, current_value, default_value, min_value, max_value, unit, sensitivity, affects_logic_chains)
    VALUES
        (gen_random_uuid(), 'equipment_available_hours_default', '设备默认可用小时/天', 'equipment', 'hours', '16', '16', 8, 24, 'h', 'low',
         '[]'::jsonb),
        (gen_random_uuid(), 'equipment_efficiency_target', '设备效率系数目标', 'equipment', 'percentage', '85', '85', 50, 100, '%', 'normal',
         '["efficiency_alert"]'::jsonb),
        (gen_random_uuid(), 'equipment_setup_time_minutes', '默认换型时间(分钟)', 'equipment', 'minutes', '30', '30', 0, 120, 'min', 'low',
         '["scheduling_constraint"]'::jsonb),
        (gen_random_uuid(), 'oee_target_pct', 'OEE目标百分比', 'equipment', 'percentage', '80', '80', 50, 99, '%', 'normal',
         '["oee_alert"]'::jsonb),
        (gen_random_uuid(), 'pm_cycle_default_days', '预防性维护默认周期(天)', 'equipment', 'days', '7', '7', 1, 30, '天', 'normal',
         '["pm_overdue_alert"]'::jsonb),
        (gen_random_uuid(), 'pm_warning_days_before', 'PM到期前预警天数', 'equipment', 'days', '3', '3', 1, 7, '天', 'low',
         '["pm_warning"]'::jsonb),
        (gen_random_uuid(), 'equipment_downtime_alert_min', '设备停机超时报警阈值(分钟)', 'equipment', 'minutes', '30', '30', 10, 180, 'min', 'high',
         '["downtime_alert"]'::jsonb)
    ON CONFLICT (param_code) DO UPDATE SET
        current_value = EXCLUDED.current_value,
        target_value = EXCLUDED.default_value,
        updated_at = CURRENT_TIMESTAMP;

    -- ═══════════════════════════════════════
    -- 2.3 工单统筹参数
    -- ═══════════════════════════════════════
    INSERT INTO global_adjustable_params (id, param_code, param_name, category, param_type, current_value, default_value, min_value, max_value, unit, sensitivity, affects_logic_chains)
    VALUES
        (gen_random_uuid(), 'priority_weight_urgent', '紧急优先级权重', 'work_order', 'integer', '10', '10', 1, 20, '', 'normal',
         '["auto_schedule"]'::jsonb),
        (gen_random_uuid(), 'priority_weight_high', '高优先级权重', 'work_order', 'integer', '7', '7', 1, 20, '', 'normal',
         '["auto_schedule"]'::jsonb),
        (gen_random_uuid(), 'priority_weight_medium', '普通优先级权重', 'work_order', 'integer', '5', '5', 1, 20, '', 'normal',
         '["auto_schedule"]'::jsonb),
        (gen_random_uuid(), 'priority_weight_low', '低优先级权重', 'work_order', 'integer', '2', '2', 1, 20, '', 'low',
         '["auto_schedule"]'::jsonb),
        (gen_random_uuid(), 'delivery_grace_period_hours', '交期宽限期(小时)', 'work_order', 'hours', '24', '24', 0, 72, 'h', 'normal',
         '["delivery_risk"]'::jsonb),
        (gen_random_uuid(), 'max_parallel_orders_per_station', '单工位最大并行工单数', 'work_order', 'integer', '1', '1', 0, 3, '个', 'high',
         '["scheduling_constraint"]'::jsonb),
        (gen_random_uuid(), 'order_reorder_threshold', '订单重排触发阈值', 'work_order', 'percentage', '15', '15', 0, 50, '%', 'normal',
         '["auto_reschedule"]'::jsonb),
        (gen_random_uuid(), 'material_shortage_auto_postpone_hours', '物料齐套不足自动推迟时长(小时)', 'work_order', 'hours', '48', '48', 0, 168, 'h', 'high',
         '["auto_reschedule"]'::jsonb)
    ON CONFLICT (param_code) DO UPDATE SET
        current_value = EXCLUDED.current_value,
        target_value = EXCLUDED.default_value,
        updated_at = CURRENT_TIMESTAMP;

    -- ═══════════════════════════════════════
    -- 2.4 环境基线参数
    -- ═══════════════════════════════════════
    INSERT INTO global_adjustable_params (id, param_code, param_name, category, param_type, current_value, default_value, min_value, max_value, unit, sensitivity, affects_logic_chains)
    VALUES
        (gen_random_uuid(), 'env_temperature_min_c', '车间温度下限(°C)', 'environment', 'numeric', '18', '18', 10, 25, '°C', 'low',
         '["env_alert"]'::jsonb),
        (gen_random_uuid(), 'env_temperature_max_c', '车间温度上限(°C)', 'environment', 'numeric', '28', '28', 20, 35, '°C', 'low',
         '["env_alert"]'::jsonb),
        (gen_random_uuid(), 'env_humidity_min_pct', '车间湿度下限(%)', 'environment', 'numeric', '30', '30', 0, 80, '%', 'low',
         '["env_alert"]'::jsonb),
        (gen_random_uuid(), 'env_humidity_max_pct', '车间湿度上限(%)', 'environment', 'numeric', '70', '70', 40, 90, '%', 'low',
         '["env_alert"]'::jsonb),
        (gen_random_uuid(), 'env_dust_limit_ug_m3', '粉尘浓度限值(µg/m³)', 'environment', 'numeric', '100', '100', 0, 500, 'µg/m³', 'normal',
         '["cleanliness_alert"]'::jsonb),
        (gen_random_uuid(), 'env_noise_limit_db', '噪声限值(dB)', 'environment', 'numeric', '85', '85', 50, 120, 'dB', 'normal',
         '["noise_alert"]'::jsonb),
        (gen_random_uuid(), 'env_reading_interval_minutes', '环境监测采样间隔(分钟)', 'environment', 'minutes', '5', '5', 1, 30, 'min', 'low',
         '[]'::jsonb)
    ON CONFLICT (param_code) DO UPDATE SET
        current_value = EXCLUDED.current_value,
        target_value = EXCLUDED.default_value,
        updated_at = CURRENT_TIMESTAMP;

    -- ═══════════════════════════════════════
    -- 2.5 工艺基线参数
    -- ═══════════════════════════════════════
    INSERT INTO global_adjustable_params (id, param_code, param_name, category, param_type, current_value, default_value, min_value, max_value, unit, sensitivity, affects_logic_chains)
    VALUES
        (gen_random_uuid(), 'process_cycle_time_baseline', '标准节拍时间基准(秒)', 'process', 'seconds', '60', '60', 10, 300, 's', 'medium',
         '["cycle_time_alert"]'::jsonb),
        (gen_random_uuid(), 'yield_rate_target_pct', '良品率目标(%)', 'process', 'percentage', '98', '98', 90, 100, '%', 'high',
         '["yield_alert"]'::jsonb),
        (gen_random_uuid(), 'aql_level_general', '通用AQL级别', 'process', 'string', 'General-II', 'General-II', NULL, NULL, NULL, 'medium',
         '["inspection_standard"]'::jsonb),
        (gen_random_uuid(), 'defect_threshold_warn_pct', '不良率预警线(%)', 'process', 'percentage', '5', '5', 0, 20, '%', 'normal',
         '["defect_alert"]'::jsonb),
        (gen_random_uuid(), 'process_change_review_required', '工艺变更需审批标志', 'process', 'boolean', 'true', 'true', NULL, NULL, NULL, 'high',
         '["process_change_approval"]'::jsonb),
        (gen_random_uuid(), 'standard_cycle_time_by_process', '标准节拍时间配置(JSON)', 'process', 'json', '{"smt":30,"solder":45,"assembly":60,"test":120,"packaging":40}', '{"smt":30,"solder":45,"assembly":60,"test":120,"packaging":40}', NULL, NULL, NULL, 'medium',
         '["capacity_calc"]'::jsonb)
    ON CONFLICT (param_code) DO UPDATE SET
        current_value = EXCLUDED.current_value,
        target_value = EXCLUDED.default_value,
        updated_at = CURRENT_TIMESTAMP;

    -- ═══════════════════════════════════════
    -- 2.6 逻辑链触发参数
    -- ═══════════════════════════════════════
    INSERT INTO global_adjustable_params (id, param_code, param_name, category, param_type, current_value, default_value, min_value, max_value, unit, sensitivity, affects_logic_chains)
    VALUES
        (gen_random_uuid(), 'logic_chain_priority', '逻辑链执行优先级', 'logic', 'integer', '1', '1', 1, 10, '', 'normal',
         '[]'::jsonb),
        (gen_random_uuid(), 'logic_chain_enable_env_sync', '自动同步环境读数到RCC', 'logic', 'boolean', 'true', 'true', NULL, NULL, NULL, 'normal',
         '["env_auto_update"]'::jsonb),
        (gen_random_uuid(), 'logic_chain_enable_wo_alert', '工单异常自动通知', 'logic', 'boolean', 'true', 'true', NULL, NULL, NULL, 'normal',
         '["wo_auto_notify"]'::jsonb),
        (gen_random_uuid(), 'logic_chain_enable_pm_auto', 'PM逾期自动触发维护工单', 'logic', 'boolean', 'true', 'true', NULL, NULL, NULL, 'high',
         '["pm_auto_create"]'::jsonb)
    ON CONFLICT (param_code) DO UPDATE SET
        current_value = EXCLUDED.current_value,
        target_value = EXCLUDED.default_value,
        updated_at = CURRENT_TIMESTAMP;

    RAISE NOTICE '✅ RCC global_adjustable_params 种子已写入';
END $$;


-- ── 3. 预置确定性逻辑链种子 ──
INSERT INTO deterministic_logic_chains (id, chain_code, chain_name, org_unit_id, trigger_event, conditions, action_sequence, execution_order)
VALUES
    ('rc-001', 'AUTO_RESCHEDULE_ON_EQ_DOWNTIME', '设备故障→自动重排', 'rcc-root',
     'equipment_breakdown',
     '[{"field":"event.status","op":"in","value":["running","maintenance"]}]',
     '[{"type":"update_param","param_code":"scheduling_algo_override","value":"reschedule","source":"system"},{"type":"notify_org_unit","target_org_unit":"rcc-root","message":"设备故障触发自动重排"},{"type":"create_chatbot_ticket","ticket_type":"reschedule_request","message":"设备故障触发自动重排"}]'::jsonb,
     1),

    ('rc-002', 'MAT_SHORTAGE_POSTPONE_ORDER', '物料齐套不足→自动推迟工单', 'rcc-root',
     'material_shortage',
     '[{"field":"event.type","op":"eq","value":"material_shortage"}]',
     '[{"type":"update_param","param_code":"material_shortage_auto_postpone_hours","value":"48","source":"system"},{"type":"escalate_rcc","level":2,"message":"物料齐套不足需升级处理"}]'::jsonb,
     2),

    ('rc-003', 'DEADLINE_RISK_NOTIFY', '交期风险预警', 'rcc-root',
     'delivery_risk',
     '[{"field":"event.days_overdue","op":"gt","value":0}]',
     '[{"type":"create_chatbot_ticket","ticket_type":"delivery_risk","message":"工单交期风险"}, {"type":"notify_org_unit","target_org_unit":"rcc-root","message":"交期风险通知"}]'::jsonb,
     3),

    ('rc-004', 'YIELD_DROP_AUTO_INC', '良品率下降→自动触发检验加严', 'rcc-root',
     'yield_drop',
     '[{"field":"event.yield_rate","op":"lt","value":98}]',
     '[{"type":"update_param","param_code":"aql_level_general","value":"General-III","source":"system"},{"type":"create_chatbot_ticket","ticket_type":"quality_inc","message":"良品率低于目标，自动加严AQL级别"}]'::jsonb,
     4),

    ('rc-005', 'ENV_ABNORMAL_NOTIFICATION', '环境异常通知', 'rcc-root',
     'environment_abnormal',
     '[{"field":"event.warning","op":"neq","value":""}]',
     '[{"type":"notify_org_unit","target_org_unit":"rcc-root","message":"环境参数异常"}, {"type":"log_audit","reason":"环境异常事件记录"}]'::jsonb,
     5);

-- ✅ RCC deterministic_logic_chains 种子已写入


-- ── 4. 补充 org_units 的产线层级（如果rcc基础org不完整）──
INSERT INTO org_units (id, code, name, parent_id, level_type, factory_id, metadata_)
VALUES
    ('line-a', 'LINE_A', '产线A', 'rcc-root', 'operational', 'FAC_MECH_001', '{"type": "production_line", "line_balance": true}'),
    ('line-b', 'LINE_B', '产线B', 'rcc-root', 'operational', 'FAC_MECH_001', '{"type": "production_line", "line_balance": true}'),
    ('hr-office', 'HR_OFFICE', '人力资源部', 'rcc-root', 'support', 'FAC_MECH_001', '{"type": "office"}'),
    ('quality-dept', 'QMS_DEPT', '品质部', 'rcc-root', 'tactical', 'FAC_MECH_001', '{"type": "department"}'),
    ('planning-dept', 'PLANNING', '计划部', 'rcc-root', 'tactical', 'FAC_MECH_001', '{"type": "department", "role": "scheduling_agent"}')
ON CONFLICT (id) DO UPDATE SET
    updated_at = CURRENT_TIMESTAMP;

-- ── 5. 索引优化 ──
CREATE INDEX IF NOT EXISTS idx_rcc_params_category ON global_adjustable_params(category);
CREATE INDEX IF NOT EXISTS idx_rcc_params_sensitivity ON global_adjustable_params(sensitivity);

COMMENT ON TABLE global_adjustable_params IS 'RCC全局可调参数 — 人/设备/工单/环境/工艺基线';
COMMENT ON COLUMN global_adjustable_params.category IS 'people|equipment|work_order|environment|process|logic';
COMMENT ON COLUMN global_adjustable_params.sensitivity IS 'low(normal)|medium(review)|high(approval)|strategic(rcc_only)';
