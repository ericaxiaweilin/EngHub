"""
HRM Services - 人力资源管理服务层
包含：员工管理、考勤管理、请假管理、薪资核算、行政管理
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import and_, or_, func, Date
from datetime import date, datetime
from typing import List, Optional, Dict, Any
from app.models.hrm import (
    Employee, Department, Attendance, Leave, Salary,
    AdminRequest, Asset, MeetingRoom, MeetingRoomBooking, Notice,
    EmploymentType, EmployeeStatus, AttendanceStatus, LeaveStatus, RequestStatus, AssetStatus
)


# ==================== 部门服务 ====================

class DepartmentService:
    """部门管理服务"""
    
    @staticmethod
    async def get_all(db: AsyncSession, status: bool = True) -> List[Department]:
        query = select(Department).where(Department.status == status)
        result = await db.execute(query)
        return list(result.scalars().all())
    
    @staticmethod
    async def get_by_id(db: AsyncSession, dept_id: int) -> Optional[Department]:
        query = select(Department).where(Department.id == dept_id)
        result = await db.execute(query)
        return result.scalar_one_or_none()
    
    @staticmethod
    async def create(db: AsyncSession, data: Dict[str, Any]) -> Department:
        dept = Department(**data)
        db.add(dept)
        await db.commit()
        await db.refresh(dept)
        return dept
    
    @staticmethod
    async def update(db: AsyncSession, dept_id: int, data: Dict[str, Any]) -> Optional[Department]:
        dept = await DepartmentService.get_by_id(db, dept_id)
        if dept:
            for key, value in data.items():
                setattr(dept, key, value)
            await db.commit()
            await db.refresh(dept)
        return dept
    
    @staticmethod
    async def delete(db: AsyncSession, dept_id: int) -> bool:
        dept = await DepartmentService.get_by_id(db, dept_id)
        if dept:
            dept.status = False
            await db.commit()
            return True
        return False
    
    @staticmethod
    async def get_tree(db: AsyncSession) -> List[Dict]:
        depts = await DepartmentService.get_all(db)
        tree = []
        for dept in depts:
            if dept.parent_id is None:
                node = {"id": dept.id, "name": dept.name, "code": dept.code, "children": []}
                children = [d for d in depts if d.parent_id == dept.id]
                for child in children:
                    node["children"].append({"id": child.id, "name": child.name, "code": child.code})
                tree.append(node)
        return tree


# ==================== 员工服务 ====================

class EmployeeService:
    """员工管理服务"""
    
    @staticmethod
    async def get_all(
        db: AsyncSession,
        department_id: Optional[int] = None,
        status: Optional[EmployeeStatus] = None,
        keyword: Optional[str] = None
    ) -> List[Employee]:
        query = select(Employee)
        if department_id:
            query = query.where(Employee.department_id == department_id)
        if status:
            query = query.where(Employee.status == status)
        if keyword:
            query = query.where(or_(
                Employee.name.like(f"%{keyword}%"),
                Employee.employee_no.like(f"%{keyword}%"),
                Employee.phone.like(f"%{keyword}%")
            ))
        result = await db.execute(query)
        return list(result.scalars().all())
    
    @staticmethod
    async def get_by_id(db: AsyncSession, emp_id: int) -> Optional[Employee]:
        query = select(Employee).where(Employee.id == emp_id)
        result = await db.execute(query)
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_by_employee_no(db: AsyncSession, employee_no: str) -> Optional[Employee]:
        query = select(Employee).where(Employee.employee_no == employee_no)
        result = await db.execute(query)
        return result.scalar_one_or_none()
    
    @staticmethod
    async def create(db: AsyncSession, data: Dict[str, Any]) -> Employee:
        if "employee_no" not in data:
            count = await db.scalar(select(func.count()).select_from(Employee))
            data["employee_no"] = f"EMP{count + 1:05d}"
        emp = Employee(**data)
        db.add(emp)
        await db.commit()
        await db.refresh(emp)
        return emp
    
    @staticmethod
    async def update(db: AsyncSession, emp_id: int, data: Dict[str, Any]) -> Optional[Employee]:
        emp = await EmployeeService.get_by_id(db, emp_id)
        if emp:
            for key, value in data.items():
                setattr(emp, key, value)
            await db.commit()
            await db.refresh(emp)
        return emp
    
    @staticmethod
    async def resign(db: AsyncSession, emp_id: int, reason: str, resign_date: date) -> Optional[Employee]:
        emp = await EmployeeService.get_by_id(db, emp_id)
        if emp:
            emp.status = EmployeeStatus.RESIGNED
            emp.resignation_reason = reason
            emp.resignation_date = resign_date
            await db.commit()
            await db.refresh(emp)
        return emp


# ==================== 考勤服务 ====================

class AttendanceService:
    """考勤管理服务"""
    
    @staticmethod
    async def record_attendance(
        db: AsyncSession,
        employee_id: int,
        clock_in: datetime,
        clock_out: datetime,
        scheduled_start: datetime,
        scheduled_end: datetime
    ) -> Attendance:
        late_minutes = int((clock_in - scheduled_start).total_seconds() / 60) if clock_in > scheduled_start else 0
        early_leave_minutes = int((scheduled_end - clock_out).total_seconds() / 60) if clock_out < scheduled_end else 0
        work_hours = (clock_out - clock_in).total_seconds() / 3600
        
        status = AttendanceStatus.NORMAL
        if late_minutes > 30:
            status = AttendanceStatus.LATE
        elif early_leave_minutes > 30:
            status = AttendanceStatus.EARLY_LEAVE
        
        attendance = Attendance(
            employee_id=employee_id,
            date=clock_in.date(),
            clock_in=clock_in,
            clock_out=clock_out,
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_end,
            work_hours=work_hours,
            late_minutes=late_minutes,
            early_leave_minutes=early_leave_minutes,
            status=status
        )
        db.add(attendance)
        await db.commit()
        await db.refresh(attendance)
        return attendance
    
    @staticmethod
    async def get_monthly_stats(db: AsyncSession, employee_id: int, year: int, month: int) -> Dict[str, Any]:
        start_date = date(year, month, 1)
        end_date = date(year, month + 1, 1) if month < 12 else date(year + 1, 1, 1)
        
        query = select(Attendance).where(
            and_(Attendance.employee_id == employee_id, Attendance.date >= start_date, Attendance.date < end_date)
        )
        result = await db.execute(query)
        attendances = list(result.scalars().all())
        
        return {
            "total_days": len(attendances),
            "normal_days": sum(1 for a in attendances if a.status == AttendanceStatus.NORMAL),
            "late_days": sum(1 for a in attendances if a.status == AttendanceStatus.LATE),
            "absent_days": sum(1 for a in attendances if a.status == AttendanceStatus.ABSENT),
            "total_work_hours": round(sum(a.work_hours or 0 for a in attendances), 2),
            "total_overtime_hours": round(sum(a.overtime_hours or 0 for a in attendances), 2)
        }


# ==================== 请假服务 ====================

class LeaveService:
    """请假管理服务"""
    
    @staticmethod
    async def apply_leave(
        db: AsyncSession,
        employee_id: int,
        leave_type: str,
        start_date: date,
        end_date: date,
        reason: str,
        approver_id: Optional[int] = None
    ) -> Leave:
        days = (end_date - start_date).days + 1
        leave = Leave(
            employee_id=employee_id,
            type=leave_type,
            start_date=start_date,
            end_date=end_date,
            days=days,
            reason=reason,
            approver_id=approver_id
        )
        db.add(leave)
        await db.commit()
        await db.refresh(leave)
        return leave
    
    @staticmethod
    async def approve(db: AsyncSession, leave_id: int, approved: bool, remark: str) -> Optional[Leave]:
        query = select(Leave).where(Leave.id == leave_id)
        result = await db.execute(query)
        leave = result.scalar_one_or_none()
        if leave:
            leave.status = LeaveStatus.APPROVED if approved else LeaveStatus.REJECTED
            leave.approval_remark = remark
            leave.approval_time = datetime.now()
            await db.commit()
            await db.refresh(leave)
        return leave


# ==================== 薪资服务 ====================

class SalaryService:
    """薪资管理服务"""
    
    @staticmethod
    async def calculate_salary(db: AsyncSession, employee_id: int, year: int, month: int) -> Salary:
        emp = await EmployeeService.get_by_id(db, employee_id)
        if not emp:
            raise ValueError("Employee not found")
        
        stats = await AttendanceService.get_monthly_stats(db, employee_id, year, month)
        overtime_pay = stats["total_overtime_hours"] * (emp.base_salary / 21.75 / 8) * 1.5 if emp.base_salary else 0
        absence_deduction = stats["absent_days"] * (emp.base_salary / 21.75) if emp.base_salary else 0
        
        gross_salary = (emp.base_salary or 0) + (emp.performance_salary or 0) + overtime_pay + (emp.subsidy or 0)
        social_security = (emp.base_salary or 0) * 0.105
        housing_fund = (emp.base_salary or 0) * 0.12
        tax = max(0, (gross_salary - 5000 - social_security - housing_fund) * 0.03)
        net_salary = gross_salary - social_security - housing_fund - tax - absence_deduction
        
        salary = Salary(
            employee_id=employee_id,
            year_month=f"{year}-{month:02d}",
            base_salary=emp.base_salary or 0,
            performance_salary=emp.performance_salary or 0,
            overtime_pay=overtime_pay,
            allowance=emp.subsidy or 0,
            social_security=social_security,
            housing_fund=housing_fund,
            tax=tax,
            absence_deduction=absence_deduction,
            gross_salary=gross_salary,
            net_salary=net_salary
        )
        db.add(salary)
        await db.commit()
        await db.refresh(salary)
        return salary


# ==================== 行政服务 ====================

class AdminService:
    """行政管理服务"""
    
    @staticmethod
    async def create_request(
        db: AsyncSession,
        employee_id: int,
        request_type: str,
        title: str,
        content: str,
        amount: Optional[float] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> AdminRequest:
        count = await db.scalar(select(func.count()).select_from(AdminRequest))
        request_no = f"REQ{datetime.now().strftime('%Y%m%d')}{count + 1:04d}"
        request = AdminRequest(
            request_no=request_no,
            employee_id=employee_id,
            type=request_type,
            title=title,
            content=content,
            amount=amount,
            start_date=start_date,
            end_date=end_date
        )
        db.add(request)
        await db.commit()
        await db.refresh(request)
        return request
    
    @staticmethod
    async def approve_request(db: AsyncSession, request_id: int, approved: bool, remark: str, approver_id: int) -> Optional[AdminRequest]:
        query = select(AdminRequest).where(AdminRequest.id == request_id)
        result = await db.execute(query)
        request = result.scalar_one_or_none()
        if request:
            request.status = RequestStatus.APPROVED if approved else RequestStatus.REJECTED
            request.approval_remark = remark
            request.current_approver_id = approver_id
            if approved:
                request.status = RequestStatus.COMPLETED
            await db.commit()
            await db.refresh(request)
        return request


# ==================== 资产服务 ====================

class AssetService:
    """资产管理服务"""
    
    @staticmethod
    async def assign_asset(db: AsyncSession, asset_id: int, user_id: int) -> Optional[Asset]:
        query = select(Asset).where(Asset.id == asset_id)
        result = await db.execute(query)
        asset = result.scalar_one_or_none()
        if asset:
            asset.user_id = user_id
            asset.status = AssetStatus.IN_USE
            await db.commit()
            await db.refresh(asset)
        return asset
    
    @staticmethod
    async def return_asset(db: AsyncSession, asset_id: int) -> Optional[Asset]:
        query = select(Asset).where(Asset.id == asset_id)
        result = await db.execute(query)
        asset = result.scalar_one_or_none()
        if asset:
            asset.user_id = None
            asset.status = AssetStatus.AVAILABLE
            await db.commit()
            await db.refresh(asset)
        return asset


# ==================== 会议室服务 ====================

class MeetingRoomService:
    """会议室管理服务"""
    
    @staticmethod
    async def book_room(
        db: AsyncSession,
        room_id: int,
        booker_id: int,
        title: str,
        start_time: datetime,
        end_time: datetime,
        participants: int,
        description: Optional[str] = None
    ) -> MeetingRoomBooking:
        booking = MeetingRoomBooking(
            room_id=room_id,
            booker_id=booker_id,
            title=title,
            start_time=start_time,
            end_time=end_time,
            participants=participants,
            description=description
        )
        db.add(booking)
        await db.commit()
        await db.refresh(booking)
        return booking
    
    @staticmethod
    async def check_availability(db: AsyncSession, room_id: int, start_time: datetime, end_time: datetime) -> bool:
        query = select(MeetingRoomBooking).where(
            and_(
                MeetingRoomBooking.room_id == room_id,
                MeetingRoomBooking.status != "cancelled",
                MeetingRoomBooking.start_time < end_time,
                MeetingRoomBooking.end_time > start_time
            )
        )
        result = await db.execute(query)
        return len(list(result.scalars().all())) == 0


# ==================== 公告服务 ====================

class NoticeService:
    """公告管理服务"""
    
    @staticmethod
    async def publish_notice(
        db: AsyncSession,
        publisher_id: int,
        title: str,
        content: str,
        notice_type: str = "general",
        priority: int = 0,
        is_top: bool = False
    ) -> Notice:
        notice = Notice(
            publisher_id=publisher_id,
            title=title,
            content=content,
            type=notice_type,
            priority=priority,
            is_top=is_top,
            is_published=True
        )
        db.add(notice)
        await db.commit()
        await db.refresh(notice)
        return notice
    
    @staticmethod
    async def get_all_notices(db: AsyncSession, is_published: bool = True) -> List[Notice]:
        query = select(Notice).where(Notice.is_published == is_published)
        query = query.order_by(Notice.is_top.desc(), Notice.priority.desc(), Notice.publish_time.desc())
        result = await db.execute(query)
        return list(result.scalars().all())
