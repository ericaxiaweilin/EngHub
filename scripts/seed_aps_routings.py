"""
为 FAC_MECH_001 机械厂补充工艺路线模板 + 工序步骤，并关联工单
解决 APS 排程"无可用资源/无待排程工单"问题
"""
import asyncio
import uuid
from datetime import datetime

from database.db_config import db_config
from sqlalchemy import text

FACTORY = "FAC_MECH_001"

# 产品 -> 工艺路线定义 (seq, process_code, operation_name, work_center, standard_hours单件工时, is_qc_gate)
ROUTING_DEFS = {
    "FG-DUMBBELL-01": {
        "name": "哑铃生产工艺",
        "code": "RT-DUMBBELL-V1",
        "steps": [
            (1, "OP10", "来料检验", "ST-QC-01", 0.003, True),
            (2, "OP20", "注塑成型", "ST-ZS-01", 0.008, False),
            (3, "OP30", "浸塑处理", "ST-JS-01", 0.006, False),
            (4, "OP40", "哑铃组装", "ST-YL-01", 0.010, False),
            (5, "OP50", "成品检验", "ST-QC-02", 0.003, True),
            (6, "OP60", "包装入库", "ST-PK-01", 0.004, False),
        ],
    },
    "FG-WIRE-01": {
        "name": "线材生产工艺",
        "code": "RT-WIRE-V1",
        "steps": [
            (1, "OP10", "来料检验", "ST-QC-01", 0.003, True),
            (2, "OP20", "线材加工", "ST-XC-01", 0.008, False),
            (3, "OP30", "焊接", "ST-HJ-01", 0.010, False),
            (4, "OP40", "组立一线", "ST-ZL-01", 0.008, False),
            (5, "OP50", "成品检验", "ST-QC-02", 0.003, True),
            (6, "OP60", "包装入库", "ST-PK-01", 0.004, False),
        ],
    },
    "FG-WHEEL-01": {
        "name": "滚轮生产工艺",
        "code": "RT-WHEEL-V1",
        "steps": [
            (1, "OP10", "来料检验", "ST-QC-01", 0.003, True),
            (2, "OP20", "粗加工", "ST-JG-01", 0.012, False),
            (3, "OP30", "精加工", "ST-JJG-01", 0.015, False),
            (4, "OP40", "涂装", "ST-TZ-01", 0.006, False),
            (5, "OP50", "滚轮组装", "ST-GL-01", 0.008, False),
            (6, "OP60", "成品检验", "ST-QC-02", 0.003, True),
            (7, "OP70", "包装入库", "ST-PK-01", 0.004, False),
        ],
    },
    "FG-METER-01": {
        "name": "仪表生产工艺",
        "code": "RT-METER-V1",
        "steps": [
            (1, "OP10", "来料检验", "ST-QC-01", 0.003, True),
            (2, "OP20", "注塑成型", "ST-ZS-01", 0.008, False),
            (3, "OP30", "仪表装配", "ST-YB-01", 0.010, False),
            (4, "OP40", "机电装配", "ST-JD-01", 0.008, False),
            (5, "OP50", "成品检验", "ST-QC-02", 0.003, True),
            (6, "OP60", "包装入库", "ST-PK-01", 0.004, False),
        ],
    },
}


async def seed():
    async with db_config.session_factory() as session:
        now = datetime.utcnow()
        product_template_map = {}

        for product_id, defn in ROUTING_DEFS.items():
            # 检查是否已存在
            existing = await session.execute(
                text("SELECT id FROM routing_templates WHERE template_code = :code"),
                {"code": defn["code"]},
            )
            row = existing.fetchone()
            if row:
                template_id = str(row[0])
                # 已存在：更新工序工时为单件工时
                for seq, pcode, op_name, wc, hours, is_qc in defn["steps"]:
                    await session.execute(
                        text("""
                            UPDATE routing_template_steps SET standard_hours = :hours, work_center = :wc
                            WHERE template_id = :tid AND seq = :seq
                        """),
                        {"hours": hours, "wc": wc, "tid": template_id, "seq": seq},
                    )
                print(f"[updated] {defn['code']} steps hours")
            else:
                template_id = str(uuid.uuid4())
                await session.execute(
                    text("""
                        INSERT INTO routing_templates (id, template_code, template_name, factory_id, description, is_active, created_by, created_at, updated_at)
                        VALUES (:id, :code, :name, :factory, :desc, true, 'system', :now, :now)
                    """),
                    {"id": template_id, "code": defn["code"], "name": defn["name"],
                     "factory": FACTORY, "desc": f"{product_id} 标准工艺路线", "now": now},
                )
                for seq, pcode, op_name, wc, hours, is_qc in defn["steps"]:
                    await session.execute(
                        text("""
                            INSERT INTO routing_template_steps (id, template_id, seq, process_code, operation_name, work_center, standard_hours, is_parallel, is_qc_gate, remark, created_at)
                            VALUES (:id, :tid, :seq, :pcode, :op, :wc, :hours, false, :qc, :remark, :now)
                        """),
                        {"id": str(uuid.uuid4()), "tid": template_id, "seq": seq,
                         "pcode": pcode, "op": op_name, "wc": wc, "hours": hours,
                         "qc": is_qc, "remark": "", "now": now},
                    )
                print(f"[created] {defn['code']} ({defn['name']}) with {len(defn['steps'])} steps")

            product_template_map[product_id] = template_id

        # 关联工单
        for product_id, template_id in product_template_map.items():
            result = await session.execute(
                text("""
                    UPDATE work_orders SET routing_template_id = :tid
                    WHERE factory_id = :factory AND product_id = :pid
                      AND routing_template_id IS NULL
                      AND status IN ('released', 'in_progress', 'pending', 'created')
                """),
                {"tid": template_id, "factory": FACTORY, "pid": product_id},
            )
            print(f"[linked] {product_id} -> {result.rowcount} work orders")

        await session.commit()
        print("\nDone! Seed complete.")


if __name__ == "__main__":
    asyncio.run(seed())
