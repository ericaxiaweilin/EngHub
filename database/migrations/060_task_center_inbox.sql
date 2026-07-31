-- =============================================================================
-- Migration: 060_task_center_inbox.sql
-- Description: 任务中心升级为统一工作台 — 除 AI 跟进外，接入他人指派任务、
--              会议纪要、邮件等内容，AI 自动分诊（摘要/行动项/紧急度），
--              纯知会类自动关闭，减少用户需要亲自处理的事项
-- Date: 2026-07-30
-- =============================================================================

-- 条目类型：followup(AI跟进) / assigned(他人指派) / meeting(会议纪要) / email(邮件) / note(备忘)
ALTER TABLE followup_tasks ADD COLUMN IF NOT EXISTS item_type VARCHAR(20) NOT NULL DEFAULT 'followup';
-- 指派给谁（username，NULL = 创建人自己的事）
ALTER TABLE followup_tasks ADD COLUMN IF NOT EXISTS assigned_to VARCHAR(64);
-- 原始内容（会议纪要全文 / 邮件正文，分诊与跟进时作为上下文）
ALTER TABLE followup_tasks ADD COLUMN IF NOT EXISTS payload TEXT;
-- AI 分诊摘要（接入时自动生成）
ALTER TABLE followup_tasks ADD COLUMN IF NOT EXISTS ai_summary TEXT;
-- AI 建议动作（含提取的行动项）
ALTER TABLE followup_tasks ADD COLUMN IF NOT EXISTS ai_suggestion TEXT;
-- 截止时间（指派任务用）
ALTER TABLE followup_tasks ADD COLUMN IF NOT EXISTS due_at TIMESTAMP WITH TIME ZONE;

CREATE INDEX IF NOT EXISTS idx_followup_assignee ON followup_tasks(assigned_to, status);
CREATE INDEX IF NOT EXISTS idx_followup_item_type ON followup_tasks(factory_id, item_type, status);

COMMENT ON COLUMN followup_tasks.item_type IS '条目类型: followup/assigned/meeting/email/note';
COMMENT ON COLUMN followup_tasks.payload IS '原始内容（会议纪要/邮件正文）';
COMMENT ON COLUMN followup_tasks.ai_summary IS 'AI 分诊摘要';
COMMENT ON COLUMN followup_tasks.ai_suggestion IS 'AI 建议动作/行动项';
