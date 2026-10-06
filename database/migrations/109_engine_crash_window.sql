-- 引擎循环崩溃率的窗口化（2026-10-06）
--
-- 累计口径把 10-04 起的所有失败永久压在分子上：插桩之前那 5 次失败连成因都查不到
-- （recent_errors 小环还没建、心跳台账还断写过），却永远压着 L1 不让上层对外引用。
-- 一个无法归因的数不能当判据，所以判据改看当前窗口，累计值只当诊断留档。

ALTER TABLE engine_loop_state
    ADD COLUMN IF NOT EXISTS window_started_at timestamp,
    ADD COLUMN IF NOT EXISTS window_ticks bigint NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS window_failures bigint NOT NULL DEFAULT 0;

-- 窗口从迁移时刻起算，第一轮心跳就把自己的数写进去
UPDATE engine_loop_state SET window_started_at = NOW() WHERE window_started_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_engine_loop_state_window
    ON engine_loop_state (window_started_at DESC);
