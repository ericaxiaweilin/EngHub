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
               shift, hire_date, status, skill_level, phone
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
        INSERT INTO hr_employees (id, factory_id, employee_code, name, gender, department, station, position, shift, hire_date, status, skill_level, phone)
        VALUES (:id, :fid, :code, :name, :gender, :dept, :station, :pos, :shift, COALESCE(:hire, CURRENT_DATE), 'active', :skill, :phone)
    """), {
        "id": emp_id, "fid": fid, "code": code, "name": body.name, "gender": body.gender,
        "dept": body.department, "station": body.station, "pos": body.position,
        "shift": body.shift, "hire": body.hire_date, "skill": body.skill_level, "phone": body.phone,
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
    for field in ["name", "gender", "department", "station", "position", "shift", "status", "skill_level", "phone"]:
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
            await db.execute(text("""
                INSERT INTO hr_employees (id, factory_id, employee_code, name, gender, department, station, position, shift, hire_date, status, skill_level)
                VALUES (:id, :fid, :code, :name, :gender, :dept, :station, '操作员',
                        CASE WHEN random() < 0.6 THEN '白班' ELSE '夜班' END,
                        CURRENT_DATE - (random() * 2000)::INT, 'active',
                        CASE WHEN random() < 0.3 THEN 'L2' ELSE 'L1' END)
            """), {
                "id": str(uuid.uuid4()), "fid": fid, "code": f"{prefix}-{seq:04d}",
                "name": name, "gender": "男" if random.random() < 0.62 else "女",
                "dept": item.department, "station": item.station,
            })
    await db.commit()
    return {"message": f"已导入 {total_created} 人", "total_created": total_created}
