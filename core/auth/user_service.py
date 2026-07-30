"""
User Service - 用户管理服务
处理用户相关的业务逻辑
"""
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import secrets
from string import ascii_letters, digits
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import User
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

    async def forgot_password(self, email: str) -> Optional[Dict[str, Any]]:
        """
        忘记密码流程：
        1. 根据邮箱查找用户
        2. 如果找到用户，生成重置令牌并设置过期时间
        3. 清除任何旧的重置令牌
        4. 保存更新的用户记录
        5. 返回包含令牌和过期时间的信息（实际应用中会通过邮件发送）
        
        返回字典：{'token': str, 'expires_at': datetime} 或 None（用户不存在）
        """
        # from .email_service import send_password_reset_email  # 延迟导入避免循环依赖
# Use email service via get_email_service() instead
        
        user = await self.get_user_by_email(email)
        if not user:
            # 为了安全，即使用户不存在也返回相同消息，防止枚举攻击
            return None
        
        # 清除旧的重置令牌（如果存在）
        user.password_reset_token = None
        user.password_reset_expires = None
        
        # 生成安全的随机令牌（64字符的十六进制字符串）
        token = secrets.token_hex(32)
        
        # 设置令牌有效期（例如：1小时）
        expires_at = datetime.utcnow() + timedelta(hours=1)
        
        # 存储令牌的哈希（生产环境中应存储哈希而非明文）
        # 注意：这里简化处理，实际应使用类似get_password_hash的方法
        user.password_reset_token = token  # 建议在生产中存储哈希值
        user.password_reset_expires = expires_at
        user.updated_at = datetime.utcnow()
        
        await self.db.commit()
        
        # 准备重置链接（实际应用中需要通过邮件发送）
        reset_link = f"https://yourapp.com/reset-password?token={token}&email={email}"
        
        result = {
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "full_name": user.full_name,
            },
            "token": token,
            "expires_at": expires_at,
            "reset_link": reset_link,
            "email_sent": False,  # 将在email_service中实际发送邮件
        }
        
        # 异步发送重置邮件（不阻塞主流程）
        try:
            from .email_service import get_email_service
            email_service = get_email_service()
            # 在真实环境中启用以下行以发送邮件：
            # await email_service.send_password_reset_email(email, reset_link)
            print(f"📧 Password reset email would be sent to {email} (SMTP not configured in test env)")
        except Exception as e:
            print(f"Warning: Failed to prepare password reset email: {e}")
        
        return result

    async def reset_password(self, token: str, new_password: str) -> bool:
        """
        重置密码流程：
        1. 根据令牌查找有效且未过期的重置记录
        2. 验证新密码强度（可选）
        3. 更新用户的密码哈希
        4. 清除重置令牌
        5. 返回布尔值表示是否成功
        """
        from .security import get_password_hash
        
        # 检查新密码长度等基本要求（可扩展为更复杂的策略）
        if len(new_password) < 8:
            raise ValueError("Password must be at least 8 characters long")
        
        if len(new_password) > 255:
            raise ValueError("Password cannot exceed 255 characters")
        
        # 查找带有该令牌且未过期的用户
        query = select(User).where(
            User.password_reset_token == token,
            User.password_reset_expires > datetime.utcnow(),
            User.is_active == True
        )
        result = await self.db.execute(query)
        user = result.scalar_one_or_none()
        
        if not user:
            return False  # 令牌无效或已过期
        
        # 更新密码
        user.hashed_password = get_password_hash(new_password)
        user.password_reset_token = None  # 使用后立即清除令牌
        user.password_reset_expires = None
        user.updated_at = datetime.utcnow()
        
        await self.db.commit()
        
        return True
