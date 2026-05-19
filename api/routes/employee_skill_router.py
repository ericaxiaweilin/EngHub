"""
员工能力标签 API 路由
提供技能管理、员工技能评估、技能矩阵查询等功能
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from datetime import date

from database.db_config import get_db
from api.services.employee_skill_service import (
    EmployeeSkillService, SkillService, TrainingService
)
from api.schemas.employee_skill import (
    SkillCreate, SkillUpdate, SkillResponse,
    EmployeeSkillCreate, EmployeeSkillUpdate, EmployeeSkillResponse,
    TrainingRecordCreate, TrainingRecordResponse,
    SkillMatrixResponse
)
from database.models import User
from api.services.auth_service import get_current_user


router = APIRouter(prefix="/employee-skills", tags=["员工能力标签"])


# ==================== 技能库管理 ====================

@router.post("/skills", response_model=SkillResponse, status_code=status.HTTP_201_CREATED)
async def create_skill(
    skill_data: SkillCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """创建新技能"""
    service = SkillService(db)
    return await service.create_skill(skill_data)


@router.get("/skills", response_model=List[SkillResponse])
async def get_all_skills(
    category: Optional[str] = Query(None, description="技能分类"),
    db: AsyncSession = Depends(get_db)
):
    """获取所有技能"""
    service = SkillService(db)
    skills = await service.get_all_skills(category)
    return skills


@router.get("/skills/{skill_id}", response_model=SkillResponse)
async def get_skill(
    skill_id: int,
    db: AsyncSession = Depends(get_db)
):
    """获取技能详情"""
    service = SkillService(db)
    try:
        return await service.update_skill(skill_id, {})  # Just to check existence
    except ValueError:
        raise HTTPException(status_code=404, detail="Skill not found")


@router.put("/skills/{skill_id}", response_model=SkillResponse)
async def update_skill(
    skill_id: int,
    updates: SkillUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """更新技能信息"""
    service = SkillService(db)
    try:
        return await service.update_skill(skill_id, updates.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ==================== 员工技能管理 ====================

@router.get("/employees/{user_id}/skills", response_model=List[EmployeeSkillResponse])
async def get_employee_skills(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取员工的所有技能"""
    service = EmployeeSkillService(db)
    return await service.get_employee_skills(user_id)


@router.post("/employees/{user_id}/skills", response_model=EmployeeSkillResponse)
async def add_skill_to_employee(
    user_id: int,
    skill_data: EmployeeSkillCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """给员工添加/更新技能标签"""
    service = EmployeeSkillService(db)
    try:
        return await service.add_skill_to_employee(
            user_id=user_id,
            skill_data=skill_data,
            evaluated_by=current_user.id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/skill-matrix", response_model=List[SkillMatrixResponse])
async def get_skill_matrix(
    department: Optional[str] = Query(None, description="部门"),
    skill_category: Optional[str] = Query(None, description="技能分类"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取技能矩阵
    展示全员或特定部门的技能分布情况
    """
    service = EmployeeSkillService(db)
    return await service.get_skill_matrix(department, skill_category)


@router.get("/qualified-employees")
async def find_qualified_employees(
    skill_id: int = Query(..., description="技能 ID"),
    min_level: str = Query("L2", description="最低技能等级"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """查找具备特定技能等级的员工"""
    from models.employee_skill import SkillLevel
    
    level_map = {
        "L1": SkillLevel.L1_TRAINEE,
        "L2": SkillLevel.L2_BASIC,
        "L3": SkillLevel.L3_INDEPENDENT,
        "L4": SkillLevel.L4_ADVANCED,
        "L5": SkillLevel.L5_EXPERT
    }
    
    if min_level not in level_map:
        raise HTTPException(status_code=400, detail="Invalid level. Use L1-L5")
    
    service = EmployeeSkillService(db)
    employees = await service.find_qualified_employees(
        skill_id=skill_id,
        min_level=level_map[min_level]
    )
    
    return [
        {"id": emp.id, "username": emp.username, "department": emp.department}
        for emp in employees
    ]


@router.get("/expiring-certifications")
async def get_expiring_certifications(
    days: int = Query(30, description="提前多少天提醒", ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取即将过期的资质认证"""
    service = EmployeeSkillService(db)
    return await service.get_expiring_certifications(days)


# ==================== 培训记录 ====================

@router.post("/training-records", response_model=TrainingRecordResponse, status_code=status.HTTP_201_CREATED)
async def create_training_record(
    record_data: TrainingRecordCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """创建培训记录"""
    service = TrainingService(db)
    return await service.create_training_record(record_data)


@router.get("/employees/{user_id}/training-history", response_model=List[TrainingRecordResponse])
async def get_employee_training_history(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取员工培训历史"""
    service = TrainingService(db)
    return await service.get_employee_training_history(user_id)
