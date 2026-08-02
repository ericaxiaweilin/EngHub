-- 030: 站内通知表（生产统计员打穿：报告就绪/异常预警/系统消息推送）
CREATE TABLE IF NOT EXISTS notifications (
    id VARCHAR(36) PRIMARY KEY,
    factory_id VARCHAR(50) NOT NULL,
    recipient VARCHAR(50),
    category VARCHAR(30) NOT NULL DEFAULT 'system',
    title VARCHAR(200) NOT NULL,
    content TEXT,
    severity VARCHAR(10) DEFAULT 'info',
    source_type VARCHAR(30),
    source_id VARCHAR(50),
    is_read BOOLEAN DEFAULT FALSE,
    read_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notifications_factory ON notifications(factory_id);
CREATE INDEX IF NOT EXISTS idx_notifications_recipient ON notifications(recipient);
CREATE INDEX IF NOT EXISTS idx_notif_unread ON notifications(factory_id, recipient, is_read);
