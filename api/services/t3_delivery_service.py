"""
T+3 交期管控服务 - 参照美的模式
================================
美的T+3：下单3天 + 备料3天 + 生产3天 + 发货3天 = 12天交付
核心：每个环节有倒计时，超期自动升级，不需要人盯。

本服务实现：
1. 订单交期倒计时（距交期还有几天 → 红黄绿灯）
2. 工单进度实时监控（按工位/部门/全厂三级）
3. 超期自动预警+升级（不需要调度员/跟单员盯）
4. T+3环节追踪（每张订单在哪个阶段）
"""
import logging
from datetime import datetime, date, timedelta
from typing import Dict, Any, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

_logger = logging.getLogger("t3_delivery")


class T3DeliveryService:
    """T+3交期管控"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def delivery_countdown(self, factory_id: str) -> Dict[str, Any]:
        """订单交期倒计时（红黄绿灯）

        绿灯: >7天
        黄灯: 3-7天
        红灯: <3天或已超期
        """
        orders = await self._query("""
            SELECT so.id, so.order_code, so.customer_name, so.product_name,
                   so.quantity, so.delivery_date, so.status, so.priority,
                   count(wo.id) as wo_count,
                   sum(wo.planned_qty) as wo_planned,
                   sum(wo.completed_qty) as wo_done
            FROM sales_orders so
            LEFT JOIN work_orders wo ON wo.sales_order_id = so.id AND wo.factory_id = so.factory_id
            WHERE so.factory_id = :fid AND so.status NOT IN ('shipped', 'cancelled')
            GROUP BY so.id, so.order_code, so.customer_name, so.product_name,
                     so.quantity, so.delivery_date, so.status, so.priority
            ORDER BY so.delivery_date
        """, {"fid": factory_id})

        today = date.today()
        result = []
        red_count = 0
        yellow_count = 0
        green_count = 0

        for o in orders:
            delivery = o.get("delivery_date")
            if not delivery:
                continue
            if isinstance(delivery, datetime):
                delivery = delivery.date()
            days_left = (delivery - today).days
            progress = round((o.get("wo_done") or 0) / max(o.get("wo_planned") or o.get("quantity") or 1, 1) * 100, 1)

            if days_left < 0:
                light = "red"
                status_text = f"超期{-days_left}天"
                red_count += 1
            elif days_left <= 3:
                light = "red"
                status_text = f"仅剩{days_left}天"
                red_count += 1
            elif days_left <= 7:
                light = "yellow"
                status_text = f"剩{days_left}天"
                yellow_count += 1
            else:
                light = "green"
                status_text = f"剩{days_left}天"
                green_count += 1

            # T+3阶段判断
            t3_stage = self._get_t3_stage(o, progress)

            result.append({
                "order_code": o["order_code"],
                "customer": o["customer_name"],
                "product": o["product_name"],
                "quantity": o["quantity"],
                "delivery_date": str(delivery),
                "days_left": days_left,
                "light": light,
                "status_text": status_text,
                "progress_pct": progress,
                "t3_stage": t3_stage,
                "priority": o.get("priority"),
                "wo_count": o.get("wo_count", 0),
            })

        return {
            "factory_id": factory_id,
            "generated_at": datetime.now().isoformat(),
            "summary": {
                "total_active_orders": len(result),
                "red": red_count,
                "yellow": yellow_count,
                "green": green_count,
                "on_time_rate": round(green_count / max(len(result), 1) * 100, 1),
            },
            "orders": result,
        }

    async def realtime_progress(self, factory_id: str) -> Dict[str, Any]:
        """实时进度看板（工位→部门→全厂 三级）

        美的模式：每条产线的产量/进度/良率实时可见
        """
        # 按工位
        by_station = await self._query("""
            SELECT st.station_code, st.station_name,
                   count(wo.id) as wo_count,
                   sum(wo.planned_qty) as planned,
                   sum(wo.completed_qty) as done,
                   sum(wo.defect_qty) as defects,
                   sum(CASE WHEN wo.status = 'in_progress' THEN 1 ELSE 0 END) as active_wo
            FROM work_orders wo
            JOIN stations st ON wo.assigned_station_id = st.id::text
            WHERE wo.factory_id = :fid AND wo.status IN ('released', 'in_progress')
            GROUP BY st.station_code, st.station_name
            ORDER BY active_wo DESC
        """, {"fid": factory_id})

        # 按部门（从stations的department字段或工位的station_type推断）
        by_dept = await self._query("""
            SELECT
                CASE
                    WHEN st.station_code LIKE 'ST-JJG%' OR st.station_code LIKE 'ST-GL%'
                         OR st.station_code LIKE 'ST-ZS%' OR st.station_code LIKE 'ST-JS%'
                    THEN '关键零件一部'
                    WHEN st.station_code LIKE 'ST-JG%' OR st.station_code LIKE 'ST-HJ%'
                         OR st.station_code LIKE 'ST-TZ%' OR st.station_code LIKE 'ST-ZL%'
                    THEN '生产一部'
                    WHEN st.station_code LIKE 'ST-XC%' OR st.station_code LIKE 'ST-YB%'
                         OR st.station_code LIKE 'ST-JD%'
                    THEN '生产二部'
                    WHEN st.station_code LIKE 'ST-QC%' THEN '品质部'
                    WHEN st.station_code LIKE 'ST-PK%' THEN '物流部'
                    ELSE '其他'
                END as department,
                count(wo.id) as wo_count,
                sum(wo.planned_qty) as planned,
                sum(wo.completed_qty) as done,
                sum(wo.defect_qty) as defects
            FROM work_orders wo
            JOIN stations st ON wo.assigned_station_id = st.id::text
            WHERE wo.factory_id = :fid AND wo.status IN ('released', 'in_progress')
            GROUP BY 1
            ORDER BY wo_count DESC
        """, {"fid": factory_id})

        # 全厂汇总
        total = await self._query("""
            SELECT count(*) as total_wo,
                   sum(planned_qty) as total_planned,
                   sum(completed_qty) as total_done,
                   sum(defect_qty) as total_defects,
                   sum(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END) as in_progress,
                   sum(CASE WHEN status = 'released' THEN 1 ELSE 0 END) as waiting
            FROM work_orders
            WHERE factory_id = :fid AND status IN ('released', 'in_progress')
        """, {"fid": factory_id})

        t = total[0] if total else {}
        total_planned = t.get("total_planned") or 0
        total_done = t.get("total_done") or 0
        total_defects = t.get("total_defects") or 0

        # 加工各工位的完成率
        for s in by_station:
            planned = s.get("planned") or 0
            done = s.get("done") or 0
            defects = s.get("defects") or 0
            s["completion_pct"] = round(done / max(planned, 1) * 100, 1)
            s["defect_rate"] = round(defects / max(done, 1) * 100, 2)

        for d in by_dept:
            planned = d.get("planned") or 0
            done = d.get("done") or 0
            defects = d.get("defects") or 0
            d["completion_pct"] = round(done / max(planned, 1) * 100, 1)
            d["defect_rate"] = round(defects / max(done, 1) * 100, 2)

        return {
            "factory_id": factory_id,
            "generated_at": datetime.now().isoformat(),
            "factory_summary": {
                "total_active_wo": t.get("total_wo", 0),
                "in_progress": t.get("in_progress", 0),
                "waiting": t.get("waiting", 0),
                "total_planned": total_planned,
                "total_done": total_done,
                "completion_pct": round(total_done / max(total_planned, 1) * 100, 1),
                "defect_rate": round(total_defects / max(total_done, 1) * 100, 2),
            },
            "by_department": by_dept,
            "by_station": by_station,
        }

    async def overdue_alerts(self, factory_id: str) -> Dict[str, Any]:
        """超期自动预警（不需要调度员/跟单员盯）

        扫描：
        1. 工单超期未完工
        2. 采购超期未到货
        3. 订单即将超期
        """
        # 工单超期
        wo_overdue = await self._query("""
            SELECT wo.work_order_code, wo.product_id, wo.planned_qty, wo.completed_qty,
                   wo.status, wo.planned_due, st.station_name
            FROM work_orders wo
            LEFT JOIN stations st ON wo.assigned_station_id = st.id::text
            WHERE wo.factory_id = :fid
              AND wo.status IN ('released', 'in_progress')
              AND wo.planned_due < NOW()
            ORDER BY wo.planned_due
        """, {"fid": factory_id})

        # 采购超期
        po_overdue = await self._query("""
            SELECT po_code, supplier_name, material_code, qty, expected_date, status
            FROM purchase_orders
            WHERE factory_id = :fid
              AND status NOT IN ('received', 'cancelled')
              AND expected_date < CURRENT_DATE
            ORDER BY expected_date
        """, {"fid": factory_id})

        # 订单3天内到期
        so_urgent = await self._query("""
            SELECT order_code, customer_name, product_name, quantity, delivery_date, status
            FROM sales_orders
            WHERE factory_id = :fid
              AND status NOT IN ('shipped', 'cancelled', 'completed')
              AND delivery_date <= CURRENT_DATE + INTERVAL '3 days'
            ORDER BY delivery_date
        """, {"fid": factory_id})

        total_alerts = len(wo_overdue) + len(po_overdue) + len(so_urgent)

        return {
            "factory_id": factory_id,
            "generated_at": datetime.now().isoformat(),
            "total_alerts": total_alerts,
            "alerts": {
                "工单超期": {
                    "count": len(wo_overdue),
                    "action": "自动升级到车间主任（异常引擎已处理）",
                    "records": wo_overdue[:10],
                },
                "采购超期未到货": {
                    "count": len(po_overdue),
                    "action": "自动跟催供应商+升级采购主管",
                    "records": po_overdue[:10],
                },
                "订单3天内到期": {
                    "count": len(so_urgent),
                    "action": "自动通知销售+PMC优先排产",
                    "records": so_urgent[:10],
                },
            },
            "auto_actions": [
                "工单超期 → 异常引擎自动升级（5分钟→班组长→主管）",
                "采购超期 → 自动跟催+供应商评分扣分",
                "订单到期 → 自动通知销售+调整排产优先级",
            ],
        }

    def _get_t3_stage(self, order: dict, progress: float) -> str:
        """判断订单在T+3哪个阶段"""
        status = order.get("status", "")
        if status == "pending":
            return "T0-订单确认"
        elif status == "confirmed":
            return "T1-备料中"
        elif status == "in_production":
            if progress < 50:
                return "T2-生产中(前半)"
            else:
                return "T2-生产中(后半)"
        elif status == "completed":
            return "T3-待发运"
        else:
            return "T0-订单确认"

    async def _query(self, sql: str, params: dict) -> List[Dict]:
        result = await self.db.execute(text(sql), params)
        rows = result.fetchall()
        cols = result.keys()
        return [dict(zip(cols, row)) for row in rows]
