"""
异常处理引擎 - 岗位消除后的安全网

核心逻辑：取消人 ≠ 取消异常处理能力
- 文员不只是录入，她还在拦截错误、发现异常、协调处理
- 系统替代后，异常必须有明确的处理流程和升级路径

三级处理：
1. 自动拦截（系统能判断）：直接拒绝 + 提示修正
2. 自动升级（系统不能判断）：通知有权处理的人
3. 超时再升级：N分钟未处理 → 自动升级到上一级

升级路径：操作工 → 班组长 → 主管 → 经理
超时规则：
- critical: 5分钟未处理 → 升级
- warning: 30分钟未处理 → 升级
- info: 不升级（记录即可）
"""
import uuid
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

_logger = logging.getLogger("exception_engine")


def _gen_id():
    return str(uuid.uuid4())


# ==================== 异常场景定义 ====================
# 每个被消除岗位的异常场景 + 标准处理流程

EXCEPTION_SCENARIOS = {
    # --- 生产文员消除后的异常 ---
    "report_qty_overflow": {
        "name": "报工数量超限",
        "source_role": "生产文员",
        "severity": "warning",
        "auto_action": "reject",  # 系统直接拒绝
        "handler_sop": "操作工确认数量是否正确；若确实超量（如补报），班组长审批后放行",
        "escalate_to": "team_leader",
        "escalate_minutes": 30,
    },
    "report_wrong_wo": {
        "name": "报工工单号错误/不存在",
        "source_role": "生产文员",
        "severity": "info",
        "auto_action": "reject",
        "handler_sop": "操作工重新扫码；若条码损坏，班组长手动输入工单号",
        "escalate_to": None,  # 不升级，操作工自行修正
    },
    "report_high_defect": {
        "name": "报工不良率异常（>20%）",
        "source_role": "生产文员",
        "severity": "critical",
        "auto_action": "notify",  # 不拒绝，但立即通知
        "handler_sop": "主管10分钟内到现场确认：1)是否批量问题 2)是否停机 3)是否误报",
        "escalate_to": "supervisor",
        "escalate_minutes": 5,
    },
    "report_zero_output": {
        "name": "连续2小时零报工",
        "source_role": "生产文员",
        "severity": "warning",
        "auto_action": "notify",
        "handler_sop": "班组长确认：1)是否换线 2)是否设备故障 3)是否缺料停线",
        "escalate_to": "team_leader",
        "escalate_minutes": 30,
    },
    "report_duplicate": {
        "name": "重复报工（同工单同班次短时间多次）",
        "source_role": "生产文员",
        "severity": "warning",
        "auto_action": "flag",  # 标记可疑，不拒绝
        "handler_sop": "班组长确认是否误操作；若重复则撤回",
        "escalate_to": "team_leader",
        "escalate_minutes": 60,
    },

    # --- 跟单文员消除后的异常 ---
    "order_delivery_risk": {
        "name": "订单交期风险（进度落后）",
        "source_role": "跟单文员",
        "severity": "warning",
        "auto_action": "notify",
        "handler_sop": "计划员评估：1)能否加班赶工 2)能否调整排产 3)是否需通知客户延期",
        "escalate_to": "planner",
        "escalate_minutes": 60,
    },
    "order_overdue": {
        "name": "订单已超期",
        "source_role": "跟单文员",
        "severity": "critical",
        "auto_action": "notify",
        "handler_sop": "主管立即处理：1)确认原因 2)与客户沟通 3)制定赶工计划",
        "escalate_to": "supervisor",
        "escalate_minutes": 5,
    },
    "order_change_request": {
        "name": "客户改单/加单",
        "source_role": "跟单文员",
        "severity": "critical",
        "auto_action": "notify",
        "handler_sop": "计划员评估影响 → 主管审批 → 调整排产 → 回复客户新交期",
        "escalate_to": "planner",
        "escalate_minutes": 15,
    },

    # --- 采购文员消除后的异常 ---
    "purchase_no_supplier": {
        "name": "无合格供应商（MRP触发但无比价）",
        "source_role": "采购员",
        "severity": "critical",
        "auto_action": "notify",
        "handler_sop": "采购主管：1)寻找新供应商 2)确认替代料 3)评估停产风险",
        "escalate_to": "supervisor",
        "escalate_minutes": 15,
    },
    "purchase_overdue": {
        "name": "采购订单超期未到货",
        "source_role": "采购员",
        "severity": "warning",
        "auto_action": "notify",
        "handler_sop": "系统自动发催货通知；超3天未响应 → 采购主管介入",
        "escalate_to": "supervisor",
        "escalate_minutes": 60,
    },
    "purchase_price_anomaly": {
        "name": "供应商报价异常（涨幅>30%）",
        "source_role": "采购员",
        "severity": "warning",
        "auto_action": "hold",  # 暂停自动下单
        "handler_sop": "采购主管确认：1)是否市场涨价 2)是否规格变更 3)是否需换源",
        "escalate_to": "supervisor",
        "escalate_minutes": 30,
    },

    # --- 设备相关异常 ---
    "equipment_down": {
        "name": "设备故障停机",
        "source_role": "调度员",
        "severity": "critical",
        "auto_action": "reschedule",  # 自动重排受影响工单
        "handler_sop": "系统自动：释放工单→重派到其他工位。维修工接单→现场修复",
        "escalate_to": "maintenance",
        "escalate_minutes": 5,
    },
    "equipment_pm_overdue": {
        "name": "设备保养超期未执行",
        "source_role": "设备维护员",
        "severity": "warning",
        "auto_action": "notify",
        "handler_sop": "维护主管安排补保养；超7天 → 经理审批是否停机保养",
        "escalate_to": "supervisor",
        "escalate_minutes": 120,
    },
}


class ExceptionEngine:
    """异常处理引擎"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def raise_exception(
        self,
        factory_id: str,
        scenario_key: str,
        context: Dict[str, Any],
        source_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """触发异常事件。

        根据场景定义自动：
        1. 判断严重度
        2. 执行自动动作（reject/notify/hold/reschedule）
        3. 确定升级路径
        4. 写入异常记录 + 通知
        """
        scenario = EXCEPTION_SCENARIOS.get(scenario_key)
        if not scenario:
            scenario = {
                "name": scenario_key,
                "source_role": "unknown",
                "severity": "warning",
                "auto_action": "notify",
                "handler_sop": "请相关人员处理",
                "escalate_to": "supervisor",
                "escalate_minutes": 30,
            }

        exception_id = _gen_id()
        severity = scenario["severity"]
        auto_action = scenario["auto_action"]

        # 写入异常记录
        await self.db.execute(text("""
            INSERT INTO notifications
            (id, factory_id, recipient, category, title, content, severity,
             source_type, source_id, is_read, created_at)
            VALUES (:id, :fid, :recipient, 'exception', :title, :content, :sev,
                    :src_type, :src_id, FALSE, NOW())
        """), {
            "id": exception_id,
            "fid": factory_id,
            "recipient": scenario.get("escalate_to"),  # 定向通知
            "title": f"{'🚨' if severity == 'critical' else '⚠️'} {scenario['name']}",
            "content": self._format_context(scenario, context),
            "sev": severity,
            "src_type": scenario.get("source_role", ""),
            "src_id": source_id or "",
        })
        await self.db.commit()

        return {
            "exception_id": exception_id,
            "scenario": scenario_key,
            "severity": severity,
            "auto_action": auto_action,
            "handler_sop": scenario["handler_sop"],
            "escalate_to": scenario.get("escalate_to"),
            "escalate_minutes": scenario.get("escalate_minutes"),
            "message": f"异常已触发：{scenario['name']}，"
                       f"自动动作={auto_action}，"
                       f"升级对象={scenario.get('escalate_to', '无')}",
        }

    def _format_context(self, scenario: Dict, context: Dict) -> str:
        """格式化异常上下文为可读文本"""
        lines = [f"【{scenario['name']}】"]
        lines.append(f"处理SOP：{scenario['handler_sop']}")
        lines.append("---")
        for k, v in context.items():
            lines.append(f"  {k}: {v}")
        lines.append(f"触发时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        return "\n".join(lines)

    # ==================== 超时升级扫描 ====================

    async def check_escalation(self, factory_id: str) -> Dict[str, Any]:
        """扫描超时未处理的异常，自动升级。

        规则：
        - critical: 5分钟未读 → 升级到 supervisor
        - warning: 30分钟未读 → 升级到 supervisor
        - 已升级仍超时 → 升级到 manager
        """
        # 查找未读异常通知
        result = await self.db.execute(text("""
            SELECT id, title, content, severity, recipient, created_at,
                   EXTRACT(EPOCH FROM (NOW() - created_at))/60 as minutes_elapsed
            FROM notifications
            WHERE factory_id = :fid AND category = 'exception' AND is_read = FALSE
            ORDER BY created_at ASC
        """), {"fid": factory_id})
        pending = [dict(r) for r in result.mappings().all()]

        escalated = []
        for item in pending:
            minutes = float(item["minutes_elapsed"] or 0)
            threshold = 5 if item["severity"] == "critical" else 30

            if minutes > threshold:
                # 升级：创建新通知给更高级别
                new_recipient = "manager" if item["recipient"] == "supervisor" else "supervisor"
                esc_id = _gen_id()
                await self.db.execute(text("""
                    INSERT INTO notifications
                    (id, factory_id, recipient, category, title, content, severity,
                     source_type, source_id, is_read, created_at)
                    VALUES (:id, :fid, :rcpt, 'exception', :title, :content, 'critical',
                            'escalation', :orig_id, FALSE, NOW())
                """), {
                    "id": esc_id,
                    "fid": factory_id,
                    "rcpt": new_recipient,
                    "title": f"⬆️ 升级：{item['title']}（{int(minutes)}分钟未处理）",
                    "content": f"原异常超时未处理，自动升级。\n原通知: {item['title']}\n"
                               f"已等待 {int(minutes)} 分钟（阈值 {threshold} 分钟）\n"
                               f"原处理人: {item['recipient']}",
                    "orig_id": item["id"],
                })
                escalated.append({
                    "original_title": item["title"],
                    "minutes_elapsed": int(minutes),
                    "escalated_to": new_recipient,
                })

        if escalated:
            await self.db.commit()

        return {
            "pending_count": len(pending),
            "escalated_count": len(escalated),
            "escalated": escalated,
        }

    # ==================== 异常统计 ====================

    async def exception_dashboard(self, factory_id: str) -> Dict[str, Any]:
        """异常看板：当前未处理异常 + 历史统计"""
        # 未处理
        pending_result = await self.db.execute(text("""
            SELECT severity, COUNT(*) as cnt
            FROM notifications
            WHERE factory_id = :fid AND category = 'exception' AND is_read = FALSE
            GROUP BY severity
        """), {"fid": factory_id})
        pending = {r["severity"]: r["cnt"] for r in pending_result.mappings().all()}

        # 今日已处理
        resolved_result = await self.db.execute(text("""
            SELECT COUNT(*) as cnt FROM notifications
            WHERE factory_id = :fid AND category = 'exception' AND is_read = TRUE
              AND created_at >= CURRENT_DATE
        """), {"fid": factory_id})
        resolved_today = resolved_result.scalar() or 0

        # 最近异常
        recent_result = await self.db.execute(text("""
            SELECT title, severity, is_read, created_at
            FROM notifications
            WHERE factory_id = :fid AND category = 'exception'
            ORDER BY created_at DESC LIMIT 10
        """), {"fid": factory_id})
        recent = [dict(r) for r in recent_result.mappings().all()]

        return {
            "pending": pending,
            "pending_total": sum(pending.values()),
            "resolved_today": resolved_today,
            "recent": recent,
        }
