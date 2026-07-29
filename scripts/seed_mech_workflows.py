"""
机械厂(FAC_MECH_001) 全工作流运营数据种子
============================================
基于实际人力结构(1044人)和行业运营量，建模7条核心工作流及其部门交叉点。

工作流模型：
WF1: 订单→交付流    销售→PMC→生产→品质→仓储→出货
WF2: 采购→收货流    PMC→采购→供应商→IQC→仓库
WF3: 生产→报工流    PMC→各生产部→报工→统计
WF4: 领料→消耗流    生产→仓库→库存扣减
WF5: 质量→判定流    品质↔所有生产部（IQC/IPQC/FQC）
WF6: 转序→流转流    工位间流转（跨部门交接）
WF7: 设备→维保流    设备→生产部（停机影响）

部门交叉点（= 需要人协调/录单的地方 = 文员存在的原因）：
X1: 采购×品质×仓储 → 收货三方确认
X2: 生产×仓储 → 领料/退料
X3: 生产×品质 → 首检/巡检/完工检
X4: 生产×生产 → 转序交接（关键零件一部→生产一部）
X5: 生产×仓储 → 成品入库
X6: 仓储×销售 → 出货装柜
X7: PMC×所有部门 → 工单下达/进度跟踪
"""
import asyncio
import asyncpg
import os
import uuid
import random
from datetime import date, datetime, timedelta

DB_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@db:5432/enghub").replace("+asyncpg", "")
FID = "FAC_MECH_001"

random.seed(2026)


def _id():
    return str(uuid.uuid4())


def _ts(days_ago, hour=8, minute=0):
    dt = datetime.now() - timedelta(days=days_ago)
    return dt.replace(hour=hour, minute=minute, second=0, microsecond=0)


# ═══════════════════════════════════════════
# 基础数据：物料主数据（按产品结构）
# ═══════════════════════════════════════════
MATERIALS = [
    # (code, name, category, unit, unit_cost, warehouse)
    # 原材料
    ("RM-STEEL-01", "Q235钢板 3mm", "raw", "kg", 4.5, "WH-RAW"),
    ("RM-STEEL-02", "45#圆钢 φ50", "raw", "kg", 5.2, "WH-RAW"),
    ("RM-CAST-01", "铸铁件毛坯(哑铃)", "raw", "pcs", 18.0, "WH-RAW"),
    ("RM-CAST-02", "铸铁件毛坯(滚轮)", "raw", "pcs", 8.5, "WH-RAW"),
    ("RM-PLASTIC-01", "PP塑料粒子", "raw", "kg", 9.8, "WH-RAW"),
    ("RM-PLASTIC-02", "PVC浸塑液", "raw", "kg", 12.5, "WH-RAW"),
    ("RM-WIRE-01", "铜芯线材 0.5mm²", "raw", "m", 0.8, "WH-RAW"),
    ("RM-WIRE-02", "端子接插件", "raw", "pcs", 0.35, "WH-RAW"),
    ("RM-PCB-01", "仪表PCB板", "raw", "pcs", 15.0, "WH-RAW"),
    ("RM-SENSOR-01", "压力传感器", "raw", "pcs", 28.0, "WH-RAW"),
    ("RM-PAINT-01", "环氧底漆", "raw", "L", 35.0, "WH-RAW"),
    ("RM-PAINT-02", "丙烯酸面漆", "raw", "L", 42.0, "WH-RAW"),
    ("RM-BOLT-01", "M8×30螺栓", "raw", "pcs", 0.15, "WH-RAW"),
    ("RM-PACK-01", "瓦楞纸箱(哑铃)", "raw", "pcs", 3.5, "WH-RAW"),
    ("RM-PACK-02", "泡棉衬垫", "raw", "pcs", 1.2, "WH-RAW"),
    # 半成品(WIP)
    ("WIP-BAR-01", "哑铃杆组件(精加工后)", "wip", "pcs", 22.0, "WH-WIP"),
    ("WIP-PLATE-01", "哑铃片(涂装后)", "wip", "pcs", 20.0, "WH-WIP"),
    ("WIP-WHEEL-01", "滚轮体(注塑后)", "wip", "pcs", 10.0, "WH-WIP"),
    ("WIP-WIRE-01", "线材组件(焊接后)", "wip", "pcs", 2.5, "WH-WIP"),
    ("WIP-PCBA-01", "仪表PCBA(组装后)", "wip", "pcs", 45.0, "WH-WIP"),
    # 成品
    ("FG-DUMBBELL-01", "包胶哑铃 10kg", "finished", "pair", 85.0, "WH-FG"),
    ("FG-DUMBBELL-02", "包胶哑铃 20kg", "finished", "pair", 145.0, "WH-FG"),
    ("FG-WHEEL-01", "健腹轮组件", "finished", "pcs", 35.0, "WH-FG"),
    ("FG-WIRE-01", " fitness线材总成", "finished", "pcs", 12.0, "WH-FG"),
    ("FG-METER-01", "数字压力仪表", "finished", "pcs", 120.0, "WH-FG"),
]

# 客户
CUSTOMERS = [
    ("CUS-001", "迪卡侬(上海)"),
    ("CUS-002", "亚马逊FBA(深圳仓)"),
    ("CUS-003", "李宁体育(东莞)"),
    ("CUS-004", "Walmart Buyer(HK)"),
    ("CUS-005", "京东京造(北京)"),
    ("CUS-006", "Keep健身(杭州)"),
]

# 供应商
SUPPLIERS = [
    ("SUP-001", "宝钢金属(佛山)"),
    ("SUP-002", "华塑新材料(东莞)"),
    ("SUP-003", "精达线材(惠州)"),
    ("SUP-004", "汇顶电子(深圳)"),
    ("SUP-005", "立邦涂料(广州)"),
    ("SUP-006", "裕同包装(东莞)"),
    ("SUP-007", "永年紧固件(邯郸)"),
]

# 工位ID映射（从DB获取）
STATION_MAP = {}  # station_code -> id

# 产品→工艺路线→工位序列
PRODUCT_ROUTES = {
    "FG-DUMBBELL-01": [
        ("精加工", "ST-JJG-01", "关键零件一部"),
        ("焊接", "ST-HJ-01", "生产一部"),
        ("涂装", "ST-TZ-01", "生产一部"),
        ("组立", "ST-ZL-01", "生产一部"),
        ("成品检", "ST-QC-02", "品质部"),
        ("包装", "ST-PK-01", "物流部"),
    ],
    "FG-WHEEL-01": [
        ("注塑", "ST-ZS-01", "关键零件一部"),
        ("精加工", "ST-JJG-01", "关键零件一部"),
        ("浸塑", "ST-JS-01", "关键零件一部"),
        ("组立", "ST-ZL-02", "生产一部"),
        ("成品检", "ST-QC-02", "品质部"),
        ("包装", "ST-PK-01", "物流部"),
    ],
    "FG-WIRE-01": [
        ("线材加工", "ST-XC-01", "生产二部"),
        ("焊接", "ST-HJ-01", "生产一部"),
        ("機電组装", "ST-JD-01", "生产二部"),
        ("仪表检测", "ST-YB-01", "生产二部"),
        ("成品检", "ST-QC-02", "品质部"),
        ("包装", "ST-PK-01", "物流部"),
    ],
    "FG-METER-01": [
        ("加工", "ST-JG-01", "生产一部"),
        ("機電组装", "ST-JD-01", "生产二部"),
        ("仪表校准", "ST-YB-01", "生产二部"),
        ("组立", "ST-ZL-03", "生产一部"),
        ("成品检", "ST-QC-02", "品质部"),
        ("包装", "ST-PK-01", "物流部"),
    ],
}


async def main():
    conn = await asyncpg.connect(DB_URL)

    # 获取工位ID
    rows = await conn.fetch(
        "SELECT station_code, id FROM stations WHERE factory_id=$1", FID
    )
    for r in rows:
        STATION_MAP[r["station_code"]] = r["id"]
    print(f"[0] 已加载 {len(STATION_MAP)} 个工位ID")

    # ═══ 清理旧数据 ═══
    for tbl in ["inventory_transactions", "inventory", "inbound_orders",
                "outbound_orders", "inspection_tasks", "purchase_orders",
                "purchase_requisitions", "work_orders", "sales_orders"]:
        try:
            await conn.execute(f"DELETE FROM {tbl} WHERE factory_id=$1", FID)
        except Exception:
            pass
    print("[1] 已清理旧运营数据")

    # ═══ WF基础: 物料 + 库存 ═══
    inv_ids = {}  # material_code -> inventory_id
    for code, name, cat, unit, cost, wh in MATERIALS:
        mat_id = f"MAT-{code}"
        inv_id = _id()
        inv_ids[code] = inv_id
        # 库存量：原材料充足，WIP中等，成品按订单
        if cat == "raw":
            qty = random.randint(500, 5000)
        elif cat == "wip":
            qty = random.randint(100, 800)
        else:
            qty = random.randint(50, 300)
        await conn.execute("""
            INSERT INTO inventory (id, material_id, material_code, material_name, factory_id,
                warehouse_id, total_qty, available_qty, reserved_qty, unit_cost, unit, status, created_at, updated_at, last_movement_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,'active',NOW(),NOW(),NOW())
        """, inv_id, mat_id, code, name, FID, wh, qty, int(qty*0.85), int(qty*0.15), cost, unit)
    print(f"[2] 已创建 {len(MATERIALS)} 个物料+库存")

    # ═══ WF1: 销售订单（月30-50张） ═══
    so_ids = []
    products_fg = ["FG-DUMBBELL-01", "FG-DUMBBELL-02", "FG-WHEEL-01", "FG-WIRE-01", "FG-METER-01"]
    product_names = {"FG-DUMBBELL-01": "包胶哑铃10kg", "FG-DUMBBELL-02": "包胶哑铃20kg",
                     "FG-WHEEL-01": "健腹轮组件", "FG-WIRE-01": "fitness线材总成", "FG-METER-01": "数字压力仪表"}
    for i in range(40):
        so_id = _id()
        so_ids.append(so_id)
        cust_code, cust_name = random.choice(CUSTOMERS)
        prod = random.choice(products_fg)
        qty = random.choice([500, 1000, 2000, 3000, 5000, 8000, 10000])
        days_ago = random.randint(0, 30)
        delivery = date.today() + timedelta(days=random.randint(5, 25))
        status = random.choice(["pending", "confirmed", "in_production", "completed", "shipped"])
        priority = random.choice(["low", "medium", "medium", "high", "urgent"])
        price = {"FG-DUMBBELL-01": 85, "FG-DUMBBELL-02": 145, "FG-WHEEL-01": 35,
                 "FG-WIRE-01": 12, "FG-METER-01": 120}[prod]
        await conn.execute("""
            INSERT INTO sales_orders (id, order_code, factory_id, customer_name, customer_code,
                product_id, product_name, quantity, unit, delivery_date, priority, status,
                unit_price, total_amount, currency, created_by, created_at, updated_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'pcs',$9,$10,$11,$12,$13,'CNY','PMC',$14,NOW())
        """, so_id, f"SO-MECH-{2601+i:04d}", FID, cust_name, cust_code,
            prod, product_names[prod], qty, delivery, priority, status,
            price, price * qty, _ts(days_ago))
    print(f"[3] WF1: 已创建 {len(so_ids)} 张销售订单")

    # ═══ WF3: 生产工单（月300-500张，当前在制+完工） ═══
    wo_ids = []
    wo_counter = 0
    for so_id in so_ids[:30]:  # 30张SO分解为工单
        so_row = await conn.fetchrow("SELECT * FROM sales_orders WHERE id=$1", so_id)
        prod = so_row["product_id"]
        route = PRODUCT_ROUTES.get(prod)
        if not route:
            continue
        # 每张SO → 1张主工单 + 按工序分子工单
        master_id = _id()
        wo_counter += 1
        wo_code = f"WO-MECH-{wo_counter:05d}"
        qty = so_row["quantity"]
        status = so_row["status"]
        if status in ("pending", "confirmed"):
            wo_status = "released"
        elif status == "in_production":
            wo_status = "in_progress"
        else:
            wo_status = "completed"

        # 当前所在工序
        if wo_status == "in_progress":
            current_step = random.randint(1, len(route) - 1)
        elif wo_status == "completed":
            current_step = len(route)
        else:
            current_step = 0

        station_code = route[min(current_step, len(route)-1)][1]
        station_id = STATION_MAP.get(station_code)

        completed = int(qty * random.uniform(0.3, 0.9)) if wo_status == "in_progress" else (qty if wo_status == "completed" else 0)
        defect = int(completed * random.uniform(0.01, 0.05))
        days_ago = random.randint(1, 20)

        await conn.execute("""
            INSERT INTO work_orders (id, factory_id, work_order_code, sales_order_id, product_id,
                planned_qty, unit, completed_qty, good_qty, defect_qty, scrap_qty, status, priority,
                planned_start, planned_due, actual_start, current_routing_step,
                assigned_station_id, wo_type, created_by, created_at, updated_at)
            VALUES ($1,$2,$3,$4,$5,$6,'pcs',$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,'master','PMC',$18,NOW())
        """, master_id, FID, wo_code, so_id, prod, qty,
            completed, completed - defect, defect, int(defect*0.3),
            wo_status, so_row["priority"],
            _ts(days_ago + 5), _ts(days_ago - 10) if days_ago > 10 else datetime.now() + timedelta(days=5),
            _ts(days_ago) if wo_status != "released" else None,
            current_step, station_id, _ts(days_ago + 6))
        wo_ids.append((master_id, wo_code, prod, route, wo_status, qty, completed))

    print(f"[4] WF3: 已创建 {len(wo_ids)} 张生产工单")

    # ═══ WF2: 采购订单（月150-250张） ═══
    # 先插入供应商主数据
    for sup_code, sup_name in SUPPLIERS:
        await conn.execute("""
            INSERT INTO suppliers (id, factory_id, supplier_code, supplier_name, category, rating, on_time_rate, quality_rate, avg_lead_days, created_at, updated_at)
            VALUES ($1,$2,$3,$4,'general',3.5,92.0,97.0,7,NOW(),NOW())
            ON CONFLICT (id) DO NOTHING
        """, sup_code, FID, sup_code, sup_name)
    print(f"[4.5] 已创建 {len(SUPPLIERS)} 个供应商")

    po_count = 0
    raw_mats = [(c, n, cost) for c, n, cat, u, cost, w in MATERIALS if cat == "raw"]
    for i in range(60):
        po_id = _id()
        mat_code, mat_name, cost = random.choice(raw_mats)
        sup_code, sup_name = random.choice(SUPPLIERS)
        qty = random.choice([100, 200, 500, 1000, 2000, 5000])
        days_ago = random.randint(0, 25)
        expected = date.today() + timedelta(days=random.randint(-5, 10))
        status = random.choice(["draft", "confirmed", "in_transit", "received", "received", "received"])
        actual = date.today() - timedelta(days=random.randint(0, 3)) if status == "received" else None
        po_count += 1
        await conn.execute("""
            INSERT INTO purchase_orders (id, factory_id, po_code, supplier_id, supplier_name,
                material_code, material_name, qty, unit_price, total_amount, currency,
                order_date, expected_date, actual_date, status, auto_generated, created_by, created_at, updated_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,'CNY',$11,$12,$13,$14,false,'采购部',$15,NOW())
        """, po_id, FID, f"PO-MECH-{po_count:04d}", sup_code, sup_name,
            mat_code, mat_name, qty, cost * random.uniform(0.9, 1.1),
            round(qty * cost * random.uniform(0.9, 1.1), 2),
            date.today() - timedelta(days=days_ago), expected, actual, status, _ts(days_ago))
    print(f"[5] WF2: 已创建 {po_count} 张采购订单")

    # ═══ WF2+X1: 收货单（采购×品质×仓储 交叉） ═══
    inb_count = 0
    for i in range(45):
        inb_id = _id()
        mat_code, mat_name, cat, unit, cost, wh = random.choice(
            [m for m in MATERIALS if m[2] == "raw"])
        sup_code, sup_name = random.choice(SUPPLIERS)
        qty = random.choice([200, 500, 1000, 2000, 5000])
        days_ago = random.randint(0, 20)
        status = random.choice(["pending", "inspecting", "completed", "completed", "completed"])
        inb_count += 1
        await conn.execute("""
            INSERT INTO inbound_orders (id, inbound_code, factory_id, warehouse_id, material_id,
                material_code, quantity, batch_code, supplier_id, unit_cost, inbound_type, status, created_by, created_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,'purchase',$11,'仓管',$12)
        """, inb_id, f"INB-{inb_count:05d}", FID, wh, f"MAT-{mat_code}",
            mat_code, qty, f"B{2607-days_ago:04d}{random.randint(1,9):01d}",
            sup_code, cost, status, _ts(days_ago, random.randint(7, 16)))
    print(f"[6] WF2+X1: 已创建 {inb_count} 张收货单")

    # ═══ WF4+X2: 领料/出库（生产×仓储 交叉） ═══
    out_count = 0
    for wo_id, wo_code, prod, route, status, qty, comp in wo_ids:
        if status in ("in_progress", "completed"):
            # 每张在制工单 1-3 次领料
            for _ in range(random.randint(1, 3)):
                out_id = _id()
                mat_code = random.choice([m[0] for m in MATERIALS if m[2] == "raw"])
                out_qty = random.randint(50, 500)
                days_ago = random.randint(0, 15)
                out_count += 1
                await conn.execute("""
                    INSERT INTO outbound_orders (id, outbound_code, factory_id, warehouse_id,
                        material_id, quantity, work_order_id, outbound_type, status, created_by, created_at)
                    VALUES ($1,$2,$3,'WH-RAW',$4,$5,$6,'production','completed','仓管',$7)
                """, out_id, f"OUT-{out_count:05d}", FID, f"MAT-{mat_code}",
                    out_qty, wo_id, _ts(days_ago, random.randint(7, 11)))
    print(f"[7] WF4+X2: 已创建 {out_count} 张领料单")

    # ═══ WF5+X3: 检验任务（品质×生产 交叉） ═══
    insp_count = 0
    # IQC（来料检）
    for i in range(30):
        insp_id = _id()
        mat_code, mat_name = random.choice([(m[0], m[1]) for m in MATERIALS if m[2] == "raw"])
        batch_qty = random.choice([200, 500, 1000, 2000])
        sample = min(80, int(batch_qty * 0.1))
        defect = random.randint(0, 5)
        result = "pass" if defect <= 3 else ("conditional" if defect <= 5 else "fail")
        days_ago = random.randint(0, 20)
        insp_count += 1
        await conn.execute("""
            INSERT INTO inspection_tasks (id, factory_id, task_code, inspect_type, source_type,
                material_id, material_code, material_name, batch_qty, sample_qty, aql_level,
                status, defect_qty, defect_rate, result, disposition, inspector, created_at)
            VALUES ($1,$2,$3,'IQC','inbound',$4,$5,$6,$7,$8,'General-II','completed',$9,$10,$11,$12,$13,$14)
        """, insp_id, FID, f"IQC-{insp_count:05d}", f"MAT-{mat_code}", mat_code, mat_name,
            batch_qty, sample, defect, round(defect/max(sample,1)*100, 2), result,
            "入库" if result == "pass" else ("让步接收" if result == "conditional" else "退货"),
            random.choice(["黄质检", "赵检验", "钱QC"]), _ts(days_ago, 9))

    # IPQC（巡检）
    for i in range(50):
        insp_id = _id()
        wo_pick = random.choice(wo_ids) if wo_ids else None
        if not wo_pick:
            continue
        station_code = wo_pick[3][min(wo_pick[6] // max(wo_pick[5], 1) * len(wo_pick[3]), len(wo_pick[3])-1)][1]
        batch_qty = random.randint(50, 300)
        sample = min(32, batch_qty)
        defect = random.randint(0, 4)
        result = "pass" if defect <= 2 else "fail"
        days_ago = random.randint(0, 15)
        insp_count += 1
        await conn.execute("""
            INSERT INTO inspection_tasks (id, factory_id, task_code, inspect_type, source_type,
                work_order_id, station_id, batch_qty, sample_qty, aql_level,
                status, defect_qty, defect_rate, result, disposition, inspector, created_at)
            VALUES ($1,$2,$3,'IPQC','work_order',$4,$5,$6,$7,'General-II','completed',$8,$9,$10,$11,$12,$13)
        """, insp_id, FID, f"IPQC-{insp_count:05d}", wo_pick[0],
            STATION_MAP.get(station_code), batch_qty, sample,
            defect, round(defect/max(sample,1)*100, 2), result,
            "继续生产" if result == "pass" else "停线整改",
            random.choice(["黄质检", "赵检验", "钱QC"]), _ts(days_ago, random.randint(8, 16)))

    # FQC（出货检）
    for i in range(25):
        insp_id = _id()
        prod = random.choice(products_fg)
        batch_qty = random.choice([500, 1000, 2000, 3000])
        sample = min(125, int(batch_qty * 0.05))
        defect = random.randint(0, 6)
        result = "pass" if defect <= 4 else ("conditional" if defect <= 6 else "fail")
        days_ago = random.randint(0, 15)
        insp_count += 1
        await conn.execute("""
            INSERT INTO inspection_tasks (id, factory_id, task_code, inspect_type, source_type,
                product_id, batch_qty, sample_qty, aql_level,
                status, defect_qty, defect_rate, result, disposition, inspector, created_at)
            VALUES ($1,$2,$3,'FQC','outbound',$4,$5,$6,'General-II','completed',$7,$8,$9,$10,$11,$12)
        """, insp_id, FID, f"FQC-{insp_count:05d}", prod,
            batch_qty, sample, defect, round(defect/max(sample,1)*100, 2), result,
            "放行出货" if result == "pass" else ("返工" if result == "conditional" else "报废"),
            random.choice(["黄质检", "赵检验", "钱QC"]), _ts(days_ago, 14))
    print(f"[8] WF5+X3: 已创建 {insp_count} 张检验单(IQC/IPQC/FQC)")

    # ═══ WF6+X4: 库存流水（转序/领料/入库 全记录） ═══
    txn_count = 0
    for wo_id, wo_code, prod, route, status, qty, comp in wo_ids:
        if status in ("in_progress", "completed"):
            # 每道工序产生一条转序记录
            for step_idx in range(min(comp // max(qty // len(route), 1), len(route))):
                txn_id = _id()
                txn_count += 1
                step_name, station_code, dept = route[step_idx]
                await conn.execute("""
                    INSERT INTO inventory_transactions (id, factory_id, material_id, batch_code,
                        transaction_type, quantity, reference_type, reference_id, operator, remark, created_at)
                    VALUES ($1,$2,$3,$4,'transfer',$5,'work_order',$6,$7,$8,$9)
                """, txn_id, FID, f"WIP-{prod}", f"B-WO-{wo_code}",
                    random.randint(50, 300), wo_id,
                    random.choice(["张师傅", "李工", "王技师"]),
                    f"WF6转序: {step_name}→{route[min(step_idx+1, len(route)-1)][0]} ({dept}→{route[min(step_idx+1, len(route)-1)][2]})",
                    _ts(random.randint(0, 15), random.randint(7, 17)))
    print(f"[9] WF6+X4: 已创建 {txn_count} 条转序流水")

    # ═══ WF1+X6: 出货单（仓储×销售 交叉） ═══
    ship_count = 0
    for so_id in so_ids:
        so_row = await conn.fetchrow("SELECT * FROM sales_orders WHERE id=$1 AND status IN ('completed','shipped')", so_id)
        if not so_row:
            continue
        out_id = _id()
        ship_count += 1
        await conn.execute("""
            INSERT INTO outbound_orders (id, outbound_code, factory_id, warehouse_id,
                material_id, quantity, outbound_type, status, created_by, created_at, completed_at)
            VALUES ($1,$2,$3,'WH-FG',$4,$5,'shipment','completed','物流部',$6,$7)
        """, out_id, f"SHP-{ship_count:05d}", FID, so_row["product_id"],
            so_row["quantity"], _ts(random.randint(0, 10), 15), _ts(random.randint(0, 10), 17))
    print(f"[10] WF1+X6: 已创建 {ship_count} 张出货单")

    # ═══ 验证 ═══
    print("\n" + "="*60)
    print("✅ 机械厂工作流数据种子完成")
    print("="*60)
    checks = [
        ("物料/库存", "SELECT count(*) FROM inventory WHERE factory_id=$1"),
        ("销售订单", "SELECT count(*) FROM sales_orders WHERE factory_id=$1"),
        ("生产工单", "SELECT count(*) FROM work_orders WHERE factory_id=$1"),
        ("采购订单", "SELECT count(*) FROM purchase_orders WHERE factory_id=$1"),
        ("收货单", "SELECT count(*) FROM inbound_orders WHERE factory_id=$1"),
        ("领料/出货", "SELECT count(*) FROM outbound_orders WHERE factory_id=$1"),
        ("检验任务", "SELECT count(*) FROM inspection_tasks WHERE factory_id=$1"),
        ("库存流水", "SELECT count(*) FROM inventory_transactions WHERE factory_id=$1"),
    ]
    for label, sql in checks:
        cnt = await conn.fetchval(sql, FID)
        print(f"  {label}: {cnt}")

    # 工作流交叉统计
    print("\n--- 工作流交叉点数据量 ---")
    iqc = await conn.fetchval("SELECT count(*) FROM inspection_tasks WHERE factory_id=$1 AND inspect_type='IQC'", FID)
    ipqc = await conn.fetchval("SELECT count(*) FROM inspection_tasks WHERE factory_id=$1 AND inspect_type='IPQC'", FID)
    fqc = await conn.fetchval("SELECT count(*) FROM inspection_tasks WHERE factory_id=$1 AND inspect_type='FQC'", FID)
    print(f"  X1 采购×品质×仓储(IQC): {iqc}")
    print(f"  X3 生产×品质(IPQC): {ipqc}")
    print(f"  X6 仓储×销售(FQC+出货): {fqc}+{ship_count}")
    print(f"  X2 生产×仓储(领料): {out_count}")
    print(f"  X4 生产×生产(转序): {txn_count}")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
