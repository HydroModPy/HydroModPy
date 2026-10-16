"""The schema of ``.hmp/index.duckdb``, written by the indexer and read by ``Catalog``.

Why
---
The index is derived from the run and session directories. A schema change
is therefore not a migration but a full rebuild: the indexer writes this DDL
into a fresh staging database and publishes it in one rename. The reader
checks :data:`INDEX_SCHEMA_VERSION` in ``index_meta`` and refuses an index
written under another version with the command that rebuilds it.

What the index holds
--------------------
- ``cases``: one row per result directory that carries an ``outcome.json`` or
  a ``manifest.json``: runs, kept trials and sessions. Its ``status`` is what
  :func:`hydromodpy.results.outcome.effective_status` read at indexing time.
- ``attempts``: one row per attempt of a case, the current one included.
- ``simulations`` and its child tables: the sealed runs, read from their
  ``simulation.parquet``, ``manifest.json``, ``provenance.json`` and the
  payloads under ``tables.parquet/``. The label is computed at indexing and
  dated.
- ``sites``: one row per site named by a sealed run or a session.
- ``calibration_sessions``, ``calibration_phases``, ``calibration_iterations``:
  the sessions, read from ``session.json``, ``phases/*/session.json`` and
  ``trials.jsonl``.

The dimension tables (``solvers``, ``statuses``, ``flow_regimes``,
``mesh_topologies``) keep the codes the readers join on. ``timeseries``,
``budgets`` and the other Parquet views are not tables: the reader installs
them per connection over the payload files (:mod:`parquet_views`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    import duckdb

INDEX_SCHEMA_VERSION: Final[str] = "3"
"""Version of the index schema. A different value in a file means: rebuild it."""

INDEX_META_TABLE: Final[str] = "index_meta"
"""Key-value table carrying the schema version, the labelling build and the indexing stamp."""

META_SCHEMA_VERSION: Final[str] = "schema_version"
META_HYDROMODPY_VERSION: Final[str] = "hydromodpy_version"
META_INDEXED_AT: Final[str] = "indexed_at"
META_RULE_VERSION: Final[str] = "rule_version"
META_KNOWN_ISSUES_DIGEST: Final[str] = "known_issues_digest"

CASE_STATUSES: Final[tuple[str, ...]] = (
    "running",
    "completed",
    "partial",
    "failed",
    "aborted",
    "stale",
)
"""What ``cases.status`` may hold: the effective status of a directory at indexing time."""

CASE_KINDS: Final[tuple[str, ...]] = ("run", "trial", "session")
"""What a ``cases`` row is: a run, a kept trial of a session, or the session itself."""

_DIMENSIONS = """
CREATE TABLE index_meta (
    key   VARCHAR PRIMARY KEY,
    value VARCHAR
);

CREATE TABLE solvers (
    id        SMALLINT PRIMARY KEY,
    code      VARCHAR NOT NULL UNIQUE,
    category  VARCHAR NOT NULL
);

INSERT INTO solvers (id, code, category) VALUES
    (1, 'modflow6',     'distributed'),
    (2, 'modflow_nwt',  'distributed'),
    (3, 'boussinesq',   'integrated'),
    (4, 'gr4j',         'lumped'),
    (5, 'mt3dms',       'transport'),
    (6, 'modpath',      'particle_tracking');

CREATE TABLE statuses (
    id   SMALLINT PRIMARY KEY,
    code VARCHAR NOT NULL UNIQUE
);

INSERT INTO statuses (id, code) VALUES
    (1, 'pending'),
    (2, 'running'),
    (3, 'completed'),
    (4, 'partial'),
    (5, 'failed'),
    (6, 'aborted'),
    (7, 'resumed'),
    (8, 'trashed');

CREATE TABLE flow_regimes (
    id   SMALLINT PRIMARY KEY,
    code VARCHAR NOT NULL UNIQUE
);

INSERT INTO flow_regimes (id, code) VALUES
    (1, 'steady'),
    (2, 'transient'),
    (3, 'steady_then_transient');

CREATE TABLE mesh_topologies (
    id   SMALLINT PRIMARY KEY,
    code VARCHAR NOT NULL UNIQUE
);

INSERT INTO mesh_topologies (id, code) VALUES
    (1, 'structured_2d'),
    (2, 'structured_3d'),
    (3, 'unstructured_2d'),
    (4, 'unstructured_3d'),
    (5, 'lumped'),
    (6, 'network_1d');
"""

_CASES = f"""
CREATE TABLE sites (
    site              VARCHAR PRIMARY KEY,
    site_fingerprint  VARCHAR,
    label             VARCHAR,
    gauge             VARCHAR,
    uri               VARCHAR,
    x_outlet          DOUBLE,
    y_outlet          DOUBLE,
    crs               VARCHAR,
    area_km2          DOUBLE,
    dem_resolution_m  DOUBLE,
    n_cases           INTEGER NOT NULL,
    n_runs            INTEGER NOT NULL
);

CREATE TABLE cases (
    rel_dir          VARCHAR PRIMARY KEY,
    kind             VARCHAR NOT NULL CHECK (kind IN ({", ".join(repr(k) for k in CASE_KINDS)})),
    case_id          VARCHAR NOT NULL,
    site             VARCHAR,
    recipe           VARCHAR,
    project          VARCHAR,
    sim_id           VARCHAR,
    attempt          INTEGER,
    attempt_id       VARCHAR,
    status           VARCHAR NOT NULL CHECK (status IN ({", ".join(repr(s) for s in CASE_STATUSES)})),
    started_at       TIMESTAMPTZ,
    ended_at         TIMESTAMPTZ,
    host             VARCHAR,
    pid              INTEGER,
    step             VARCHAR,
    exit_code        INTEGER,
    signal           INTEGER,
    written_by       VARCHAR,
    error_type       VARCHAR,
    error_message    VARCHAR,
    heartbeat_at     TIMESTAMPTZ,
    source_key       VARCHAR NOT NULL,
    source_mtime_ns  BIGINT NOT NULL,
    indexed_at       TIMESTAMPTZ NOT NULL
);

CREATE INDEX ix_cases_case_id ON cases(case_id);
CREATE INDEX ix_cases_site    ON cases(site);
CREATE INDEX ix_cases_status  ON cases(status);

CREATE TABLE attempts (
    rel_dir        VARCHAR NOT NULL,
    attempt        INTEGER NOT NULL,
    attempt_id     VARCHAR NOT NULL,
    case_id        VARCHAR NOT NULL,
    sim_id         VARCHAR,
    status         VARCHAR NOT NULL,
    started_at     TIMESTAMPTZ,
    ended_at       TIMESTAMPTZ,
    host           VARCHAR,
    pid            INTEGER,
    exit_code      INTEGER,
    signal         INTEGER,
    written_by     VARCHAR,
    error_type     VARCHAR,
    error_message  VARCHAR
);

CREATE UNIQUE INDEX ux_attempts_rel_dir_attempt ON attempts(rel_dir, attempt_id);
"""

_SIMULATIONS = """
CREATE TABLE simulations (
    sim_id                        UUID PRIMARY KEY,
    name                          VARCHAR NOT NULL,
    name_stem                     VARCHAR NOT NULL,
    version_int                   INTEGER NOT NULL,
    project                       VARCHAR NOT NULL,
    site                          VARCHAR,
    site_fingerprint              VARCHAR,
    recipe                        VARCHAR,
    case_id                       VARCHAR NOT NULL,
    rel_dir                       VARCHAR NOT NULL,
    attempt                       INTEGER NOT NULL,
    attempt_id                    VARCHAR NOT NULL,
    solver_id                     SMALLINT NOT NULL REFERENCES solvers(id),
    status_id                     SMALLINT NOT NULL REFERENCES statuses(id),
    flow_regime_id                SMALLINT REFERENCES flow_regimes(id),
    mesh_topology_id              SMALLINT REFERENCES mesh_topologies(id),
    mesh_hash                     VARCHAR,
    n_cells                       INTEGER,
    n_layers                      INTEGER,
    n_timesteps                   INTEGER,
    crs_wkt                       VARCHAR,
    crs_epsg                      INTEGER,
    bbox_xmin                     DOUBLE,
    bbox_ymin                     DOUBLE,
    bbox_xmax                     DOUBLE,
    bbox_ymax                     DOUBLE,
    period_start                  TIMESTAMPTZ,
    period_end                    TIMESTAMPTZ,
    time_unit                     VARCHAR,
    config_toml                   VARCHAR,
    config_snapshot               JSON,
    config_hash                   VARCHAR,
    config_source                 VARCHAR,
    parent_sim_id                 UUID,
    lineage_kind                  VARCHAR,
    session_id                    VARCHAR,
    hydromodpy_version            VARCHAR NOT NULL,
    duration_s                    DOUBLE,
    started_at                    TIMESTAMPTZ,
    ended_at                      TIMESTAMPTZ,
    created_at                    TIMESTAMPTZ NOT NULL,
    description                   VARCHAR,
    scientific_objective          VARCHAR,
    contact_email                 VARCHAR,
    doi                           VARCHAR,
    budget_pct                    DOUBLE,
    budget_threshold_pct          DOUBLE,
    converged                     BOOLEAN,
    obs_coverage                  DOUBLE,
    score_window_start            DATE,
    score_window_end              DATE,
    n_samples                     BIGINT,
    calibrated_by_session_id      VARCHAR,
    calibrated_by_phase           VARCHAR,
    calibrated_by_trial           BIGINT,
    calibrated_by_session_status  VARCHAR,
    calibrated_by_window_start    DATE,
    calibrated_by_window_end      DATE,
    validities_failed             VARCHAR,
    fatal_failed                  BOOLEAN NOT NULL,
    bounds_hit                    VARCHAR,
    code_reproducible             BOOLEAN,
    nse                           DOUBLE,
    nse_window_start              DATE,
    nse_window_end                DATE,
    nse_n                         BIGINT,
    nse_station                   VARCHAR,
    nse_variable                  VARCHAR,
    metric_rule_version           VARCHAR,
    objective_name                VARCHAR,
    objective_value               DOUBLE,
    objective_window_start        DATE,
    objective_window_end          DATE,
    label                         VARCHAR NOT NULL
                                  CHECK (label IN ('exploratory', 'calibrated', 'evaluated', 'failed')),
    label_date                    DATE NOT NULL,
    rule_version                  VARCHAR NOT NULL,
    label_reasons                 VARCHAR,
    known_issues                  VARCHAR
);

CREATE UNIQUE INDEX ux_sim_rel_dir     ON simulations(rel_dir);
CREATE INDEX ix_sim_project            ON simulations(project);
CREATE INDEX ix_sim_site               ON simulations(site);
CREATE INDEX ix_sim_case_id            ON simulations(case_id);
CREATE INDEX ix_sim_status             ON simulations(status_id);
CREATE INDEX ix_sim_created_at         ON simulations(created_at DESC);
CREATE INDEX ix_sim_config_hash        ON simulations(config_hash);
CREATE INDEX ix_sim_name_stem          ON simulations(project, name_stem, version_int);
CREATE INDEX ix_sim_label              ON simulations(label);

CREATE TABLE parameters (
    sim_id           UUID NOT NULL,
    param_name       VARCHAR NOT NULL,
    zone_id          VARCHAR NOT NULL,
    value            DOUBLE,
    unit             VARCHAR,
    parameterization VARCHAR,
    valid_from       TIMESTAMPTZ,
    origin           VARCHAR NOT NULL,
    calibrated       BOOLEAN NOT NULL
);

CREATE INDEX ix_param_sim  ON parameters(sim_id);
CREATE INDEX ix_param_name ON parameters(param_name);

CREATE TABLE metrics (
    sim_id               UUID NOT NULL,
    station_id           VARCHAR,
    variable             VARCHAR,
    metric_name          VARCHAR NOT NULL,
    value                DOUBLE,
    n_samples            BIGINT,
    period_start         TIMESTAMPTZ,
    period_end           TIMESTAMPTZ,
    nse_window_start     DATE,
    nse_window_end       DATE,
    nse_n                BIGINT,
    metric_rule_version  VARCHAR
);

CREATE INDEX ix_metrics_sim_metric ON metrics(sim_id, metric_name);

CREATE TABLE runs_environment (
    sim_id                UUID PRIMARY KEY,
    python_version        VARCHAR,
    hydromodpy_version    VARCHAR,
    platform              VARCHAR,
    hostname              VARCHAR,
    user_name             VARCHAR,
    cpu_info              JSON,
    memory_gb             DOUBLE,
    git_commit            VARCHAR,
    git_dirty             BOOLEAN,
    project_git_commit    VARCHAR,
    solver_name           VARCHAR,
    solver_engine         VARCHAR,
    solver_execution_mode VARCHAR,
    solver_binary_path    VARCHAR,
    solver_binary_sha256  VARCHAR,
    solver_version_text   VARCHAR,
    conda_env_hash        VARCHAR,
    env_packages          JSON,
    rng_seed              BIGINT,
    recorded_at           TIMESTAMPTZ
);

CREATE TABLE provenance (
    sim_id         UUID NOT NULL,
    variable       VARCHAR NOT NULL,
    source_type    VARCHAR,
    source_ref     VARCHAR NOT NULL,
    source_sha256  VARCHAR,
    payload_sha256 VARCHAR,
    loader_name    VARCHAR,
    loader_version VARCHAR,
    fetched_at     TIMESTAMPTZ,
    period_start   TIMESTAMPTZ,
    period_end     TIMESTAMPTZ,
    n_records      BIGINT,
    stats          JSON,
    valid_from     TIMESTAMPTZ
);

CREATE INDEX ix_prov_sim ON provenance(sim_id);

CREATE TABLE tracked_files (
    sim_id         UUID NOT NULL,
    role           VARCHAR NOT NULL,
    category       VARCHAR NOT NULL,
    original_path  VARCHAR NOT NULL,
    canonical_path VARCHAR NOT NULL,
    sha256         VARCHAR NOT NULL,
    size_bytes     BIGINT,
    portable       BOOLEAN NOT NULL,
    recorded_at    TIMESTAMPTZ
);

CREATE INDEX ix_tracked_files_sim ON tracked_files(sim_id);
CREATE INDEX ix_tracked_files_sha ON tracked_files(sha256);

CREATE TABLE geographic_features (
    sim_id          UUID NOT NULL,
    feature_name    VARCHAR NOT NULL,
    geometry_kind   VARCHAR,
    crs_wkt         VARCHAR,
    geoparquet_path VARCHAR,
    properties      JSON
);

CREATE INDEX ix_geo_features_sim ON geographic_features(sim_id);

CREATE TABLE geographic_metadata (
    sim_id     UUID NOT NULL,
    key        VARCHAR NOT NULL,
    value      VARCHAR,
    value_type VARCHAR NOT NULL
);

CREATE INDEX ix_geo_metadata_sim ON geographic_metadata(sim_id);

CREATE TABLE tags (
    sim_id UUID NOT NULL,
    tag    VARCHAR NOT NULL
);

CREATE INDEX ix_tags_tag ON tags(tag);
CREATE INDEX ix_tags_sim ON tags(sim_id);

CREATE TABLE sim_notes (
    sim_id   UUID NOT NULL,
    note     VARCHAR NOT NULL,
    added_at VARCHAR,
    added_by VARCHAR
);

CREATE INDEX ix_sim_notes_sim ON sim_notes(sim_id);
"""

_SESSIONS = """
CREATE TABLE calibration_sessions (
    session_id             VARCHAR PRIMARY KEY,
    rel_dir                VARCHAR NOT NULL,
    site                   VARCHAR,
    case_id                VARCHAR NOT NULL,
    project                VARCHAR,
    config_hash            VARCHAR NOT NULL,
    hydromodpy_version     VARCHAR NOT NULL,
    method                 VARCHAR NOT NULL,
    search_space           JSON,
    objective_name         VARCHAR NOT NULL,
    objective_window_start DATE,
    objective_window_end   DATE,
    n_trials               INTEGER NOT NULL,
    best_trial             INTEGER,
    best_sim_id            VARCHAR,
    best_rel_dir           VARCHAR,
    best_objective         DOUBLE,
    status                 VARCHAR NOT NULL,
    started_at             TIMESTAMPTZ NOT NULL,
    ended_at               TIMESTAMPTZ,
    error_message          VARCHAR,
    root_search            JSON
);

CREATE UNIQUE INDEX ux_cal_session_rel_dir ON calibration_sessions(rel_dir);
CREATE INDEX ix_cal_session_case ON calibration_sessions(case_id);

CREATE TABLE calibration_phases (
    session_id     VARCHAR NOT NULL,
    phase_id       VARCHAR NOT NULL,
    name           VARCHAR NOT NULL,
    phase_index    INTEGER NOT NULL,
    status         VARCHAR NOT NULL,
    frozen         JSON,
    best_trial     INTEGER,
    best_sim_id    VARCHAR,
    best_objective DOUBLE,
    restarts       INTEGER NOT NULL
);

CREATE INDEX ix_cal_phases_session ON calibration_phases(session_id);

CREATE TABLE calibration_iterations (
    session_id   VARCHAR NOT NULL,
    trial        INTEGER NOT NULL,
    phase        VARCHAR NOT NULL,
    restart      INTEGER NOT NULL,
    params       JSON NOT NULL,
    params_hash  VARCHAR,
    objective    DOUBLE,
    metrics      JSON,
    status       VARCHAR NOT NULL,
    started_at   TIMESTAMPTZ NOT NULL,
    ended_at     TIMESTAMPTZ,
    sim_id       VARCHAR,
    rel_dir      VARCHAR
);

CREATE UNIQUE INDEX ux_cal_iter_session_trial ON calibration_iterations(session_id, trial);
CREATE INDEX ix_cal_iter_sim ON calibration_iterations(sim_id);
"""

INDEX_DDL: Final[str] = _DIMENSIONS + _CASES + _SIMULATIONS + _SESSIONS
"""The whole DDL of an index, applied to an empty database."""

SIMULATION_CHILD_TABLES: Final[tuple[str, ...]] = (
    "parameters",
    "metrics",
    "provenance",
    "runs_environment",
    "tracked_files",
    "geographic_features",
    "geographic_metadata",
    "tags",
    "sim_notes",
)
"""Tables keyed by ``sim_id`` that go with a ``simulations`` row."""

SESSION_CHILD_TABLES: Final[tuple[str, ...]] = ("calibration_phases", "calibration_iterations")
"""Tables keyed by ``session_id`` that go with a ``calibration_sessions`` row."""


def create_index_schema(connection: duckdb.DuckDBPyConnection, *, hydromodpy_version: str) -> None:
    """Apply the DDL to an empty database and stamp its schema version."""
    for statement in INDEX_DDL.split(";"):
        text = statement.strip()
        if text:
            connection.execute(text)
    connection.execute(
        f"INSERT INTO {INDEX_META_TABLE} (key, value) VALUES (?, ?), (?, ?)",
        [
            META_SCHEMA_VERSION,
            INDEX_SCHEMA_VERSION,
            META_HYDROMODPY_VERSION,
            hydromodpy_version,
        ],
    )


def read_index_schema_version(connection: duckdb.DuckDBPyConnection) -> str | None:
    """Return the schema version an index declares, or ``None`` for a file without one."""
    present = connection.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?",
        [INDEX_META_TABLE],
    ).fetchone()
    if not present or int(present[0]) == 0:
        return None
    row = connection.execute(
        f"SELECT value FROM {INDEX_META_TABLE} WHERE key = ?", [META_SCHEMA_VERSION]
    ).fetchone()
    return None if row is None else str(row[0])


__all__ = [
    "CASE_KINDS",
    "CASE_STATUSES",
    "INDEX_DDL",
    "INDEX_META_TABLE",
    "INDEX_SCHEMA_VERSION",
    "META_HYDROMODPY_VERSION",
    "META_INDEXED_AT",
    "META_KNOWN_ISSUES_DIGEST",
    "META_RULE_VERSION",
    "META_SCHEMA_VERSION",
    "SESSION_CHILD_TABLES",
    "SIMULATION_CHILD_TABLES",
    "create_index_schema",
    "read_index_schema_version",
]
