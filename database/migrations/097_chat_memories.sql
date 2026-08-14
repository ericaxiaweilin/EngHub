-- 097_chat_memories.sql
-- Chat 用户长期记忆：按 user_id(+factory) 维度跨会话持久。
-- 供 Harness Kernel 注入 system prompt 记忆块，实现「我的名字你记得吗」类跨会话记忆。
-- ORM 同步定义见 database/models.py ChatMemory。

CREATE TABLE IF NOT EXISTS chat_memories (
    id          VARCHAR(36) PRIMARY KEY,
    user_id     VARCHAR(36) NOT NULL,
    factory_id  VARCHAR(32),
    key         VARCHAR(64) NOT NULL,
    value       TEXT NOT NULL,
    confidence  SMALLINT NOT NULL DEFAULT 2,   -- 1=推断 2=用户明确告知
    source      VARCHAR(32) NOT NULL DEFAULT 'chat',
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_memories_user_key
    ON chat_memories(user_id, factory_id, key);
CREATE INDEX IF NOT EXISTS idx_chat_memories_user
    ON chat_memories(user_id);
