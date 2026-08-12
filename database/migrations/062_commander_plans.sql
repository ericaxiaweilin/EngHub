-- =============================================================================
-- Migration: 062_commander_plans.sql
-- Description: 工厂指挥官行动计划（Plan）— 指挥官每轮决策必须产出目标导向的计划，
--              计划及其子任务（followup_tasks）记录在任务中心，持续盯办直到闭环。
-- Tables: commander_plans（计划主体）；followup_tasks 增 plan_id/plan_seq（任务归属计划）
-- Date: 2026-07-31
-- =============================================================================

-- 指挥官行动计划主体：一个工厂同一时间只有一个 active 计划（随态势演进），
-- 全部子任务完成后置 done；下一轮有新决策再开新计划，形成计划列表（历史）。
CREATE TABLE IF NOT EXISTS commander_plans (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(64) NOT NULL,             -- 工厂隔离
    created_by VARCHAR(64) NOT NULL,             -- 计划归属用户 username
    cycle_id VARCHAR(36),                        -- 关联指挥官决策轮次
    objective VARCHAR(500) NOT NULL,             -- 计划总目标（一句话，随态势更新）
    mode VARCHAR(20),                            -- 制定时的订单模式 surplus/normal/deficit
    status VARCHAR(20) NOT NULL DEFAULT 'active',-- active(执行中) / done(全部完成) / superseded(被取代)
    progress_pct INTEGER NOT NULL DEFAULT 0,     -- 计划总进度（子任务进度聚合）
    item_count INTEGER NOT NULL DEFAULT 0,       -- 子任务数
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    closed_at TIMESTAMP WITH TIME ZONE           -- done 时间
);

CREATE INDEX IF NOT EXISTS idx_commander_plans_factory ON commander_plans(factory_id, status);
CREATE INDEX IF NOT EXISTS idx_commander_plans_created ON commander_plans(factory_id, created_at DESC);

COMMENT ON TABLE commander_plans IS '工厂指挥官行动计划：决策聚合为目标导向计划，子任务挂 followup_tasks 持续盯办';

-- followup_tasks 归属计划：plan_id 指向 commander_plans.id，plan_seq 为计划内优先序
ALTER TABLE followup_tasks ADD COLUMN IF NOT EXISTS plan_id VARCHAR(36);
ALTER TABLE followup_tasks ADD COLUMN IF NOT EXISTS plan_seq INTEGER;

CREATE INDEX IF NOT EXISTS idx_followup_plan ON followup_tasks(plan_id);

COMMENT ON COLUMN followup_tasks.plan_id IS '所属指挥官计划（commander_plans.id），NULL=非计划任务';
COMMENT ON COLUMN followup_tasks.plan_seq IS '计划内序号（按优先级排序，1 最优先）';
