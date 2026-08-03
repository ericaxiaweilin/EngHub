-- WMS 物料体积/重量参数表 + 仓库容积字段
CREATE TABLE IF NOT EXISTS material_volume_specs (
    id VARCHAR(36) PRIMARY KEY,
    factory_id VARCHAR(50) NOT NULL,
    material_id VARCHAR(50) NOT NULL,
    material_code VARCHAR(50) NOT NULL,
    material_name VARCHAR(100),
    length_cm NUMERIC(10, 2),
    width_cm NUMERIC(10, 2),
    height_cm NUMERIC(10, 2),
    unit_volume_m3 NUMERIC(14, 6) NOT NULL DEFAULT 0,
    unit_weight_kg NUMERIC(14, 4) NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    UNIQUE (factory_id, material_code)
);

CREATE INDEX IF NOT EXISTS idx_material_volume_specs_factory
    ON material_volume_specs (factory_id);

ALTER TABLE warehouses ADD COLUMN IF NOT EXISTS total_volume_m3 NUMERIC(14, 2);
ALTER TABLE warehouses ADD COLUMN IF NOT EXISTS usable_volume_m3 NUMERIC(14, 2);
