-- 029: work_order_templates 增加 module 分组 + form_fields 动态表单定义
-- 支持按模块（QMS/设备/仓储/生产/PP）分类工单模板，前端动态渲染表单字段

ALTER TABLE work_order_templates
    ADD COLUMN IF NOT EXISTS module VARCHAR(30) DEFAULT 'production',
    ADD COLUMN IF NOT EXISTS form_fields JSONB DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS standard_ref VARCHAR(200),
    ADD COLUMN IF NOT EXISTS badge_text VARCHAR(100),
    ADD COLUMN IF NOT EXISTS color VARCHAR(20) DEFAULT '#1677ff',
    ADD COLUMN IF NOT EXISTS sort_order INTEGER DEFAULT 0;

-- 为现有模板补充 module 归属
UPDATE work_order_templates SET module = 'production' WHERE template_code IN ('WO-TPL-PROD', 'WO-TPL-REWORK', 'WO-TPL-TRIAL', 'WO-TPL-SAMPLE');
UPDATE work_order_templates SET module = 'equipment' WHERE template_code = 'WO-TPL-MAINT';
UPDATE work_order_templates SET module = 'production' WHERE template_code LIKE 'WO-TPL-M-%' OR template_code LIKE 'WO-TPL-E-%';

COMMENT ON COLUMN work_order_templates.module IS '所属模块: qms/equipment/wms/production/pp';
COMMENT ON COLUMN work_order_templates.form_fields IS '动态表单字段定义 JSON [{key,label,type,required?,options?,placeholder?,suffix?,span?}]';
COMMENT ON COLUMN work_order_templates.standard_ref IS '参考标准（如 ISO 9001 / IATF 16949）';
COMMENT ON COLUMN work_order_templates.badge_text IS '卡片角标文字';
COMMENT ON COLUMN work_order_templates.color IS '模板主题色';
