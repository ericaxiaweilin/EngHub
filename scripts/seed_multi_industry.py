

#!/usr/bin/env python3
"""
v2.5 - Multi-Industry Seed Data Generator
一键生成 模具厂、电子厂、运动器材厂 三种典型场景数据（含设备、工人、BOM、工艺路线）
内置 急单场景：自动生成带违约罚款的加急工单，用于压力测试
技能矩阵数据：每位工人绑定技能等级、资质证书、效率评分
"""

import uuid
import random
from datetime import datetime, timedelta
from typing import Dict, List, Any

# 模拟数据生成器（不依赖数据库连接，可独立运行测试）

INDUSTRIES = {
    "mold_factory": {
        "name": "模具厂",
        "description": "精密模具加工 — 铣削/车削/线切割/EDM/装配",
        "products": [
            {"id": f"prod-{uuid.uuid4().hex[:8]}", "code": "MOLD-A100", "name": "汽车仪表盘模具", "category": "mold", "standard_cost": 8500.0},
            {"id": f"prod-{uuid.uuid4().hex[:8]}", "code": "MOLD-B200", "name": "电子连接器模具", "category": "mold", "standard_cost": 5200.0},
            {"id": f"prod-{uuid.uuid4().hex[:8]}", "code": "MOLD-C300", "name": "家电外壳模具", "category": "mold", "standard_cost": 12000.0},
        ],
        "workstations": [
            {"code": "CNC-001", "name": "五轴铣床", "type": "cnc", "capacity_per_hour": 4},
            {"code": "CNC-002", "name": "数控车床", "type": "lathe", "capacity_per_hour": 6},
            {"code": "EDM-001", "name": "电火花加工机", "type": "edm", "capacity_per_hour": 3},
            {"code": "WJC-001", "name": "线切割机", "type": "wire_cut", "capacity_per_hour": 5},
            {"code": "ASSY-001", "name": "模具装配工位", "type": "assembly", "capacity_per_hour": 2},
        ],
        "workers": [
            {"code": "W-MOLD-001", "name": "张师傅", "skills": [{"code": "cnc_operate", "level": 5, "score": 92}], "certificates": ["CNC高级操作证"], "efficiency": 0.95},
            {"code": "W-MOLD-002", "name": "李工", "skills": [{"code": "edm_operate", "level": 4, "score": 85}], "certificates": ["EDM操作证"], "efficiency": 0.88},
            {"code": "W-MOLD-003", "name": "王技师", "skills": [{"code": "assembly", "level": 5, "score": 90}], "certificates": ["模具装配技师证"], "efficiency": 0.91},
            {"code": "W-MOLD-004", "name": "赵技术员", "skills": [{"code": "quality_inspect", "level": 3, "score": 78}], "certificates": ["质检员证"], "efficiency": 0.82},
        ],
        "routings": [
            {
                "id": f"rt-{uuid.uuid4().hex[:8]}",
                "product_id": "MOLD-A100",
                "steps": [
                    {"step_no": 1, "name": "下料", "station_type": "raw_material"},
                    {"step_no": 2, "name": "粗铣", "station_type": "cnc"},
                    {"step_no": 3, "name": "精铣", "station_type": "cnc"},
                    {"step_no": 4, "name": "线切割", "station_type": "wire_cut"},
                    {"step_no": 5, "name": "电火花", "station_type": "edm"},
                    {"step_no": 6, "name": "钳工装配", "station_type": "assembly"},
                    {"step_no": 7, "name": "终检", "station_type": "inspection"},
                ]
            }
        ],
        "rush_order": {
            "title": "汽车仪表盘模具-加急订单",
            "quantity": 15,
            "due_date_offset_days": 5,
            "penalty_per_day": 2000.0,
            "priority": "urgent",
        },
    },
    "electronics_factory": {
        "name": "电子厂",
        "description": "消费电子组装 — SMT/DIP/测试/包装",
        "products": [
            {"id": f"prod-{uuid.uuid4().hex[:8]}", "code": "PCBA-X100", "name": "智能手表主板", "category": "pcba", "standard_cost": 45.0},
            {"id": f"prod-{uuid.uuid4().hex[:8]}", "code": "PCBA-Y200", "name": "蓝牙耳机主板", "category": "pcba", "standard_cost": 32.0},
            {"id": f"prod-{uuid.uuid4().hex[:8]}", "code": "ASM-Z300", "name": "智能手环成品", "category": "asm", "standard_cost": 89.0},
        ],
        "workstations": [
            {"code": "SMT-001", "name": "SMT贴片机", "type": "smt", "capacity_per_hour": 5000},
            {"code": "SMT-002", "name": "回流焊", "type": "reflow", "capacity_per_hour": 4000},
            {"code": "DIP-001", "name": "DIP插件线", "type": "dip", "capacity_per_hour": 2000},
            {"code": "TEST-001", "name": "功能测试站", "type": "test", "capacity_per_hour": 3000},
            {"code": "PACK-001", "name": "包装线", "type": "packaging", "capacity_per_hour": 4000},
        ],
        "workers": [
            {"code": "W-ELEC-001", "name": "陈操作员", "skills": [{"code": "smt_load", "level": 4, "score": 88}], "certificates": ["SMT操作员证"], "efficiency": 0.87},
            {"code": "W-ELEC-002", "name": "刘技术员", "skills": [{"code": "smt_setup", "level": 5, "score": 93}], "certificates": ["SMT高级工程师证"], "efficiency": 0.92},
            {"code": "W-ELEC-003", "name": "黄质检员", "skills": [{"code": "aoi_inspect", "level": 3, "score": 76}], "certificates": ["AOI检验员证"], "efficiency": 0.80},
            {"code": "W-ELEC-004", "name": "吴工程师", "skills": [{"code": "process_engineer", "level": 4, "score": 86}], "certificates": ["PE工程师证"], "efficiency": 0.85},
        ],
        "routings": [
            {
                "id": f"rt-{uuid.uuid4().hex[:8]}",
                "product_id": "PCBA-X100",
                "steps": [
                    {"step_no": 1, "name": "锡膏印刷", "station_type": "smt"},
                    {"step_no": 2, "name": "贴片", "station_type": "smt"},
                    {"step_no": 3, "name": "回流焊", "station_type": "reflow"},
                    {"step_no": 4, "name": "AOI检测", "station_type": "test"},
                    {"step_no": 5, "name": "DIP插件", "station_type": "dip"},
                    {"step_no": 6, "name": "波峰焊", "station_type": "reflow"},
                    {"step_no": 7, "name": "功能测试", "station_type": "test"},
                    {"step_no": 8, "name": "组装包装", "station_type": "packaging"},
                ]
            }
        ],
        "rush_order": {
            "title": "智能手表主板-芯片短缺加急单",
            "quantity": 5000,
            "due_date_offset_days": 3,
            "penalty_per_day": 1500.0,
            "priority": "urgent",
        },
    },
    "sporting_goods_factory": {
        "name": "运动器材厂",
        "description": "运动鞋/球拍/健身器材生产 — 裁断/针车/成型/涂装",
        "products": [
            {"id": f"prod-{uuid.uuid4().hex[:8]}", "code": "SHOE-R001", "name": "跑步鞋Pro", "category": "shoe", "standard_cost": 120.0},
            {"id": f"prod-{uuid.uuid4().hex[:8]}", "code": "RACKET-T001", "name": "碳纤维羽毛球拍", "category": "racket", "standard_cost": 280.0},
            {"id": f"prod-{uuid.uuid4().hex[:8]}", "code": "DUMBBELL-K001", "name": "可调哑铃套装", "category": "dumbbell", "standard_cost": 350.0},
        ],
        "workstations": [
            {"code": "CUT-001", "name": "自动裁断机", "type": "cutting", "capacity_per_hour": 800},
            {"code": "SEW-001", "name": "高速针车线", "type": "sewing", "capacity_per_hour": 600},
            {"code": "LAST-001", "name": "成型贴底机", "type": "lasting", "capacity_per_hour": 400},
            {"code": "PAINT-001", "name": "涂装流水线", "type": "painting", "capacity_per_hour": 500},
            {"code": "PACK-001", "name": "成品包装线", "type": "packaging", "capacity_per_hour": 700},
        ],
        "workers": [
            {"code": "W-SPRT-001", "name": "林师傅", "skills": [{"code": "cutting", "level": 4, "score": 86}], "certificates": ["裁断技师证"], "efficiency": 0.89},
            {"code": "W-SPRT-002", "name": "吴师傅", "skills": [{"code": "sewing", "level": 5, "score": 91}], "certificates": ["针车高级技师证"], "efficiency": 0.93},
            {"code": "W-SPRT-003", "name": "郑技术员", "skills": [{"code": "lasting", "level": 3, "score": 79}], "certificates": ["成型技术员证"], "efficiency": 0.81},
            {"code": "W-SPRT-004", "name": "孙工程师", "skills": [{"code": "quality_control", "level": 4, "score": 87}], "certificates": ["QC工程师证"], "efficiency": 0.88},
        ],
        "routings": [
            {
                "id": f"rt-{uuid.uuid4().hex[:8]}",
                "product_id": "SHOE-R001",
                "steps": [
                    {"step_no": 1, "name": "材料检验", "station_type": "iqc"},
                    {"step_no": 2, "name": "裁断", "station_type": "cutting"},
                    {"step_no": 3, "name": "针车", "station_type": "sewing"},
                    {"step_no": 4, "name": "成型", "station_type": "lasting"},
                    {"step_no": 5, "name": "涂装", "station_type": "painting"},
                    {"step_no": 6, "name": "成品检验", "station_type": "oqc"},
                    {"step_no": 7, "name": "包装入库", "station_type": "packaging"},
                ]
            }
        ],
        "rush_order": {
            "title": "跑步鞋Pro-电商大促加急单",
            "quantity": 2000,
            "due_date_offset_days": 7,
            "penalty_per_day": 800.0,
            "priority": "high",
        },
    },
}


def generate_seed_data(industry_code: str) -> Dict[str, Any]:
    """生成指定行业的完整种子数据"""
    if industry_code not in INDUSTRIES:
        raise ValueError(f"未知行业: {industry_code}")

    industry = INDUSTRIES[industry_code]
    base_date = datetime.now()

    data = {
        "industry": industry["name"],
        "description": industry["description"],
        "generated_at": base_date.isoformat(),
        "products": industry["products"],
        "workstations": industry["workstations"],
        "workers": industry["workers"],
        "routings": industry["routings"],
        "rush_order": {
            **industry["rush_order"],
            "order_id": f"RUSH-{industry_code.upper()}-{base_date.strftime('%Y%m%d')}-{str(uuid.uuid4())[:6].upper()}",
            "planned_start": base_date.isoformat(),
            "due_date": (base_date + timedelta(days=industry["rush_order"]["due_date_offset_days"])).isoformat(),
        },
        "simulated_work_orders": [
            {
                "wo_code": f"WO-{industry_code[:3].upper()}-{base_date.strftime('%Y%m%d')}-{i+1:04d}",
                "product_code": product["code"],
                "planned_qty": random.randint(100, 1000),
                "status": random.choice(["pending", "released", "in_progress"]),
                "priority": random.choice(["low", "medium", "high"]),
                "created_by": f"W-{random.choice(range(1, 5)):03d}",
            }
            for i, product in enumerate(industry["products"])
        ],
    }

    return data


if __name__ == "__main__":
    import json
    print("=== EngHub v2.5 多行业种子数据生成器 ===")
    for code, industry in INDUSTRIES.items():
        data = generate_seed_data(code)
        print(f"\n📦 {data['industry']}:")
        print(f"   产品: {len(data['products'])} 种")
        print(f"   工位: {len(data['workstations'])} 个")
        print(f"   工人: {len(data['workers'])} 人")
        print(f"   急单: {data['rush_order']['title']} (数量: {data['rush_order']['quantity']}, 交期: {data['rush_order']['due_date_offset_days']}天, 罚款: ${data['rush_order']['penalty_per_day']}/天)")
        print(f"   已生成工单: {len(data['simulated_work_orders'])} 个")
        # 导出JSON
        with open(f"./data/{code}_seed.json", "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"   ✅ 数据已导出至 data/{code}_seed.json")


