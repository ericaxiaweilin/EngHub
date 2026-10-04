-- WMS 仓库/库位 ORM 与生产库表结构对齐。
-- warehouses.manager_id、locations.row/column 在生产库已存在（业务先建表），
-- ORM 缺失导致读取即 AttributeError。IF NOT EXISTS 保证幂等。
ALTER TABLE warehouses
    ADD COLUMN IF NOT EXISTS manager_id VARCHAR(36);
ALTER TABLE locations
    ADD COLUMN IF NOT EXISTS "row" VARCHAR(30);
ALTER TABLE locations
    ADD COLUMN IF NOT EXISTS "column" VARCHAR(30);
