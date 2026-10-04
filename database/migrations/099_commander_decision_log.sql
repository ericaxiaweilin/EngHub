-- 099: 指挥官决策轨迹落盘 —— 数据驱动策略评估的基础。
--
-- 背景：指挥官的 OrderMode 判定 / 选中的 CommanderAction / 理由此前只进 _logger，
-- 而 FactoryState（待排/逾期/负荷/缺料/设备）完全不落盘。结果是"看得到决定了什么，
-- 但无法把当时的状态喂给另一个策略重跑一遍" —— 策略改动无法做 A/B，只能靠感觉。
--
-- 形状对齐 aps_plan_events（event_type/actor/reason/payload），便于统一回放。
--
-- state_snapshot 存 FactoryState 的【原始数值】快照，刻意不用 to_dict()：
-- 后者是给前端看的展示版（数值格式化成字符串并四舍五入），无法无损重建 FactoryState。
--
-- mode_source 区分"策略决策"与"force_mode / _mode_override"：
-- 人工干预不是策略输出，混在一起会把人工干预算成策略效果。
CREATE TABLE IF NOT EXISTS commander_decision_log (
    id              VARCHAR(36) PRIMARY KEY,
    factory_id      VARCHAR(64) NOT NULL,
    cycle_id        VARCHAR(36) NOT NULL,
    mode            VARCHAR(20) NOT NULL,
    mode_source     VARCHAR(16) NOT NULL DEFAULT 'policy',
    mode_reason     VARCHAR(500),
    state_snapshot  JSONB NOT NULL,
    decisions       JSONB NOT NULL DEFAULT '[]'::jsonb,
    policy_version  VARCHAR(64) NOT NULL,
    duration_ms     INTEGER,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_commander_decision_log_factory
    ON commander_decision_log(factory_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_commander_decision_log_cycle
    ON commander_decision_log(cycle_id);
