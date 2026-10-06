-- 崩溃要能归因：last_error 会被下一次成功心跳冲掉，于是"5 次失败"永远查不出是哪一步。
-- 加一个只保留最近 5 条错误的小环，配合 failures 计数就能定位到底哪个环节在坏。
ALTER TABLE engine_loop_state ADD COLUMN IF NOT EXISTS recent_errors jsonb NOT NULL DEFAULT '[]'::jsonb;
