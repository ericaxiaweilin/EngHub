-- 015: 文件/附件存储表（chatbot 多模态收发 + 系统表单/报告导出）
-- 统一存储上传文件与 AI 导出文件的元数据，实体落盘到容器 /app/uploads。
-- 按 factory_id 做多工厂隔离；related_type/related_id 关联业务对象（如 work_order/inspection）。

CREATE TABLE IF NOT EXISTS files (
    id VARCHAR(36) PRIMARY KEY,
    filename VARCHAR(255) NOT NULL,            -- 原始文件名
    content_type VARCHAR(100),                 -- MIME 类型（image/png、application/pdf...）
    size BIGINT DEFAULT 0,                     -- 字节数
    storage_path VARCHAR(500) NOT NULL,        -- 容器内落盘路径
    uploaded_by VARCHAR(50),                   -- 上传人 username
    factory_id VARCHAR(50),                    -- 所属工厂（多工厂隔离）
    related_type VARCHAR(50),                  -- 关联业务对象类型（work_order/inspection/report/chat...）
    related_id VARCHAR(50),                    -- 关联业务对象 ID
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_files_factory ON files (factory_id);
CREATE INDEX IF NOT EXISTS idx_files_related ON files (related_type, related_id);
CREATE INDEX IF NOT EXISTS idx_files_created ON files (created_at);
