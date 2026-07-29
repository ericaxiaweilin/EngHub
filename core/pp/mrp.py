"""
PP Material Requirements Planning (MRP) Service
物料需求计划模块

功能:
- BOM展开
- 库存可用量检查
- 采购建议生成
"""

import uuid
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Set
from enum import Enum


class MRPStatus(str, Enum):
    """MRP状态"""
    PENDING = "pending"       # 待处理
    CALCULATED = "calculated"  # 已计算
    ORDERED = "ordered"       # 已下单
    PARTIAL = "partial"      # 部分到货
    RECEIVED = "received"    # 已收货


class PurchasePriority(str, Enum):
    """采购优先级"""
    URGENT = "urgent"     # 紧急
    HIGH = "high"         # 高
    NORMAL = "normal"     # 普通
    LOW = "low"           # 低


class MRPService:
    """
    物料需求计划服务
    
    核心功能:
    - BOM展开 (根据工单/计划的产品展开物料需求)
    - 库存检查 (可用量 vs 需求量)
    - 采购建议 (短缺物料生成采购建议)
    
    注意：使用内存存储模拟数据库，实际项目应连接真实数据库
    """
    
    def __init__(self, db_pool=None):
        self.db_pool = db_pool
        # 内存存储模拟（生产环境替换为数据库查询）
        self._bom_db: Dict[str, List[Dict]] = {}  # 产品BOM清单
        self._inventory_db: Dict[str, Dict] = {}  # 库存数据
        self._material_master: Dict[str, Dict] = {}  # 物料主数据
        self._supplier_db: Dict[str, Dict] = {}  # 供应商数据
        
        # 初始化示例数据
        self._init_sample_data()
        # === APS 智能联动配置 ===
        self.aps_auto_trigger_enabled = False
        self.aps_shortage_threshold_items = 2
        self.aps_shortage_threshold_ratio = 0.5
        self.aps_override_horizon_days = 7
        self.aps_optimize_for = "delivery"
    
    def _init_sample_data(self):
        """初始化示例BOM、库存和物料数据"""
        # BOM示例：PRODUCT-A由多个子部件组成
        self._bom_db["PRODUCT-A"] = [
            {
                "material_id": "MAT-RES-10K",
                "material_code": "RES-10K-0603",
                "material_name": "贴片电阻10K",
                "unit": "pcs",
                "quantity_per_parent": 10,
                "level": 1,
            },
            {
                "material_id": "MAT-CAP-100NF",
                "material_code": "CAP-100NF-0603",
                "material_name": "贴片电容100NF",
                "unit": "pcs",
                "quantity_per_parent": 5,
                "level": 1,
            },
            {
                "material_id": "MAT-MCU-STM32",
                "material_code": "MCU-STM32F407",
                "material_name": "STM32微控制器",
                "unit": "pcs",
                "quantity_per_parent": 1,
                "level": 1,
            },
            {
                "material_id": "MAT-BODY-PLASTIC",
                "material_code": "BODY-ABS-RED",
                "material_name": "红色塑料外壳",
                "unit": "pcs",
                "quantity_per_parent": 1,
                "level": 1,
            },
        ]
        
        self._bom_db["PRODUCT-B"] = [
            {
                "material_id": "MAT-SENSOR-TEMP",
                "material_code": "TMP-HX-001",
                "material_name": "温度传感器",
                "unit": "pcs",
                "quantity_per_parent": 2,
                "level": 1,
            },
            {
                "material_id": "MAT-MCU-STM32",
                "material_code": "MCU-STM32F407",
                "material_name": "STM32微控制器",
                "unit": "pcs",
                "quantity_per_parent": 1,
                "level": 1,
            },
        ]
        
        # 库存数据
        self._inventory_db["RES-10K-0603"] = {
            "material_id": "MAT-RES-10K",
            "material_code": "RES-10K-0603",
            "on_hand": 15000,
            "reserved": 2000,
            "on_order": 5000,
            "safety_stock": 1000,
            "lead_time_days": 7,
            "warehouse_id": "WH-MAIN-01",
        }
        
        self._inventory_db["CAP-100NF-0603"] = {
            "material_id": "MAT-CAP-100NF",
            "material_code": "CAP-100NF-0603",
            "on_hand": 8000,
            "reserved": 1000,
            "on_order": 0,
            "safety_stock": 500,
            "lead_time_days": 5,
            "warehouse_id": "WH-MAIN-01",
        }
        
        self._inventory_db["MCU-STM32F407"] = {
            "material_id": "MAT-MCU-STM32",
            "material_code": "MCU-STM32F407",
            "on_hand": 150,
            "reserved": 50,
            "on_order": 100,
            "safety_stock": 30,
            "lead_time_days": 14,
            "warehouse_id": "WH-ELEC-01",
        }
        
        self._inventory_db["BODY-ABS-RED"] = {
            "material_id": "MAT-BODY-PLASTIC",
            "material_code": "BODY-ABS-RED",
            "on_hand": 200,
            "reserved": 50,
            "on_order": 0,
            "safety_stock": 20,
            "lead_time_days": 10,
            "warehouse_id": "WH-PLASTIC-01",
        }
        
        self._inventory_db["TMP-HX-001"] = {
            "material_id": "MAT-SENSOR-TEMP",
            "material_code": "TMP-HX-001",
            "on_hand": 300,
            "reserved": 100,
            "on_order": 200,
            "safety_stock": 50,
            "lead_time_days": 7,
            "warehouse_id": "WH-ELEC-01",
        }
        
        # 物料主数据
        self._material_master["RES-10K-0603"] = {
            "material_code": "RES-10K-0603",
            "material_name": "贴片电阻10K",
            "unit": "pcs",
            "moq": 100,  # 最小订单量
            "eoq": 5000,  # 经济批量
            "packing_unit": 1000,  # 包装倍数
            "unit_cost": 0.01,  # 单位成本
            "last_purchase_date": datetime.now().strftime("%Y-%m-%d"),
            "preferred_supplier": "SUP-ELEC-001",
        }
        
        self._material_master["CAP-100NF-0603"] = {
            "material_code": "CAP-100NF-0603",
            "material_name": "贴片电容100NF",
            "unit": "pcs",
            "moq": 100,
            "eoq": 3000,
            "packing_unit": 500,
            "unit_cost": 0.02,
            "last_purchase_date": datetime.now().strftime("%Y-%m-%d"),
            "preferred_supplier": "SUP-ELEC-001",
        }
        
        self._material_master["MCU-STM32F407"] = {
            "material_code": "MCU-STM32F407",
            "material_name": "STM32微控制器",
            "unit": "pcs",
            "moq": 50,
            "eoq": 200,
            "packing_unit": 50,
            "unit_cost": 8.5,
            "last_purchase_date": datetime.now().strftime("%Y-%m-%d"),
            "preferred_supplier": "SUP-CHIP-001",
        }
        
        self._material_master["BODY-ABS-RED"] = {
            "material_code": "BODY-ABS-RED",
            "material_name": "红色塑料外壳",
            "unit": "pcs",
            "moq": 100,
            "eoq": 500,
            "packing_unit": 100,
            "unit_cost": 1.2,
            "last_purchase_date": datetime.now().strftime("%Y-%m-%d"),
            "preferred_supplier": "SUP-PLASTIC-001",
        }
        
        self._material_master["TMP-HX-001"] = {
            "material_code": "TMP-HX-001",
            "material_name": "温度传感器",
            "unit": "pcs",
            "moq": 50,
            "eoq": 150,
            "packing_unit": 50,
            "unit_cost": 3.5,
            "last_purchase_date": datetime.now().strftime("%Y-%m-%d"),
            "preferred_supplier": "SUP-SENSOR-001",
        }
        
        # 供应商数据
        self._supplier_db["SUP-ELEC-001"] = {
            "supplier_id": "SUP-ELEC-001",
            "supplier_name": "电子元件供应商A",
            "lead_time_days": 7,
            "rating": 4.5,
        }
        
        self._supplier_db["SUP-CHIP-001"] = {
            "supplier_id": "SUP-CHIP-001",
            "supplier_name": "芯片供应商B",
            "lead_time_days": 14,
            "rating": 4.8,
        }
        
        self._supplier_db["SUP-PLASTIC-001"] = {
            "supplier_id": "SUP-PLASTIC-001",
            "supplier_name": "塑料制品供应商C",
            "lead_time_days": 10,
            "rating": 4.2,
        }
        
        self._supplier_db["SUP-SENSOR-001"] = {
            "supplier_id": "SUP-SENSOR-001",
            "supplier_name": "传感器供应商D",
            "lead_time_days": 7,
            "rating": 4.6,
        }

    async def calculate_mrp(
        self,
        plan_id: str,
        product_id: str,
        quantity: int,
        bom_version: str = None,
    ) -> Dict[str, Any]:
        """
        计算MRP - 核心业务逻辑
        
        根据生产计划展开BOM，计算物料净需求
        """
        # 验证产品BOM存在
        if product_id not in self._bom_db:
            raise ValueError(f"产品 {product_id} 无BOM记录")
        
        mrp_result = {
            "id": str(uuid.uuid4()),
            "plan_id": plan_id,
            "product_id": product_id,
            "product_name": product_id,
            "quantity": quantity,
            "calculated_at": datetime.now(),
            "bom_version": bom_version or "CURRENT",
            "items": [],  # 每个物料的明细
            "total_shortage_qty": 0,
            "total_shortage_value": 0.0,
            "total_purchase_suggestion_value": 0.0,
            "suggestion_count": 0,
            "warning_messages": [],
        }
        
        # 步骤1: 获取并展开BOM
        bom_items = await self.expand_bom(product_id, quantity, bom_version)
        mrp_result["bom_expanded_count"] = len(bom_items)
        
        # 步骤2: 收集所有需要检查的物料ID（去重）
        material_codes_seen: Set[str] = set()
        material_unique_items: List[Dict] = []  # 去重后的BOM层级列表
        
        for item in bom_items:
            if item["material_code"] not in material_codes_seen:
                material_codes_seen.add(item["material_code"])
                material_unique_items.append(item)
        
        # 步骤3: 检查每个物料的库存可用性
        inventory_availability = await self.check_inventory_availability(
            list(material_codes_seen),
        )
        
        # 步骤4: 计算净需求和短缺
        for item in material_unique_items:
            material_code = item["material_code"]
            parent_qty = item["quantity_per_parent"] * quantity  # 父层数量 * 母件数量
            
            # 获取该物料在当前BOM层级的总需求（考虑层级重复计算，此处简化取单层）
            total_gross_demand = parent_qty  # 毛需求 = 母件数量 × 单层用量
            
            # 获取库存信息
            inv_info = inventory_availability.get(material_code, {})
            
            # 计算可用量 = 在库 - 预留 + 在途
            available_qty = inv_info.get("on_hand", 0) - inv_info.get("reserved_qty", 0) + inv_info.get("on_order_qty", 0)
            safety_stock = inv_info.get("safety_stock", 0)
            
            # 净需求 = 毛需求 - 可用量 + 安全库存保护
            net_demand = max(0, total_gross_demand - available_qty + safety_stock)
            
            # 检查是否短缺
            shortage_qty = max(0, total_gross_demand - available_qty)
            
            item_result = {
                "material_id": item["material_id"],
                "material_code": material_code,
                "material_name": item["material_name"],
                "level": item["level"],
                "unit": item["unit"],
                "gross_demand": total_gross_demand,
                "available_qty": available_qty,
                "safety_stock": safety_stock,
                "net_demand": net_demand,
                "shortage_qty": shortage_qty,
                "lead_time_days": inv_info.get("lead_time_days", 7),
                "warehouse_id": inv_info.get("warehouse_id", ""),
            }
            
            mrp_result["items"].append(item_result)
            mrp_result["total_shortage_qty"] += shortage_qty
            
            # 计算短缺价值（按物料成本）
            material_cost = self._get_material_cost(material_code)
            mrp_result["total_shortage_value"] += shortage_qty * material_cost
        
        # 步骤5: 生成采购建议
        purchase_suggestions = await self.generate_purchase_suggestions(mrp_result)
        mrp_result["purchase_suggestions"] = purchase_suggestions
        
        # 计算建议采购总价值
        suggestion_total = sum(s.get("estimated_cost", 0) for s in purchase_suggestions)
        mrp_result["total_purchase_suggestion_value"] = round(suggestion_total, 2)
        mrp_result["suggestion_count"] = len(purchase_suggestions)
        
        # 设置状态
        
        # 计算汇总信息（在设置状态前）
        total_materials = len(mrp_result["items"])
        shortage_count = sum(1 for item in mrp_result["items"] if item["net_demand"] > 0)
        total_shortage_qty = sum(item["net_demand"] for item in mrp_result["items"] if item["net_demand"] > 0)
        
        mrp_result["summary"] = {
            "total_materials": total_materials,
            "shortage_count": shortage_count,
            "total_shortage_qty": total_shortage_qty,
}

        # 设置状态
        
        # === 智能联动：MRP 计算后检查是否需触发 APS 重排 ===
        # 仅在启用自动触发的情况下执行
        if getattr(self, "aps_auto_trigger_enabled", False):
            from core.pp.aps_integration import PPAPSLinker
            shortage_count = mrp_result.get("summary", {}).get("shortage_count", 0)
            total_shortage_qty = mrp_result.get("summary", {}).get("total_shortage_qty", 0)
            
            # 条件 1: 短缺项数超过阈值
            items_threshold = getattr(self, "aps_shortage_threshold_items", 2)
            # 条件 2: 短缺比例过高（粗略估算）
            ratio_threshold = getattr(self, "aps_shortage_threshold_ratio", 0.5)
            
            trigger_aps = False
            reason = ""
            
            if shortage_count >= items_threshold:
                trigger_aps = True
                reason = f"短缺项数 {shortage_count} ≥ 阈值 {items_threshold}"
            
            if not trigger_aps and total_shortage_qty > 0:
                # 简化的短缺比例检查（总短缺量 / 总需求量粗略估计）
                total_gross_demand = sum(item["gross_demand"] for item in mrp_result["items"])
                if total_gross_demand > 0 and (total_shortage_qty / total_gross_demand) > ratio_threshold:
                    trigger_aps = True
                    reason = f"短缺比例 {(total_shortage_qty/total_gross_demand):.2f} 高于阈值 {ratio_threshold}"
            
            if trigger_aps:
                print(f'[智能联动] ⚡ {reason} → 触发 APS 自动重排...')
                try:
                    link = PPAPSLinker(None)  # 内存测试模式
                    plan_id = mrp_result.get("plan_id", "unknown")
                    aps_result = await link.trigger_aps_after_mrp(
                        plan_id=plan_id,
                        horizon_days=getattr(self, "aps_override_horizon_days", 7),
                        optimize_for=getattr(self, "aps_optimize_for", "delivery"),
                        auto_confirm=False,
                    )
                    print(f'[智能联动] ✅ APS 触发完成: {aps_result.get("message", "N/A")}')
                except Exception as e:
                    print(f'[智能联动] ❌ APS 触发异常: {e}')
        return mrp_result
    
    async def expand_bom(
        self,
        product_id: str,
        quantity: int,
        bom_version: str = None,
    ) -> List[Dict[str, Any]]:
        """
        展开BOM - 递归展开子部件
        
        Returns:
            List of materials with level information and quantities per parent product
        """
        if product_id not in self._bom_db:
            raise ValueError(f"产品 {product_id} 不存在，无BOM记录")
        
        bom_items = []
        
        # 直接从BOM数据库获取（实际项目支持版本控制）
        direct_components = self._bom_db[product_id]
        
        for comp in direct_components:
            # 计算该组件的总需求量
            required_qty = comp["quantity_per_parent"] * quantity
            
            bom_item = {
                "material_id": comp["material_id"],
                "material_code": comp["material_code"],
                "material_name": comp["material_name"],
                "unit": comp["unit"],
                "required_qty": required_qty,
                "quantity_per_parent": comp["quantity_per_parent"],
                "level": comp["level"],
                "parent_product_id": product_id,
            }
            
            bom_items.append(bom_item)
        
        # TODO: 递归展开多层BOM（当前只支持单层BOM）
        # 如果BOM中有子部件，需要进一步展开
        
        return bom_items
    
    async def check_inventory_availability(
        self,
        material_codes: List[str],
        warehouse_id: str = None,
    ) -> Dict[str, Dict[str, Any]]:
        """
        检查物料库存可用量
        
        Returns:
            {
                "RES-10K-0603": {
                    "available_qty": 10000,
                    "reserved_qty": 500,
                    "on_order_qty": 5000,
                    "lead_time_days": 7,
                    "safety_stock": 100,
                    "warehouse_id": "WH-MAIN-01",
                },
                ...
            }
        """
        availability = {}
        
        for material_code in material_codes:
            if material_code in self._inventory_db:
                inv = self._inventory_db[material_code]
                
                # 计算可用量 = 在库 - 预留（已在其他计划中占用）
                on_hand = inv.get("on_hand", 0)
                reserved = inv.get("reserved", 0)
                on_order = inv.get("on_order", 0)
                safety_stock = inv.get("safety_stock", 0)
                lead_time = inv.get("lead_time_days", 7)
                
                # 可用库存（不能立即动用的部分要扣除）
                available_qty = max(0, on_hand - reserved)
                
                availability[material_code] = {
                    "material_id": inv.get("material_id", material_code),
                    "material_code": material_code,
                    "available_qty": available_qty,
                    "on_hand": on_hand,
                    "reserved_qty": reserved,
                    "on_order_qty": on_order,
                    "total_potential": available_qty + on_order,  # 潜在可用量
                    "safety_stock": safety_stock,
                    "lead_time_days": lead_time,
                    "warehouse_id": inv.get("warehouse_id", ""),
                }
            else:
                # 如果没有库存记录，视为无库存
                availability[material_code] = {
                    "material_id": material_code,
                    "material_code": material_code,
                    "available_qty": 0,
                    "on_hand": 0,
                    "reserved_qty": 0,
                    "on_order_qty": 0,
                    "total_potential": 0,
                    "safety_stock": 0,
                    "lead_time_days": 7,
                    "warehouse_id": "",
                }
        
        return availability
    
    async def generate_purchase_suggestions(
        self,
        mrp_result: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        生成采购建议 - 根据净需求和批量规则生成建议
        
        Returns: List of purchase suggestions for短缺 materials
        """
        suggestions = []
        
        if "items" not in mrp_result:
            return suggestions
        
        for item in mrp_result["items"]:
            # 只有净需求大于0时才生成采购建议
            if item["net_demand"] > 0:
                suggestion = self._create_purchase_suggestion(item, mrp_result)
                suggestions.append(suggestion)
        
        return suggestions
    
    def _create_purchase_suggestion(
        self,
        item: Dict[str, Any],
        mrp_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """创建单个采购建议单"""
        material_code = item["material_code"]
        material_master = self._material_master.get(material_code, {})
        
        # 获取供应商信息
        supplier_id = material_master.get("preferred_supplier", "")
        supplier = self._supplier_db.get(supplier_id, {})
        
        # 计算建议采购量（考虑MOQ、EOQ、包装倍数）
        suggested_qty = self._calculate_optimal_order_qty(
            required_qty=item["net_demand"],
            moq=material_master.get("moq", 100),
            eoq=material_master.get("eoq", 1000),
            packing_unit=material_master.get("packing_unit", 1),
        )
        
        # 计算建议采购日期（考虑提前期）
        lead_time_days = item.get("lead_time_days", material_master.get("lead_time_days", 7))
        suggested_date = datetime.now() + timedelta(days=lead_time_days)
        
        # 估算成本
        unit_cost = material_master.get("unit_cost", 0)
        estimated_cost = suggested_qty * unit_cost
        
        # 确定优先级
        priority = self._determine_purchase_priority(
            shortage_qty=item["shortage_qty"],
            net_demand=item["net_demand"],
            lead_time_days=lead_time_days,
        )
        
        suggestion = {
            "id": str(uuid.uuid4()),
            "mrp_plan_id": mrp_result.get("id", ""),
            "material_id": item["material_id"],
            "material_code": material_code,
            "material_name": item["material_name"],
            "unit": item["unit"],
            "required_qty": item["gross_demand"],  # 毛需求
            "available_qty": item["available_qty"],
            "shortage_qty": item["shortage_qty"],
            "suggested_qty": suggested_qty,
            "suggested_date": suggested_date.strftime("%Y-%m-%d"),
            "priority": priority.value,
            "estimated_cost": round(estimated_cost, 2),
            "unit_cost": unit_cost,
            "supplier_id": supplier_id,
            "supplier_name": supplier.get("supplier_id", "未知"),
            "lead_time_days": lead_time_days,
            "warehouse_id": item.get("warehouse_id", ""),
        }
        
        return suggestion
    
    def _calculate_optimal_order_qty(
        self,
        required_qty: int,
        moq: int = 100,
        eoq: int = 1000,
        packing_unit: int = 1,
    ) -> int:
        """
        计算最优采购量
        
        考虑: 最小订单量(MOQ)、经济批量(EOQ)、包装倍数
        """
        if required_qty <= 0:
            return 0
        
        # 取最大值: 需求量、最小订单量、经济批量
        order_qty = max(required_qty, moq, eoq)
        
        # 向上取整到包装倍数的整数倍
        if order_qty % packing_unit != 0:
            order_qty = ((order_qty // packing_unit) + 1) * packing_unit
        
        return order_qty
    
    def _determine_purchase_priority(
        self,
        shortage_qty: int,
        net_demand: int,
        lead_time_days: int,
    ) -> PurchasePriority:
        """
        确定采购优先级
        
        规则:
        - 短缺量占净需求比例>50% 或 提前期>10天 → URGENT
        - 短缺量中等或提前期5-10天 → HIGH
        - 其他情况 → NORMAL
        """
        if shortage_qty > net_demand * 0.5 or lead_time_days > 10:
            return PurchasePriority.URGENT
        elif shortage_qty > net_demand * 0.2 or lead_time_days > 7:
            return PurchasePriority.HIGH
        else:
            return PurchasePriority.NORMAL
    
    async def calculate_optimal_order_qty(
        self,
        material_id: str,
        required_qty: int,
        moq: int = 100,  # 最小订单量
        eoq: int = 1000,  # 经济批量
        packing_unit: int = 1,  # 包装倍数
    ) -> int:
        """
        计算最优采购量
        
        考虑最小订单量(MOQ)、经济批量(EOQ)、包装倍数
        """
        return self._calculate_optimal_order_qty(
            required_qty=required_qty,
            moq=moq,
            eoq=eoq,
            packing_unit=packing_unit,
        )
    
    async def get_inventory_alerts(
        self,
        factory_id: str = None,
    ) -> List[Dict[str, Any]]:
        """
        获取库存预警
        
        - 安全库存不足
        - 即将过期
        - 长期呆滞
        """
        alerts = []
        
        for material_code, inv in self._inventory_db.items():
            available_qty = inv.get("on_hand", 0) - inv.get("reserved", 0)
            safety_stock = inv.get("safety_stock", 0)
            
            # 安全库存不足预警
            if available_qty < safety_stock:
                alerts.append({
                    "type": "low_stock",
                    "material_code": material_code,
                    "material_name": inv.get("material_name", material_code),
                    "current_qty": available_qty,
                    "safety_stock": safety_stock,
                    "shortage": safety_stock - available_qty,
                    "severity": "HIGH" if available_qty < safety_stock * 0.5 else "MEDIUM",
                    "warehouse_id": inv.get("warehouse_id", ""),
                })
            
            # 呆滞物料预警（简单判断：有库存但无BOM关联）
            if available_qty > 0 and available_qty < 100:
                is_in_bom = any(
                    material_code in bom_items 
                    for bom_items in self._bom_db.values()
                )
                if not is_in_bom:
                    alerts.append({
                        "type": "slow_moving",
                        "material_code": material_code,
                        "material_name": inv.get("material_name", material_code),
                        "current_qty": available_qty,
                        "severity": "LOW",
                    })
        
        return alerts
    
    def _get_material_cost(self, material_code: str) -> float:
        """获取物料单位成本"""
        material_master = self._material_master.get(material_code, {})
        return material_master.get("unit_cost", 0.0)
    
    async def get_mrp_history(self, limit: int = 50) -> List[Dict]:
        """获取MRP计算历史记录"""
        # 实际项目应从数据库读取
        return []


__all__ = ["MRPService", "MRPStatus", "PurchasePriority"]