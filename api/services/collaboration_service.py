"""
岗位协同网络引擎 - 定义跨岗位信息流+决策边界
=============================================
核心原则：
1. 信息流可自动协同（事件→秒级通知相关岗位）
2. 决策权不可跨岗（只有对应岗位能执行决策）
3. 自动化等级约束协同深度（L1只通知，L2本岗自动，L3跨岗协调）

给chatbot的规则：
- 当用户问"这个事该谁管" → 查决策权
- 当用户说"通知一下" → 查信息流（谁需要知道）
- 当用户说"处理一下" → 检查是否有权限（不跨边界）
"""
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

_logger = logging.getLogger("collaboration")


# ═══════════════════════════════════════════════════════════
# 岗位定义（含权限边界）
# ═══════════════════════════════════════════════════════════

ROLES = {
    # 生产系统
    "operator": {
        "name": "操作工",
        "department": "生产",
        "can_decide": ["报工", "停机", "呼叫班组长", "首件确认"],
        "cannot_decide": ["工艺参数修改", "工单优先级", "物料替代", "放行不合格品"],
        "receives_info": ["派工", "工艺变更", "设备状态", "物料到位"],
    },
    "team_leader": {
        "name": "班组长",
        "department": "生产",
        "can_decide": ["工位调配", "小异常处理", "加班安排", "首件判定", "暂停生产"],
        "cannot_decide": ["工单取消", "工艺变更", "供应商选择", "出货放行"],
        "receives_info": ["产量异常", "设备故障", "缺料预警", "品质异常", "插单通知"],
    },
    "workshop_manager": {
        "name": "车间主任",
        "department": "生产",
        "can_decide": ["工单优先级调整", "产线调配", "人员调度", "紧急停机", "批量返工"],
        "cannot_decide": ["订单交期承诺", "供应商淘汰", "工艺路线变更", "出货判定"],
        "receives_info": ["所有生产异常", "设备重大故障", "品质批量问题", "交期风险"],
    },
    # 品质系统
    "qc_inspector": {
        "name": "质检员",
        "department": "品质",
        "can_decide": ["检验判定(合格/不合格)", "抽样方案", "外观判定", "尺寸判定"],
        "cannot_decide": ["让步接收", "供应商处罚", "工艺修改", "出货延期"],
        "receives_info": ["收货通知(IQC)", "首件请求(IPQC)", "完工通知(FQC)", "客诉(OQC)"],
    },
    "qc_engineer": {
        "name": "品质工程师",
        "department": "品质",
        "can_decide": ["让步接收", "纠正措施", "8D报告", "检验标准修改", "供应商质量评级"],
        "cannot_decide": ["生产排程", "采购下单", "出货计划", "工艺参数"],
        "receives_info": ["批量不良", "客诉", "供应商来料异常趋势", "SPC超限"],
    },
    # 仓储系统
    "warehouse_keeper": {
        "name": "仓管员",
        "department": "仓储",
        "can_decide": ["库位分配", "FIFO执行", "盘点差异上报", "收货数量确认"],
        "cannot_decide": ["物料放行(需IQC)", "报废处理", "采购决定", "出货顺序"],
        "receives_info": ["到货通知", "领料需求", "出货指令", "盘点计划"],
    },
    # 采购系统
    "buyer": {
        "name": "采购员",
        "department": "采购",
        "can_decide": ["供应商选择(标准件)", "下单(阈值内)", "跟催", "对账"],
        "cannot_decide": ["物料替代", "工艺变更", "检验标准", "生产排程"],
        "receives_info": ["MRP需求", "缺料预警", "IQC不合格(来料)", "供应商交期变更"],
    },
    # 计划系统
    "planner": {
        "name": "计划员/PMC",
        "department": "PMC",
        "can_decide": ["排产顺序", "工单下达", "MRP运算", "交期回复(内部)", "插单评估"],
        "cannot_decide": ["客户交期承诺(需销售)", "工艺路线", "质量标准", "设备维修方案"],
        "receives_info": ["新订单", "设备故障(影响产能)", "缺料", "工单完工", "品质异常(影响流转)"],
    },
    # 销售系统
    "sales": {
        "name": "销售/跟单",
        "department": "销售",
        "can_decide": ["客户交期承诺", "发货指令", "客户沟通", "报价"],
        "cannot_decide": ["生产排程", "工艺变更", "质量判定", "采购决定"],
        "receives_info": ["订单进度", "交期风险", "完工通知", "出货完成"],
    },
    # 设备系统
    "maintenance": {
        "name": "设备维护员",
        "department": "设备",
        "can_decide": ["维修方案", "是否停机", "备件请购", "保养计划执行"],
        "cannot_decide": ["生产排程调整", "工单取消", "工艺参数", "人员调配"],
        "receives_info": ["设备报警", "安灯呼叫", "PM到期", "操作工报修"],
    },
    # 技术系统
    "process_engineer": {
        "name": "工艺员",
        "department": "技术",
        "can_decide": ["工艺参数", "工艺路线", "ECN变更", "作业指导书", "材料替代建议"],
        "cannot_decide": ["生产排程", "质量标准修改", "采购下单", "出货判定"],
        "receives_info": ["新品导入", "品质异常(工艺相关)", "ECN申请", "设备能力变更"],
    },
}


# ═══════════════════════════════════════════════════════════
# 事件协同规则（每种事件：通知谁、影响谁、谁有权处理）
# ═══════════════════════════════════════════════════════════

EVENT_RULES = {
    "quality_incoming_fail": {
        "name": "来料检验不合格",
        "trigger": "IQC判定不合格",
        "source_role": "qc_inspector",
        "notify": ["buyer", "warehouse_keeper", "planner"],
        "impact": ["planner", "team_leader"],
        "decision_authority": "qc_engineer",  # 只有品质工程师能判"让步/退货/挑选"
        "decision_options": ["退货", "让步接收", "挑选使用", "降级使用"],
        "boundary": "采购不能替品质判'可以用'，仓管不能替品质'放行'",
        "auto_actions": {
            "L1": "通知采购+仓管（人决定怎么处理）",
            "L2": "自动冻结该批次库存+通知采购跟催供应商",
            "L3": "自动冻结+自动触发退货流程+自动调整排产（跳过该批料）",
        },
    },
    "quality_process_fail": {
        "name": "过程检验异常（不良率超标）",
        "trigger": "IPQC/报工不良率>阈值",
        "source_role": "qc_inspector",
        "notify": ["team_leader", "process_engineer", "workshop_manager"],
        "impact": ["planner", "team_leader"],
        "decision_authority": "workshop_manager",  # 车间主任决定"停/继续/返工"
        "decision_options": ["继续生产(观察)", "暂停(排查)", "批量返工", "报废"],
        "boundary": "操作工不能自己决定'继续做'，质检员不能决定'停线'",
        "auto_actions": {
            "L1": "通知班组长（人判断）",
            "L2": "自动通知+标记工单异常+建议暂停",
            "L3": "自动暂停该工位+触发异常升级+通知工艺员排查",
        },
    },
    "equipment_breakdown": {
        "name": "设备故障",
        "trigger": "安灯/设备报警/操作工报修",
        "source_role": "operator",
        "notify": ["maintenance", "team_leader", "planner"],
        "impact": ["planner", "team_leader", "sales"],
        "decision_authority": "maintenance",  # 维修工决定"修多久/要不要换件"
        "decision_options": ["现场修复", "更换备件", "外协维修", "报废设备"],
        "boundary": "生产不能催维修'快点修好'来跳过安全确认，计划不能跳过维修直接排产",
        "auto_actions": {
            "L1": "通知维修+班组长",
            "L2": "自动通知+释放该工位工单+建议重排",
            "L3": "自动释放工单+自动重排到其他工位+自动通知受影响的订单交期",
        },
    },
    "material_shortage": {
        "name": "缺料",
        "trigger": "库存<安全库存 / 领料不足",
        "source_role": "warehouse_keeper",
        "notify": ["buyer", "planner", "team_leader"],
        "impact": ["planner", "team_leader", "sales"],
        "decision_authority": "planner",  # 计划员决定"等料/换产/调整排程"
        "decision_options": ["等料(调整顺序)", "换产(先做有料单)", "紧急采购", "通知销售延期"],
        "boundary": "仓管不能决定'先发给谁'（按计划优先级），采购不能决定'不买了'",
        "auto_actions": {
            "L1": "通知采购+计划",
            "L2": "自动触发MRP补货建议+通知计划调整排程",
            "L3": "自动下采购单(阈值内)+自动调整排产顺序+自动通知销售交期影响",
        },
    },
    "delivery_risk": {
        "name": "交期风险",
        "trigger": "订单预计延期 / 工单超期",
        "source_role": "planner",
        "notify": ["sales", "workshop_manager", "planner"],
        "impact": ["sales", "workshop_manager"],
        "decision_authority": "sales",  # 销售决定"怎么回客户"
        "decision_options": ["协调加班赶工", "分批交货", "协商延期", "外协加工"],
        "boundary": "生产不能直接回客户'延期'（必须销售确认），计划不能承诺'一定能赶上'",
        "auto_actions": {
            "L1": "通知销售+计划（人协调）",
            "L2": "自动计算影响+生成建议方案+通知销售确认",
            "L3": "自动调整排产优先级+自动生成交期变更通知（销售确认后发出）",
        },
    },
    "urgent_order": {
        "name": "紧急插单",
        "trigger": "销售下达紧急订单",
        "source_role": "sales",
        "notify": ["planner", "workshop_manager", "team_leader"],
        "impact": ["planner", "workshop_manager", "team_leader"],
        "decision_authority": "planner",  # 计划员评估+排入
        "decision_options": ["立即插入", "排到下一批", "拒绝(产能不足)", "外协"],
        "boundary": "销售不能直接命令车间'马上做'（必须通过计划评估），车间不能拒绝已排入的插单",
        "auto_actions": {
            "L1": "通知计划评估",
            "L2": "自动评估产能影响+生成插单方案+待计划确认",
            "L3": "自动评估+自动排入（如影响<2小时）+自动通知受影响订单",
        },
    },
    "ecn_change": {
        "name": "工艺/设计变更(ECN)",
        "trigger": "工艺员发起变更",
        "source_role": "process_engineer",
        "notify": ["team_leader", "qc_engineer", "planner", "buyer"],
        "impact": ["team_leader", "qc_inspector", "buyer"],
        "decision_authority": "process_engineer",  # 工艺员决定参数/路线
        "decision_options": ["立即执行", "下批执行", "在制品返工后执行"],
        "boundary": "生产不能拒绝执行已批准的ECN，品质不能阻止已批准的工艺变更",
        "auto_actions": {
            "L1": "通知相关岗位（人确认收到）",
            "L2": "自动标记受影响工单+更新SOP+通知操作工",
            "L3": "自动标记+自动更新工艺路线+自动通知采购(物料变更)+自动调整检验标准",
        },
    },
    "shipment_ready": {
        "name": "完工待出货",
        "trigger": "FQC合格+入库完成",
        "source_role": "warehouse_keeper",
        "notify": ["sales", "planner"],
        "impact": ["sales"],
        "decision_authority": "sales",  # 销售决定"什么时候发/发多少"
        "decision_options": ["立即发货", "等凑整车", "分批先发一部分", "等客户通知"],
        "boundary": "仓库不能自己决定'发货'（需销售指令），生产不能催'快发走腾地方'",
        "auto_actions": {
            "L1": "通知销售（人安排发货）",
            "L2": "自动生成出货单+通知销售确认",
            "L3": "自动生成出货单+自动通知物流+自动更新订单状态",
        },
    },
    "supplier_delay": {
        "name": "供应商交期延迟",
        "trigger": "PO超期未到货",
        "source_role": "buyer",
        "notify": ["planner", "warehouse_keeper", "sales"],
        "impact": ["planner", "team_leader"],
        "decision_authority": "buyer",  # 采购决定"催/换/等"
        "decision_options": ["继续催货", "换供应商", "调整到货计划", "升级处理"],
        "boundary": "计划不能直接找供应商催（通过采购），生产不能自己找替代料（通过工艺+采购）",
        "auto_actions": {
            "L1": "通知采购跟催",
            "L2": "自动跟催(发邮件/短信)+通知计划调整+供应商扣分",
            "L3": "自动跟催+自动评估替代供应商+自动调整排产+自动通知销售",
        },
    },
    "safety_incident": {
        "name": "安全事故/隐患",
        "trigger": "操作工报告/设备异常",
        "source_role": "operator",
        "notify": ["team_leader", "workshop_manager", "maintenance"],
        "impact": ["workshop_manager", "team_leader"],
        "decision_authority": "workshop_manager",  # 车间主任决定"停不停/怎么处理"
        "decision_options": ["立即停线", "继续观察", "隔离区域", "上报EHS"],
        "boundary": "任何人不能阻止安全停机，但只有车间主任能决定'恢复生产'",
        "auto_actions": {
            "L1": "立即通知班组长+车间主任",
            "L2": "自动通知+自动暂停相关工位+记录事件",
            "L3": "自动暂停+自动隔离+自动升级+自动记录（恢复需人确认）",
        },
    },
}


# ═══════════════════════════════════════════════════════════
# 协同矩阵（岗位×岗位 的信息流方向）
# ═══════════════════════════════════════════════════════════

COLLABORATION_MATRIX = {
    # (from_role, to_role): 什么信息流
    ("qc_inspector", "buyer"): "来料不合格→采购处理供应商",
    ("qc_inspector", "warehouse_keeper"): "来料不合格→冻结库存",
    ("qc_inspector", "team_leader"): "过程异常→生产暂停/继续",
    ("qc_inspector", "process_engineer"): "工艺相关不良→工艺排查",
    ("operator", "maintenance"): "设备异常→维修",
    ("operator", "team_leader"): "安灯呼叫→班组长响应",
    ("team_leader", "planner"): "产能异常→计划调整",
    ("planner", "team_leader"): "排产/插单→生产执行",
    ("planner", "buyer"): "MRP需求→采购执行",
    ("planner", "sales"): "交期评估→销售回客户",
    ("buyer", "warehouse_keeper"): "到货通知→收货",
    ("buyer", "planner"): "供应商延迟→计划调整",
    ("sales", "planner"): "新订单/插单→排产",
    ("sales", "warehouse_keeper"): "发货指令→出货",
    ("warehouse_keeper", "qc_inspector"): "收货→触发IQC",
    ("warehouse_keeper", "team_leader"): "发料→生产领用",
    ("process_engineer", "team_leader"): "ECN/工艺变更→生产执行",
    ("process_engineer", "qc_engineer"): "工艺变更→检验标准更新",
    ("maintenance", "planner"): "设备停机时间→计划调整",
    ("maintenance", "team_leader"): "设备恢复→可复产",
}


class CollaborationService:
    """岗位协同网络引擎"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_network(self, factory_id: str) -> Dict[str, Any]:
        """获取完整协同网络（岗位+事件+边界）"""
        return {
            "factory_id": factory_id,
            "roles": {k: {"name": v["name"], "department": v["department"]} for k, v in ROLES.items()},
            "total_roles": len(ROLES),
            "total_event_types": len(EVENT_RULES),
            "collaboration_links": len(COLLABORATION_MATRIX),
            "events": {k: {
                "name": v["name"],
                "trigger": v["trigger"],
                "source": ROLES[v["source_role"]]["name"],
                "notify": [ROLES[r]["name"] for r in v["notify"]],
                "decision_authority": ROLES[v["decision_authority"]]["name"],
                "boundary": v["boundary"],
            } for k, v in EVENT_RULES.items()},
        }

    async def query_event_rule(self, event_key: str) -> Dict[str, Any]:
        """查询单个事件的协同规则"""
        rule = EVENT_RULES.get(event_key)
        if not rule:
            return {"error": f"未知事件: {event_key}", "available": list(EVENT_RULES.keys())}

        return {
            "event_key": event_key,
            "name": rule["name"],
            "trigger": rule["trigger"],
            "source_role": rule["source_role"],
            "source_role_name": ROLES[rule["source_role"]]["name"],
            "notify": [{"role": r, "name": ROLES[r]["name"], "dept": ROLES[r]["department"]} for r in rule["notify"]],
            "impact": [{"role": r, "name": ROLES[r]["name"]} for r in rule["impact"]],
            "decision_authority": {
                "role": rule["decision_authority"],
                "name": ROLES[rule["decision_authority"]]["name"],
                "options": rule["decision_options"],
            },
            "boundary": rule["boundary"],
            "auto_actions": rule["auto_actions"],
        }

    async def check_permission(self, role_key: str, action: str) -> Dict[str, Any]:
        """检查某岗位是否有权执行某动作（边界检查）"""
        role = ROLES.get(role_key)
        if not role:
            return {"error": f"未知岗位: {role_key}"}

        can = action in role["can_decide"]
        cannot = action in role["cannot_decide"]

        if can:
            return {"allowed": True, "role": role["name"], "action": action, "message": f"✅ {role['name']}有权执行'{action}'"}
        elif cannot:
            # 找谁有权
            who_can = [r["name"] for r in ROLES.values() if action in r["can_decide"]]
            return {
                "allowed": False,
                "role": role["name"],
                "action": action,
                "message": f"❌ {role['name']}无权执行'{action}'",
                "who_can": who_can,
                "suggestion": f"请联系 {'/'.join(who_can)} 处理",
            }
        else:
            return {"allowed": None, "role": role["name"], "action": action, "message": f"⚠️ '{action}'未明确定义权限，建议确认"}

    async def get_role_boundaries(self, role_key: str) -> Dict[str, Any]:
        """获取某岗位的完整权限边界"""
        role = ROLES.get(role_key)
        if not role:
            return {"error": f"未知岗位: {role_key}"}

        # 找该岗位参与的事件
        involved_events = []
        for key, rule in EVENT_RULES.items():
            if role_key in [rule["source_role"]] + rule["notify"] + rule["impact"] or role_key == rule["decision_authority"]:
                involved_events.append({
                    "event": rule["name"],
                    "my_role_in_event": "发起者" if role_key == rule["source_role"]
                        else "决策者" if role_key == rule["decision_authority"]
                        else "被通知" if role_key in rule["notify"]
                        else "受影响",
                })

        # 找该岗位的协同连接
        outgoing = [(to, desc) for (fr, to), desc in COLLABORATION_MATRIX.items() if fr == role_key]
        incoming = [(fr, desc) for (fr, to), desc in COLLABORATION_MATRIX.items() if to == role_key]

        return {
            "role": role["name"],
            "department": role["department"],
            "can_decide": role["can_decide"],
            "cannot_decide": role["cannot_decide"],
            "receives_info": role["receives_info"],
            "involved_events": involved_events,
            "outgoing_links": [{"to": ROLES[t]["name"], "info": d} for t, d in outgoing],
            "incoming_links": [{"from": ROLES[f]["name"], "info": d} for f, d in incoming],
        }

    async def simulate_event(
        self, factory_id: str, event_key: str, context: Dict[str, Any] = {}
    ) -> Dict[str, Any]:
        """模拟事件触发：展示协同流程（谁被通知、谁决策、边界在哪）"""
        rule = EVENT_RULES.get(event_key)
        if not rule:
            return {"error": f"未知事件: {event_key}"}

        # 获取当前自动化等级
        from api.services.automation_level_service import AutomationLevelService
        lvl_svc = AutomationLevelService(self.db)

        # 映射事件到工作流
        event_to_workflow = {
            "quality_incoming_fail": "auto_iqc",
            "quality_process_fail": "escalation",
            "equipment_breakdown": "escalation",
            "material_shortage": "auto_procure",
            "delivery_risk": "delivery_ctrl",
            "urgent_order": "auto_dispatch",
            "ecn_change": "escalation",
            "shipment_ready": "delivery_ctrl",
            "supplier_delay": "auto_procure",
            "safety_incident": "escalation",
        }
        wf_key = event_to_workflow.get(event_key, "escalation")
        level = await lvl_svc.get_level(factory_id, wf_key)

        return {
            "event": rule["name"],
            "trigger": rule["trigger"],
            "context": context,
            "current_level": level,
            "flow": {
                "step1_trigger": f"{ROLES[rule['source_role']]['name']}触发: {rule['trigger']}",
                "step2_notify": [f"→ 通知{ROLES[r]['name']}" for r in rule["notify"]],
                "step3_impact": [f"→ 影响{ROLES[r]['name']}" for r in rule["impact"]],
                "step4_decision": f"→ {ROLES[rule['decision_authority']]['name']}决定: {'/'.join(rule['decision_options'])}",
                "step5_boundary": f"⚠️ 边界: {rule['boundary']}",
            },
            "auto_behavior": rule["auto_actions"].get(f"L{level}", "未定义"),
            "what_happens_now": rule["auto_actions"][f"L{level}"],
        }

    async def chatbot_rules(self) -> Dict[str, Any]:
        """给chatbot的协同规则摘要（用于system prompt或tool描述）"""
        rules_summary = []
        for key, rule in EVENT_RULES.items():
            rules_summary.append({
                "event": rule["name"],
                "who_decides": ROLES[rule["decision_authority"]]["name"],
                "who_gets_notified": [ROLES[r]["name"] for r in rule["notify"]],
                "boundary": rule["boundary"],
            })

        return {
            "principle": "信息流自动协同，决策权不跨岗",
            "chatbot_rules": [
                "1. 用户问'该谁管' → 查decision_authority",
                "2. 用户说'通知一下' → 查notify列表",
                "3. 用户说'处理一下' → 先检查用户角色权限",
                "4. 跨岗操作 → 拒绝+告知应该找谁",
                "5. 不确定 → 不执行，建议确认",
            ],
            "events": rules_summary,
            "role_permissions": {
                k: {"can": v["can_decide"], "cannot": v["cannot_decide"]}
                for k, v in ROLES.items()
            },
        }
