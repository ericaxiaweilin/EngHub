-- 线组（并联线的合流产能）。用户 2026-10-06 第二次给数时讲清了一件我原来推不出来的事：
-- bike 两条线不是 400 + 400 = 800，而是**合并 700** —— 两条线共用后段/共用人力，
-- 并联起来有损耗。把这种"组合产能"写死成 parallel_lines × units_per_day 就会高估 bike 线 14%，
-- 而在"缺料能不能靠另一条线追回来"这类判断上，14% 的富余正好是结论翻不翻的分界线。
ALTER TABLE line_profiles
    ADD COLUMN IF NOT EXISTS line_group VARCHAR(64),
    ADD COLUMN IF NOT EXISTS group_units_per_day NUMERIC(10, 2);

COMMENT ON COLUMN line_profiles.line_group IS
    '同一组内的线共用一个合流产能（group_units_per_day），不是各自独立相加';
COMMENT ON COLUMN line_profiles.group_units_per_day IS
    '这一组一天实际能出多少台（合并值；空=按各线相加）';

-- 用户口述的更正（覆盖第一批行）：
--   bike：单线 400 台/天，2 条线，合并 700 台/天，共 450 人，11 小时
--   跑步机：300 台/天，1 条线，200 人，11 小时
UPDATE line_profiles SET
    line_group = 'GROUP-BIKE', group_units_per_day = 700,
    crew_size = 225, units_per_day = 400, parallel_lines = 1,
    note = '用户口述 2026-10-06（第二次更正）：bike 单线 400 台、共 2 条线、合并 700 台/天、450 人、11h。'
           '本行是两条线中的一条（各 400、各 225 人），合流上限由 group_units_per_day=700 表达。'
           '可以做跑步机（单向：跑步机线做不了 bike）。',
    updated_at = NOW()
WHERE line_code = 'LINE-BIKE-01';

INSERT INTO line_profiles
    (id, factory_id, line_code, line_name, hours_per_day, units_per_day, crew_size,
     parallel_lines, can_make_models, cannot_make_models, default_model,
     line_group, group_units_per_day, source, note)
VALUES
    ('lp-bike-02', 'FAC_MECH_001', 'LINE-BIKE-02', 'bike线2（阻力车）', 11, 400, 225, 1,
     ARRAY['HTM1481-00','HTM1390-00','HTM1374-00','HTM1495-00','A-50-04-F'], ARRAY[]::text[],
     'HTM1481-00', 'GROUP-BIKE', 700, '用户口述 2026-10-06',
     'bike 的第二条线，与 LINE-BIKE-01 合流上限 700 台/天（不是 800）')
ON CONFLICT DO NOTHING;

UPDATE line_profiles SET
    line_group = 'GROUP-TREAD', group_units_per_day = 300,
    note = '用户口述 2026-10-06：跑步机线 300 台/天、11 小时、200 人；做不了 bike（单向兼容由用户明确）。',
    updated_at = NOW()
WHERE line_code = 'LINE-TREAD-01';
