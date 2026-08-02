"""
User Service - 用户管理服务
处理用户相关的业务逻辑 + 角色管理
"""
from typing import Optional, List
from datetime import datetime
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import User, Role, UserRole, Permission
from core.auth.security import get_password_hash, verify_password


class UserService:
    """用户服务类"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_user_by_username(self, username: str) -> Optional[User]:
        """根据用户名获取用户"""
        result = await self.db.execute(
            select(User).where(User.username == username)
        )
        return result.scalar_one_or_none()
    
    async def get_user_by_email(self, email: str) -> Optional[User]:
        """根据邮箱获取用户"""
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()
    
    async def get_user_by_id(self, user_id: str) -> Optional[User]:
        """根据 ID 获取用户"""
        from uuid import UUID
        result = await self.db.execute(
            select(User).where(User.id == UUID(user_id))
        )
        return result.scalar_one_or_none()
    
    async def authenticate_user(
        self, 
        username: str, 
        password: str
    ) -> Optional[User]:
        """
        验证用户登录
        返回用户对象或 None
        """
        user = await self.get_user_by_username(username)
        if not user:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return user
    
    async def create_user(
        self,
        username: str,
        email: str,
        password: str,
        full_name: Optional[str] = None,
        factory_id: Optional[str] = None,
        role: str = "operator",
        is_superuser: bool = False,
        position: Optional[str] = None,
        department: Optional[str] = None,
    ) -> User:
        """创建新用户"""
        hashed_password = get_password_hash(password)
        
        # 查找角色定义
        role_obj = None
        if role != "admin" and not is_superuser:
            from core.auth.roles import get_role_by_code
            role_def = get_role_by_code(role)
            if role_def:
                role_obj = Role(
                    role_code=role,
                    role_name=role_def["name"],
                    position=position or role_def["position"],
                    department=department or role_def["department"],
                    description=role_def.get("description", ""),
                    is_system=False,
                    level=role_def.get("level", 999),
                    permissions=role_def.get("permissions", []),
                    data_scope=role_def.get("data_scope", {"type": "own"}),
                )
                self.db.add(role_obj)
                await self.db.flush()
        
        user = User(
            username=username,
            email=email,
            hashed_password=hashed_password,
            full_name=full_name,
            factory_id=factory_id,
            role=role,
            role_id=role_obj.id if role_obj else None,
            is_active=True,
            is_superuser=is_superuser,
        )
        
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        
        return user
    
    async def update_user(
        self,
        user_id: str,
        **kwargs
    ) -> Optional[User]:
        """更新用户信息"""
        user = await self.get_user_by_id(user_id)
        if not user:
            return None
        
        # 允许更新的字段
        allowed_fields = [
            "email", "full_name", "factory_id", "role", "is_active",
        ]
        
        for field in allowed_fields:
            if field in kwargs:
                setattr(user, field, kwargs[field])
        
        # 特殊处理密码更新
        if "password" in kwargs and kwargs["password"]:
            user.hashed_password = get_password_hash(kwargs["password"])
        
        user.updated_at = datetime.utcnow()
        
        await self.db.commit()
        await self.db.refresh(user)
        
        return user
    
    async def assign_role(self, user_id: str, role_code: str) -> User:
        """给用户分配角色（更新 role 字段）"""
        user = await self.get_user_by_id(user_id)
        if not user:
            return None
        
        from core.auth.roles import get_role_by_code
        role_def = get_role_by_code(role_code)
        if not role_def:
            raise ValueError(f"角色不存在: {role_code}")
        
        user.role = role_code
        
        # 同步更新 role 表中的角色记录
        role_obj = await self.db.execute(
            select(Role).where(Role.role_code == role_code)
        )
        role_record = role_obj.scalar_one_or_none()
        if role_record:
            user.role_id = role_record.id
        
        await self.db.commit()
        await self.db.refresh(user)
        return user
    
    async def update_last_login(self, user_id: str) -> bool:
        """更新最后登录时间"""
        await self.db.execute(
            update(User)
            .where(User.id == user_id)
            .values(last_login=datetime.utcnow())
        )
        await self.db.commit()
        return True
    
    async def list_users(
        self,
        factory_id: Optional[str] = None,
        role: Optional[str] = None,
        is_active: Optional[bool] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[User]:
        """获取用户列表"""
        query = select(User)
        
        if factory_id:
            query = query.where(User.factory_id == factory_id)
        if role:
            query = query.where(User.role == role)
        if is_active is not None:
            query = query.where(User.is_active == is_active)
        
        query = query.offset(skip).limit(limit)
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def delete_user(self, user_id: str) -> bool:
        """删除用户 (软删除，设置为非激活)"""
        user = await self.get_user_by_id(user_id)
        if not user:
            return False
        
        user.is_active = False
        user.updated_at = datetime.utcnow()
        
        await self.db.commit()
        return True
    
    # ---- 角色管理 ----
    
    async def list_roles(self, is_system: Optional[bool] = None) -> List[Role]:
        """获取角色列表"""
        query = select(Role)
        if is_system is not None:
            query = query.where(Role.is_system == is_system)
        query = query.order_by(Role.level)
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def get_role_by_code(self, role_code: str) -> Optional[Role]:
        """根据编码获取角色"""
        result = await self.db.execute(
            select(Role).where(Role.role_code == role_code)
        )
        return result.scalar_one_or_none()
    
    async def create_role(self, role_data: dict) -> Role:
        """创建角色"""
        role = Role(**role_data)
        self.db.add(role)
        await self.db.commit()
        await self.db.refresh(role)
        return role
    
    async def update_role(self, role_id: str, **kwargs) -> Optional[Role]:
        """更新角色"""
        from uuid import UUID
        role = await self.db.execute(
            select(Role).where(Role.id == UUID(role_id))
        )
        role = role.scalar_one_or_none()
        if not role:
            return None
        
        allowed_fields = ["role_name", "position", "department", "description", "level"]
        for field in allowed_fields:
            if field in kwargs:
                setattr(role, field, kwargs[field])
        
        if "permissions" in kwargs:
            role.permissions = kwargs["permissions"]
        if "data_scope" in kwargs:
            role.data_scope = kwargs["data_scope"]
        
        role.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(role)
        return role
    
    async def delete_role(self, role_id: str) -> bool:
        """删除角色（仅非系统角色可删除）"""
        from uuid import UUID
        role = await self.db.execute(
            select(Role).where(Role.id == UUID(role_id))
        )
        role = role.scalar_one_or_none()
        if not role:
            return False
        if role.is_system:
            return False
        
        await self.db.execute(
            update(UserRole)
            .where(UserRole.role_id == UUID(role_id))
            .values(expires_at=datetime.utcnow())  # 软过期
        )
        await self.db.delete(role)
        await self.db.commit()
        return True
    
    async def init_default_permissions(self) -> int:
        """初始化默认权限记录到数据库"""
        from core.auth.roles import MODULES, ACTIONS
        count = 0
        for module, module_name in MODULES.items():
            for action, action_name in ACTIONS.items():
                existing = await self.db.execute(
                    select(Permission).where(
                        Permission.module == module,
                        Permission.action == action,
                    )
                )
                if existing.scalar_one_or_none():
                    continue
                perm = Permission(
                    module=module,
                    action=action,
                    module_name=module_name,
                    action_name=action_name,
                    description=f"{module_name} - {action_name}",
                )
                self.db.add(perm)
                count += 1
        await self.db.commit()
        return count
