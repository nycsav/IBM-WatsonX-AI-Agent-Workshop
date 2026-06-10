-- ============================================================================
-- IoT Iceberg Schema — Historical, analytical, and external
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS iceberg_data.iot;
USE iceberg_data.iot;

-- ----------------------------------------------------------------------------
-- readings_archive — sensor readings older than 24h
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS readings_archive (
    device_id             VARCHAR,
    reading_date          DATE,
    reading_year          INTEGER,
    reading_month         INTEGER,
    reading_timestamp     TIMESTAMP,
    device_class          VARCHAR,
    site_id               VARCHAR,
    metric_name           VARCHAR,
    metric_value          DECIMAL(12,4),
    unit                  VARCHAR,
    quality_code          VARCHAR
)
WITH (
    format = 'PARQUET',
    partitioning = ARRAY['reading_year', 'reading_month']
);

-- ----------------------------------------------------------------------------
-- hourly_aggregates — per-device per-metric rollup (min/max/avg/p95)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hourly_aggregates (
    device_id             VARCHAR,
    site_id               VARCHAR,
    device_class          VARCHAR,
    metric_name           VARCHAR,
    hour_start            TIMESTAMP,
    hour_year             INTEGER,
    hour_month            INTEGER,
    sample_count          INTEGER,
    min_value             DECIMAL(12,4),
    max_value             DECIMAL(12,4),
    avg_value             DECIMAL(12,4),
    p95_value             DECIMAL(12,4),
    stddev_value          DECIMAL(12,4)
)
WITH (
    format = 'PARQUET',
    partitioning = ARRAY['hour_year', 'hour_month']
);

-- ----------------------------------------------------------------------------
-- daily_site_summary — per-site rollup across all devices
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS daily_site_summary (
    site_id               VARCHAR,
    summary_date          DATE,
    summary_year          INTEGER,
    summary_month         INTEGER,
    device_count          INTEGER,
    devices_online_avg    DECIMAL(6,2),
    devices_degraded_avg  DECIMAL(6,2),
    readings_received     BIGINT,
    alerts_raised         INTEGER,
    alerts_critical       INTEGER,
    uptime_pct            DECIMAL(5,2),
    avg_battery_pct       DECIMAL(5,2)
)
WITH (
    format = 'PARQUET',
    partitioning = ARRAY['summary_year', 'summary_month']
);

-- ----------------------------------------------------------------------------
-- failure_history — labeled device-failure events (training set for ML)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS failure_history (
    failure_id            VARCHAR,
    device_id             VARCHAR,
    site_id               VARCHAR,
    device_class          VARCHAR,
    failure_timestamp     TIMESTAMP,
    failure_year          INTEGER,
    failure_month         INTEGER,
    failure_type          VARCHAR,       -- hardware | firmware | network | power | sensor_drift
    root_cause            VARCHAR,
    downtime_minutes      INTEGER,
    days_since_install    INTEGER,
    firmware_version      VARCHAR,
    predicted_12h_prior   BOOLEAN        -- did our model predict it 12h in advance?
)
WITH (
    format = 'PARQUET',
    partitioning = ARRAY['failure_year']
);

-- ----------------------------------------------------------------------------
-- firmware_deployment_history — which firmware ran on which device when
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS firmware_deployment_history (
    device_id             VARCHAR,
    firmware_version      VARCHAR,
    deployed_at           TIMESTAMP,
    deployed_year         INTEGER,
    retired_at            TIMESTAMP,
    rollout_wave          VARCHAR,       -- canary | early | general
    deployed_by           VARCHAR,
    success               BOOLEAN,
    rollback_reason       VARCHAR
)
WITH (
    format = 'PARQUET',
    partitioning = ARRAY['deployed_year']
);

-- ----------------------------------------------------------------------------
-- maintenance_windows — planned + unplanned outage history
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS maintenance_windows (
    window_id             VARCHAR,
    site_id               VARCHAR,
    window_start          TIMESTAMP,
    window_end            TIMESTAMP,
    window_year           INTEGER,
    window_month          INTEGER,
    window_type           VARCHAR,       -- planned | unplanned
    reason                VARCHAR,
    devices_affected      INTEGER,
    downtime_minutes      INTEGER
)
WITH (
    format = 'PARQUET',
    partitioning = ARRAY['window_year', 'window_month']
);

-- ----------------------------------------------------------------------------
-- weather_by_location — external weather feed per site (hourly)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS weather_by_location (
    site_id               VARCHAR,
    observation_time      TIMESTAMP,
    observation_year      INTEGER,
    observation_month     INTEGER,
    temperature_c         DECIMAL(5,2),
    humidity_pct          DECIMAL(5,2),
    pressure_hpa          DECIMAL(7,2),
    wind_speed_mps        DECIMAL(5,2),
    precipitation_mm      DECIMAL(5,2),
    conditions            VARCHAR,       -- clear | cloudy | rain | snow | storm
    source                VARCHAR        -- external feed name
)
WITH (
    format = 'PARQUET',
    partitioning = ARRAY['observation_year', 'observation_month']
);
