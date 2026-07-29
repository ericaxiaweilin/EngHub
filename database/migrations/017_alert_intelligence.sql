-- 017: AI 预警审查记录表（Chatbot 主动智能与预警审查）
-- 每条被动预警（Andon/质量缺陷/设备故障/工单超时）触发一条 AI 审查记录

CREATE TABLE IF NOT EXISTS alert_intelligence_reviews (
  id VARCHAR(36) PRIMARY KEY,
  factory_id VARCHAR(50) NOT NULL,
  alert_source VARCHAR(30) NOT NULL,       -- andon/defect/equipment/wo_timeout/inventory
  alert_ref_id VARCHAR(36) NOT NULL,       -- 关联的源记录 ID
  alert_ref_code VARCHAR(100),             -- 源记录编码（便于展示）
  alert_summary TEXT NOT NULL,             -- 预警摘要（传给 AI 的上下文）
  severity_assessment VARCHAR(20),         -- AI 判定严重度：critical/high/medium/low
  root_cause_hypothesis TEXT,              -- AI 根因假设
  recommended_actions TEXT,                -- AI 处置建议（JSON array）
  dispatch_recommendation VARCHAR(100),    -- AI 推荐分派对象（工序组/角色/人名）
  raw_ai_response TEXT,                    -- AI 原始回复（调试用）
  status VARCHAR(20) DEFAULT 'pending',    -- pending/acknowledged/dismissed/acted
  acknowledged_by VARCHAR(50),             -- 确认人
  acknowledged_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_air_factory ON alert_intelligence_reviews(factory_id);
CREATE INDEX IF NOT EXISTS idx_air_source ON alert_intelligence_reviews(alert_source, status);
CREATE INDEX IF NOT EXISTS idx_air_created ON alert_intelligence_reviews(created_at DESC);
