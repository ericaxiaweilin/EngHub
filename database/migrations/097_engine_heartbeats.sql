-- 097_engine_heartbeats.sql
-- 引擎后台循环的心跳台账：一行一个循环，谁在跑、多久一轮、最近一次成没成功。
-- 之前这些循环藏在 API worker 的进程内存里，跑没跑只能靠猜
-- （2026-10-04 实测：两个 worker 都执行了 startup handler，但 12 小时没有自主脉搏）。

CREATE TABLE IF NOT EXISTS engine_loop_state (
    loop_name        VARCHAR(64) PRIMARY KEY,
    host             VARCHAR(120),
    pid              INTEGER,
    interval_seconds INTEGER NOT NULL DEFAULT 300,
    started_at       TIMESTAMP,
    last_tick_at     TIMESTAMP,
    ticks            BIGINT  NOT NULL DEFAULT 0,
    failures         BIGINT  NOT NULL DEFAULT 0,
    last_status      VARCHAR(16),
    last_error       TEXT,
    last_detail      JSONB,
    updated_at       TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_engine_loop_state_tick
    ON engine_loop_state (last_tick_at DESC);
