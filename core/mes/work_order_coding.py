"""
Work Order Coding System - 工单体系化编码模块（唯一编码源）
============================================================

设计目标：解决工单编码"乱跑、难追踪"问题，将散落各处的多套编码生成器
收敛到本模块，统一遵循工业规范（ISA-95 / ISO 9001 可追溯性 / SAP 工序惯例）。

编码结构（带工厂段 + 类型 + 日期 + 流水 + 工序派生）：

    主工单码   : {PLANT}-{TYPE}{DATE}-{SEQ}
                 例 ELEC-S20260720-001
    工序工单码 : {主工单码}-{PROCESS}{OP_SEQ}
                 例 ELEC-S20260720-001-SMT01

字段含义：
    PLANT   工厂短码（由 factory_id 推导，多工厂追踪无歧义，对齐 SAP 按工厂分号段惯例）
    TYPE    工单类型：S=标准量产 T=试产 R=返工 M=模具 E=工程样品
    DATE    创建日期 YYYYMMDD
    SEQ     当日该类型真实递增流水号（001-999，告别随机 UUID）
    PROCESS 行业通用英文工序代码（见 PROCESS_CODES，如 SMT/INJ/MACH/ASSY）
    OP_SEQ  同一工序内的道次序号（01/02，区分同工序多道，如 SMT01 锡膏印刷 / SMT02 贴片）

可追溯性（编码即关系，不查库即可解析）：
    1. 向上追溯：工序工单码截取最后一个 '-' 之前 = 主工单码
    2. 向下展开：主工单码做前缀匹配 = 其全部工序工单
    3. 看码知工序：PROCESS 段直接标识工序，无需查表
    4. 看序号知批次：末两位 = 该工序内道次
"""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from database.models import Routing, WorkOrder

# ============================================================
# 工序代码字典（行业通用英文缩写）
# ============================================================
# keywords 用于把工艺路线里的中文工序名/工位解析到标准代码。
PROCESS_CODES: Dict[str, Dict[str, Any]] = {
    "CUT":  {"name": "下料/备料", "en": "Cutting/Blanking",
             "keywords": ["下料", "备料", "切割", "cut", "blank"]},
    "MACH": {"name": "机加", "en": "Machining",
             "keywords": ["机加", "机械加工", "车削", "铣削", "铣", "钻孔", "cnc", "mach", "turn", "mill", "drill"]},
    "INJ":  {"name": "注塑", "en": "Injection Molding",
             "keywords": ["注塑", "注射", "inj", "mold", "mould"]},
    "EDM":  {"name": "电火花", "en": "EDM (Electric Discharge Machining)",
             "keywords": ["电火花", "火花", "edm"]},
    "WCUT": {"name": "线切割", "en": "Wire Cutting",
             "keywords": ["线切割", "线割", "wire_cut", "wire"]},
    "WELD": {"name": "焊接", "en": "Welding",
             "keywords": ["焊接", "回流焊", "波峰焊", "weld", "reflow"]},
    "PAINT": {"name": "涂装", "en": "Painting/Coating",
              "keywords": ["涂装", "喷涂", "喷漆", "paint", "coat"]},
    "ASSY": {"name": "组立/装配", "en": "Assembly",
             "keywords": ["组立", "装配", "组装", "assy", "assembl"]},
    "PKG":  {"name": "包装", "en": "Packaging",
             "keywords": ["包装", "打包", "pack"]},
    "QC":   {"name": "检验", "en": "Quality Control",
             "keywords": ["检验", "检测", "测试", "aoi", "qc", "inspect", "test"]},
    "SMT":  {"name": "贴片", "en": "Surface Mount Technology",
             "keywords": ["贴片", "锡膏", "印刷", "smt"]},
    "DIP":  {"name": "插件", "en": "DIP Insertion",
             "keywords": ["插件", "dip"]},
    "STMP": {"name": "冲压", "en": "Stamping",
             "keywords": ["冲压", "stamp", "press"]},
    "CAST": {"name": "铸造", "en": "Casting",
             "keywords": ["铸造", "cast"]},
    "HT":   {"name": "热处理", "en": "Heat Treatment",
             "keywords": ["热处理", "heat"]},
    "FIN":  {"name": "表面处理", "en": "Finishing",
             "keywords": ["表面处理", "电镀", "阳极", "finish"]},
    "GRD":  {"name": "研磨", "en": "Grinding",
             "keywords": ["研磨", "磨削", "grind"]},
    "SEW":  {"name": "针车/缝纫", "en": "Sewing",
             "keywords": ["针车", "缝纫", "sew"]},
    "FORM": {"name": "成型", "en": "Forming/Lasting",
             "keywords": ["成型", "贴底", "lasting", "form"]},
    "GEN":  {"name": "通用工序", "en": "General",
             "keywords": []},
}

# 工单类型字典
WO_TYPES: Dict[str, str] = {
    "S": "标准量产",
    "T": "试产",
    "R": "返工",
    "M": "模具",
    "E": "工程样品",
}

# 工位类型 → 标准工序代码（工艺路线 step.station_type 优先按此映射，最可靠）
STATION_TYPE_TO_CODE: Dict[str, str] = {
    "smt": "SMT", "reflow": "WELD", "test": "QC", "dip": "DIP",
    "packaging": "PKG", "pack": "PKG", "assembly": "ASSY", "assy": "ASSY",
    "machining": "MACH", "cnc": "MACH", "mold": "INJ", "injection": "INJ",
    "welding": "WELD", "edm": "EDM", "wire_cut": "WCUT", "raw_material": "CUT",
    "painting": "PAINT", "coating": "PAINT", "inspection": "QC", "qc": "QC",
    "iqc": "QC", "oqc": "QC", "ipqc": "QC",
    "cutting": "CUT", "stamping": "STMP", "grinding": "GRD",
    "sewing": "SEW", "lasting": "FORM", "forming": "FORM",
}


# ============================================================
# 纯函数：工厂短码 / 工序解析 / 编码生成 / 编码解析
# ============================================================

def derive_plant_code(factory_id: str) -> str:
    """从 factory_id 推导工厂短码（PLANT 段）。

    例：FAC_ELEC_DEMO_2026 -> ELEC；FAC_MOLD_DEMO_2026 -> MOLD。
    规则：按 '_' 切分，剔除 FAC/DEMO/FACTORY 及纯数字（年份），取首个有意义片段前 4 位。
    """
    if not factory_id:
        return "GEN"
    skip = {"FAC", "DEMO", "FACTORY", "PLANT"}
    parts = factory_id.upper().split("_")
    meaningful = [p for p in parts if p and p not in skip and not p.isdigit()]
    if meaningful:
        return meaningful[0][:4]
    return factory_id[:4].upper() or "GEN"


def resolve_operation_code(step: Dict[str, Any], process_codes: Optional[Dict[str, Dict[str, Any]]] = None) -> str:
    """把工艺路线的一道工序解析为标准工序代码。

    优先按 station_type 映射（最可靠），其次按工序名关键词匹配，无法识别返回 GEN。
    process_codes: 可传入 DB 加载的工序字典（覆盖默认硬编码）。
    """
    codes = process_codes or PROCESS_CODES
    stype = str(step.get("station_type") or step.get("station_id") or "").lower()
    if stype in STATION_TYPE_TO_CODE:
        return STATION_TYPE_TO_CODE[stype]
    name = str(step.get("name") or step.get("operation_name") or "").lower()
    for code, meta in codes.items():
        for kw in meta.get("keywords", []):
            if kw and kw.lower() in name:
                return code
    return "GEN"


def generate_master_code(plant_code: str, wo_type: str, date_str: str, seq: int) -> str:
    """生成主工单码：{PLANT}-{TYPE}{DATE}-{SEQ:03d}，例 ELEC-S20260720-001。"""
    return f"{plant_code}-{wo_type}{date_str}-{seq:03d}"


def generate_operation_code(master_code: str, op_code: str, op_seq: int) -> str:
    """生成工序工单码：{主工单码}-{PROCESS}{OP_SEQ:02d}，例 ELEC-S20260720-001-SMT01。"""
    return f"{master_code}-{op_code}{op_seq:02d}"


def parse_work_order_code(code: str) -> Dict[str, Any]:
    """反向解析工单码，返回结构化信息。兼容旧版 WO-* 编码（标记 legacy）。

    返回字段：
        is_master / is_operation / legacy
        plant, wo_type, date, seq              （主工单）
        master_code, process_code, op_seq      （工序工单）
    """
    if not code:
        return {"legacy": True, "raw": code}
    # 旧版编码（WO- 开头）无法按新规则解析
    if code.upper().startswith("WO-"):
        return {"legacy": True, "raw": code}

    parts = code.split("-")
    # 工序工单：PLANT-TYPEDATE-SEQ-PROCESSOPSEQ （4 段）
    if len(parts) == 4:
        master_code = "-".join(parts[:3])
        seg = parts[3]
        op_seq_str = seg[-2:]
        op_code = seg[:-2]
        return {
            "is_operation": True,
            "is_master": False,
            "master_code": master_code,
            "process_code": op_code,
            "process_name": PROCESS_CODES.get(op_code, {}).get("name", op_code),
            "op_seq": int(op_seq_str) if op_seq_str.isdigit() else None,
            "raw": code,
        }
    # 主工单：PLANT-TYPEDATE-SEQ （3 段）
    if len(parts) == 3:
        plant = parts[0]
        type_date = parts[1]
        seq_str = parts[2]
        wo_type = type_date[:1] if type_date else ""
        date_str = type_date[1:] if len(type_date) > 1 else ""
        return {
            "is_master": True,
            "is_operation": False,
            "plant": plant,
            "wo_type": wo_type,
            "wo_type_name": WO_TYPES.get(wo_type, wo_type),
            "date": date_str,
            "seq": int(seq_str) if seq_str.isdigit() else None,
            "raw": code,
        }
    return {"legacy": True, "raw": code}


# ============================================================
# 数据库相关：流水号 / 工艺路线加载 / 工序工单派生
# ============================================================

async def next_master_seq(db, plant_code: str, wo_type: str, date_str: str) -> int:
    """计算当日该工厂该类型的下一个主工单流水号（基于已存在主工单码解析最大值 +1）。"""
    prefix = f"{plant_code}-{wo_type}{date_str}-"
    stmt = select(WorkOrder.work_order_code).where(
        WorkOrder.wo_type == "master",
        WorkOrder.work_order_code.like(f"{prefix}%"),
    )
    rows = (await db.execute(stmt)).scalars().all()
    max_seq = 0
    for code in rows:
        seq_str = code[len(prefix):].split("-")[0]
        if seq_str.isdigit():
            max_seq = max(max_seq, int(seq_str))
    return max_seq + 1


async def generate_master_work_order_code(
    db, factory_id: str, wo_type: str = "S", when: Optional[datetime] = None
) -> str:
    """生成主工单码的唯一入口（供各创建路径统一调用）。"""
    when = when or datetime.now()
    plant = derive_plant_code(factory_id)
    date_str = when.strftime("%Y%m%d")
    seq = await next_master_seq(db, plant, wo_type, date_str)
    return generate_master_code(plant, wo_type, date_str, seq)


async def load_routing_steps(db, master_wo: WorkOrder) -> List[Dict[str, Any]]:
    """加载主工单对应工艺路线的工序清单。

    优先按 routing_id，其次按 product_id 取最新激活工艺路线；无则返回 []。
    """
    if getattr(master_wo, "routing_id", None):
        rt = (await db.execute(
            select(Routing).where(Routing.id == master_wo.routing_id)
        )).scalar_one_or_none()
        if rt and rt.steps:
            return rt.steps
    rt = (await db.execute(
        select(Routing)
        .where(Routing.product_id == master_wo.product_id, Routing.is_active == True)  # noqa: E712
        .order_by(Routing.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if rt and rt.steps:
        return rt.steps
    return []


async def derive_operation_work_orders(
    db,
    master_wo: WorkOrder,
    created_by: str = "system",
    steps: Optional[List[Dict[str, Any]]] = None,
) -> List[WorkOrder]:
    """按工艺路线为主工单一次性派生全部工序工单（对齐 ISA-95 计划层）。

    steps 为空时自动按 master_wo 的工艺路线加载。无工艺路线则返回 []（仅主工单，向后兼容）。
    同一工序代码出现多道时，用 OP_SEQ 递增区分（如 SMT01 锡膏印刷 / SMT02 贴片）。
    工序代码字典优先从 DB 码表加载（支持用户自定义扩展），fallback 硬编码。
    """
    if steps is None:
        steps = await load_routing_steps(db, master_wo)
    if not steps:
        return []

    # 从 DB 码表加载工序字典（支持自定义扩展），失败则 fallback 硬编码
    try:
        from api.services.code_table_service import CodeTableService
        svc = CodeTableService(db)
        db_codes = await svc.get_process_codes_dict()
        process_codes = db_codes if db_codes else PROCESS_CODES
    except Exception:
        process_codes = PROCESS_CODES

    op_counters: Dict[str, int] = {}
    created: List[WorkOrder] = []
    for step in steps:
        op_code = resolve_operation_code(step, process_codes=process_codes)
        op_counters[op_code] = op_counters.get(op_code, 0) + 1
        op_seq = op_counters[op_code]
        op_wo_code = generate_operation_code(master_wo.work_order_code, op_code, op_seq)
        op_name = process_codes.get(op_code, {}).get("name", op_code)
        step_name = step.get("name") or step.get("operation_name") or op_name
        op_wo = WorkOrder(
            id=str(uuid.uuid4()),
            work_order_code=op_wo_code,
            factory_id=master_wo.factory_id,
            product_id=master_wo.product_id,
            routing_id=master_wo.routing_id,
            planned_qty=master_wo.planned_qty,
            unit=master_wo.unit,
            planned_start=master_wo.planned_start,
            planned_due=master_wo.planned_due,
            priority=master_wo.priority,
            status="pending",
            sales_order_id=master_wo.sales_order_id,
            bom_version=master_wo.bom_version,
            wo_type="operation",
            process_code=op_code,
            operation_seq=op_seq,
            parent_work_order_id=master_wo.id,
            created_by=created_by,
            remark=f"由主工单 {master_wo.work_order_code} 派生｜{op_name}（{step_name}）第{op_seq}道",
        )
        db.add(op_wo)
        created.append(op_wo)
    return created


__all__ = [
    "PROCESS_CODES",
    "WO_TYPES",
    "STATION_TYPE_TO_CODE",
    "derive_plant_code",
    "resolve_operation_code",
    "generate_master_code",
    "generate_operation_code",
    "parse_work_order_code",
    "next_master_seq",
    "generate_master_work_order_code",
    "load_routing_steps",
    "derive_operation_work_orders",
]
