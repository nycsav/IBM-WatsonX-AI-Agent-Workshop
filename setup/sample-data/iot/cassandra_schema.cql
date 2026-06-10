-- ============================================================================
-- IoT Cassandra Schema — Operational / hot-window only
--
-- Cassandra holds: current device state, last 24h of sensor readings,
-- open alerts, recent (last 7d) device events, current device→site topology.
-- Everything older / aggregated / external lives in Iceberg.
-- ============================================================================

CREATE KEYSPACE IF NOT EXISTS iot
WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1};

USE iot;

-- ----------------------------------------------------------------------------
-- device_state_current — live device state
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS device_state_current (
    device_id             UUID PRIMARY KEY,
    device_type           TEXT,          -- sensor | gateway | actuator | camera
    device_class          TEXT,          -- temperature | humidity | pressure | vibration | energy | presence
    model                 TEXT,
    firmware_version      TEXT,
    status                TEXT,          -- online | offline | degraded | maintenance
    last_heartbeat        TIMESTAMP,
    last_reading_value    DECIMAL,
    battery_percent       INT,
    signal_strength_dbm   INT,
    site_id               TEXT,
    zone                  TEXT,
    installed_at          TIMESTAMP,
    updated_at            TIMESTAMP
);
CREATE INDEX IF NOT EXISTS devices_site_idx ON device_state_current (site_id);
CREATE INDEX IF NOT EXISTS devices_status_idx ON device_state_current (status);

-- ----------------------------------------------------------------------------
-- readings_hot — last 24h of sensor readings (high-cardinality, per-device)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS readings_hot (
    device_id             UUID,
    reading_bucket_hour   TIMESTAMP,     -- rounded to the hour (for partition pruning)
    reading_timestamp     TIMESTAMP,
    metric_name           TEXT,
    metric_value          DECIMAL,
    unit                  TEXT,
    quality_code          TEXT,          -- good | suspect | bad
    PRIMARY KEY ((device_id, reading_bucket_hour), reading_timestamp)
) WITH CLUSTERING ORDER BY (reading_timestamp DESC);

-- ----------------------------------------------------------------------------
-- alerts_open — unacknowledged active alerts
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alerts_open (
    device_id             UUID,
    alert_id              UUID,
    raised_at             TIMESTAMP,
    severity              TEXT,          -- low | medium | high | critical
    alert_type            TEXT,          -- threshold | anomaly | offline | battery_low
    metric_name           TEXT,
    metric_value          DECIMAL,
    threshold_value       DECIMAL,
    site_id               TEXT,
    acknowledged          BOOLEAN,
    PRIMARY KEY (device_id, alert_id)
) WITH CLUSTERING ORDER BY (alert_id DESC);

-- ----------------------------------------------------------------------------
-- device_events_recent — state changes, commands in last 7 days
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS device_events_recent (
    device_id             UUID,
    event_date            DATE,
    event_id              TIMEUUID,
    event_type            TEXT,          -- boot | shutdown | config_change | command | error
    event_source          TEXT,          -- cloud | local | user
    payload               TEXT,
    created_at            TIMESTAMP,
    PRIMARY KEY ((device_id, event_date), event_id)
) WITH CLUSTERING ORDER BY (event_id DESC);

-- ----------------------------------------------------------------------------
-- topology_current — device → gateway → site associations right now
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS topology_current (
    site_id               TEXT,
    gateway_id            UUID,
    device_id             UUID,
    zone                  TEXT,
    installed_at          TIMESTAMP,
    ip_address            TEXT,
    PRIMARY KEY (site_id, gateway_id, device_id)
);
