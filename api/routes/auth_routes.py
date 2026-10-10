"""
认证授权 API 路由
用户登录、注册、Token 刷新、角色管理
"""
import os
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional, List

from database.db_config import get_db
from api.services.user_service import UserService
from core.auth.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    require_permission,
    get_user_menu_items,
    get_user_data_scope,
    SESSION_EXPIRE_HOURS,
)
from core.auth.roles import get_user_permissions, get_role_by_code
from database.models import User, Role

router = APIRouter(prefix="/auth", tags=["authentication"])


# --- Request/Response Models ---

class TokenResponse(BaseModel):
    """Token 响应"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshTokenRequest(BaseModel):
    """刷新 Token 请求"""
    refresh_token: str


class ResetPasswordRequest(BaseModel):
    """忘记密码自助重置请求(内网信任环境: 凭用户名直接重置)"""
    username: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _validate_new_password(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("新密码至少 6 位")
        if len(v) > 255:
            raise ValueError("新密码过长")
        return v


class UserCreate(BaseModel):
    """用户创建请求"""
    username: str
    email: EmailStr
    password: str
    full_name: Optional[str] = None
    factory_id: Optional[str] = None
    role: str = "operator"          # 角色编码: operator, line_leader, production_manager...
    is_superuser: bool = False      # 仅管理员可设置


class UserResponse(BaseModel):
    """用户响应"""
    id: str
    username: str
    email: str
    full_name: Optional[str]
    factory_id: Optional[str]
    role: str
    position: Optional[str] = None
    department: Optional[str] = None
    permissions: list = []
    data_scope: dict = {}
    menu_items: list = []
    is_active: bool
    
    class Config:
        from_attributes = True

    @field_validator("id", mode="before")
    @classmethod
    def _coerce_id(cls, v):
        return str(v)


class RoleResponse(BaseModel):
    """角色响应"""
    id: str
    role_code: str
    role_name: str
    position: str
    department: str
    description: Optional[str]
    is_system: bool
    level: int
    permissions: list
    data_scope: dict
    
    class Config:
        from_attributes = True

    @field_validator("id", mode="before")
    @classmethod
    def _coerce_id(cls, v):
        return str(v)


class AssignRoleRequest(BaseModel):
    """分配角色请求"""
    user_id: str
    role: str


# --- Helper Functions ---

async def get_current_active_superuser(current_user: User = Depends(get_current_user)) -> User:
    """获取超级管理员用户"""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要系统管理员权限"
        )
    return current_user


def _build_user_response(user: User) -> UserResponse:
    """构建用户响应（含权限和菜单）"""
    resp = UserResponse(
        id=str(user.id),
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        factory_id=user.factory_id,
        role=user.role,
        # position/department 从硬编码角色定义取（与菜单/权限同源），
        # 避免访问 user.role_obj 触发 async 懒加载 (MissingGreenlet)
        position=(get_role_by_code(user.role) or {}).get("position"),
        department=(get_role_by_code(user.role) or {}).get("department"),
        permissions=get_user_permissions(user),
        data_scope=get_user_data_scope(user),
        menu_items=get_user_menu_items(user),
        is_active=user.is_active,
    )
    return resp


# --- 口令爆破节流 ---
# 计数放在库里而不是进程内存：uvicorn 以 --workers 2 起跑，进程内计数会让攻击者
# 按 worker 数把预算翻倍，而且重启即清零。窗口与阈值都用窗口内失败行数判，
# 锁定到期不需要定时任务 —— 超窗的行自然不再计入。
LOGIN_FAIL_WINDOW_MINUTES = int(os.getenv("LOGIN_FAIL_WINDOW_MINUTES", "15"))
LOGIN_FAIL_LIMIT = int(os.getenv("LOGIN_FAIL_LIMIT", "10"))


async def _recent_login_failures(db: AsyncSession, username: str) -> int:
    from sqlalchemy import text
    return int((await db.execute(
        text("SELECT count(*) FROM login_attempts WHERE username = :u "
             "AND attempted_at > now() - make_interval(mins => :w)"),
        {"u": username, "w": LOGIN_FAIL_WINDOW_MINUTES})).scalar() or 0)


async def _note_login_failure(db: AsyncSession, username: str, client_ip: str) -> None:
    from sqlalchemy import text
    await db.execute(
        text("INSERT INTO login_attempts (username, client_ip, reason) VALUES (:u, :i, :r)"),
        {"u": username, "i": client_ip, "r": "bad_password"})
    await db.commit()


async def _clear_login_failures(db: AsyncSession, username: str) -> None:
    from sqlalchemy import text
    await db.execute(text("DELETE FROM login_attempts WHERE username = :u"), {"u": username})
    await db.commit()


# --- Endpoints ---

@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """
    用户登录
    返回 access_token 和 refresh_token
    """
    user_service = UserService(db)

    client_ip = ((request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
                 or (request.client.host if request.client else ""))
    failed = await _recent_login_failures(db, form_data.username)
    if failed >= LOGIN_FAIL_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(f"账号 {form_data.username} 在 {LOGIN_FAIL_WINDOW_MINUTES} 分钟内"
                    f"密码错误 {failed} 次，已临时锁定"),
            headers={"Retry-After": str(LOGIN_FAIL_WINDOW_MINUTES * 60)},
        )

    # 验证用户
    user = await user_service.authenticate_user(form_data.username, form_data.password)
    if not user:
        await _note_login_failure(db, form_data.username, client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    await _clear_login_failures(db, form_data.username)

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号已被禁用，请联系管理员"
        )
    
    # 更新最后登录时间
    await user_service.update_last_login(user.id)
    
    # 生成 Token（包含角色信息）
    access_token = create_access_token(
        data={
            "sub": user.username,
            "user_id": str(user.id),
            "role": user.role,
            "is_superuser": user.is_superuser,
            "factory_id": user.factory_id,
        }
    )
    refresh_token = create_refresh_token(
        data={"sub": user.username, "user_id": str(user.id)}
    )
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=SESSION_EXPIRE_HOURS * 3600
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(request: RefreshTokenRequest, db: AsyncSession = Depends(get_db)):
    """
    刷新 Token
    使用 refresh_token 获取新的 access_token
    """
    payload = decode_token(request.refresh_token)
    
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的刷新令牌"
        )
    
    username = payload.get("sub")
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的刷新令牌"
        )
    
    user_service = UserService(db)
    user = await user_service.get_user_by_username(username)
    
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在或已停用"
        )
    
    # 生成新的 Token
    access_token = create_access_token(
        data={
            "sub": user.username,
            "user_id": str(user.id),
            "role": user.role,
            "is_superuser": user.is_superuser,
            "factory_id": user.factory_id,
        }
    )
    new_refresh_token = create_refresh_token(
        data={"sub": user.username, "user_id": str(user.id)}
    )
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        expires_in=SESSION_EXPIRE_HOURS * 3600
    )


@router.post("/register", response_model=UserResponse)
async def register(
    user_data: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_superuser)
):
    """
    注册新用户
    需要管理员权限
    """
    user_service = UserService(db)
    
    # 检查用户名是否已存在
    existing_user = await user_service.get_user_by_username(user_data.username)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名已存在"
        )
    
    # 检查邮箱是否已存在
    existing_email = await user_service.get_user_by_email(user_data.email)
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="邮箱已被注册"
        )
    
    # 创建用户（自动关联角色定义）
    user = await user_service.create_user(
        username=user_data.username,
        email=user_data.email,
        password=user_data.password,
        full_name=user_data.full_name,
        factory_id=user_data.factory_id,
        role=user_data.role,
        is_superuser=user_data.is_superuser,
    )
    
    return _build_user_response(user)


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """获取当前登录用户信息（含权限和菜单）"""
    return _build_user_response(current_user)


@router.put("/password")
async def change_password(
    old_password: str,
    new_password: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """修改密码"""
    user_service = UserService(db)
    
    # 验证旧密码
    if not user_service.authenticate_user(current_user.username, old_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="旧密码错误"
        )
    
    # 更新密码
    await user_service.update_user(current_user.id, password=new_password)
    
    return {"message": "密码修改成功"}


@router.post("/reset-password")
async def reset_password(request: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    """忘记密码自助重置(内网信任环境, 凭用户名直接设新密码, 无需登录态)。"""
    user_service = UserService(db)
    user = await user_service.get_user_by_username(request.username.strip())
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )
    await user_service.update_user(str(user.id), password=request.new_password)
    return {"message": "密码已重置, 请用新密码登录"}


@router.get("/roles", response_model=List[RoleResponse])
async def list_roles(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取角色列表（需查看角色权限）"""
    user_service = UserService(db)
    roles = await user_service.list_roles()
    # roles.permissions 在库里存的是 {"purchase": {"view": true, ...}} 权限映射，
    # 而 RoleResponse 声明 permissions: list —— 声明与真实形状不一致时 FastAPI 在
    # 序列化阶段抛 ResponseValidationError，这个端点每次 500。
    # 这里按接口已承诺的形状把映射展开：不改公开契约，也不动库里数据。
    items = []
    for role in roles:
        raw = role.permissions or {}
        if isinstance(raw, dict):
            permissions = [
                {"module": module, "actions": [a for a, allowed in (actions or {}).items() if allowed]}
                for module, actions in raw.items()
            ]
        else:
            permissions = list(raw)
        items.append({
            "id": role.id,
            "role_code": role.role_code,
            "role_name": role.role_name,
            "position": role.position,
            "department": role.department,
            "description": role.description,
            "is_system": bool(role.is_system),
            "level": role.level,
            "data_scope": role.data_scope,
            "permissions": permissions,
        })
    return items


@router.post("/users/{user_id}/assign-role", response_model=UserResponse)
async def assign_role_to_user(
    request: AssignRoleRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_superuser)
):
    """管理员为用户分配角色"""
    user_service = UserService(db)
    user = await user_service.assign_role(request.user_id, request.role)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return _build_user_response(user)


@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user_profile(
    user_id: str,
    data: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_superuser)
):
    """管理员更新用户信息"""
    user_service = UserService(db)
    user = await user_service.update_user(
        user_id,
        email=data.email,
        full_name=data.full_name,
        factory_id=data.factory_id,
        role=data.role,
    )
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return _build_user_response(user)


__all__ = ["router"]
