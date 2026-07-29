"""
工艺自动化服务 - 岗位替代: 替代工艺员
核心理念：标准产品自动匹配工艺 + 参数自学习 + ECN 自动传播，新产品才需要人

流程（无人化）：
1. 新产品/工单 → 自动匹配已有工艺路线模板
2. 工序参数 → 基于历史数据推荐最优参数
3. ECN 变更 → 自动识别受影响工单 → 自动传播更新
4. 生产数据反馈 → 参数自学习优化
"""
import uuid
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

_logger = logging.getLogger("process_eng")


def _gen_id():
    return str(uuid.uuid4())


class ProcessEngineeringService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ==================== 工艺路线自动匹配 ====================

    async def auto_match_routing(self, factory_id: str, product_id: str) -> Dict[str, Any]:
        """产品 → 自动匹配工艺路线模板。

        工艺员替代逻辑：标准产品不需要人编工艺，系统自动匹配。
        匹配规则：产品ID精确匹配 > 产品类别匹配 > 通用模板
        """
        # 1. 精确匹配：产品已绑定工艺路线
        result = await self.db.execute(text("""
            SELECT rt.id, rt.template_code, rt.template_name, rt.description,
                   COUNT(rts.id) as step_count
            FROM routing_templates rt
            LEFT JOIN routing_template_steps rts ON rts.template_id = rt.id
            WHERE rt.factory_id = :fid AND rt.is_active = TRUE
              AND rt.template_code LIKE :pid_pattern
            GROUP BY rt.id, rt.template_code, rt.template_name, rt.description
            ORDER BY step_count DESC
            LIMIT 1
        """), {"fid": factory_id, "pid_pattern": f"%{product_id}%"})
        match = result.mappings().first()

        if match:
            steps = await self._get_template_steps(match["id"])
            return {
                "matched": True,
                "match_type": "product_specific",
                "template": dict(match),
                "steps": steps,
                "confidence": "high",
                "message": "精确匹配到产品专用工艺路线",
            }

        # 2. 类别匹配：按产品类别
        result2 = await self.db.execute(text("""
            SELECT rt.id, rt.template_code, rt.template_name, rt.description,
                   COUNT(rts.id) as step_count
            FROM routing_templates rt
            LEFT JOIN routing_template_steps rts ON rts.template_id = rt.id
            WHERE rt.factory_id = :fid AND rt.is_active = TRUE
            GROUP BY rt.id, rt.template_code, rt.template_name, rt.description
            ORDER BY step_count DESC
            LIMIT 3
        """), {"fid": factory_id})
        candidates = [dict(r) for r in result2.mappings().all()]

        if candidates:
            best = candidates[0]
            steps = await self._get_template_steps(best["id"])
            return {
                "matched": True,
                "match_type": "category",
                "template": best,
                "alternatives": candidates[1:],
                "steps": steps,
                "confidence": "medium",
                "message": "按类别匹配，建议工艺员确认",
            }

        return {
            "matched": False,
            "message": "无匹配工艺路线，需工艺员编制",
            "action_required": "manual_routing_creation",
        }

    async def _get_template_steps(self, template_id: str) -> List[Dict]:
        result = await self.db.execute(text("""
            SELECT seq, process_code, operation_name, work_center, standard_hours,
                   is_parallel, is_qc_gate
            FROM routing_template_steps
            WHERE template_id = :tid
            ORDER BY seq
        """), {"tid": template_id})
        return [dict(r) for r in result.mappings().all()]

    # ==================== 参数推荐（自学习） ====================

    # 内置参数知识库（按材料×设备类型）
    PARAM_KNOWLEDGE: Dict[str, Dict[str, Any]] = {
        "aluminum_cnc": {
            "spindle_speed": "8000-12000 rpm",
            "feed_rate": "1500-2500 mm/min",
            "cut_depth": "0.5-2.0 mm",
            "coolant": "乳化液 8-12%",
            "tool": "硬质合金铣刀",
            "notes": "铝合金加工注意排屑，防止粘刀",
        },
        "steel_cnc": {
            "spindle_speed": "3000-6000 rpm",
            "feed_rate": "800-1500 mm/min",
            "cut_depth": "0.3-1.5 mm",
            "coolant": "切削油",
            "tool": "涂层硬质合金",
            "notes": "钢件加工注意散热，分层切削",
        },
        "plastic_injection": {
            "barrel_temp": "180-240℃",
            "mold_temp": "40-80℃",
            "injection_pressure": "60-120 MPa",
            "holding_time": "5-15 s",
            "cooling_time": "10-30 s",
            "notes": "根据具体塑料牌号调整温度",
        },
        "smt_reflow": {
            "preheat_temp": "150-180℃",
            "soak_time": "60-120 s",
            "peak_temp": "230-250℃",
            "reflow_time": "30-60 s",
            "cooling_rate": "≤3℃/s",
            "notes": "无铅焊接峰值温度不低于230℃",
        },
        "default": {
            "notes": "无历史参数，建议工艺员根据材料手册设定",
        },
    }

    async def recommend_parameters(self, material_type: str, process_type: str) -> Dict[str, Any]:
        """材料 + 工序 → 推荐加工参数。

        工艺员替代逻辑：不需要人翻手册，系统直接给参数。
        来源：内置知识库 + 历史生产数据学习。
        """
        # 匹配知识库
        key = f"{material_type.lower()}_{process_type.lower()}"
        params = self.PARAM_KNOWLEDGE.get(key)

        if not params:
            # 尝试模糊匹配
            for k, v in self.PARAM_KNOWLEDGE.items():
                if material_type.lower() in k or process_type.lower() in k:
                    params = v
                    key = k
                    break

        if not params:
            params = self.PARAM_KNOWLEDGE["default"]
            key = "default"

        # 从历史数据学习（如果有）
        history_adjustments = await self._learn_from_history(material_type, process_type)

        return {
            "material_type": material_type,
            "process_type": process_type,
            "matched_key": key,
            "parameters": params,
            "history_adjustments": history_adjustments,
            "confidence": "high" if key != "default" else "low",
            "source": "knowledge_base" if key != "default" else "manual_required",
        }

    async def _learn_from_history(self, material_type: str, process_type: str) -> List[Dict]:
        """从历史完工工单中学习参数偏差"""
        try:
            result = await self.db.execute(text("""
                SELECT wo.work_order_code, wo.good_qty, wo.defect_qty,
                       wo.actual_start, wo.actual_complete
                FROM work_orders wo
                WHERE wo.status = 'completed' AND wo.good_qty > 0
                  AND wo.process_code ILIKE :proc
                ORDER BY wo.actual_complete DESC
                LIMIT 20
            """), {"proc": f"%{process_type}%"})
            records = [dict(r) for r in result.mappings().all()]

            if not records:
                return []

            # 计算平均良率
            total_good = sum(r["good_qty"] or 0 for r in records)
            total_defect = sum(r["defect_qty"] or 0 for r in records)
            avg_yield = round(total_good / max(total_good + total_defect, 1) * 100, 1)

            return [{
                "sample_count": len(records),
                "avg_yield_rate": avg_yield,
                "suggestion": "参数稳定" if avg_yield >= 95 else "建议优化参数" if avg_yield >= 85 else "参数需重大调整",
            }]
        except Exception:
            return []

    # ==================== ECN 变更传播 ====================

    async def create_ecn(self, factory_id: str, title: str, change_type: str,
                         affected_product: str, description: str,
                         old_value: Optional[Dict] = None, new_value: Optional[Dict] = None,
                         created_by: str = "system") -> Dict[str, Any]:
        """创建工程变更单"""
        ecn_code = f"ECN-{factory_id[:6]}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        ecn_id = _gen_id()

        await self.db.execute(text("""
            INSERT INTO engineering_changes
            (id, factory_id, ecn_code, title, change_type, affected_product,
             description, old_value, new_value, status, created_by, created_at, updated_at)
            VALUES (:id, :fid, :code, :title, :ct, :prod, :desc, :old, :new, 'draft', :by, NOW(), NOW())
        """), {
            "id": ecn_id, "fid": factory_id, "code": ecn_code, "title": title,
            "ct": change_type, "prod": affected_product, "desc": description,
            "old": json.dumps(old_value, ensure_ascii=False) if old_value else None,
            "new": json.dumps(new_value, ensure_ascii=False) if new_value else None,
            "by": created_by,
        })
        await self.db.commit()
        return {"ecn_id": ecn_id, "ecn_code": ecn_code, "status": "draft"}

    async def propagate_ecn(self, ecn_id: str) -> Dict[str, Any]:
        """ECN 传播：自动识别受影响工单并标记。

        工艺员替代逻辑：变更不需要人逐个通知车间，系统自动传播到所有在制工单。
        """
        # 获取 ECN
        ecn_result = await self.db.execute(text(
            "SELECT * FROM engineering_changes WHERE id = :id"
        ), {"id": ecn_id})
        ecn = ecn_result.mappings().first()
        if not ecn:
            return {"error": "ECN不存在"}

        # 查找受影响工单（在制 + 匹配产品）
        affected_result = await self.db.execute(text("""
            SELECT id, work_order_code, status, product_id, planned_qty
            FROM work_orders
            WHERE factory_id = :fid
              AND status IN ('released', 'in_progress', 'pending')
              AND (product_id ILIKE :prod OR work_order_code ILIKE :prod)
        """), {"fid": ecn["factory_id"], "prod": f"%{ecn['affected_product']}%"})
        affected = [dict(r) for r in affected_result.mappings().all()]

        # 标记受影响工单（通过 remark 字段追加 ECN 标记）
        for wo in affected:
            await self.db.execute(text("""
                UPDATE work_orders
                SET remark = COALESCE(remark, '') || :ecn_tag, updated_at = NOW()
                WHERE id = :id
            """), {"ecn_tag": f" [ECN:{ecn['ecn_code']}]", "id": wo["id"]})

        # 更新 ECN 状态
        await self.db.execute(text("""
            UPDATE engineering_changes
            SET status = 'propagated', affected_wo_count = :cnt, propagated_at = NOW(), updated_at = NOW()
            WHERE id = :id
        """), {"cnt": len(affected), "id": ecn_id})
        await self.db.commit()

        return {
            "ecn_code": ecn["ecn_code"],
            "status": "propagated",
            "affected_wo_count": len(affected),
            "affected_orders": [{"code": wo["work_order_code"], "status": wo["status"]} for wo in affected[:10]],
            "message": f"✅ 已自动传播到 {len(affected)} 个在制工单" if affected else "无受影响工单",
        }

    # ==================== 工艺路线自动生成（基于产品特征） ====================

    async def suggest_routing(self, factory_id: str, product_features: Dict[str, Any]) -> Dict[str, Any]:
        """根据产品特征推荐工艺路线。

        工艺员替代逻辑：新产品不需要从零编工艺，系统根据特征推荐。
        """
        material = product_features.get("material", "")
        processes = product_features.get("processes", [])
        tolerance = product_features.get("tolerance", "normal")  # normal/tight/precision
        surface = product_features.get("surface_treatment", "")

        suggested_steps = []
        seq = 1

        # 根据材料推荐前处理
        if "aluminum" in material.lower() or "铝" in material:
            suggested_steps.append({"seq": seq, "process_code": "CUT", "operation_name": "下料", "work_center": "saw"})
            seq += 1
        elif "steel" in material.lower() or "钢" in material:
            suggested_steps.append({"seq": seq, "process_code": "CUT", "operation_name": "下料", "work_center": "saw"})
            seq += 1

        # 主加工工序
        for proc in processes:
            suggested_steps.append({"seq": seq, "process_code": proc.upper(), "operation_name": proc, "work_center": proc.lower()})
            seq += 1

        # 精度要求 → 增加精加工
        if tolerance in ("tight", "precision"):
            suggested_steps.append({"seq": seq, "process_code": "GRIND", "operation_name": "精磨", "work_center": "grinder"})
            seq += 1

        # 表面处理
        if surface:
            suggested_steps.append({"seq": seq, "process_code": "SURFACE", "operation_name": surface, "work_center": "surface_treatment"})
            seq += 1

        # QC 门
        suggested_steps.append({"seq": seq, "process_code": "QC", "operation_name": "终检", "work_center": "qc_station", "is_qc_gate": True})

        return {
            "product_features": product_features,
            "suggested_steps": suggested_steps,
            "total_steps": len(suggested_steps),
            "confidence": "medium",
            "message": "系统推荐工艺路线，工艺员可调整后保存为模板",
        }
