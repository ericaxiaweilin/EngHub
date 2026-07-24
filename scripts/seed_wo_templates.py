"""
工单模板种子数据（数据库驱动，按模块分组）
5 个模块 × 3~4 个模板 = 17 个新模板 + 更新现有 5 个通用模板的 module/form_fields

运行: .venv/bin/python scripts/seed_wo_templates.py
"""
import asyncio
import json
import uuid
import os

import asyncpg

DB_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/enghub")

# 两厂 factory_id（与 seed_elec_factory.py 一致）
MECH_FID = "FAC_MECH_001"
ELEC_FID = "FAC_ELEC_DEMO_2026"

# ==================== 模板定义 ====================
# (code, name, module, color, badge, standard, description, fields)

TEMPLATES = [
    # ━━━━━ QMS 品质模块 ━━━━━
    ("WO-TPL-8D", "8D纠正措施报告", "qms", "#f5222d", "D1-D8 完整闭环",
     "IATF 16949 / Ford 8D / AIAG",
     "客户投诉或重大品质异常的完整8D纠正措施流程：团队组建→问题描述→围堵→根因→纠正→预防→验证→关闭",
     [
         {"key": "d1_team", "label": "D1-团队成员", "type": "textarea", "required": True, "placeholder": "组长/成员/职能(品质/工程/生产/采购)..."},
         {"key": "d2_problem", "label": "D2-问题描述(5W2H)", "type": "textarea", "required": True, "placeholder": "What/Where/When/Who/Why/How/How much..."},
         {"key": "product_code", "label": "产品编码", "type": "text", "required": True, "placeholder": "如: PRD-A1023", "span": 12},
         {"key": "customer", "label": "客户/产线", "type": "text", "required": True, "placeholder": "如: 客户A / Line4", "span": 12},
         {"key": "defect_qty", "label": "不良数量", "type": "number", "required": True, "suffix": "pcs", "span": 8},
         {"key": "ppm", "label": "不良PPM", "type": "number", "suffix": "ppm", "span": 8},
         {"key": "severity", "label": "严重等级", "type": "radio", "required": True, "options": ["Critical", "Major", "Minor"]},
         {"key": "d3_containment", "label": "D3-围堵措施", "type": "textarea", "required": True, "placeholder": "库存隔离/在制品筛选/客户端追溯/加严检验..."},
         {"key": "d4_root_cause", "label": "D4-根本原因(鱼骨图/5Why)", "type": "textarea", "required": True, "placeholder": "人/机/料/法/环/测 分析，5Why追问到真因..."},
         {"key": "d5_corrective", "label": "D5-永久纠正措施", "type": "textarea", "required": True, "placeholder": "针对真因的永久对策(防错/工艺变更/治具改善)..."},
         {"key": "d6_verify", "label": "D6-效果验证", "type": "textarea", "placeholder": "验证方法/数据/批次/结果(PPM下降趋势)..."},
         {"key": "d7_preventive", "label": "D7-预防措施/标准化", "type": "textarea", "placeholder": "水平展开/文件更新(FMEA/CP/SOP)/培训..."},
         {"key": "d8_close", "label": "D8-团队祝贺/关闭", "type": "radio", "options": ["待关闭", "已验证关闭"]},
         {"key": "due_date", "label": "要求关闭日期", "type": "date"},
     ]),
    ("WO-TPL-CAR", "客户投诉处理单", "qms", "#eb2f96", "响应: 24h内",
     "ISO 9001 §9.1.2 / IATF §9.1.3",
     "客户投诉受理→原因分析→纠正措施→回复客户，追踪客诉关闭率与响应时效",
     [
         {"key": "customer_name", "label": "客户名称", "type": "text", "required": True, "span": 12},
         {"key": "complaint_no", "label": "客诉编号", "type": "text", "required": True, "placeholder": "如: CC-2026-0089", "span": 12},
         {"key": "product_code", "label": "涉及产品", "type": "text", "required": True, "span": 12},
         {"key": "complaint_date", "label": "投诉日期", "type": "date", "required": True},
         {"key": "defect_desc", "label": "投诉内容", "type": "textarea", "required": True, "placeholder": "客户反馈的不良现象、数量、批次..."},
         {"key": "qty_affected", "label": "涉及数量", "type": "number", "suffix": "pcs", "span": 8},
         {"key": "claim_amount", "label": "索赔金额", "type": "number", "suffix": "元", "span": 8},
         {"key": "urgency", "label": "紧急程度", "type": "radio", "required": True, "options": ["特急(停线)", "紧急(3日)", "一般(7日)"]},
         {"key": "root_cause", "label": "原因分析", "type": "textarea", "placeholder": "流出原因+发生原因..."},
         {"key": "corrective_action", "label": "纠正措施", "type": "textarea", "placeholder": "对策内容/责任人/完成日..."},
         {"key": "customer_reply", "label": "客户回复内容", "type": "textarea", "placeholder": "正式回复客户的8D/报告摘要..."},
     ]),
    ("WO-TPL-SPC", "SPC异常处置单", "qms", "#722ed1", "Cpk < 1.33 触发",
     "AIAG SPC Manual / ISO 7870",
     "控制图触发异常规则(超限/趋势/偏移)时的处置流程：停线→排查→纠正→恢复",
     [
         {"key": "control_chart", "label": "控制图编号", "type": "text", "required": True, "placeholder": "如: Xbar-R-OP30-D1", "span": 12},
         {"key": "characteristic", "label": "管控特性", "type": "text", "required": True, "placeholder": "如: 外径 Ø25±0.05", "span": 12},
         {"key": "rule_violated", "label": "违反规则", "type": "select", "required": True, "options": ["Rule1 超限", "Rule2 连续9点同侧", "Rule3 连续6点递增/递减", "Rule4 连续14点交替", "Cpk<1.33", "其他"]},
         {"key": "process_step", "label": "工序/设备", "type": "text", "required": True, "placeholder": "如: OP30 CNC-05"},
         {"key": "out_of_spec_qty", "label": "疑似不良数", "type": "number", "suffix": "pcs", "span": 8},
         {"key": "time_detected", "label": "发现时间", "type": "date"},
         {"key": "immediate_action", "label": "即时措施", "type": "select", "required": True, "options": ["停线调整", "全数筛选", "加严抽检", "调整参数后继续"]},
         {"key": "cause_analysis", "label": "异常原因", "type": "textarea", "placeholder": "刀具磨损/材料批次/温漂/夹具松动..."},
         {"key": "corrective", "label": "纠正措施", "type": "textarea", "placeholder": "换刀/补偿/更换批次/修夹具..."},
         {"key": "cpk_after", "label": "改善后Cpk", "type": "number", "span": 8},
     ]),
    ("WO-TPL-IQC", "来料异常报告", "qms", "#fa541c", "IQC 判定",
     "ISO 9001 §8.4 / AQL GB2828",
     "来料检验发现不合格时的处理：标识→隔离→评审→处置(退货/特采/筛选)→供应商纠正",
     [
         {"key": "supplier", "label": "供应商", "type": "text", "required": True, "span": 12},
         {"key": "material_code", "label": "物料编码", "type": "text", "required": True, "span": 12},
         {"key": "po_no", "label": "采购单号", "type": "text", "placeholder": "如: PO-2026-0456", "span": 12},
         {"key": "delivery_no", "label": "送货单号", "type": "text", "span": 12},
         {"key": "received_qty", "label": "来料数量", "type": "number", "required": True, "suffix": "pcs/kg", "span": 8},
         {"key": "sample_qty", "label": "抽样数", "type": "number", "suffix": "pcs", "span": 8},
         {"key": "defect_qty", "label": "不良数", "type": "number", "required": True, "suffix": "pcs", "span": 8},
         {"key": "aql_level", "label": "AQL等级", "type": "select", "options": ["Level I", "Level II(标准)", "Level III", "加严"]},
         {"key": "defect_desc", "label": "不良描述", "type": "textarea", "required": True, "placeholder": "外观/尺寸/功能/材质 具体不良现象..."},
         {"key": "disposition", "label": "处置判定", "type": "radio", "required": True, "options": ["退货RTV", "特采Concession", "全数筛选", "返工后使用", "报废"]},
         {"key": "sc_required", "label": "是否要求供应商8D", "type": "radio", "options": ["是", "否"]},
     ]),

    # ━━━━━ 设备模块 ━━━━━
    ("WO-TPL-PM", "PM保养计划单", "equipment", "#13c2c2", "周期性",
     "ISO 55001 / TPM",
     "预防性维护计划执行：按周期(日保/周保/月保/年保)对设备进行标准化保养作业",
     [
         {"key": "equipment_code", "label": "设备编号", "type": "text", "required": True, "span": 12},
         {"key": "equipment_name", "label": "设备名称", "type": "text", "required": True, "span": 12},
         {"key": "pm_level", "label": "保养级别", "type": "radio", "required": True, "options": ["日保(操作者)", "周保", "月保", "季保", "年保(大修)"]},
         {"key": "planned_date", "label": "计划执行日", "type": "date", "required": True},
         {"key": "checklist", "label": "保养项目清单", "type": "textarea", "required": True, "placeholder": "1.润滑部位注油\n2.皮带张力检查\n3.滤芯更换\n4.精度校验..."},
         {"key": "spare_parts", "label": "所需备件/耗材", "type": "textarea", "placeholder": "滤芯×2 / 润滑油1L / 皮带×1..."},
         {"key": "estimated_hours", "label": "预计工时", "type": "number", "suffix": "小时", "span": 8},
         {"key": "need_shutdown", "label": "是否需停机", "type": "radio", "required": True, "options": ["是-需协调停产", "否-可在线保养"]},
         {"key": "executor", "label": "执行人", "type": "text", "span": 12},
     ]),
    ("WO-TPL-INSPECT-ABN", "点检异常报告", "equipment", "#fa8c16", "点检发现",
     "TPM 自主保全",
     "日常点检发现设备异常(非停机)时的预警报告：记录异常→评估→安排处理",
     [
         {"key": "equipment_code", "label": "设备编号", "type": "text", "required": True, "span": 12},
         {"key": "check_date", "label": "点检日期", "type": "date", "required": True},
         {"key": "abnormal_item", "label": "异常项目", "type": "select", "required": True, "options": ["异响/振动", "温度偏高", "漏油/漏气", "精度偏移", "电气异常", "安全装置异常", "外观损伤", "其他"]},
         {"key": "abnormal_desc", "label": "异常描述", "type": "textarea", "required": True, "placeholder": "具体部位、现象、程度..."},
         {"key": "urgency", "label": "紧急程度", "type": "radio", "required": True, "options": ["立即处理(安全隐患)", "本班内处理", "可安排计划处理"]},
         {"key": "can_continue", "label": "能否继续运行", "type": "radio", "required": True, "options": ["可继续(降速)", "必须停机", "观察运行"]},
         {"key": "photo_note", "label": "现场照片/备注", "type": "text", "placeholder": "已拍照编号/位置说明"},
     ]),
    ("WO-TPL-SPARE", "备件申请单", "equipment", "#2f54eb", "库存联动",
     "ISO 55001 资产管理",
     "维修/保养所需备件的采购申请：含规格、用量、库存核对与紧急程度",
     [
         {"key": "equipment_code", "label": "关联设备", "type": "text", "required": True, "span": 12},
         {"key": "part_name", "label": "备件名称", "type": "text", "required": True, "span": 12},
         {"key": "part_spec", "label": "规格型号", "type": "text", "required": True, "placeholder": "如: 轴承 6205-2RS / 滤芯 HF-320", "span": 12},
         {"key": "qty_needed", "label": "需求数量", "type": "number", "required": True, "suffix": "个/套", "span": 8},
         {"key": "current_stock", "label": "当前库存", "type": "number", "suffix": "个", "span": 8},
         {"key": "urgency", "label": "紧急程度", "type": "radio", "required": True, "options": ["紧急(停机待件)", "3日内", "计划性(周/月)"]},
         {"key": "purpose", "label": "用途", "type": "select", "required": True, "options": ["故障维修", "PM保养", "改善改造", "安全库存补充"]},
         {"key": "preferred_vendor", "label": "建议供应商", "type": "text", "placeholder": "品牌/供应商/联系方式"},
         {"key": "estimated_cost", "label": "预估单价", "type": "number", "suffix": "元", "span": 8},
     ]),
    ("WO-TPL-EQUIP-MOD", "设备改造申请", "equipment", "#597ef7", "需审批",
     "TPM 个别改善",
     "设备改善/改造/升级申请：含现状问题、改造方案、预算与预期收益",
     [
         {"key": "equipment_code", "label": "目标设备", "type": "text", "required": True, "span": 12},
         {"key": "modification_type", "label": "改造类型", "type": "select", "required": True, "options": ["效率提升", "品质改善", "安全改善", "节能降耗", "自动化升级", "防错(Poka-Yoke)"]},
         {"key": "current_issue", "label": "现状问题", "type": "textarea", "required": True, "placeholder": "当前设备存在的问题/瓶颈/数据..."},
         {"key": "proposal", "label": "改造方案", "type": "textarea", "required": True, "placeholder": "改造内容/方法/步骤..."},
         {"key": "expected_benefit", "label": "预期收益", "type": "textarea", "placeholder": "效率提升%/不良率降低/节省金额..."},
         {"key": "budget", "label": "预估费用", "type": "number", "required": True, "suffix": "元", "span": 8},
         {"key": "downtime_plan", "label": "停机计划", "type": "text", "placeholder": "需停机X天/利用假期", "span": 12},
         {"key": "payback_period", "label": "投资回收期", "type": "text", "placeholder": "如: 6个月", "span": 12},
     ]),

    # ━━━━━ WMS 仓储模块 ━━━━━
    ("WO-TPL-INV-DIFF", "盘点差异单", "wms", "#faad14", "账实不符",
     "ISO 9001 §7.1.5 / 财务合规",
     "库存盘点发现账实差异时的处理：差异记录→原因调查→调整审批→纠正",
     [
         {"key": "warehouse", "label": "仓库/库位", "type": "text", "required": True, "span": 12},
         {"key": "material_code", "label": "物料编码", "type": "text", "required": True, "span": 12},
         {"key": "system_qty", "label": "系统数量", "type": "number", "required": True, "span": 8},
         {"key": "actual_qty", "label": "实盘数量", "type": "number", "required": True, "span": 8},
         {"key": "diff_qty", "label": "差异数量", "type": "number", "required": True, "span": 8},
         {"key": "unit_cost", "label": "单位成本", "type": "number", "suffix": "元", "span": 8},
         {"key": "diff_amount", "label": "差异金额", "type": "number", "suffix": "元", "span": 8},
         {"key": "cause", "label": "差异原因", "type": "select", "required": True, "options": ["发料未扣账", "收货未入账", "报废未处理", "错放/混料", "系统录入错误", "失窃/丢失", "待查"]},
         {"key": "adjustment", "label": "调整方式", "type": "radio", "required": True, "options": ["盘盈入账", "盘亏核销", "暂挂待查"]},
         {"key": "corrective", "label": "纠正措施", "type": "textarea", "placeholder": "防止再发措施..."},
     ]),
    ("WO-TPL-RETURN", "退料单", "wms", "#a0d911", "产线→仓库",
     "WMS 退料流程",
     "产线剩余物料/不良物料退回仓库：含退料原因、数量核对与品质判定",
     [
         {"key": "work_order_no", "label": "原工单号", "type": "text", "required": True, "span": 12},
         {"key": "material_code", "label": "物料编码", "type": "text", "required": True, "span": 12},
         {"key": "return_qty", "label": "退料数量", "type": "number", "required": True, "suffix": "pcs/kg", "span": 8},
         {"key": "return_reason", "label": "退料原因", "type": "select", "required": True, "options": ["工单结束余料", "物料不良", "工程变更(旧料)", "订单取消", "多发料", "其他"]},
         {"key": "material_status", "label": "物料状态", "type": "radio", "required": True, "options": ["良品(可再用)", "不良(待判定)", "报废"]},
         {"key": "batch_no", "label": "批次号", "type": "text", "span": 12},
         {"key": "return_from", "label": "退料工位/产线", "type": "text", "span": 12},
         {"key": "remark", "label": "备注", "type": "textarea", "placeholder": "补充说明..."},
     ]),
    ("WO-TPL-DEAD-STOCK", "呆滞料处理单", "wms", "#8c8c8c", "库龄>90天",
     "库存管理 / 财务合规",
     "超过周转天数的呆滞物料处理：鉴定→处置(降级/退供/报废)→财务核销",
     [
         {"key": "material_code", "label": "物料编码", "type": "text", "required": True, "span": 12},
         {"key": "material_name", "label": "物料名称", "type": "text", "required": True, "span": 12},
         {"key": "stock_qty", "label": "库存数量", "type": "number", "required": True, "span": 8},
         {"key": "stock_days", "label": "库龄(天)", "type": "number", "required": True, "suffix": "天", "span": 8},
         {"key": "stock_amount", "label": "库存金额", "type": "number", "suffix": "元", "span": 8},
         {"key": "dead_cause", "label": "呆滞原因", "type": "select", "required": True, "options": ["订单取消", "设计变更", "过量采购", "客户停产", "品质问题封存", "其他"]},
         {"key": "disposition", "label": "处置建议", "type": "radio", "required": True, "options": ["降级使用", "退供应商", "转售", "报废核销", "继续保留(有订单)"]},
         {"key": "finance_approval", "label": "是否需财务审批", "type": "radio", "options": ["是(金额>阈值)", "否"]},
     ]),
    ("WO-TPL-RECV-ABN", "入库异常单", "wms", "#ffa940", "收货异常",
     "WMS 收货流程",
     "收货环节发现异常(数量/包装/标识/品质)时的记录与处理",
     [
         {"key": "po_no", "label": "采购单号", "type": "text", "required": True, "span": 12},
         {"key": "supplier", "label": "供应商", "type": "text", "required": True, "span": 12},
         {"key": "abnormal_type", "label": "异常类型", "type": "select", "required": True, "options": ["数量短缺", "数量溢出", "包装破损", "标识不清/错误", "无送货单", "品质异常(外观)", "混料"]},
         {"key": "expected_qty", "label": "应收数量", "type": "number", "span": 8},
         {"key": "actual_qty", "label": "实收数量", "type": "number", "span": 8},
         {"key": "diff_qty", "label": "差异数量", "type": "number", "span": 8},
         {"key": "description", "label": "异常描述", "type": "textarea", "required": True, "placeholder": "具体异常现象、涉及箱数/托数..."},
         {"key": "handling", "label": "处理方式", "type": "radio", "required": True, "options": ["拒收退回", "部分收货", "先收后补", "特采接收"]},
         {"key": "notify_purchasing", "label": "是否通知采购", "type": "radio", "options": ["是", "否"]},
     ]),

    # ━━━━━ 生产模块 ━━━━━
    ("WO-TPL-REWORK-OP", "返工处理单", "production", "#f5222d", "品质触发",
     "ISO 9001 §8.7.1",
     "不良品/客户退回品的返工作业：含返工工艺、数量追踪与再检验要求",
     [
         {"key": "source_wo", "label": "原工单号", "type": "text", "required": True, "span": 12},
         {"key": "product_code", "label": "产品编码", "type": "text", "required": True, "span": 12},
         {"key": "rework_qty", "label": "返工数量", "type": "number", "required": True, "suffix": "pcs", "span": 8},
         {"key": "defect_type", "label": "不良类型", "type": "select", "required": True, "options": ["外观不良", "尺寸超差", "功能异常", "装配错误", "焊接不良", "其他"]},
         {"key": "rework_process", "label": "返工工艺/步骤", "type": "textarea", "required": True, "placeholder": "从哪道工序开始、具体返工操作方法..."},
         {"key": "start_station", "label": "起始工位", "type": "text", "placeholder": "如: OP20 打磨", "span": 12},
         {"key": "reinspection", "label": "再检要求", "type": "radio", "required": True, "options": ["全数重检", "加严抽检", "正常抽检"]},
         {"key": "responsible", "label": "责任部门", "type": "select", "options": ["生产部", "品质部", "工程部", "供应商"]},
         {"key": "time_limit", "label": "完成时限", "type": "date"},
     ]),
    ("WO-TPL-PROD-ABN", "生产异常报告", "production", "#fa541c", "产线异常",
     "MES 异常管理",
     "生产过程中各类异常事件的记录与处理：停线/品质/物料/工艺异常",
     [
         {"key": "work_order_no", "label": "工单号", "type": "text", "required": True, "span": 12},
         {"key": "station", "label": "异常工位/产线", "type": "text", "required": True, "span": 12},
         {"key": "abnormal_type", "label": "异常类型", "type": "select", "required": True, "options": ["品质异常(批量不良)", "设备故障停线", "物料异常(缺料/错料)", "工艺异常(参数偏移)", "人员异常(操作失误)", "环境异常(温湿度)"]},
         {"key": "start_time", "label": "异常发生时间", "type": "date", "required": True},
         {"key": "duration_min", "label": "持续时长", "type": "number", "suffix": "分钟", "span": 8},
         {"key": "impact_qty", "label": "影响数量", "type": "number", "suffix": "pcs", "span": 8},
         {"key": "description", "label": "异常描述", "type": "textarea", "required": True, "placeholder": "发生经过、现象、初步判断..."},
         {"key": "immediate_action", "label": "即时处理", "type": "textarea", "placeholder": "已采取的临时措施..."},
         {"key": "escalated_to", "label": "升级至", "type": "select", "options": ["组长", "主管", "经理", "无需升级"]},
         {"key": "root_cause", "label": "原因分析", "type": "textarea", "placeholder": "根本原因(待调查可后补)..."},
     ]),
    ("WO-TPL-SHIFT", "交接班异常记录", "production", "#52c41a", "班次交接",
     "MES 交接班管理",
     "交接班时记录的异常事项/遗留问题/注意事项，确保信息不断层",
     [
         {"key": "shift_from", "label": "交班班次", "type": "radio", "required": True, "options": ["白班→夜班", "夜班→白班", "A班→B班"]},
         {"key": "line", "label": "产线/区域", "type": "text", "required": True, "span": 12},
         {"key": "production_status", "label": "当班生产概况", "type": "textarea", "required": True, "placeholder": "完成工单/产量/良率/在制品状态..."},
         {"key": "abnormal_items", "label": "异常/遗留事项", "type": "textarea", "required": True, "placeholder": "1. 设备XX异响待修\n2. 物料XX缺料等补\n3. 工单XX待首检确认..."},
         {"key": "pending_actions", "label": "待办事项", "type": "textarea", "placeholder": "需下一班跟进的事项..."},
         {"key": "safety_notes", "label": "安全注意事项", "type": "textarea", "placeholder": "安全隐患/LOTO状态/特殊注意..."},
         {"key": "handover_person", "label": "交班人", "type": "text", "span": 12},
         {"key": "receiver", "label": "接班人", "type": "text", "span": 12},
     ]),

    # ━━━━━ PP 计划模块 ━━━━━
    ("WO-TPL-URGENT-INSERT", "插单申请", "pp", "#f5222d", "紧急排产",
     "PMC 插单管理",
     "紧急订单插入现有排产的申请：含影响评估、资源协调与审批",
     [
         {"key": "order_no", "label": "订单号", "type": "text", "required": True, "span": 12},
         {"key": "customer", "label": "客户", "type": "text", "required": True, "span": 12},
         {"key": "product_code", "label": "产品编码", "type": "text", "required": True, "span": 12},
         {"key": "qty", "label": "数量", "type": "number", "required": True, "suffix": "pcs", "span": 8},
         {"key": "required_date", "label": "要求交期", "type": "date", "required": True},
         {"key": "urgency_reason", "label": "插单原因", "type": "select", "required": True, "options": ["客户紧急需求", "补单(品质退货)", "样品加急", "战略客户优先", "其他"]},
         {"key": "impact_assessment", "label": "对现有排产影响", "type": "textarea", "required": True, "placeholder": "哪些工单需延后/加班/外协..."},
         {"key": "resource_need", "label": "资源需求", "type": "textarea", "placeholder": "物料/人力/设备/模具 是否齐备..."},
         {"key": "approver", "label": "审批人", "type": "text", "span": 12},
     ]),
    ("WO-TPL-SCHEDULE-CHG", "排产变更申请", "pp", "#1890ff", "计划调整",
     "PMC 变更管理",
     "因各种原因需调整已排定生产计划的申请：含变更内容与影响分析",
     [
         {"key": "original_plan", "label": "原计划编号/工单", "type": "text", "required": True, "span": 12},
         {"key": "change_type", "label": "变更类型", "type": "select", "required": True, "options": ["提前生产", "延后生产", "数量变更", "产线切换", "优先级调整", "取消"]},
         {"key": "change_reason", "label": "变更原因", "type": "select", "required": True, "options": ["客户交期变更", "物料延迟", "设备故障", "品质问题", "人力不足", "插单影响", "其他"]},
         {"key": "original_date", "label": "原计划日期", "type": "date", "span": 12},
         {"key": "new_date", "label": "变更后日期", "type": "date", "span": 12},
         {"key": "affected_orders", "label": "受影响的其他工单", "type": "textarea", "placeholder": "因本次变更需联动调整的工单..."},
         {"key": "mitigation", "label": "补救措施", "type": "textarea", "placeholder": "加班/外协/调货等补救方案..."},
     ]),
]


async def main():
    conn = await asyncpg.connect(DB_URL)

    # 1. 执行迁移（加列）
    migration_path = os.path.join(os.path.dirname(__file__), "..", "database", "migrations", "029_wo_template_module_fields.sql")
    if os.path.exists(migration_path):
        sql = open(migration_path).read()
        await conn.execute(sql)
        print("[1] 迁移 029 已执行（加列）")

    # 2. 插入新模板（两厂各一份）
    inserted = 0
    for fid in [MECH_FID, ELEC_FID]:
        for code, name, module, color, badge, standard, desc, fields in TEMPLATES:
            exists = await conn.fetchval(
                "SELECT 1 FROM work_order_templates WHERE factory_id=$1 AND template_code=$2", fid, code
            )
            if exists:
                # 更新已有记录的 form_fields/module 等
                await conn.execute("""
                    UPDATE work_order_templates
                    SET module=$3, form_fields=$4, standard_ref=$5, badge_text=$6, color=$7, description=$8, updated_at=NOW()
                    WHERE factory_id=$1 AND template_code=$2
                """, fid, code, module, json.dumps(fields, ensure_ascii=False), standard, badge, color, desc)
            else:
                await conn.execute("""
                    INSERT INTO work_order_templates
                    (id, factory_id, template_code, template_name, wo_type, module, description,
                     form_fields, standard_ref, badge_text, color, is_active, sort_order, created_at, updated_at)
                    VALUES ($1,$2,$3,$4,'operation',$5,$6,$7,$8,$9,$10,true,0,NOW(),NOW())
                """, str(uuid.uuid4()), fid, code, name, module, desc,
                     json.dumps(fields, ensure_ascii=False), standard, badge, color)
                inserted += 1

    print(f"[2] 新增 {inserted} 条模板记录（两厂 × {len(TEMPLATES)} 模板）")

    # 3. 更新现有通用模板的 module 归属（已有但无 form_fields 的）
    await conn.execute("UPDATE work_order_templates SET module='production' WHERE template_code IN ('WO-TPL-PROD','WO-TPL-REWORK','WO-TPL-TRIAL','WO-TPL-SAMPLE') AND module IS NULL")
    await conn.execute("UPDATE work_order_templates SET module='equipment' WHERE template_code='WO-TPL-MAINT' AND module IS NULL")

    # 4. 验证
    total = await conn.fetchval("SELECT count(*) FROM work_order_templates")
    with_fields = await conn.fetchval("SELECT count(*) FROM work_order_templates WHERE form_fields IS NOT NULL AND form_fields != '[]'")
    modules = await conn.fetch("SELECT module, count(*) as cnt FROM work_order_templates GROUP BY module ORDER BY module")

    print(f"\n✅ 完成:")
    print(f"  模板总数: {total}")
    print(f"  含表单字段: {with_fields}")
    for r in modules:
        print(f"  {r['module']}: {r['cnt']} 个")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
