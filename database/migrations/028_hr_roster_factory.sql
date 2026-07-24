-- 028: 人力档案 + 工厂注册表 + 全局工厂切换
-- 机械厂花名册：关键零件一部(119) + 生产一部(803) + 生产二部(102) + 哑铃(20) = 1044

-- ━━━ 1. 工厂注册表 ━━━
CREATE TABLE IF NOT EXISTS factories (
    id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    short_name VARCHAR(50),
    factory_type VARCHAR(50),          -- mechanical / electronics / ...
    address TEXT,
    contact_person VARCHAR(50),
    contact_phone VARCHAR(30),
    status VARCHAR(20) DEFAULT 'active',
    config JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 注册两个工厂
INSERT INTO factories (id, name, short_name, factory_type, address, status)
VALUES
    ('FAC_MECH_001', '机械厂', '机械', 'mechanical', '工业园区A栋', 'active'),
    ('FAC_ELEC_DEMO_2026', '电子厂', '电子', 'electronics', '科技园区B栋', 'active')
ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, short_name = EXCLUDED.short_name;

-- ━━━ 2. 人力档案表 ━━━
CREATE TABLE IF NOT EXISTS hr_employees (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    factory_id VARCHAR(50) NOT NULL REFERENCES factories(id),
    employee_code VARCHAR(30) NOT NULL,
    name VARCHAR(50) NOT NULL,
    gender VARCHAR(4) DEFAULT '男',
    department VARCHAR(50) NOT NULL,       -- 关键零件一部 / 生产一部 / 生产二部 / 哑铃
    station VARCHAR(50) NOT NULL,          -- 精加工 / 滚轮 / 注塑 / ...
    position VARCHAR(50) DEFAULT '操作员',
    shift VARCHAR(20) DEFAULT '白班',       -- 白班 / 夜班 / 两班倒
    hire_date DATE DEFAULT CURRENT_DATE,
    status VARCHAR(20) DEFAULT 'active',   -- active / leave / resigned
    phone VARCHAR(20),
    skill_level VARCHAR(10) DEFAULT 'L1',  -- L1-L5
    certifications TEXT[],
    remarks TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(factory_id, employee_code)
);

CREATE INDEX IF NOT EXISTS idx_hr_emp_factory ON hr_employees(factory_id);
CREATE INDEX IF NOT EXISTS idx_hr_emp_dept ON hr_employees(factory_id, department);
CREATE INDEX IF NOT EXISTS idx_hr_emp_station ON hr_employees(factory_id, station);
CREATE INDEX IF NOT EXISTS idx_hr_emp_status ON hr_employees(factory_id, status);

-- ━━━ 3. 机械厂种子数据（1044人） ━━━
-- 使用姓氏+名字数组生成真实中文姓名
DO $$
DECLARE
    surnames TEXT[] := ARRAY['王','李','张','刘','陈','杨','黄','赵','周','吴','徐','孙','马','朱','胡','郭','何','林','罗','高','郑','梁','谢','宋','唐','韩','曹','许','邓','冯','萧','程','蔡','彭','潘','袁','董','叶','蒋','余','苏','吕','魏','蒋','田','杜','丁','沈','姜','范','江','傅','钟','卢','汪','戴','崔','任','陆','廖','姚','方','金','邱','夏','谭','石','贾','邹','熊','孟','秦','阎','薛','侯','雷','白','龙','段','郝','孔','邵','史','毛','常','万','顾','赖','武','康','贺','严','尹','钱','施','牛','洪','龚'];
    given1 TEXT[] := ARRAY['伟','芳','娜','敏','静','强','磊','洋','勇','军','杰','涛','超','明','霞','平','刚','桂','英','华','建','文','辉','力','斌','飞','鑫','鹏','波','宇','浩','然','博','宁','毅','俊','峰','志','义','兴','良','海','山','仁','奇','固','之','轮','翰','朗','伯','宏','言','若','鸣','朋','裕','河','哲','江','晨','辰','士','以','建','致','煜','进','林','有','坚','和','彪','诚','先','敬','震','振','壮','会','思','群','豪','心','邦','承','乐','绍','功','松','善','厚','庆','磊','民','友','永','健','世','广','志','义','兴','良'];
    given2 TEXT[] := ARRAY['华','明','志','文','建','国','荣','坤','鑫','鹏','龙','虎','伟','强','军','杰','涛','斌','飞','波','宇','浩','然','博','宁','毅','俊','峰','超','磊','洋','勇','刚','桂','英','辉','力','平','霞','芳','娜','敏','静','丽','艳','娟','莉','秀','兰','凤','梅','琳','素','云','莲','真','环','雪','荣','爱','妹','霞','慧','巧','美','娥','珍','莉','桂','颖','欣','雨','萱','瑶','蕾','薇','悦','彤','佳','琪','萌','悦','馨','妍','彤','蕊','倩','莹','丹','菲','萍','红','玲','芬','芳','燕','彩','春','菊','勤','珍','贞','莉','兰','凤','洁','梅','琳','素','云','莲'];
    v_idx INT := 0;
    v_seq INT := 0;
    v_dept TEXT;
    v_station TEXT;
    v_count INT;
    v_stations TEXT[][] := ARRAY[
        ['关键零件一部','精加工','66'],
        ['关键零件一部','滚轮','14'],
        ['关键零件一部','注塑','26'],
        ['关键零件一部','浸塑','13'],
        ['生产一部','加工','164'],
        ['生产一部','焊接','218'],
        ['生产一部','涂装','91'],
        ['生产一部','组立','330'],
        ['生产二部','线材','50'],
        ['生产二部','仪表','14'],
        ['生产二部','機電','38'],
        ['哑铃','哑铃','20']
    ];
    v_shift TEXT;
    v_skill TEXT;
    v_hire DATE;
BEGIN
    FOR i IN 1..array_length(v_stations, 1) LOOP
        v_dept := v_stations[i][1];
        v_station := v_stations[i][2];
        v_count := v_stations[i][3]::INT;
        FOR j IN 1..v_count LOOP
            v_seq := v_seq + 1;
            v_idx := v_idx + 1;
            -- 姓名：姓 + 1~2字名
            v_shift := CASE WHEN random() < 0.6 THEN '白班' WHEN random() < 0.8 THEN '夜班' ELSE '两班倒' END;
            v_skill := CASE
                WHEN random() < 0.15 THEN 'L4'
                WHEN random() < 0.35 THEN 'L3'
                WHEN random() < 0.65 THEN 'L2'
                ELSE 'L1'
            END;
            v_hire := CURRENT_DATE - (random() * 3650)::INT;  -- 0~10年工龄
            INSERT INTO hr_employees (
                factory_id, employee_code, name, gender,
                department, station, position, shift,
                hire_date, status, skill_level
            ) VALUES (
                'FAC_MECH_001',
                'MEC-' || lpad(v_seq::TEXT, 4, '0'),
                surnames[1 + (v_idx % array_length(surnames, 1))]
                    || given1[1 + ((v_idx * 7 + j * 3) % array_length(given1, 1))]
                    || CASE WHEN random() < 0.55 THEN given2[1 + ((v_idx * 13 + j) % array_length(given2, 1))] ELSE '' END,
                CASE WHEN random() < 0.62 THEN '男' ELSE '女' END,
                v_dept,
                v_station,
                CASE WHEN random() < 0.08 THEN '组长' WHEN random() < 0.03 THEN '技术员' ELSE '操作员' END,
                v_shift,
                v_hire,
                CASE WHEN random() < 0.95 THEN 'active' WHEN random() < 0.98 THEN 'leave' ELSE 'resigned' END,
                v_skill
            );
        END LOOP;
    END LOOP;
END $$;

-- ━━━ 4. 用户表增加 active_factory_id（开发账户切换用） ━━━
ALTER TABLE users ADD COLUMN IF NOT EXISTS active_factory_id VARCHAR(50);
-- eric 开发账户默认激活机械厂
UPDATE users SET active_factory_id = 'FAC_MECH_001' WHERE username = 'eric';
UPDATE users SET active_factory_id = 'FAC_ELEC_DEMO_2026' WHERE username = 'admin' AND active_factory_id IS NULL;
