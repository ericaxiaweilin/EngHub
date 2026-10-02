"""
HR 人力档案 + 工厂切换 API

- 人力花名册 CRUD / 统计（按部门/工序/班次/技能分布）
- 工厂列表 + 开发账户全局工厂切换
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import text, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.db_config import get_db
from database.models import User
from core.auth.security import get_current_user

router = APIRouter(prefix="/api/v1/hr", tags=["hr-roster"])


# ==================== Schemas ====================

class EmployeeCreate(BaseModel):
    name: str
    gender: str = "男"
    department: str
    station: str
    position: str = "操作员"
    shift: str = "白班"
    hire_date: Optional[str] = None
    skill_level: str = "L1"
    phone: Optional[str] = None
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None


class EmployeeUpdate(BaseModel):
    name: Optional[str] = None
    gender: Optional[str] = None
    department: Optional[str] = None
    station: Optional[str] = None
    position: Optional[str] = None
    shift: Optional[str] = None
    status: Optional[str] = None
    skill_level: Optional[str] = None
    phone: Optional[str] = None
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None


class EmployeeSkillAssign(BaseModel):
    """给花名册员工分配/更新内部工序技能"""
    skill_id: int
    level: str = "L1"  # L1-L5
    certified_date: Optional[str] = None
    expiry_date: Optional[str] = None


class FactorySwitch(BaseModel):
    factory_id: str


# ==================== 工具函数 ====================

def _get_active_factory(user: User, request: Request) -> str:
    """获取当前生效的 factory_id：优先 X-Factory-Id header > user.active_factory_id > user.factory_id"""
    header_fid = request.headers.get("x-factory-id")
    if header_fid:
        return header_fid
    if hasattr(user, "active_factory_id") and user.active_factory_id:
        return user.active_factory_id
    return user.factory_id or "FAC_MECH_001"


def _is_dev_account(user: User) -> bool:
    """开发账户判定：超管 或 username=eric"""
    return user.is_superuser or user.username == "eric"


# ==================== 工厂管理 ====================

@router.get("/factories")
async def list_factories(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取所有工厂列表"""
    rows = (await db.execute(text(
        "SELECT id, name, short_name, factory_type, address, status FROM factories ORDER BY created_at"
    ))).fetchall()
    return {
        "items": [
            {"id": r[0], "name": r[1], "short_name": r[2], "factory_type": r[3], "address": r[4], "status": r[5]}
            for r in rows
        ]
    }


@router.post("/factory/switch")
async def switch_factory(
    body: FactorySwitch,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """切换当前激活工厂（仅开发账户）"""
    if not _is_dev_account(current_user):
        raise HTTPException(403, "仅开发账户可切换工厂")
    # 验证工厂存在
    row = (await db.execute(text("SELECT id, name FROM factories WHERE id = :fid"), {"fid": body.factory_id})).fetchone()
    if not row:
        raise HTTPException(404, f"工厂 {body.factory_id} 不存在")
    # 更新用户 active_factory_id
    await db.execute(
        text("UPDATE users SET active_factory_id = :fid WHERE id = :uid"),
        {"fid": body.factory_id, "uid": str(current_user.id)},
    )
    await db.commit()
    return {"factory_id": row[0], "factory_name": row[1], "message": f"已切换到 {row[1]}"}


# ==================== 人力花名册 ====================

@router.get("/employees")
async def list_employees(
    department: Optional[str] = Query(None),
    station: Optional[str] = Query(None),
    status: Optional[str] = Query(None, alias="status"),
    shift: Optional[str] = Query(None),
    skill_level: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None, description="姓名/工号模糊搜索"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """花名册列表（分页 + 筛选）"""
    fid = _get_active_factory(current_user, request)
    conditions = ["factory_id = :fid"]
    params: Dict[str, Any] = {"fid": fid}
    if department:
        conditions.append("department = :dept")
        params["dept"] = department
    if station:
        conditions.append("station = :station")
        params["station"] = station
    if status:
        conditions.append("status = :status")
        params["status"] = status
    if shift:
        conditions.append("shift = :shift")
        params["shift"] = shift
    if skill_level:
        conditions.append("skill_level = :skill")
        params["skill"] = skill_level
    if keyword:
        conditions.append("(name ILIKE :kw OR employee_code ILIKE :kw)")
        params["kw"] = f"%{keyword}%"

    where = " AND ".join(conditions)
    total = (await db.execute(text(f"SELECT count(*) FROM hr_employees WHERE {where}"), params)).scalar()
    offset = (page - 1) * page_size
    params["limit"] = page_size
    params["offset"] = offset
    rows = (await db.execute(text(f"""
        SELECT id, employee_code, name, gender, department, station, position,
               shift, hire_date, status, skill_level, phone, height_cm, weight_kg
        FROM hr_employees WHERE {where}
        ORDER BY department, station, employee_code
        LIMIT :limit OFFSET :offset
    """), params)).fetchall()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "factory_id": fid,
        "items": [
            {
                "id": r[0], "employee_code": r[1], "name": r[2], "gender": r[3],
                "department": r[4], "station": r[5], "position": r[6],
                "shift": r[7], "hire_date": str(r[8]) if r[8] else None,
                "status": r[9], "skill_level": r[10], "phone": r[11],
                "height_cm": float(r[12]) if r[12] is not None else None,
                "weight_kg": float(r[13]) if r[13] is not None else None,
            }
            for r in rows
        ],
    }


@router.get("/stats")
async def hr_stats(
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """人力统计：按部门/工序/班次/技能/状态分布"""
    fid = _get_active_factory(current_user, request)
    params = {"fid": fid}

    # 总人数
    total = (await db.execute(text("SELECT count(*) FROM hr_employees WHERE factory_id = :fid"), params)).scalar()
    active = (await db.execute(text("SELECT count(*) FROM hr_employees WHERE factory_id = :fid AND status = 'active'"), params)).scalar()

    # 按部门+工序
    dept_rows = (await db.execute(text("""
        SELECT department, station, count(*) as cnt,
               count(*) FILTER (WHERE status = 'active') as active_cnt
        FROM hr_employees WHERE factory_id = :fid
        GROUP BY department, station
        ORDER BY department, station
    """), params)).fetchall()

    # 按班次
    shift_rows = (await db.execute(text("""
        SELECT shift, count(*) FROM hr_employees WHERE factory_id = :fid GROUP BY shift ORDER BY count(*) DESC
    """), params)).fetchall()

    # 按技能等级
    skill_rows = (await db.execute(text("""
        SELECT skill_level, count(*) FROM hr_employees WHERE factory_id = :fid GROUP BY skill_level ORDER BY skill_level
    """), params)).fetchall()

    # 按性别
    gender_rows = (await db.execute(text("""
        SELECT gender, count(*) FROM hr_employees WHERE factory_id = :fid GROUP BY gender
    """), params)).fetchall()

    # 组装部门→工序树
    dept_map: Dict[str, List[Dict]] = {}
    for r in dept_rows:
        dept_map.setdefault(r[0], []).append({"station": r[1], "total": r[2], "active": r[3]})

    return {
        "factory_id": fid,
        "total": total,
        "active": active,
        "departments": [
            {"department": d, "stations": stations, "total": sum(s["total"] for s in stations)}
            for d, stations in dept_map.items()
        ],
        "shifts": [{"shift": r[0], "count": r[1]} for r in shift_rows],
        "skill_levels": [{"level": r[0], "count": r[1]} for r in skill_rows],
        "genders": [{"gender": r[0], "count": r[1]} for r in gender_rows],
    }


@router.get("/attendance/summary")
async def attendance_summary(
    date_value: Optional[str] = Query(None, alias="date"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Today's operational attendance pulse for HR and RCC."""
    fid = _get_active_factory(current_user, request)
    target_date = date_value or "CURRENT_DATE"
    date_expr = "CURRENT_DATE::text" if target_date == "CURRENT_DATE" else ":attendance_date"
    params: Dict[str, Any] = {"fid": fid}
    if target_date != "CURRENT_DATE":
        params["attendance_date"] = target_date
    row = (await db.execute(text(f"""
        SELECT COUNT(*)::int AS total,
               COUNT(*) FILTER (WHERE status = 'present')::int AS present,
               COUNT(*) FILTER (WHERE status = 'late')::int AS late,
               COUNT(*) FILTER (WHERE status = 'leave')::int AS on_leave,
               COUNT(*) FILTER (WHERE status = 'rest')::int AS rest
        FROM attendance
        WHERE factory_id = :fid AND date = {date_expr}
    """), params)).mappings().first()
    summary = dict(row or {"total": 0, "present": 0, "late": 0, "on_leave": 0, "rest": 0})
    total = summary.get("total", 0) or 0
    summary["attended"] = summary.get("present", 0) + summary.get("late", 0)
    summary["attendance_rate_pct"] = round(summary["attended"] / total * 100, 1) if total else 0
    summary["factory_id"] = fid
    summary["date"] = date_value or "today"
    return summary


@router.get("/attendance")
async def list_attendance(
    date_value: Optional[str] = Query(None, alias="date"),
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Attendance records joined back to HR employee profiles."""
    fid = _get_active_factory(current_user, request)
    conditions = ["a.factory_id = :fid"]
    params: Dict[str, Any] = {"fid": fid, "limit": limit}
    if date_value:
        conditions.append("a.date = :attendance_date")
        params["attendance_date"] = date_value
    else:
        conditions.append("a.date = CURRENT_DATE::text")
    if status:
        conditions.append("a.status = :attendance_status")
        params["attendance_status"] = status
    rows = (await db.execute(text(f"""
        SELECT a.id, a.operator_id, COALESCE(e.employee_code, o.employee_id) AS employee_code,
               COALESCE(e.name, o.name) AS name, a.date, a.shift, a.status,
               a.check_in, a.check_out
        FROM attendance a
        LEFT JOIN operators o ON o.id = a.operator_id
        LEFT JOIN hr_employees e ON e.factory_id = a.factory_id AND e.employee_code = o.employee_id
        WHERE {' AND '.join(conditions)}
        ORDER BY CASE a.status WHEN 'late' THEN 0 WHEN 'leave' THEN 1 WHEN 'rest' THEN 2 ELSE 3 END,
                 a.operator_id
        LIMIT :limit
    """), params)).fetchall()
    return {
        "factory_id": fid,
        "items": [
            {
                "id": r[0], "operator_id": r[1], "employee_code": r[2], "name": r[3],
                "date": r[4], "shift": r[5], "status": r[6],
                "check_in": r[7].isoformat() if r[7] else None,
                "check_out": r[8].isoformat() if r[8] else None,
            }
            for r in rows
        ],
    }


@router.post("/employees")
async def create_employee(
    body: EmployeeCreate,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """新增员工"""
    fid = _get_active_factory(current_user, request)
    # 生成工号
    last = (await db.execute(text(
        "SELECT employee_code FROM hr_employees WHERE factory_id = :fid ORDER BY employee_code DESC LIMIT 1"
    ), {"fid": fid})).fetchone()
    if last:
        seq = int(last[0].split("-")[-1]) + 1
    else:
        seq = 1
    prefix = "MEC" if "MECH" in fid else "EMP"
    code = f"{prefix}-{seq:04d}"
    emp_id = str(uuid.uuid4())
    await db.execute(text("""
        INSERT INTO hr_employees (id, factory_id, employee_code, name, gender, department, station, position, shift, hire_date, status, skill_level, phone, height_cm, weight_kg)
        VALUES (:id, :fid, :code, :name, :gender, :dept, :station, :pos, :shift, COALESCE(:hire, CURRENT_DATE), 'active', :skill, :phone, :height, :weight)
    """), {
        "id": emp_id, "fid": fid, "code": code, "name": body.name, "gender": body.gender,
        "dept": body.department, "station": body.station, "pos": body.position,
        "shift": body.shift, "hire": body.hire_date, "skill": body.skill_level, "phone": body.phone,
        "height": body.height_cm, "weight": body.weight_kg,
    })
    await db.commit()
    return {"id": emp_id, "employee_code": code, "message": f"已添加 {body.name}"}


@router.put("/employees/{emp_id}")
async def update_employee(
    emp_id: str,
    body: EmployeeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新员工信息"""
    updates = []
    params: Dict[str, Any] = {"id": emp_id}
    for field in ["name", "gender", "department", "station", "position", "shift", "status", "skill_level", "phone", "height_cm", "weight_kg"]:
        val = getattr(body, field, None)
        if val is not None:
            updates.append(f"{field} = :{field}")
            params[field] = val
    if not updates:
        raise HTTPException(400, "无更新字段")
    updates.append("updated_at = NOW()")
    await db.execute(text(f"UPDATE hr_employees SET {', '.join(updates)} WHERE id = :id"), params)
    await db.commit()
    return {"message": "更新成功"}


@router.delete("/employees/{emp_id}")
async def delete_employee(
    emp_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除员工（软删除→resigned）"""
    await db.execute(text("UPDATE hr_employees SET status = 'resigned', updated_at = NOW() WHERE id = :id"), {"id": emp_id})
    await db.commit()
    return {"message": "已标记离职"}


# ==================== 批量导入（按部门/工序/人数） ====================

class BatchImportItem(BaseModel):
    department: str
    station: str
    count: int


class BatchImportRequest(BaseModel):
    items: List[BatchImportItem]


@router.post("/batch-import")
async def batch_import(
    body: BatchImportRequest,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """批量导入人力（按部门/工序/人数自动生成花名册）"""
    fid = _get_active_factory(current_user, request)
    # 当前最大序号
    last = (await db.execute(text(
        "SELECT employee_code FROM hr_employees WHERE factory_id = :fid ORDER BY employee_code DESC LIMIT 1"
    ), {"fid": fid})).fetchone()
    seq = int(last[0].split("-")[-1]) if last else 0
    prefix = "MEC" if "MECH" in fid else "EMP"

    import random
    surnames = list("王李张刘陈杨黄赵周吴徐孙马朱胡郭何林罗高郑梁谢宋唐韩曹许邓冯萧程蔡彭潘袁董叶蒋余苏吕魏田杜丁沈姜范江傅钟卢汪戴崔任陆廖姚方金邱夏谭石贾邹熊孟秦阎薛侯雷白龙段郝孔邵史毛常万顾赖武康贺严尹钱施牛洪龚")
    given = list("伟芳娜敏静强磊洋勇军杰涛超明霞平刚桂英华建文辉力斌飞鑫鹏波宇浩然博宁毅俊峰志义兴良海山仁奇固之轮翰朗伯宏言若鸣朋裕河哲江晨辰士以致煜进林有坚和彪诚先敬震振壮会思群豪心邦承乐绍功松善厚庆民友永健世广")

    total_created = 0
    for item in body.items:
        for _ in range(item.count):
            seq += 1
            total_created += 1
            name = random.choice(surnames) + random.choice(given) + (random.choice(given) if random.random() < 0.55 else "")
            gender = "男" if random.random() < 0.62 else "女"
            if gender == "男":
                height = round(random.uniform(165, 180), 1)
                weight = round(random.uniform(55, 75), 1)
            else:
                height = round(random.uniform(155, 168), 1)
                weight = round(random.uniform(45, 60), 1)
            await db.execute(text("""
                INSERT INTO hr_employees (id, factory_id, employee_code, name, gender, department, station, position, shift, hire_date, status, skill_level, height_cm, weight_kg)
                VALUES (:id, :fid, :code, :name, :gender, :dept, :station, '操作员',
                        CASE WHEN random() < 0.6 THEN '白班' ELSE '夜班' END,
                        CURRENT_DATE - (random() * 2000)::INT, 'active',
                        CASE WHEN random() < 0.3 THEN 'L2' ELSE 'L1' END, :height, :weight)
            """), {
                "id": str(uuid.uuid4()), "fid": fid, "code": f"{prefix}-{seq:04d}",
                "name": name, "gender": gender,
                "dept": item.department, "station": item.station,
                "height": height, "weight": weight,
            })
    await db.commit()
    return {"message": f"已导入 {total_created} 人", "total_created": total_created}


# ==================== 内部工序技能库 + 员工技能 + 人力调配 ====================

# 技能等级映射（用于调配候选人等级过滤）
SKILL_LEVELS = {"L1": 1, "L2": 2, "L3": 3, "L4": 4, "L5": 5}


@router.get("/skill-library")
async def get_skill_library(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """内部工序技能库（按工序大类分组）"""
    rows = (await db.execute(text(
        "SELECT id, code, name, category FROM skills WHERE is_active = TRUE ORDER BY category, code"
    ))).fetchall()
    groups: Dict[str, List[Dict]] = {}
    for r in rows:
        groups.setdefault(r[3] or "未分类", []).append({"id": r[0], "code": r[1], "name": r[2]})
    return [{"category": cat, "skills": skills} for cat, skills in groups.items()]


@router.get("/employees/{emp_id}/skills")
async def get_employee_skills(
    emp_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取某花名册员工的内部工序技能列表"""
    rows = (await db.execute(text("""
        SELECT s.id, s.code, s.name, s.category, hes.level, hes.certified_date, hes.expiry_date,
               (hes.expiry_date IS NULL OR hes.expiry_date >= CURRENT_DATE) AS is_valid
        FROM hr_employee_skills hes
        JOIN skills s ON s.id = hes.skill_id
        WHERE hes.hr_employee_id = :eid
        ORDER BY s.category, s.code
    """), {"eid": emp_id})).fetchall()
    return [
        {
            "skill_id": r[0], "code": r[1], "name": r[2], "category": r[3],
            "level": r[4],
            "certified_date": str(r[5]) if r[5] else None,
            "expiry_date": str(r[6]) if r[6] else None,
            "is_valid": bool(r[7]),
        }
        for r in rows
    ]


@router.post("/employees/{emp_id}/skills")
async def assign_employee_skill(
    emp_id: str,
    body: EmployeeSkillAssign,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """给花名册员工分配/更新内部工序技能（upsert）"""
    if body.level not in SKILL_LEVELS:
        raise HTTPException(400, "技能等级无效，应为 L1-L5")
    skill = (await db.execute(text("SELECT id, name FROM skills WHERE id = :sid"), {"sid": body.skill_id})).fetchone()
    if not skill:
        raise HTTPException(404, f"技能 {body.skill_id} 不存在")
    emp = (await db.execute(text("SELECT id FROM hr_employees WHERE id = :eid"), {"eid": emp_id})).fetchone()
    if not emp:
        raise HTTPException(404, "员工不存在")
    await db.execute(text("""
        INSERT INTO hr_employee_skills (hr_employee_id, skill_id, level, certified_date, expiry_date)
        VALUES (:eid, :sid, :level, :cdate, :edate)
        ON CONFLICT (hr_employee_id, skill_id) DO UPDATE SET
            level = EXCLUDED.level,
            certified_date = EXCLUDED.certified_date,
            expiry_date = EXCLUDED.expiry_date,
            updated_at = NOW()
    """), {
        "eid": emp_id, "sid": body.skill_id, "level": body.level,
        "cdate": body.certified_date, "edate": body.expiry_date,
    })
    await db.commit()
    return {"message": f"已分配技能 {skill[1]}", "skill_id": body.skill_id, "level": body.level}


@router.delete("/employees/{emp_id}/skills/{skill_id}")
async def remove_employee_skill(
    emp_id: str,
    skill_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """移除花名册员工的某项技能"""
    result = await db.execute(text(
        "DELETE FROM hr_employee_skills WHERE hr_employee_id = :eid AND skill_id = :sid"
    ), {"eid": emp_id, "sid": skill_id})
    await db.commit()
    if result.rowcount == 0:
        raise HTTPException(404, "未找到该技能记录")
    return {"message": "已移除技能"}


@router.get("/dispatch-candidates")
async def dispatch_candidates(
    category: Optional[str] = Query(None, description="工序大类，如 组立/焊接/检测"),
    skill_id: Optional[int] = Query(None, description="具体技能 ID"),
    min_level: str = Query("L2", description="最低技能等级 L1-L5"),
    limit: int = Query(50, ge=1, le=500),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """人力调配候选人：按工序技能（大类或具体技能）+ 最低等级，查找能顶岗的在职员工"""
    if not category and not skill_id:
        raise HTTPException(400, "请提供 category（工序大类）或 skill_id（具体技能）")
    min_num = SKILL_LEVELS.get(min_level, 2)
    valid_levels = [lv for lv, n in SKILL_LEVELS.items() if n >= min_num]
    fid = _get_active_factory(current_user, request)

    conditions = [
        "e.factory_id = :fid",
        "e.status = 'active'",
        "(hes.expiry_date IS NULL OR hes.expiry_date >= CURRENT_DATE)",
    ]
    params: Dict[str, Any] = {"fid": fid}
    # 等级过滤（参数化 IN，避免驱动数组绑定差异）
    level_placeholders = ", ".join(f":lv{i}" for i in range(len(valid_levels)))
    for i, lv in enumerate(valid_levels):
        params[f"lv{i}"] = lv
    conditions.append(f"hes.level IN ({level_placeholders})")
    if skill_id:
        conditions.append("hes.skill_id = :sid")
        params["sid"] = skill_id
    if category:
        conditions.append("s.category = :cat")
        params["cat"] = category
    where = " AND ".join(conditions)
    params["limit"] = limit

    rows = (await db.execute(text(f"""
        SELECT e.id, e.employee_code, e.name, e.gender, e.height_cm, e.weight_kg,
               e.department, e.station, e.shift, e.skill_level,
               s.id, s.code, s.name, s.category, hes.level
        FROM hr_employee_skills hes
        JOIN hr_employees e ON e.id = hes.hr_employee_id
        JOIN skills s ON s.id = hes.skill_id
        WHERE {where}
        ORDER BY hes.level DESC, e.department, e.station
        LIMIT :limit
    """), params)).fetchall()

    return {
        "total": len(rows),
        "min_level": min_level,
        "factory_id": fid,
        "items": [
            {
                "id": r[0], "employee_code": r[1], "name": r[2], "gender": r[3],
                "height_cm": float(r[4]) if r[4] is not None else None,
                "weight_kg": float(r[5]) if r[5] is not None else None,
                "department": r[6], "station": r[7], "shift": r[8], "skill_level": r[9],
                "matched_skill": {
                    "id": r[10], "code": r[11], "name": r[12], "category": r[13], "level": r[14],
                },
            }
            for r in rows
        ],
    }
