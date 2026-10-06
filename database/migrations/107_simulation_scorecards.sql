-- 仿真记分卡：每轮组合推演的结果落一张，分数走势与瓶颈变化要能被追溯（飞轮的那条轨迹）。
-- 只存我方推演读数，不改任何事实表；detail 里是逐单的分项分，权重和依据类别一起存。
CREATE TABLE IF NOT EXISTS simulation_scorecards (
    id VARCHAR(36) PRIMARY KEY,
    factory_id VARCHAR(50) NOT NULL,
    engine_date DATE NOT NULL,
    models_simulated INTEGER NOT NULL DEFAULT 0,
    portfolio_score NUMERIC(6, 2) NOT NULL,
    weights JSONB,
    top_constraint VARCHAR(200),
    lever_deltas JSONB,
    detail JSONB,
    source VARCHAR(40) NOT NULL DEFAULT 'portfolio_sim',
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sim_scorecards_factory_time
    ON simulation_scorecards (factory_id, engine_date DESC);

COMMENT ON TABLE simulation_scorecards IS
    '机种组合推演的记分卡历史：分数、权重、瓶颈、杠杆对比。推演读数，不是现场事实。';
