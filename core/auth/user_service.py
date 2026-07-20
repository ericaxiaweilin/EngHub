"""
User Service - 用户管理服务
处理用户相关的业务逻辑
"""
from typing import Optional, List
import secrets
from datetime import datetime, timedelta
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import User, Factory, UserInvitation
from .security import get_password_hash, verify_password


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
        result = await self.db.execute(
            select(User).where(User.id == user_id)
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
    ) -> User:
        """创建新用户"""
        hashed_password = get_password_hash(password)
        
        user = User(
            username=username,
            email=email,
            hashed_password=hashed_password,
            full_name=full_name,
            factory_id=factory_id,
            role=role,
            is_superuser=is_superuser,
            is_active=True,
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
            "email", "full_name", "factory_id", "role",
            "is_active", "is_superuser"
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

    # ------------------------------------------------------------------
    # 多租户 / 邀请制 (移植自 engflow AuthService + rbac.invitation_service)
    # ------------------------------------------------------------------

    async def get_factory(self, factory_id: str) -> Optional[Factory]:
        """根据租户键获取厂区"""
        result = await self.db.execute(
            select(Factory).where(Factory.id == factory_id)
        )
        return result.scalar_one_or_none()

    async def create_factory(self, factory_id: str, name: str) -> Factory:
        """创建新租户(厂区)"""
        factory = Factory(id=factory_id, name=name, is_active=True)
        self.db.add(factory)
        await self.db.commit()
        await self.db.refresh(factory)
        return factory

    async def create_invitation(
        self,
        email: str,
        factory_id: str,
        role: str = "operator",
        invited_by: Optional[str] = None,
        ttl_days: int = 7,
    ) -> UserInvitation:
        """创建邀请 (安全随机 token + 7 天有效期，改进自 engflow 邮箱匹配方式)"""
        invitation = UserInvitation(
            email=email,
            factory_id=factory_id,
            role=role,
            token=secrets.token_urlsafe(32),
            accepted=False,
            invited_by=invited_by,
            expires_at=datetime.utcnow() + timedelta(days=ttl_days),
        )
        self.db.add(invitation)
        await self.db.commit()
        await self.db.refresh(invitation)
        return invitation

    async def get_invitation_by_token(self, token: str) -> Optional[UserInvitation]:
        """根据 token 获取未接受且未过期的邀请"""
        result = await self.db.execute(
            select(UserInvitation).where(UserInvitation.token == token)
        )
        inv = result.scalar_one_or_none()
        if not inv or inv.accepted or inv.expires_at < datetime.utcnow():
            return None
        return inv

    async def list_invitations(self, factory_id: str) -> List[UserInvitation]:
        """列出某租户下的邀请"""
        result = await self.db.execute(
            select(UserInvitation)
            .where(UserInvitation.factory_id == factory_id)
            .order_by(UserInvitation.created_at.desc())
        )
        return result.scalars().all()

    async def register_user(
        self,
        username: str,
        email: str,
        password: str,
        full_name: Optional[str] = None,
        factory_id: Optional[str] = None,
        invitation_token: Optional[str] = None,
    ) -> User:
        """自助注册 (邀请制多租户，移植自 engflow register_user 并改进):

        - 有邀请 token：校验 token（邮箱/厂区一致、未过期），角色取自邀请，标记已接受；
        - 无邀请且厂区不存在：开放注册，创建新租户，首个用户成为该租户 admin；
        - 无邀请但厂区已存在：拒绝（已有租户仅邀请可加入）。
        """
        if await self.get_user_by_username(username):
            raise ValueError("用户名已存在")
        if await self.get_user_by_email(email):
            raise ValueError("邮箱已注册")

        role = "operator"
        is_superuser = False
        invitation: Optional[UserInvitation] = None

        if invitation_token:
            invitation = await self.get_invitation_by_token(invitation_token)
            if not invitation:
                raise ValueError("邀请码无效或已过期")
            if invitation.email.lower() != email.lower():
                raise ValueError("邀请码与邮箱不匹配")
            factory_id = invitation.factory_id
            role = invitation.role
        else:
            if not factory_id:
                raise ValueError("必须提供厂区(租户)")
            existing_factory = await self.get_factory(factory_id)
            if existing_factory:
                raise ValueError(f"厂区 '{factory_id}' 已存在，需邀请码才能加入")
            # 开放注册：创建新租户，首用户为租户管理员
            await self.create_factory(factory_id, name=(full_name or username) + " 厂区")
            role = "admin"

        user = await self.create_user(
            username=username,
            email=email,
            password=password,
            full_name=full_name,
            factory_id=factory_id,
            role=role,
            is_superuser=is_superuser,
        )

        if invitation:
            invitation.accepted = True
            await self.db.commit()

        return user
