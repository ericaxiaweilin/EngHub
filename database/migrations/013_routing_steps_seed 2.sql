-- 013: 填充演示工厂工艺路线工序（使工单派生工序工单生效）
-- ============================================================
-- 此前 routings.steps 为空，导致建主工单派生 0 道工序工单。
-- 按工厂类型填充标准工艺路线（仅填充当前为空的激活工艺路线，幂等）。
-- 工序代码由后端 work_order_coding.resolve_operation_code 解析（station_type 优先）。

-- 电子SMT厂（蓝牙音箱）：SMT/DIP/测试/包装 8 道
UPDATE routings SET steps = '[
    {"step_no":1,"name":"锡膏印刷","station_type":"smt"},
    {"step_no":2,"name":"贴片","station_type":"smt"},
    {"step_no":3,"name":"回流焊","station_type":"reflow"},
    {"step_no":4,"name":"AOI检测","station_type":"test"},
    {"step_no":5,"name":"DIP插件","station_type":"dip"},
    {"step_no":6,"name":"波峰焊","station_type":"reflow"},
    {"step_no":7,"name":"功能测试","station_type":"test"},
    {"step_no":8,"name":"组装包装","station_type":"packaging"}
]'::jsonb
WHERE factory_id = 'FAC_ELEC_DEMO_2026' AND is_active = true
  AND (steps IS NULL OR steps = '[]'::jsonb);

-- 精密机械厂（华为P70手机壳精密塑胶模具）：模具制造 8 道（含试模注塑）
UPDATE routings SET steps = '[
    {"step_no":1,"name":"下料","station_type":"raw_material"},
    {"step_no":2,"name":"粗铣","station_type":"cnc"},
    {"step_no":3,"name":"精铣","station_type":"cnc"},
    {"step_no":4,"name":"线切割","station_type":"wire_cut"},
    {"step_no":5,"name":"电火花","station_type":"edm"},
    {"step_no":6,"name":"钳工装配","station_type":"assembly"},
    {"step_no":7,"name":"试模注塑","station_type":"injection"},
    {"step_no":8,"name":"终检","station_type":"inspection"}
]'::jsonb
WHERE factory_id = 'FAC_MECH_DEMO_2026' AND is_active = true
  AND (steps IS NULL OR steps = '[]'::jsonb);
