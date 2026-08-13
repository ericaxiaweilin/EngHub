-- Persisted Univer workbooks for PMC/Chatbot online tables.
CREATE TABLE IF NOT EXISTS online_workbooks (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    factory_id VARCHAR(50),
    snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_file_id VARCHAR(36),
    created_by VARCHAR(50),
    updated_by VARCHAR(50),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_online_workbooks_factory
    ON online_workbooks(factory_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_online_workbooks_source_file
    ON online_workbooks(source_file_id);
