-- 装配线画像：用户 10-06 口述的真实线参数（谁做多少台、几个人、几小时、能不能替别人做）。
-- 为什么单独建一张表：线级节拍是推演的物理约束，不能塞进 cost_parameters（那是钱），
-- 也不能由我从工位产能反推（反推出来 1.05 工时/件，和你给的 11 小时 300 台差一个数量级，
-- 说明厂里是**流水线节拍**，不是单工位累计工时 —— 这一点只有你知道）。
CREATE TABLE IF NOT EXISTS line_profiles (
    id VARCHAR(64) PRIMARY KEY,
    factory_id VARCHAR(64) NOT NULL,
    line_code VARCHAR(64) NOT NULL,
    line_name VARCHAR(128),
    hours_per_day NUMERIC(6, 2) NOT NULL,             -- 每天的班时（11H）
    units_per_day NUMERIC(10, 2) NOT NULL,            -- 节拍：一天能做多少台
    crew_size INTEGER NOT NULL,                       -- 这条线多少人（人力=硬支出，闲着就是钱）
    parallel_lines INTEGER NOT NULL DEFAULT 1,        -- 几条同型线并联
    can_make_models TEXT[] NOT NULL DEFAULT '{}',     -- 能做的机种；空数组=按 line 的默认机种
    cannot_make_models TEXT[] NOT NULL DEFAULT '{}',  -- 明确做不了的（单向兼容就靠这两列表达）
    default_model VARCHAR(64),                        -- 这条线默认做哪个机种
    source VARCHAR(256) NOT NULL,                     -- 依据：谁给的、什么时候
    note TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_line_profiles_factory_line
    ON line_profiles (factory_id, line_code);

COMMENT ON TABLE line_profiles IS
    '产线级物理约束：节拍、班组人数、机种兼容（单向兼容 = can/cannot 两列），推演与人挪移的依据';


-- 用户 2026-10-06 口述的线参数（原文进 note，可回溯；bike 那个 400 台/150 人是"两线合计"
-- 还是"单线"他还没确认，所以先按单线记 400、parallel_lines=2，并把这层不确定写进 note，
-- 推演里两种口径都跑一遍，让他看见结论会不会因为这一个数翻掉。）
INSERT INTO line_profiles
    (id, factory_id, line_code, line_name, hours_per_day, units_per_day, crew_size,
     parallel_lines, can_make_models, cannot_make_models, default_model, source, note)
VALUES
    ('lp-tread-01', 'FAC_MECH_001', 'LINE-TREAD-01', '跑步机线', 11, 300, 200, 1,
     ARRAY['A-50-04-F'], ARRAY['HTM1481-00','HTM1390-00','HTM1374-00','HTM1495-00'],
     'A-50-04-F', '用户口述 2026-10-06',
     '每天 300 台 / 11 小时 / 200 人；做不了 bike（用户明确：跑步机做不了 bike）'),
    ('lp-bike-01', 'FAC_MECH_001', 'LINE-BIKE-01', 'bike线（阻力车）', 11, 400, 150, 2,
     ARRAY['HTM1481-00','HTM1390-00','HTM1374-00','HTM1495-00','A-50-04-F'], ARRAY[]::text[],
     'HTM1481-00', '用户口述 2026-10-06',
     '11 小时 / 400 台 / 150 人 / 2 条线；可以做跑步机（用户明确：bike 线可以做跑步机）。'
     '待确认：400 台是单线还是两线合计 —— 推演两种口径都跑。')
ON CONFLICT DO NOTHING;
