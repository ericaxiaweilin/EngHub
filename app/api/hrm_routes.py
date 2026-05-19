"""
HRM API Routes - 人力资源管理 API
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from datetime import date, datetime
from pydantic import BaseModel, Field

from app.core.database import get_db
from app.services.hrm_service import (
    DepartmentService, EmployeeService, AttendanceService,
    LeaveService, SalaryService, AdminService, AssetService,
    MeetingRoomService, NoticeService
)
from app.models.hrm import EmploymentType, EmployeeStatus, LeaveType, RequestType

router = APIRouter(prefix="/hrm", tags=["HRM 人力资源"])


# ==================== Pydantic Schemas ====================

class DepartmentCreate(BaseModel):
    code: str
    name: str
    parent_id: Optional[int] = None
    level: int = 1
    manager_id: Optional[int] = None


class DepartmentResponse(BaseModel):
    id: int
    code: str
    name: str
    parent_id: Optional[int] = None
    level: int
    manager_id: Optional[int] = None
    status: bool
    
    class Config:
        from_attributes = True


class EmployeeCreate(BaseModel):
    name: str
    gender: Optional[str] = None
    birth_date: Optional[date] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    department_id: Optional[int] = None
    position: Optional[str] = None
    entry_date: date
    employment_type: EmploymentType = EmploymentType.FULL_TIME
    base_salary: Optional[float] = None
    performance_salary: Optional[float] = None


class EmployeeResponse(BaseModel):
    id: int
    employee_no: str
    name: str
    gender: Optional[str] = None
    department_id: Optional[int] = None
    position: Optional[str] = None
    entry_date: date
    employment_type: EmploymentType
    status: EmployeeStatus
    base_salary: Optional[float] = None
    
    class Config:
        from_attributes = True


class LeaveApply(BaseModel):
    type: LeaveType
    start_date: date
    end_date: date
    reason: str
    approver_id: Optional[int] = None


class LeaveResponse(BaseModel):
    id: int
    employee_id: int
    type: LeaveType
    start_date: date
    end_date: date
    days: float
    reason: str
    status: str
    
    class Config:
        from_attributes = True


class AdminRequestCreate(BaseModel):
    type: RequestType
    title: str
    content: str
    amount: Optional[float] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


class AssetAssign(BaseModel):
    user_id: int


class MeetingRoomBook(BaseModel):
    title: str
    start_time: datetime
    end_time: datetime
    participants: int
    description: Optional[str] = None


class NoticeCreate(BaseModel):
    title: str
    content: str
    type: str = "general"
    priority: int = 0
    is_top: bool = False


# ==================== 部门管理 ====================

@router.get("/departments", response_model=List[DepartmentResponse])
async def get_departments(db: AsyncSession = Depends(get_db), status: bool = True):
    """获取部门列表"""
    return await DepartmentService.get_all(db, status)


@router.get("/departments/tree")
async def get_department_tree(db: AsyncSession = Depends(get_db)):
    """获取部门树形结构"""
    return await DepartmentService.get_tree(db)


@router.post("/departments", response_model=DepartmentResponse)
async def create_department(dept: DepartmentCreate, db: AsyncSession = Depends(get_db)):
    """创建部门"""
    return await DepartmentService.create(db, dept.model_dump())


@router.put("/departments/{dept_id}", response_model=DepartmentResponse)
async def update_department(dept_id: int, dept: DepartmentCreate, db: AsyncSession = Depends(get_db)):
    """更新部门"""
    result = await DepartmentService.update(db, dept_id, dept.model_dump())
    if not result:
        raise HTTPException(status_code=404, detail="Department not found")
    return result


@router.delete("/departments/{dept_id}")
async def delete_department(dept_id: int, db: AsyncSession = Depends(get_db)):
    """删除部门（软删除）"""
    success = await DepartmentService.delete(db, dept_id)
    if not success:
        raise HTTPException(status_code=404, detail="Department not found")
    return {"message": "Department deleted successfully"}


# ==================== 员工管理 ====================

@router.get("/employees", response_model=List[EmployeeResponse])
async def get_employees(
    db: AsyncSession = Depends(get_db),
    department_id: Optional[int] = None,
    keyword: Optional[str] = None
):
    """获取员工列表"""
    return await EmployeeService.get_all(db, department_id=department_id, keyword=keyword)


@router.get("/employees/{emp_id}", response_model=EmployeeResponse)
async def get_employee(emp_id: int, db: AsyncSession = Depends(get_db)):
    """获取员工详情"""
    emp = await EmployeeService.get_by_id(db, emp_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    return emp


@router.post("/employees", response_model=EmployeeResponse)
async def create_employee(emp: EmployeeCreate, db: AsyncSession = Depends(get_db)):
    """创建员工"""
    return await EmployeeService.create(db, emp.model_dump())


@router.put("/employees/{emp_id}", response_model=EmployeeResponse)
async def update_employee(emp_id: int, emp: EmployeeCreate, db: AsyncSession = Depends(get_db)):
    """更新员工信息"""
    result = await EmployeeService.update(db, emp_id, emp.model_dump())
    if not result:
        raise HTTPException(status_code=404, detail="Employee not found")
    return result


@router.post("/employees/{emp_id}/resign")
async def resign_employee(
    emp_id: int,
    reason: str,
    resign_date: date,
    db: AsyncSession = Depends(get_db)
):
    """办理离职"""
    result = await EmployeeService.resign(db, emp_id, reason, resign_date)
    if not result:
        raise HTTPException(status_code=404, detail="Employee not found")
    return {"message": "Employee resigned successfully"}


# ==================== 考勤管理 ====================

@router.get("/attendance/stats/{emp_id}")
async def get_attendance_stats(
    emp_id: int,
    year: int,
    month: int,
    db: AsyncSession = Depends(get_db)
):
    """获取员工月度考勤统计"""
    return await AttendanceService.get_monthly_stats(db, emp_id, year, month)


# ==================== 请假管理 ====================

@router.post("/leaves/apply", response_model=LeaveResponse)
async def apply_leave(leave: LeaveApply, db: AsyncSession = Depends(get_db)):
    """申请请假"""
    result = await LeaveService.apply_leave(
        db,
        employee_id=1,
        leave_type=leave.type.value,
        start_date=leave.start_date,
        end_date=leave.end_date,
        reason=leave.reason,
        approver_id=leave.approver_id
    )
    return result


@router.post("/leaves/{leave_id}/approve")
async def approve_leave(
    leave_id: int,
    approved: bool,
    remark: str,
    db: AsyncSession = Depends(get_db)
):
    """审批请假"""
    result = await LeaveService.approve(db, leave_id, approved, remark)
    if not result:
        raise HTTPException(status_code=404, detail="Leave request not found")
    return {"message": "Leave request approved" if approved else "Leave request rejected"}


@router.get("/leaves/my")
async def get_my_leaves(db: AsyncSession = Depends(get_db)):
    """获取我的请假记录"""
    return await LeaveService.get_employee_leaves(db, employee_id=1)


# ==================== 薪资管理 ====================

@router.post("/salary/calculate/{emp_id}")
async def calculate_salary(
    emp_id: int,
    year: int,
    month: int,
    db: AsyncSession = Depends(get_db)
):
    """计算员工薪资"""
    try:
        result = await SalaryService.calculate_salary(db, emp_id, year, month)
        return {"message": "Salary calculated successfully", "salary_id": result.id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ==================== 行政管理 ====================

@router.post("/admin-requests")
async def create_admin_request(req: AdminRequestCreate, db: AsyncSession = Depends(get_db)):
    """创建行政申请"""
    return await AdminService.create_request(
        db,
        employee_id=1,
        request_type=req.type.value,
        title=req.title,
        content=req.content,
        amount=req.amount,
        start_date=req.start_date,
        end_date=req.end_date
    )


@router.post("/admin-requests/{request_id}/approve")
async def approve_admin_request(
    request_id: int,
    approved: bool,
    remark: str,
    db: AsyncSession = Depends(get_db)
):
    """审批行政申请"""
    result = await AdminService.approve_request(db, request_id, approved, remark, approver_id=1)
    if not result:
        raise HTTPException(status_code=404, detail="Request not found")
    return {"message": "Request approved" if approved else "Request rejected"}


# ==================== 资产管理 ====================

@router.post("/assets/{asset_id}/assign")
async def assign_asset(asset_id: int, data: AssetAssign, db: AsyncSession = Depends(get_db)):
    """分配资产"""
    result = await AssetService.assign_asset(db, asset_id, data.user_id)
    if not result:
        raise HTTPException(status_code=404, detail="Asset not found")
    return {"message": "Asset assigned successfully"}


@router.post("/assets/{asset_id}/return")
async def return_asset(asset_id: int, db: AsyncSession = Depends(get_db)):
    """归还资产"""
    result = await AssetService.return_asset(db, asset_id)
    if not result:
        raise HTTPException(status_code=404, detail="Asset not found")
    return {"message": "Asset returned successfully"}


# ==================== 会议室预定 ====================

@router.post("/meeting-rooms/{room_id}/book")
async def book_meeting_room(room_id: int, booking: MeetingRoomBook, db: AsyncSession = Depends(get_db)):
    """预定会议室"""
    available = await MeetingRoomService.check_availability(
        db, room_id, booking.start_time, booking.end_time
    )
    if not available:
        raise HTTPException(status_code=400, detail="Meeting room is not available")
    
    return await MeetingRoomService.book_room(
        db,
        room_id=room_id,
        booker_id=1,
        title=booking.title,
        start_time=booking.start_time,
        end_time=booking.end_time,
        participants=booking.participants,
        description=booking.description
    )


@router.get("/meeting-rooms/{room_id}/availability")
async def check_room_availability(
    room_id: int,
    start_time: datetime,
    end_time: datetime,
    db: AsyncSession = Depends(get_db)
):
    """检查会议室可用性"""
    available = await MeetingRoomService.check_availability(db, room_id, start_time, end_time)
    return {"available": available}


# ==================== 公告管理 ====================

@router.post("/notices")
async def publish_notice(notice: NoticeCreate, db: AsyncSession = Depends(get_db)):
    """发布公告"""
    return await NoticeService.publish_notice(
        db,
        publisher_id=1,
        title=notice.title,
        content=notice.content,
        notice_type=notice.type,
        priority=notice.priority,
        is_top=notice.is_top
    )


@router.get("/notices")
async def get_notices(db: AsyncSession = Depends(get_db)):
    """获取所有公告"""
    return await NoticeService.get_all_notices(db)
