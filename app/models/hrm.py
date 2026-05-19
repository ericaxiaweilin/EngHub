"""
HRM - Human Resource Management Models
人力资源管理系统数据库模型
包含：组织架构、员工信息、考勤管理、薪资核算、行政管理
"""
from sqlalchemy import Column, Integer, String, Date, DateTime, Float, ForeignKey, Boolean, Enum, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.core.database import Base


# ==================== 组织架构 ====================

class Department(Base):
    """部门表"""
    __tablename__ = "departments"
    
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(20), unique=True, index=True, nullable=False)  # 部门编码
    name = Column(String(100), nullable=False)  # 部门名称
    parent_id = Column(Integer, ForeignKey("departments.id"), index=True)  # 上级部门
    level = Column(Integer, default=1)  # 层级
    manager_id = Column(Integer, ForeignKey("employees.id"))  # 部门负责人
    status = Column(Boolean, default=True)  # 状态
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # 关系
    parent = relationship("Department", remote_side=[id], backref="children")
    employees = relationship("Employee", back_populates="department")
    manager = relationship("Employee", foreign_keys=[manager_id])


# ==================== 员工信息 ====================

class EmploymentType(str, enum.Enum):
    """雇佣类型"""
    FULL_TIME = "full_time"  # 全职
    PART_TIME = "part_time"  # 兼职
    INTERN = "intern"  # 实习
    CONTRACT = "contract"  # 合同工
    DISPATCH = "dispatch"  # 劳务派遣


class EmployeeStatus(str, enum.Enum):
    """员工状态"""
    PROBATION = "probation"  # 试用期
    REGULAR = "regular"  # 正式
    RESIGNED = "resigned"  # 已离职
    RETIRED = "retired"  # 退休
    SUSPENDED = "suspended"  # 停职


class Employee(Base):
    """员工信息表"""
    __tablename__ = "employees"
    
    id = Column(Integer, primary_key=True, index=True)
    employee_no = Column(String(20), unique=True, index=True, nullable=False)  # 工号
    name = Column(String(50), nullable=False)  # 姓名
    gender = Column(String(10))  # 性别
    birth_date = Column(Date)  # 出生日期
    id_card = Column(String(18))  # 身份证号
    phone = Column(String(20))  # 手机号
    email = Column(String(100))  # 邮箱
    address = Column(String(200))  # 住址
    emergency_contact = Column(String(50))  # 紧急联系人
    emergency_phone = Column(String(20))  # 紧急联系电话
    
    # 入职信息
    entry_date = Column(Date, nullable=False)  # 入职日期
    probation_end_date = Column(Date)  # 转正日期
    employment_type = Column(Enum(EmploymentType), default=EmploymentType.FULL_TIME)
    status = Column(Enum(EmployeeStatus), default=EmployeeStatus.PROBATION)
    resignation_date = Column(Date)  # 离职日期
    resignation_reason = Column(String(200))  # 离职原因
    
    # 组织关系
    department_id = Column(Integer, ForeignKey("departments.id"), index=True)
    position = Column(String(100))  # 职位
    job_level = Column(String(20))  # 职级
    direct_manager_id = Column(Integer, ForeignKey("employees.id"))  # 直属上级
    
    # 薪资信息
    base_salary = Column(Float)  # 基本工资
    performance_salary = Column(Float)  # 绩效工资
    subsidy = Column(Float)  # 补贴
    bank_account = Column(String(50))  # 银行卡号
    bank_name = Column(String(100))  # 开户行
    
    # 合同信息
    contract_start = Column(Date)  # 合同开始日期
    contract_end = Column(Date)  # 合同结束日期
    contract_times = Column(Integer, default=1)  # 签约次数
    
    # 教育背景
    education = Column(String(20))  # 学历
    major = Column(String(100))  # 专业
    graduation_school = Column(String(100))  # 毕业院校
    graduation_year = Column(Integer)  # 毕业年份
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # 关系
    department = relationship("Department", back_populates="employees")
    direct_manager = relationship("Employee", remote_side=[id], backref="subordinates")
    attendances = relationship("Attendance", back_populates="employee")
    salaries = relationship("Salary", back_populates="employee")
    leaves = relationship("Leave", back_populates="employee")
    admin_requests = relationship("AdminRequest", back_populates="employee")


# ==================== 考勤管理 ====================

class AttendanceType(str, enum.Enum):
    """考勤类型"""
    WORK = "work"  # 正常上班
    OVERTIME = "overtime"  # 加班
    BUSINESS = "business"  # 出差
    TRAINING = "training"  # 培训


class AttendanceStatus(str, enum.Enum):
    """考勤状态"""
    NORMAL = "normal"  # 正常
    LATE = "late"  # 迟到
    EARLY_LEAVE = "early_leave"  # 早退
    ABSENT = "absent"  # 旷工
    HALF_ABSENT = "half_absent"  # 半天旷工


class Attendance(Base):
    """考勤记录表"""
    __tablename__ = "attendances"
    
    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), index=True, nullable=False)
    date = Column(Date, nullable=False, index=True)  # 考勤日期
    
    # 打卡时间
    clock_in = Column(DateTime(timezone=True))  # 上班打卡
    clock_out = Column(DateTime(timezone=True))  # 下班打卡
    
    # 排班时间
    scheduled_start = Column(DateTime(timezone=True))  # 应上班时间
    scheduled_end = Column(DateTime(timezone=True))  # 应下班时间
    
    # 考勤结果
    type = Column(Enum(AttendanceType), default=AttendanceType.WORK)
    status = Column(Enum(AttendanceStatus))
    work_hours = Column(Float)  # 工作时长
    overtime_hours = Column(Float)  # 加班时长
    late_minutes = Column(Integer, default=0)  # 迟到分钟数
    early_leave_minutes = Column(Integer, default=0)  # 早退分钟数
    
    remark = Column(String(200))  # 备注
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    employee = relationship("Employee", back_populates="attendances")


class LeaveType(str, enum.Enum):
    """请假类型"""
    ANNUAL = "annual"  # 年假
    SICK = "sick"  # 病假
    PERSONAL = "personal"  # 事假
    MARRIAGE = "marriage"  # 婚假
    MATERNITY = "maternity"  # 产假
    PATERNITY = "paternity"  # 陪产假
    BEREAVEMENT = "bereavement"  # 丧假
    OTHER = "other"  # 其他


class LeaveStatus(str, enum.Enum):
    """请假状态"""
    PENDING = "pending"  # 待审批
    APPROVED = "approved"  # 已批准
    REJECTED = "rejected"  # 已拒绝
    CANCELLED = "cancelled"  # 已取消


class Leave(Base):
    """请假申请表"""
    __tablename__ = "leaves"
    
    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), index=True, nullable=False)
    
    type = Column(Enum(LeaveType), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    days = Column(Float, nullable=False)  # 请假天数
    reason = Column(String(500))  # 请假事由
    
    status = Column(Enum(LeaveStatus), default=LeaveStatus.PENDING)
    approver_id = Column(Integer, ForeignKey("employees.id"))  # 审批人
    approval_time = Column(DateTime(timezone=True))  # 审批时间
    approval_remark = Column(String(200))  # 审批意见
    
    attachment = Column(String(200))  # 附件（如病假条）
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    employee = relationship("Employee", back_populates="leaves")
    approver = relationship("Employee", foreign_keys=[approver_id])


# ==================== 薪资管理 ====================

class Salary(Base):
    """薪资表"""
    __tablename__ = "salaries"
    
    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), index=True, nullable=False)
    
    year_month = Column(String(7), index=True, nullable=False)  # 薪资月份 (YYYY-MM)
    
    # 应发项目
    base_salary = Column(Float, default=0)  # 基本工资
    performance_salary = Column(Float, default=0)  # 绩效工资
    overtime_pay = Column(Float, default=0)  # 加班费
    allowance = Column(Float, default=0)  # 各类补贴
    bonus = Column(Float, default=0)  # 奖金
    other_income = Column(Float, default=0)  # 其他收入
    
    # 扣款项目
    social_security = Column(Float, default=0)  # 社保个人部分
    housing_fund = Column(Float, default=0)  # 公积金个人部分
    tax = Column(Float, default=0)  # 个人所得税
    absence_deduction = Column(Float, default=0)  # 缺勤扣款
    other_deduction = Column(Float, default=0)  # 其他扣款
    
    # 汇总
    gross_salary = Column(Float)  # 应发合计
    net_salary = Column(Float)  # 实发合计
    
    # 发放状态
    payment_status = Column(String(20), default="pending")  # pending/paid
    payment_date = Column(Date)  # 发放日期
    remark = Column(String(200))
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    employee = relationship("Employee", back_populates="salaries")


# ==================== 行政管理 ====================

class RequestType(str, enum.Enum):
    """行政申请类型"""
    LEAVE = "leave"  # 请假（关联请假模块）
    OVERTIME = "overtime"  # 加班申请
    BUSINESS_TRIP = "business_trip"  # 出差申请
    SEAL_USE = "seal_use"  # 用印申请
    ASSET_USE = "asset_use"  # 资产借用
    MEETING_ROOM = "meeting_room"  # 会议室预定
    VEHICLE_USE = "vehicle_use"  # 用车申请
    PROCUREMENT = "procurement"  # 采购申请
    EXPENSE = "expense"  # 费用报销
    OTHER = "other"  # 其他


class RequestStatus(str, enum.Enum):
    """申请状态"""
    DRAFT = "draft"  # 草稿
    PENDING = "pending"  # 待审批
    APPROVED = "approved"  # 已批准
    REJECTED = "rejected"  # 已拒绝
    COMPLETED = "completed"  # 已完成
    CANCELLED = "cancelled"  # 已取消


class AdminRequest(Base):
    """行政申请表"""
    __tablename__ = "admin_requests"
    
    id = Column(Integer, primary_key=True, index=True)
    request_no = Column(String(30), unique=True, index=True)  # 申请单号
    employee_id = Column(Integer, ForeignKey("employees.id"), index=True, nullable=False)
    
    type = Column(Enum(RequestType), nullable=False)
    title = Column(String(100), nullable=False)  # 申请标题
    content = Column(Text)  # 申请内容
    amount = Column(Float)  # 涉及金额（报销/采购用）
    
    start_date = Column(DateTime(timezone=True))  # 开始时间
    end_date = Column(DateTime(timezone=True))  # 结束时间
    
    status = Column(Enum(RequestStatus), default=RequestStatus.PENDING)
    current_approver_id = Column(Integer, ForeignKey("employees.id"))  # 当前审批人
    final_approver_id = Column(Integer, ForeignKey("employees.id"))  # 最终审批人
    
    approval_flow = Column(Text)  # 审批流程 JSON
    approval_remark = Column(String(500))  # 审批意见
    
    attachment = Column(String(500))  # 附件列表，逗号分隔
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    employee = relationship("Employee", back_populates="admin_requests")
    current_approver = relationship("Employee", foreign_keys=[current_approver_id])
    final_approver = relationship("Employee", foreign_keys=[final_approver_id])


class AssetType(str, enum.Enum):
    """资产类型"""
    COMPUTER = "computer"  # 电脑
    FURNITURE = "furniture"  # 办公家具
    EQUIPMENT = "equipment"  # 设备
    VEHICLE = "vehicle"  # 车辆
    OTHER = "other"  # 其他


class AssetStatus(str, enum.Enum):
    """资产状态"""
    AVAILABLE = "available"  # 闲置
    IN_USE = "in_use"  # 使用中
    MAINTENANCE = "maintenance"  # 维修中
    SCRAPPED = "scrapped"  # 已报废


class Asset(Base):
    """公司资产表"""
    __tablename__ = "assets"
    
    id = Column(Integer, primary_key=True, index=True)
    asset_no = Column(String(30), unique=True, index=True, nullable=False)  # 资产编号
    name = Column(String(100), nullable=False)  # 资产名称
    type = Column(Enum(AssetType), nullable=False)
    
    brand = Column(String(50))  # 品牌
    model = Column(String(50))  # 型号
    purchase_date = Column(Date)  # 购买日期
    purchase_price = Column(Float)  # 购买价格
    supplier = Column(String(100))  # 供应商
    
    status = Column(Enum(AssetStatus), default=AssetStatus.AVAILABLE)
    user_id = Column(Integer, ForeignKey("employees.id"), index=True)  # 使用人
    location = Column(String(100))  # 存放位置
    
    warranty_period = Column(Integer)  # 保修期（月）
    warranty_end = Column(Date)  # 保修截止日期
    
    remark = Column(String(200))
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    user = relationship("Employee")


class MeetingRoom(Base):
    """会议室表"""
    __tablename__ = "meeting_rooms"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False)  # 会议室名称
    location = Column(String(100))  # 位置
    capacity = Column(Integer)  # 容纳人数
    
    facilities = Column(String(200))  # 设施（投影仪、白板等）
    status = Column(Boolean, default=True)  # 是否可用
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class MeetingRoomBooking(Base):
    """会议室预定表"""
    __tablename__ = "meeting_room_bookings"
    
    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(Integer, ForeignKey("meeting_rooms.id"), nullable=False)
    booker_id = Column(Integer, ForeignKey("employees.id"), nullable=False)
    
    title = Column(String(100), nullable=False)  # 会议主题
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    
    participants = Column(Integer)  # 参会人数
    description = Column(String(500))  # 会议描述
    
    status = Column(String(20), default="confirmed")  # confirmed/cancelled/completed
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    room = relationship("MeetingRoom")
    booker = relationship("Employee")


class Notice(Base):
    """公司公告表"""
    __tablename__ = "notices"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    
    type = Column(String(20), default="general")  # general/urgent/policy
    priority = Column(Integer, default=0)  # 优先级
    
    publisher_id = Column(Integer, ForeignKey("employees.id"))
    publish_time = Column(DateTime(timezone=True), server_default=func.now())
    
    is_top = Column(Boolean, default=False)  # 是否置顶
    is_published = Column(Boolean, default=False)  # 是否发布
    
    view_count = Column(Integer, default=0)  # 浏览次数
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    publisher = relationship("Employee")
