"""
订单跟踪自动化服务 - 岗位替代: 完全消除跟单文员/销售文员

跟单文员的真实工作：
1. 客户/销售问"我的订单到哪了" → 查系统 → 回复
2. 订单状态变了 → 通知客户/销售
3. 交期要到了 → 提醒
4. 客户问"什么时候能交货" → 查排产 → 回复

系统替代（0人）：
1. 订单进度自动查询：输入订单号 → 返回完整进度链（下单→排产→生产→入库→发货）
2. 状态变更自动通知：工单完工 → 自动通知关联销售订单负责人
3. 交期预警：订单可能延期 → 自动通知
4. 交期自动回复：已有 delivery-promise 端点
"""
import uuid
import logging
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

_logger = logging.getLogger("order_tracking")


def _gen_id():
    return str(uuid.uuid4())


class OrderTrackingService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ==================== 订单进度自动查询 ====================

    async def track_order(self, factory_id: str, order_code: str) -> Dict[str, Any]:
        """订单全链路进度追踪（替代跟单员查系统→回复客户）。

        输入：销售订单号/客户订单号
        输出：完整进度链（下单→排产→各工序→入库→发货）
        """
        # 查找销售订单
        so_result = await self.db.execute(text("""
            SELECT id, order_code, customer_name, product_id, quantity,
                   status, order_date, required_date, created_at
            FROM sales_orders
            WHERE factory_id = :fid AND (order_code = :code OR id = :code)
        """), {"fid": factory_id, "code": order_code})
        so = so_result.mappings().first()

        if not so:
            return {"found": False, "error": f"订单 {order_code} 不存在"}

        # 查找关联工单
        wo_result = await self.db.execute(text("""
            SELECT work_order_code, status, planned_qty, completed_qty, good_qty,
                   defect_qty, work_center, planned_start, planned_due, actual_complete
            FROM work_orders
            WHERE factory_id = :fid AND sales_order_id = :so_id
            ORDER BY created_at ASC
        """), {"fid": factory_id, "so_id": so["id"]})
        work_orders = [dict(r) for r in wo_result.mappings().all()]

        # 构建进度链
        progress_chain = []
        total_qty = so["quantity"] or 0
        total_completed = sum(wo.get("completed_qty", 0) or 0 for wo in work_orders)
        total_good = sum(wo.get("good_qty", 0) or 0 for wo in work_orders)

        # 阶段判断
        if not work_orders:
            current_stage = "待排产"
            progress_pct = 10
        else:
            statuses = [wo["status"] for wo in work_orders]
            if all(s in ("completed", "closed") for s in statuses):
                current_stage = "已完工"
                progress_pct = 100
            elif any(s == "in_progress" for s in statuses):
                current_stage = "生产中"
                progress_pct = min(90, int(total_completed / max(total_qty, 1) * 100))
            elif any(s == "released" for s in statuses):
                current_stage = "已下达"
                progress_pct = 20
            else:
                current_stage = "待下达"
                progress_pct = 15

        for wo in work_orders:
            progress_chain.append({
                "work_order_code": wo["work_order_code"],
                "stage": wo.get("work_center", ""),
                "status": wo["status"],
                "progress": f"{wo.get('completed_qty', 0)}/{wo.get('planned_qty', 0)}",
                "good_qty": wo.get("good_qty", 0),
                "planned_due": str(wo.get("planned_due", ""))[:10] if wo.get("planned_due") else None,
            })

        # 交期判断
        required_date = so.get("required_date")
        delivery_risk = None
        if required_date and current_stage != "已完工":
            if isinstance(required_date, str):
                required_date = date.fromisoformat(required_date[:10])
            days_left = (required_date - date.today()).days
            if days_left < 0:
                delivery_risk = f"已超期 {-days_left} 天"
            elif days_left <= 3 and progress_pct < 80:
                delivery_risk = f"交期风险：仅剩 {days_left} 天，进度 {progress_pct}%"

        return {
            "found": True,
            "order_code": so["order_code"],
            "customer": so.get("customer_name", ""),
            "product": so.get("product_id", ""),
            "quantity": total_qty,
            "order_date": str(so.get("order_date", ""))[:10],
            "required_date": str(required_date) if required_date else None,
            "current_stage": current_stage,
            "progress_pct": progress_pct,
            "total_completed": total_completed,
            "total_good": total_good,
            "yield_rate": round(total_good / max(total_completed, 1) * 100, 1),
            "work_orders": progress_chain,
            "delivery_risk": delivery_risk,
            "summary": f"订单 {so['order_code']}：{current_stage}，进度 {progress_pct}%，"
                       f"完成 {total_completed}/{total_qty}" + (f"，⚠️ {delivery_risk}" if delivery_risk else ""),
        }

    # ==================== 状态变更自动通知 ====================

    async def notify_status_change(self, factory_id: str, work_order_id: str,
                                    new_status: str, operator: str = "system") -> Dict[str, Any]:
        """工单状态变更 → 自动通知关联销售订单负责人。

        跟单文员消除逻辑：不需要人盯着看工单变了然后去通知客户/销售。
        """
        # 查找工单关联的销售订单
        wo_result = await self.db.execute(text("""
            SELECT wo.work_order_code, wo.sales_order_id, wo.completed_qty, wo.planned_qty,
                   so.order_code, so.customer_name
            FROM work_orders wo
            LEFT JOIN sales_orders so ON so.id = wo.sales_order_id
            WHERE wo.id = :wo_id
        """), {"wo_id": work_order_id})
        row = wo_result.mappings().first()

        if not row or not row.get("order_code"):
            return {"notified": False, "reason": "无关联销售订单"}

        # 生成通知
        status_map = {
            "released": "已下达车间",
            "in_progress": "已开始生产",
            "completed": "已完工",
            "paused": "已暂停",
        }
        status_text = status_map.get(new_status, new_status)

        from database.models import Notification
        notif = Notification(
            id=_gen_id(),
            factory_id=factory_id,
            category="order",
            title=f"📦 订单进度：{row['order_code']} → {status_text}",
            content=f"客户 {row.get('customer_name', '')} 的订单 {row['order_code']}，"
                    f"工单 {row['work_order_code']} 状态变更为「{status_text}」"
                    f"（{row.get('completed_qty', 0)}/{row.get('planned_qty', 0)}）",
            severity="info",
            source_type="sales_order",
            source_id=row.get("sales_order_id", ""),
        )
        self.db.add(notif)
        await self.db.commit()

        return {"notified": True, "order_code": row["order_code"], "status": status_text}

    # ==================== 交期预警自动扫描 ====================

    async def delivery_alert_scan(self, factory_id: str) -> Dict[str, Any]:
        """自动扫描即将超期的订单，生成预警通知。

        跟单文员消除逻辑：不需要人记着哪个单快到期了，系统自动扫。
        """
        # 查找未完成且交期在3天内的销售订单
        result = await self.db.execute(text("""
            SELECT so.id, so.order_code, so.customer_name, so.required_date,
                   COALESCE(SUM(wo.completed_qty), 0) as total_completed,
                   COALESCE(SUM(wo.planned_qty), 0) as total_planned
            FROM sales_orders so
            LEFT JOIN work_orders wo ON wo.sales_order_id = so.id AND wo.factory_id = :fid
            WHERE so.factory_id = :fid
              AND so.status NOT IN ('completed', 'cancelled', 'closed')
              AND so.required_date IS NOT NULL
              AND so.required_date <= CURRENT_DATE + INTERVAL '3 days'
            GROUP BY so.id, so.order_code, so.customer_name, so.required_date
            ORDER BY so.required_date ASC
        """), {"fid": factory_id})
        at_risk = [dict(r) for r in result.mappings().all()]

        alerts = []
        for order in at_risk:
            required = order["required_date"]
            if isinstance(required, str):
                required = date.fromisoformat(required[:10])
            days_left = (required - date.today()).days
            completed = order["total_completed"] or 0
            planned = order["total_planned"] or 0
            progress = round(completed / max(planned, 1) * 100)

            severity = "critical" if days_left <= 0 else "warning"
            alerts.append({
                "order_code": order["order_code"],
                "customer": order.get("customer_name", ""),
                "required_date": str(required),
                "days_left": days_left,
                "progress_pct": progress,
                "severity": severity,
            })

            # 写入通知
            from database.models import Notification
            notif = Notification(
                id=_gen_id(),
                factory_id=factory_id,
                category="anomaly",
                title=f"{'🚨' if days_left <= 0 else '⚠️'} 交期预警：{order['order_code']} "
                      f"{'已超期' if days_left <= 0 else f'仅剩{days_left}天'}",
                content=f"客户 {order.get('customer_name', '')}，进度 {progress}%，"
                        f"要求交期 {required}",
                severity=severity,
                source_type="sales_order",
                source_id=order["id"],
            )
            self.db.add(notif)

        if alerts:
            await self.db.commit()

        return {
            "scanned_at": datetime.utcnow().isoformat(),
            "at_risk_count": len(alerts),
            "alerts": alerts,
        }
