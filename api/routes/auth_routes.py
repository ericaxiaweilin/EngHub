"""
认证授权 API 路由
用户登录、注册、Token 刷新等
"""
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional

from database.db_config import get_db
from core.auth.user_service import UserService
from core.auth.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
)
from database.models import User

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


class UserCreate(BaseModel):
    """用户创建请求"""
    username: str
    email: EmailStr
    password: str
    full_name: Optional[str] = None
    factory_id: Optional[str] = None
    role: str = "operator"


class UserResponse(BaseModel):
    """用户响应"""
    id: str
    username: str
    email: str
    full_name: Optional[str]
    factory_id: Optional[str]
    role: str
    is_active: bool
    
    class Config:
        from_attributes = True

    @field_validator("id", mode="before")
    @classmethod
    def _coerce_id(cls, v):
        # user.id 为 UUID 类型，pydantic v2 不会自动转 str
        return str(v)


class RegisterRequest(BaseModel):
    """自助注册请求 (邀请制多租户)"""
    username: str
    email: EmailStr
    password: str
    full_name: Optional[str] = None
    factory_id: Optional[str] = None
    invitation_token: Optional[str] = None


class InvitationCreate(BaseModel):
    """创建邀请请求"""
    email: EmailStr
    role: str = "operator"
    factory_id: Optional[str] = None  # 默认当前管理员自身厂区；仅超管可指定其他


class InvitationResponse(BaseModel):
    """邀请响应"""
    id: str
    email: str
    factory_id: str
    role: str
    token: str
    accepted: bool
    expires_at: str

    @field_validator("id", mode="before")
    @classmethod
    def _coerce_id(cls, v):
        return str(v)

    @field_validator("expires_at", mode="before")
    @classmethod
    def _coerce_dt(cls, v):
        return v.isoformat() if hasattr(v, "isoformat") else str(v)


# --- Helper Functions ---

async def get_current_active_superuser(current_user: User = Depends(get_current_user)) -> User:
    """获取超级管理员用户"""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough privileges"
        )
    return current_user


# --- Endpoints ---

@router.post("/login", response_model=TokenResponse)
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    """
    用户登录
    返回 access_token 和 refresh_token
    """
    user_service = UserService(db)
    
    # 验证用户
    user = await user_service.authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled"
        )
    
    # 更新最后登录时间
    await user_service.update_last_login(user.id)
    
    # 生成 Token (租户 factory_id 写入 JWT，服务端从 token 取租户)
    access_token = create_access_token(
        data={"sub": user.username, "user_id": str(user.id), "role": user.role, "factory_id": user.factory_id}
    )
    refresh_token = create_refresh_token(
        data={"sub": user.username, "user_id": str(user.id), "factory_id": user.factory_id}
    )
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=1800  # 30 minutes
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
            detail="Invalid refresh token"
        )
    
    username = payload.get("sub")
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )
    
    user_service = UserService(db)
    user = await user_service.get_user_by_username(username)
    
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive"
        )
    
    # 生成新的 Token
    access_token = create_access_token(
        data={"sub": user.username, "user_id": str(user.id), "role": user.role, "factory_id": user.factory_id}
    )
    new_refresh_token = create_refresh_token(
        data={"sub": user.username, "user_id": str(user.id), "factory_id": user.factory_id}
    )
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        expires_in=1800
    )


@router.post("/register", response_model=UserResponse)
async def register(user_data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """
    自助注册 (邀请制多租户，公开端点)
    - 携邀请码：加入已有厂区，角色由邀请决定
    - 无邀请码且厂区不存在：创建新租户，首用户为该厂区 admin
    - 无邀请码但厂区已存在：拒绝
    """
    user_service = UserService(db)
    try:
        user = await user_service.register_user(
            username=user_data.username,
            email=user_data.email,
            password=user_data.password,
            full_name=user_data.full_name,
            factory_id=user_data.factory_id,
            invitation_token=user_data.invitation_token,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return user


@router.post("/invitations", response_model=InvitationResponse)
async def create_invitation(
    data: InvitationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建邀请 (需 admin/manager 或超管)；普通管理员仅能邀请到自身厂区"""
    if not (current_user.is_superuser or current_user.role in ("admin", "manager")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权邀请用户")

    target_factory = data.factory_id or current_user.factory_id
    if not target_factory:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未指定厂区(租户)")
    # 非超管不能跨厂区邀请
    if not current_user.is_superuser and target_factory != current_user.factory_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权邀请至其他厂区")

    user_service = UserService(db)
    invitation = await user_service.create_invitation(
        email=data.email,
        factory_id=target_factory,
        role=data.role,
        invited_by=current_user.username,
    )
    return invitation


@router.get("/invitations", response_model=list[InvitationResponse])
async def list_invitations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出当前管理员厂区下的邀请 (超管可传 factory_id 查其他，此处默认自身)"""
    if not (current_user.is_superuser or current_user.role in ("admin", "manager")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看邀请")
    user_service = UserService(db)
    return await user_service.list_invitations(current_user.factory_id)


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """获取当前登录用户信息"""
    return current_user


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
            detail="Incorrect password"
        )
    
    # 更新密码
    await user_service.update_user(current_user.id, password=new_password)
    
    return {"message": "Password updated successfully"}


__all__ = ["router"]
