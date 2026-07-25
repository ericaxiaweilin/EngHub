-- 037_environment_readings.sql
-- 车间环境监测数据表（预留 IoT 传感器接入）
-- 当前「环」数据源为公共气象 API（Open-Meteo），此表用于未来接入
-- 车间内部温湿度传感器、粉尘、噪声等 IoT 设备的实时读数。

CREATE TABLE IF NOT EXISTS environment_readings (
    id              SERIAL PRIMARY KEY,
    factory_id      VARCHAR(64) NOT NULL DEFAULT 'FAC_ELEC_DEMO_2026',
    station_id      VARCHAR(64),                          -- 关联工位（可选）
    sensor_id       VARCHAR(128),                         -- IoT 传感器编号
    reading_type    VARCHAR(32) NOT NULL DEFAULT 'weather', -- weather / iot_sensor
    temperature_c   NUMERIC(5,1),                         -- 温度 °C
    humidity_pct    NUMERIC(5,1),                         -- 相对湿度 %
    noise_db        NUMERIC(5,1),                         -- 噪声 dB
    dust_ug_m3      NUMERIC(8,2),                         -- 粉尘浓度 µg/m³
    wind_speed_kmh  NUMERIC(5,1),                         -- 风速 km/h
    pressure_hpa    NUMERIC(7,2),                         -- 气压 hPa
    precipitation_mm NUMERIC(6,2),                        -- 降水量 mm
    extra_json      JSONB DEFAULT '{}',                   -- 扩展字段
    measured_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),   -- 测量时间
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_env_readings_factory ON environment_readings(factory_id);
CREATE INDEX IF NOT EXISTS idx_env_readings_time ON environment_readings(measured_at DESC);
CREATE INDEX IF NOT EXISTS idx_env_readings_type ON environment_readings(reading_type);

COMMENT ON TABLE environment_readings IS '车间环境监测读数（IoT传感器 + 公共气象）';
COMMENT ON COLUMN environment_readings.reading_type IS 'weather=公共气象API, iot_sensor=车间IoT传感器';
