"""
Security utilities for authentication
密码加密和 JWT Token 工具 + RBAC 权限控制
"""
import os
import bcrypt
from datetime import datetime, timedelta
from functools import wraps
from typing import Optional, List
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from database.db_config import get_db
from database.models import User, Role, UserRole

# 配置
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
# 会话策略：12 小时强制重新登录（access 与 refresh 同步过期，禁止静默续期）
SESSION_EXPIRE_HOURS = int(os.getenv("SESSION_EXPIRE_HOURS", "12"))
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", str(SESSION_EXPIRE_HOURS * 60)))
REFRESH_TOKEN_EXPIRE_HOURS = int(os.getenv("REFRESH_TOKEN_EXPIRE_HOURS", str(SESSION_EXPIRE_HOURS)))

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码 (直连 bcrypt，避开 passlib 1.7.4 与 bcrypt>=4.1 的 72-byte 自检 bug)"""
    if not hashed_password:
        return False
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    """生成密码哈希 (直连 bcrypt，输出标准 $2b$ 哈希，与旧 passlib 哈希兼容)"""
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    return hashed.decode("utf-8")


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """创建访问令牌"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """创建刷新令牌"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(hours=REFRESH_TOKEN_EXPIRE_HOURS)

    to_encode.update({"exp": expire, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_token(token: str) -> Optional[dict]:
    """解码令牌"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db)
) -> User:
    """
    获取当前登录用户
    用于需要认证的路由
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_token(token)
    if payload is None:
        raise credentials_exception

    username: str = payload.get("sub")
    if username is None:
        raise credentials_exception

    # 从数据库查询用户
    from sqlalchemy import select
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise credentials_exception

    return user


async def get_current_active_superuser(
    current_user: User = Depends(get_current_user)
) -> User:
    """获取当前超级管理员用户"""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough privileges"
        )
    return current_user


async def enforce_tenant(
    factory_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
) -> str:
    """多租户隔离依赖 (改进自 engflow TenantContext)。

    作为路由级依赖挂到业务 router：
    - 普通用户：强制锁定自身 factory_id，客户端传入不一致的厂区直接 403；
    - 超管(is_superuser)：可跨厂区，传什么用什么，不传则用自身。
    返回生效的 factory_id (供需要的端点复用)。
    """
    if current_user.is_superuser:
        return factory_id or current_user.factory_id
    if not current_user.factory_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前用户未分配厂区(租户)",
        )
    if factory_id and factory_id != current_user.factory_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权访问其他厂区(租户)的数据",
        )
    return current_user.factory_id


# ============================================================
# RBAC 权限控制
# ============================================================

class PermissionDenied(Exception):
    """权限不足异常"""
    pass


async def require_permission(
    module: str,
    action: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    检查当前用户是否拥有指定模块的操作权限
    
    用法:
        @router.post("/work-orders")
        async def create_work_order(
            ...
            current_user: User = Depends(require_permission("work_order", "create")),
        ):
            ...
    """
    if current_user.is_superuser or current_user.role == "admin":
        return current_user

    # 从角色定义中获取权限
    from core.auth.roles import get_user_permissions, has_permission
    user_perms = get_user_permissions(current_user)
    
    if has_permission(user_perms, module, action):
        return current_user

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"权限不足：需要 [{module}.{action}] 权限",
    )


async def require_any_permission(
    checks: List[tuple],
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    检查当前用户是否拥有任一权限组合
    
    checks: [("work_order", "view"), ("work_order", "create")]
    只要满足其中一个即可
    """
    if current_user.is_superuser or current_user.role == "admin":
        return current_user

    from core.auth.roles import get_user_permissions, has_permission
    user_perms = get_user_permissions(current_user)
    
    for module, action in checks:
        if has_permission(user_perms, module, action):
            return current_user

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="权限不足：需要以下任一权限",
    )


async def require_all_permissions(
    checks: List[tuple],
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    检查当前用户是否拥有所有权限组合
    
    checks: [("work_order", "view"), ("work_order", "create")]
    必须全部满足
    """
    if current_user.is_superuser or current_user.role == "admin":
        return current_user

    from core.auth.roles import get_user_permissions, has_permission
    user_perms = get_user_permissions(current_user)
    
    for module, action in checks:
        if not has_permission(user_perms, module, action):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"权限不足：需要 [{module}.{action}] 权限",
            )
    
    return current_user


def get_user_menu_items(user: User) -> list:
    """获取用户可见菜单项"""
    from core.auth.roles import get_menu_items_for_user
    return get_menu_items_for_user(user)


def get_user_data_scope(user: User) -> dict:
    """获取用户数据范围"""
    from core.auth.roles import get_user_data_scope
    return get_user_data_scope(user)
