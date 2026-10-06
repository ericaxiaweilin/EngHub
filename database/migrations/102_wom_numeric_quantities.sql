-- 齐套表的数字列从 integer 放宽到 numeric(18,4)。
--
-- BOM 里深层原料的每件用量是小数（实测 A-30-04-F 的 圓棒料 φ26：0.255 / 0.33 / 1.714，
-- 单位是长度/重量类计量，不是"几个"）。MRP 表 mrp_items 本来就是 numeric，
-- 但复制到工单齐套表时被 int() 截成 0：
--   · 这些行看起来"不需要料"，拆出的子工单因此拿不到自己的物料行（实测 289 张子单无行，
--     其中 113 张的行其实就挂在父单快照里，只是数量为 0 被跳过）；
--   · 引擎判"没有依据"，既不投产也不催料 —— 等于整条深层供应链被看不见。
-- 这是只放宽、不收紧的变更（integer → numeric(18,4) 无精度损失）。
ALTER TABLE work_order_materials
    ALTER COLUMN qty_per_unit   TYPE numeric(18,4) USING qty_per_unit::numeric(18,4),
    ALTER COLUMN required_qty   TYPE numeric(18,4) USING required_qty::numeric(18,4),
    ALTER COLUMN available_qty  TYPE numeric(18,4) USING available_qty::numeric(18,4),
    ALTER COLUMN received_qty   TYPE numeric(18,4) USING received_qty::numeric(18,4),
    ALTER COLUMN shortage_qty   TYPE numeric(18,4) USING shortage_qty::numeric(18,4);
