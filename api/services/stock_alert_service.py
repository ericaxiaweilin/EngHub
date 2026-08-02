"""
库存预警服务 - 岗位替代 Phase 3
安全库存预警 / 呆滞料检测 / 超储预警
"""
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, text

from database.models import Inventory


def _gen_id() -> str:
    return str(uuid.uuid4())


class StockAlertService:
    """库存预警引擎"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def run_alert_check(self, factory_id: str) -> Dict[str, Any]:
        """
        执行库存预警检查
        1. 低于安全库存
        2. 超过最大库存
        3. 呆滞料（N天无动销）
        """
        now = datetime.utcnow()
        alerts_created = 0
        alert_details = []

        # 获取安全库存配置
        config_result = await self.db.execute(text(
            "SELECT * FROM safety_stock_config WHERE factory_id = :fid AND is_active = TRUE"
        ), {"fid": factory_id})
        configs = {r["material_id"]: dict(r) for r in config_result.mappings().all()}

        # 获取所有库存
        inv_stmt = select(Inventory).where(
            and_(Inventory.factory_id == factory_id, Inventory.total_qty >= 0)
        )
        inv_result = await self.db.execute(inv_stmt)
        inventories = inv_result.scalars().all()

        # 按物料汇总
        material_stock: Dict[str, Dict] = {}
        for inv in inventories:
            mid = inv.material_id
            if mid not in material_stock:
                material_stock[mid] = {
                    "material_id": mid,
                    "material_code": inv.material_code,
                    "material_name": inv.material_name or inv.material_code,
                    "total_qty": 0,
                    "last_movement": None,
                }
            material_stock[mid]["total_qty"] += inv.total_qty
            if inv.last_movement_at:
                if not material_stock[mid]["last_movement"] or inv.last_movement_at > material_stock[mid]["last_movement"]:
                    material_stock[mid]["last_movement"] = inv.last_movement_at

        # 检查每个物料
        for mid, stock in material_stock.items():
            config = configs.get(mid)
            if not config:
                continue

            # 1. 低于安全库存
            safety = config.get("safety_stock", 0)
            if safety > 0 and stock["total_qty"] < safety:
                severity = "critical" if stock["total_qty"] == 0 else "warning"
                alert_id = await self._create_alert(
                    factory_id, "below_safety", mid,
                    stock["material_code"], stock["material_name"],
                    current_qty=stock["total_qty"], threshold_qty=safety,
                    severity=severity,
                )
                if alert_id:
                    alerts_created += 1
                    alert_details.append({
                        "type": "below_safety",
                        "material": stock["material_code"],
                        "current": stock["total_qty"],
                        "threshold": safety,
                        "severity": severity,
                    })

            # 2. 超过最大库存
            max_stock = config.get("max_stock", 0)
            if max_stock > 0 and stock["total_qty"] > max_stock:
                alert_id = await self._create_alert(
                    factory_id, "above_max", mid,
                    stock["material_code"], stock["material_name"],
                    current_qty=stock["total_qty"], threshold_qty=max_stock,
                    severity="info",
                )
                if alert_id:
                    alerts_created += 1
                    alert_details.append({
                        "type": "above_max",
                        "material": stock["material_code"],
                        "current": stock["total_qty"],
                        "threshold": max_stock,
                    })

            # 3. 呆滞料
            dead_days = config.get("dead_stock_days", 90)
            if dead_days > 0 and stock["total_qty"] > 0:
                last_move = stock["last_movement"]
                if last_move:
                    inactive_days = (now - last_move).days
                    if inactive_days >= dead_days:
                        severity = "critical" if inactive_days >= dead_days * 2 else "warning"
                        alert_id = await self._create_alert(
                            factory_id, "dead_stock", mid,
                            stock["material_code"], stock["material_name"],
                            current_qty=stock["total_qty"], days_inactive=inactive_days,
                            severity=severity,
                        )
                        if alert_id:
                            alerts_created += 1
                            alert_details.append({
                                "type": "dead_stock",
                                "material": stock["material_code"],
                                "qty": stock["total_qty"],
                                "days": inactive_days,
                            })

            # 4. 慢销预警（介于呆滞与正常之间）
            slow_days = config.get("slow_moving_days", 60)
            if slow_days > 0 and stock["total_qty"] > 0 and dead_days > slow_days:
                last_move = stock["last_movement"]
                if last_move:
                    inactive_days = (now - last_move).days
                    if slow_days <= inactive_days < dead_days:
                        alert_id = await self._create_alert(
                            factory_id, "slow_moving", mid,
                            stock["material_code"], stock["material_name"],
                            current_qty=stock["total_qty"], days_inactive=inactive_days,
                            severity="warning",
                        )
                        if alert_id:
                            alerts_created += 1
                            alert_details.append({
                                "type": "slow_moving",
                                "material": stock["material_code"],
                                "days": inactive_days,
                            })

        # 5. 即将过期预警（按批次 expiry_date）
        warn_days = 30
        expiring_rows = await self.db.execute(text("""
            SELECT i.material_id, i.material_code, i.material_name, i.batch_code,
                   i.total_qty, i.expiry_date,
                   COALESCE(c.expiry_warn_days, :default_warn) AS warn_days
            FROM inventory i
            LEFT JOIN safety_stock_config c
              ON c.factory_id = i.factory_id AND c.material_id = i.material_id
            WHERE i.factory_id = :fid AND i.total_qty > 0 AND i.expiry_date IS NOT NULL
              AND i.expiry_date <= CURRENT_DATE + COALESCE(c.expiry_warn_days, :default_warn) * INTERVAL '1 day'
        """), {"fid": factory_id, "default_warn": warn_days})
        for row in expiring_rows.mappings().all():
            days_left = (row["expiry_date"] - now.date()).days if row["expiry_date"] else 0
            severity = "critical" if days_left <= 7 else "warning"
            alert_id = await self._create_alert(
                factory_id, "expiring", row["material_id"],
                row["material_code"], row["material_name"] or row["material_code"],
                current_qty=int(row["total_qty"] or 0),
                days_inactive=max(0, -days_left) if days_left < 0 else days_left,
                severity=severity,
            )
            if alert_id:
                alerts_created += 1
                alert_details.append({
                    "type": "expiring",
                    "material": row["material_code"],
                    "batch": row["batch_code"],
                    "days_left": days_left,
                })

        await self.db.commit()

        return {
            "checked_at": now.isoformat(),
            "materials_checked": len(material_stock),
            "alerts_created": alerts_created,
            "details": alert_details,
        }

    async def _create_alert(
        self, factory_id: str, alert_type: str, material_id: str,
        material_code: str, material_name: str,
        current_qty: int = 0, threshold_qty: int = 0,
        days_inactive: int = 0, severity: str = "warning",
    ) -> Optional[str]:
        """创建预警（去重：同类型同物料只保留一条 open）"""
        # 检查是否已存在
        existing = await self.db.execute(text(
            "SELECT id FROM stock_alerts WHERE factory_id = :fid AND alert_type = :type "
            "AND material_id = :mid AND status = 'open'"
        ), {"fid": factory_id, "type": alert_type, "mid": material_id})
        if existing.first():
            return None  # 已存在，不重复创建

        alert_id = _gen_id()
        await self.db.execute(text("""
            INSERT INTO stock_alerts (id, factory_id, alert_type, material_id, material_code,
                material_name, current_qty, threshold_qty, days_inactive, severity, status, created_at)
            VALUES (:id, :fid, :type, :mid, :mcode, :mname, :qty, :threshold, :days, :sev, 'open', :now)
        """), {
            "id": alert_id, "fid": factory_id, "type": alert_type,
            "mid": material_id, "mcode": material_code, "mname": material_name,
            "qty": current_qty, "threshold": threshold_qty,
            "days": days_inactive, "sev": severity, "now": datetime.utcnow(),
        })
        return alert_id

    async def get_alerts(
        self, factory_id: str, status: Optional[str] = None, alert_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """获取预警列表"""
        query = "SELECT * FROM stock_alerts WHERE factory_id = :fid"
        params: Dict[str, Any] = {"fid": factory_id}
        if status:
            query += " AND status = :status"
            params["status"] = status
        if alert_type:
            query += " AND alert_type = :type"
            params["type"] = alert_type
        query += " ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, created_at DESC LIMIT 100"

        result = await self.db.execute(text(query), params)
        items = [dict(r) for r in result.mappings().all()]

        # 统计
        stats = {"critical": 0, "warning": 0, "info": 0}
        for item in items:
            if item["status"] == "open":
                stats[item.get("severity", "info")] = stats.get(item.get("severity", "info"), 0) + 1

        return {"items": items, "total": len(items), "stats": stats}

    async def resolve_alert(self, alert_id: str, resolved_by: str = "system") -> Dict[str, Any]:
        """解决预警"""
        await self.db.execute(text("""
            UPDATE stock_alerts SET status = 'resolved', resolved_by = :by, resolved_at = :now
            WHERE id = :id
        """), {"by": resolved_by, "now": datetime.utcnow(), "id": alert_id})
        await self.db.commit()
        return {"success": True}

    async def acknowledge_alert(self, alert_id: str) -> Dict[str, Any]:
        """确认预警"""
        await self.db.execute(text(
            "UPDATE stock_alerts SET status = 'acknowledged' WHERE id = :id"
        ), {"id": alert_id})
        await self.db.commit()
        return {"success": True}

    # ==================== 安全库存配置 ====================

    async def get_safety_configs(self, factory_id: str) -> Dict[str, Any]:
        """获取安全库存配置"""
        result = await self.db.execute(text(
            "SELECT * FROM safety_stock_config WHERE factory_id = :fid ORDER BY material_code"
        ), {"fid": factory_id})
        return {"items": [dict(r) for r in result.mappings().all()]}

    async def upsert_safety_config(
        self, factory_id: str, material_id: str, material_code: str = "",
        material_name: str = "", safety_stock: int = 0, reorder_point: int = 0,
        max_stock: int = 0, dead_stock_days: int = 90,
    ) -> Dict[str, Any]:
        """新增/更新安全库存配置"""
        await self.db.execute(text("""
            INSERT INTO safety_stock_config (id, factory_id, material_id, material_code, material_name,
                safety_stock, reorder_point, max_stock, dead_stock_days, is_active, created_at, updated_at)
            VALUES (:id, :fid, :mid, :mcode, :mname, :safety, :reorder, :max, :dead, TRUE, :now, :now)
            ON CONFLICT (factory_id, material_id) DO UPDATE SET
                safety_stock = :safety, reorder_point = :reorder, max_stock = :max,
                dead_stock_days = :dead, updated_at = :now
        """), {
            "id": _gen_id(), "fid": factory_id, "mid": material_id,
            "mcode": material_code, "mname": material_name,
            "safety": safety_stock, "reorder": reorder_point,
            "max": max_stock, "dead": dead_stock_days, "now": datetime.utcnow(),
        })
        await self.db.commit()
        return {"success": True, "material_id": material_id}

    # ==================== 库存健康度概览 ====================

    async def stock_health_summary(self, factory_id: str) -> Dict[str, Any]:
        """库存健康度概览"""
        # 总库存
        total_result = await self.db.execute(text(
            "SELECT COUNT(DISTINCT material_id) as sku_count, COALESCE(SUM(total_qty), 0) as total_qty "
            "FROM inventory WHERE factory_id = :fid AND total_qty > 0"
        ), {"fid": factory_id})
        total = total_result.mappings().first()

        # 预警统计
        alert_result = await self.db.execute(text(
            "SELECT alert_type, COUNT(*) as cnt FROM stock_alerts "
            "WHERE factory_id = :fid AND status = 'open' GROUP BY alert_type"
        ), {"fid": factory_id})
        alert_stats = {r["alert_type"]: r["cnt"] for r in alert_result.mappings().all()}

        # 今日操作
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        txn_result = await self.db.execute(text(
            "SELECT transaction_type, COUNT(*) as cnt, COALESCE(SUM(ABS(quantity)), 0) as total_qty "
            "FROM inventory_transactions WHERE factory_id = :fid AND created_at >= :today "
            "GROUP BY transaction_type"
        ), {"fid": factory_id, "today": today_start})
        txn_stats = {r["transaction_type"]: {"count": r["cnt"], "qty": r["total_qty"]} for r in txn_result.mappings().all()}

        return {
            "sku_count": total["sku_count"] if total else 0,
            "total_qty": total["total_qty"] if total else 0,
            "alerts": alert_stats,
            "today_operations": txn_stats,
            "health_score": self._calc_health_score(alert_stats, total),
        }

    def _calc_health_score(self, alert_stats: Dict, total) -> int:
        """计算库存健康分（100分制）"""
        score = 100
        score -= alert_stats.get("below_safety", 0) * 10  # 缺料扣分重
        score -= alert_stats.get("dead_stock", 0) * 5
        score -= alert_stats.get("above_max", 0) * 3
        return max(0, min(100, score))
