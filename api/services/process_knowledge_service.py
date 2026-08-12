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
            {
                "step": 1,
                "task": "销售订单评审（Gate 1）",
                "owner": "PMC计划员",
                "detail": "接收销售/业务提交的订单，核对需求、RDD、BOM/图纸版本、物料和产能，做出通过或不通过的明确闸口结论。",
                "inputs": ["销售订单/预测版本", "客户与订单优先级", "产品型号与需求数量", "RDD/客户收货节点", "BOM/图纸/工艺路线版本", "当前库存/在途/开放PO", "APS产能与越南工作日历"],
                "judgement_criteria": ["订单字段与版本完整", "RDD口径明确且可倒推", "BOM/工艺版本有效", "物料与产能证据可追溯", "预计ETA不晚于RDD；否则只能条件承诺或阻塞"],
                "outputs": ["通过：锁定需求量、RDD和有效版本并进入MRP", "不通过：退回补资料或进入交期风险评审", "风险责任人与补证据期限"],
                "deliverables": ["订单评审记录", "PMC工作矩阵", "MPS可行性初判", "风险/假设清单"],
                "next_focus": ["通过：进入MRP运算", "条件放行：先跟踪缺口和责任人", "阻塞：不得直接承诺客户交期"],
                "blockers": ["缺少RDD", "BOM或工艺版本未冻结", "VN工作日历未配置", "库存/PO/产能数据缺失"],
                "work_matrix": ["需求量", "RDD", "UHN（若企业已定义）", "可加工时间", "库存齐套率", "含PO预计齐套率", "预计ETA"],
                "systems": ["销售订单", "PMC工作矩阵", "APS日历", "BOM/工艺"],
                "pass_condition": "通过：订单/RDD/版本齐全，物料与产能可行，预计ETA≤RDD",
                "exception_paths": [
                    {"condition": "不通过：订单/RDD/BOM/图纸/工艺版本缺失", "action": "退回销售/RD补齐资料", "owner": "销售/RD", "outputs": ["补齐后的订单包与版本确认"], "deliverables": ["退回原因", "补资料责任人", "补齐期限"], "resume_condition": "资料补齐并重新提交订单评审", "return_to": "current"},
                    {"condition": "不通过：ETA晚于RDD或产能不可行", "action": "发起跨部门交期风险评审", "owner": "PMC主管/生产主管/销售", "inputs": ["缺料清单", "瓶颈负荷", "原RDD"], "outputs": ["加班/外协/分批/改期方案"], "deliverables": ["风险评审结论", "新承诺日期或资源方案"], "resume_condition": "方案获批且更新订单承诺后重新评审", "return_to": "current"},
                ],
            },
            {
                "step": 2,
                "task": "MRP运算与齐套判断",
                "owner": "PMC物控",
                "detail": "按有效需求、BOM、库存和供应证据计算净需求，不把未确认在途当作已齐套。",
                "inputs": ["已评审需求", "有效BOM", "合格可用库存", "安全库存", "开放PO/在途数量与ETA", "损耗率/直通率假设"],
                "judgement_criteria": ["净需求=需求量×单位用量+安全库存-合格可用库存-可信供应", "每项缺口都有数量、需求日和责任人", "PO/在途只有在ETA与IQC可满足时才计入条件齐套", "替代料必须完成工程与品质验证"],
                "outputs": ["物料齐套率", "缺料清单与需求日", "采购/调拨/替代建议", "条件齐套结论"],
                "deliverables": ["MRP运算结果", "缺料跟催表", "到料计划", "替代料验证任务"],
                "next_focus": ["齐套：进入产能与MPS排程", "不齐套：锁定PO、ETA和升级节点"],
                "blockers": ["BOM用量缺失", "库存状态不合格", "PO无可靠ETA", "替代料未验证"],
                "matrix_fields": ["required_qty", "qualified_available_qty", "in_transit_qty", "on_order_qty", "shortage_qty", "supplier_lead_days"],
                "systems": ["MRP", "库存", "采购订单", "IQC"],
                "pass_condition": "通过：库存齐套，或已确认PO/在途可在需求日前完成IQC放行",
                "exception_paths": [
                    {"condition": "不通过：关键料缺口且无可靠ETA", "action": "升级采购主管并评估改期", "owner": "采购主管/PMC主管", "outputs": ["供应恢复日期或改期建议"], "deliverables": ["缺料升级记录", "责任人与恢复ETA"], "resume_condition": "供应ETA覆盖需求日后重新齐套判断", "return_to": "current"},
                    {"condition": "不通过但存在可替代料", "action": "发起替代料验证", "owner": "RD/品质/采购", "outputs": ["批准/拒绝替代料结论"], "deliverables": ["替代料验证与批准记录"], "resume_condition": "替代料获批并有合格库存后重新齐套判断", "return_to": "current"},
                ],
            },
            {
                "step": 3,
                "task": "产能校核与MPS排程",
                "owner": "PMC计划员",
                "detail": "把需求工时与瓶颈工位可加工时间进行CRP校核，形成有资源约束的周/日计划。",
                "inputs": ["齐套结论", "需求投入量", "工艺路线/标准工时", "班次与设备日历", "已占用产能", "订单优先级"],
                "judgement_criteria": ["瓶颈工位需求工时≤可加工时间", "共享线体按实际占用比例折减", "良率、换线、保养和法定假期已纳入", "MPS完工节点支持RDD倒推"],
                "outputs": ["MPS草案", "周计划/日计划", "瓶颈负荷与冲突订单", "预计生产完成时间"],
                "deliverables": ["MPS版本", "产能负荷表", "排程冲突清单", "资源调整建议"],
                "next_focus": ["无冲突：冻结本版MPS并准备建单", "有冲突：先完成优先级仲裁和资源调整"],
                "blockers": ["标准工时/UHN口径缺失", "设备日历缺失", "线体被其他订单抢占", "需求工时超过瓶颈可用时间"],
                "matrix_fields": ["required_production_qty", "required_hours", "available_machining_hours", "utilization_pct", "production_complete_at"],
                "systems": ["APS/CRP", "MPS", "设备日历", "技能矩阵"],
                "pass_condition": "瓶颈产能可行且MPS完工节点满足RDD",
                "exception_paths": [
                    {"condition": "瓶颈工位超载", "action": "比较加班、换线、外协与改期方案", "owner": "生产主管/PMC主管", "deliverables": ["获批的资源调整方案"], "return_to": "current"},
                    {"condition": "插单造成计划冲突", "action": "执行优先级仲裁并重排受影响订单", "owner": "PMC主管/业务", "deliverables": ["插单影响清单与新版MPS"], "return_to": "current"},
                ],
            },
            {
                "step": 4,
                "task": "建工单与释放闸口",
                "owner": "PMC计划员/生产主管",
                "detail": "将已确认MPS转换为主工单和工序工单；只有资源、版本与审批全部满足才能释放到车间。",
                "inputs": ["已冻结MPS", "产品/BOM/工艺版本", "主工单与工序工单结构", "物料齐套结论", "产能/人员/设备确认", "审批记录"],
                "judgement_criteria": ["工单数量与MPS一致", "主单与工序子单编码和数量闭环", "BOM/工艺版本已冻结", "物料和产能满足释放门槛", "创建人与审批/下达人职责分离"],
                "outputs": ["主工单及工序工单", "状态：pending→released", "计划开始/完成时间", "派工前置条件"],
                "deliverables": ["工单包", "版本快照", "释放审批记录", "未释放原因清单"],
                "next_focus": ["已释放：通知生产主管派工", "未释放：按缺口责任人跟催，不允许状态假闭环"],
                "blockers": ["主/子工单数量不一致", "版本未冻结", "物料或产能未达闸口", "审批缺失"],
                "systems": ["MPS", "工单中心", "审批流", "派工看板"],
                "pass_condition": "工单数据闭环且主管完成释放审批",
                "exception_paths": [
                    {"condition": "释放闸口未满足", "action": "保持pending并生成未释放原因", "owner": "PMC计划员", "deliverables": ["未释放原因与责任人清单"], "return_to": "current"},
                    {"condition": "审批驳回", "action": "修订MPS/工单后重新提交", "owner": "PMC计划员", "deliverables": ["修订记录"], "return_to": "current"},
                ],
            },
            {
                "step": 5,
                "task": "执行监控与异常闭环",
                "owner": "PMC计划员",
                "detail": "按工单、工序和物料节点监控计划达成，不只看主工单状态；偏差必须形成责任人与恢复时间。",
                "inputs": ["已释放工单", "派工/开工状态", "工序报工", "良品/不良/报废", "物料到货与IQC", "设备停机与安灯"],
                "judgement_criteria": ["主工单与工序状态一致", "累计投入/良品/不良数量守恒", "计划与实际偏差在阈值内", "关键异常有责任人、措施和恢复ETA", "预计完工持续满足交付节点"],
                "outputs": ["工单进度与达成率", "延期预测", "异常行动队列", "新版预计完工/FG Ready"],
                "deliverables": ["PMC日报", "缺料/停机/品质异常跟催表", "恢复计划", "升级记录"],
                "next_focus": ["无偏差：持续按节奏监控", "有偏差：先保关键路径，再更新交付预测"],
                "blockers": ["工序未下达但主单显示生产中", "漏报/晚报", "物料延迟", "设备停机", "批量不良"],
                "systems": ["生产看板", "报工", "安灯", "质量/NCR", "采购跟催"],
                "pass_condition": "生产完工且关键异常闭环，FG Ready时间可确认",
                "exception_paths": [
                    {"condition": "进度偏差超过阈值", "action": "启动恢复计划并重算ETA", "owner": "生产主管/PMC", "deliverables": ["恢复计划与新版ETA"], "return_to": "current"},
                    {"condition": "品质或设备异常影响关键路径", "action": "升级责任部门并冻结不可靠承诺", "owner": "品质/设备/生产主管", "deliverables": ["处置结论与恢复时间"], "return_to": "current"},
                ],
            },
            {
                "step": 6,
                "task": "交付确认与闭环",
                "owner": "PMC计划员",
                "detail": "基于完工、终检、入库、装柜和运输证据回复交期，并关闭计划版本与遗留事项。",
                "inputs": ["完工与终检结果", "成品入库数量", "FG Ready时间", "装柜/报关计划", "运输方式与ETA", "未结异常"],
                "judgement_criteria": ["完工数、良品数、入库数数量闭环", "终检与放行状态合格", "装柜/海关/运输缓冲已计入", "客户承诺日期有证据来源", "未结风险已明确披露"],
                "outputs": ["可承诺交付日期", "出货计划", "订单执行结论", "未结事项与责任人"],
                "deliverables": ["交期回复记录", "出货/装柜计划", "订单关闭检查表", "复盘改进项"],
                "next_focus": ["按承诺节点持续跟踪至签收", "偏差时先通知业务并给出证据化新ETA"],
                "blockers": ["终检未放行", "入库数与完工数不一致", "装柜/海关状态未知", "运输资源未确认"],
                "systems": ["完工入库", "OQC", "出货计划", "订单中心"],
                "pass_condition": "质量、数量、出货和ETA证据全部闭环",
                "exception_paths": [
                    {"condition": "FG Ready或运输节点晚于承诺", "action": "通知业务并审批新ETA/运输方案", "owner": "PMC主管/业务", "deliverables": ["客户沟通记录与新承诺日期"], "return_to": "current"},
                ],
            },
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


# ==================== 独立业务流程注册表 ====================
# 岗位端到端流程与独立子流程必须使用不同注册键。模型只负责识别对象，
# 流程引擎只按注册定义出图；未知对象不得回退到 PMC 或最近审批实例。

BUSINESS_WORKFLOW_REGISTRY: Dict[str, Dict[str, Any]] = {
    "process:alternate_material_validation": {
        "title": "替代料验证与受控放行流程图",
        "aliases": ["发起替代料验证", "替代料验证", "代用料验证", "替代物料验证", "alternative material validation"],
        "description": "从缺料/变更需求提出候选替代料，经过技术等效、供应商资料、样品试验、批准或拒绝、主数据更新，最终受控放行。",
        "role": "RD/品质/采购",
        "start_title": "替代需求与候选料输入",
        "start_summary": "提交原物料、候选替代料、使用场景、需求日期和缺料/变更证据。",
        "end_title": "受控放行或拒绝关闭",
        "end_summary": "批准时完成版本与库存状态更新后受控放行；拒绝时保留结论并关闭候选。",
        "metadata": {
            "workflow_domain": "物料变更/工程验证",
            "process_scope": "standalone",
            "parent_contexts": ["MRP缺料处理", "采购降本", "供应中断", "工程变更"],
            "related_parties": ["需求提出方", "PMC", "采购", "供应商", "RD/工程", "品质/SQE/IQC", "生产", "仓库", "文控/主数据"],
            "related_tools": ["BOM/PLM", "规格书/图纸", "供应商资料", "检验/试验记录", "ECN/变更单", "ERP物料主数据", "AVL", "库存状态"],
            "forbid_parent_workflow_fallback": True,
        },
        "steps": [
            {
                "step": 1,
                "task": "提交替代料验证申请",
                "owner": "需求提出方/PMC/采购",
                "detail": "说明替代原因、原物料与候选料、适用产品/订单、需求日期及临时或永久替代范围。",
                "inputs": ["原物料编码与版本", "候选替代料编码/供应商", "缺料或降本证据", "适用产品/BOM/订单", "需求日期", "临时/永久替代类型"],
                "judgement_criteria": ["原料与候选料唯一可识别", "替代原因和范围明确", "需求日期与申请人完整"],
                "outputs": ["替代料验证申请", "验证范围与优先级", "责任人和目标完成日"],
                "deliverables": ["替代料申请单", "原料-候选料对照表"],
                "systems": ["替代料申请", "BOM/ERP", "缺料清单"],
                "pass_condition": "申请资料完整且候选料、适用范围、目标日期明确",
                "exception_paths": [
                    {"condition": "申请缺少原料/候选料/适用范围或需求日期", "action": "退回提出方补齐申请", "owner": "需求提出方", "deliverables": ["退回原因与补齐清单"], "resume_condition": "资料补齐后重新提交", "return_to": "current"},
                ],
            },
            {
                "step": 2,
                "task": "技术等效性预评审",
                "owner": "RD/工程",
                "detail": "对照规格、尺寸、材料、性能、接口、法规和工艺适配性，判定是否值得进入样品验证。",
                "inputs": ["原料与候选料规格书", "图纸/材料声明", "关键特性CTQ", "法规与客户特殊要求", "现行工艺条件"],
                "judgement_criteria": ["关键规格满足或有可验证差异", "接口/尺寸/材料兼容", "法规与客户限制允许", "风险可通过试验覆盖"],
                "outputs": ["技术差异清单", "预评审通过/拒绝结论", "需要验证的风险项目"],
                "deliverables": ["技术等效性评审记录", "风险等级"],
                "systems": ["PLM/图纸", "规格书", "法规资料库"],
                "pass_condition": "技术预评审通过，差异与验证风险已量化",
                "exception_paths": [
                    {"condition": "存在不可接受的规格/接口/法规差异", "action": "拒绝该候选并要求重新选料", "owner": "RD/工程", "outputs": ["拒绝原因"], "deliverables": ["技术拒绝记录"], "resume_condition": "提交新候选料后重新申请", "return_to": 0},
                    {"condition": "资料不足以判断技术等效性", "action": "要求供应商补规格和声明", "owner": "采购/供应商", "deliverables": ["资料缺口清单"], "resume_condition": "资料齐全后重新预评审", "return_to": "current"},
                ],
            },
            {
                "step": 3,
                "task": "供应商资料与样品齐备",
                "owner": "采购/SQE/供应商",
                "detail": "收集合格供应商、材质/环保/可靠性资料、批次追溯信息，并取得可验证样品。",
                "inputs": ["供应商资质与AVL状态", "COC/材质证明", "RoHS/REACH等声明", "样品数量与批次", "报价与供应LT"],
                "judgement_criteria": ["供应商准入状态有效或已启动临时准入", "文件版本有效", "样品数量和批次满足验证计划", "样品可追溯"],
                "outputs": ["供应商资料包", "可追溯样品", "供应能力与LT结论"],
                "deliverables": ["资料检查表", "样品接收记录"],
                "systems": ["SRM/AVL", "供应商文件", "样品台账"],
                "pass_condition": "供应商资料有效且样品数量、批次、追溯信息齐备",
                "exception_paths": [
                    {"condition": "供应商未准入、文件过期或样品不足", "action": "暂停验证并跟催供应商补齐", "owner": "采购/SQE", "deliverables": ["缺口与承诺日期"], "resume_condition": "准入/文件/样品全部齐备", "return_to": "current"},
                ],
            },
            {
                "step": 4,
                "task": "制定并批准验证计划",
                "owner": "RD/品质/生产",
                "detail": "根据技术差异和风险等级确定尺寸、功能、可靠性、试产及检验项目、样本量和接受标准。",
                "inputs": ["技术差异清单", "风险等级", "客户/法规要求", "样品与设备资源", "历史不良模式"],
                "judgement_criteria": ["每项风险都有对应试验", "样本量和接受标准明确", "责任人、设备和完成日期可执行", "需要客户批准时已列入"],
                "outputs": ["验证项目与样本量", "接受/拒绝标准", "试验责任人与排期"],
                "deliverables": ["获批验证计划", "试产/测试排程"],
                "systems": ["验证计划", "实验室/设备日历", "试产计划"],
                "pass_condition": "验证计划覆盖全部风险并获RD、品质及相关方确认",
                "exception_paths": [
                    {"condition": "风险未覆盖、标准不清或验证资源不可用", "action": "修订验证计划与资源安排", "owner": "RD/品质/生产", "deliverables": ["修订版验证计划"], "resume_condition": "计划获批且资源锁定", "return_to": "current"},
                ],
            },
            {
                "step": 5,
                "task": "执行样品试验与试产验证",
                "owner": "RD/品质/生产",
                "detail": "按获批计划执行来料、尺寸、功能、可靠性和必要的试产验证，完整记录原始数据与异常。",
                "inputs": ["获批验证计划", "可追溯样品", "检验/试验设备", "试产工单与工艺参数"],
                "judgement_criteria": ["试验按计划和有效方法执行", "原始数据可追溯", "所有接受标准逐项判定", "异常有隔离与调查记录"],
                "outputs": ["逐项试验结果", "试产良率与异常", "通过/失败建议"],
                "deliverables": ["验证报告", "原始数据", "试产记录", "不符合项清单"],
                "systems": ["检验/实验室", "试产工单", "NCR/异常记录"],
                "pass_condition": "全部关键项目满足接受标准且试产风险可接受",
                "exception_paths": [
                    {"condition": "试验失败但原因可纠正并允许复测", "action": "隔离样品、完成原因分析后申请复测", "owner": "RD/品质/供应商", "deliverables": ["原因分析与复测申请"], "resume_condition": "纠正措施完成且复测计划获批", "return_to": "current"},
                    {"condition": "关键项目失败或风险不可接受", "action": "判定候选料验证失败并重新选料", "owner": "RD/品质", "deliverables": ["失败结论与禁用原因"], "resume_condition": "提交新候选料后重新申请", "return_to": 0},
                ],
            },
            {
                "step": 6,
                "task": "验证结论评审与批准",
                "owner": "RD/品质/采购/需求部门",
                "detail": "汇总技术、质量、供应和成本证据，批准永久替代、限时/限批替代，或拒绝候选。",
                "inputs": ["验证报告与原始数据", "试产结果", "供应能力/成本/LT", "未关闭风险", "客户批准要求"],
                "judgement_criteria": ["关键试验全部通过", "残余风险有控制措施", "替代范围和有效期明确", "所需客户/主管批准完成"],
                "outputs": ["批准/条件批准/拒绝结论", "适用产品与订单范围", "有效期/批次与控制条件"],
                "deliverables": ["签核后的替代料验证报告", "风险接受记录"],
                "systems": ["工程变更/ECN", "电子签核", "客户批准记录"],
                "pass_condition": "替代结论获相关责任方批准，范围、期限和控制条件明确",
                "exception_paths": [
                    {"condition": "证据不足、残余风险未接受或批准被驳回", "action": "退回补试验、补批准或重新选料", "owner": "RD/品质/申请方", "deliverables": ["驳回原因与补充行动"], "resume_condition": "证据与批准补齐后重新评审", "return_to": "current"},
                ],
            },
            {
                "step": 7,
                "task": "主数据更新与受控放行",
                "owner": "文控/工程/PMC/仓库/IQC",
                "detail": "按批准范围更新BOM、AVL、检验标准和ERP状态，区分临时/永久替代并通知执行部门。",
                "inputs": ["已批准替代结论", "适用范围/有效期/批次", "BOM与AVL变更内容", "检验与仓储控制要求"],
                "judgement_criteria": ["BOM/AVL/ERP版本一致", "临时替代有效期和批次受控", "IQC与仓库状态已更新", "相关订单与部门已通知"],
                "outputs": ["可用替代料主数据", "更新后的BOM/AVL/检验标准", "受控库存与订单放行状态"],
                "deliverables": ["ECN/版本记录", "ERP变更日志", "放行通知", "到期复审任务"],
                "systems": ["BOM/PLM", "ERP物料主数据", "AVL", "IQC检验标准", "库存状态"],
                "pass_condition": "所有主数据和控制点同步完成，替代料按批准范围可追溯放行",
                "exception_paths": [
                    {"condition": "BOM/AVL/ERP/检验标准未同步或库存状态不一致", "action": "保持冻结并完成主数据纠正", "owner": "文控/工程/IT主数据/IQC", "deliverables": ["未放行清单与纠正记录"], "resume_condition": "系统版本一致且控制点复核通过", "return_to": "current"},
                ],
            },
        ],
    },
    "process:work_order_lifecycle": {
        "title": "生产工单全生命周期流程图",
        "aliases": ["工单流程图", "工单全生命周期", "生产工单流程", "work order lifecycle"],
        "description": "生产工单从创建、下达、派工、执行、报工、质检、完工到关闭入库的完整流转。",
        "role": "生产运营团队",
        "start_title": "订单/计划需求输入",
        "end_title": "工单关闭与入库归档",
        "metadata": {"workflow_domain": "生产工单", "process_scope": "end_to_end", "related_parties": ["PMC", "生产主管", "班组/操作员", "品检", "仓库", "设备/工程"]},
        "steps": [
            {
                "step": index + 1,
                "task": stage["stage"],
                "owner": stage["role"],
                "detail": stage["actions"],
                "inputs": ["上一阶段已确认状态", "工单主数据与版本"],
                "judgement_criteria": [f"满足进入{stage['stage']}阶段的状态和责任要求"],
                "outputs": [f"工单状态：{stage['status']}", f"{stage['stage']}阶段执行记录"],
                "deliverables": [f"{stage['stage']}留痕"],
                "pass_condition": f"{stage['stage']}完成并满足下一阶段门槛",
                "exception_paths": [{"condition": stage["blockpoint"], "action": "按卡点责任链处理并补齐证据", "owner": stage["role"], "resume_condition": f"卡点关闭后重新确认{stage['stage']}", "return_to": "current"}],
            }
            for index, stage in enumerate(WORK_ORDER_FLOW)
        ],
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

def _match_position_entry(keyword: str) -> Optional[tuple[str, Dict[str, Any]]]:
    """按关键词模糊匹配职位并返回注册键与定义。"""
    if not keyword:
        return None
    normalized = keyword.strip().lower()
    for key, sop in POSITION_SOPS.items():
        candidates = [key, sop["title"], *sop["aliases"]]
        if any(normalized in str(candidate).lower() or str(candidate).lower() in normalized for candidate in candidates):
            return key, sop
    return None


def _match_position(keyword: str) -> Optional[Dict[str, Any]]:
    entry = _match_position_entry(keyword)
    return entry[1] if entry else None


def get_workflow_catalog() -> List[Dict[str, Any]]:
    """返回流程引擎可渲染对象；供模型工具说明和流程目录使用。"""
    processes = [
        {
            "workflow_key": key,
            "scope": definition.get("metadata", {}).get("process_scope", "process"),
            "title": definition["title"],
            "aliases": definition.get("aliases", []),
            "description": definition.get("description", ""),
            "step_count": len(definition.get("steps", [])),
        }
        for key, definition in BUSINESS_WORKFLOW_REGISTRY.items()
    ]
    positions = [
        {
            "workflow_key": "pmc:end_to_end" if key == "pmc_planner" else f"position:{key}",
            "scope": "position_end_to_end",
            "title": f"{sop['title']} 工作流",
            "aliases": sop.get("aliases", []),
            "description": sop.get("duties", ""),
            "step_count": len(sop.get("daily_flow", [])),
        }
        for key, sop in POSITION_SOPS.items()
    ]
    return processes + positions


def _match_business_workflow(selector: str) -> Optional[tuple[str, Dict[str, Any]]]:
    if not selector:
        return None
    normalized = selector.strip().casefold()
    if normalized in BUSINESS_WORKFLOW_REGISTRY:
        return normalized, BUSINESS_WORKFLOW_REGISTRY[normalized]
    candidates: List[tuple[int, str, Dict[str, Any]]] = []
    for key, definition in BUSINESS_WORKFLOW_REGISTRY.items():
        for alias in [key, definition.get("title", ""), *definition.get("aliases", [])]:
            alias_text = str(alias).strip().casefold()
            if alias_text and (alias_text in normalized or normalized in alias_text):
                candidates.append((len(alias_text), key, definition))
    if not candidates:
        return None
    _, key, definition = max(candidates, key=lambda item: item[0])
    return key, definition


def build_registered_workflow_diagram(
    workflow_key: str = "",
    process_name: str = "",
    position: str = "",
    current_step: int = 0,
) -> Dict[str, Any]:
    """按明确注册对象出图；未知对象返回目录，绝不回退到 PMC 父流程。"""
    from core.workflow_diagram_engine import build_business_flow_diagram

    key = (workflow_key or "").strip()
    if key in {"pmc", "pmc:end_to_end", "position:pmc_planner"}:
        return build_pmc_workflow_diagram(current_step=current_step)
    if key.startswith("position:"):
        return build_position_workflow_diagram(key.split(":", 1)[1], current_step=current_step)
    if position:
        return build_position_workflow_diagram(position, current_step=current_step)

    selector = key or (process_name or "").strip()
    entry = _match_business_workflow(selector)
    if not entry:
        return {
            "type": "workflow_diagram",
            "source": "business_workflow_registry",
            "error": f"未找到已注册业务流程：{selector or '未指定'}",
            "requested_scope": "standalone_process" if process_name else "unknown",
            "available_workflows": get_workflow_catalog(),
            "hint": "请明确要画岗位端到端流程还是独立业务子流程；系统不会用 PMC 父流程代替未知流程。",
        }
    registry_key, definition = entry
    diagram = build_business_flow_diagram(
        workflow_key=registry_key,
        title=definition["title"],
        role=definition.get("role"),
        description=definition.get("description", ""),
        steps=definition.get("steps", []),
        current_step=current_step,
        source="business_workflow_registry",
        metadata={
            "registry_key": registry_key,
            "requested_process": process_name or definition["title"],
            **definition.get("metadata", {}),
        },
    )
    start_node = next(node for node in diagram["nodes"] if node.get("id") == "start")
    end_node = next(node for node in diagram["nodes"] if node.get("id") == "end")
    start_node.update({
        "label": definition.get("start_title", "业务需求输入"),
        "title": definition.get("start_title", "业务需求输入"),
        "summary": definition.get("start_summary", definition.get("description", "")),
    })
    end_node.update({
        "label": definition.get("end_title", "流程闭环"),
        "title": definition.get("end_title", "流程闭环"),
        "summary": definition.get("end_summary", "所有流程证据闭环。"),
    })
    return {
        "type": "workflow_diagram",
        "source": "business_workflow_registry",
        "workflow_key": registry_key,
        "title": diagram["title"],
        "scope": definition.get("metadata", {}).get("process_scope", "standalone"),
        "diagram": diagram,
    }


def build_pmc_workflow_diagram(current_step: int = 0) -> Dict[str, Any]:
    """PMC专用端到端流程；不经过审批实例，也绝不回退到DCC。"""
    from core.workflow_diagram_engine import build_business_flow_diagram

    sop = POSITION_SOPS["pmc_planner"]
    diagram = build_business_flow_diagram(
        workflow_key="pmc:end_to_end",
        title="PMC端到端工作流程图（销售订单评审→交付闭环）",
        role=sop["title"],
        description="从销售订单输入开始，经过订单评审、MRP齐套、产能排程、工单释放、执行监控，直到交付闭环；每个Gate同时保留通过与不通过/Fallback路径。",
        steps=sop.get("daily_flow", []),
        current_step=current_step,
        source="pmc_workflow_registry",
        metadata={
            "workflow_domain": "PMC",
            "position_key": "pmc_planner",
            "position_title": sop["title"],
            "related_parties": ["销售/业务", "RD/工程", "采购", "仓库", "IQC/品质", "生产主管", "车间/班组", "物流/关务"],
            "escalation": sop.get("escalation"),
            "related_tools": sop.get("related_tools"),
            "forbid_approval_fallback": True,
        },
    )
    next(node for node in diagram["nodes"] if node.get("id") == "start").update({
        "label": "销售订单输入",
        "title": "销售订单输入",
        "summary": "销售/业务提交订单、需求数量、RDD和产品版本资料。",
    })
    next(node for node in diagram["nodes"] if node.get("id") == "end").update({
        "label": "交付承诺与订单闭环",
        "title": "交付承诺与订单闭环",
        "summary": "质量、数量、出货与ETA证据闭环，完成客户交付承诺和复盘。",
    })
    return {
        "type": "workflow_diagram",
        "source": "pmc_workflow_registry",
        "workflow_key": "pmc:end_to_end",
        "title": diagram["title"],
        "position": sop["title"],
        "diagram": diagram,
    }


def build_position_workflow_diagram(position: str, current_step: int = 0) -> Dict[str, Any]:
    """把职位SOP送入通用流程引擎；所有职位共用同一图契约。"""
    from core.workflow_diagram_engine import build_business_flow_diagram

    entry = _match_position_entry(position)
    if not entry:
        return {
            "type": "workflow_diagram",
            "source": "business_workflow_registry",
            "error": f"未找到职位工作流：{position}",
            "available_positions": [sop["title"] for sop in POSITION_SOPS.values()],
            "hint": "请指定职位名称，例如 PMC、品检员、操作员或生产主管。",
        }
    key, sop = entry
    if key == "pmc_planner":
        return build_pmc_workflow_diagram(current_step=current_step)
    diagram = build_business_flow_diagram(
        workflow_key=f"position:{key}",
        title=f"{sop['title']} 工作流",
        role=sop["title"],
        description=sop.get("duties", ""),
        steps=sop.get("daily_flow", []),
        current_step=current_step,
        metadata={
            "position_key": key,
            "position_title": sop["title"],
            "escalation": sop.get("escalation"),
            "related_tools": sop.get("related_tools"),
        },
    )
    return {
        "type": "workflow_diagram",
        "source": "business_workflow_registry",
        "workflow_key": f"position:{key}",
        "title": diagram["title"],
        "position": sop["title"],
        "diagram": diagram,
    }


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


__all__ = [
    "WORK_ORDER_FLOW",
    "POSITION_SOPS",
    "BUSINESS_WORKFLOW_REGISTRY",
    "RACI_MATRIX",
    "query_knowledge",
    "get_workflow_catalog",
    "build_registered_workflow_diagram",
    "build_pmc_workflow_diagram",
    "build_position_workflow_diagram",
]
