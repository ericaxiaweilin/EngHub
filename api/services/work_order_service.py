"""
WorkOrder Service - 工单管理服务 v2
完整状态机 + 暂停/恢复/待入库 + 统计
"""
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from database.models import WorkOrder, ProductionReport, WoStatusLog, QualityInspection
from core.mes.work_order_coding import (
    generate_master_work_order_code,
    derive_operation_work_orders,
)


# ============================================================
# 状态审核门槛（默认模板：初期固定，后续可改为客户自定义配置）
# 因果关系：创建人不能下达自己工单（职责分离）；下达需管理角色；完工需品质确认
# ============================================================
ACTION_ROLE_GATES = {
    "release": ["factory_manager", "production_manager", "admin"],   # 下达需管理角色
    "complete": ["factory_manager", "quality_manager", "admin"],     # 完工需品质确认
    "close": ["factory_manager", "admin"],                           # 关闭需厂长/管理员
}


class WoPermissionError(Exception):
    """角色权限不足（路由层转 403，与业务错误 400 区分）"""
    pass


# ============================================================
# 工单状态枚举
# ============================================================
class WOStatus:
    DRAFT = "draft"              # 草稿
    PENDING = "pending"          # 待下发
    RELEASED = "released"        # 已下达
    IN_PROGRESS = "in_progress"  # 生产中
    ON_HOLD = "on_hold"          # 暂停
    PENDING_INBOUND = "pending_inbound"  # 待入库
    COMPLETED = "completed"      # 已完成
    CLOSED = "closed"            # 已关闭
    CANCELLED = "cancelled"      # 已取消

    ALL = [DRAFT, PENDING, RELEASED, IN_PROGRESS, ON_HOLD, PENDING_INBOUND, COMPLETED, CLOSED, CANCELLED]

    DISPLAY = {
        "draft": "草稿",
        "pending": "待下发",
        "released": "已下达",
        "in_progress": "生产中",
        "on_hold": "暂停",
        "pending_inbound": "待入库",
        "completed": "已完成",
        "closed": "已关闭",
        "cancelled": "已取消",
    }

    COLORS = {
        "draft": "default",
        "pending": "processing",
        "released": "blue",
        "in_progress": "blue",
        "on_hold": "warning",
        "pending_inbound": "cyan",
        "completed": "success",
        "closed": "default",
        "cancelled": "error",
    }

    # 状态转移规则：当前状态 -> 可转移到的状态
    TRANSITIONS = {
        "draft": ["pending", "cancelled"],
        "pending": ["released", "cancelled"],
        "released": ["in_progress", "on_hold", "cancelled"],
        "in_progress": ["on_hold", "pending_inbound", "completed", "cancelled"],
        "on_hold": ["in_progress", "cancelled"],
        "pending_inbound": ["completed"],
        "completed": [],
        "closed": [],
        "cancelled": [],
    }


# ============================================================
# 工单优先级
# ============================================================
class WOPriority:
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"

    DISPLAY = {
        "low": "低",
        "medium": "中",
        "high": "高",
        "urgent": "紧急",
    }

    COLORS = {
        "low": "default",
        "medium": "blue",
        "high": "orange",
        "urgent": "red",
    }


class WorkOrderService:
    """工单服务类 v2"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_work_order_by_id(self, work_order_id: str) -> Optional[WorkOrder]:
        # 预加载报工关联（selectin），避免 async 上下文中同步 lazy-load 报 MissingGreenlet
        result = await self.db.execute(
            select(WorkOrder)
            .where(WorkOrder.id == work_order_id)
            .options(selectinload(WorkOrder.production_reports))
        )
        return result.scalar_one_or_none()
    
    async def get_work_order_by_code(self, work_order_code: str) -> Optional[WorkOrder]:
        result = await self.db.execute(select(WorkOrder).where(WorkOrder.work_order_code == work_order_code))
        return result.scalar_one_or_none()

    # ============================================================
    # 审核机制辅助：角色门禁 / 状态日志 / 父子工单
    # ============================================================

    def _require_role(self, user, action: str):
        """动作角色门槛校验（默认审核模板，集中定义便于后续改可配置）"""
        allowed = ACTION_ROLE_GATES.get(action)
        if not allowed:
            return
        role = (getattr(user, "role", None) or "").strip()
        if getattr(user, "is_superuser", False) or role in allowed:
            return
        raise WoPermissionError(
            f"权限不足：「{action}」需要角色 {' / '.join(allowed)}，当前角色：{role or '(无)'}"
        )

    def _log_status(self, wo: WorkOrder, action: str, from_status: Optional[str],
                    to_status: str, user, comment: Optional[str] = None):
        """写状态操作日志（随主事务一起提交，不单独 commit；user 可为 User 对象或 username 字符串）"""
        if isinstance(user, str):
            operator, role = user or "system", ""
        else:
            operator = getattr(user, "username", None) or "system"
            role = getattr(user, "role", None) or ""
        self.db.add(WoStatusLog(
            work_order_id=wo.id,
            action=action,
            from_status=from_status,
            to_status=to_status,
            operator=operator,
            operator_role=role,
            comment=comment,
        ))

    async def _get_children(self, work_order_id: str) -> List[WorkOrder]:
        """取子工单（不含已取消，按创建时间排序）"""
        result = await self.db.execute(
            select(WorkOrder)
            .where(WorkOrder.parent_work_order_id == work_order_id)
            .where(WorkOrder.status != WOStatus.CANCELLED)
            .order_by(WorkOrder.created_at)
        )
        return list(result.scalars().all())

    def _aggregate_children_qty(self, children: List[WorkOrder]) -> Dict[str, int]:
        """汇总子工单数量：拆分型（无工序码，量被瓜分）求和；工序型（同一批量流经各工序）取最小值"""
        fields = ["completed_qty", "good_qty", "defect_qty", "scrap_qty"]
        if not children:
            return {f: 0 for f in fields}
        if all(not c.process_code for c in children):
            return {f: sum(int(getattr(c, f) or 0) for c in children) for f in fields}
        return {f: min(int(getattr(c, f) or 0) for c in children) for f in fields}

    async def _refresh_master_aggregates(self, master: WorkOrder):
        """子工单状态变化后刷新主工单汇总数量"""
        children = await self._get_children(master.id)
        if not children:
            return
        for k, v in self._aggregate_children_qty(children).items():
            setattr(master, k, v)
        master.updated_at = datetime.utcnow()

    async def get_status_logs(self, work_order_id: str) -> List[Dict[str, Any]]:
        """状态操作日志（审核追溯）"""
        result = await self.db.execute(
            select(WoStatusLog)
            .where(WoStatusLog.work_order_id == work_order_id)
            .order_by(WoStatusLog.created_at)
        )
        return [{
            "id": log.id,
            "action": log.action,
            "from_status": log.from_status,
            "to_status": log.to_status,
            "operator": log.operator,
            "operator_role": log.operator_role,
            "comment": log.comment,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        } for log in result.scalars().all()]

    async def get_children_detail(self, work_order_id: str) -> List[Dict[str, Any]]:
        """子工单列表（含进度）"""
        children = await self._get_children(work_order_id)
        out = []
        for c in children:
            d = self.to_dict(c)
            d["progress"] = await self.get_progress(c)
            out.append(d)
        return out
    
    async def create_work_order(
        self,
        factory_id: str,
        product_id: str,
        planned_qty: int,
        planned_due: datetime,
        priority: str = "medium",
        sales_order_id: Optional[str] = None,
        routing_id: Optional[str] = None,
        assigned_station_id: Optional[str] = None,
        bom_version: Optional[str] = None,
        remark: Optional[str] = None,
        created_by: Optional[str] = None,
        wo_type: str = "S",
        derive_operations: bool = True,
        routing_template_id: Optional[str] = None,
    ) -> WorkOrder:
        # 体系化编码：主工单码 = {PLANT}-{TYPE}{DATE}-{SEQ}（如 ELEC-S20260720-001）
        work_order_code = await generate_master_work_order_code(self.db, factory_id, wo_type=wo_type)

        work_order = WorkOrder(
            work_order_code=work_order_code,
            factory_id=factory_id,
            product_id=product_id,
            planned_qty=planned_qty,
            planned_due=planned_due,
            status=WOStatus.DRAFT,
            priority=priority,
            sales_order_id=sales_order_id,
            routing_id=routing_id,
            assigned_station_id=assigned_station_id,
            bom_version=bom_version,
            remark=remark,
            created_by=created_by,
            wo_type="master",
            routing_template_id=routing_template_id,
        )

        self.db.add(work_order)
        await self.db.flush()  # 先 flush 拿到主工单 id，供派生工序工单引用 parent_work_order_id
        self._log_status(work_order, "create", None, WOStatus.DRAFT, created_by)

        # 按工艺路线一次性派生全部工序工单（无工艺路线则仅主工单，向后兼容）
        if derive_operations:
            await derive_operation_work_orders(
                self.db, work_order, created_by=created_by or "system"
            )

        await self.db.commit()
        await self.db.refresh(work_order)
        return work_order
    
    async def _get_next_wo_number(self, factory_id: str) -> int:
        today = datetime.now().date()
        result = await self.db.execute(
            select(func.count(WorkOrder.id)).where(
                WorkOrder.factory_id == factory_id,
                func.date(WorkOrder.created_at) == today
            )
        )
        count = result.scalar() or 0
        return count + 1
    
    async def list_work_orders(
        self,
        factory_id: str,
        status: Optional[str] = None,
        product_id: Optional[str] = None,
        priority: Optional[str] = None,
        station_id: Optional[str] = None,
        wo_type: Optional[str] = "master",
        parent_work_order_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[WorkOrder]:
        query = select(WorkOrder).where(WorkOrder.factory_id == factory_id)
        
        # 工单层级过滤：默认只显示主工单，避免工序工单刷屏；传 "all" 不过滤
        if wo_type and wo_type != "all":
            query = query.where(WorkOrder.wo_type == wo_type)
        if parent_work_order_id:
            query = query.where(WorkOrder.parent_work_order_id == parent_work_order_id)
        if status:
            query = query.where(WorkOrder.status == status)
        if product_id:
            query = query.where(WorkOrder.product_id == product_id)
        if priority:
            query = query.where(WorkOrder.priority == priority)
        if station_id:
            query = query.where(WorkOrder.assigned_station_id == station_id)
        
        query = query.order_by(WorkOrder.created_at.desc()).offset(skip).limit(limit)
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def get_stats(self, factory_id: str) -> Dict[str, Any]:
        """获取工单统计"""
        total = await self.db.execute(
            select(func.count(WorkOrder.id)).where(WorkOrder.factory_id == factory_id)
        )
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_count = await self.db.execute(
            select(func.count(WorkOrder.id)).where(
                WorkOrder.factory_id == factory_id,
                WorkOrder.created_at >= today_start,
            )
        )
        in_progress = await self.db.execute(
            select(func.count(WorkOrder.id)).where(
                WorkOrder.factory_id == factory_id,
                WorkOrder.status == WOStatus.IN_PROGRESS,
            )
        )
        overdue = await self.db.execute(
            select(func.count(WorkOrder.id)).where(
                WorkOrder.factory_id == factory_id,
                WorkOrder.status.in_([WOStatus.IN_PROGRESS, WOStatus.ON_HOLD]),
                WorkOrder.planned_due < datetime.utcnow(),
            )
        )
        completed_today = await self.db.execute(
            select(func.count(WorkOrder.id)).where(
                WorkOrder.factory_id == factory_id,
                WorkOrder.status == WOStatus.COMPLETED,
                WorkOrder.updated_at >= today_start,
            )
        )
        pending = await self.db.execute(
            select(func.count(WorkOrder.id)).where(
                WorkOrder.factory_id == factory_id,
                WorkOrder.status == WOStatus.PENDING,
            )
        )
        
        # 注意：Result.scalar() 读取后即关闭，不能对同一 Result 重复调用，
        # 先统一提取到局部变量再组装返回值
        total_v = total.scalar() or 0
        today_new = today_count.scalar() or 0
        in_progress_v = in_progress.scalar() or 0
        overdue_v = overdue.scalar() or 0
        completed_today_v = completed_today.scalar() or 0
        pending_v = pending.scalar() or 0

        return {
            "total": total_v,
            "today_new": today_new,
            "in_progress": in_progress_v,
            "overdue_risk": overdue_v,
            "completed_today": completed_today_v,
            "pending_release": pending_v,
            "completion_rate_24h": round(
                (completed_today_v / max(today_new, 1)) * 100
            ),
        }
    
    async def update_work_order(
        self, work_order_id: str, **kwargs
    ) -> Optional[WorkOrder]:
        work_order = await self.get_work_order_by_id(work_order_id)
        if not work_order:
            return None
        
        if work_order.status in [WOStatus.COMPLETED, WOStatus.CLOSED, WOStatus.CANCELLED]:
            raise ValueError(f"Cannot update work order with status {work_order.status}")
        
        allowed_fields = [
            "planned_qty", "planned_due", "priority", "assigned_station_id",
            "routing_id", "bom_version", "remark",
        ]
        
        for field in allowed_fields:
            if field in kwargs and kwargs[field] is not None:
                setattr(work_order, field, kwargs[field])
        
        work_order.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(work_order)
        return work_order
    
    async def release_work_order(self, work_order_id: str, user=None) -> Optional[WorkOrder]:
        """待下发 → 已下达（审核门槛：管理角色 + 职责分离：创建人不能下达自己的工单）"""
        work_order = await self.get_work_order_by_id(work_order_id)
        if not work_order:
            return None
        
        if work_order.status != WOStatus.DRAFT:
            raise ValueError(f"只能下达草稿状态的工单，当前状态: {work_order.status}")
        
        # 审核门槛 1：角色（生产经理 / 厂长）
        self._require_role(user, "release")
        # 审核门槛 2：职责分离 —— 创建人不能下达自己创建的工单（admin 也不例外）
        operator = getattr(user, "username", None) or "system"
        if work_order.created_by and work_order.created_by == operator:
            raise ValueError("职责分离：创建人不能下达自己创建的工单，请由其他管理人员下达")
        
        from_status = work_order.status
        work_order.status = WOStatus.RELEASED
        work_order.planned_start = datetime.utcnow()
        work_order.released_by = operator
        work_order.updated_at = datetime.utcnow()
        self._log_status(work_order, "release", from_status, WOStatus.RELEASED, user)
        
        await self.db.commit()
        await self.db.refresh(work_order)
        return work_order
    
    async def _check_prerequisite_steps(self, work_order: WorkOrder) -> bool:
        """
        工序依赖锁止检查 - 第2号缺陷修复
        
        对于工序工单（operation），在开工前检查前一道工序是否已开始生产。
        规则：当前步骤 seq > 1 时，必须有至少一个前序步骤的工单处于 in_progress/completed 状态。
        
        返回: True 可通过，False 被阻断
        """
        # 主工单无需检查前序（它是根工序）
        if work_order.wo_type == "master":
            return True
        
        # 工序工单：检查 current_routing_step 的前序
        step_seq = work_order.current_routing_step
        if step_seq is None or step_seq <= 1:
            # 第一步或无步序标记，允许开工
            return True
        
        factory_id = work_order.factory_id
        routing_template_id = work_order.routing_template_id
        
        if not routing_template_id:
            # 没有绑定模板，按宽松模式处理（可能使用旧式 Routing.steps）
            return True
        
        # 查询该路由模板的前一个步骤（step_seq - 1）的所有操作工单
        from database.models import WorkOrder as WOModel
        
        prev_step_query = select(WOModel).where(
            WOModel.routing_template_id == routing_template_id,
            WOModel.current_routing_step == step_seq - 1,
            WOModel.wo_type == "operation",
            WOModel.factory_id == factory_id,
            WOModel.status.in_([WOStatus.RELEASED.value, WOStatus.IN_PROGRESS.value, WOStatus.COMPLETED.value])
        )
        
        result = await self.db.execute(prev_step_query)
        has_prev_started = result.scalar_one_or_none() is not None
        
        if not has_prev_started:
            # 检查是否有前序工单但尚未开始（用于提供错误信息）
            pending_prev_query = select(WOModel).where(
                WOModel.routing_template_id == routing_template_id,
                WOModel.current_routing_step == step_seq - 1,
                WOModel.wo_type == "operation",
                WOModel.factory_id == factory_id,
                WOModel.status.in_([WOStatus.PENDING.value, WOStatus.RELEASED.value])
            )
            pending_result = await self.db.execute(pending_prev_query)
            pending_prev = pending_prev_query.scalars().all()
            
            if pending_prev:
                pending_codes = ", ".join(wo.work_order_code for wo in pending_prev[:3])
                raise ValueError(
                    f"工序锁止：步骤 {step_seq-1} 尚未开始生产（工单：{pending_codes}等）。"
                    f"请先让前道工序开工后，再执行本工单 {work_order.work_order_code} 的步骤 {step_seq}。"
                )
            else:
                # 前序步骤没有任何工单（可能未派生），也视为阻塞
                raise ValueError(
                    f"工序锁止：步骤 {step_seq-1} 无待开工工单。"
                    "请检查工艺路线是否正确派生了前序工序工单。"
                )
        
        return True
    
    async def start_work_order(self, work_order_id: str, user=None) -> Optional[WorkOrder]:
        """已下达 → 生产中（父子约束+工序依赖锁止：含子工单的主工单不直接生产）"""
        work_order = await self.get_work_order_by_id(work_order_id)
        if not work_order:
            return None
        
        if work_order.status not in [WOStatus.PENDING, WOStatus.RELEASED]:
            raise ValueError(f"只能开工待下发/已下达的工单，当前状态: {work_order.status}")
        
        # 【新增】工序依赖锁止 - 确保按工艺顺序执行（第2号缺陷修复）
        await self._check_prerequisite_steps(work_order)
        
        # 父子约束：已拆分的主工单由子工单分别组织生产，进度自动汇总
        children = await self._get_children(work_order_id)
        if children:
            codes = "、".join(c.work_order_code for c in children[:5])
            raise ValueError(f"该工单已拆分为 {len(children)} 个子工单（{codes}），请对子工单分别开工，主工单进度自动汇总")
        
        from_status = work_order.status
        work_order.status = WOStatus.IN_PROGRESS
        work_order.actual_start = datetime.utcnow()
        work_order.updated_at = datetime.utcnow()
        self._log_status(work_order, "start", from_status, WOStatus.IN_PROGRESS, user)
        
        await self.db.commit()
        await self.db.refresh(work_order)
        return work_order
    
    async def pause_work_order(self, work_order_id: str, reason: str = "", user=None) -> Optional[WorkOrder]:
        """生产中 → 暂停"""
        work_order = await self.get_work_order_by_id(work_order_id)
        if not work_order:
            return None
        
        if work_order.status != WOStatus.IN_PROGRESS:
            raise ValueError(f"只能暂停生产中的工单，当前状态: {work_order.status}")
        
        from_status = work_order.status
        work_order.status = WOStatus.ON_HOLD
        work_order.updated_at = datetime.utcnow()
        if reason:
            work_order.remark = f"{work_order.remark or ''}\n[暂停]: {reason}"
        self._log_status(work_order, "pause", from_status, WOStatus.ON_HOLD, user, comment=reason or None)
        
        await self.db.commit()
        await self.db.refresh(work_order)
        return work_order
    
    async def resume_work_order(self, work_order_id: str, reason: str = "", user=None) -> Optional[WorkOrder]:
        """暂停 → 生产中"""
        work_order = await self.get_work_order_by_id(work_order_id)
        if not work_order:
            return None
        
        if work_order.status != WOStatus.ON_HOLD:
            raise ValueError(f"只能恢复暂停的工单，当前状态: {work_order.status}")
        
        from_status = work_order.status
        work_order.status = WOStatus.IN_PROGRESS
        work_order.updated_at = datetime.utcnow()
        if reason:
            work_order.remark = f"{work_order.remark or ''}\n[恢复]: {reason}"
        self._log_status(work_order, "resume", from_status, WOStatus.IN_PROGRESS, user, comment=reason or None)
        
        await self.db.commit()
        await self.db.refresh(work_order)
        return work_order
    
    async def mark_pending_inbound(self, work_order_id: str, user=None) -> Optional[WorkOrder]:
        """生产中 → 待入库"""
        work_order = await self.get_work_order_by_id(work_order_id)
        if not work_order:
            return None
        
        if work_order.status != WOStatus.IN_PROGRESS:
            raise ValueError(f"只能将生产中的工单标记为待入库，当前状态: {work_order.status}")
        
        from_status = work_order.status
        work_order.status = WOStatus.PENDING_INBOUND
        work_order.updated_at = datetime.utcnow()
        self._log_status(work_order, "pending_inbound", from_status, WOStatus.PENDING_INBOUND, user)
        
        await self.db.commit()
        await self.db.refresh(work_order)
        return work_order
    
    async def complete_work_order(
        self, 
        work_order_id: str,
        completed_qty: Optional[int] = None,
        good_qty: Optional[int] = None,
        defect_qty: Optional[int] = None,
        user=None,
    ) -> Optional[WorkOrder]:
        """生产中/待入库 → 已完成（审核门槛：品质角色 + 实际产出 + 父子完工约束）"""
        work_order = await self.get_work_order_by_id(work_order_id)
        if not work_order:
            return None
        
        # 审核门槛 1：品质确认（厂长 / 品质经理）
        self._require_role(user, "complete")
        
        children = await self._get_children(work_order_id)
        if children:
            # 父子约束：主工单自身不生产，须全部子工单完工后才能完工，数量自动汇总
            unfinished = [c for c in children if c.status not in [WOStatus.COMPLETED, WOStatus.CLOSED]]
            if unfinished:
                codes = "、".join(
                    f"{c.work_order_code}（{WOStatus.DISPLAY.get(c.status, c.status)}）" for c in unfinished
                )
                raise ValueError(f"子工单未全部完工，主工单不可完工。未完工子工单：{codes}")
            if work_order.status not in [WOStatus.RELEASED, WOStatus.IN_PROGRESS, WOStatus.PENDING_INBOUND]:
                raise ValueError(f"只能完成已下达/生产中/待入库的工单，当前状态: {work_order.status}")
            # 数量由子工单自动汇总，不接受手工传入
            for k, v in self._aggregate_children_qty(children).items():
                setattr(work_order, k, v)
        else:
            if work_order.status not in [WOStatus.IN_PROGRESS, WOStatus.PENDING_INBOUND]:
                raise ValueError(f"只能完成生产中/待入库的工单，当前状态: {work_order.status}")
            if completed_qty is not None:
                work_order.completed_qty = completed_qty
            if good_qty is not None:
                work_order.good_qty = good_qty
            if defect_qty is not None:
                work_order.defect_qty = defect_qty
        
        # 审核门槛 2：有实际产出才能完工
        if not (work_order.completed_qty or 0) > 0:
            raise ValueError("完工数量为 0：无实际产出不能完工（请先报工）")
        
        # 【新增】品质检验 gate - 关键业务流程控制
        # 对于关联了工艺路线的工单，必须完成所有QC控制点的检验才能完工
        if work_order.routing_id:
            from database.models import QualityInspection
            
            # 至少需要有一份该工单的检验记录且结果为 PASS（合格）
            # IPQC（过程检验）用于工序工单，FQC（最终检验）用于主工单
            required_types = []
            if work_order.wo_type == "operation":
                required_types = ["ipqc"]  # 工序工单需要IPQC
            else:
                required_types = ["fqc"]   # 主工单需要FQC
            
            inspect_check = await self.db.execute(
                select(QualityInspection).where(
                    QualityInspection.work_order_id == work_order.id,
                    QualityInspection.result == "PASS",
                    QualityInspection.inspect_type.in_(required_types)
                )
            )
            
            if not inspect_check.first():
                type_name = "IPQC（过程检验）" if work_order.wo_type == "operation" else "FQC（最终检验）"
                raise ValueError(
                    f"工单 {work_order.work_order_code} 必须先通过{type_name}才能完工。"
                    "请先创建并提交对应检验单，结果必须为合格（PASS）。"
                )
                # 如果是IPQC类型的工单（工序工单），需要IPQC检验通过
                if work_order.process_code:
                    raise ValueError(
                        f"工序工单 {work_order.work_order_code} 必须先通过IPQC检验才能完工。"
                        "请创建并提交IPQC检验单，状态为合格后方可完工。"
                    )
                # 如果是主工单，需要FQC检验通过
                else:
                    raise ValueError(
                        f"主工单 {work_order.work_order_code} 必须先通过最终检验（FQC）才能完工。"
                        "请创建并提交FQC检验单，状态为合格后方可完工。"
                    )
        
        from_status = work_order.status
        work_order.status = WOStatus.COMPLETED
        work_order.actual_complete = datetime.utcnow()
        work_order.updated_at = datetime.utcnow()
        work_order.completed_by = getattr(user, "username", None) or "system"
        self._log_status(work_order, "complete", from_status, WOStatus.COMPLETED, user)
        
        # 子工单完工后自动刷新主工单汇总数量
        if work_order.parent_work_order_id:
            master = await self.get_work_order_by_id(work_order.parent_work_order_id)
            if master and master.status not in [WOStatus.COMPLETED, WOStatus.CLOSED, WOStatus.CANCELLED]:
                await self._refresh_master_aggregates(master)
        
        await self.db.commit()
        await self.db.refresh(work_order)
        return work_order
    
    async def close_work_order(self, work_order_id: str, user=None) -> Optional[WorkOrder]:
        """已完成 → 已关闭（审核门槛：厂长 / 管理员）"""
        work_order = await self.get_work_order_by_id(work_order_id)
        if not work_order:
            return None
        
        if work_order.status != WOStatus.COMPLETED:
            raise ValueError(f"只能关闭已完成的工单，当前状态: {work_order.status}")
        
        self._require_role(user, "close")
        
        from_status = work_order.status
        work_order.status = WOStatus.CLOSED
        work_order.updated_at = datetime.utcnow()
        self._log_status(work_order, "close", from_status, WOStatus.CLOSED, user)
        
        await self.db.commit()
        await self.db.refresh(work_order)
        return work_order
    
    async def cancel_work_order(self, work_order_id: str, reason: str, user=None) -> Optional[WorkOrder]:
        """取消工单（draft/pending/released/in_progress/on_hold 均可取消）"""
        work_order = await self.get_work_order_by_id(work_order_id)
        if not work_order:
            return None
        
        if work_order.status in [WOStatus.COMPLETED, WOStatus.CLOSED, WOStatus.CANCELLED]:
            raise ValueError(f"无法取消 {work_order.status} 状态的工单")
        
        from_status = work_order.status
        work_order.status = WOStatus.CANCELLED
        work_order.updated_at = datetime.utcnow()
        if reason:
            work_order.remark = f"{work_order.remark or ''}\n[取消]: {reason}"
        self._log_status(work_order, "cancel", from_status, WOStatus.CANCELLED, user, comment=reason or None)
        
        await self.db.commit()
        await self.db.refresh(work_order)
        return work_order
    
    async def split_work_order(
        self,
        work_order_id: str,
        split_qty: int,
        remark: Optional[str] = None,
        created_by: Optional[str] = None,
        user=None,
    ) -> tuple[WorkOrder, WorkOrder]:
        """拆分工单：新工单作为子工单挂在当前工单下（parent_work_order_id），量从主工单扣减。

        子工单编码 {主工单码}-SPL{nn}，无工序码 → 主工单数量按「求和」汇总。
        """
        original_wo = await self.get_work_order_by_id(work_order_id)
        if not original_wo:
            raise ValueError("Work order not found")
        
        if original_wo.status not in [WOStatus.DRAFT, WOStatus.PENDING, WOStatus.RELEASED]:
            raise ValueError(f"只能拆分草稿/待下发/已下达的工单")
        
        if split_qty >= original_wo.planned_qty:
            raise ValueError("拆分数量必须小于计划数量")
        
        # 已有子工单数（含已取消，保证编码唯一）→ SPL 序号
        existing = await self.db.execute(
            select(func.count(WorkOrder.id)).where(WorkOrder.parent_work_order_id == original_wo.id)
        )
        child_seq = (existing.scalar() or 0) + 1
        child_code = f"{original_wo.work_order_code}-SPL{child_seq:02d}"
        
        new_wo = WorkOrder(
            work_order_code=child_code,
            factory_id=original_wo.factory_id,
            product_id=original_wo.product_id,
            planned_qty=split_qty,
            unit=original_wo.unit,
            planned_due=original_wo.planned_due,
            priority=original_wo.priority,
            status=WOStatus.DRAFT,
            sales_order_id=original_wo.sales_order_id,
            routing_id=original_wo.routing_id,
            assigned_station_id=original_wo.assigned_station_id,
            bom_version=original_wo.bom_version,
            wo_type="operation",
            parent_work_order_id=original_wo.id,
            remark=f"Split from {original_wo.work_order_code}. {remark or ''}",
            created_by=created_by,
        )
        self.db.add(new_wo)
        
        original_wo.planned_qty -= split_qty
        original_wo.wo_type = "master"
        original_wo.remark = f"{original_wo.remark or ''}\n[Split]: Created {child_code} with qty {split_qty}"
        original_wo.updated_at = datetime.utcnow()
        self._log_status(
            original_wo, "split", original_wo.status, original_wo.status, user,
            comment=f"拆分子工单 {child_code}（数量 {split_qty}）",
        )
        
        await self.db.commit()
        await self.db.refresh(original_wo)
        await self.db.refresh(new_wo)
        
        return original_wo, new_wo
    
    async def get_progress(self, work_order: WorkOrder) -> Dict[str, Any]:
        """计算工单进度信息"""
        planned_qty = work_order.planned_qty or 0
        completed_qty = work_order.completed_qty or 0
        good_qty = work_order.good_qty or 0
        defect_qty = work_order.defect_qty or 0
        
        progress_rate = round((completed_qty / planned_qty * 100) if planned_qty > 0 else 0, 1)
        yield_rate = round((good_qty / completed_qty * 100) if completed_qty > 0 else 0, 1)
        
        # 估算剩余时间（基于实际开工时间和当前进度）
        remaining_time = None
        if work_order.actual_start and completed_qty > 0:
            elapsed = datetime.utcnow() - work_order.actual_start
            rate_per_hour = completed_qty / max(elapsed.total_seconds() / 3600, 0.01)
            remaining_qty = planned_qty - completed_qty
            if remaining_qty > 0 and rate_per_hour > 0:
                remaining_hours = remaining_qty / rate_per_hour
                remaining_time = f"{int(remaining_hours)}h {int(remaining_hours % 1 * 60)}m"
        
        return {
            "progress_rate": progress_rate,
            "yield_rate": yield_rate,
            "remaining_qty": max(planned_qty - completed_qty, 0),
            "remaining_time": remaining_time,
            "is_overdue": work_order.planned_due is not None and work_order.planned_due < datetime.utcnow()
                           and work_order.status not in [WOStatus.COMPLETED, WOStatus.CLOSED, WOStatus.CANCELLED],
        }
    
    def to_dict(self, wo: WorkOrder) -> Dict[str, Any]:
        """工单转字典"""
        return {
            "id": str(wo.id),
            "work_order_code": wo.work_order_code,
            "factory_id": wo.factory_id,
            "sales_order_id": wo.sales_order_id,
            "product_id": wo.product_id,
            "routing_id": wo.routing_id,
            "planned_qty": wo.planned_qty,
            "unit": wo.unit,
            "completed_qty": wo.completed_qty,
            "good_qty": wo.good_qty,
            "defect_qty": wo.defect_qty,
            "scrap_qty": wo.scrap_qty,
            "status": wo.status,
            "status_text": WOStatus.DISPLAY.get(wo.status, wo.status),
            "priority": wo.priority,
            "priority_text": WOPriority.DISPLAY.get(wo.priority, wo.priority),
            "planned_start": wo.planned_start.isoformat() if wo.planned_start else None,
            "planned_due": wo.planned_due.isoformat() if wo.planned_due else None,
            "actual_start": wo.actual_start.isoformat() if wo.actual_start else None,
            "actual_complete": wo.actual_complete.isoformat() if wo.actual_complete else None,
            "assigned_station_id": wo.assigned_station_id,
            "current_routing_step": wo.current_routing_step,
            "bom_version": wo.bom_version,
            "wo_type": wo.wo_type,
            "process_code": wo.process_code,
            "operation_seq": wo.operation_seq,
            "parent_work_order_id": wo.parent_work_order_id,
            "created_by": wo.created_by,
            "updated_by": wo.updated_by,
            "released_by": wo.released_by,
            "completed_by": wo.completed_by,
            "remark": wo.remark,
            "created_at": wo.created_at.isoformat() if wo.created_at else None,
            "updated_at": wo.updated_at.isoformat() if wo.updated_at else None,
        }

    # ==================== 增强的拆单功能 ====================
    
    async def split_preview(
        self,
        work_order_id: str,
        method: str = "simple",
        parameters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """拆分预览：模拟并返回拟生成的工单列表，支持多种模式"""
        from sqlalchemy import json
        
        original_wo = await self.get_work_order_by_id(work_order_id)
        if not original_wo:
            raise ValueError("Work order not found")
        
        if method == "simple":
            if not parameters or "split_qty" not in parameters:
                raise ValueError("Specify 'split_qty' for simple split mode")
            split_qty = parameters["split_qty"]
            if split_qty >= original_wo.planned_qty:
                raise ValueError("Split quantity must be less than planned quantity")
            
            child_seq = await self._count_children(original_wo.id) + 1
            child_code = f"{original_wo.work_order_code}-SPL{child_seq:02d}"
            
            return {
                "method": "simple",
                "master_wo": {"code": original_wo.work_order_code, "new_planned_qty": original_wo.planned_qty - split_qty},
                "children": [{"code": child_code, "planned_qty": split_qty, "status": "draft"}],
                "total_children": 1,
            }
        
        elif method == "by_routing":
            routing_id = original_wo.routing_id
            if not routing_id:
                raise ValueError("No routing assigned to this work order")
            
            steps_stmt = select(RoutingTemplateStep).where(RoutingTemplateStep.routing_template_id == routing_id)
            steps_result = await self.db.execute(steps_stmt)
            steps = steps_result.scalars().all()
            
            if not steps:
                raise ValueError("No routing steps defined")
            
            children = []
            for i, step in enumerate(steps):
                child_code = f"{original_wo.work_order_code}-{step.step_code:03d}"
                children.append({
                    "code": child_code, "planned_qty": original_wo.planned_qty,
                    "station_id": step.station_id, "process_code": step.process_code,
                    "operation_seq": step.sequence, "status": "draft"
                })
            
            return {"method": "by_routing", "master_wo": {"code": original_wo.work_order_code, "new_planned_qty": original_wo.planned_qty},
                   "children": children, "total_children": len(children)}
        
        elif method == "by_batch":
            if not parameters or "batch_size" not in parameters:
                raise ValueError("Specify 'batch_size' for batch split mode")
            batch_size = parameters["batch_size"]
            if batch_size <= 0:
                raise ValueError("Batch size must be positive")
            
            children = []
            remaining = original_wo.planned_qty
            batch_num = 1
            
            while remaining > 0:
                qty = min(batch_size, remaining)
                child_code = f"{original_wo.work_order_code}-BATCH{batch_num:03d}"
                children.append({"code": child_code, "planned_qty": qty, "batch_number": batch_num, "status": "draft"})
                remaining -= qty
                batch_num += 1
            
            return {"method": "by_batch", "master_wo": {"code": original_wo.work_order_code, "new_planned_qty": 0},
                   "children": children, "total_children": len(children), "batch_count": len(children)}
        
        elif method == "by_ratio":
            if not parameters or "ratios" not in parameters:
                raise ValueError("Specify 'ratios' array for ratio split mode")
            ratios = parameters["ratios"]
            total_ratio = sum(ratios)
            if total_ratio <= 0:
                raise ValueError("Total ratio must be greater than zero")
            
            children = []
            for i, ratio in enumerate(ratios):
                qty = round(original_wo.planned_qty * ratio / total_ratio)
                if qty == 0 and original_wo.planned_qty > 0:
                    qty = 1
                child_code = f"{original_wo.work_order_code}-R{i+1:02d}"
                children.append({"code": child_code, "planned_qty": qty, "ratio": ratio, "status": "draft"})
            
            total_split = sum(c["planned_qty"] for c in children)
            if total_split < original_wo.planned_qty and children:
                children[-1]["planned_qty"] += original_wo.planned_qty - total_split
            
            return {"method": "by_ratio", "master_wo": {"code": original_wo.work_order_code, "new_planned_qty": 0},
                   "children": children, "total_children": len(children), "total_ratio": total_ratio}
        
        else:
            raise ValueError(f"Unknown split method: {method}")
    
    async def _count_children(self, parent_id: str) -> int:
        result = await self.db.execute(select(func.count(WorkOrder.id)).where(WorkOrder.parent_work_order_id == parent_id))
        return result.scalar() or 0
    
    async def split_advanced(
        self, work_order_id: str, method: str = "simple", parameters: Dict = None, operator: str = "system", remark: str = ""
    ) -> Dict[str, Any]:
        """高级拆分执行函数 - 支持多种模式并持久化到数据库"""
        parameters = parameters or {}
        original_wo = await self.get_work_order_by_id(work_order_id)
        if not original_wo:
            raise ValueError("Work order not found")
        if original_wo.status not in [WOStatus.DRAFT, WOStatus.PENDING, WOStatus.RELEASED]:
            raise ValueError("只能拆分草稿/待下发/已下达的工单")
        
        children_created = []
        
        if method == "simple":
            split_qty = parameters.get("split_qty")
            if not split_qty or split_qty >= original_wo.planned_qty:
                raise ValueError("Invalid split quantity")
            child_seq = await self._count_children(original_wo.id) + 1
            child_code = f"{original_wo.work_order_code}-SPL{child_seq:02d}"
            new_wo = WorkOrder(work_order_code=child_code, factory_id=original_wo.factory_id, product_id=original_wo.product_id,
                               planned_qty=split_qty, unit=original_wo.unit, planned_due=original_wo.planned_due, priority=original_wo.priority,
                               status=WOStatus.DRAFT, sales_order_id=original_wo.sales_order_id, routing_id=original_wo.routing_id,
                               assigned_station_id=original_wo.assigned_station_id, bom_version=original_wo.bom_version, wo_type="operation",
                               parent_work_order_id=original_wo.id, remark=f"Split from {original_wo.work_order_code}. {remark or ''}", created_by=operator)
            self.db.add(new_wo)
            children_created.append(new_wo)
            original_wo.planned_qty -= split_qty
            original_wo.wo_type = "master"
            original_wo.remark = f"{original_wo.remark or ''}\n[Split]: Created {child_code} with qty {split_qty}"
            original_wo.updated_at = datetime.utcnow()
        
        elif method == "by_routing":
            routing_id = original_wo.routing_id
            if not routing_id:
                raise ValueError("No routing assigned to this work order")
            steps_stmt = select(RoutingTemplateStep).where(RoutingTemplateStep.routing_template_id == routing_id).order_by(RoutingTemplateStep.sequence)
            steps_result = await self.db.execute(steps_stmt)
            steps = steps_result.scalars().all()
            for i, step in enumerate(steps):
                child_code = f"{original_wo.work_order_code}-{step.step_code:03d}"
                existing = await self.db.execute(select(WorkOrder).where(WorkOrder.parent_work_order_id == original_wo.id, WorkOrder.work_order_code == child_code))
                if existing.scalar(): continue
                new_wo = WorkOrder(work_order_code=child_code, factory_id=original_wo.factory_id, product_id=original_wo.product_id,
                                   planned_qty=original_wo.planned_qty, unit=original_wo.unit, planned_due=original_wo.planned_due, priority=original_wo.priority,
                                   status=WOStatus.DRAFT, sales_order_id=original_wo.sales_order_id, routing_id=routing_id, assigned_station_id=step.station_id,
                                   bom_version=original_wo.bom_version, wo_type="operation", parent_work_order_id=original_wo.id,
                                   process_code=step.process_code, operation_seq=i + 1, remark=f"Routing split for step {step.step_code}. {remark or ''}", created_by=operator)
                self.db.add(new_wo)
                children_created.append(new_wo)
            original_wo.wo_type = "master"
            original_wo.updated_at = datetime.utcnow()
        
        elif method == "by_batch":
            batch_size = parameters.get("batch_size")
            if not batch_size or batch_size <= 0:
                raise ValueError("Invalid batch size")
            remaining = original_wo.planned_qty
            batch_num = 1
            while remaining > 0:
                qty = min(batch_size, remaining)
                child_code = f"{original_wo.work_order_code}-BATCH{batch_num:03d}"
                new_wo = WorkOrder(work_order_code=child_code, factory_id=original_wo.factory_id, product_id=original_wo.product_id,
                                   planned_qty=qty, unit=original_wo.unit, planned_due=original_wo.planned_due, priority=original_wo.priority,
                                   status=WOStatus.DRAFT, sales_order_id=original_wo.sales_order_id, routing_id=original_wo.routing_id,
                                   assigned_station_id=original_wo.assigned_station_id, bom_version=original_wo.bom_version, wo_type="operation",
                                   parent_work_order_id=original_wo.id, batch_number=batch_num, remark=f"Batch split #{batch_num}. {remark or ''}", created_by=operator)
                self.db.add(new_wo)
                children_created.append(new_wo)
                remaining -= qty
                batch_num += 1
            original_wo.planned_qty = 0
            original_wo.wo_type = "master"
            original_wo.updated_at = datetime.utcnow()
        
        elif method == "by_ratio":
            ratios = parameters.get("ratios")
            if not ratios:
                raise ValueError("Specify ratios for ratio split mode")
            total_ratio = sum(ratios)
            children_data = []
            for i, ratio in enumerate(ratios):
                qty = round(original_wo.planned_qty * ratio / total_ratio)
                children_data.append({"ratio": ratio, "qty": qty, "code_prefix": f"R{i+1:02d}"})
            total_split = sum(d["qty"] for d in children_data)
            if total_split < original_wo.planned_qty and children_data:
                children_data[-1]["qty"] += original_wo.planned_qty - total_split
            for i, data in enumerate(children_data):
                child_code = f"{original_wo.work_order_code}-{data['code_prefix']}"
                new_wo = WorkOrder(work_order_code=child_code, factory_id=original_wo.factory_id, product_id=original_wo.product_id,
                                   planned_qty=data["qty"], unit=original_wo.unit, planned_due=original_wo.planned_due, priority=original_wo.priority,
                                   status=WOStatus.DRAFT, sales_order_id=original_wo.sales_order_id, routing_id=original_wo.routing_id,
                                   assigned_station_id=original_wo.assigned_station_id, bom_version=original_wo.bom_version, wo_type="operation",
                                   parent_work_order_id=original_wo.id, ratio=data["ratio"], remark=f"Ratio split {i+1}/{len(ratios)}. {remark or ''}", created_by=operator)
                self.db.add(new_wo)
                children_created.append(new_wo)
            original_wo.planned_qty = 0
            original_wo.wo_type = "master"
            original_wo.updated_at = datetime.utcnow()
        
        else:
            raise ValueError(f"Unknown split method: {method}")
        
        await self.db.commit()
        await self.db.refresh(original_wo)
        for child in children_created:
            await self.db.refresh(child)
        self._log_status(original_wo, "split", original_wo.status, original_wo.status, operator, comment=f"Advanced split ({method}): {len(children_created)} children created")
        await self.db.commit()
        return {"master_work_order": self.to_dict(original_wo), "work_orders_created": [self.to_dict(c) for c in children_created],
                "total_created": len(children_created), "method": method}
    
    async def reverse_split(self, work_order_id: str, latest_only: bool = True, operator: str = "system") -> Dict[str, Any]:
        """反拆分：将最近拆分的子工单合并回主工单"""
        master_wo = await self.get_work_order_by_id(work_order_id)
        if not master_wo or master_wo.wo_type != "master":
            raise ValueError("Not a valid master work order")
        children = await self._get_children(master_wo.id)
        if not children:
            return {"message": "No child work orders to reverse"}
        if latest_only:
            children = [children[-1]]
        total_child_qty = sum(c.planned_qty for c in children)
        master_wo.planned_qty += total_child_qty
        master_wo.updated_at = datetime.utcnow()
        for child in children:
            child.status = WOStatus.CANCELLED
            child.remark = f"[Reversed]: Merged back to master {master_wo.work_order_code} on {datetime.utcnow().isoformat()}"
        self._log_status(master_wo, "reverse_split", master_wo.status, master_wo.status, operator, comment=f"Reversed split: {len(children)} child(ren) merged back")
        await self.db.commit()
        await self.db.refresh(master_wo)
        return {"master_work_order": self.to_dict(master_wo), "reversed_children": [self.to_dict(c) for c in children], "quantity_merged": total_child_qty}
    
    async def get_split_history(self, work_order_id: str) -> List[Dict]:
        from sqlalchemy import text
        result = await self.db.execute(text("""SELECT * FROM order_decomposition_logs WHERE work_order_id = :id ORDER BY created_at DESC""", {"id": work_order_id}))
        logs = result.mappings().all()
        return [dict(log) for log in logs]
    
    async def get_work_order_tree(self, work_order_id: str) -> Dict[str, Any]:
        """获取工单树形结构（含所有层级）"""
        master = await self.get_work_order_by_id(work_order_id)
        if not master:
            raise ValueError("Work order not found")
        children = await self._get_children(master.id)
        tree = {"master": self.to_dict(master), "children": []}
        if children:
            sorted_children = sorted(children, key=lambda x: (x.operation_seq or x.created_at, x.id))
            for child in sorted_children:
                child_data = self.to_dict(child)
                grandchildren = await self._get_children(child.id)
                if grandchildren:
                    child_data["subtree"] = await self._build_subtree(grandchildren)
                tree["children"].append(child_data)
        return tree
    
    async def _build_subtree(self, children: List[WorkOrder]) -> List[Dict]:
        sorted_children = sorted(children, key=lambda x: (x.operation_seq or x.created_at, x.id))
        result = []
        for child in sorted_children:
            child_data = self.to_dict(child)
            grandchildren = await self._get_children(child.id)
            if grandchildren:
                child_data["subtree"] = await self._build_subtree(grandchildren)
            result.append(child_data)
        return result
