-- 成本模型的参数覆盖表：默认标定在 api/services/cost_model.py 里（每项都标 basis=default_calibration），
-- 这张表只放**用户给的数**。为什么不在这里 seed 一批"看起来像真的"的单价：
-- 钱数错一次，后面所有"要不要调线"的建议都错；参数必须能追到是谁什么时候给的。
-- amount 用 numeric 而不是 double precision：单价是小数（30.5），浮点会带来 0.1 分钱级的漂移。
CREATE TABLE IF NOT EXISTS cost_parameters (
    id VARCHAR(64) PRIMARY KEY,
    factory_id VARCHAR(64),                      -- NULL = 全集团默认，厂区可按自己实际覆盖
    item_code VARCHAR(64) NOT NULL,              -- labor_person_day / equipment_line_day / ...
    amount NUMERIC(18, 4) NOT NULL,
    is_hard BOOLEAN,                             -- 是否硬现金支出：设备全款=折旧(false)，有贷款/租赁=true
    currency VARCHAR(8) DEFAULT 'USD',
    source VARCHAR(256),                         -- 谁给的：老板口述 / 工资表 / 财务报表 / 询价
    note TEXT,
    valid_from DATE,
    valid_to DATE,
    created_by VARCHAR(64) NOT NULL DEFAULT 'system',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_cost_parameters_factory_item
    ON cost_parameters (COALESCE(factory_id, '*'), item_code);

COMMENT ON TABLE cost_parameters IS
    '成本模型的可覆盖参数：没填就用内置标定并在结果里标 basis=default_calibration，填了必须带 source';
