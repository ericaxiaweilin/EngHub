"""
员工能力标签服务
提供技能矩阵、资质认证、人员匹配等功能
"""
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from datetime import date, datetime
from typing import List, Optional, Dict
from database.models import (
    EmployeeSkill, Skill, TrainingRecord, User
)
from api.schemas.employee_skill import (
    EmployeeSkillCreate, EmployeeSkillUpdate, EmployeeSkillResponse,
    SkillCreate, SkillResponse, TrainingRecordCreate,
    SkillMatrixResponse, EmployeeSkillMatch
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
    
    async def get_employee_skills(self, user_id: int) -> List[EmployeeSkill]:
        """获取员工所有技能"""
        result = await self.db.execute(
            select(EmployeeSkill)
            .where(EmployeeSkill.user_id == user_id)
            .options(joinedload(EmployeeSkill.skill))
        )
        return list(result.scalars().all())
    
    async def add_skill_to_employee(
        self, 
        user_id, 
        skill_data: EmployeeSkillCreate,
        evaluated_by
    ):
        """给员工添加技能标签"""
        # 检查技能是否存在
        skill_result = await self.db.execute(
            select(Skill).where(Skill.id == skill_data.skill_id)
        )
        skill = skill_result.scalar_one_or_none()
        if not skill:
            raise ValueError(f"Skill {skill_data.skill_id} not found")
        
        # 检查是否已存在该技能
        existing = await self.db.execute(
            select(EmployeeSkill).where(
                EmployeeSkill.user_id == user_id,
                EmployeeSkill.skill_id == skill_data.skill_id
            )
        )
        emp_skill = existing.scalar_one_or_none()
        
        if emp_skill:
            # 更新现有技能
            emp_skill.level = skill_data.level.value if hasattr(skill_data.level, 'value') else skill_data.level
            emp_skill.score = skill_data.score
            emp_skill.certified_date = skill_data.certified_date
            emp_skill.expiry_date = skill_data.expiry_date
            emp_skill.remarks = skill_data.remarks
            emp_skill.evaluated_by = evaluated_by
            emp_skill.updated_at = datetime.utcnow()
        else:
            # 创建新技能记录
            emp_skill = EmployeeSkill(
                user_id=user_id,
                skill_id=skill_data.skill_id,
                level=skill_data.level.value if hasattr(skill_data.level, 'value') else skill_data.level,
                score=skill_data.score,
                certified_date=skill_data.certified_date,
                expiry_date=skill_data.expiry_date,
                remarks=skill_data.remarks,
                evaluated_by=evaluated_by
            )
            self.db.add(emp_skill)
        
        await self.db.commit()
        await self.db.refresh(emp_skill)
        return emp_skill
    
    async def get_skill_matrix(
        self, 
        department: Optional[str] = None,
        skill_category: Optional[str] = None
    ) -> List[SkillMatrixResponse]:
        """
        获取技能矩阵
        展示部门/全员的技能分布情况
        """
        query = (
            select(User, EmployeeSkill, Skill)
            .join(EmployeeSkill, User.id == EmployeeSkill.user_id)
            .join(Skill, EmployeeSkill.skill_id == Skill.id)
            .where((EmployeeSkill.expiry_date.is_(None)) | (EmployeeSkill.expiry_date >= datetime.utcnow()))
        )
        
        if department:
            query = query.where(User.factory_id == department)
        if skill_category:
            query = query.where(Skill.category == skill_category)
        
        result = await self.db.execute(query)
        rows = result.all()
        
        matrix = {}
        for user, emp_skill, skill in rows:
            if user.id not in matrix:
                matrix[user.id] = SkillMatrixResponse(
                    user_id=str(user.id),
                    name=user.full_name or user.username,
                    department=user.factory_id,
                    skills=[]
                )
            
            # Check if certification is valid
            is_valid = True
            if emp_skill.expiry_date and emp_skill.expiry_date < datetime.utcnow():
                is_valid = False
            
            matrix[user.id].skills.append({
                "skill_name": skill.name,
                "category": skill.category,
                "level": emp_skill.level,
                "score": float(emp_skill.score) if emp_skill.score else None,
                "certified_date": emp_skill.certified_date,
                "expiry_date": emp_skill.expiry_date,
                "is_valid": is_valid
            })
        
        return list(matrix.values())
    
    async def find_qualified_employees(
        self, 
        skill_id: int, 
        min_level: str = "L2"
    ) -> List[User]:
        """查找具备特定技能等级的员工"""
        min_level_num = SKILL_LEVELS.get(min_level, 2)
        
        # Get all qualified user IDs
        result = await self.db.execute(
            select(EmployeeSkill.user_id)
            .where(
                EmployeeSkill.skill_id == skill_id,
                EmployeeSkill.level.in_([l for l, num in SKILL_LEVELS.items() if num >= min_level_num]),
                or_(
                    EmployeeSkill.expiry_date.is_(None),
                    EmployeeSkill.expiry_date >= datetime.utcnow()
                )
            )
        )
        qualified_user_ids = [row[0] for row in result.all()]
        
        if not qualified_user_ids:
            return []
        
        # Get user details
        users_result = await self.db.execute(
            select(User).where(User.id.in_(qualified_user_ids))
        )
        return list(users_result.scalars().all())
    
    def _level_gte(self, level: str, min_level: str) -> bool:
        """判断技能等级是否大于等于最低要求"""
        return SKILL_LEVELS.get(level, 0) >= SKILL_LEVELS.get(min_level, 0)
    
    async def get_expiring_certifications(self, days: int = 30) -> List[Dict]:
        """获取即将过期的资质认证"""
        from sqlalchemy import func
        target_date = date.today()
        
        result = await self.db.execute(
            select(EmployeeSkill, User, Skill)
            .join(User, EmployeeSkill.user_id == User.id)
            .join(Skill, EmployeeSkill.skill_id == Skill.id)
            .where(
                EmployeeSkill.expiry_date.isnot(None),
                EmployeeSkill.expiry_date <= func.date(target_date, f'+{days} days'),
                EmployeeSkill.expiry_date >= target_date
            )
        )
        
        expiring = []
        for emp_skill, user, skill in result.all():
            expiring.append({
                "user_id": user.id,
                "username": user.username,
                "skill_name": skill.name,
                "current_level": emp_skill.level.value,
                "expiry_date": emp_skill.expiry_date,
                "days_until_expiry": (emp_skill.expiry_date - target_date).days
            })
        
        return expiring


class SkillService:
    """技能库管理服务"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_skill(self, skill_data: SkillCreate) -> Skill:
        """创建新技能"""
        skill = Skill(**skill_data.model_dump())
        self.db.add(skill)
        await self.db.commit()
        await self.db.refresh(skill)
        return skill
    
    async def get_all_skills(self, category: Optional[str] = None) -> List[Skill]:
        """获取所有技能"""
        query = select(Skill).where(Skill.is_active == True)
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
            setattr(skill, key, value)
        
        await self.db.commit()
        await self.db.refresh(skill)
        return skill


class TrainingService:
    """培训记录服务"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_training_record(self, record_data: TrainingRecordCreate) -> TrainingRecord:
        """创建培训记录"""
        record = TrainingRecord(**record_data.model_dump())
        self.db.add(record)
        await self.db.commit()
        await self.db.refresh(record)
        return record
    
    async def get_employee_training_history(self, user_id: int) -> List[TrainingRecord]:
        """获取员工培训历史"""
        result = await self.db.execute(
            select(TrainingRecord)
            .where(TrainingRecord.user_id == user_id)
            .order_by(TrainingRecord.start_date.desc())
        )
        return list(result.scalars().all())
