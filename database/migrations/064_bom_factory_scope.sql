-- Migration 064: BOM 按工厂隔离，支持 EngFlow → 机械厂同步
-- enghub_bom_items 增加 factory_id；补齐 id 自增序列

ALTER TABLE enghub_bom_items
    ADD COLUMN IF NOT EXISTS factory_id VARCHAR(50);

CREATE INDEX IF NOT EXISTS idx_enghub_bom_factory
    ON enghub_bom_items(factory_id);

CREATE INDEX IF NOT EXISTS idx_enghub_bom_factory_model
    ON enghub_bom_items(factory_id, product_model);

CREATE SEQUENCE IF NOT EXISTS enghub_bom_items_id_seq;
SELECT setval(
    'enghub_bom_items_id_seq',
    COALESCE((SELECT MAX(id) FROM enghub_bom_items), 0) + 1,
    false
);
ALTER TABLE enghub_bom_items
    ALTER COLUMN id SET DEFAULT nextval('enghub_bom_items_id_seq');
ALTER SEQUENCE enghub_bom_items_id_seq OWNED BY enghub_bom_items.id;

ALTER TABLE enghub_bom_sync_log
    ADD COLUMN IF NOT EXISTS factory_id VARCHAR(50);
ALTER TABLE enghub_bom_sync_log
    ADD COLUMN IF NOT EXISTS source_company_id VARCHAR(50);

CREATE UNIQUE INDEX IF NOT EXISTS uq_enghub_bom_factory_source
    ON enghub_bom_items(factory_id, source_row_id)
    WHERE factory_id IS NOT NULL AND source_row_id IS NOT NULL;

COMMENT ON COLUMN enghub_bom_items.factory_id IS 'EngHub 工厂 ID，EngFlow BOM 仅同步至 FAC_MECH_001';
