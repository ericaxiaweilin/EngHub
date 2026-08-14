-- 096: PMC训练题新增题型（判断/填空/计算/排序）

INSERT INTO position_training_questions
    (id, position_code, question_code, skill, difficulty, question_type, prompt,
     options, answer, explanation, reference_terms, points)
VALUES
('PT-PMC-Q31', 'pmc', 'PT-PMC-Q31', 'MRP净需求', 2, 'true_false',
 '判断：净需求 = 毛需求 - 可用库存 + 安全库存。',
 '[{"value":"T","label":"正确"},{"value":"F","label":"错误"}]'::jsonb,
 '["T"]'::jsonb,
 '净需求 = 毛需求 - 可用库存 + 安全库存，可用库存含现有库存、在途采购与在制工单。',
 '["MRP","净需求"]'::jsonb, 2),
('PT-PMC-Q32', 'pmc', 'PT-PMC-Q32', 'MPS排程', 2, 'true_false',
 '判断：MPS 冻结区（未来 1-3 周）内可以随意插单。',
 '[{"value":"T","label":"正确"},{"value":"F","label":"错误"}]'::jsonb,
 '["F"]'::jsonb,
 '冻结区内不可随意插单，插单必须走异常仲裁，否则破坏产能稳定与物料齐套。',
 '["MPS","冻结区","插单"]'::jsonb, 2),
('PT-PMC-Q33', 'pmc', 'PT-PMC-Q33', 'MRP参数', 3, 'fill',
 '填空：MRP 净需求公式中，在"毛需求 - 可用库存"的基础上还需要加回的是____。',
 '[]'::jsonb,
 '["安全库存","安全库存量"]'::jsonb,
 '净需求 = 毛需求 - 可用库存 + 安全库存，安全库存是必须保留的缓冲。',
 '["MRP","安全库存"]'::jsonb, 3),
('PT-PMC-Q34', 'pmc', 'PT-PMC-Q34', '出货前置', 2, 'fill',
 '填空：出货 T 日需在系统中完成过账操作（Post Good Issue，填英文缩写），并上传 Packing List & Invoice 至客户门户。',
 '[]'::jsonb,
 '["pgi","post good issue"]'::jsonb,
 'T 日系统过账 Post Good Issue（PGI）确认出库，随单上传装箱单与发票。',
 '["OTD","Post Good Issue","PGI"]'::jsonb, 2)
ON CONFLICT (id) DO UPDATE SET
    position_code = EXCLUDED.position_code, skill = EXCLUDED.skill,
    difficulty = EXCLUDED.difficulty, question_type = EXCLUDED.question_type,
    prompt = EXCLUDED.prompt, options = EXCLUDED.options, answer = EXCLUDED.answer,
    explanation = EXCLUDED.explanation, reference_terms = EXCLUDED.reference_terms,
    points = EXCLUDED.points, is_active = TRUE, updated_at = NOW();

INSERT INTO position_training_questions
    (id, position_code, question_code, skill, difficulty, question_type, prompt,
     options, answer, explanation, reference_terms, points)
VALUES
('PT-PMC-Q35', 'pmc', 'PT-PMC-Q35', 'MRP净需求', 3, 'calc',
 '计算：某物料现有库存 100，在途采购 50，在制工单 30，安全库存 20，毛需求 250。净需求 = ？',
 '[]'::jsonb,
 '["90"]'::jsonb,
 '净需求 = 250 - (100+50+30) + 20 = 250 - 180 + 20 = 90。',
 '["MRP","净需求","计算"]'::jsonb, 3),
('PT-PMC-Q36', 'pmc', 'PT-PMC-Q36', '库存DOH', 3, 'calc',
 '计算：库存金额 360 万元，过去 3 个月平均日消耗成本 4 万元/天，DOH = ？',
 '[]'::jsonb,
 '["90"]'::jsonb,
 'DOH = 360 / 4 = 90 天，超过 60 天标红预警。',
 '["DOH","库存周转","计算"]'::jsonb, 3),
('PT-PMC-Q37', 'pmc', 'PT-PMC-Q37', 'MRP参数', 2, 'calc',
 '计算：某料 MOQ=100，MRP 净需求为 240，按 MOQ 凑整后应下单多少？',
 '[]'::jsonb,
 '["300"]'::jsonb,
 '净需求 240 需向上凑整到 MOQ=100 的倍数，即 300。',
 '["MOQ","批量","凑整"]'::jsonb, 2)
ON CONFLICT (id) DO UPDATE SET
    position_code = EXCLUDED.position_code, skill = EXCLUDED.skill,
    difficulty = EXCLUDED.difficulty, question_type = EXCLUDED.question_type,
    prompt = EXCLUDED.prompt, options = EXCLUDED.options, answer = EXCLUDED.answer,
    explanation = EXCLUDED.explanation, reference_terms = EXCLUDED.reference_terms,
    points = EXCLUDED.points, is_active = TRUE, updated_at = NOW();

INSERT INTO position_training_questions
    (id, position_code, question_code, skill, difficulty, question_type, prompt,
     options, answer, explanation, reference_terms, points)
VALUES
('PT-PMC-Q38', 'pmc', 'PT-PMC-Q38', 'MRP例外处理', 3, 'order',
 '排序：MRP 跑完后到转成正式单据，正确的处理顺序是？',
 '[{"value":"a","label":"直接全部转为正式单据"},{"value":"b","label":"先处理例外信息"},{"value":"c","label":"按交期紧迫度排序"},{"value":"d","label":"微调数量凑整包装与日期避开车历"}]'::jsonb,
 '["b","c","d","a"]'::jsonb,
 '正确顺序：先看例外信息（提前期不足/批量调整）→ 按交期紧迫度排序 → 微调数量与日期 → 确认后转正式单据。',
 '["MRP","例外信息","计划订单","顺序"]'::jsonb, 3),
('PT-PMC-Q39', 'pmc', 'PT-PMC-Q39', '呆滞处置', 3, 'order',
 '排序：针对已认定的 E&O 物料，月度处置动作的正确顺序是？',
 '[{"value":"a","label":"替代品使用"},{"value":"b","label":"报废（高层财务签字）"},{"value":"c","label":"退回供应商"},{"value":"d","label":"低价甩卖（打折给贸易商）"}]'::jsonb,
 '["a","c","d","b"]'::jsonb,
 '处置顺序：①替代品使用（优先）②退回供应商 ③低价甩卖 ④报废（高层财务签字）。',
 '["E&O","处置","顺序"]'::jsonb, 3),
('PT-PMC-Q40', 'pmc', 'PT-PMC-Q40', 'OTD出货', 2, 'order',
 '排序：从接单到出货，以下环节的正确先后顺序是？',
 '[{"value":"a","label":"出货过账与上传单据"},{"value":"b","label":"拣货、贴标、二次称重"},{"value":"c","label":"库存锁定与发货优先级排序"},{"value":"d","label":"确认交期（CTP）"}]'::jsonb,
 '["d","c","b","a"]'::jsonb,
 '流程：先确认可承诺交期（CTP）→ 库存锁定按优先级分配 → T-1 拣货贴标称重 → T 日系统过账并上传单据。',
 '["CTP","发货优先级","OTD","顺序"]'::jsonb, 2)
ON CONFLICT (id) DO UPDATE SET
    position_code = EXCLUDED.position_code, skill = EXCLUDED.skill,
    difficulty = EXCLUDED.difficulty, question_type = EXCLUDED.question_type,
    prompt = EXCLUDED.prompt, options = EXCLUDED.options, answer = EXCLUDED.answer,
    explanation = EXCLUDED.explanation, reference_terms = EXCLUDED.reference_terms,
    points = EXCLUDED.points, is_active = TRUE, updated_at = NOW();
