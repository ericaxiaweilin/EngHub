"""
TMS Distribution Engine - 任务分发引擎（核心模块）

分发策略：
- skill_match: 技能匹配（结合 EmployeeSkill）
- load_balance: 负载均衡（当前任务量最少）
- round_robin: 轮询
- priority_queue: 优先级队列
- agent_decide: Agent 智能决策（外部 AI 决定）

分发模式：
- 直接分配: 引擎直接指定执行人
- 候选池抢单: 推送给多个候选人，先抢先得
- Agent 决策: 调用外部 AI Agent 决定分配
- 审批人指定: 按审批流角色自动匹配
"""

import logging
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from enum import Enum

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    TMSTask,
    TMSDistributionLog,
    User,
    EmployeeSkill,
    Skill,
)
from core.tms.events import tms_event_bus, TMSEventType

logger = logging.getLogger(__name__)


class DistributionStrategy(str, Enum):
    """分发策略"""
    SKILL_MATCH = "skill_match"
    LOAD_BALANCE = "load_balance"
    ROUND_ROBIN = "round_robin"
    PRIORITY_QUEUE = "priority_queue"
    AGENT_DECIDE = "agent_decide"
    MANUAL = "manual"


class DistributionMode(str, Enum):
    """分发模式"""
    DIRECT = "direct"          # 直接分配
    POOL = "pool"              # 候选池抢单
    AGENT = "agent"            # Agent 决策
    ROLE_MATCH = "role_match"  # 审批人指定


@dataclass
class CandidateScore:
    """候选人评分"""
    user_id: str
    username: str
    full_name: str
    total_score: float
    skill_score: float = 0.0       # 技能匹配度 (40%)
    load_score: float = 0.0        # 当前负载 (25%)
    history_score: float = 0.0     # 历史完成率 (20%)
    response_score: float = 0.0    # 响应速度 (15%)
    reasons: List[str] = field(default_factory=list)


@dataclass
class DistributionResult:
    """分发结果"""
    success: bool
    task_id: str
    strategy: str
    mode: str
    assigned_to: Optional[str] = None
    assigned_to_name: Optional[str] = None
    candidate_pool: List[Dict[str, Any]] = field(default_factory=list)
    candidate_scores: Dict[str, float] = field(default_factory=dict)
    reason: str = ""
    message: str = ""


class DistributionEngine:
    """
    任务分发引擎 - TMS 核心
    
    核心分发流程：
    1. 解析任务所需技能/角色
    2. 获取候选人池（过滤在线、有技能、未超负载）
    3. 按策略评分排序
    4. 写入 candidate_pool 或直接分配
    5. 记录 DistributionLog（可审计）
    6. 发布事件 TaskDistributed
    """

    # 评分权重
    WEIGHTS = {
        "skill": 0.40,     # 技能匹配度
        "load": 0.25,      # 当前负载
        "history": 0.20,   # 历史完成率
        "response": 0.15,  # 响应速度
    }

    # 最大负载阈值
    MAX_TASKS_PER_USER = 10

    def __init__(self, db: AsyncSession):
        self.db = db
        self._round_robin_index: Dict[str, int] = {}  # task_type -> last_index

    async def distribute(
        self,
        task: TMSTask,
        strategy: str = DistributionStrategy.SKILL_MATCH.value,
        mode: str = DistributionMode.DIRECT.value,
        triggered_by: str = "system",
        target_user_id: Optional[str] = None,
    ) -> DistributionResult:
        """
        核心分发入口
        
        Args:
            task: 待分发任务
            strategy: 分发策略
            mode: 分发模式
            triggered_by: 触发者 (system / agent:xxx / user:xxx)
            target_user_id: 手动指定分配对象（manual 模式）
        """
        logger.info(f"Distributing task {task.task_code} | strategy={strategy} | mode={mode}")

        # 手动分配
        if strategy == DistributionStrategy.MANUAL.value and target_user_id:
            return await self._manual_distribute(task, target_user_id, triggered_by)

        # 获取候选人
        candidates = await self._get_candidates(task)
        if not candidates:
            return DistributionResult(
                success=False,
                task_id=str(task.id),
                strategy=strategy,
                mode=mode,
                reason="无可用候选人",
                message="未找到符合条件的候选人，请调整任务要求或手动分配",
            )

        # 按策略评分
        if strategy == DistributionStrategy.SKILL_MATCH.value:
            scored_candidates = await self._score_by_skill(task, candidates)
        elif strategy == DistributionStrategy.LOAD_BALANCE.value:
            scored_candidates = await self._score_by_load(task, candidates)
        elif strategy == DistributionStrategy.ROUND_ROBIN.value:
            scored_candidates = await self._score_round_robin(task, candidates)
        elif strategy == DistributionStrategy.PRIORITY_QUEUE.value:
            scored_candidates = await self._score_by_priority(task, candidates)
        elif strategy == DistributionStrategy.AGENT_DECIDE.value:
            # Agent 决策模式：返回候选人列表，等待外部 Agent 决定
            return await self._agent_decide_mode(task, candidates, triggered_by)
        else:
            scored_candidates = await self._score_by_skill(task, candidates)

        # 排序
        scored_candidates.sort(key=lambda c: c.total_score, reverse=True)

        # 执行分发
        if mode == DistributionMode.DIRECT.value:
            result = await self._direct_assign(task, scored_candidates[0], strategy, triggered_by)
        elif mode == DistributionMode.POOL.value:
            result = await self._pool_distribute(task, scored_candidates[:5], strategy, triggered_by)
        else:
            result = await self._direct_assign(task, scored_candidates[0], strategy, triggered_by)

        return result

    async def _get_candidates(self, task: TMSTask) -> List[User]:
        """获取候选人池"""
        query = select(User).where(
            and_(
                User.is_active == True,
                User.role.in_(["operator", "manager", "admin"]),
            )
        )

        # 按角色过滤
        if task.required_roles:
            query = query.where(User.role.in_(task.required_roles))

        result = await self.db.execute(query)
        candidates = list(result.scalars().all())

        # 按技能过滤（如果有技能要求）
        if task.required_skills:
            candidates = await self._filter_by_skills(candidates, task.required_skills)

        # 过滤超负载用户
        candidates = await self._filter_overloaded(candidates)

        return candidates

    async def _filter_by_skills(self, candidates: List[User], required_skills: List[str]) -> List[User]:
        """按技能过滤候选人"""
        if not required_skills:
            return candidates

        # 查询技能 ID
        skill_result = await self.db.execute(
            select(Skill.id, Skill.code).where(Skill.code.in_(required_skills))
        )
        skill_map = {row.code: row.id for row in skill_result.all()}
        skill_ids = list(skill_map.values())

        if not skill_ids:
            return candidates

        # 查询拥有这些技能的员工
        emp_skill_result = await self.db.execute(
            select(EmployeeSkill.user_id).where(
                and_(
                    EmployeeSkill.skill_id.in_(skill_ids),
                    EmployeeSkill.level.in_(["L3", "L4", "L5"]),  # 至少 L3 级别
                )
            ).distinct()
        )
        qualified_user_ids = {str(row[0]) for row in emp_skill_result.all()}

        return [c for c in candidates if str(c.id) in qualified_user_ids]

    async def _filter_overloaded(self, candidates: List[User]) -> List[User]:
        """过滤超负载用户"""
        if not candidates:
            return candidates

        user_ids = [c.id for c in candidates]

        # 查询每个用户的进行中任务数
        load_result = await self.db.execute(
            select(
                TMSTask.assigned_to,
                func.count(TMSTask.id).label("task_count")
            ).where(
                and_(
                    TMSTask.assigned_to.in_(user_ids),
                    TMSTask.status.in_(["distributed", "claimed", "in_progress"]),
                )
            ).group_by(TMSTask.assigned_to)
        )
        load_map = {str(row.assigned_to): row.task_count for row in load_result.all()}

        return [
            c for c in candidates
            if load_map.get(str(c.id), 0) < self.MAX_TASKS_PER_USER
        ]

    async def _score_by_skill(self, task: TMSTask, candidates: List[User]) -> List[CandidateScore]:
        """技能匹配评分"""
        scored = []
        for candidate in candidates:
            score = CandidateScore(
                user_id=str(candidate.id),
                username=candidate.username,
                full_name=candidate.full_name or candidate.username,
                total_score=0.0,
            )

            # 技能匹配度 (40%)
            skill_score = await self._calc_skill_score(candidate, task.required_skills or [])
            score.skill_score = skill_score * self.WEIGHTS["skill"]
            if skill_score > 0.8:
                score.reasons.append(f"技能高度匹配 ({skill_score:.0%})")

            # 当前负载 (25%)
            load_score = await self._calc_load_score(candidate)
            score.load_score = load_score * self.WEIGHTS["load"]
            if load_score > 0.7:
                score.reasons.append("当前负载较低")

            # 历史完成率 (20%)
            history_score = await self._calc_history_score(candidate, task.task_type)
            score.history_score = history_score * self.WEIGHTS["history"]

            # 响应速度 (15%)
            response_score = await self._calc_response_score(candidate)
            score.response_score = response_score * self.WEIGHTS["response"]

            score.total_score = score.skill_score + score.load_score + score.history_score + score.response_score
            scored.append(score)

        return scored

    async def _score_by_load(self, task: TMSTask, candidates: List[User]) -> List[CandidateScore]:
        """负载均衡评分（主要看负载）"""
        scored = []
        for candidate in candidates:
            score = CandidateScore(
                user_id=str(candidate.id),
                username=candidate.username,
                full_name=candidate.full_name or candidate.username,
                total_score=0.0,
            )

            # 负载评分占主导 (60%)
            load_score = await self._calc_load_score(candidate)
            score.load_score = load_score * 0.60
            score.skill_score = await self._calc_skill_score(candidate, task.required_skills or []) * 0.25
            score.history_score = await self._calc_history_score(candidate, task.task_type) * 0.15

            score.total_score = score.load_score + score.skill_score + score.history_score
            if load_score > 0.8:
                score.reasons.append("负载最低优先")
            scored.append(score)

        return scored

    async def _score_round_robin(self, task: TMSTask, candidates: List[User]) -> List[CandidateScore]:
        """轮询评分"""
        task_type = task.task_type
        last_index = self._round_robin_index.get(task_type, -1)
        next_index = (last_index + 1) % len(candidates)
        self._round_robin_index[task_type] = next_index

        scored = []
        for i, candidate in enumerate(candidates):
            score = CandidateScore(
                user_id=str(candidate.id),
                username=candidate.username,
                full_name=candidate.full_name or candidate.username,
                total_score=1.0 if i == next_index else 0.5,
            )
            if i == next_index:
                score.reasons.append("轮询选中")
            scored.append(score)

        return scored

    async def _score_by_priority(self, task: TMSTask, candidates: List[User]) -> List[CandidateScore]:
        """优先级队列评分（高优先级任务分配给高技能人员）"""
        scored = await self._score_by_skill(task, candidates)

        # 高优先级任务加权技能分
        if task.priority in ["high", "urgent"]:
            for s in scored:
                s.total_score = s.skill_score * 1.5 + s.load_score + s.history_score
                if s.skill_score > 0.7:
                    s.reasons.append("高优先级任务 - 技能优先")

        return scored

    async def _calc_skill_score(self, candidate: User, required_skills: List[str]) -> float:
        """计算技能匹配度"""
        if not required_skills:
            return 0.7  # 无技能要求时给默认分

        # 查询候选人技能
        result = await self.db.execute(
            select(Skill.code, EmployeeSkill.level).join(
                EmployeeSkill, EmployeeSkill.skill_id == Skill.id
            ).where(EmployeeSkill.user_id == candidate.id)
        )
        candidate_skills = {row.code: row.level for row in result.all()}

        # 计算匹配度
        matched = 0
        level_bonus = 0.0
        for skill_code in required_skills:
            if skill_code in candidate_skills:
                matched += 1
                level = candidate_skills[skill_code]
                level_bonus += {"L1": 0.2, "L2": 0.4, "L3": 0.6, "L4": 0.8, "L5": 1.0}.get(level, 0.5)

        if not required_skills:
            return 0.7

        match_rate = matched / len(required_skills)
        avg_level = level_bonus / max(matched, 1)

        return min(1.0, match_rate * 0.7 + avg_level * 0.3)

    async def _calc_load_score(self, candidate: User) -> float:
        """计算负载评分（负载越低分越高）"""
        result = await self.db.execute(
            select(func.count(TMSTask.id)).where(
                and_(
                    TMSTask.assigned_to == candidate.id,
                    TMSTask.status.in_(["distributed", "claimed", "in_progress"]),
                )
            )
        )
        current_load = result.scalar() or 0
        return max(0.0, 1.0 - (current_load / self.MAX_TASKS_PER_USER))

    async def _calc_history_score(self, candidate: User, task_type: str) -> float:
        """计算历史完成率"""
        # 同类任务完成数
        completed_result = await self.db.execute(
            select(func.count(TMSTask.id)).where(
                and_(
                    TMSTask.assigned_to == candidate.id,
                    TMSTask.task_type == task_type,
                    TMSTask.status == "completed",
                )
            )
        )
        completed = completed_result.scalar() or 0

        # 同类任务总数
        total_result = await self.db.execute(
            select(func.count(TMSTask.id)).where(
                and_(
                    TMSTask.assigned_to == candidate.id,
                    TMSTask.task_type == task_type,
                    TMSTask.status.in_(["completed", "rejected"]),
                )
            )
        )
        total = total_result.scalar() or 0

        if total == 0:
            return 0.5  # 无历史数据给默认分

        return completed / total

    async def _calc_response_score(self, candidate: User) -> float:
        """计算响应速度评分"""
        # 简化实现：基于最近认领任务的时间差
        # 实际生产中可计算平均认领时间
        return 0.7  # 默认分

    async def _direct_assign(
        self, task: TMSTask, candidate: CandidateScore, strategy: str, triggered_by: str
    ) -> DistributionResult:
        """直接分配"""
        task.assigned_to = candidate.user_id
        task.assigned_by = triggered_by
        task.status = "distributed"
        task.distribution_strategy = strategy
        task.candidate_pool = [{"user_id": candidate.user_id, "score": candidate.total_score}]
        task.updated_at = datetime.utcnow()

        # 记录分发日志
        log = TMSDistributionLog(
            id=str(uuid.uuid4()),
            task_id=task.id,
            strategy=strategy,
            candidate_scores={candidate.user_id: candidate.total_score},
            selected_user_id=candidate.user_id,
            reason=f"策略={strategy} | 评分={candidate.total_score:.2f} | {'; '.join(candidate.reasons)}",
            triggered_by=triggered_by,
        )
        self.db.add(log)
        await self.db.commit()

        # 发布事件
        await tms_event_bus.publish(
            TMSEventType.TASK_DISTRIBUTED.value,
            {
                "task_id": str(task.id),
                "task_code": task.task_code,
                "assigned_to": candidate.user_id,
                "assigned_to_name": candidate.full_name,
                "strategy": strategy,
                "score": candidate.total_score,
            },
            source=triggered_by,
        )

        return DistributionResult(
            success=True,
            task_id=str(task.id),
            strategy=strategy,
            mode=DistributionMode.DIRECT.value,
            assigned_to=candidate.user_id,
            assigned_to_name=candidate.full_name,
            candidate_scores={candidate.user_id: candidate.total_score},
            reason=f"直接分配给 {candidate.full_name}，综合评分 {candidate.total_score:.2f}",
            message=f"任务已分配给 {candidate.full_name}",
        )

    async def _pool_distribute(
        self, task: TMSTask, candidates: List[CandidateScore], strategy: str, triggered_by: str
    ) -> DistributionResult:
        """候选池抢单模式"""
        pool = [
            {"user_id": c.user_id, "username": c.username, "score": c.total_score}
            for c in candidates
        ]

        task.status = "distributed"
        task.distribution_strategy = strategy
        task.candidate_pool = pool
        task.updated_at = datetime.utcnow()

        # 记录分发日志
        log = TMSDistributionLog(
            id=str(uuid.uuid4()),
            task_id=task.id,
            strategy=strategy,
            candidate_scores={c.user_id: c.total_score for c in candidates},
            selected_user_id=None,  # 等待抢单
            reason=f"候选池模式 | 候选人数={len(candidates)} | 策略={strategy}",
            triggered_by=triggered_by,
        )
        self.db.add(log)
        await self.db.commit()

        # 发布事件
        await tms_event_bus.publish(
            TMSEventType.TASK_DISTRIBUTED.value,
            {
                "task_id": str(task.id),
                "task_code": task.task_code,
                "mode": "pool",
                "candidate_count": len(candidates),
                "candidates": [c.user_id for c in candidates],
            },
            source=triggered_by,
        )

        return DistributionResult(
            success=True,
            task_id=str(task.id),
            strategy=strategy,
            mode=DistributionMode.POOL.value,
            candidate_pool=pool,
            candidate_scores={c.user_id: c.total_score for c in candidates},
            reason=f"推送给 {len(candidates)} 名候选人，等待抢单",
            message=f"任务已推送给 {len(candidates)} 名候选人",
        )

    async def _manual_distribute(
        self, task: TMSTask, target_user_id: str, triggered_by: str
    ) -> DistributionResult:
        """手动分配"""
        # 验证用户存在
        result = await self.db.execute(select(User).where(User.id == target_user_id))
        user = result.scalar_one_or_none()
        if not user:
            return DistributionResult(
                success=False,
                task_id=str(task.id),
                strategy=DistributionStrategy.MANUAL.value,
                mode=DistributionMode.DIRECT.value,
                reason=f"用户 {target_user_id} 不存在",
            )

        task.assigned_to = target_user_id
        task.assigned_by = triggered_by
        task.status = "distributed"
        task.distribution_strategy = DistributionStrategy.MANUAL.value
        task.updated_at = datetime.utcnow()

        log = TMSDistributionLog(
            id=str(uuid.uuid4()),
            task_id=task.id,
            strategy=DistributionStrategy.MANUAL.value,
            candidate_scores={},
            selected_user_id=target_user_id,
            reason="手动指定分配",
            triggered_by=triggered_by,
        )
        self.db.add(log)
        await self.db.commit()

        await tms_event_bus.publish(
            TMSEventType.TASK_DISTRIBUTED.value,
            {"task_id": str(task.id), "task_code": task.task_code, "assigned_to": target_user_id, "mode": "manual"},
            source=triggered_by,
        )

        return DistributionResult(
            success=True,
            task_id=str(task.id),
            strategy=DistributionStrategy.MANUAL.value,
            mode=DistributionMode.DIRECT.value,
            assigned_to=target_user_id,
            assigned_to_name=user.full_name or user.username,
            reason="手动分配",
            message=f"任务已手动分配给 {user.full_name or user.username}",
        )

    async def _agent_decide_mode(
        self, task: TMSTask, candidates: List[User], triggered_by: str
    ) -> DistributionResult:
        """Agent 决策模式 - 返回候选人列表等待外部 AI 决定"""
        candidate_info = []
        for c in candidates:
            skill_score = await self._calc_skill_score(c, task.required_skills or [])
            load_score = await self._calc_load_score(c)
            candidate_info.append({
                "user_id": str(c.id),
                "username": c.username,
                "full_name": c.full_name or c.username,
                "skill_score": round(skill_score, 3),
                "load_score": round(load_score, 3),
                "role": c.role,
            })

        # 标记为等待 Agent 决策
        task.status = "pending_distribution"
        task.distribution_strategy = DistributionStrategy.AGENT_DECIDE.value
        task.agent_context = {
            **task.agent_context,
            "awaiting_agent_decision": True,
            "candidates": candidate_info,
            "requested_at": datetime.utcnow().isoformat(),
        }
        task.updated_at = datetime.utcnow()
        await self.db.commit()

        await tms_event_bus.publish(
            TMSEventType.AGENT_CONFIRMATION_REQUIRED.value,
            {
                "task_id": str(task.id),
                "task_code": task.task_code,
                "action": "distribute",
                "candidates": candidate_info,
            },
            source=triggered_by,
        )

        return DistributionResult(
            success=True,
            task_id=str(task.id),
            strategy=DistributionStrategy.AGENT_DECIDE.value,
            mode=DistributionMode.AGENT.value,
            candidate_pool=candidate_info,
            reason="等待 Agent 智能决策",
            message=f"已推送 {len(candidates)} 名候选人给 Agent，等待决策",
        )

    async def claim_task(self, task: TMSTask, user_id: str) -> DistributionResult:
        """抢单（候选池模式）"""
        # 验证用户是否在候选池中
        pool_user_ids = [c.get("user_id") for c in (task.candidate_pool or [])]
        if user_id not in pool_user_ids:
            return DistributionResult(
                success=False,
                task_id=str(task.id),
                strategy=task.distribution_strategy or "pool",
                mode=DistributionMode.POOL.value,
                reason="用户不在候选池中",
            )

        task.assigned_to = user_id
        task.status = "claimed"
        task.updated_at = datetime.utcnow()
        await self.db.commit()

        await tms_event_bus.publish(
            TMSEventType.TASK_CLAIMED.value,
            {"task_id": str(task.id), "task_code": task.task_code, "claimed_by": user_id},
        )

        return DistributionResult(
            success=True,
            task_id=str(task.id),
            strategy=task.distribution_strategy or "pool",
            mode=DistributionMode.POOL.value,
            assigned_to=user_id,
            message="任务认领成功",
        )

    async def get_distribution_stats(self, factory_id: Optional[str] = None) -> Dict[str, Any]:
        """获取分发统计"""
        # 各状态任务数
        status_result = await self.db.execute(
            select(TMSTask.status, func.count(TMSTask.id)).group_by(TMSTask.status)
        )
        status_counts = {row[0]: row[1] for row in status_result.all()}

        # 各策略使用次数
        strategy_result = await self.db.execute(
            select(TMSDistributionLog.strategy, func.count(TMSDistributionLog.id))
            .group_by(TMSDistributionLog.strategy)
        )
        strategy_counts = {row[0]: row[1] for row in strategy_result.all()}

        return {
            "status_distribution": status_counts,
            "strategy_usage": strategy_counts,
            "total_distributions": sum(strategy_counts.values()),
        }
