"""
测试模式角色切换 API
仅当 TEST_MODE=true 时可用，用于开发/测试阶段快速切换不同职位账号。
生产环境必须关闭此功能。
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import List, Optional

from database.db_config import get_db
from api.services.user_service import UserService
from core.auth.security import (
    create_access_token,
    create_refresh_token,
    get_current_user,
    SESSION_EXPIRE_HOURS,
)
from core.auth.roles import ROLE_DEFINITIONS, SYSTEM_ROLES, DEFAULT_ROLE_MAP, POSITION_NAMES, get_role_by_code
from database.models import User

# 仅用于测试模式的 router
test_router = APIRouter(prefix="/api/v1/auth/test", tags=["test-mode"])

# 测试模式开关（生产环境必须为 false）
TEST_MODE_ENABLED = __import__('os').getenv("TEST_MODE", "false").lower() == "true"


class TestSwitchRoleRequest(BaseModel):
    """测试模式切换角色请求"""
    role_code: str  # 角色编码，如 factory_manager, operator...


class TestSwitchResult(BaseModel):
    """切换结果"""
    username: str
    full_name: str
    role: str
    position: str
    department: str
    permissions: list
    data_scope: dict
    menu_items: list
    access_token: str
    refresh_token: str
    expires_in: int


def _is_test_mode():
    return TEST_MODE_ENABLED


async def _build_test_user_response(user: User) -> TestSwitchResult:
    """构建测试用户响应"""
    from core.auth.roles import get_user_permissions, get_menu_items_for_user, get_user_data_scope

    access_token = create_access_token(
        data={
            "sub": user.username,
            "user_id": str(user.id),
            "role": user.role,
            "is_superuser": user.is_superuser,
            "factory_id": user.factory_id,
            "test_mode": True,  # 标记这是测试模式 token
        }
    )
    refresh_token = create_refresh_token(
        data={"sub": user.username, "user_id": str(user.id)}
    )

    return TestSwitchResult(
        username=user.username,
        full_name=user.full_name or user.username,
        role=user.role,
        # position/department 从硬编码角色定义取（与菜单/权限同源），
        # 避免访问 user.role_obj 触发 async 懒加载 (MissingGreenlet)
        position=(get_role_by_code(user.role) or {}).get("position") or user.role,
        department=(get_role_by_code(user.role) or {}).get("department") or "all",
        permissions=get_user_permissions(user),
        data_scope=get_user_data_scope(user),
        menu_items=get_menu_items_for_user(user),
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=SESSION_EXPIRE_HOURS * 3600,
    )


@test_router.get("/status")
async def check_test_mode():
    """检查测试模式是否启用"""
    return {
        "enabled": _is_test_mode(),
        "message": "测试模式已启用 - 可以免登录切换角色" if _is_test_mode() else "测试模式未启用",
    }


@test_router.get("/roles")
async def list_test_roles():
    """
    获取所有可切换的角色列表
    每个角色包含：
      - code: 角色编码
      - name: 显示名称
      - position: 职位层级
      - department: 所属部门
      - description: 说明
      - permissions: 权限列表
      - data_scope: 数据范围
      - sample_users: 示例用户名列表
    """
    roles = []

    # 系统角色
    for code, role_def in SYSTEM_ROLES.items():
        roles.append({
            "code": code,
            "name": role_def["name"],
            "position": role_def["position"],
            "department": role_def.get("department", "all"),
            "description": role_def.get("description", ""),
            "permissions": role_def.get("permissions", []),
            "data_scope": role_def.get("data_scope", {"type": "all"}),
            "is_system": True,
            "sample_users": ["admin"],
        })

    # 业务角色
    for role_def in ROLE_DEFINITIONS:
        # 查找对应的示例用户
        sample_users = [
            username for username, mapped_role in DEFAULT_ROLE_MAP.items()
            if mapped_role == role_def["code"]
        ]

        roles.append({
            "code": role_def["code"],
            "name": role_def["name"],
            "position": role_def["position"],
            "department": role_def["department"],
            "description": role_def.get("description", ""),
            "permissions": role_def.get("permissions", []),
            "data_scope": role_def.get("data_scope", {"type": "own"}),
            "is_system": False,
            "sample_users": sample_users,
        })

    return roles


@test_router.post("/switch-role", response_model=TestSwitchResult)
async def switch_role(
    request: TestSwitchRoleRequest,
    db=Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    测试模式：切换当前会话到指定角色
    
    ⚠️ 仅在 TEST_MODE=true 时可用
    
    使用方式：
    1. 先登录任意账号
    2. 调用此接口切换角色
    3. 前端自动更新 token 和用户信息
    """
    if not _is_test_mode():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="测试模式未启用，请在环境变量中设置 TEST_MODE=true"
        )

    # 验证角色是否存在
    role_def = get_role_by_code(request.role_code)
    if not role_def:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"角色不存在: {request.role_code}"
        )

    user_service = UserService(db)

    # 查找该角色的示例用户
    # 优先使用 DEFAULT_ROLE_MAP 中映射的用户
    target_username = None
    for username, mapped_role in DEFAULT_ROLE_MAP.items():
        if mapped_role == request.role_code:
            target_username = username
            break

    # 如果没找到，尝试用 role_code 本身作为 username
    if not target_username:
        target_username = request.role_code

    # 查询目标用户
    target_user = await user_service.get_user_by_username(target_username)

    if not target_user:
        # 如果用户不存在，创建一个临时测试用户
        # 这样即使没有预创建用户也能测试
        try:
            target_user = await user_service.create_user(
                username=target_username,
                email=f"{target_username}@test.enghub.com",
                password="enghub123",
                full_name=role_def["name"],
                factory_id=current_user.factory_id,  # 继承当前用户的厂区
                role=request.role_code,
                is_superuser=(request.role_code == "admin"),
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"无法创建测试用户: {str(e)}"
            )

    if not target_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"角色用户 [{target_username}] 已被禁用"
        )

    return await _build_test_user_response(target_user)


@test_router.get("/users/{username}")
async def get_test_user_info(
    username: str,
    db=Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取指定测试用户的信息（含权限和菜单）"""
    user_service = UserService(db)
    user = await user_service.get_user_by_username(username)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"用户不存在: {username}"
        )

    return await _build_test_user_response(user)
