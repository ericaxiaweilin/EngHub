"""
流程知识库服务（职位工作流 + 工单全生命周期 + RACI 责任矩阵）

为 chatbot 提供结构化的流程知识查询能力：
- WORK_ORDER_FLOW：工单全生命周期 8 阶段（阶段/状态/负责角色/动作/卡点处理）
- POSITION_SOPS：6 个核心职位的标准作业流程（日常流/职责/升级路径/关联系统工具）
- RACI_MATRIX：工单流阶段 × 角色责任矩阵（R执行/A负责/C咨询/I知会）

设计原则（延续「确定性业务底座」）：
- 知识为结构化静态数据，查询结果 100% 确定，不依赖模型记忆。
- 后续可迁移至数据库码表，由管理员在系统设置页自定义维护。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


# ==================== 工单全生命周期（8 阶段） ====================

WORK_ORDER_FLOW: List[Dict[str, Any]] = [
    {
        "stage": "创建",
        "status": "pending",
        "role": "PMC计划员",
        "actions": "根据客户订单/需求建立生产工单（产品、数量、交期），工单编码体系化：主单→工序子单",
        "blockpoint": "编码不规范/信息缺失 → 驳回补全；主单派生子单（如 S20260720 → S20260720-zs01）",
    },
    {
        "stage": "审批/下达",
        "status": "released",
        "role": "生产主管",
        "actions": "审核物料/产能/人力是否齐备，确认后下达工单至车间",
        "blockpoint": "超时未下达 → 系统提醒主管；物料不足 → 触发MRP采购建议",
    },
    {
        "stage": "派工",
        "status": "dispatched",
        "role": "生产主管/组长",
        "actions": "将工单分配至具体工位与操作员，确认人员技能匹配",
        "blockpoint": "技能不匹配 → 查询技能矩阵换人；工位负荷满 → 调度排产",
    },
    {
        "stage": "执行",
        "status": "in_progress",
        "role": "操作员",
        "actions": "按工艺路线逐工序生产，遵守SOP作业标准",
        "blockpoint": "设备故障 → 安灯呼叫设备工程师；物料异常 → 物料呼叫；工艺疑问 → 呼叫工艺工程师",
    },
    {
        "stage": "报工",
        "status": "reporting",
        "role": "操作员/组长",
        "actions": "提交本工序良品数/不良数/报废数，记录工时与异常",
        "blockpoint": "漏报/晚报 → 数据采集提醒；数量异常(良品>投入) → 系统校验拦截",
    },
    {
        "stage": "质检",
        "status": "inspection",
        "role": "品检员",
        "actions": "首件检验(FAI)、过程巡检(2h频次)、终检，判定批次合格/不合格",
        "blockpoint": "不良超阈值 → 开NCR不合格品报告 → OCAP纠正预防跟踪",
    },
    {
        "stage": "完工",
        "status": "completed",
        "role": "操作员+品检员",
        "actions": "末道工序完成且终检合格，工单状态转完工",
        "blockpoint": "部分完工(尾数不足) → 拆单处理，尾数单独跟踪",
    },
    {
        "stage": "关闭/入库",
        "status": "closed",
        "role": "仓管员/PMC计划员",
        "actions": "成品入库（核对数量/批次）、工单归档、成本结算",
        "blockpoint": "入库数与完工数差异 → 盘点差异处理；超期未入库 → 提醒仓管",
    },
]


# ==================== 职位标准作业流程（6 个核心职位） ====================

POSITION_SOPS: Dict[str, Dict[str, Any]] = {
    "operator": {
        "title": "操作员",
        "aliases": ["操作员", "作业员", "一线员工", "产线工人", "操作工"],
        "duties": "按工艺标准执行生产作业，如实报工，及时上报异常",
        "daily_flow": [
            {"step": 1, "task": "班前确认", "detail": "确认当日工单、物料齐套、设备点检正常"},
            {"step": 2, "task": "领单开工", "detail": "从派工列表领取工单，扫码/点击开工"},
            {"step": 3, "task": "逐工序作业", "detail": "按工艺路线SOP执行，首件送检确认"},
            {"step": 4, "task": "过程报工", "detail": "每完成一批提交良品/不良数量"},
            {"step": 5, "task": "异常上报", "detail": "设备/物料/品质异常 → 安灯呼叫对应支援"},
            {"step": 6, "task": "交接班", "detail": "记录在制品状态、异常遗留事项，交接下一班"},
        ],
        "escalation": "设备故障→设备工程师 | 物料缺料→仓管/组长 | 品质异常→品检员 | 工艺问题→工艺工程师",
        "related_tools": "工单列表、报工、安灯呼叫、工艺路线查询",
    },
    "ipqc": {
        "title": "品检员(IPQC)",
        "aliases": ["品检员", "IPQC", "质检员", "品质检验", "QC", "品管员"],
        "duties": "执行首检/巡检/终检，判定产品合格性，开立不良品报告并跟踪闭环",
        "daily_flow": [
            {"step": 1, "task": "首件检验(FAI)", "detail": "开机/换线/换料时，对首件按检验标准全尺寸检测"},
            {"step": 2, "task": "过程巡检", "detail": "每2小时按巡检路线抽检各工位，记录SPC数据"},
            {"step": 3, "task": "终检", "detail": "工单完工前对末批产品做最终检验判定"},
            {"step": 4, "task": "不良品处理", "detail": "发现不良 → 开NCR单 → 标识隔离 → 判定处置(返工/报废/特采)"},
            {"step": 5, "task": "OCAP跟踪", "detail": "对重复性不良开纠正预防措施单，跟踪责任部门闭环"},
            {"step": 6, "task": "检验报告", "detail": "汇总当日检验数据，输出日报(良率/不良TOP/趋势)"},
        ],
        "escalation": "批量不良→品质主管+停线 | 争议判定→品质主管仲裁 | 供应商来料不良→IQC+采购",
        "related_tools": "检验单、不良品查询、SPC图表、NCR流程",
    },
    "equipment_engineer": {
        "title": "设备工程师",
        "aliases": ["设备工程师", "设备维修", "机修", "设备技术员", "维修工程师"],
        "duties": "保障设备稼动，执行点检/维修/保养，管理备件，分析设备效率",
        "daily_flow": [
            {"step": 1, "task": "日常点检", "detail": "按点检表对责任区域设备做开机前检查(润滑/气压/安全装置)"},
            {"step": 2, "task": "故障接报", "detail": "收到安灯设备故障呼叫，确认故障现象与工位"},
            {"step": 3, "task": "维修执行", "detail": "到场诊断、维修、试机确认，记录故障原因与维修工时"},
            {"step": 4, "task": "保养计划(PM)", "detail": "按周期执行预防性保养(日保/周保/月保)，更新保养记录"},
            {"step": 5, "task": "备件管理", "detail": "消耗备件登记、库存不足时提出采购申请"},
            {"step": 6, "task": "稼动率分析", "detail": "汇总设备OEE(稼动率/性能/良率)，输出改善建议"},
        ],
        "escalation": "重大故障(停机>2h)→设备主管+生产主管 | 需外协维修→设备主管审批 | 安全隐患→立即停线+上报",
        "related_tools": "设备状态查询、维修工单、保养计划、OEE看板",
    },
    "pmc_planner": {
        "title": "PMC计划员",
        "aliases": ["PMC", "计划员", "PMC计划员", "生管", "物控", "生产计划员"],
        "duties": "统筹订单评审、物料需求与产能排产，建工单并跟催进度，回复交期",
        "daily_flow": [
            {"step": 1, "task": "订单评审", "detail": "接收客户订单，评审交期可行性(产能/物料/人力)"},
            {"step": 2, "task": "MRP运算", "detail": "运行物料需求计划，生成采购建议与到料需求日"},
            {"step": 3, "task": "排产计划", "detail": "按产能与优先级编排周/日生产计划"},
            {"step": 4, "task": "建工单/下达", "detail": "将计划转为生产工单，提交主管审批后下达车间"},
            {"step": 5, "task": "进度跟催", "detail": "监控工单进度，滞后工单跟催车间；物料延迟跟催采购"},
            {"step": 6, "task": "交期回复", "detail": "汇总订单执行情况，回复业务/客户交期承诺"},
        ],
        "escalation": "产能不足→生产主管协调加班/外协 | 物料断供→采购主管+业务变更交期 | 插单冲突→PMC主管仲裁优先级",
        "related_tools": "MRP运算、工单创建/下达、生产统计、库存查询",
    },
    "production_supervisor": {
        "title": "生产主管",
        "aliases": ["生产主管", "车间主管", "制造主管", "生产经理", "课长"],
        "duties": "审批下达工单、派工调度、监控生产指标、异常决策、团队管理",
        "daily_flow": [
            {"step": 1, "task": "审批工单", "detail": "审核PMC提交的工单(资源齐备性)，确认下达"},
            {"step": 2, "task": "派工调度", "detail": "将工单分配至工位/人员，平衡各线负荷"},
            {"step": 3, "task": "看板监控", "detail": "实时关注产量达成率、良率、设备稼动率、工单进度"},
            {"step": 4, "task": "异常决策", "detail": "处理升级异常(停线/批量不良/人员不足)，协调资源"},
            {"step": 5, "task": "日度复盘", "detail": "汇总当日KPI，分析未达标项，布置次日重点"},
        ],
        "escalation": "重大品质事故→品质经理+总经理 | 交期风险→PMC主管+业务 | 安全事故→EHS+厂长",
        "related_tools": "生产统计、工单查询、设备状态、预警简报、日度复盘工作流",
    },
    "warehouse_keeper": {
        "title": "仓管员",
        "aliases": ["仓管员", "仓管", "仓库管理员", "物料员", "库管"],
        "duties": "管理物料/成品收发存，确保账实一致，执行先进先出与安全库存管控",
        "daily_flow": [
            {"step": 1, "task": "收料入库", "detail": "供应商来料核对送货单/检验报告，合格品入库上架"},
            {"step": 2, "task": "发料", "detail": "按工单BOM定额发料至产线，扫码扣账"},
            {"step": 3, "task": "库存盘点", "detail": "日盘(动碰盘)+月盘(全盘)，差异查明原因并调整"},
            {"step": 4, "task": "安全库存预警", "detail": "监控库存水位，低于安全库存触发补货申请"},
            {"step": 5, "task": "先进先出管控", "detail": "按批次日期顺序发料，防止物料过期呆滞"},
        ],
        "escalation": "账实差异>阈值→仓管主管+财务 | 来料不合格→IQC退货 | 呆滞料→PMC+采购处理",
        "related_tools": "库存查询、出入库记录、盘点、安全库存预警",
    },
}


# ==================== RACI 责任矩阵（工单流阶段 × 角色） ====================
# R=执行(Responsible) A=负责(Accountable) C=咨询(Consulted) I=知会(Informed)

RACI_MATRIX: Dict[str, Dict[str, str]] = {
    "创建": {"PMC计划员": "R/A", "生产主管": "C", "仓管员": "C", "品检员": "I", "操作员": "I", "设备工程师": "I"},
    "审批/下达": {"生产主管": "R/A", "PMC计划员": "C", "仓管员": "C", "品检员": "I", "操作员": "I", "设备工程师": "I"},
    "派工": {"生产主管": "A", "操作员": "R", "PMC计划员": "C", "品检员": "I", "仓管员": "I", "设备工程师": "I"},
    "执行": {"操作员": "R", "生产主管": "A", "设备工程师": "C", "品检员": "C", "仓管员": "C", "PMC计划员": "I"},
    "报工": {"操作员": "R", "生产主管": "A", "PMC计划员": "I", "品检员": "I", "仓管员": "I", "设备工程师": "I"},
    "质检": {"品检员": "R/A", "操作员": "C", "生产主管": "I", "PMC计划员": "I", "仓管员": "I", "设备工程师": "I"},
    "完工": {"操作员": "R", "品检员": "A", "生产主管": "I", "PMC计划员": "I", "仓管员": "I", "设备工程师": "I"},
    "关闭/入库": {"仓管员": "R", "PMC计划员": "A", "品检员": "C", "生产主管": "I", "操作员": "I", "设备工程师": "I"},
}


# ==================== 统一查询入口 ====================

def _match_position(keyword: str) -> Optional[Dict[str, Any]]:
    """按关键词模糊匹配职位（别名/标题包含即命中）。"""
    if not keyword:
        return None
    for sop in POSITION_SOPS.values():
        if keyword in sop["title"] or any(keyword in a for a in sop["aliases"]):
            return sop
    return None


def _match_stage(keyword: str) -> Optional[Dict[str, Any]]:
    """按关键词模糊匹配工单流阶段。"""
    if not keyword:
        return None
    for stage in WORK_ORDER_FLOW:
        if keyword in stage["stage"] or keyword in stage["status"] or keyword in stage["actions"]:
            return stage
    return None


def query_knowledge(topic: str = "", keyword: str = "") -> Dict[str, Any]:
    """流程知识统一查询入口。

    topic 取值：
    - "work_order_flow"：返回工单全生命周期（keyword 可按阶段过滤）
    - "position_sop"：返回职位SOP（keyword 匹配职位名）
    - "who_handles"：RACI 责任查询（keyword 匹配阶段名 → 返回各角色责任）
    - 空/其他：全文模糊匹配（自动判断是阶段还是职位）
    """
    topic = (topic or "").strip()
    keyword = (keyword or "").strip()

    # ---- 工单全生命周期 ----
    if topic == "work_order_flow":
        if keyword:
            stage = _match_stage(keyword)
            if stage:
                return {"type": "work_order_stage", "title": f"工单流程 - {stage['stage']}阶段", "stages": [stage]}
            return {"type": "work_order_flow", "title": "工单全生命周期流程", "stages": WORK_ORDER_FLOW,
                    "note": f"未找到「{keyword}」对应阶段，已返回完整流程"}
        return {"type": "work_order_flow", "title": "工单全生命周期流程", "stages": WORK_ORDER_FLOW}

    # ---- 职位 SOP ----
    if topic == "position_sop":
        sop = _match_position(keyword)
        if sop:
            return {"type": "position_sop", "title": f"{sop['title']} 标准作业流程", "position": sop}
        # 未指定具体职位 → 返回全部职位概览
        overview = [
            {"position": s["title"], "duties": s["duties"], "steps": len(s["daily_flow"])}
            for s in POSITION_SOPS.values()
        ]
        return {"type": "position_overview", "title": "全部职位工作流概览", "positions": overview,
                "note": "可追问具体职位（如：品检员的日常工作流程）"}

    # ---- RACI 责任归属 ----
    if topic == "who_handles":
        stage = _match_stage(keyword) if keyword else None
        if stage:
            raci = RACI_MATRIX.get(stage["stage"], {})
            rows = [
                {"stage": stage["stage"], "role": role, "responsibility": resp,
                 "meaning": {"R": "执行", "A": "负责", "C": "咨询", "I": "知会"}.get(resp.split("/")[0], resp)}
                for role, resp in raci.items()
            ]
            # 按责任权重排序：A > R > C > I
            order = {"R/A": 0, "A": 1, "R": 2, "C": 3, "I": 4}
            rows.sort(key=lambda r: order.get(r["responsibility"], 9))
            primary = rows[0] if rows else None
            return {
                "type": "who_handles",
                "title": f"「{stage['stage']}」环节责任归属",
                "stage": stage,
                "raci": rows,
                "answer": f"「{stage['stage']}」环节：{primary['role']}（{primary['responsibility']} {primary['meaning']}）" if primary else "",
            }
        # 未匹配到阶段 → 返回全部阶段的主要负责人
        rows = []
        for st in WORK_ORDER_FLOW:
            raci = RACI_MATRIX.get(st["stage"], {})
            primary_role = next((r for r, v in raci.items() if "A" in v), st["role"])
            rows.append({"stage": st["stage"], "status": st["status"], "primary_role": primary_role, "blockpoint": st["blockpoint"]})
        return {"type": "who_handles_all", "title": "工单各环节主要负责人", "stages": rows}

    # ---- 无 topic：全文模糊匹配 ----
    # 先尝试匹配职位
    sop = _match_position(keyword)
    if sop:
        return {"type": "position_sop", "title": f"{sop['title']} 标准作业流程", "position": sop}
    # 再尝试匹配阶段
    stage = _match_stage(keyword)
    if stage:
        raci = RACI_MATRIX.get(stage["stage"], {})
        return {"type": "work_order_stage", "title": f"工单流程 - {stage['stage']}阶段", "stages": [stage], "raci": raci}
    # 兜底：返回完整知识目录
    return {
        "type": "knowledge_index",
        "title": "流程知识目录",
        "work_order_flow_stages": [s["stage"] for s in WORK_ORDER_FLOW],
        "positions": [s["title"] for s in POSITION_SOPS.values()],
        "note": "可问：工单流程是什么 / 品检员的日常工作流程 / 工单卡在下达环节该找谁",
    }


__all__ = ["WORK_ORDER_FLOW", "POSITION_SOPS", "RACI_MATRIX", "query_knowledge"]
