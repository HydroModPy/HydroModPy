"""Unit tests for the refactored DuckDB simulation catalog (phase P02)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import duckdb
import pytest

from hydromodpy.results.catalog import SimulationCatalog
from hydromodpy.results.catalog_schema import (
    TABLE_NAMES,
    VIEW_NAMES,
    ensure_schema,
)


@pytest.fixture
def mem_conn():
    conn = duckdb.connect(":memory:")
    ensure_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def catalog(tmp_path: Path):
    cat = SimulationCatalog(tmp_path / "workspace")
    yield cat
    cat.close()


def _sim_id() -> str:
    return str(uuid.uuid4())


class TestSchema:
    def test_sixteen_tables_present(self, mem_conn):
        rows = mem_conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='main' AND table_type='BASE TABLE'"
        ).fetchall()
        tables = {r[0] for r in rows}
        assert set(TABLE_NAMES) <= tables
        assert len(TABLE_NAMES) == 16

    def test_schema_version_table_absent(self, mem_conn):
        rows = mem_conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='main'"
        ).fetchall()
        tables = {r[0] for r in rows}
        assert "_schema_version" not in tables

    def test_config_snapshot_column_exists(self, mem_conn):
        row = mem_conn.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name='simulations' AND column_name='config_snapshot'"
        ).fetchone()
        assert row is not None
        assert "JSON" in row[0].upper()

    def test_geographic_fingerprint_column_exists(self, mem_conn):
        row = mem_conn.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name='simulations' "
            "AND column_name='geographic_fingerprint'"
        ).fetchone()
        assert row is not None
        assert "VARCHAR" in row[0].upper()

    def test_bbox_expanded_to_four_columns(self, mem_conn):
        cols = {
            r[0]
            for r in mem_conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='simulations'"
            ).fetchall()
        }
        assert {"bbox_xmin", "bbox_ymin", "bbox_xmax", "bbox_ymax"} <= cols
        assert "bbox" not in cols  # old single-array column is gone

    def test_period_columns_timestamptz(self, mem_conn):
        rows = mem_conn.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name='simulations' "
            "AND column_name IN ('period_start','period_end',"
            "                    'started_at','ended_at','created_at')"
        ).fetchall()
        for _, dtype in rows:
            assert "TIME" in dtype.upper()

    def test_ensure_schema_is_idempotent(self, mem_conn):
        ensure_schema(mem_conn)
        ensure_schema(mem_conn)
        rows = mem_conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='main'"
        ).fetchall()
        tables = {r[0] for r in rows}
        assert set(TABLE_NAMES) <= tables


class TestRegisterAndRead:
    def test_register_creates_row(self, catalog):
        sid = _sim_id()
        catalog.register_simulation(sid, project="p1", solver="modflow6")
        row = catalog.connection.execute(
            "SELECT project, solver, status FROM simulations WHERE sim_id=?",
            [sid],
        ).fetchone()
        assert row == ("p1", "modflow6", "running")

    def test_register_stores_config_snapshot(self, catalog):
        sid = _sim_id()
        snapshot = {"flow": {"regime": "steady"}, "k": 1.5e-5}
        catalog.register_simulation(
            sid, project="p", solver="modflow6",
            config_snapshot=snapshot,
        )
        raw = catalog.connection.execute(
            "SELECT config_snapshot FROM simulations WHERE sim_id=?",
            [sid],
        ).fetchone()[0]
        assert json.loads(raw) == snapshot

    def test_register_config_snapshot_falls_back_to_config(self, catalog):
        sid = _sim_id()
        config = {"a": 1, "b": 2}
        catalog.register_simulation(
            sid, project="p", solver="modflow6", config=config,
        )
        raw = catalog.connection.execute(
            "SELECT config_snapshot FROM simulations WHERE sim_id=?",
            [sid],
        ).fetchone()[0]
        assert json.loads(raw) == config

    def test_register_maps_bbox_and_crs(self, catalog):
        sid = _sim_id()
        catalog.register_simulation(
            sid, project="p", solver="modflow6",
            bbox=[1.0, 2.0, 3.0, 4.0], crs="EPSG:2154",
        )
        row = catalog.connection.execute(
            "SELECT bbox_xmin, bbox_ymin, bbox_xmax, bbox_ymax, "
            "       crs_wkt, crs_epsg "
            "FROM simulations WHERE sim_id=?",
            [sid],
        ).fetchone()
        assert row == (1.0, 2.0, 3.0, 4.0, "EPSG:2154", 2154)

    def test_register_persists_geographic_fingerprint(self, catalog):
        sid = _sim_id()
        fp = "a" * 64
        catalog.register_simulation(
            sid, project="p", solver="modflow6",
            geographic_fingerprint=fp,
        )
        row = catalog.connection.execute(
            "SELECT geographic_fingerprint FROM simulations WHERE sim_id=?",
            [sid],
        ).fetchone()
        assert row[0] == fp

    def test_register_with_zarr_creates_store(self, catalog):
        sid = _sim_id()
        reg = catalog.register_simulation(
            sid, project="p", solver="modflow6",
            n_cells=16, n_layers=2, geographic_fingerprint="fp-abc",
        )
        sz = reg.zarr
        try:
            assert sz is not None
            assert sz.geographic_fingerprint == "fp-abc"
            zarr_dir = catalog.workspace_path / "simulations" / f"{sid}.zarr"
            assert zarr_dir.is_dir()
        finally:
            if sz is not None:
                sz.close()


class TestPrimaryKeys:
    def test_parameters_pk_rejects_duplicates(self, mem_conn):
        sid = _sim_id()
        mem_conn.execute(
            "INSERT INTO simulations (sim_id, project, solver) "
            "VALUES (?, 'p', 'mf6')", [sid],
        )
        mem_conn.execute(
            "INSERT INTO parameters (sim_id, param_name, value) "
            "VALUES (?, 'K', 1.0)", [sid],
        )
        with pytest.raises(duckdb.ConstraintException):
            mem_conn.execute(
                "INSERT INTO parameters (sim_id, param_name, value) "
                "VALUES (?, 'K', 2.0)", [sid],
            )

    def test_metrics_pk_includes_variable(self, mem_conn):
        sid = _sim_id()
        mem_conn.execute(
            "INSERT INTO simulations (sim_id, project, solver) "
            "VALUES (?, 'p', 'mf6')", [sid],
        )
        mem_conn.execute(
            "INSERT INTO metrics (sim_id, station_id, variable, "
            "metric_name, value) "
            "VALUES (?, 'P01', 'head', 'nse', 0.8)", [sid],
        )
        # Same metric / variable / station → conflict
        with pytest.raises(duckdb.ConstraintException):
            mem_conn.execute(
                "INSERT INTO metrics (sim_id, station_id, variable, "
                "metric_name, value) "
                "VALUES (?, 'P01', 'head', 'nse', 0.9)", [sid],
            )
        # Different variable → distinct row allowed
        mem_conn.execute(
            "INSERT INTO metrics (sim_id, station_id, variable, "
            "metric_name, value) "
            "VALUES (?, 'P01', 'discharge', 'nse', 0.7)", [sid],
        )


class TestPerSimColumns:
    def test_per_sim_tables_carry_sim_id(self, mem_conn):
        """Each per-sim table exposes a non-null ``sim_id`` column.

        Referential integrity is enforced by the catalog's delete path
        rather than by DuckDB FK constraints (see module docstring), so
        this test only checks the structural invariant.
        """
        per_sim = (
            "parameters", "metrics", "timeseries", "budgets",
            "mass_balance", "observation_points", "provenance",
            "geographic_features", "geographic_metadata",
        )
        for table in per_sim:
            row = mem_conn.execute(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name = ? AND column_name = 'sim_id'",
                [table],
            ).fetchone()
            assert row is not None, f"{table} missing sim_id"
            assert row[0] == "NO", f"{table}.sim_id must be NOT NULL"


class TestChecks:
    def test_status_enum_enforced(self, mem_conn):
        sid = _sim_id()
        with pytest.raises(duckdb.ConstraintException):
            mem_conn.execute(
                "INSERT INTO simulations (sim_id, project, solver, status) "
                "VALUES (?, 'p', 'mf6', 'bogus')", [sid],
            )

    def test_budget_component_not_null(self, mem_conn):
        """The budgets table must reject NULL component values.

        The previous enum-based CHECK was dropped because solver
        extractors legitimately emit labels like ``drains``,
        ``river leakage`` or ``head dep bounds`` that were outside the
        original closed list. Only NOT NULL is enforced now.
        """
        sid = _sim_id()
        mem_conn.execute(
            "INSERT INTO simulations (sim_id, project, solver) "
            "VALUES (?, 'p', 'mf6')", [sid],
        )
        with pytest.raises(duckdb.ConstraintException):
            mem_conn.execute(
                "INSERT INTO budgets (sim_id, timestep, component, "
                "flux_in, flux_out) VALUES (?, 0, NULL, 0, 0)", [sid],
            )
        # A previously-rejected label like 'drains' is now accepted.
        mem_conn.execute(
            "INSERT INTO budgets (sim_id, timestep, component, "
            "flux_in, flux_out) VALUES (?, 0, 'drains', 0, 0)", [sid],
        )

    def test_bbox_order_enforced(self, mem_conn):
        sid = _sim_id()
        with pytest.raises(duckdb.ConstraintException):
            mem_conn.execute(
                "INSERT INTO simulations (sim_id, project, solver, "
                "bbox_xmin, bbox_xmax) VALUES (?, 'p', 'mf6', 10, 0)", [sid],
            )


class TestG05Tables:
    """The 4 G05-added tables: runs_environment, tags, stations, observations."""

    def test_runs_environment_pk_is_sim_id(self, mem_conn):
        sid = _sim_id()
        mem_conn.execute(
            "INSERT INTO simulations (sim_id, project, solver) "
            "VALUES (?, 'p', 'mf6')", [sid],
        )
        mem_conn.execute(
            "INSERT INTO runs_environment (sim_id, python_version) "
            "VALUES (?, '3.13')", [sid],
        )
        with pytest.raises(duckdb.ConstraintException):
            mem_conn.execute(
                "INSERT INTO runs_environment (sim_id, python_version) "
                "VALUES (?, '3.12')", [sid],
            )

    def test_tags_pk_sim_tag(self, mem_conn):
        sid = _sim_id()
        mem_conn.execute(
            "INSERT INTO simulations (sim_id, project, solver) "
            "VALUES (?, 'p', 'mf6')", [sid],
        )
        mem_conn.execute(
            "INSERT INTO tags (sim_id, tag) VALUES (?, 'draft')", [sid],
        )
        mem_conn.execute(
            "INSERT INTO tags (sim_id, tag) VALUES (?, 'published')", [sid],
        )
        with pytest.raises(duckdb.ConstraintException):
            mem_conn.execute(
                "INSERT INTO tags (sim_id, tag) VALUES (?, 'draft')", [sid],
            )

    def test_stations_pk_station_variable(self, mem_conn):
        mem_conn.execute(
            "INSERT INTO stations (station_id, variable_type, name) "
            "VALUES ('P01', 'head', 'Piezo P01')"
        )
        mem_conn.execute(
            "INSERT INTO stations (station_id, variable_type, name) "
            "VALUES ('P01', 'discharge', 'Gauge P01')"
        )
        with pytest.raises(duckdb.ConstraintException):
            mem_conn.execute(
                "INSERT INTO stations (station_id, variable_type, name) "
                "VALUES ('P01', 'head', 'Duplicate')"
            )

    def test_observations_pk(self, mem_conn):
        mem_conn.execute(
            "INSERT INTO observations "
            "(station_id, variable_type, datetime, value) "
            "VALUES ('P01', 'head', TIMESTAMP '2020-01-01', 1.0)"
        )
        with pytest.raises(duckdb.ConstraintException):
            mem_conn.execute(
                "INSERT INTO observations "
                "(station_id, variable_type, datetime, value) "
                "VALUES ('P01', 'head', TIMESTAMP '2020-01-01', 2.0)"
            )


class TestG05Views:
    """The four denormalized views added in G05."""

    def test_views_exist(self, mem_conn):
        rows = mem_conn.execute(
            "SELECT table_name FROM information_schema.views "
            "WHERE table_schema='main'"
        ).fetchall()
        names = {r[0] for r in rows}
        assert set(VIEW_NAMES) <= names

    def test_simulation_summary_pulls_outlet_metrics(self, mem_conn):
        sid = _sim_id()
        mem_conn.execute(
            "INSERT INTO simulations (sim_id, project, solver, status) "
            "VALUES (?, 'river', 'mf6', 'completed')", [sid],
        )
        mem_conn.execute(
            "INSERT INTO metrics (sim_id, metric_name, value) "
            "VALUES (?, 'nse', 0.9)", [sid],
        )
        mem_conn.execute(
            "INSERT INTO metrics (sim_id, metric_name, value) "
            "VALUES (?, 'rmse', 0.05)", [sid],
        )
        row = mem_conn.execute(
            "SELECT nse, rmse FROM v_simulation_summary WHERE sim_id = ?",
            [sid],
        ).fetchone()
        assert row is not None
        assert row[0] == 0.9
        assert row[1] == 0.05

    def test_best_per_project_picks_highest_nse(self, mem_conn):
        sa = _sim_id()
        sb = _sim_id()
        for sid, nse in [(sa, 0.5), (sb, 0.8)]:
            mem_conn.execute(
                "INSERT INTO simulations (sim_id, project, solver, status) "
                "VALUES (?, 'lab', 'mf6', 'completed')", [sid],
            )
            mem_conn.execute(
                "INSERT INTO metrics (sim_id, metric_name, value) "
                "VALUES (?, 'nse', ?)", [sid, nse],
            )
        row = mem_conn.execute(
            "SELECT sim_id FROM v_best_per_project WHERE project='lab'"
        ).fetchone()
        assert str(row[0]) == sb

    def test_metrics_wide_pivots_known_names(self, mem_conn):
        sid = _sim_id()
        mem_conn.execute(
            "INSERT INTO simulations (sim_id, project, solver) "
            "VALUES (?, 'p', 'mf6')", [sid],
        )
        for name, val in [("nse", 0.9), ("kge", 0.85), ("rmse", 0.1)]:
            mem_conn.execute(
                "INSERT INTO metrics (sim_id, metric_name, value) "
                "VALUES (?, ?, ?)", [sid, name, val],
            )
        row = mem_conn.execute(
            "SELECT nse, kge, rmse FROM v_metrics_wide WHERE sim_id = ?",
            [sid],
        ).fetchone()
        assert row == (0.9, 0.85, 0.1)

    def test_params_wide_returns_map(self, mem_conn):
        sid = _sim_id()
        mem_conn.execute(
            "INSERT INTO simulations (sim_id, project, solver) "
            "VALUES (?, 'p', 'mf6')", [sid],
        )
        mem_conn.execute(
            "INSERT INTO parameters (sim_id, param_name, value) "
            "VALUES (?, 'K', 1e-5)", [sid],
        )
        mem_conn.execute(
            "INSERT INTO parameters (sim_id, param_name, zone_id, value) "
            "VALUES (?, 'K', 'granite', 5e-6)", [sid],
        )
        row = mem_conn.execute(
            "SELECT params FROM v_params_wide WHERE sim_id = ?", [sid],
        ).fetchone()
        params = row[0]
        assert params["K"] == 1e-5
        assert params["K::granite"] == 5e-6


class TestG05ZoneGlobal:
    """The ``parameters.zone_id`` default was renamed ``_homogeneous`` ->
    ``__global__`` in G05. Make sure the new default is active and the old
    one no longer resolves."""

    def test_global_zone_is_default(self, mem_conn):
        sid = _sim_id()
        mem_conn.execute(
            "INSERT INTO simulations (sim_id, project, solver) "
            "VALUES (?, 'p', 'mf6')", [sid],
        )
        mem_conn.execute(
            "INSERT INTO parameters (sim_id, param_name, value) "
            "VALUES (?, 'K', 1.0)", [sid],
        )
        row = mem_conn.execute(
            "SELECT zone_id FROM parameters WHERE sim_id = ?", [sid],
        ).fetchone()
        assert row[0] == "__global__"

    def test_old_homogeneous_zone_constant_is_gone(self):
        from hydromodpy.results import catalog_schema
        assert not hasattr(catalog_schema, "HOMOGENEOUS_ZONE")
        assert catalog_schema.GLOBAL_ZONE == "__global__"


class TestResolveReference:
    """``catalog.resolve(ref)`` — unified UUID / prefix / name resolution."""

    def _register(self, catalog, *, project="p", name=None):
        sid = _sim_id()
        catalog.register_simulation(
            sid, project=project, solver="modflow6", name=name,
        )
        return sid

    def test_full_uuid_resolves(self, catalog):
        sid = self._register(catalog)
        assert catalog.resolve(sid) == sid

    def test_uuid_prefix_unique_resolves(self, catalog):
        sid = self._register(catalog)
        assert catalog.resolve(sid[:8]) == sid
        assert catalog.resolve(sid[:12]) == sid

    def test_uuid_prefix_too_short_not_accepted_as_uuid(self, catalog):
        sid = self._register(catalog)
        from hydromodpy.results.catalog import SimulationNotFoundError
        with pytest.raises(SimulationNotFoundError):
            catalog.resolve(sid[:3])

    def test_uuid_prefix_ambiguous_raises(self, catalog):
        from hydromodpy.results.catalog import AmbiguousReferenceError
        forced_sid_1 = "12345678-0000-0000-0000-000000000001"
        forced_sid_2 = "12349999-0000-0000-0000-000000000002"
        catalog.register_simulation(forced_sid_1, project="p", solver="s")
        catalog.register_simulation(forced_sid_2, project="p", solver="s")
        with pytest.raises(AmbiguousReferenceError):
            catalog.resolve("1234")

    def test_name_in_project_resolves(self, catalog):
        sid = self._register(catalog, name="baseline")
        assert catalog.resolve("baseline", project="p") == sid

    def test_name_without_project_resolves_if_unique(self, catalog):
        sid = self._register(catalog, name="only_one")
        assert catalog.resolve("only_one") == sid

    def test_name_without_project_ambiguous(self, catalog):
        from hydromodpy.results.catalog import AmbiguousReferenceError
        sid_a = self._register(catalog, project="p1", name="shared")
        sid_b = self._register(catalog, project="p2", name="shared")
        with pytest.raises(AmbiguousReferenceError):
            catalog.resolve("shared")
        assert catalog.resolve("shared", project="p1") == sid_a
        assert catalog.resolve("shared", project="p2") == sid_b

    def test_not_found_raises(self, catalog):
        from hydromodpy.results.catalog import SimulationNotFoundError
        with pytest.raises(SimulationNotFoundError):
            catalog.resolve("no-such-thing")

    def test_getitem_delegates_to_resolve(self, catalog):
        sid = self._register(catalog, name="via_item")
        assert catalog[sid[:8]].sim_id == sid
        assert catalog[sid].sim_id == sid


class TestOnCollision:
    """``register_simulation(on_collision=...)`` behavior."""

    def test_replace_soft_clears_previous_name(self, catalog):
        old = _sim_id()
        new = _sim_id()
        catalog.register_simulation(old, project="p", solver="s", name="foo")
        reg = catalog.register_simulation(
            new, project="p", solver="s", name="foo",
            on_collision="replace",
        )
        assert reg.name == "foo"
        assert reg.replaced_sim_id == old
        sims = catalog.list_simulations(project="p")
        rows = {str(r["sim_id"]): r["name"] for _, r in sims.iterrows()}
        assert rows[new] == "foo"
        assert rows[old] is None

    def test_fail_raises_duplicate(self, catalog):
        from hydromodpy.results.catalog import DuplicateSimulationNameError
        old = _sim_id()
        new = _sim_id()
        catalog.register_simulation(old, project="p", solver="s", name="foo")
        with pytest.raises(DuplicateSimulationNameError):
            catalog.register_simulation(
                new, project="p", solver="s", name="foo",
                on_collision="fail",
            )

    def test_version_auto_suffixes(self, catalog):
        sid_1 = _sim_id()
        sid_2 = _sim_id()
        sid_3 = _sim_id()
        catalog.register_simulation(sid_1, project="p", solver="s", name="foo")
        reg2 = catalog.register_simulation(
            sid_2, project="p", solver="s", name="foo",
            on_collision="version",
        )
        reg3 = catalog.register_simulation(
            sid_3, project="p", solver="s", name="foo",
            on_collision="version",
        )
        assert reg2.name == "foo.v2"
        assert reg3.name == "foo.v3"

    def test_different_projects_do_not_collide(self, catalog):
        sid_a = _sim_id()
        sid_b = _sim_id()
        catalog.register_simulation(sid_a, project="p1", solver="s", name="foo")
        reg = catalog.register_simulation(
            sid_b, project="p2", solver="s", name="foo",
            on_collision="fail",
        )
        assert reg.name == "foo"

    def test_replace_is_the_default(self, catalog):
        old = _sim_id()
        new = _sim_id()
        catalog.register_simulation(old, project="p", solver="s", name="x")
        reg = catalog.register_simulation(new, project="p", solver="s", name="x")
        assert reg.replaced_sim_id == old


def test_short_id_helper():
    from hydromodpy.results.catalog import short_id
    assert short_id("19d90750-a7ae-451a-9e6d-805a46d136d8") == "19d90750"
    assert len(short_id(uuid.uuid4())) == 8
