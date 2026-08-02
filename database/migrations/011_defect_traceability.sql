-- 011: 补全 defect_records 品质追溯流程字段 + 重写种子数据
-- 完整流程：发现→判定→根因→责任→处置→纠正/预防→关闭

-- 1. 新增追溯字段
ALTER TABLE defect_records ADD COLUMN IF NOT EXISTS defect_source VARCHAR(30);       -- 缺陷来源: incoming/process/design/operation/environment/customer
ALTER TABLE defect_records ADD COLUMN IF NOT EXISTS root_cause_category VARCHAR(30); -- 原因分类(5M1E): material/method/machine/man/environment/measurement
ALTER TABLE defect_records ADD COLUMN IF NOT EXISTS root_cause TEXT;                 -- 根因描述
ALTER TABLE defect_records ADD COLUMN IF NOT EXISTS responsible_dept VARCHAR(30);    -- 责任部门: QA/production/purchasing/engineering/vendor
ALTER TABLE defect_records ADD COLUMN IF NOT EXISTS discovery_stage VARCHAR(20);     -- 发现阶段: IQC/IPQC/FQC/OQC/customer
ALTER TABLE defect_records ADD COLUMN IF NOT EXISTS discovery_time TIMESTAMP;        -- 发现时间
ALTER TABLE defect_records ADD COLUMN IF NOT EXISTS defect_location VARCHAR(200);    -- 缺陷位置
ALTER TABLE defect_records ADD COLUMN IF NOT EXISTS inspection_id VARCHAR(36);       -- 关联检验单
ALTER TABLE defect_records ADD COLUMN IF NOT EXISTS corrective_action TEXT;          -- 纠正措施
ALTER TABLE defect_records ADD COLUMN IF NOT EXISTS preventive_action TEXT;          -- 预防措施
ALTER TABLE defect_records ADD COLUMN IF NOT EXISTS process_step VARCHAR(50);        -- 工序名称
ALTER TABLE defect_records ADD COLUMN IF NOT EXISTS review_status VARCHAR(20) DEFAULT 'pending'; -- pending/under_review/reviewed/closed
ALTER TABLE defect_records ADD COLUMN IF NOT EXISTS reviewed_by VARCHAR(50);
ALTER TABLE defect_records ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMP;

-- 2. 清除旧种子数据
DELETE FROM defect_records WHERE id LIKE 'dr-seed-%';

-- 3. 插入完整品质追溯种子数据（覆盖不同来源/阶段/处置状态）

-- 3.1 来料不良 (IQC发现, 供应商责任, 已退货)
INSERT INTO defect_records (
    id, record_code, factory_id, work_order_id, production_report_id, product_id,
    material_id, batch_code, station_id, equipment_id,
    defect_type, severity, quantity,
    defect_source, root_cause_category, root_cause, responsible_dept,
    discovery_stage, discovery_time, defect_location, inspection_id,
    process_step, description,
    disposition, disposition_by, disposition_at, disposition_remark,
    corrective_action, preventive_action,
    ocap_status, review_status, reviewed_by, reviewed_at,
    created_by, created_at, updated_at, is_finalized
) VALUES (
    'dr-seed-001', 'DEF-20260718-001', 'FAC_ELEC_DEMO_2026',
    '409bd5c3-6e7f-4fe1-9783-a1194af9c81d', 'eb9fe9c1-ded9-4583-9491-db2f2d18853b',
    'cf72bbb9-25b1-44c7-bf01-37b8a1f579b5',
    'MAT-BT-CHIP-001', 'BATCH-20260715', 'ST-IQC-01', NULL,
    'function', 'major', 6,
    'incoming', 'material', '供应商批次BT芯片射频参数偏移，蓝牙连接距离不足3m（规格≥10m），判定为来料不良',
    'vendor',
    'IQC', '2026-07-18 09:30:00', 'U3射频模块-BT芯片引脚', NULL,
    'IQC来料检验', 'IQC抽检发现6件BT芯片蓝牙连接异常，连接距离<3m，不满足规格书≥10m要求',
    'return', 'QA-张工', '2026-07-18 14:00:00', '整批退货供应商，要求48h内补货并附8D报告',
    '1.该批次全部退货 2.供应商提交8D改善报告 3.加严下批抽检AQL至0.65',
    '1.更新AVL合格供应商评分 2.关键射频器件增加入厂全检项 3.季度审核供应商制程能力',
    'completed', 'closed', 'QA-李经理', '2026-07-19 10:00:00',
    'IQC-王检', '2026-07-18 09:30:00', '2026-07-19 10:00:00', true
);

-- 3.2 制程不良 (IPQC发现, 生产责任, 已返工)
INSERT INTO defect_records (
    id, record_code, factory_id, work_order_id, production_report_id, product_id,
    material_id, batch_code, station_id, equipment_id,
    defect_type, severity, quantity,
    defect_source, root_cause_category, root_cause, responsible_dept,
    discovery_stage, discovery_time, defect_location, inspection_id,
    process_step, description,
    disposition, disposition_by, disposition_at, disposition_remark,
    corrective_action, preventive_action,
    ocap_status, review_status, reviewed_by, reviewed_at,
    created_by, created_at, updated_at, is_finalized
) VALUES (
    'dr-seed-002', 'DEF-20260720-002', 'FAC_ELEC_DEMO_2026',
    'bcbbeb04-23f8-4bdd-ab35-451a02ade5ce', 'a2f1c8e3-7b4d-4e9a-b6d2-1f8a3c5e7d90',
    'cf72bbb9-25b1-44c7-bf01-37b8a1f579b5',
    NULL, 'BATCH-20260720', 'ST-SMT-02', 'eq-reflow-001',
    'appearance', 'minor', 7,
    'process', 'method', '回流焊温度曲线峰值温度偏高5°C(实测250°C/规格245±3°C)，导致焊点氧化发黑、外观不良',
    'production',
    'IPQC', '2026-07-20 14:15:00', 'PCB正面-U5/Q3焊点', '38303e43-1bc8-4c49-93f7-3b505662f498',
    'SMT回流焊', 'IPQC巡检发现回流焊后7件PCB焊点氧化发黑，外观不合格',
    'rework', 'QA-陈工', '2026-07-20 16:30:00', '返工：热风返修台重焊受影响焊点，复检OK后流入下工序',
    '1.立即修正回流焊温度曲线(峰值245°C) 2.该批次7件返工重焊 3.当班全检',
    '1.每2h记录炉温曲线 2.增加炉温超限自动报警 3.作业指导书明确温度管控上下限',
    'completed', 'closed', 'QA-李经理', '2026-07-21 09:00:00',
    'IPQC-刘检', '2026-07-20 14:15:00', '2026-07-21 09:00:00', true
);

-- 3.3 制程不良 (FQC发现, 设备责任, 待评审)
INSERT INTO defect_records (
    id, record_code, factory_id, work_order_id, production_report_id, product_id,
    material_id, batch_code, station_id, equipment_id,
    defect_type, severity, quantity,
    defect_source, root_cause_category, root_cause, responsible_dept,
    discovery_stage, discovery_time, defect_location, inspection_id,
    process_step, description,
    disposition, disposition_by, disposition_at, disposition_remark,
    corrective_action, preventive_action,
    ocap_status, review_status, reviewed_by, reviewed_at,
    created_by, created_at, updated_at, is_finalized
) VALUES (
    'dr-seed-003', 'DEF-20260721-003', 'FAC_ELEC_DEMO_2026',
    'c378ef64-de7e-4483-b738-9a33fcfab51c', 'b3e2d9f4-8c5a-4f1b-a7e3-2g9b4d6f8a01',
    'cf72bbb9-25b1-44c7-bf01-37b8a1f579b5',
    NULL, 'BATCH-20260721', 'ST-ASM-01', 'eq-pick-003',
    'dimension', 'major', 8,
    'process', 'machine', '贴片机Z轴压力传感器漂移，贴片压力过大导致PCB定位孔变形偏移0.15mm(规格≤0.05mm)',
    'engineering',
    'FQC', '2026-07-21 16:45:00', 'PCB定位孔-K1/K2', '02b659c1-2ef3-4c22-b907-978b3d187f84',
    'SMT贴片', 'FQC终检发现8件PCB定位孔偏移超标，影响后续组装定位精度',
    NULL, NULL, NULL, NULL,
    NULL, NULL,
    'triggered', 'under_review', NULL, NULL,
    'FQC-赵检', '2026-07-21 16:45:00', '2026-07-21 16:45:00', false
);

-- 3.4 设计不良 (OQC发现, 工程责任, 让步接收)
INSERT INTO defect_records (
    id, record_code, factory_id, work_order_id, production_report_id, product_id,
    material_id, batch_code, station_id, equipment_id,
    defect_type, severity, quantity,
    defect_source, root_cause_category, root_cause, responsible_dept,
    discovery_stage, discovery_time, defect_location, inspection_id,
    process_step, description,
    disposition, disposition_by, disposition_at, disposition_remark,
    corrective_action, preventive_action,
    ocap_status, review_status, reviewed_by, reviewed_at,
    created_by, created_at, updated_at, is_finalized
) VALUES (
    'dr-seed-004', 'DEF-20260722-004', 'FAC_ELEC_DEMO_2026',
    '409bd5c3-6e7f-4fe1-9783-a1194af9c81d', NULL,
    'cf72bbb9-25b1-44c7-bf01-37b8a1f579b5',
    NULL, 'BATCH-20260722', 'ST-PACK-01', NULL,
    'appearance', 'observation', 3,
    'design', 'method', '外壳卡扣设计间隙0.2mm偏小，组装后轻微翘曲(0.3mm)，不影响功能但外观面有轻微缝隙',
    'engineering',
    'OQC', '2026-07-22 10:20:00', '外壳底盖-卡扣B/C位', NULL,
    'OQC出货检验', 'OQC抽检发现3件底盖卡扣处轻微翘曲0.3mm，外观面有<0.5mm缝隙',
    'concession', 'QA-李经理', '2026-07-22 15:00:00', '经评审：不影响功能及防护等级，客户可接受，让步放行。下批次前完成ECN变更',
    '1.本批让步放行 2.发起ECN-2026-078变更卡扣间隙至0.35mm',
    '1.ECN变更卡扣模具 2.DFM检查清单增加卡扣间隙审核项 3.新品试产增加外观全检',
    'completed', 'closed', 'QA-李经理', '2026-07-22 15:00:00',
    'OQC-孙检', '2026-07-22 10:20:00', '2026-07-22 15:00:00', true
);

-- 3.5 操作不良 (IPQC发现, 人员责任, 待处置)
INSERT INTO defect_records (
    id, record_code, factory_id, work_order_id, production_report_id, product_id,
    material_id, batch_code, station_id, equipment_id,
    defect_type, severity, quantity,
    defect_source, root_cause_category, root_cause, responsible_dept,
    discovery_stage, discovery_time, defect_location, inspection_id,
    process_step, description,
    disposition, disposition_by, disposition_at, disposition_remark,
    corrective_action, preventive_action,
    ocap_status, review_status, reviewed_by, reviewed_at,
    created_by, created_at, updated_at, is_finalized
) VALUES (
    'dr-seed-005', 'DEF-20260722-005', 'FAC_ELEC_DEMO_2026',
    'bcbbeb04-23f8-4bdd-ab35-451a02ade5ce', NULL,
    'cf72bbb9-25b1-44c7-bf01-37b8a1f579b5',
    NULL, 'BATCH-20260722', 'ST-ASM-02', NULL,
    'function', 'critical', 2,
    'operation', 'man', '作业员未按SOP执行锁附顺序(应先对角后中间)，导致FPC排线被夹伤断路，功能测试FAIL',
    'production',
    'IPQC', '2026-07-22 11:05:00', 'FPC排线-J2连接器第3/5pin', '69ab761e-55c7-4f81-83bf-9d862ce460e3',
    '组装锁附', 'IPQC发现2件成品功能测试FAIL，拆解确认FPC排线J2连接器第3/5pin断路',
    NULL, NULL, NULL, NULL,
    NULL, NULL,
    'triggered', 'pending', NULL, NULL,
    'IPQC-刘检', '2026-07-22 11:05:00', '2026-07-22 11:05:00', false
);
