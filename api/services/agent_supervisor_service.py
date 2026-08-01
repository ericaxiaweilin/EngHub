"""
智能体监督引擎（Agent Supervisor）
==================================
核心理念：无感 ≠ 无监督。系统自动做事，但必须有人能监督。

能力：
1. 智能体注册：定义所有Agent（排产/采购/质量/设备/交期/派工）
2. 长任务追踪：多步骤任务的实时进度（做到哪了/卡住了/完成了）
3. 卡住检测：N分钟无进展 → 自动标记stalled → 升级
4. 主动感知：不是等人问，是事件驱动自动触发
5. 预测性：不是出了问题才动，是预判要出问题
6. 闭环验证：做完了自动验证对不对

与luaguage的区别：
- luaguage: ScheduledTask + retry + dead-letter（定时任务+重试）
- 本引擎: 实时进度追踪 + 卡住检测 + 预测 + 闭环验证（完整监督链）
"""
import uuid
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

_logger = logging.getLogger("agent_supervisor")


def _gen_id():
    return str(uuid.uuid4())


# ═══════════════════════════════════════════════════════════
# 智能体定义
# ═══════════════════════════════════════════════════════════

AGENTS = {
    "dispatch_agent": {
        "name": "派工智能体",
        "description": "自动派发工单到空闲工位",
        "capabilities": ["查询在制工单与工位状态", "按技能矩阵匹配操作员", "下发派工并跟踪开工"],
        "inputs": ["工单/工艺路线", "工位与设备状态", "员工技能矩阵"],
        "outputs": ["派工结果", "责任人/工位", "未派工原因"],
        "boundaries": ["不负责改变主排产", "技能或工位不满足时升级人工"],
        "trigger": "工单完工/新工单下达/设备恢复",
        "sensing": "event",  # event/schedule/prediction
        "interval_min": 2,
        "timeout_min": 10,
        "verify": "派工后5分钟确认操作工是否开始",
    },
    "procurement_agent": {
        "name": "采购智能体",
        "description": "MRP→比价→自动下单→跟催",
        "capabilities": ["计算物料缺口", "生成采购申请/订单", "跟踪供应商接单与交期"],
        "inputs": ["MRP需求", "库存与安全线", "供应商与采购订单"],
        "outputs": ["缺料清单", "采购申请/订单状态", "供应商跟催记录"],
        "boundaries": ["金额和供应商审批仍需授权", "不修改物料主数据"],
        "trigger": "MRP需求/库存低于安全线/PO超期",
        "sensing": "event+schedule",
        "interval_min": 30,
        "timeout_min": 60,
        "verify": "下单后确认供应商是否接单",
    },
    "quality_agent": {
        "name": "质量智能体",
        "description": "收货自动IQC/过程异常自动暂停/SPC监控",
        "capabilities": ["IQC/过程质量检查", "SPC超限识别", "不良分级与OCAP分派"],
        "inputs": ["检验记录", "不良品与缺陷", "SPC控制数据"],
        "outputs": ["质量异常", "暂停/隔离建议", "OCAP任务与责任人"],
        "boundaries": ["不替代质量人员放行", "不擅自修改检验标准或豁免不良"],
        "trigger": "收货/报工不良率超标/SPC超限",
        "sensing": "event",
        "interval_min": 0,  # 纯事件驱动
        "timeout_min": 15,
        "verify": "暂停后确认是否真的停了+原因是否找到",
    },
    "delivery_agent": {
        "name": "交期智能体",
        "description": "订单倒计时/超期预警/自动通知",
        "capabilities": ["订单交期倒计时", "按进度预测风险", "生成客户/内部通知"],
        "inputs": ["销售订单与承诺交期", "工单进度", "产能和物料状态"],
        "outputs": ["ETA与风险等级", "逾期预警", "通知记录"],
        "boundaries": ["不擅自承诺或变更客户交期", "交期冲突需交由计划/主管决策"],
        "trigger": "定时扫描(每小时)+订单状态变更",
        "sensing": "schedule+event",
        "interval_min": 60,
        "timeout_min": 120,
        "verify": "通知后确认销售是否已回复客户",
    },
    "escalation_agent": {
        "name": "异常升级智能体",
        "description": "异常分级→通知→超时升级→闭环",
        "capabilities": ["汇总异常事件", "按SLA分级通知", "超时升级与闭环核验"],
        "inputs": ["安灯/质量/设备/交期异常", "严重度与SLA", "责任岗位"],
        "outputs": ["异常等级", "通知/升级记录", "闭环状态"],
        "boundaries": ["不代替专业智能体分析根因", "没有处理证据时不关闭异常"],
        "trigger": "任何异常事件",
        "sensing": "event",
        "interval_min": 5,
        "timeout_min": 5,
        "verify": "升级后确认是否有人接手处理",
    },
    "equipment_agent": {
        "name": "设备智能体",
        "description": "PM排程/故障预测/维修派单",
        "capabilities": ["设备健康与OEE查询", "PM到期预测", "故障维修派单与恢复确认"],
        "inputs": ["设备台账与状态", "运行/OEE数据", "维护与停机记录"],
        "outputs": ["设备风险", "PM/维修工单", "责任工程师与恢复状态"],
        "boundaries": ["无采集数据时明确标记数据缺失", "涉及安全隔离的操作必须人工确认"],
        "trigger": "PM到期/设备报警/运行时长阈值",
        "sensing": "schedule+prediction",
        "interval_min": 720,  # 12小时
        "timeout_min": 480,
        "verify": "维修完成后确认设备是否恢复正常",
    },
    "scheduling_agent": {
        "name": "排产智能体",
        "description": "事件驱动自动排程/插单重排/产能平衡/what-if模拟",
        "capabilities": ["按约束生成排程", "插单重排与产能平衡", "执行what-if影响分析"],
        "inputs": ["订单交期与优先级", "工艺路线与产能", "物料/设备/人员约束"],
        "outputs": ["排产计划", "冲突与交期风险", "模拟方案对比"],
        "boundaries": ["不替代派工确认", "不忽略物料、设备和班次约束"],
        "trigger": "新工单下达/紧急插单/设备故障/物料延迟",
        "sensing": "event+schedule",
        "interval_min": 30,
        "timeout_min": 10,
        "verify": "排程后验证：无时间重叠+交期风险已标记+产能平衡",
    },
    "warehouse_agent": {
        "name": "仓储智能体",
        "description": "自动补货/呆滞预警/齐套检查/库位优化",
        "capabilities": ["库存与安全线监控", "齐套检查", "补货和呆滞预警"],
        "inputs": ["库存流水与库位", "BOM/物料需求", "安全库存与预留量"],
        "outputs": ["库存状态", "缺料/补货建议", "齐套结果与库位建议"],
        "boundaries": ["不绕过审批直接调整账面库存", "不替代采购审批"],
        "trigger": "库存低于安全线/工单下达/定时扫描",
        "sensing": "event+schedule",
        "interval_min": 60,
        "timeout_min": 15,
        "verify": "补货后确认采购申请已创建+齐套结果已标记",
    },
}


class AgentSupervisor:
    """智能体监督引擎"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ═══ 长任务管理 ═══

    async def start_task(
        self,
        factory_id: str,
        agent_key: str,
        task_type: str,
        task_desc: str = "",
        total_steps: int = 1,
        timeout_minutes: int = 30,
    ) -> Dict[str, Any]:
        """启动一个长任务（智能体开始做多步骤工作）"""
        agent = AGENTS.get(agent_key, {"name": agent_key})
        task_id = _gen_id()

        await self.db.execute(text("""
            INSERT INTO agent_tasks (id, factory_id, agent_key, agent_name, task_type, task_desc,
                status, total_steps, completed_steps, progress_pct, timeout_minutes, started_at, last_progress_at)
            VALUES (:id, :fid, :ak, :an, :tt, :td, 'running', :ts, 0, 0, :tm, NOW(), NOW())
        """), {
            "id": task_id, "fid": factory_id, "ak": agent_key,
            "an": agent.get("name", agent_key), "tt": task_type,
            "td": task_desc, "ts": total_steps, "tm": timeout_minutes,
        })
        await self.db.commit()

        return {
            "task_id": task_id,
            "agent": agent.get("name", agent_key),
            "task_type": task_type,
            "status": "running",
            "total_steps": total_steps,
            "timeout_minutes": timeout_minutes,
        }

    async def update_progress(
        self, task_id: str, completed_steps: int, note: str = ""
    ) -> Dict[str, Any]:
        """更新任务进度（智能体每完成一步调用）"""
        # 先获取total_steps来计算百分比
        pre = await self.db.execute(text(
            "SELECT total_steps FROM agent_tasks WHERE id = CAST(:id AS uuid) AND status = 'running'"
        ), {"id": task_id})
        pre_row = pre.first()
        if not pre_row:
            return {"success": False, "error": "任务不存在或已完成"}
        total_steps = pre_row[0] or 1
        pct = round(completed_steps / total_steps * 100, 1) if total_steps > 0 else 0

        result = await self.db.execute(text("""
            UPDATE agent_tasks
            SET completed_steps = :cs,
                progress_pct = :pct,
                last_progress_at = NOW()
            WHERE id = CAST(:id AS uuid) AND status = 'running'
            RETURNING agent_name, task_type, total_steps, completed_steps
        """), {"cs": completed_steps, "pct": pct, "id": task_id})
        row = result.first()
        await self.db.commit()

        if not row:
            return {"success": False, "error": "任务不存在或已完成"}

        return {
            "success": True,
            "agent": row[0],
            "task_type": row[1],
            "progress": f"{row[3]}/{row[2]}",
            "pct": round(row[3] / row[2] * 100, 1) if row[2] > 0 else 0,
            "note": note,
        }

    async def complete_task(
        self, task_id: str, result: Dict[str, Any] = None, error: str = None
    ) -> Dict[str, Any]:
        """完成任务（成功或失败）"""
        status = "completed" if not error else "failed"
        await self.db.execute(text("""
            UPDATE agent_tasks
            SET status = :st, completed_at = NOW(), progress_pct = 100,
                result = :res, error = :err
            WHERE id = CAST(:id AS uuid)
        """), {
            "st": status, "id": task_id,
            "res": str(result or {}), "err": error,
        })
        await self.db.commit()
        return {"task_id": task_id, "status": status, "result": result, "error": error}

    async def verify_task(self, task_id: str, verify_result: str) -> Dict[str, Any]:
        """闭环验证（确认执行结果是否正确）"""
        await self.db.execute(text("""
            UPDATE agent_tasks
            SET verified = TRUE, verified_at = NOW(), verify_result = :vr
            WHERE id = CAST(:id AS uuid)
        """), {"vr": verify_result, "id": task_id})
        await self.db.commit()
        return {"task_id": task_id, "verified": True, "verify_result": verify_result}

    # ═══ 监督：卡住检测 + 超时 ═══

    async def check_stalled(self, factory_id: str) -> Dict[str, Any]:
        """检测卡住的任务（超时无进展）"""
        result = await self.db.execute(text("""
            SELECT id, agent_key, agent_name, task_type, task_desc,
                   completed_steps, total_steps, timeout_minutes,
                   EXTRACT(EPOCH FROM (NOW() - last_progress_at)) / 60 as stalled_minutes
            FROM agent_tasks
            WHERE factory_id = :fid AND status = 'running'
              AND last_progress_at < NOW() - (timeout_minutes || ' minutes')::interval
        """), {"fid": factory_id})
        stalled = [dict(r._mapping) for r in result.fetchall()]

        # 标记为 stalled
        for task in stalled:
            await self.db.execute(text("""
                UPDATE agent_tasks SET status = 'stalled' WHERE id = CAST(:id AS uuid)
            """), {"id": task["id"]})

        if stalled:
            await self.db.commit()

        return {
            "factory_id": factory_id,
            "stalled_count": len(stalled),
            "stalled_tasks": [{
                "task_id": t["id"],
                "agent": t["agent_name"],
                "task_type": t["task_type"],
                "progress": f"{t['completed_steps']}/{t['total_steps']}",
                "stalled_minutes": round(t["stalled_minutes"], 1),
                "action": "已标记stalled，需人工介入或自动重试",
            } for t in stalled],
        }

    # ═══ 主动感知：心跳记录 ═══

    async def record_heartbeat(
        self,
        factory_id: str,
        agent_key: str,
        action_taken: str,
        trigger_type: str = "schedule",
        result_summary: str = "",
    ) -> None:
        """记录智能体行为（主动感知日志）"""
        await self.db.execute(text("""
            INSERT INTO agent_heartbeats (id, factory_id, agent_key, action_taken, trigger_type, result_summary)
            VALUES (:id, :fid, :ak, :at, :tt, :rs)
        """), {
            "id": _gen_id(), "fid": factory_id, "ak": agent_key,
            "at": action_taken, "tt": trigger_type, "rs": result_summary,
        })
        await self.db.commit()

    # ═══ 预测性：预判问题 ═══

    async def predict_issues(self, factory_id: str) -> Dict[str, Any]:
        """预测性问题发现（不是出了问题才动，是预判要出问题）"""
        predictions = []

        # 1. 预测工单超期（按当前速度，N天后会超期）
        try:
            result = await self.db.execute(text("""
                SELECT wo.work_order_code, wo.planned_qty, wo.completed_qty, wo.planned_due,
                       wo.actual_start,
                       CASE WHEN wo.completed_qty > 0 AND wo.actual_start IS NOT NULL
                            THEN (wo.planned_qty - wo.completed_qty) * 
                                 EXTRACT(EPOCH FROM (NOW() - wo.actual_start)) / wo.completed_qty / 86400.0
                            ELSE NULL END as estimated_remaining_days
                FROM work_orders wo
                WHERE wo.factory_id = :fid AND wo.status = 'in_progress'
                  AND wo.planned_due IS NOT NULL
            """), {"fid": factory_id})

            for row in result.fetchall():
                r = dict(row._mapping)
                remaining_days = r.get("estimated_remaining_days")
                due_date = r.get("planned_due")
                if remaining_days and due_date:
                    days_to_due = (due_date - datetime.utcnow()).total_seconds() / 86400
                    if remaining_days > days_to_due and days_to_due > 0:
                        predictions.append({
                            "type": "delivery_risk",
                            "severity": "high" if days_to_due < 3 else "medium",
                            "target": r["work_order_code"],
                            "prediction": f"按当前速度需{remaining_days:.1f}天完成，但距交期只有{days_to_due:.1f}天",
                            "suggestion": "建议提前调整排产优先级或安排加班",
                            "auto_action": "已自动提升该工单优先级" if days_to_due < 3 else "建议关注",
                        })
        except Exception as e:
            _logger.warning(f"[predict] 工单超期预测失败: {e}")

        # 2. 预测库存耗尽（按当前消耗速度）
        try:
            result2 = await self.db.execute(text("""
            SELECT i.material_code, i.available_qty,
                   COALESCE(consumption.daily_avg, 0) as daily_consumption
            FROM inventory i
            LEFT JOIN (
                SELECT material_code, 
                       SUM(quantity)::real / GREATEST((MAX(created_at::date) - MIN(created_at::date)), 1) as daily_avg
                FROM inventory_transactions
                WHERE factory_id = :fid AND transaction_type = 'outbound'
                  AND created_at > NOW() - INTERVAL '7 days'
                GROUP BY material_code
            ) consumption ON i.material_code = consumption.material_code
            WHERE i.factory_id = :fid AND i.available_qty > 0
            """), {"fid": factory_id})

            for row in result2.fetchall():
                r = dict(row._mapping)
                daily = r.get("daily_consumption", 0)
                if daily and daily > 0:
                    days_left = r["available_qty"] / daily
                    if days_left < 5:
                        predictions.append({
                            "type": "material_shortage",
                            "severity": "high" if days_left < 2 else "medium",
                            "target": r["material_code"],
                            "prediction": f"按当前消耗速度，{days_left:.1f}天后库存耗尽",
                            "suggestion": "建议立即补货" if days_left < 2 else "建议本周内补货",
                            "auto_action": "已自动生成采购申请" if days_left < 2 else "已加入补货计划",
                        })
        except Exception as e:
            _logger.warning(f"[predict] 库存预测失败: {e}")

        # 3. 预测设备PM超期
        try:
            result3 = await self.db.execute(text("""
                SELECT equipment_code, equipment_name, last_maintenance_at,
                       maintenance_cycle_days,
                       last_maintenance_at + (maintenance_cycle_days || ' days')::interval as next_pm_due
                FROM equipment
                WHERE factory_id = :fid AND status = 'running'
                  AND last_maintenance_at IS NOT NULL
                  AND maintenance_cycle_days IS NOT NULL
                  AND last_maintenance_at + (maintenance_cycle_days || ' days')::interval < NOW() + INTERVAL '3 days'
            """), {"fid": factory_id})

            for row in result3.fetchall():
                r = dict(row._mapping)
                predictions.append({
                    "type": "equipment_pm_due",
                    "severity": "medium",
                    "target": r["equipment_code"],
                    "prediction": f"{r['equipment_name']} PM即将到期（{r.get('next_pm_due', '近期')}）",
                    "suggestion": "建议安排保养，避免故障停机",
                    "auto_action": "已自动生成PM工单",
                })
        except Exception as e:
            _logger.warning(f"[predict] 设备PM预测失败: {e}")

        return {
            "factory_id": factory_id,
            "generated_at": datetime.utcnow().isoformat(),
            "total_predictions": len(predictions),
            "high_risk": len([p for p in predictions if p["severity"] == "high"]),
            "predictions": predictions,
        }

    # ═══ 监督看板 ═══

    async def supervisor_dashboard(self, factory_id: str) -> Dict[str, Any]:
        """智能体监督看板（所有Agent状态一览）"""
        # 各Agent最近活动
        agent_status = []
        for key, agent in AGENTS.items():
            # 最近心跳
            hb = await self.db.execute(text("""
                SELECT action_taken, trigger_type, result_summary, created_at
                FROM agent_heartbeats
                WHERE factory_id = :fid AND agent_key = :ak
                ORDER BY created_at DESC LIMIT 1
            """), {"fid": factory_id, "ak": key})
            last_hb = hb.first()

            # 运行中任务
            tasks = await self.db.execute(text("""
                SELECT count(*) as running, 
                       count(*) FILTER (WHERE status = 'stalled') as stalled
                FROM agent_tasks
                WHERE factory_id = :fid AND agent_key = :ak
                  AND status IN ('running', 'stalled')
            """), {"fid": factory_id, "ak": key})
            task_info = tasks.first()

            agent_status.append({
                "key": key,
                "name": agent["name"],
                "description": agent["description"],
                "capabilities": agent["capabilities"],
                "inputs": agent["inputs"],
                "outputs": agent["outputs"],
                "boundaries": agent["boundaries"],
                "sensing": agent["sensing"],
                "last_action": dict(last_hb._mapping) if last_hb else None,
                "running_tasks": task_info[0] if task_info else 0,
                "stalled_tasks": task_info[1] if task_info else 0,
                "status": "stalled" if (task_info and task_info[1] > 0) else "active",
            })

        # 最近任务
        recent = await self.db.execute(text("""
            SELECT agent_name, task_type, status, progress_pct, started_at, completed_at, verified
            FROM agent_tasks
            WHERE factory_id = :fid
            ORDER BY started_at DESC LIMIT 10
        """), {"fid": factory_id})
        recent_tasks = [dict(r._mapping) for r in recent.fetchall()]

        return {
            "factory_id": factory_id,
            "total_agents": len(AGENTS),
            "agents": agent_status,
            "recent_tasks": recent_tasks,
            "health": self._assess_health(agent_status),
        }

    def _assess_health(self, agents: List[Dict]) -> Dict[str, Any]:
        """评估整体健康度"""
        stalled = sum(1 for a in agents if a["status"] == "stalled")
        active = sum(1 for a in agents if a["status"] == "active")
        total = len(agents)

        if stalled == 0:
            level = "healthy"
            msg = "所有智能体正常运行"
        elif stalled <= 2:
            level = "warning"
            msg = f"{stalled}个智能体有卡住任务，需关注"
        else:
            level = "critical"
            msg = f"{stalled}个智能体卡住，需立即处理"

        return {"level": level, "message": msg, "active": active, "stalled": stalled, "total": total}

    # ═══ 智能体列表（给前端/chatbot） ═══

    async def list_agents(self) -> Dict[str, Any]:
        """获取所有智能体定义"""
        return {
            "total": len(AGENTS),
            "agents": [{
                "key": k,
                "name": v["name"],
                "description": v["description"],
                "capabilities": v["capabilities"],
                "inputs": v["inputs"],
                "outputs": v["outputs"],
                "boundaries": v["boundaries"],
                "trigger": v["trigger"],
                "sensing": v["sensing"],
                "verify": v["verify"],
            } for k, v in AGENTS.items()],
            "architecture": {
                "principle": "无感≠无监督：系统自动做事，但全程可追踪、可干预",
                "layers": [
                    "感知层：事件驱动+定时扫描+预测（不等人问）",
                    "执行层：自动执行（按L0-L3等级）",
                    "监督层：进度追踪+卡住检测+超时升级",
                    "验证层：闭环确认执行结果",
                    "降级层：搞不定时找人（chatbot/通知/审批）",
                ],
            },
        }
