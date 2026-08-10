-- 064: APS 日期级节假日/补班日历
-- 每周班次继续使用 aps_work_calendars；本表用于春节、法定节假日、补休和企业特殊休息日。

CREATE TABLE IF NOT EXISTS aps_holidays (
  id VARCHAR(36) PRIMARY KEY,
  factory_id VARCHAR(50) NOT NULL,
  calendar_code VARCHAR(80) NOT NULL,
  year INT NOT NULL,
  holiday_date DATE NOT NULL,
  holiday_name VARCHAR(150) NOT NULL,
  holiday_type VARCHAR(30) NOT NULL DEFAULT 'legal',
  is_working_day BOOLEAN NOT NULL DEFAULT FALSE,
  source_name VARCHAR(200),
  source_url VARCHAR(500),
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_by VARCHAR(50),
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_aps_holiday_factory_date UNIQUE (factory_id, holiday_date)
);
CREATE INDEX IF NOT EXISTS idx_aps_holiday_factory_year
  ON aps_holidays(factory_id, year);
