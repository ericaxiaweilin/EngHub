-- APS 写量刹车：输入没变就不再新造一份草案。
-- 线上 304 份排程方案全部是 draft、没有一份被确认，而每次"再跑一遍"都要新写
-- 21~459 行 aps_schedule_tasks（10-03 一天 71 份 = 6183 行）。排程算法是确定性的：
-- 同样的工单池、路线、产能、日历、缺口、钉住工序必然得到同样的任务行。
-- 所以给每版方案记一个输入指纹，指纹命中同一份未确认草案就复用它、一行都不写。
ALTER TABLE aps_schedules ADD COLUMN IF NOT EXISTS input_fingerprint VARCHAR(64);

-- 复用查询固定按 (厂区, 指纹, 计划期起点) 找未确认草案；做成 partial index
-- 只覆盖 draft，历史 archived/confirmed 行不进索引，写放大最小。
CREATE INDEX IF NOT EXISTS idx_aps_sched_fp
    ON aps_schedules (factory_id, input_fingerprint, horizon_start)
    WHERE status = 'draft';
