-- 职位训练器：题目和成绩是接口数据，不绑定在某个业务模块页面。

CREATE TABLE IF NOT EXISTS position_training_questions (
    id              VARCHAR(64) PRIMARY KEY,
    position_code   VARCHAR(64) NOT NULL,
    question_code   VARCHAR(64) NOT NULL UNIQUE,
    skill           VARCHAR(64) NOT NULL,
    difficulty      INTEGER NOT NULL DEFAULT 1,
    question_type   VARCHAR(16) NOT NULL DEFAULT 'single',
    prompt          TEXT NOT NULL,
    options         JSONB NOT NULL DEFAULT '[]'::jsonb,
    answer          JSONB NOT NULL DEFAULT '[]'::jsonb,
    explanation     TEXT NOT NULL,
    reference_terms JSONB NOT NULL DEFAULT '[]'::jsonb,
    points          INTEGER NOT NULL DEFAULT 1,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_position_training_questions
    ON position_training_questions(position_code, is_active, difficulty);

CREATE TABLE IF NOT EXISTS position_training_attempts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    position_code   VARCHAR(64) NOT NULL,
    user_id         VARCHAR(64) NOT NULL,
    factory_id      VARCHAR(64),
    answers         JSONB NOT NULL DEFAULT '{}'::jsonb,
    score           NUMERIC(5,2) NOT NULL DEFAULT 0,
    earned_points   INTEGER NOT NULL DEFAULT 0,
    total_points    INTEGER NOT NULL DEFAULT 0,
    details         JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_position_training_attempts_user
    ON position_training_attempts(position_code, user_id, created_at DESC);

INSERT INTO position_training_questions
    (id, position_code, question_code, skill, difficulty, question_type, prompt,
     options, answer, explanation, reference_terms, points)
VALUES
('PT-PMC-Q01', 'pmc', 'PT-PMC-Q01', '交期基础', 1, 'single',
 '客户说“8月30日必须收到货”，PMC首先应把它识别为什么？',
 '[{"value":"a","label":"ETD，船开日"},{"value":"b","label":"RDD，客户要求到货日"},{"value":"c","label":"FG Ready，成品待出货"},{"value":"d","label":"Cut-off，截关时间"}]'::jsonb,
 '["b"]'::jsonb,
 '这是客户到货承诺点，还要继续倒推海运、ETD、截关、FG Ready和生产节点。',
 '["RDD","ETD","FG Ready"]'::jsonb, 1),
('PT-PMC-Q02', 'pmc', 'PT-PMC-Q02', '物料红线', 1, 'single',
 '物料缺口存在时，供应商ETA要满足什么条件才算赶得上上线？',
 '[{"value":"a","label":"ETA早于客户RDD即可"},{"value":"b","label":"ETA早于生产完成即可"},{"value":"c","label":"ETA不晚于物料上线红线，且要加上IQC、入库和发料时间"},{"value":"d","label":"供应商口头说能到即可"}]'::jsonb,
 '["c"]'::jsonb,
 '到厂不等于可上线，必须扣除IQC、入库和发料时间，并与生产开始红线比较。',
 '["ETA","IQC","MRP"]'::jsonb, 1),
('PT-PMC-Q03', 'pmc', 'PT-PMC-Q03', '产能判断', 1, 'single',
 '判断CTP时，哪个说法正确？',
 '[{"value":"a","label":"有成品库存就一定能承诺"},{"value":"b","label":"只看平均日产能即可"},{"value":"c","label":"要同时核对瓶颈工位、有效工时、换线和时间窗口"},{"value":"d","label":"只要工单已创建就能承诺"}]'::jsonb,
 '["c"]'::jsonb,
 'CTP关注可承诺产能，不能只看库存或平均产能，还要验证瓶颈与实际窗口。',
 '["CTP","瓶颈","UPH"]'::jsonb, 1),
('PT-PMC-Q04', 'pmc', 'PT-PMC-Q04', '工单释放', 2, 'multi',
 '工单释放前应至少核对哪些闸口？（多选）',
 '[{"value":"a","label":"计划已确认且版本受控"},{"value":"b","label":"物料齐套或有书面ETA与上线红线"},{"value":"c","label":"工艺路线、工位和技能可用"},{"value":"d","label":"质量冻结和必要审批已确认"},{"value":"e","label":"只看客户是否着急"}]'::jsonb,
 '["a","b","c","d"]'::jsonb,
 '释放至少需要计划、物料、工艺/产能、质量和审批证据，客户着急不能替代闸口。',
 '["MPS","CTP","齐套","质量冻结"]'::jsonb, 2),
('PT-PMC-Q05', 'pmc', 'PT-PMC-Q05', '异常升级', 2, 'single',
 '关键物料缺口没有可靠ETA，最合适的PMC动作是什么？',
 '[{"value":"a","label":"先把工单Released，后面再说"},{"value":"b","label":"用供应商口头承诺当作已确认ETA"},{"value":"c","label":"标记P0，确认缺口与上线红线，升级采购并同步交期影响"},{"value":"d","label":"直接删除这条缺料记录"}]'::jsonb,
 '["c"]'::jsonb,
 '没有可靠ETA就没有可审计承诺，应形成缺口、红线、责任人和升级记录。',
 '["P0","ETA","RCC"]'::jsonb, 1),
('PT-PMC-Q06', 'pmc', 'PT-PMC-Q06', '日报闭环', 1, 'single',
 '一份可执行的PMC日报最不能缺少什么？',
 '[{"value":"a","label":"只有产量排名"},{"value":"b","label":"计划/达成、良率、WIP、缺料ETA、瓶颈、交期风险和决策项"},{"value":"c","label":"只写昨天发生的事情"},{"value":"d","label":"只写没有异常的部分"}]'::jsonb,
 '["b"]'::jsonb,
 '日报要支持明日交期决策，必须同时呈现达成差异、风险证据、责任人和决策项。',
 '["WIP","良率","ETA","瓶颈"]'::jsonb, 1)
ON CONFLICT (id) DO UPDATE SET
    position_code = EXCLUDED.position_code,
    skill = EXCLUDED.skill,
    difficulty = EXCLUDED.difficulty,
    question_type = EXCLUDED.question_type,
    prompt = EXCLUDED.prompt,
    options = EXCLUDED.options,
    answer = EXCLUDED.answer,
    explanation = EXCLUDED.explanation,
    reference_terms = EXCLUDED.reference_terms,
    points = EXCLUDED.points,
    is_active = TRUE,
    updated_at = NOW();
