"""Integration coverage for the four ML access patterns of HydroModPy.

Validates that ``SimulationCatalog`` exposes its results through:

- DuckDB SQL queries on ``simulations`` (with scientific metadata columns).
- Parquet files readable directly by ``pandas.read_parquet`` (with KV
  metadata).
- Zarr stores readable directly by ``xarray.open_zarr``.
- ``Catalog.training_split`` returning a deterministic train/val/test split.

The tests run end-to-end against a tmp workspace; no solver is invoked.
"""

from __future__ import annotations

from uuid import uuid4

import numpy as np
import pandas as pd
import pytest

from hydromodpy.results.catalog import SimulationCatalog


@pytest.fixture
def catalog(tmp_path):
    c = SimulationCatalog(tmp_path / "workspace")
    yield c
    c.close()


def _seed_run(
    catalog: SimulationCatalog,
    *,
    project: str,
    name: str,
    objective: str,
    n_cells: int = 4,
    n_timesteps: int = 3,
) -> str:
    """Register, populate, and finalize one fake simulation."""
    sid = str(uuid4())
    catalog.register_simulation(
        sid,
        project=project,
        solver="modflow6",
        name=name,
        scientific_objective=objective,
        study_area_name=f"{project}_basin",
        n_cells=n_cells,
        n_layers=1,
        n_timesteps=n_timesteps,
        mesh_topology="dis",
    )
    catalog.write_run_environment(sid)

    vertices = np.array(
        [[0.0, 0.0], [1.0, 0.0], [2.0, 0.0], [0.0, 1.0], [1.0, 1.0]],
        dtype=float,
    )
    fnc = np.array([[0, 1, 4, 3], [1, 2, 4, 4], [0, 3, 4, 4], [1, 4, 3, 3]], dtype=int)
    catalog.write_mesh(
        sid,
        vertices=vertices,
        face_node_connectivity=fnc,
        z_interfaces=np.array([0.0, 10.0], dtype=float),
    )
    for t in range(n_timesteps):
        head = np.full((1, n_cells), float(t + 1), dtype="float64")
        catalog.write_field(sid, "head", t, head, n_timesteps=n_timesteps)

    ts = pd.Series(
        np.linspace(1.0, 5.0, n_timesteps),
        index=pd.date_range("2024-01-01", periods=n_timesteps, freq="D"),
    )
    catalog.write_timeseries(sid, station_id="outlet", variable="discharge", ts=ts, unit="m3/s")
    catalog.write_metric(sid, station_id="__outlet__", metric_name="nse", value=0.7)
    catalog.finalize(sid, status="completed", duration_s=1.0)
    return sid


class TestRunsEnvironment:
    """Pattern 0: every new run has a populated runs_environment row."""

    def test_environment_is_captured(self, catalog):
        sid = _seed_run(catalog, project="ml_p1", name="r1", objective="exploratory")
        row = catalog._db.execute(
            "SELECT python_version, hydromodpy_version, platform, hostname, "
            "memory_gb, cpu_info FROM runs_environment WHERE sim_id = ?",
            [sid],
        ).fetchone()
        assert row is not None, "runs_environment row missing"
        py_ver, hmp_ver, platform, hostname, _mem, cpu_info = row
        assert py_ver and py_ver.count(".") >= 2
        assert hmp_ver
        assert platform
        assert hostname
        assert cpu_info  # JSON-encoded dict, never empty


class TestDuckDBPattern:
    """Pattern 1: DuckDB SQL queries return scientific_objective per sim."""

    def test_sql_select_returns_scientific_metadata(self, catalog):
        _seed_run(catalog, project="ml_p2a", name="r1", objective="calibration")
        _seed_run(catalog, project="ml_p2a", name="r2", objective="validation")

        df = catalog._db.execute(
            "SELECT sim_id, project, name, scientific_objective, study_area_name "
            "FROM simulations WHERE project = 'ml_p2a' ORDER BY name"
        ).fetchdf()

        assert len(df) == 2
        assert df["scientific_objective"].tolist() == ["calibration", "validation"]
        assert all(df["study_area_name"] == "ml_p2a_basin")


class TestParquetPattern:
    """Pattern 2: per-sim Parquet files readable directly + KV metadata."""

    def test_parquet_with_kv_metadata(self, catalog):
        sid = _seed_run(catalog, project="ml_p3", name="r1", objective="exploratory")
        target = catalog.parquet_dir_for(sid) / "timeseries.parquet"
        assert target.is_file()

        # Read via DuckDB (no pyarrow dependency); equivalent to
        # pd.read_parquet when pyarrow / fastparquet is installed.
        df = catalog._db.execute(f"SELECT * FROM read_parquet('{target}')").fetchdf()
        assert {"datetime", "value", "variable", "station_id"}.issubset(df.columns)
        assert len(df) > 0

        # The same file is also readable by pandas when pyarrow is available.
        try:
            df_pd = pd.read_parquet(target)
        except ImportError:
            pytest.skip("pyarrow / fastparquet not installed; pandas path is documented")
        else:
            assert {"datetime", "value", "variable", "station_id"}.issubset(df_pd.columns)

        rows = catalog._db.execute(
            f"SELECT key, value FROM parquet_kv_metadata('{target}')"
        ).fetchall()
        kv = {row[0].decode(): row[1].decode() for row in rows}
        assert kv["sim_id"] == sid
        assert kv["project"] == "ml_p3"
        assert kv["scientific_objective"] == "exploratory"
        assert kv["schema_version"]
        assert kv["hydromodpy_version"]


class TestZarrPattern:
    """Pattern 3: per-sim Zarr stores read directly via xarray."""

    def test_run_to_xarray_batch(self, catalog):
        sid = _seed_run(catalog, project="ml_p4", name="r1", objective="exploratory")
        run = catalog[sid]

        ds = run.array.to_xarray_batch(("head",))
        assert "head" in ds
        assert ds["head"].dims == ("time", "layer", "cell")
        assert ds["head"].sizes["time"] == 3
        assert ds["head"].attrs.get("units") == "m"

    def test_run_to_xarray_batch_unknown_field_raises(self, catalog):
        sid = _seed_run(catalog, project="ml_p4b", name="r1", objective="exploratory")
        run = catalog[sid]
        with pytest.raises(KeyError, match="not found"):
            run.array.to_xarray_batch(("watertable_depth",))


class TestTrainingSplit:
    """Pattern 4: deterministic train/val/test split."""

    def test_split_deterministic_and_disjoint(self, catalog):
        for i in range(20):
            _seed_run(
                catalog,
                project=f"split_{i % 2}",
                name=f"r{i}",
                objective="calibration" if i % 2 == 0 else "validation",
            )

        first = catalog.training_split(test_size=0.25, val_size=0.1, random_state=42)
        second = catalog.training_split(test_size=0.25, val_size=0.1, random_state=42)
        assert first == second  # determinism

        train, val, test = first
        all_ids = train + val + test
        assert len(all_ids) == 20
        assert len(set(all_ids)) == 20  # no duplicates across splits

    def test_split_no_completed_returns_empty_tuples(self, catalog):
        train, val, test = catalog.training_split()
        assert (train, val, test) == ([], [], [])

    def test_split_without_sklearn_raises(self, catalog, monkeypatch):
        from hydromodpy.results.catalog import discovery

        _seed_run(catalog, project="ms", name="r1", objective="exploratory")
        # Force the sklearn import inside training_split to fail.
        import builtins as _builtins

        real_import = _builtins.__import__

        def _broken_import(name, *args, **kwargs):
            if name.startswith("sklearn"):
                raise ImportError("simulated absence of sklearn")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(_builtins, "__import__", _broken_import)
        with pytest.raises(discovery.MissingMLDependencyError):
            catalog.training_split()


class TestScientificObjective:
    """Setter and finalize default behaviour for ``scientific_objective``."""

    def test_write_scientific_objective_overrides_existing(self, catalog):
        sid = _seed_run(catalog, project="so", name="r1", objective="exploratory")
        catalog.write_scientific_objective(
            sid,
            "regression",
            description="Sensitivity sweep",
            doi="10.5281/zenodo.0",
            outlet_x=247_500.0,
            outlet_y=6_770_000.0,
        )
        row = catalog._db.execute(
            "SELECT scientific_objective, description, doi, outlet_x, outlet_y "
            "FROM simulations WHERE sim_id = ?",
            [sid],
        ).fetchone()
        assert row == (
            "regression",
            "Sensitivity sweep",
            "10.5281/zenodo.0",
            247_500.0,
            6_770_000.0,
        )

    def test_finalize_defaults_objective_when_missing(self, catalog):
        sid = str(uuid4())
        catalog.register_simulation(sid, project="so2", solver="gr4j")
        catalog.finalize(sid, status="completed", duration_s=0.1)
        row = catalog._db.execute(
            "SELECT scientific_objective FROM simulations WHERE sim_id = ?",
            [sid],
        ).fetchone()
        assert row[0] == "unspecified"
