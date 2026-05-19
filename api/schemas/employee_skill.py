"""
员工能力标签 Schema 定义
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date, datetime
from enum import Enum


class SkillLevelEnum(str, Enum):
    """技能等级枚举"""
    L1_TRAINEE = "L1"
    L2_BASIC = "L2"
    L3_INDEPENDENT = "L3"
    L4_ADVANCED = "L4"
    L5_EXPERT = "L5"


# ==================== Skill ====================

class SkillCreate(BaseModel):
    """创建技能"""
    code: str = Field(..., max_length=20, description="技能编码")
    name: str = Field(..., max_length=100, description="技能名称")
    category: Optional[str] = Field(None, max_length=50, description="分类")
    description: Optional[str] = Field(None, description="技能描述")


class SkillUpdate(BaseModel):
    """更新技能"""
    name: Optional[str] = Field(None, max_length=100)
    category: Optional[str] = Field(None, max_length=50)
    description: Optional[str] = None
    is_active: Optional[bool] = None


class SkillResponse(BaseModel):
    """技能响应"""
    id: int
    code: str
    name: str
    category: Optional[str]
    description: Optional[str]
    is_active: bool
    
    class Config:
        from_attributes = True


# ==================== EmployeeSkill ====================

class EmployeeSkillCreate(BaseModel):
    """给员工添加技能"""
    skill_id: int = Field(..., description="技能 ID")
    level: SkillLevelEnum = Field(..., description="技能等级")
    certified_date: Optional[date] = Field(None, description="认证日期")
    expiry_date: Optional[date] = Field(None, description="有效期至")
    score: Optional[float] = Field(None, ge=0, le=100, description="评分")
    remarks: Optional[str] = Field(None, description="备注")


class EmployeeSkillUpdate(BaseModel):
    """更新员工技能"""
    level: Optional[SkillLevelEnum] = None
    score: Optional[float] = Field(None, ge=0, le=100)
    certified_date: Optional[date] = None
    expiry_date: Optional[date] = None
    remarks: Optional[str] = None


class EmployeeSkillItem(BaseModel):
    """员工技能项"""
    id: int
    skill_id: int
    skill_name: str
    skill_category: Optional[str]
    level: SkillLevelEnum
    score: Optional[float]
    certified_date: Optional[date]
    expiry_date: Optional[date]
    is_valid: bool
    
    class Config:
        from_attributes = True


class EmployeeSkillResponse(BaseModel):
    """员工技能详情"""
    id: int
    user_id: int
    skill_id: int
    level: SkillLevelEnum
    score: Optional[float]
    certified_date: Optional[date]
    expiry_date: Optional[date]
    remarks: Optional[str]
    evaluated_by: Optional[int]
    created_at: datetime
    updated_at: Optional[datetime]
    
    class Config:
        from_attributes = True


# ==================== Skill Matrix ====================

class SkillMatrixItem(BaseModel):
    """技能矩阵项"""
    skill_name: str
    category: Optional[str]
    level: str
    score: Optional[float]
    certified_date: Optional[date]
    expiry_date: Optional[date]
    is_valid: bool


class SkillMatrixResponse(BaseModel):
    """技能矩阵响应"""
    user_id: int
    name: str
    department: Optional[str]
    skills: List[SkillMatrixItem]


# ==================== Training Record ====================

class TrainingRecordCreate(BaseModel):
    """创建培训记录"""
    user_id: int = Field(..., description="员工 ID")
    skill_id: int = Field(..., description="技能 ID")
    training_type: str = Field(..., description="培训类型")
    trainer: Optional[str] = Field(None, description="培训师")
    start_date: date = Field(..., description="开始日期")
    end_date: Optional[date] = Field(None, description="结束日期")
    hours: Optional[float] = Field(None, description="培训时长")
    result: Optional[str] = Field(None, description="结果")
    certificate_no: Optional[str] = Field(None, description="证书编号")


class TrainingRecordResponse(BaseModel):
    """培训记录响应"""
    id: int
    user_id: int
    skill_id: int
    training_type: str
    trainer: Optional[str]
    start_date: date
    end_date: Optional[date]
    hours: Optional[float]
    result: Optional[str]
    certificate_no: Optional[str]
    created_at: datetime
    
    class Config:
        from_attributes = True


# ==================== Employee Skill Match ====================

class EmployeeSkillMatch(BaseModel):
    """员工技能匹配结果"""
    user_id: int
    username: str
    department: Optional[str]
    matched_skills: List[dict]
    match_score: float  # 匹配度百分比
