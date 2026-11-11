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

Four tables copy a Parquet table of the run: ``simulations``
(``simulation.parquet``), ``parameters``, ``metrics`` and ``provenance``. Their
DDL is not written here but read off those schemas by :func:`table_ddl`: one
column per Arrow field, in the schema order, with the DuckDB type of
:data:`ARROW_TO_DUCKDB` and ``NOT NULL`` where the field is not nullable. A
:class:`MirroredTable` only says what the index does differently: a column
typed otherwise, a code joined on a dimension table, a field left out, and the
columns the index alone carries. A column added to a Parquet schema reaches
the index with no line here.

``cases.bytes`` is the size of the directory on disk when it was indexed.

The dimension tables (``solvers``, ``statuses``, ``flow_regimes``,
``mesh_topologies``) hold the codes the readers join on. ``solvers`` and
``mesh_topologies`` start empty: every row comes from the run itself, the
category of a solver read off its manifest either way. ``statuses`` and
``flow_regimes`` keep their seed: closed vocabularies of the pipeline, and no
name in them is a backend. ``timeseries``, ``budgets`` and the other Parquet
views are not tables: the reader installs them per connection over the payload
files (:mod:`parquet_views`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

import pyarrow as pa

from hydromodpy.results.storage.parquet_schemas import (
    METRICS_SCHEMA,
    PARAMETERS_SCHEMA,
    PROVENANCE_SCHEMA,
    SIMULATION_SCHEMA,
)

if TYPE_CHECKING:
    import duckdb

INDEX_SCHEMA_VERSION: Final[str] = "13"
"""Version of the index schema. A different value in a file means: rebuild it."""

INDEX_META_TABLE: Final[str] = "index_meta"
"""Key-value table carrying the schema version, the labeling build and the indexing stamp."""

META_SCHEMA_VERSION: Final[str] = "schema_version"
META_HYDROMODPY_VERSION: Final[str] = "hydromodpy_version"
META_INDEXED_AT: Final[str] = "indexed_at"
META_RULE_VERSION: Final[str] = "rule_version"
META_KNOWN_ISSUES_DIGEST: Final[str] = "known_issues_digest"

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
    status           VARCHAR NOT NULL,
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
    indexed_at       TIMESTAMPTZ NOT NULL,
    bytes            BIGINT NOT NULL
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

_SIMULATIONS_TEMPLATE = """
{simulations}

CREATE UNIQUE INDEX ux_sim_rel_dir     ON simulations(rel_dir);
CREATE INDEX ix_sim_project            ON simulations(project);
CREATE INDEX ix_sim_site               ON simulations(site);
CREATE INDEX ix_sim_case_id            ON simulations(case_id);
CREATE INDEX ix_sim_status             ON simulations(status_id);
CREATE INDEX ix_sim_created_at         ON simulations(created_at DESC);
CREATE INDEX ix_sim_solution_key       ON simulations(solution_key);
CREATE INDEX ix_sim_name_stem          ON simulations(project, name_stem, version_int);
CREATE INDEX ix_sim_label              ON simulations(label);

{parameters}

CREATE INDEX ix_param_sim  ON parameters(sim_id);
CREATE INDEX ix_param_name ON parameters(param_name);

{metrics}

CREATE INDEX ix_metrics_sim_metric ON metrics(sim_id, metric, window_name);

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

{provenance}

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
    case_id                VARCHAR NOT NULL,
    project                VARCHAR,
    config_hash            VARCHAR NOT NULL,
    hydromodpy_version     VARCHAR NOT NULL,
    method                 VARCHAR NOT NULL,
    sites                  JSON NOT NULL,
    bounds                 JSON,
    cost_name              VARCHAR NOT NULL,
    windows                JSON,
    n_trials               INTEGER NOT NULL,
    best_trial             INTEGER,
    best_cost              DOUBLE,
    status                 VARCHAR NOT NULL,
    started_at             TIMESTAMPTZ NOT NULL,
    ended_at               TIMESTAMPTZ,
    error_message          VARCHAR,
    root_search            JSON,
    widths                 JSON
);

CREATE UNIQUE INDEX ux_cal_session_rel_dir ON calibration_sessions(rel_dir);
CREATE INDEX ix_cal_session_case ON calibration_sessions(case_id);

CREATE TABLE calibration_session_cases (
    session_id   VARCHAR NOT NULL,
    case_id      VARCHAR NOT NULL,
    site         VARCHAR,
    config_hash  VARCHAR NOT NULL,
    best_sim_id  VARCHAR,
    best_rel_dir VARCHAR,
    best_cost    DOUBLE
);

CREATE UNIQUE INDEX ux_cal_session_case ON calibration_session_cases(session_id, case_id);
CREATE INDEX ix_cal_session_case_site ON calibration_session_cases(site);

CREATE TABLE calibration_phases (
    session_id  VARCHAR NOT NULL,
    phase_id    VARCHAR NOT NULL,
    name        VARCHAR NOT NULL,
    phase_index INTEGER NOT NULL,
    status      VARCHAR NOT NULL,
    frozen      JSON,
    windows     JSON,
    best_trial  INTEGER,
    best_cost   DOUBLE,
    restarts    INTEGER NOT NULL
);

CREATE INDEX ix_cal_phases_session ON calibration_phases(session_id);

CREATE TABLE calibration_iterations (
    session_id VARCHAR NOT NULL,
    trial      INTEGER NOT NULL,
    phase      VARCHAR NOT NULL,
    restart    INTEGER NOT NULL,
    params     JSON NOT NULL,
    cost       DOUBLE,
    status     VARCHAR NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at   TIMESTAMPTZ
);

CREATE UNIQUE INDEX ux_cal_iter_session_trial ON calibration_iterations(session_id, trial);

CREATE TABLE calibration_trial_cases (
    session_id  VARCHAR NOT NULL,
    trial       INTEGER NOT NULL,
    case_id     VARCHAR NOT NULL,
    cost        DOUBLE,
    status      VARCHAR NOT NULL,
    params_hash VARCHAR,
    from_cache  BOOLEAN NOT NULL,
    components  JSON,
    sim_id      VARCHAR,
    rel_dir     VARCHAR
);

CREATE UNIQUE INDEX ux_cal_trial_case ON calibration_trial_cases(session_id, trial, case_id);
CREATE INDEX ix_cal_trial_case_sim ON calibration_trial_cases(sim_id);
"""

ARROW_TO_DUCKDB: Final[Mapping[str, str]] = MappingProxyType(
    {
        "string": "VARCHAR",
        "double": "DOUBLE",
        "float": "FLOAT",
        "int16": "SMALLINT",
        "int32": "INTEGER",
        "int64": "BIGINT",
        "bool": "BOOLEAN",
        "date32[day]": "DATE",
        "timestamp[*, tz=UTC]": "TIMESTAMPTZ",
    }
)
"""DuckDB type of each Arrow type a mirrored Parquet schema uses.

A UTC timestamp of any unit is ``timestamp[*, tz=UTC]``.
"""


def arrow_type_key(arrow_type: pa.DataType) -> str:
    """Return the key of ``arrow_type`` in :data:`ARROW_TO_DUCKDB`."""
    if pa.types.is_timestamp(arrow_type):
        return f"timestamp[*, tz={arrow_type.tz}]"
    return str(arrow_type)


@dataclass(frozen=True, slots=True)
class MirroredTable:
    """An index table that copies a Parquet schema, and what it does differently.

    ``types`` gives a column its own DuckDB type (constraints included).
    ``coded`` maps a field to the dimension table it is coded on: the column
    becomes ``<field>_id SMALLINT REFERENCES <table>(id)``. ``leave_out`` names
    the fields the index does not keep. ``extra`` lists the columns the index
    alone carries, as ``(name, DuckDB definition)``, written after the others.
    """

    name: str
    schema: pa.Schema
    types: Mapping[str, str] = field(default_factory=dict)
    coded: Mapping[str, str] = field(default_factory=dict)
    leave_out: frozenset[str] = frozenset()
    extra: tuple[tuple[str, str], ...] = ()


def _column(table: MirroredTable, arrow_field: pa.Field) -> str:
    nullity = "" if arrow_field.nullable else " NOT NULL"
    if arrow_field.name in table.coded:
        dimension = table.coded[arrow_field.name]
        return f"{arrow_field.name}_id SMALLINT{nullity} REFERENCES {dimension}(id)"
    if arrow_field.name in table.types:
        return f"{arrow_field.name} {table.types[arrow_field.name]}{nullity}"
    key = arrow_type_key(arrow_field.type)
    try:
        duckdb_type = ARROW_TO_DUCKDB[key]
    except KeyError:
        raise KeyError(
            f"{table.name}.{arrow_field.name} has Arrow type {arrow_field.type}, "
            "which ARROW_TO_DUCKDB does not map"
        ) from None
    return f"{arrow_field.name} {duckdb_type}{nullity}"


def table_ddl(table: MirroredTable) -> str:
    """Return the ``CREATE TABLE`` statement of a mirrored table.

    Raises ``KeyError`` naming the field and its type when an Arrow type is not
    in :data:`ARROW_TO_DUCKDB`.
    """
    columns = [
        _column(table, arrow_field)
        for arrow_field in table.schema
        if arrow_field.name not in table.leave_out
    ]
    columns.extend(f"{name} {definition}" for name, definition in table.extra)
    body = ",\n".join(f"    {column}" for column in columns)
    return f"CREATE TABLE {table.name} (\n{body}\n);"


MIRRORED_TABLES: Final[tuple[MirroredTable, ...]] = (
    MirroredTable(
        name="simulations",
        schema=SIMULATION_SCHEMA,
        types={"sim_id": "UUID PRIMARY KEY", "parent_sim_id": "UUID"},
        coded={
            "solver": "solvers",
            "status": "statuses",
            "flow_regime": "flow_regimes",
            "mesh_topology": "mesh_topologies",
        },
        leave_out=frozenset({"solver_category"}),
        extra=(
            ("mesh_engine", "VARCHAR"),
            ("config_toml", "VARCHAR"),
            ("config_snapshot", "JSON"),
            ("solution_key", "VARCHAR"),
            ("request_id", "VARCHAR"),
            (
                "label",
                "VARCHAR NOT NULL "
                "CHECK (label IN ('exploratory', 'calibrated', 'evaluated', 'failed'))",
            ),
            ("label_date", "DATE NOT NULL"),
            ("rule_version", "VARCHAR NOT NULL"),
            ("label_reasons", "VARCHAR"),
            ("known_issues", "VARCHAR"),
        ),
    ),
    MirroredTable(name="parameters", schema=PARAMETERS_SCHEMA, types={"sim_id": "UUID"}),
    MirroredTable(
        name="metrics",
        schema=METRICS_SCHEMA,
        types={"sim_id": "UUID"},
        leave_out=frozenset({"valid_from"}),
    ),
    MirroredTable(
        name="provenance",
        schema=PROVENANCE_SCHEMA,
        types={"sim_id": "UUID", "stats": "JSON"},
        extra=(("valid_from", "TIMESTAMPTZ"),),
    ),
)
"""The index tables whose columns are read off a Parquet schema of the run."""

_SIMULATIONS = _SIMULATIONS_TEMPLATE.format_map(
    {table.name: table_ddl(table) for table in MIRRORED_TABLES}
)

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

SESSION_CHILD_TABLES: Final[tuple[str, ...]] = (
    "calibration_session_cases",
    "calibration_phases",
    "calibration_iterations",
    "calibration_trial_cases",
)
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
    "ARROW_TO_DUCKDB",
    "CASE_KINDS",
    "MIRRORED_TABLES",
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
    "MirroredTable",
    "arrow_type_key",
    "create_index_schema",
    "read_index_schema_version",
    "table_ddl",
]
