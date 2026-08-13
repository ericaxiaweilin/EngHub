-- 086: PMC 数据口径补强与产能主数据推导
--
-- This migration only adds traceability fields and derives capacity master
-- data from existing station master values.  It does not create orders, POs,
-- ECNs or inventory movements.

ALTER TABLE sales_orders ADD COLUMN IF NOT EXISTS actual_ship_date DATE;
ALTER TABLE sales_orders ADD COLUMN IF NOT EXISTS shipped_qty INTEGER;
ALTER TABLE sales_orders ADD COLUMN IF NOT EXISTS source_system VARCHAR(50);

ALTER TABLE station_capacity ADD COLUMN IF NOT EXISTS source VARCHAR(40) NOT NULL DEFAULT 'manual';
ALTER TABLE station_capacity ADD COLUMN IF NOT EXISTS source_note TEXT;
ALTER TABLE station_capacity ADD COLUMN IF NOT EXISTS verified_at TIMESTAMP;

-- The station master already stores daily output (capacity) and hourly
-- throughput (capacity_per_hour).  Derive the implied available hours per
-- day, keep station_code as the resource key used by routings, and never
-- overwrite a manually maintained station_capacity row.
INSERT INTO station_capacity (
    id,
    factory_id,
    station_id,
    available_hours_per_day,
    efficiency_rate,
    setup_time_minutes,
    max_concurrent_orders,
    source,
    source_note,
    verified_at,
    is_active,
    created_at,
    updated_at
)
SELECT
    gen_random_uuid()::text,
    s.factory_id,
    s.station_code,
    ROUND((s.capacity::numeric / NULLIF(s.capacity_per_hour, 0)), 2)::double precision,
    1.0,
    30,
    1,
    'derived_station_master',
    '由 stations.capacity / stations.capacity_per_hour 推导；需业务确认班次、效率和维护窗口后可改为 manual。',
    NOW(),
    TRUE,
    NOW(),
    NOW()
FROM stations s
WHERE COALESCE(s.status, 'active') = 'active'
  AND COALESCE(s.station_code, '') <> ''
  AND COALESCE(s.capacity, 0) > 0
  AND COALESCE(s.capacity_per_hour, 0) > 0
ON CONFLICT (factory_id, station_id) DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_pmc_sales_orders_ship_date
    ON sales_orders(factory_id, actual_ship_date);
CREATE INDEX IF NOT EXISTS idx_pmc_station_capacity_source
    ON station_capacity(factory_id, source);
