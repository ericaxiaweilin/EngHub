"""
Kanban看板业务服务模块 - 拉动式生产管理的核心引擎

Kanban看板系统是精益生产（Lean Production）中实现"准时制"（JIT）和
"拉动式"（Pull）生产的视觉化管理工具。本模块提供看板生命周期管理、
状态流转控制和工序级可视化能力。
"""

from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Dict, Any, List, Set
from uuid import uuid4


class KanbanType(str, Enum):
    """看板类型分类"""
    PRODUCTION = "production"    # 生产看板（指示何时生产）
    MOVEMENT = "movement"        # 移动看板（指示物料搬运）
    EXPRESS = "express"          # 紧急看板（插单/加急）
    SPECIAL = "special"          # 特殊看板（定制订单）


class KanbanStatus(str, Enum):
    """看板状态流转（符合精益原则）"""
    EMPTY = "empty"             # 空（已用完，需补货）
    PENDING = "pending"         # 等待（已申请待处理）
    IN_PROGRESS = "in_progress"   # 执行中（生产中）
    DONE = "done"               # 完成（可取走）
    RETAINED = "retained"       # 保留（特殊用途）


class KanbanCard:
    """单个看板卡片实体"""
    
    def __init__(self, card_id: str, product_id: str, product_name: str, 
                 quantity: int, source_station: str, target_station: str,
                 kanban_type: KanbanType = KanbanType.PRODUCTION,
                 work_order_id: Optional[str] = None):
        self.id = str(uuid4())
        self.card_id = card_id                      # 看板卡号（如 KAB-2026-0001）
        self.product_id = product_id
        self.product_name = product_name
        self.quantity = quantity                    # 看板数量
        self.source_station = source_station        # 发出站
        self.target_station = target_station        # 接收站
        self.kanban_type = kanban_type              # 看板类型
        self.work_order_id = work_order_id          # 关联工单
        
        # 状态相关字段
        self.status = KanbanStatus.EMPTY
        self.created_at = datetime.utcnow()
        self.updated_at = self.created_at
        
        # 时间戳（用于统计）
        self.issued_at: Optional[datetime] = None     # 发出时间
        self.received_at: Optional[datetime] = None    # 接收时间
        self.completed_at: Optional[datetime] = None   # 完成时间
        self.collected_at: Optional[datetime] = None   # 回收时间
        
        # 操作日志历史（审计追踪）
        self.action_log: List[Dict[str, Any]] = [
            {"action": "created", "from": "EMPTY", "to": "EMPTY", 
             "at": self.created_at, "by": "system"}
        ]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "card_id": self.card_id,
            "product_id": self.product_id,
            "product_name": self.product_name,
            "quantity": self.quantity,
            "source_station": self.source_station,
            "target_station": self.target_station,
            "kanban_type": self.kanban_type.value,
            "work_order_id": self.work_order_id,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "issued_at": self.issued_at.isoformat() if self.issued_at else None,
            "received_at": self.received_at.isoformat() if self.received_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "collected_at": self.collected_at.isoformat() if self.collected_at else None,
            "action_log_count": len(self.action_log),
        }
    
    def add_action(self, action: str, from_status: Optional[str] = None, 
                   to_status: Optional[str] = None, by: str = "system") -> None:
        """添加操作日志记录"""
        log_entry = {
            "action": action,
            "from_status": from_status,
            "to_status": to_status,
            "at": datetime.utcnow(),
            "by": by,
        }
        self.action_log.append(log_entry)
        self.updated_at = datetime.utcnow()
    
    def emit(self, issued_by: str) -> None:
        """空出并下发看板（EMPTY → PENDING）"""
        if self.status == KanbanStatus.EMPTY:
            old_status = self.status
            self.status = KanbanStatus.PENDING
            self.issued_at = datetime.utcnow()
            self.add_action("emit", str(old_status), str(self.status), issued_by)
    
    def receive(self, received_by: str) -> None:
        """接收物料后看板变为IN_PROGRESS（PENDING → IN_PROGRESS）"""
        if self.status == KanbanStatus.PENDING:
            old_status = self.status
            self.status = KanbanStatus.IN_PROGRESS
            self.received_at = datetime.utcnow()
            self.add_action("receive", str(old_status), str(self.status), received_by)
    
    def complete(self, completed_by: str) -> None:
        """加工完成，看板变为DONE（IN_PROGRESS → DONE）"""
        if self.status == KanbanStatus.IN_PROGRESS:
            old_status = self.status
            self.status = KanbanStatus.DONE
            self.completed_at = datetime.utcnow()
            self.add_action("complete", str(old_status), str(self.status), completed_by)
    
    def collect(self, collected_by: str) -> None:
        """收回到源站点（DONE → EMPTY），形成闭环"""
        if self.status == KanbanStatus.DONE:
            old_status = self.status
            self.status = KanbanStatus.EMPTY
            self.collected_at = datetime.utcnow()
            self.add_action("collect", str(old_status), str(self.status), collected_by)


class KanbanPool:
    """看板池组 - 按产品/工序组合管理多张看板卡片"""
    
    def __init__(self, pool_id: str, product_id: str, 
                 source_station: str, target_station: str,
                 max_capacity: int = 10):
        self.pool_id = pool_id
        self.product_id = product_id
        self.source_station = source_station
        self.target_station = target_station
        self.max_capacity = max_capacity  # 最大在看板数
        self.cards: List[KanbanCard] = []
        self.created_at = datetime.utcnow()
    
    def add_card(self, card: KanbanCard) -> bool:
        """向池中添加新看板卡片"""
        if len(self.cards) < self.max_capacity:
            self.cards.append(card)
            return True
        return False
    
    def get_available_count(self) -> int:
        """获取可用（EMPTY状态）看板数量"""
        return sum(1 for c in self.cards if c.status == KanbanStatus.EMPTY)
    
    def get_in_process_count(self) -> int:
        """获取在制品数量（IN_PROGRESS或DONE状态）"""
        return sum(1 for c in self.cards if c.status in [KanbanStatus.IN_PROGRESS, KanbanStatus.DONE])
    
    def get_cards_by_status(self, status: KanbanStatus) -> List[KanbanCard]:
        """获取特定状态的看板列表"""
        return [c for c in self.cards if c.status == status]
    
    def get_all_cards(self) -> List[KanbanCard]:
        """返回所有卡片"""
        return self.cards.copy()


class KanbanService:
    """Kanban业务服务类 - 核心业务逻辑封装"""
    
    def __init__(self):
        # 内存存储（生产环境替换为数据库持久化）
        self._cards: Dict[str, KanbanCard] = {}      # card_id -> KanbanCard
        self._pools: Dict[str, KanbanPool] = {}     # pool_id -> KanbanPool
        self._next_card_number = 1
    
    def create_kanban_pool(self, pool_id: str, product_id: str, 
                          source_station: str, target_station: str,
                          max_capacity: int = 10) -> KanbanPool:
        """创建看板池（一组相关联的看板卡片）"""
        pool = KanbanPool(
            pool_id=pool_id,
            product_id=product_id,
            source_station=source_station,
            target_station=target_station,
            max_capacity=max_capacity,
        )
        self._pools[pool_id] = pool
        return pool
    
    def create_kanban_card(self, pool_id: str, product_id: str, 
                           product_name: str, quantity: int,
                           work_order_id: Optional[str] = None,
                           kanban_type: KanbanType = KanbanType.PRODUCTION) -> KanbanCard:
        """创建单个看板卡片并归入指定池"""
        if pool_id not in self._pools:
            raise ValueError(f"看板池 {pool_id} 不存在")
        
        pool = self._pools[pool_id]
        if pool.get_available_count() >= pool.max_capacity:
            raise RuntimeError(f"看板池 {pool_id} 已满，无法创建新看板")
        
        # 生成卡号
        card_id = f"KAN-{pool.product_id}-{str(self._next_card_number).zfill(4)}"
        self._next_card_number += 1
        
        card = KanbanCard(
            card_id=card_id,
            product_id=product_id,
            product_name=product_name,
            quantity=quantity,
            source_station=pool.source_station,
            target_station=pool.target_station,
            kanban_type=kanban_type,
            work_order_id=work_order_id,
        )
        
        self._cards[card.id] = card
        pool.add_card(card)
        
        return card
    
    def get_card(self, card_id: str) -> Optional[KanbanCard]:
        """获取看板卡片"""
        return self._cards.get(card_id)
    
    def emit_card(self, card_id: str, emitted_by: str) -> bool:
        """下发看板（EMPTY→PENDING）"""
        card = self._cards.get(card_id)
        if card and card.status == KanbanStatus.EMPTY:
            card.emit(emitted_by)
            return True
        return False
    
    def receive_card(self, card_id: str, received_by: str) -> bool:
        """接收看板并转为加工中（PENDING→IN_PROGRESS）"""
        card = self._cards.get(card_id)
        if card and card.status == KanbanStatus.PENDING:
            card.receive(received_by)
            return True
        return False
    
    def complete_card(self, card_id: str, completed_by: str) -> bool:
        """加工完成看板（IN_PROGRESS→DONE）"""
        card = self._cards.get(card_id)
        if card and card.status == KanbanStatus.IN_PROGRESS:
            card.complete(completed_by)
            return True
        return False
    
    def collect_card(self, card_id: str, collected_by: str) -> bool:
        """回收看板（DONE→EMPTY），完成循环"""
        card = self._cards.get(card_id)
        if card and card.status == KanbanStatus.DONE:
            card.collect(collected_by)
            return True
        return False
    
    def list_pools(self, product_id: Optional[str] = None) -> List[Dict]:
        """列出看板池"""
        result = []
        for pool in self._pools.values():
            if product_id or pool.product_id == product_id:
                result.append({
                    "pool_id": pool.pool_id,
                    "product_id": pool.product_id,
                    "source_station": pool.source_station,
                    "target_station": pool.target_station,
                    "max_capacity": pool.max_capacity,
                    "available": pool.get_available_count(),
                    "in_process": pool.get_in_process_count(),
                    "total": len(pool.cards),
                })
        return result
    
    def list_cards(self, pool_id: Optional[str] = None, 
                   status: Optional[KanbanStatus] = None) -> List[KanbanCard]:
        """列出看板卡片（可选过滤池ID和状态）"""
        cards = list(self._cards.values())
        
        if pool_id:
            pool = self._pools.get(pool_id)
            if pool:
                cards = [c for c in cards if c in pool.cards]
        
        if status:
            cards = [c for c in cards if c.status == status]
        
        return cards
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取Kanban看板统计信息"""
        total_cards = len(self._cards)
        empty_cards = sum(1 for c in self._cards.values() if c.status == KanbanStatus.EMPTY)
        pending_cards = sum(1 for c in self._cards.values() if c.status == KanbanStatus.PENDING)
        in_progress_cards = sum(1 for c in self._cards.values() if c.status == KanbanStatus.IN_PROGRESS)
        done_cards = sum(1 for c in self._cards.values() if c.status == KanbanStatus.DONE)
        retained_cards = sum(1 for c in self._cards.values() if c.status == KanbanStatus.RETAINED)
        
        pools_count = len(self._pools)
        
        return {
            "total_pools": pools_count,
            "total_cards": total_cards,
            "by_status": {
                "EMPTY": empty_cards,
                "PENDING": pending_cards,
                "IN_PROGRESS": in_progress_cards,
                "DONE": done_cards,
                "RETAINED": retained_cards,
            },
            "cards_per_pool_avg": round(total_cards / pools_count, 1) if pools_count > 0 else 0,
        }
