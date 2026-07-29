"""
员工能力标签服务 - 增强版（含技能匹配TMS任务分配功能）

提供:
- 技能矩阵管理
- 资质认证跟踪
- 人员与技能匹配
- TMS任务智能分配支持
"""
<<<<<<< HEAD

from sqlalchemy import select, and_, or_, desc, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from datetime import date, datetime, timedelta
from typing import List, Optional, Dict, Any
=======
from sqlalchemy import select, and_, or_, cast, String, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from datetime import date, datetime, timedelta
from typing import List, Optional, Dict
>>>>>>> 7258e8d
from database.models import (
    EmployeeSkill, Skill, TrainingRecord, User, TMSTask,
)
from api.schemas.employee_skill import (
    EmployeeSkillCreate, EmployeeSkillUpdate, EmployeeSkillResponse,
    SkillCreate, SkillResponse, TrainingRecordCreate,
    SkillMatrixResponse, EmployeeSkillMatch, SkillMatchResult,
)

# 技能等级映射
SKILL_LEVELS = {
    "L1": 1,
    "L2": 2,
    "L3": 3,
    "L4": 4,
    "L5": 5
}


class EmployeeSkillService:
    """员工技能服务"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_employee_skills(self, user_id: str) -> List[EmployeeSkillResponse]:
        """获取员工所有有效技能"""
        now = datetime.utcnow()
        result = await self.db.execute(
            select(EmployeeSkill)
            .where(EmployeeSkill.user_id == user_id)
            .options(joinedload(EmployeeSkill.skill))
            .where(
                or_(
                    EmployeeSkill.expiry_date.is_(None),
                    EmployeeSkill.expiry_date >= now,
                )
            )
            .order_by(desc(EmployeeSkill.score))
        )
        skills = result.scalars().all()
        return [self._emp_skill_to_response(s) for s in skills]
    
    async def add_skill_to_employee(
        self, 
        user_id: str, 
        skill_data: EmployeeSkillCreate,
        evaluated_by: str,
    ) -> EmployeeSkillResponse:
        """给员工添加技能标签"""
        # 检查技能是否存在
        skill_result = await self.db.execute(
            select(Skill).where(Skill.id == skill_data.skill_id, Skill.is_active == True)
        )
        skill = skill_result.scalar_one_or_none()
        if not skill:
            raise ValueError(f"Skill {skill_data.skill_id} not found or inactive")
        
        # 检查是否已存在该技能（同一用户+同一技能）
        existing = await self.db.execute(
            select(EmployeeSkill).where(
                EmployeeSkill.user_id == user_id,
                EmployeeSkill.skill_id == skill_data.skill_id,
            )
        )
        emp_skill = existing.scalar_one_or_none()
        
        now = datetime.utcnow()
        if emp_skill:
            # 更新现有技能
            emp_skill.level = skill_data.level
            emp_skill.score = skill_data.score
            emp_skill.certified_date = skill_data.certified_date or now
            emp_skill.expiry_date = skill_data.expiry_date
            emp_skill.remarks = skill_data.remarks
            emp_skill.evaluated_by = evaluated_by
            emp_skill.updated_at = now
        else:
            # 创建新技能记录
            emp_skill = EmployeeSkill(
                user_id=user_id,
                skill_id=skill_data.skill_id,
                level=skill_data.level,
                score=skill_data.score,
                certified_date=skill_data.certified_date or now,
                expiry_date=skill_data.expiry_date,
                remarks=skill_data.remarks,
                evaluated_by=evaluated_by,
                created_at=now,
                updated_at=now,
            )
            self.db.add(emp_skill)
        
        await self.db.commit()
        await self.db.refresh(emp_skill)
        return self._emp_skill_to_response(emp_skill)
    
    async def remove_skill_from_employee(self, db: Any, user_id: str, skill_id: int) -> bool:
        """移除员工技能"""
        now = datetime.utcnow()
        result = await self.db.execute(
            select(EmployeeSkill).where(
                EmployeeSkill.user_id == user_id,
                EmployeeSkill.skill_id == skill_id,
                EmployeeSkill.updated_at < now,  # 避免并发冲突
            )
        )
        emp_skill = result.scalar_one_or_none()
        
        if emp_skill:
            emp_skill.updated_at = now
            await self.db.commit()
            return True
        return False
    
    async def get_skill_matrix(
        self, 
        factory_id: Optional[str] = None,
        skill_category: Optional[str] = None,
        min_level: Optional[str] = None,
    ) -> List[SkillMatrixResponse]:
        """
        获取技能矩阵
<<<<<<< HEAD
        
        展示部门/全员的技能分布情况，可用于识别技能缺口
        
        Args:
            factory_id: 工厂ID（可选）
            skill_category: 技能类别（可选）
            min_level: 最低要求等级（如L2、L3）
        
        Returns:
            员工技能矩阵列表
        """
        now = datetime.utcnow()
        
        query = (
            select(User, EmployeeSkill, Skill)
            .join(EmployeeSkill, User.id == EmployeeSkill.user_id)
            .join(Skill, EmployeeSkill.skill_id == Skill.id)
            .where(
                or_(
                    EmployeeSkill.expiry_date.is_(None),
                    EmployeeSkill.expiry_date >= now,
                ),
            )
        )
        
        if factory_id:
            query = query.where(User.factory_id == factory_id)
        if skill_category:
            query = query.where(Skill.category == skill_category)
        if min_level:
            min_level_num = SKILL_LEVELS.get(min_level, 1)
            query = query.where(EmployeeSkill.level >= min_level_num)
        
        query = query.order_by(User.factory_id, User.username)
        result = await self.db.execute(query)
        rows = result.all()
        
        matrix = {}
        for user, emp_skill, skill in rows:
            user_key = str(user.id)
            if user_key not in matrix:
                matrix[user_key] = SkillMatrixResponse(
                    user_id=user_key,
                    name=user.full_name or user.username,
                    department=user.factory_id,
                    factory_id=user.factory_id,
                    skills=[],
                    total_skill_count=0,
                    max_level=None,
                )
            
            # 检查资质是否有效
            is_valid = True
            if emp_skill.expiry_date and emp_skill.expiry_date < now:
                is_valid = False
            
            skill_info = {
                "skill_id": skill.id,
                "skill_code": skill.code,
                "skill_name": skill.name,
                "category": skill.category,
                "level": emp_skill.level,
                "score": float(emp_skill.score) if emp_skill.score else None,
                "certified_date": emp_skill.certified_date,
                "expiry_date": emp_skill.expiry_date,
                "is_valid": is_valid,
            }
            
            matrix[user_key].skills.append(skill_info)
            matrix[user_key].total_skill_count += 1
            
            # 更新最高等级
            if (matrix[user_key].max_level is None or 
                SKILL_LEVELS.get(emp_skill.level, 0) > SKILL_LEVELS.get(matrix[user_key].max_level, 0)):
                matrix[user_key].max_level = emp_skill.level
        
=======
        展示部门/全员的技能分布情况
        数据源：hr_employees + hr_employee_skills + skills（真实 HR 技能档案）
        注：users+employee_skills 无数据；department 参数按厂区(factory_id)过滤
        """
        sql = """
            SELECT he.id AS emp_id, he.employee_code, he.name, he.department, he.factory_id,
                   s.name AS skill_name, s.category AS skill_category,
                   hes.level, hes.certified_date, hes.expiry_date
            FROM hr_employee_skills hes
            JOIN hr_employees he ON he.id = hes.hr_employee_id
            JOIN skills s ON s.id = hes.skill_id
            WHERE he.status = 'active'
              AND (hes.expiry_date IS NULL OR hes.expiry_date >= CURRENT_DATE)
        """
        params: Dict[str, object] = {}
        if department:
            sql += " AND he.factory_id = :fid"
            params["fid"] = department
        if skill_category:
            sql += " AND s.category = :cat"
            params["cat"] = skill_category
        sql += " ORDER BY he.employee_code, s.name"

        result = await self.db.execute(text(sql), params)
        rows = result.all()

        matrix: Dict[str, SkillMatrixResponse] = {}
        for r in rows:
            emp_id = str(r.emp_id)
            if emp_id not in matrix:
                matrix[emp_id] = SkillMatrixResponse(
                    user_id=r.employee_code or emp_id,
                    name=r.name,
                    department=r.department or r.factory_id,
                    skills=[]
                )
            is_valid = not (r.expiry_date and r.expiry_date < date.today())
            matrix[emp_id].skills.append({
                "skill_name": r.skill_name,
                "category": r.skill_category,
                "level": str(r.level or "L3").upper().replace("L", ""),
                "score": None,
                "certified_date": r.certified_date,
                "expiry_date": r.expiry_date,
                "is_valid": is_valid,
            })

>>>>>>> 7258e8d
        return list(matrix.values())
    
    async def find_qualified_employees(
        self, 
        skill_id: int, 
        min_level: str = "L2",
        include_expired: bool = False,
    ) -> List[User]:
        """查找具备特定技能等级的员工"""
        min_level_num = SKILL_LEVELS.get(min_level, 2)
        
        now = datetime.utcnow()
        conditions = [
            EmployeeSkill.skill_id == skill_id,
            EmployeeSkill.level >= min_level_num,
        ]
        
        if not include_expired:
            conditions.append(
                or_(
                    EmployeeSkill.expiry_date.is_(None),
                    EmployeeSkill.expiry_date >= now,
                )
            )
        
<<<<<<< HEAD
        result = await self.db.execute(
            select(User)
            .join(EmployeeSkill, User.id == EmployeeSkill.user_id)
            .where(*conditions)
            .distinct(User.id)
            .order_by(EmployeeSkill.score.desc())
=======
        if not qualified_user_ids:
            return []
        
        # Get user details
        users_result = await self.db.execute(
            select(User).where(cast(User.id, String(36)).in_(qualified_user_ids))
>>>>>>> 7258e8d
        )
        users = result.scalars().all()
        return list(users)
    
    async def match_skill_to_tms_task(
        self,
        task: TMSTask,
    ) -> SkillMatchResult:
        """
        为TMS任务匹配最合适的员工（基于技能要求）
        
        返回匹配结果和评分详情，用于任务分发决策
        
        Args:
            task: TMSTask对象（包含required_skills字段）
        
        Returns:
            SkillMatchResult: 包含最佳匹配候选人和评分列表
        """
        required_skills = task.required_skills or []
        
        if not required_skills:
            # 如果没有指定技能要求，返回所有可用员工
            candidates = await self._get_all_available_users()
            return SkillMatchResult(
                task_id=task.id,
                task_type=task.task_type,
                matched_user_ids=[str(u.id) for u in candidates],
                score_details=[{"user_id": str(u.id), "score": 100.0, "matched_skills": []} for u in candidates],
                recommended_user=str(candidates[0].id) if candidates else None,
            )
        
        # 查找同时满足所有必要技能的员工
        candidate_scores = []
        
        for req_skill in required_skills:
            skill_id = req_skill.get("skill_id")
            min_level = req_skill.get("min_level", "L2")
            weight = req_skill.get("weight", 1.0)  # 技能权重
            
            if skill_id:
                qualified_users = await self.find_qualified_employees(
                    skill_id=skill_id,
                    min_level=min_level,
                )
                
                for user in qualified_users:
                    user_str_id = str(user.id)
                    if not any(c["user_id"] == user_str_id for c in candidate_scores):
                        candidate_scores.append({
                            "user_id": user_str_id,
                            "score": 0.0,
                            "matched_skills": [],
                        })
                    
                    # 为匹配的技能加分
                    emp_skills = await self.get_employee_skills(user_str_id)
                    for emp_skill in emp_skills:
                        if emp_skill.skill_id == skill_id:
                            # 根据等级打分 (L1=60, L2=70, L3=80, L4=90, L5=100)
                            level_score = SKILL_LEVELS.get(emp_skill.level, 1) * 20
                            candidate_scores_candidate = next(c for c in candidate_scores if c["user_id"] == user_str_id)
                            candidate_scores_candidate["score"] = min(100.0, candidate_scores_candidate["score"] + level_score * weight)
                            candidate_scores_candidate["matched_skills"].append({
                                "skill_id": skill_id,
                                "skill_name": skill.name if hasattr(skill, 'name') else f"Skill_{skill_id}",
                                "matched_level": emp_skill.level,
                                "weight": weight,
                            })
        
        # 按得分排序并推荐最高分
        candidate_scores.sort(key=lambda x: x["score"], reverse=True)
        
        recommended_user = candidate_scores[0]["user_id"] if candidate_scores else None
        
        return SkillMatchResult(
            task_id=task.id,
            task_type=task.task_type,
            matched_user_ids=[c["user_id"] for c in candidate_scores],
            score_details=candidate_scores,
            recommended_user=recommended_user,
        )
    
    async def _get_all_available_users(self) -> List[User]:
        """获取所有可用员工（活跃状态）"""
        now = datetime.utcnow()
        result = await self.db.execute(
            select(User)
            .where(
                User.is_active == True,
                User.role != "",  # 有角色的才算正式员工
            )
            .order_by(User.created_at.asc())
        )
        return result.scalars().all()
    
    async def get_expiring_certifications(self, days: int = 30) -> List[Dict]:
<<<<<<< HEAD
        """获取即将过期的资质认证"""
        target_date = date.today()
        from sqlalchemy import func
        
        result = await self.db.execute(
            select(EmployeeSkill, User, Skill)
            .join(User, EmployeeSkill.user_id == User.id)
            .join(Skill, EmployeeSkill.skill_id == Skill.id)
            .where(
                EmployeeSkill.expiry_date.isnot(None),
                EmployeeSkill.expiry_date <= target_date + timedelta(days=days),
                EmployeeSkill.expiry_date >= target_date,
            )
=======
        """获取即将过期的资质认证（数据源：hr_employee_skills + hr_employees + skills）"""
        target_date = date.today()
        sql = """
            SELECT he.employee_code, he.name, s.name AS skill_name,
                   hes.level, hes.expiry_date
            FROM hr_employee_skills hes
            JOIN hr_employees he ON he.id = hes.hr_employee_id
            JOIN skills s ON s.id = hes.skill_id
            WHERE he.status = 'active'
              AND hes.expiry_date IS NOT NULL
              AND hes.expiry_date >= :start_date
              AND hes.expiry_date <= :end_date
            ORDER BY hes.expiry_date
        """
        result = await self.db.execute(
            text(sql),
            {"start_date": target_date, "end_date": target_date + timedelta(days=days)},
>>>>>>> 7258e8d
        )
        expiring = []
        for r in result.all():
            days_left = (r.expiry_date - target_date).days
            expiring.append({
<<<<<<< HEAD
                "user_id": str(user.id),
                "username": user.username,
                "full_name": user.full_name,
                "skill_name": skill.name,
                "skill_code": skill.code,
                "current_level": emp_skill.level,
                "expiry_date": emp_skill.expiry_date,
                "days_until_expiry": (emp_skill.expiry_date.date() - target_date).days if emp_skill.expiry_date else None,
                "score": emp_skill.score,
=======
                "user_id": r.employee_code,
                "user_name": r.name,
                "username": r.name,
                "skill_name": r.skill_name,
                "current_level": r.level,
                "expiry_date": r.expiry_date,
                "days_remaining": days_left,
                "days_until_expiry": days_left,
>>>>>>> 7258e8d
            })
        return expiring
    
    async def calculate_department_skill_gap(
        self,
        factory_id: str,
        required_skills: List[Dict[str, Any]],  # [{"skill_id": int, "min_level": str}]
    ) -> Dict[str, Any]:
        """
        计算部门技能缺口
        
        分析部门当前拥有技能与所需技能的差距
        
        Args:
            factory_id: 工厂ID
            required_skills: 所需技能列表
        
        Returns:
            技能缺口分析报告
        """
        # 获取部门所有员工及其技能
        matrix = await self.get_skill_matrix(factory_id=factory_id)
        
        # 构建员工技能集
        employee_skills_map = {}
        for emp in matrix:
            employee_skills_map[emp.user_id] = {
                "skills": {s["skill_id"]: s for s in emp.skills if s.get("skill_id")},
                "total_skills": len(emp.skills),
            }
        
        # 分析每个需求的满足情况
        gap_analysis = []
        skills_met = 0
        skills_missing = 0
        
        for req in required_skills:
            skill_id = req.get("skill_id")
            min_level = req.get("min_level", "L2")
            min_level_num = SKILL_LEVELS.get(min_level, 2)
            
            # 检查哪些员工满足该技能
            met_employees = []
            missing_employees = []
            
            for emp_id, emp_data in employee_skills_map.items():
                if skill_id in emp_data["skills"]:
                    emp_level = emp_data["skills"][skill_id]["level"]
                    if SKILL_LEVELS.get(emp_level, 0) >= min_level_num:
                        met_employees.append(emp_id)
                    else:
                        missing_employees.append(emp_id)
                else:
                    missing_employees.append(emp_id)
            
            if met_employees:
                skills_met += 1
            else:
                skills_missing += 1
            
            gap_analysis.append({
                "skill_id": skill_id,
                "min_required_level": min_level,
                "employees_met": met_employees,
                "employees_missing": missing_employees,
                "met_count": len(met_employees),
                "missing_count": len(missing_employees),
            })
        
        total_emps = len(matrix)
        satisfaction_rate = round(skills_met / len(required_skills) * 100, 2) if required_skills else 100.0
        
        return {
            "factory_id": factory_id,
            "total_employees": total_emps,
            "total_required_skills": len(required_skills),
            "skills_met": skills_met,
            "skills_missing": skills_missing,
            "satisfaction_rate": satisfaction_rate,
            "gap_analysis": gap_analysis,
            "recommendations": self._generate_skill_gap_recommendations(gap_analysis, total_emps),
        }
    
    def _generate_skill_gap_recommendations(self, gap_analysis: List, total_employees: int) -> List[str]:
        """生成技能缺口改善建议"""
        recommendations = []
        
        for item in gap_analysis:
            if item["met_count"] == 0:
                recommendations.append(
                    f"技能 '{item['skill_id']}'无员工达到要求等级 '{item['min_required_level']}'，"
                    f"需要组织专项培训或引进外部人才"
                )
            elif item["met_count"] < total_emps * 0.3:
                recommendations.append(
                    f"技能 '{item['skill_id']}'仅 {item['met_count']}名员工达标（占比{round(item['met_count']/total_employees*100)}%），"
                    f"建议扩大培训范围"
                )
        
        if total_employees > 0 and any(item["met_count"] > 0 for item in gap_analysis):
            satisfied_items = sum(1 for item in gap_analysis if item["met_count"] > 0)
            recommendations.append(
                f"共 {satisfied_items}/{len(gap_analysis)}项技能已有员工覆盖，继续保持良好技能储备"
            )
        
        return recommendations or ["当前部门技能配置完全满足需求，无需额外改善"]
    
    async def get_employee_capability_score(self, user_id: str) -> float:
        """计算员工综合能力评分（加权平均分）"""
        skills = await self.get_employee_skills(user_id)
        if not skills:
            return 0.0
        
        # 每个技能按等级加权：L1=1, L2=2, L3=3, L4=4, L5=5
        total_weighted_score = 0
        count = 0
        
        for skill in skills:
            level_num = SKILL_LEVELS.get(skill.level, 1)
            weight = skill.score or 1.0
            total_weighted_score += level_num * weight
            count += 1
        
        return round(total_weighted_score / count, 2) if count > 0 else 0.0
    
    # ===== 辅助方法 =====
    
    def _emp_skill_to_response(self, emp_skill: EmployeeSkill) -> EmployeeSkillResponse:
        """将EmployeeSkill模型转换为响应对象"""
        return EmployeeSkillResponse(
            id=emp_skill.id,
            user_id=emp_skill.user_id,
            skill_id=emp_skill.skill_id,
            level=emp_skill.level,
            score=emp_skill.score,
            certified_date=emp_skill.certified_date,
            expiry_date=emp_skill.expiry_date,
            remarks=emp_skill.remarks,
            evaluated_by=emp_skill.evaluated_by,
            created_at=emp_skill.created_at,
            updated_at=emp_skill.updated_at,
        )


class SkillService:
    """技能库管理服务"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_skill(self, skill_data: SkillCreate) -> Skill:
        """创建新技能"""
        skill = Skill(**skill_data.model_dump(exclude_unset=True))
        self.db.add(skill)
        await self.db.commit()
        await self.db.refresh(skill)
        return skill
    
    async def get_all_skills(self, category: Optional[str] = None, active_only: bool = True) -> List[Skill]:
        """获取所有技能"""
        query = select(Skill)
        if active_only:
            query = query.where(Skill.is_active == True)
        if category:
            query = query.where(Skill.category == category)
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def update_skill(self, skill_id: int, updates: dict) -> Skill:
        """更新技能信息"""
        result = await self.db.execute(
            select(Skill).where(Skill.id == skill_id)
        )
        skill = result.scalar_one_or_none()
        if not skill:
            raise ValueError(f"Skill {skill_id} not found")
        
        for key, value in updates.items():
            if hasattr(skill, key):
                setattr(skill, key, value)
        
        await self.db.commit()
        await self.db.refresh(skill)
        return skill
    
    async def deactivate_skill(self, skill_id: int) -> bool:
        """标记技能为非激活（逻辑删除）"""
        result = await self.db.execute(
            select(Skill).where(Skill.id == skill_id, Skill.is_active == True)
        )
        skill = result.scalar_one_or_none()
        if skill:
            skill.is_active = False
            await self.db.commit()
            return True
        return False


class TrainingService:
    """培训记录服务"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_training_record(self, record_data: TrainingRecordCreate) -> TrainingRecord:
        """创建培训记录"""
        record = TrainingRecord(**record_data.model_dump(exclude_unset=True))
        self.db.add(record)
        await self.db.commit()
        await self.db.refresh(record)
        return record
    
    async def get_employee_training_history(self, user_id: int) -> List[TrainingRecord]:
        """获取员工培训历史（按开始日期降序）"""
        result = await self.db.execute(
            select(TrainingRecord)
            .where(TrainingRecord.user_id == user_id)
            .order_by(TrainingRecord.start_date.desc())
        )
        return list(result.scalars().all())
    
    async def get_training_compliance_rate(self, user_id: int, period_days: int = 365) -> float:
        """获取员工培训合规率（指定时间段内）"""
        cutoff_date = datetime.utcnow() - timedelta(days=period_days)
        total_required = 5  # 假设每年需要5次培训
        
        result = await self.db.execute(
            select(TrainingRecord)
            .where(
                TrainingRecord.user_id == user_id,
                TrainingRecord.start_date >= cutoff_date,
                TrainingRecord.result == "completed"
            )
        )
        completed_count = result.scalar() or 0
        
        return round(min(completed_count / total_required * 100, 100.0), 2)