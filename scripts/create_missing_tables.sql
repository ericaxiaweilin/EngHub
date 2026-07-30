-- 缺失表创建

-- routings
CREATE TABLE IF NOT EXISTS routings (
    id VARCHAR(36) PRIMARY KEY,
    routing_code VARCHAR(50) UNIQUE NOT NULL,
    factory_id VARCHAR(50) NOT NULL,
    product_id VARCHAR(50) NOT NULL,
    version VARCHAR(20) DEFAULT 'v1',
    steps JSONB NOT NULL DEFAULT '[]',
    is_active BOOLEAN DEFAULT TRUE,
    created_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_routing_factory ON routings(factory_id);
CREATE INDEX IF NOT EXISTS idx_routing_product_version ON routings(product_id, version);

-- outbound_orders
CREATE TABLE IF NOT EXISTS outbound_orders (
    id VARCHAR(36) PRIMARY KEY,
    outbound_code VARCHAR(50) UNIQUE NOT NULL,
    factory_id VARCHAR(50) NOT NULL,
    warehouse_id VARCHAR(36),
    material_id VARCHAR(50) NOT NULL,
    quantity INTEGER NOT NULL,
    work_order_id VARCHAR(50),
    batch_code VARCHAR(50),
    outbound_type VARCHAR(20) DEFAULT 'production',
    status VARCHAR(20) DEFAULT 'pending',
    created_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_outbound_factory ON outbound_orders(factory_id);

-- skills (employee_skills的FK依赖)
CREATE TABLE IF NOT EXISTS skills (
    id SERIAL PRIMARY KEY,
    skill_code VARCHAR(50) UNIQUE,
    skill_name VARCHAR(100) NOT NULL,
    category VARCHAR(50),
    description TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- employee_skills
CREATE TABLE IF NOT EXISTS employee_skills (
    id SERIAL PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    skill_id INTEGER REFERENCES skills(id),
    level VARCHAR(10) NOT NULL,
    certified_date TIMESTAMP,
    expiry_date TIMESTAMP,
    score NUMERIC(5,2),
    remarks TEXT,
    evaluated_by UUID,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_emp_skill_user ON employee_skills(user_id);

-- 种子：工艺路线
INSERT INTO routings (id, routing_code, factory_id, product_id, version, steps) VALUES
('rt-001', 'RT-AL6061-V1', 'F01', 'PROD-AL6061', 'v1', '[{"seq":10,"name":"CNC粗加工","station":"ST-CNC","cycle_time":72},{"seq":20,"name":"CNC精加工","station":"ST-CNC","cycle_time":80},{"seq":30,"name":"检验","station":"ST-QC","cycle_time":30}]'),
('rt-002', 'RT-SUS304-V1', 'F01', 'PROD-SUS304', 'v1', '[{"seq":10,"name":"CNC加工","station":"ST-CNC","cycle_time":90},{"seq":20,"name":"磨削","station":"ST-GRIND","cycle_time":45}]')
ON CONFLICT (id) DO NOTHING;
