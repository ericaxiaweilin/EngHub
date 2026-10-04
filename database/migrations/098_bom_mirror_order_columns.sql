-- 098_bom_mirror_order_columns.sql
-- 给 BOM 镜像补上"行序"列，让多层 BOM 能重建父子结构。
--
-- engflow 上传的层级 BOM 不写 parent_sap（481,557 行全为空），结构体现在
-- 缩进顺序上：按 (source_file, original_row_number) 排好后，层深每次最多加 1
-- （A-50-04-F 的 861 行里跳层 0 次；全局 62/481557 例外）。
-- 所以"某行的直接父级 = 它前面最近的一条 level-1 行"，可确定性重建，
-- 不需要猜。镜像以前只留了 level，把行序丢了 —— 多层 MRP 就卡在这。

ALTER TABLE enghub_bom_items
    ADD COLUMN IF NOT EXISTS source_file VARCHAR(500),
    ADD COLUMN IF NOT EXISTS original_row_number BIGINT,
    ADD COLUMN IF NOT EXISTS l2_parent_group VARCHAR(200),
    ADD COLUMN IF NOT EXISTS l3_context VARCHAR(200);

-- 展开一个型号时要按行序扫它的全部层级
CREATE INDEX IF NOT EXISTS idx_enghub_bom_model_roword
    ON enghub_bom_items (factory_id, product_model, original_row_number);
