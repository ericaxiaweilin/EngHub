"""
采购自动化服务 - 岗位替代: 替代采购员
核心理念：标准物料 MRP→自动比价→自动下单→自动跟催，例外才人工

流程（无人化）：
1. MRP 计算净需求 → 自动生成采购申请(PR)
2. PR 自动审批（金额<阈值 且 有合格供应商）
3. 自动比价（价格×交期×评分 加权）→ 选最优供应商
4. 自动生成采购订单(PO)
5. 到货超期 → 自动催货通知
6. 供应商绩效自动评分
"""
import uuid
import logging
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

_logger = logging.getLogger("procurement")

# 自动审批阈值（低于此金额自动通过）
AUTO_APPROVE_LIMIT = float(5000)  # 元


def _gen_id():
    return str(uuid.uuid4())


class ProcurementService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ==================== MRP → 自动采购申请 ====================

    async def auto_pr_from_mrp(self, factory_id: str, mrp_results: List[Dict]) -> Dict[str, Any]:
        """MRP 净需求 → 自动生成采购申请。

        采购员替代逻辑：MRP 算出缺料 → 系统直接生成 PR，不需要人手动填。
        """
        created = []
        for item in mrp_results:
            net_qty = item.get("net_requirement", 0)
            if net_qty <= 0:
                continue
            material_code = item.get("material_code", "")
            pr_code = f"PR-{factory_id[:6]}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{len(created)+1:03d}"

            await self.db.execute(text("""
                INSERT INTO purchase_requisitions
                (id, factory_id, pr_code, source, source_id, material_code, material_name,
                 qty, unit, required_date, status, auto_approved, created_at, updated_at)
                VALUES (:id, :fid, :code, 'mrp', :src, :mc, :mn, :qty, 'PCS', :rd, 'pending', FALSE, NOW(), NOW())
            """), {
                "id": _gen_id(), "fid": factory_id, "code": pr_code,
                "src": item.get("plan_id", ""), "mc": material_code,
                "mn": item.get("material_name", ""), "qty": net_qty,
                "rd": (date.today() + timedelta(days=item.get("lead_days", 7))).isoformat(),
            })
            created.append({"pr_code": pr_code, "material_code": material_code, "qty": net_qty})

        if created:
            await self.db.commit()
        return {"created_count": len(created), "requisitions": created}

    # ==================== 自动比价 ====================

    async def compare_suppliers(self, material_code: str, qty: float) -> Dict[str, Any]:
        """自动比价：获取所有合格供应商报价，加权排序。

        权重：价格 50% + 交期 30% + 评分 20%
        采购员替代逻辑：不需要人打电话问价，系统自动比。
        """
        result = await self.db.execute(text("""
            SELECT s.id as supplier_id, s.supplier_code, s.supplier_name,
                   s.rating, s.on_time_rate, s.avg_lead_days,
                   sp.unit_price, sp.moq, sp.lead_days, sp.currency
            FROM supplier_prices sp
            JOIN suppliers s ON s.id = sp.supplier_id
            WHERE sp.material_code = :mc AND sp.is_active = TRUE AND s.is_approved = TRUE
              AND (sp.valid_to IS NULL OR sp.valid_to >= CURRENT_DATE)
            ORDER BY sp.unit_price ASC
        """), {"mc": material_code})
        quotes = [dict(r) for r in result.mappings().all()]

        if not quotes:
            return {"material_code": material_code, "quotes": [], "recommendation": None,
                    "message": "无合格供应商报价，需人工寻源"}

        # 归一化评分
        min_price = min(q["unit_price"] for q in quotes)
        min_lead = min(q["lead_days"] for q in quotes)
        max_rating = max(float(q["rating"]) for q in quotes) or 5

        scored = []
        for q in quotes:
            price_score = (min_price / float(q["unit_price"])) * 50 if q["unit_price"] > 0 else 50
            lead_score = (min_lead / max(q["lead_days"], 1)) * 30
            rating_score = (float(q["rating"]) / max_rating) * 20
            total = round(price_score + lead_score + rating_score, 2)

            # MOQ 检查
            meets_moq = qty >= (q["moq"] or 1)
            scored.append({
                **q,
                "price_score": round(price_score, 1),
                "lead_score": round(lead_score, 1),
                "rating_score": round(rating_score, 1),
                "total_score": total,
                "meets_moq": meets_moq,
                "total_cost": round(float(q["unit_price"]) * qty, 2),
            })

        scored.sort(key=lambda x: (-x["total_score"], -x["meets_moq"]))
        best = scored[0] if scored else None

        return {
            "material_code": material_code,
            "qty": qty,
            "quotes_count": len(scored),
            "quotes": scored,
            "recommendation": {
                "supplier_id": best["supplier_id"],
                "supplier_name": best["supplier_name"],
                "unit_price": float(best["unit_price"]),
                "total_cost": best["total_cost"],
                "lead_days": best["lead_days"],
                "score": best["total_score"],
                "auto_order": best["total_cost"] <= AUTO_APPROVE_LIMIT and best["meets_moq"],
            } if best else None,
        }

    # ==================== 自动下单（PR→PO） ====================

    async def auto_create_po(self, factory_id: str, pr_id: str) -> Dict[str, Any]:
        """采购申请 → 自动比价 → 自动生成 PO。

        采购员替代逻辑：PR 审批通过后，系统自动选供应商下单。
        只有金额>阈值 或 无合格供应商 才需要人工介入。
        """
        # 获取 PR
        pr_result = await self.db.execute(text(
            "SELECT * FROM purchase_requisitions WHERE id = :id AND status IN ('pending','approved')"
        ), {"id": pr_id})
        pr = pr_result.mappings().first()
        if not pr:
            return {"error": "PR不存在或已处理"}

        # 自动比价
        comparison = await self.compare_suppliers(pr["material_code"], float(pr["qty"]))
        rec = comparison.get("recommendation")

        if not rec:
            return {"error": "无合格供应商，需人工寻源", "pr_code": pr["pr_code"],
                    "action_required": "manual_sourcing"}

        total_cost = rec["total_cost"]
        needs_manual = total_cost > AUTO_APPROVE_LIMIT

        if needs_manual:
            # 金额超阈值 → 标记待人工审批
            await self.db.execute(text(
                "UPDATE purchase_requisitions SET status='approved', approved_by='pending_manual', updated_at=NOW() WHERE id=:id"
            ), {"id": pr_id})
            await self.db.commit()
            return {
                "status": "pending_manual_approval",
                "pr_code": pr["pr_code"],
                "recommended_supplier": rec["supplier_name"],
                "total_cost": total_cost,
                "reason": f"金额 {total_cost} 超过自动审批阈值 {AUTO_APPROVE_LIMIT}",
            }

        # 自动审批 + 自动下单
        po_code = f"PO-{factory_id[:6]}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        po_id = _gen_id()
        expected_date = (date.today() + timedelta(days=rec["lead_days"])).isoformat()

        await self.db.execute(text("""
            INSERT INTO purchase_orders
            (id, factory_id, po_code, pr_id, supplier_id, supplier_name,
             material_code, material_name, qty, unit_price, total_amount,
             order_date, expected_date, status, auto_generated, created_by, created_at, updated_at)
            VALUES (:id, :fid, :code, :pr, :sid, :sname, :mc, :mn, :qty, :price, :total,
                    CURRENT_DATE, :exp, 'confirmed', TRUE, 'system', NOW(), NOW())
        """), {
            "id": po_id, "fid": factory_id, "code": po_code, "pr": pr_id,
            "sid": rec["supplier_id"], "sname": rec["supplier_name"],
            "mc": pr["material_code"], "mn": pr.get("material_name", ""),
            "qty": pr["qty"], "price": rec["unit_price"], "total": total_cost,
            "exp": expected_date,
        })

        # 更新 PR 状态
        await self.db.execute(text(
            "UPDATE purchase_requisitions SET status='ordered', auto_approved=TRUE, approved_by='system', updated_at=NOW() WHERE id=:id"
        ), {"id": pr_id})
        await self.db.commit()

        return {
            "status": "auto_ordered",
            "po_code": po_code,
            "supplier": rec["supplier_name"],
            "total_cost": total_cost,
            "expected_date": expected_date,
            "message": "✅ 全自动完成：MRP→PR→比价→PO，无需人工",
        }

    # ==================== 到货跟催 ====================

    async def overdue_tracking(self, factory_id: str) -> Dict[str, Any]:
        """自动跟催：找出超期未到货的 PO，生成催货清单。

        采购员替代逻辑：不需要人记着打电话催，系统自动标红。
        """
        result = await self.db.execute(text("""
            SELECT po_code, supplier_name, material_code, material_name,
                   qty, expected_date, order_date,
                   CURRENT_DATE - expected_date as overdue_days
            FROM purchase_orders
            WHERE factory_id = :fid AND status IN ('confirmed', 'shipped')
              AND expected_date < CURRENT_DATE
            ORDER BY expected_date ASC
        """), {"fid": factory_id})
        overdue = [dict(r) for r in result.mappings().all()]

        # 即将到期（3天内）
        upcoming_result = await self.db.execute(text("""
            SELECT po_code, supplier_name, material_code, expected_date,
                   expected_date - CURRENT_DATE as days_left
            FROM purchase_orders
            WHERE factory_id = :fid AND status IN ('confirmed', 'shipped')
              AND expected_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '3 days'
            ORDER BY expected_date ASC
        """), {"fid": factory_id})
        upcoming = [dict(r) for r in upcoming_result.mappings().all()]

        return {
            "overdue_count": len(overdue),
            "overdue_items": overdue,
            "upcoming_count": len(upcoming),
            "upcoming_items": upcoming,
            "action": "auto_remind" if overdue else "none",
        }

    # ==================== 供应商绩效评分 ====================

    async def supplier_scorecard(self, factory_id: str) -> Dict[str, Any]:
        """自动评分：基于历史 PO 计算供应商绩效。

        采购员替代逻辑：不需要人做供应商评估表，系统自动算。
        """
        result = await self.db.execute(text("""
            SELECT s.id, s.supplier_code, s.supplier_name, s.category,
                   COUNT(po.id) as total_orders,
                   COUNT(CASE WHEN po.status = 'closed' THEN 1 END) as completed_orders,
                   COUNT(CASE WHEN po.actual_date <= po.expected_date THEN 1 END) as on_time_count,
                   AVG(po.actual_date - po.expected_date) as avg_delay_days
            FROM suppliers s
            LEFT JOIN purchase_orders po ON po.supplier_id = s.id AND po.factory_id = :fid
            WHERE s.factory_id = :fid
            GROUP BY s.id, s.supplier_code, s.supplier_name, s.category
            ORDER BY s.supplier_name
        """), {"fid": factory_id})
        suppliers = [dict(r) for r in result.mappings().all()]

        scored = []
        for s in suppliers:
            total = s["total_orders"] or 0
            on_time = s["on_time_count"] or 0
            on_time_rate = round((on_time / total * 100) if total > 0 else 0, 1)
            avg_delay = round(float(s["avg_delay_days"] or 0), 1)

            # 综合评分 (5分制)
            score = 3.0
            if total > 0:
                score = min(5.0, max(1.0, 3.0 + (on_time_rate - 80) / 20))

            scored.append({
                "supplier_code": s["supplier_code"],
                "supplier_name": s["supplier_name"],
                "category": s["category"],
                "total_orders": total,
                "on_time_rate": on_time_rate,
                "avg_delay_days": avg_delay,
                "score": round(score, 2),
                "grade": "A" if score >= 4.5 else "B" if score >= 3.5 else "C" if score >= 2.5 else "D",
            })

        # 更新评分到数据库
        for s in scored:
            await self.db.execute(text(
                "UPDATE suppliers SET rating = :r, on_time_rate = :otr, updated_at = NOW() WHERE factory_id = :fid AND supplier_code = :sc"
            ), {"r": s["score"], "otr": s["on_time_rate"], "fid": factory_id, "sc": s["supplier_code"]})
        await self.db.commit()

        return {"suppliers": scored, "evaluated_at": datetime.utcnow().isoformat()}
