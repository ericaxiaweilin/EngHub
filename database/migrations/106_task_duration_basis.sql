-- 排程任务行要说清时长是谁给的。
-- 背景：路线 JSON 里 430 个工步没有一条带工时，排程落到"0 秒/件 + 300 秒换型"的
-- 兜底上，961 条现行任务里 881 条不足 1 小时 —— 交期、负荷、闲置全跟着失真。
-- 现在只承认工步声明工时、线产能（line_profiles）、工位产能（stations.capacity_per_hour），
-- 三者都没有的写 no_time_basis，宁可没有预计时间也不编一个。
ALTER TABLE aps_schedule_tasks ADD COLUMN IF NOT EXISTS duration_basis VARCHAR(40);

COMMENT ON COLUMN aps_schedule_tasks.duration_basis IS
    '单件时长的出处：route_declared_hours / declared_line_capacity / station_declared_rate / no_time_basis';

CREATE INDEX IF NOT EXISTS idx_aps_task_duration_basis ON aps_schedule_tasks (duration_basis);
