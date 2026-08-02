"""
Email Service - 邮件发送服务
用于发送忘记密码重置链接等通知邮件
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, List
import os
from datetime import datetime


class EmailService:
    """邮件服务类"""
    
    def __init__(self):
        # 从环境变量读取邮件配置
        self.smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_username = os.getenv("SMTP_USERNAME")
        self.smtp_password = os.getenv("SMTP_PASSWORD")
        self.sender_email = os.getenv("SENDER_EMAIL", self.smtp_username)
        self.use_tls = bool(os.getenv("USE_TLS", "true").lower() == "true")
        
        if not self.smtp_username or not self.smtp_password:
            print("Warning: SMTP credentials not set, email sending will be disabled")
    
    async def send_password_reset_email(self, recipient_email: str, reset_link: str) -> bool:
        """
        发送密码重置邮件
        
        Args:
            recipient_email: 收件人邮箱地址
            reset_link: 包含重置令牌的URL链接
            
        Returns:
            bool: 发送成功返回True，失败返回False
        """
        try:
            # 构建邮件内容
            subject = "密码重置请求"
            
            body = f"""
亲爱的用户，

您收到了这封邮件是因为有人在您的账户上请求了密码重置。

如果您没有发起此请求，请忽略此邮件并无需采取任何操作。

如确实需要重置密码，请点击以下链接：
{reset_link}

该链接将在1小时后过期。

感谢您使用 EngHub！

[系统自动发送邮件，请勿直接回复]
"""
            
            msg = MIMEMultipart()
            msg["From"] = self.sender_email
            msg["To"] = recipient_email
            msg["Subject"] = subject
            
            msg.attach(MIMEText(body, "html", "utf-8"))
            
            # 连接到SMTP服务器并发送邮件
            if self.use_tls:
                server = smtplib.SMTP(self.smtp_server, self.smtp_port)
                server.starttls()
            else:
                server = smtplib.SMTP_SSL(self.smtp_server, self.smtp_port)
            
            server.login(self.smtp_username, self.smtp_password)
            
            text = msg.as_string()
            server.sendmail(self.sender_email, recipient_email, text)
            server.quit()
            
            print(f"✅ Password reset email sent to {recipient_email}")
            return True
            
        except Exception as e:
            print(f"❌ Failed to send password reset email to {recipient_email}: {e}")
            return False
    
    async def send_email_batch(self, recipients: List[str], subject: str, body: str) -> bool:
        """
        批量发送邮件（备用方法）
        """
        try:
            msg = MIMEMultipart()
            msg["From"] = self.sender_email
            msg["Subject"] = subject
            
            msg.attach(MIMEText(body, "html", "utf-8"))
            
            if self.use_tls:
                server = smtplib.SMTP(self.smtp_server, self.smtp_port)
                server.starttls()
            else:
                server = smtplib.SMTP_SSL(self.smtp_server, self.smtp_port)
            
            server.login(self.smtp_username, self.smtp_password)
            
            for recipient in recipients:
                msg["To"] = recipient
                server.sendmail(self.sender_email, recipient, msg.as_string())
            
            server.quit()
            return True
            
        except Exception as e:
            print(f"Failed to send batch email: {e}")
            return False


# 全局实例（单例模式）
_email_service: Optional[EmailService] = None


def get_email_service() -> EmailService:
    """获取邮件服务实例（单例）"""
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
    return _email_service