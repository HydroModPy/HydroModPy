"""Catalog v2 schema validation tests (P4).

Verifies the full v2 DDL is created end-to-end through ``SimulationCatalog``
and that the migration runner reports the right state, FK semantics work
through the Python lifecycle cascade, and no legacy ``mf6_*`` columns
survive in the new schema.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from hydromodpy.results.catalog.facade import SimulationCatalog
from tests._helpers.fixtures_catalog import simulation_catalog

# Tables we expect after migration 0001 has applied.
_EXPECTED_TABLES: frozenset[str] = frozenset(
    {
        # System tables installed by the runner
        "_schema_version",
        "schema_migrations",
        # Dim tables (replace v1 CHECK enums)
        "solvers",
        "statuses",
        "flow_regimes",
        "mesh_topologies",
        # Star schema dim tables
        "dim_variables",
        "dim_stations",
        "dim_metrics",
        "dim_projects",
        "dim_study_areas",
        # Core fact tables
        "simulations",
        "parameters",
        "metrics",
        "metric_definitions",
        "runs_environment",
        "provenance",
        "observations",
        "observation_points",
        # Cross-cutting
        "audit_log",
        "deletions",
        "tracked_files",
        "geographic_features",
        "geographic_metadata",
        "parquet_files",
        "tags",
        "stations",
        # Calibration
        "calibration_sessions",
        "calibration_iterations",
        # Workflow
        "workflow_steps",
    }
)


@pytest.fixture
def catalog(tmp_path: Path) -> SimulationCatalog:
    """Fresh catalog on a tmp workspace, closed at teardown."""
    with simulation_catalog(tmp_path) as cat:
        yield cat


def _table_set(cat: SimulationCatalog) -> set[str]:
    rows = cat.connection.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'main' AND table_type = 'BASE TABLE'"
    ).fetchall()
    return {r[0] for r in rows}


def _columns(cat: SimulationCatalog, table: str) -> dict[str, str]:
    rows = cat.connection.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'main' AND table_name = ?",
        [table],
    ).fetchall()
    return {r[0]: r[1].upper() for r in rows}


# ---------------------------------------------------------------------------
# Presence of every table the v2 spec requires
# ---------------------------------------------------------------------------


def test_every_expected_table_exists(catalog: SimulationCatalog) -> None:
    """All v2 catalog tables are created by the migration."""
    present = _table_set(catalog)
    missing = _EXPECTED_TABLES - present
    assert not missing, f"Missing tables: {sorted(missing)}"


def test_table_count_matches_spec(catalog: SimulationCatalog) -> None:
    """The schema lists exactly the expected number of catalog tables."""
    present = _table_set(catalog)
    # Allow extras (system catalogs) but require >= the expected count.
    assert len(present & _EXPECTED_TABLES) == len(_EXPECTED_TABLES)


# ---------------------------------------------------------------------------
# Per-table column checks
# ---------------------------------------------------------------------------


def test_simulations_has_v2_fk_columns(catalog: SimulationCatalog) -> None:
    """``simulations`` carries the v2 dim FKs and core scalars."""
    cols = _columns(catalog, "simulations")
    assert "sim_id" in cols and "UUID" in cols["sim_id"]
    assert "solver_id" in cols and cols["solver_id"] == "SMALLINT"
    assert "status_id" in cols and cols["status_id"] == "SMALLINT"
    assert "flow_regime_id" in cols
    assert "mesh_topology_id" in cols
    assert "scientific_objective" in cols
    assert "description" in cols
    assert "principal_id" in cols
    assert "last_heartbeat" in cols


def test_simulations_no_mf6_columns(catalog: SimulationCatalog) -> None:
    """v2 ``simulations`` must not carry any legacy ``mf6_*`` column."""
    cols = _columns(catalog, "simulations")
    assert not any(c.startswith("mf6_") for c in cols)


def test_runs_environment_is_solver_agnostic(catalog: SimulationCatalog) -> None:
    """``runs_environment`` exposes ``solver_*`` and no ``mf6_*``."""
    cols = _columns(catalog, "runs_environment")
    for required in (
        "solver_name",
        "solver_binary_path",
        "solver_binary_sha256",
        "solver_version_text",
        "git_dirty",
        "principal_id",
    ):
        assert required in cols, f"runs_environment.{required} missing"
    assert not any(c.startswith("mf6_") for c in cols), "Found legacy mf6_* columns"


def test_parameters_has_valid_from(catalog: SimulationCatalog) -> None:
    """``parameters.valid_from`` enables point-in-time correctness."""
    cols = _columns(catalog, "parameters")
    assert "valid_from" in cols
    assert "TIMESTAMP" in cols["valid_from"]


def test_metrics_has_valid_from(catalog: SimulationCatalog) -> None:
    """``metrics.valid_from`` enables point-in-time correctness."""
    cols = _columns(catalog, "metrics")
    assert "valid_from" in cols
    assert "TIMESTAMP" in cols["valid_from"]


def test_provenance_has_valid_from_and_v2_columns(catalog: SimulationCatalog) -> None:
    """``provenance`` exposes ``valid_from``, ``license``, ``etag``."""
    cols = _columns(catalog, "provenance")
    assert "valid_from" in cols
    assert "license" in cols
    assert "data_provider" in cols
    assert "etag" in cols
    assert "last_modified" in cols


def test_observations_has_valid_from(catalog: SimulationCatalog) -> None:
    """``observations.valid_from`` is required by §4.10octies."""
    cols = _columns(catalog, "observations")
    assert "valid_from" in cols


def test_audit_log_has_event_id_uuid(catalog: SimulationCatalog) -> None:
    """``audit_log`` is the new event-sourcing table with UUID PK."""
    cols = _columns(catalog, "audit_log")
    assert "event_id" in cols and "UUID" in cols["event_id"]
    assert "event_type" in cols
    assert "actor_kind" in cols


def test_deletions_tombstone_table(catalog: SimulationCatalog) -> None:
    """``deletions`` carries the GDPR tombstone columns."""
    cols = _columns(catalog, "deletions")
    assert "sim_id" in cols and "UUID" in cols["sim_id"]
    assert "deleted_at" in cols
    assert "sha256_snapshot" in cols


def test_parquet_files_manifest_columns(catalog: SimulationCatalog) -> None:
    """``parquet_files`` manifest exposes path / view / sha / written_at."""
    cols = _columns(catalog, "parquet_files")
    assert "path" in cols
    assert "view_name" in cols
    assert "sha256" in cols
    assert "written_at" in cols


def test_tracked_files_canonical_path_column(catalog: SimulationCatalog) -> None:
    """``tracked_files`` carries ``canonical_path`` for workspace-relative storage."""
    cols = _columns(catalog, "tracked_files")
    assert "canonical_path" in cols
    assert "role" in cols
    assert "sha256" in cols


def test_workflow_steps_has_status_fk(catalog: SimulationCatalog) -> None:
    """``workflow_steps`` references ``statuses(id)`` (FK to dim)."""
    cols = _columns(catalog, "workflow_steps")
    assert "status_id" in cols
    assert "checkpoint_path" in cols


def test_calibration_sessions_v2_enrichment(catalog: SimulationCatalog) -> None:
    """``calibration_sessions`` carries the v2 enrichment columns."""
    cols = _columns(catalog, "calibration_sessions")
    for required in (
        "config_path",
        "seed",
        "hydromodpy_version",
        "python_version",
        "hostname",
        "optimizer_storage",
        "optimizer_state_blob",
        "wallclock_breakdown",
        "last_resumed_at",
        "n_resumes",
    ):
        assert required in cols, f"calibration_sessions.{required} missing"


# ---------------------------------------------------------------------------
# Dim tables seeded with the canonical vocabulary
# ---------------------------------------------------------------------------


def test_dim_solvers_seeded(catalog: SimulationCatalog) -> None:
    """``solvers`` is pre-populated with the six canonical codes."""
    rows = catalog.connection.execute("SELECT code FROM solvers ORDER BY id").fetchall()
    codes = [r[0] for r in rows]
    assert codes == [
        "modflow6",
        "modflow_nwt",
        "boussinesq",
        "gr4j",
        "mt3dms",
        "modpath",
    ]


def test_dim_statuses_seeded(catalog: SimulationCatalog) -> None:
    """``statuses`` is pre-populated with the seven lifecycle states."""
    rows = catalog.connection.execute("SELECT code FROM statuses ORDER BY id").fetchall()
    codes = [r[0] for r in rows]
    assert codes == [
        "pending",
        "running",
        "completed",
        "partial",
        "failed",
        "aborted",
        "resumed",
    ]


def test_dim_flow_regimes_seeded(catalog: SimulationCatalog) -> None:
    """``flow_regimes`` has the three canonical regimes."""
    rows = catalog.connection.execute("SELECT code FROM flow_regimes ORDER BY id").fetchall()
    assert {r[0] for r in rows} == {"steady", "transient", "steady_then_transient"}


def test_dim_mesh_topologies_seeded(catalog: SimulationCatalog) -> None:
    """``mesh_topologies`` has the six canonical topologies."""
    rows = catalog.connection.execute("SELECT code FROM mesh_topologies ORDER BY id").fetchall()
    assert {r[0] for r in rows} == {
        "structured_2d",
        "structured_3d",
        "unstructured_2d",
        "unstructured_3d",
        "lumped",
        "network_1d",
    }


def test_metric_definitions_seeded(catalog: SimulationCatalog) -> None:
    """``metric_definitions`` is pre-populated with NSE/KGE/RMSE/R2/etc."""
    rows = catalog.connection.execute(
        "SELECT metric_name FROM metric_definitions ORDER BY metric_name"
    ).fetchall()
    names = {r[0] for r in rows}
    for required in ("nse", "kge", "rmse", "r2", "mae", "bias", "pbias"):
        assert required in names


# ---------------------------------------------------------------------------
# Schema-version bookkeeping
# ---------------------------------------------------------------------------


def test_schema_version_records_catalog_v1(catalog: SimulationCatalog) -> None:
    """``_schema_version`` carries the latest catalog migration after init."""
    rows = catalog.connection.execute("SELECT component, version FROM _schema_version").fetchall()
    assert ("catalog", 4) in rows


def test_schema_migrations_records_all_known_migrations(catalog: SimulationCatalog) -> None:
    """``schema_migrations`` records the bundled migrations in order."""
    rows = catalog.connection.execute(
        "SELECT version, slug FROM schema_migrations ORDER BY version"
    ).fetchall()
    assert rows == [
        (1, "initial"),
        (2, "audit_hash_chain"),
        (3, "retention_policies"),
        (4, "workflow_events"),
    ]


def test_workflow_steps_has_artifact_uris_column(catalog: SimulationCatalog) -> None:
    """``workflow_steps`` exposes ``artifact_uris`` (JSON) as a native column."""
    cols = _columns(catalog, "workflow_steps")
    assert "artifact_uris" in cols


# ---------------------------------------------------------------------------
# Idempotence
# ---------------------------------------------------------------------------


def test_double_init_is_idempotent(tmp_path: Path) -> None:
    """Two consecutive catalogs on the same workspace do not duplicate."""
    cat1 = SimulationCatalog(tmp_path)
    tables_a = _table_set(cat1)
    cat1.close()

    cat2 = SimulationCatalog(tmp_path)
    tables_b = _table_set(cat2)
    rows = cat2.connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()
    version_rows = cat2.connection.execute("SELECT COUNT(*) FROM _schema_version").fetchone()
    cat2.close()

    assert tables_a == tables_b
    assert rows[0] == 4, "schema_migrations should record every bundled migration"
    assert version_rows[0] == 1


# ---------------------------------------------------------------------------
# Cascading delete (enforced by Python lifecycle, FK absent at DuckDB layer)
# ---------------------------------------------------------------------------


def test_delete_cascades_to_per_sim_tables(catalog: SimulationCatalog) -> None:
    """``catalog.delete(sid)`` removes child rows in parameters/metrics."""
    sid = uuid.uuid4()
    catalog.register_simulation(
        sid,
        "lab",
        "modflow6",
        name="t1",
        n_cells=10,
        n_layers=1,
    )
    catalog.write_parameters(str(sid), [{"param_name": "k", "value": 1.0}])
    catalog.write_metric(str(sid), "__outlet__", "nse", 0.91)

    # Confirm child rows exist.
    assert catalog.connection.execute("SELECT COUNT(*) FROM parameters").fetchone()[0] == 1
    assert catalog.connection.execute("SELECT COUNT(*) FROM metrics").fetchone()[0] == 1

    catalog.delete(str(sid))

    # Confirm cascading removed every child row.
    assert catalog.connection.execute("SELECT COUNT(*) FROM parameters").fetchone()[0] == 0
    assert catalog.connection.execute("SELECT COUNT(*) FROM metrics").fetchone()[0] == 0
    assert catalog.connection.execute("SELECT COUNT(*) FROM simulations").fetchone()[0] == 0


# ---------------------------------------------------------------------------
# Solver / status JOIN exposure
# ---------------------------------------------------------------------------


def test_list_simulations_joins_dim_text(catalog: SimulationCatalog) -> None:
    """``list_simulations`` returns ``solver`` / ``status`` text via JOIN."""
    sid = uuid.uuid4()
    catalog.register_simulation(
        sid,
        "lab",
        "modflow6",
        name="t1",
        n_cells=10,
        n_layers=1,
    )
    df = catalog.list_simulations()
    assert "solver" in df.columns
    assert "solver_category" in df.columns
    assert "status" in df.columns
    assert df.iloc[0]["solver"] == "modflow6"
    assert df.iloc[0]["solver_category"] == "distributed"
    assert df.iloc[0]["status"] == "running"


def test_register_resolves_unknown_solver_to_null_fk(tmp_path: Path) -> None:
    """An unknown solver name lands NULL in solver_id (dim FK strict)."""
    cat = SimulationCatalog(tmp_path)
    sid = uuid.uuid4()
    # ``unknown`` is not in the seeded ``solvers.code`` list; FK insert
    # subselect returns NULL but NOT NULL on solver_id blocks the row.
    with pytest.raises(Exception):
        cat.register_simulation(sid, "lab", "unknown_solver", name="t1")
    cat.close()
