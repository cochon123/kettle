-- Kettle cloud schema (TimescaleDB / Tiger Data).
-- Note what is NOT here: there is no table for raw power readings.
-- Raw watts never leave the home; the cloud only ever receives appliance events.

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS homes (
    id          text PRIMARY KEY,
    person      text NOT NULL,
    pronoun     text NOT NULL DEFAULT 'they',
    tz          text NOT NULL DEFAULT 'America/Edmonton',
    paused_until timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- Appliance events detected at the edge ("kettle on", "kettle cycle 94 s").
CREATE TABLE IF NOT EXISTS events (
    time        timestamptz NOT NULL,
    home_id     text NOT NULL,
    channel     text NOT NULL,
    kind        text NOT NULL,            -- 'on' | 'cycle'
    label       text NOT NULL,            -- kettle, microwave, tv, furnace_blower, ...
    human       boolean NOT NULL,
    dp_w        real,
    duration_s  real,
    confidence  real,
    detail      jsonb
);
SELECT create_hypertable('events', by_range('time', INTERVAL '7 days'), if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS events_home_time ON events (home_id, time DESC);

-- Grid + weather context (AESO, ECCC) for cold mode and the post-event story.
CREATE TABLE IF NOT EXISTS context_readings (
    time    timestamptz NOT NULL,
    source  text NOT NULL,                -- 'aeso_csd' | 'eccc'
    metric  text NOT NULL,                -- 'ail_mw', 'temp_c', ...
    value   double precision
);
SELECT create_hypertable('context_readings', by_range('time', INTERVAL '30 days'), if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS escalations (
    id          bigint PRIMARY KEY,
    home_id     text NOT NULL,
    started_at  timestamptz NOT NULL,
    reason      text NOT NULL,
    step        text NOT NULL,
    resolution  text,
    resolved_at timestamptz,
    log         jsonb NOT NULL DEFAULT '[]'
);

-- Rhythm baselines: the first human activity of each "Kettle day" (04:00 -> 04:00 local),
-- maintained incrementally by TimescaleDB as events arrive.
CREATE MATERIALIZED VIEW IF NOT EXISTS daily_activity
WITH (timescaledb.continuous) AS
SELECT home_id,
       time_bucket(INTERVAL '1 day', time, 'America/Edmonton', "offset" => INTERVAL '4 hours') AS day,
       min(time) FILTER (WHERE human)                       AS first_human,
       count(*)  FILTER (WHERE human)                       AS human_events,
       count(*)  FILTER (WHERE label = 'kettle' AND kind = 'on') AS kettle_uses,
       count(*)  FILTER (WHERE label = 'furnace_blower' AND kind = 'cycle') AS blower_cycles,
       sum(duration_s) FILTER (WHERE label = 'furnace_blower' AND kind = 'cycle') AS blower_seconds
FROM events
GROUP BY home_id, day
WITH NO DATA;

SELECT add_continuous_aggregate_policy('daily_activity',
    start_offset => INTERVAL '35 days', end_offset => NULL, schedule_interval => INTERVAL '5 minutes',
    if_not_exists => TRUE);

-- Hourly activity profile, used for the "rhythm band" drawn in the apps.
CREATE MATERIALIZED VIEW IF NOT EXISTS hourly_activity
WITH (timescaledb.continuous) AS
SELECT home_id,
       time_bucket(INTERVAL '1 hour', time) AS hour,
       count(*) FILTER (WHERE human) AS human_events
FROM events
GROUP BY home_id, hour
WITH NO DATA;

SELECT add_continuous_aggregate_policy('hourly_activity',
    start_offset => INTERVAL '35 days', end_offset => NULL, schedule_interval => INTERVAL '5 minutes',
    if_not_exists => TRUE);

-- Keep events for 13 months (seasonal baselines), then drop them automatically.
SELECT add_retention_policy('events', INTERVAL '395 days', if_not_exists => TRUE);
SELECT add_retention_policy('context_readings', INTERVAL '395 days', if_not_exists => TRUE);
