"""Response Formatter for Chatbot.

Handles formatting of all chat responses — success cases, degraded/error messages,
JSON data converted to markdown tables, etc. Ensures consistent output format
across all chat endpoints.
"""

from typing import Optional, Dict, Any
from datetime import datetime


class ResponseFormatter:
    """Format chatbot responses according to standardized templates."""
    
    def format_success(self, reply_text: str, model: Optional[str] = None, degraded: bool = False) -> Dict[str, Any]:
        """Format a successful chat response."""
        response = {
            "reply": reply_text,
            "model": model or "dynamic-route",
            "degraded": degraded,
            "timestamp": datetime.now().isoformat(),
        }
        
        if degraded:
            response["note"] = "Some recovery strategies applied; result may be approximate"
        
        return response
    
    def format_inventory_result(self, result: Dict[str, Any]) -> str:
        """Format inventory query results as human-readable text."""
        inventory = result.get("inventory", [])
        if not inventory:
            return "该工厂暂无库存记录。"
        
        lines = ["✅ 库存查询结果："]
        for inv in inventory[:10]:  # Limit display
            material = inv.get("material_code", "未知")
            total = inv.get("total_qty", 0)
            available = inv.get("available_qty", 0)
            lines.append(f"  - {material}: 总{total}, 可用{available}")
        
        if len(inventory) > 10:
            lines.append(f"  ... (共 {len(inventory)} 条记录)")
        
        return "\n".join(lines)
    
    def format_production_summary(self, result: Dict[str, Any]) -> str:
        """Format production summary results as human-readable text."""
        good = result.get("today_good_output", 0)
        defect = result.get("today_defect", 0)
        total = good + defect
        yield_pct = result.get("yield_rate_pct", 0)
        reports = result.get("report_count", 0)
        
        lines = [f"✅ 今日生产汇总："]
        lines.append(f"   良品产出：{good} 件")
        lines.append(f"   不良品：{defect} 件")
        lines.append(f"   总产出：{total} 件")
        lines.append(f"   良率：{yield_pct:.1f}%")
        lines.append(f"   报工记录数：{reports} 条")
        
        return "\n".join(lines)
    
    def format_work_orders(self, result: Dict[str, Any]) -> str:
        """Format work order list as human-readable text."""
        orders = result.get("work_orders", [])
        count = result.get("count", 0)
        
        if not orders:
            return "当前无在制工单。"
        
        lines = f"✅ 在制工单（共 {count} 个）："
        for wo in orders[:5]:  # Limit display
            code = wo.get("work_order_code", "未知")
            status = wo.get("status", "unknown")
            product = wo.get("product_name", "未知")
            lines.append(f"  • {code} ({product}) - {status}")
        
        if len(orders) > 5:
            lines += f"\n  ... (共 {len(orders)} 个)"
        
        return lines
    
    def format_error(self, message: str, status_code: int = 500) -> Dict[str, Any]:
        """Format an error response."""
        return {
            "error": True,
            "status_code": status_code,
            "message": message,
            "timestamp": datetime.now().isoformat()
        }
    
    def format_degraded_message(self, reason: str) -> str:
        """Generate a user-friendly degraded mode message."""
        return f"⚠️ 服务降级处理中：{reason}。部分功能可能受限。"
