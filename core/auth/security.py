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
# 以前这里是 `os.getenv("SECRET_KEY", "your-secret-key-change-in-production")`：占位值是公开的，
# 任何一处启动路径漏配 SECRET_KEY，别人就能自签 `sub=任意用户名` 免口令冒充该账号
# （2026-10-10 在克隆靶上实测：用这个占位值签的票直接拿到 /api/v1/auth/me 的真实档案）。
# 所以现在不给兜底默认值 —— 没配就是没配，签票/验票一律拒绝，并由应用启动时硬拦。
PLACEHOLDER_SECRET_KEY = "your-secret-key-change-in-production"
SECRET_KEY = os.getenv("SECRET_KEY", "")
ALGORITHM = "HS256"


def secret_key_configured() -> bool:
    """JWT 签名密钥是否真的配置了（非空且不等于历史上那个公开占位值）。"""
    return bool(SECRET_KEY) and SECRET_KEY != PLACEHOLDER_SECRET_KEY


def _require_secret_key(what: str) -> None:
    if not secret_key_configured():
        raise RuntimeError(
            "SECRET_KEY 未配置：拒绝" + what +
            "（代码里那个占位值是公开的，拿它签票等于把登录交给任何人）"
        )

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
    _require_secret_key("签发访问令牌")
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
    _require_secret_key("校验令牌")
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


# 公开面：登录前必须可达的路径。/api/v1/auth/ 整段放行是因为其中的受保护接口
# （/me、/change-password 等）本来就各自挂了 current_user，不靠这道闸。
PUBLIC_API_PREFIXES = ("/api/v1/auth/", "/api/v1/health")


async def require_login_for_api(request: Request) -> None:
    """默认拒绝：/api/ 下除公开清单外的路径，一律要带有效访问票。

    为什么挂在 app 级而不是逐接口补：本仓 711 个路由装饰器里只有 470 处写了
    `current_user` 依赖，漏掉的那批不是注释没写，是真的能匿名拉数据
    （实测 /api/v1/bom/models 41KB、/api/v1/mrp/history 8.7KB 无票 200）。
    新加的接口忘记挂依赖时，这道闸仍然兜得住 —— 漏一个不会立刻裸奔。
    """
    path = request.url.path
    if not path.startswith("/api/"):
        return                      # 静态页与 SPA 兜底不归这里管
    if request.method == "OPTIONS":
        return                      # CORS 预检不带凭据
    if any(path == p or path.startswith(p) for p in PUBLIC_API_PREFIXES):
        return

    authorization = request.headers.get("authorization", "")
    token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    payload = decode_token(token) if token else None
    if not payload or payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"{path} 需要登录",
            headers={"WWW-Authenticate": "Bearer"},
        )


def allowed_factory_ids(user: Optional[User]) -> Optional[set]:
    """这个账号有权进入的厂区集合。返回 None = 不限（超管）。

    租户归属只有这一个取法：请求侧的厂区选择器（`enforce_tenant`）和对象侧的行归属
    （服务层的 `_require_object_factory`）都问它，避免两处口径各自漂移。
    普通账号的集合 = {自身 factory_id} ∪ {已被管理员切换过的 active_factory_id} ——
    `active_factory_id` 只能由 /factory/switch（超管/开发账户）改，所以不是自助后门。
    """
    if user is None:
        return None
    if getattr(user, "is_superuser", False):
        return None
    return {getattr(user, "factory_id", None), getattr(user, "active_factory_id", None)} - {None, ""}


async def enforce_tenant(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Optional[str]:
    """租户闸：请求只要带了厂区选择器（`?factory_id=` 或 `X-Factory-Id` 头），就必须属于调用者。

    挂在 app 级依赖上，对**没带选择器**的请求直接返回 None（零查询、零行为变化），
    所以它能一次性覆盖所有 router，而不必逐接口补依赖。带了选择器却没登录 → 401：
    厂区不是匿名可见的过滤条件。超管沿用 `/factory/switch` 的跨厂口径；普通用户允许
    自身厂区与已被管理员切换过的 `active_factory_id`，指到别厂就 403 并点名是哪个厂 ——
    不静默降回本厂，因为静默降级会让界面显示成"这家厂没数据"，把攻击尝试藏起来。
    """
    requested = (request.headers.get("x-factory-id") or request.query_params.get("factory_id") or "").strip()
    if not requested:
        return None

    authorization = request.headers.get("authorization", "")
    token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    payload = decode_token(token) if token else None
    if not payload or not payload.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"带厂区参数({requested})的请求需要先登录",
        )

    from sqlalchemy import select
    result = await db.execute(select(User).where(User.username == payload["sub"]))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录态已失效")

    if getattr(user, "is_superuser", False):
        return requested

    allowed = allowed_factory_ids(user)
    if allowed is None or requested in allowed:
        return requested
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(f"厂区 {requested} 不在账号 {user.username} 的可访问范围"
                f"（可访问：{'、'.join(sorted(allowed)) or '未分配厂区'}）"),
    )


# ============================================================
# RBAC 权限控制
# ============================================================

class PermissionDenied(Exception):
    """权限不足异常"""
    pass


def require_permission(module: str, action: str):
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
    async def permission_checker(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
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

    permission_checker.__name__ = f"require_{module}_{action}"
    return permission_checker


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
