"""
工作流交叉分析服务 - 看清工厂深层数据流
========================================
基于7条核心工作流和部门交叉点，分析：
1. 工作流全景（每条流的量/状态/瓶颈）
2. 部门交叉热力图（哪里交互最频繁 = 哪里需要协调人）
3. 信息断点识别（哪里还在用纸质/人工 = 哪里可以消除文员）
4. 物流×信息流对比（实物流 vs 系统记录 的差距）
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

_logger = logging.getLogger("workflow_analytics")


class WorkflowAnalyticsService:
    """工作流交叉分析"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def workflow_overview(self, factory_id: str) -> Dict[str, Any]:
        """7条工作流全景：量、状态分布、瓶颈"""
        # WF1: 订单→交付
        so_stats = await self._query("""
            SELECT status, count(*) as cnt, sum(quantity) as total_qty
            FROM sales_orders WHERE factory_id = :fid GROUP BY status
        """, {"fid": factory_id})

        # WF3: 生产工单
        wo_stats = await self._query("""
            SELECT status, count(*) as cnt, sum(planned_qty) as total_qty,
                   sum(completed_qty) as done_qty, sum(defect_qty) as defect_qty
            FROM work_orders WHERE factory_id = :fid GROUP BY status
        """, {"fid": factory_id})

        # WF2: 采购
        po_stats = await self._query("""
            SELECT status, count(*) as cnt, sum(qty) as total_qty, sum(total_amount) as total_amount
            FROM purchase_orders WHERE factory_id = :fid GROUP BY status
        """, {"fid": factory_id})

        # WF2+X1: 收货
        inb_stats = await self._query("""
            SELECT status, count(*) as cnt, sum(quantity) as total_qty
            FROM inbound_orders WHERE factory_id = :fid GROUP BY status
        """, {"fid": factory_id})

        # WF4+X2: 领料/出货
        out_stats = await self._query("""
            SELECT outbound_type, status, count(*) as cnt, sum(quantity) as total_qty
            FROM outbound_orders WHERE factory_id = :fid GROUP BY outbound_type, status
        """, {"fid": factory_id})

        # WF5: 检验
        insp_stats = await self._query("""
            SELECT inspect_type, result, count(*) as cnt, avg(defect_rate) as avg_defect
            FROM inspection_tasks WHERE factory_id = :fid GROUP BY inspect_type, result
        """, {"fid": factory_id})

        # WF6: 转序
        txn_stats = await self._query("""
            SELECT transaction_type, count(*) as cnt, sum(quantity) as total_qty
            FROM inventory_transactions WHERE factory_id = :fid GROUP BY transaction_type
        """, {"fid": factory_id})

        # 计算关键指标
        total_wo = sum(r.get("cnt", 0) for r in wo_stats)
        total_defect = sum(r.get("defect_qty", 0) or 0 for r in wo_stats)
        total_done = sum(r.get("done_qty", 0) or 0 for r in wo_stats)

        return {
            "factory_id": factory_id,
            "generated_at": datetime.now().isoformat(),
            "workflows": {
                "WF1_订单交付": {
                    "description": "销售→PMC→生产→品质→仓储→出货",
                    "sales_orders": so_stats,
                    "total_orders": sum(r.get("cnt", 0) for r in so_stats),
                },
                "WF2_采购收货": {
                    "description": "PMC→采购→供应商→IQC→仓库",
                    "purchase_orders": po_stats,
                    "inbound_orders": inb_stats,
                    "total_po": sum(r.get("cnt", 0) for r in po_stats),
                },
                "WF3_生产报工": {
                    "description": "PMC→各生产部→报工→统计",
                    "work_orders": wo_stats,
                    "total_wo": total_wo,
                    "completion_rate": round(total_done / max(sum(r.get("total_qty", 0) or 0 for r in wo_stats), 1) * 100, 1),
                    "defect_rate": round(total_defect / max(total_done, 1) * 100, 2),
                },
                "WF4_领料消耗": {
                    "description": "生产→仓库→库存扣减",
                    "outbound_by_type": out_stats,
                },
                "WF5_质量判定": {
                    "description": "品质↔所有生产部（IQC/IPQC/FQC）",
                    "inspections": insp_stats,
                    "total_inspections": sum(r.get("cnt", 0) for r in insp_stats),
                },
                "WF6_转序流转": {
                    "description": "工位间流转（跨部门交接）",
                    "transactions": txn_stats,
                    "total_transfers": sum(r.get("cnt", 0) for r in txn_stats),
                },
            },
        }

    async def department_intersection(self, factory_id: str) -> Dict[str, Any]:
        """部门交叉热力图：哪里交互最频繁 = 哪里需要协调人/文员"""

        # X1: 采购×品质×仓储（收货三方确认）
        x1 = await self._query("""
            SELECT i.status, count(*) as cnt,
                   s.supplier_name,
                   count(DISTINCT i.material_code) as material_types
            FROM inbound_orders i
            LEFT JOIN purchase_orders po ON i.supplier_id = po.supplier_id AND i.factory_id = po.factory_id
            LEFT JOIN suppliers s ON i.supplier_id = s.id
            WHERE i.factory_id = :fid
            GROUP BY i.status, s.supplier_name
            ORDER BY cnt DESC LIMIT 20
        """, {"fid": factory_id})

        # X2: 生产×仓储（领料频率 - 按工单）
        x2 = await self._query("""
            SELECT o.work_order_id, w.work_order_code, w.product_id,
                   count(*) as pick_count, sum(o.quantity) as total_picked
            FROM outbound_orders o
            LEFT JOIN work_orders w ON o.work_order_id = w.id
            WHERE o.factory_id = :fid AND o.outbound_type = 'production'
            GROUP BY o.work_order_id, w.work_order_code, w.product_id
            ORDER BY pick_count DESC LIMIT 15
        """, {"fid": factory_id})

        # X3: 生产×品质（检验覆盖 - 按工位）
        x3 = await self._query("""
            SELECT t.inspect_type, t.station_id, st.station_name, st.station_code,
                   count(*) as insp_count,
                   sum(CASE WHEN t.result = 'fail' THEN 1 ELSE 0 END) as fail_count,
                   avg(t.defect_rate) as avg_defect_rate
            FROM inspection_tasks t
            LEFT JOIN stations st ON t.station_id = st.id
            WHERE t.factory_id = :fid
            GROUP BY t.inspect_type, t.station_id, st.station_name, st.station_code
            ORDER BY insp_count DESC
        """, {"fid": factory_id})

        # X4: 生产×生产（转序 - 跨部门交接）
        x4 = await self._query("""
            SELECT remark, count(*) as transfer_count, sum(quantity) as total_qty
            FROM inventory_transactions
            WHERE factory_id = :fid AND transaction_type = 'transfer'
            GROUP BY remark
            ORDER BY transfer_count DESC LIMIT 20
        """, {"fid": factory_id})

        # X5: 生产×仓储（成品入库）
        x5 = await self._query("""
            SELECT outbound_type, status, count(*) as cnt, sum(quantity) as total_qty
            FROM outbound_orders WHERE factory_id = :fid
            GROUP BY outbound_type, status
        """, {"fid": factory_id})

        # X6: 仓储×销售（出货）
        x6 = await self._query("""
            SELECT o.outbound_code, o.quantity, o.created_at, o.completed_at,
                   s.order_code, s.customer_name, s.product_name
            FROM outbound_orders o
            LEFT JOIN sales_orders s ON o.material_id = s.product_id AND o.factory_id = s.factory_id
            WHERE o.factory_id = :fid AND o.outbound_type = 'shipment'
            ORDER BY o.created_at DESC LIMIT 20
        """, {"fid": factory_id})

        # X7: PMC×所有（工单分布 - 按工位/部门）
        x7 = await self._query("""
            SELECT st.station_name, st.station_code,
                   w.status, count(*) as wo_count,
                   sum(w.planned_qty) as planned, sum(w.completed_qty) as done
            FROM work_orders w
            LEFT JOIN stations st ON w.assigned_station_id = st.id
            WHERE w.factory_id = :fid
            GROUP BY st.station_name, st.station_code, w.status
            ORDER BY wo_count DESC
        """, {"fid": factory_id})

        # 计算交叉热度
        intersections = [
            {"id": "X1", "name": "采购×品质×仓储", "trigger": "收货三方确认",
             "volume": sum(r.get("cnt", 0) for r in x1),
             "info_flow": "送货单→IQC检验报告→入库单", "paper": "送货单+检验记录+入库单=3张纸"},
            {"id": "X2", "name": "生产×仓储", "trigger": "领料/退料",
             "volume": sum(r.get("pick_count", 0) for r in x2),
             "info_flow": "领料单→出库→扣账", "paper": "领料单=1张纸/次"},
            {"id": "X3", "name": "生产×品质", "trigger": "首检/巡检/完工检",
             "volume": sum(r.get("insp_count", 0) for r in x3),
             "info_flow": "检验记录→判定→处置", "paper": "检验报告=1张/次"},
            {"id": "X4", "name": "生产×生产", "trigger": "转序交接",
             "volume": sum(r.get("transfer_count", 0) for r in x4),
             "info_flow": "流转卡→确认→更新进度", "paper": "流转卡=1张/批"},
            {"id": "X5", "name": "生产×仓储", "trigger": "成品入库",
             "volume": sum(r.get("cnt", 0) for r in x5 if r.get("outbound_type") == "shipment"),
             "info_flow": "入库单→上架→更新库存", "paper": "入库单=1张/批"},
            {"id": "X6", "name": "仓储×销售", "trigger": "出货装柜",
             "volume": sum(r.get("cnt", 0) for r in x5 if r.get("outbound_type") == "shipment"),
             "info_flow": "出货单→箱单→发票→通知客户", "paper": "箱单+发票+出货单=3张"},
            {"id": "X7", "name": "PMC×所有部门", "trigger": "工单下达/进度跟踪",
             "volume": sum(r.get("wo_count", 0) for r in x7),
             "info_flow": "排产→派工→跟踪→催单", "paper": "派工单=1张/工单"},
        ]

        total_paper = sum(i["volume"] for i in intersections)

        return {
            "factory_id": factory_id,
            "generated_at": datetime.now().isoformat(),
            "summary": {
                "total_interactions": total_paper,
                "estimated_paper_per_month": f"~{total_paper * 3}张/月（按日均×30）",
                "clerk_workload": f"≈{total_paper // 50 + 1}个文员的全部工作",
            },
            "intersections": intersections,
            "details": {
                "X1_收货": x1,
                "X2_领料": x2,
                "X3_检验": x3,
                "X4_转序": x4,
                "X6_出货": x6,
                "X7_工单分布": x7,
            },
        }

    async def information_gap_analysis(self, factory_id: str) -> Dict[str, Any]:
        """信息断点分析：哪里系统有数据但流程断了（= 文员存在的原因）"""

        # 1. 工单有但无报工记录（应该自动报工但没有）
        wo_no_report = await self._query("""
            SELECT w.work_order_code, w.status, w.planned_qty, w.completed_qty,
                   st.station_name
            FROM work_orders w
            LEFT JOIN stations st ON w.assigned_station_id = st.id
            WHERE w.factory_id = :fid AND w.status = 'in_progress'
              AND w.completed_qty > 0
            ORDER BY w.completed_qty DESC LIMIT 10
        """, {"fid": factory_id})

        # 2. 收货单有但无IQC记录（应该检但没检）
        inb_no_iqc = await self._query("""
            SELECT i.inbound_code, i.material_code, i.quantity, i.status, i.created_at
            FROM inbound_orders i
            WHERE i.factory_id = :fid
              AND NOT EXISTS (
                  SELECT 1 FROM inspection_tasks t
                  WHERE t.factory_id = i.factory_id
                    AND t.source_code = i.inbound_code
                    AND t.inspect_type = 'IQC'
              )
            ORDER BY i.created_at DESC LIMIT 10
        """, {"fid": factory_id})

        # 3. 采购到期未收货（跟催断点）
        po_overdue = await self._query("""
            SELECT po_code, supplier_name, material_code, qty, expected_date, status
            FROM purchase_orders
            WHERE factory_id = :fid
              AND status NOT IN ('received', 'cancelled')
              AND expected_date < CURRENT_DATE
            ORDER BY expected_date LIMIT 10
        """, {"fid": factory_id})

        # 4. 工单超期未完工（调度断点）
        wo_overdue = await self._query("""
            SELECT work_order_code, product_id, planned_qty, completed_qty, status,
                   planned_due, assigned_station_id
            FROM work_orders
            WHERE factory_id = :fid
              AND status IN ('released', 'in_progress')
              AND planned_due < NOW()
            ORDER BY planned_due LIMIT 10
        """, {"fid": factory_id})

        # 5. 库存低于安全水位（补货断点）
        low_stock = await self._query("""
            SELECT material_code, material_name, total_qty, available_qty, unit
            FROM inventory
            WHERE factory_id = :fid AND available_qty < total_qty * 0.2
            ORDER BY available_qty LIMIT 10
        """, {"fid": factory_id})

        # 6. 检验不合格但未处理（品质断点）
        insp_open = await self._query("""
            SELECT task_code, inspect_type, material_code, defect_rate, result, disposition
            FROM inspection_tasks
            WHERE factory_id = :fid AND result = 'fail'
            ORDER BY created_at DESC LIMIT 10
        """, {"fid": factory_id})

        gaps = [
            {"gap_id": "G1", "name": "报工断点", "description": "工单在制但无实时报工（靠文员事后录）",
             "affected": len(wo_no_report), "records": wo_no_report,
             "solution": "操作工扫码自助报工（已实现）"},
            {"gap_id": "G2", "name": "IQC断点", "description": "收货未触发来料检（靠文员通知品质）",
             "affected": len(inb_no_iqc), "records": inb_no_iqc,
             "solution": "收货扫码→自动触发IQC任务"},
            {"gap_id": "G3", "name": "跟催断点", "description": "采购到期未收货（靠文员打电话催）",
             "affected": len(po_overdue), "records": po_overdue,
             "solution": "系统自动跟催+超期升级（已实现）"},
            {"gap_id": "G4", "name": "调度断点", "description": "工单超期未完工（靠调度员盯）",
             "affected": len(wo_overdue), "records": wo_overdue,
             "solution": "事件驱动自派发+超期自动升级（已实现）"},
            {"gap_id": "G5", "name": "补货断点", "description": "库存低于安全水位（靠仓管员发现）",
             "affected": len(low_stock), "records": low_stock,
             "solution": "安全库存自动预警+MRP补货（已实现）"},
            {"gap_id": "G6", "name": "品质断点", "description": "检验不合格未处理（靠文员跟踪）",
             "affected": len(insp_open), "records": insp_open,
             "solution": "不合格自动触发异常引擎+升级（已实现）"},
        ]

        total_gaps = sum(g["affected"] for g in gaps)

        return {
            "factory_id": factory_id,
            "generated_at": datetime.now().isoformat(),
            "summary": {
                "total_information_gaps": total_gaps,
                "interpretation": f"当前有 {total_gaps} 个信息断点需要人（文员）来弥合",
                "after_system": "系统全部打通后 → 0断点 → 0文员",
            },
            "gaps": gaps,
        }

    async def material_flow_sankey(self, factory_id: str) -> Dict[str, Any]:
        """物流全景：进→存→产→出 的完整链路"""

        # 进货（按供应商）
        inbound_by_supplier = await self._query("""
            SELECT s.supplier_name, count(*) as deliveries, sum(i.quantity) as total_qty
            FROM inbound_orders i
            LEFT JOIN suppliers s ON i.supplier_id = s.id
            WHERE i.factory_id = :fid
            GROUP BY s.supplier_name ORDER BY total_qty DESC
        """, {"fid": factory_id})

        # 库存（按仓库）
        stock_by_warehouse = await self._query("""
            SELECT warehouse_id, count(*) as sku_count,
                   sum(total_qty) as total_qty, sum(available_qty) as available
            FROM inventory WHERE factory_id = :fid
            GROUP BY warehouse_id
        """, {"fid": factory_id})

        # 生产消耗（按工位）
        consumption_by_station = await self._query("""
            SELECT st.station_name, st.station_code,
                   count(DISTINCT o.work_order_id) as wo_served,
                   sum(o.quantity) as material_consumed
            FROM outbound_orders o
            LEFT JOIN work_orders w ON o.work_order_id = w.id
            LEFT JOIN stations st ON w.assigned_station_id = st.id
            WHERE o.factory_id = :fid AND o.outbound_type = 'production'
            GROUP BY st.station_name, st.station_code
            ORDER BY material_consumed DESC
        """, {"fid": factory_id})

        # 出货（按客户）
        outbound_by_customer = await self._query("""
            SELECT s.customer_name, count(*) as shipments, sum(o.quantity) as total_qty
            FROM outbound_orders o
            LEFT JOIN sales_orders s ON o.material_id = s.product_id AND o.factory_id = s.factory_id
            WHERE o.factory_id = :fid AND o.outbound_type = 'shipment'
            GROUP BY s.customer_name ORDER BY total_qty DESC
        """, {"fid": factory_id})

        return {
            "factory_id": factory_id,
            "generated_at": datetime.now().isoformat(),
            "flow": {
                "inbound_供应商→仓库": inbound_by_supplier,
                "stock_仓库现状": stock_by_warehouse,
                "consumption_仓库→产线": consumption_by_station,
                "outbound_仓库→客户": outbound_by_customer,
            },
            "metrics": {
                "total_inbound_qty": sum(r.get("total_qty", 0) or 0 for r in inbound_by_supplier),
                "total_stock_qty": sum(r.get("total_qty", 0) or 0 for r in stock_by_warehouse),
                "total_consumed_qty": sum(r.get("material_consumed", 0) or 0 for r in consumption_by_station),
                "total_outbound_qty": sum(r.get("total_qty", 0) or 0 for r in outbound_by_customer),
            },
        }

    async def _query(self, sql: str, params: dict) -> List[Dict]:
        result = await self.db.execute(text(sql), params)
        rows = result.fetchall()
        cols = result.keys()
        return [dict(zip(cols, row)) for row in rows]
