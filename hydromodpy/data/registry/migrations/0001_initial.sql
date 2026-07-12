-- =====================================================================
-- HydroModPy V1 data cache DDL (initial migration)
--
-- Per-workspace DuckDB cache shared by every project under the same
-- workspace root. Holds relational metadata about ingested inputs
-- (rasters, time series, station catalogues) and the artefacts produced
-- by the data adapters.
--
-- Source of truth: reports_db/99_target_architecture.md sections 2.2 and
-- reports_db/01_inventory.md (cache layout).
--
-- Foreign keys: declarative FK to dim tables only. Per-sim/per-artifact
-- references stay logical (no FK) until the runner moves to Postgres
-- (V2).
-- =====================================================================

-- =====================================================================
-- Sequences
--   ``CREATE SEQUENCE IF NOT EXISTS`` is intentional: the runner replays
--   ``0001_initial.sql`` against a fresh database, so creation is always
--   the first time. The ``IF NOT EXISTS`` clause keeps the migration
--   replay-safe for development workflows that delete tables but reuse
--   the same DuckDB file.
-- =====================================================================

CREATE SEQUENCE IF NOT EXISTS entries_seq START 1;
CREATE SEQUENCE IF NOT EXISTS api_coverage_seq START 1;
CREATE SEQUENCE IF NOT EXISTS artifacts_seq START 1;
CREATE SEQUENCE IF NOT EXISTS provenance_seq START 1;
CREATE SEQUENCE IF NOT EXISTS coverage_seq START 1;
CREATE SEQUENCE IF NOT EXISTS failures_seq START 1;
CREATE SEQUENCE IF NOT EXISTS validation_reports_seq START 1;

-- =====================================================================
-- entries (cached input artefacts indexed by variable + source)
-- =====================================================================

CREATE TABLE entries (
    id             INTEGER PRIMARY KEY DEFAULT nextval('entries_seq'),
    variable       VARCHAR NOT NULL,
    source         VARCHAR NOT NULL,
    station_id     VARCHAR,
    bbox_xmin      DOUBLE,
    bbox_ymin      DOUBLE,
    bbox_xmax      DOUBLE,
    bbox_ymax      DOUBLE,
    crs            VARCHAR,
    date_start     TIMESTAMPTZ,
    date_end       TIMESTAMPTZ,
    frequency      VARCHAR,
    unit           VARCHAR,
    source_unit    VARCHAR,
    file_path      TEXT NOT NULL,
    file_mtime     DOUBLE,
    sha256         VARCHAR,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    is_custom      BOOLEAN NOT NULL DEFAULT FALSE,
    fetch_metadata JSON,
    -- Logical cache identity: the writer dedups/upserts on this triple, so a
    -- UNIQUE backstop keeps DuckDB from accumulating duplicate rows for the
    -- same input if the existence check ever races or is bypassed.
    UNIQUE (variable, source, station_id)
);

CREATE INDEX ix_entries_bbox
    ON entries(bbox_xmin, bbox_ymin, bbox_xmax, bbox_ymax);
CREATE INDEX ix_entries_sha256
    ON entries(sha256);

-- =====================================================================
-- api_coverage (advertised remote API coverage per variable)
-- =====================================================================

CREATE TABLE api_coverage (
    id          INTEGER PRIMARY KEY DEFAULT nextval('api_coverage_seq'),
    variable    VARCHAR NOT NULL,
    source      VARCHAR NOT NULL,
    country     VARCHAR,
    description VARCHAR,
    bbox_xmin   DOUBLE,
    bbox_ymin   DOUBLE,
    bbox_xmax   DOUBLE,
    bbox_ymax   DOUBLE
);

-- =====================================================================
-- artifacts (file-level metadata derived from entries)
-- =====================================================================

CREATE TABLE artifacts (
    id            INTEGER PRIMARY KEY DEFAULT nextval('artifacts_seq'),
    sim_id        VARCHAR,
    variable      VARCHAR,
    artifact_type VARCHAR NOT NULL,
    path          TEXT NOT NULL,
    sha256        VARCHAR,
    size_bytes    BIGINT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
);

CREATE INDEX ix_artifacts_sim    ON artifacts(sim_id);
CREATE INDEX ix_artifacts_sha256 ON artifacts(sha256);

-- =====================================================================
-- provenance (source tracking for each cached artifact)
-- =====================================================================

CREATE TABLE provenance (
    id              INTEGER PRIMARY KEY DEFAULT nextval('provenance_seq'),
    artifact_id     INTEGER,
    variable        VARCHAR,
    source          VARCHAR,
    input_hash      VARCHAR,
    tool_name       VARCHAR,
    tool_version    VARCHAR,
    parameters_json JSON,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
);

CREATE INDEX ix_provenance_artifact ON provenance(artifact_id);

-- =====================================================================
-- stations (station metadata, composite PK)
-- =====================================================================

CREATE TABLE stations (
    station_id  VARCHAR NOT NULL,
    variable    VARCHAR NOT NULL,
    source      VARCHAR,
    lat         DOUBLE,
    lon         DOUBLE,
    z           DOUBLE,
    name        VARCHAR,
    first_valid VARCHAR,
    last_valid  VARCHAR,
    PRIMARY KEY (station_id, variable)
);

-- =====================================================================
-- coverage (advertised spatio-temporal coverage of a variable)
-- =====================================================================

CREATE TABLE coverage (
    id           INTEGER PRIMARY KEY DEFAULT nextval('coverage_seq'),
    variable     VARCHAR NOT NULL,
    source       VARCHAR,
    region_wkt   TEXT,
    period_start VARCHAR,
    period_end   VARCHAR,
    n_stations   INTEGER
);

-- =====================================================================
-- failures (adapter-side failures, kept for cache observability)
-- =====================================================================

CREATE TABLE failures (
    id          INTEGER PRIMARY KEY DEFAULT nextval('failures_seq'),
    variable    VARCHAR,
    source_ref  VARCHAR,
    error_type  VARCHAR NOT NULL,
    message     TEXT,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
);

CREATE INDEX ix_failures_variable ON failures(variable);

-- =====================================================================
-- validation_reports (pandera output, branched by C.3 in V1)
-- =====================================================================

CREATE TABLE validation_reports (
    id           INTEGER PRIMARY KEY DEFAULT nextval('validation_reports_seq'),
    artifact_id  INTEGER,
    schema_name  VARCHAR NOT NULL,
    passed       BOOLEAN NOT NULL,
    errors_json  JSON,
    validated_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
);

CREATE INDEX ix_validation_artifact ON validation_reports(artifact_id);

-- =====================================================================
-- v_entries_summary (one row per (variable, source) with counts and
-- temporal bounds; used by ``hmp data ls``)
-- =====================================================================

CREATE VIEW v_entries_summary AS
SELECT
    variable,
    source,
    COUNT(*)              AS n_entries,
    COUNT(DISTINCT station_id) AS n_stations,
    MIN(date_start)       AS earliest,
    MAX(date_end)         AS latest,
    SUM(CASE WHEN is_custom THEN 1 ELSE 0 END) AS n_custom
FROM entries
GROUP BY variable, source;
