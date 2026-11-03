"""End-to-end: from-scratch user workflow.

Walks the chain a new user would follow:
1. ``hmp workspace init`` to scaffold a workspace.
2. Inspect ``workspace.toml`` and the scaffolded layout.
3. Get a DEM into the workspace: ``hmp data get`` refuses a box without
   its CRS, ``hmp data check`` + ``hmp data add`` ingest a local file
   dropped in ``data/dem/`` under the naming convention, and a request
   document serves that DEM cut to a smaller box.
4. Seed a minimal run through the store of a run, seal it and index it, so
   the project carries a real Zarr field. This stands in for a full solver run on the
   ``simulation_regression`` fixture, which is exercised by the regression
   tier with the same CLI entry point.
5. Open the project via ``hmp.open``, read its index through ``.store`` and
   read a field via ``hmp.read``.
6. Export the field to NetCDF and check the ACDD / CF attrs are carried.

The test is marked ``e2e`` so it stays out of the fast suite. CLI verbs
are driven through ``python -m hydromodpy`` to keep the test honest about
what an end user actually triggers.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import rasterio

from hydromodpy.core.state.paths import CATALOG_FILENAME, catalog_path_for

_FIXTURE_DEM = Path(__file__).resolve().parents[1] / "data" / "sfr_cheze" / "dem_valley.tif"


def _run_hmp(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run ``python -m hydromodpy <args>`` and return the completed process."""
    cmd = [sys.executable, "-m", "hydromodpy", *args]
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=600,
    )


def _seed_minimal_simulation(workspace: Path, *, project: str) -> tuple[str, Path, Path, Path]:
    """Write, seal and index one run with a mesh, a head field and a series.

    The run is written the way the pipeline writes it: claimed under
    ``projects/<project>/runs/``, filled through its store, sealed, its
    attempt closed, then the index rebuilt from disk. Returns the ``sim_id``,
    the project directory, and the field store and tables of the run.
    """
    from hydromodpy.results.catalog.indexer import index_new_runs
    from hydromodpy.results.storage.attempt import close_sealed_attempt
    from hydromodpy.results.storage.sealing import seal_completed
    from tests._helpers.run_stores import open_run_store

    project_dir = workspace / "projects" / project
    store = open_run_store(
        project_dir,
        "from_scratch_sim",
        n_cells=4,
        n_layers=1,
        n_timesteps=1,
        solver="modflow_nwt",
        flow_regime="steady",
        crs_epsg=2154,
        crs_wkt="EPSG:2154",
    )
    sim_id = store.sim_id
    x0, y0, step = 385000.0, 6814000.0, 500.0
    verts = np.array(
        [[x0 + i * step, y0 + j * step] for j in range(3) for i in range(3)], dtype="float64"
    )
    conn = np.array([[0, 1, 4, 3], [1, 2, 5, 4], [3, 4, 7, 6], [4, 5, 8, 7]], dtype="int32")
    store.write_mesh(sim_id, verts, conn, np.array([50.0, 0.0]))
    store.write_crs(sim_id, crs_wkt="EPSG:2154", epsg_code=2154)
    stamp = pd.to_datetime(["2024-01-01"]).values.astype("datetime64[s]").astype("int64")
    store.write_time(sim_id, stamp)
    store.write_field(sim_id, "head", 0, np.full((1, 4), 7.5, dtype="float32"), n_timesteps=1)
    idx = pd.date_range("2024-01-01", periods=4, freq="D")
    store.write_timeseries(sim_id, "P01", "head", pd.Series([10.0, 10.1, 10.2, 10.3], index=idx))
    run_dir = store.run_dir
    fields, tables = store.fields_path, store.tables_dir
    seal_completed(store)
    close_sealed_attempt(run_dir)
    index_new_runs(project_dir)
    return sim_id, project_dir, fields, tables


@pytest.mark.e2e
def test_workflow_from_scratch_init_and_catalog(tmp_path: Path) -> None:
    """Drive ``hmp workspace init`` + ``hmp data fetch`` + catalog access end-to-end."""
    workspace = tmp_path / "fresh_workspace"

    # ----- Step 1: hmp workspace init ----------------------------------------
    result = _run_hmp(
        "workspace",
        "init",
        str(workspace),
        "--project-name",
        "foo",
        "--creator-name",
        "Test User",
        "--creator-email",
        "test@example.com",
    )
    assert result.returncode == 0, (
        f"`hmp workspace init` failed (rc={result.returncode}).\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert workspace.is_dir()

    # ----- Step 2: workspace.toml carries the fields we passed --------------
    workspace_toml = workspace / "workspace.toml"
    assert workspace_toml.is_file(), "workspace.toml must be created by hmp workspace init"
    metadata = tomllib.loads(workspace_toml.read_text(encoding="utf-8"))
    assert metadata["workspace"]["name"] == "foo"
    assert metadata["workspace"]["contact"] == "test@example.com"
    assert "Test User" in metadata["workspace"]["team"]["members"]
    assert metadata["conventions"]["cf"].startswith("CF-")
    assert metadata["conventions"]["acdd"].startswith("ACDD-")

    # ----- Step 3: scaffold layout exposes the data drop zones --------------
    # Each variable gets a flat ``data/<variable>/`` folder; the provider is
    # encoded in the file name (``<variable>_custom_*`` vs ``<variable>_<api>_*``).
    assert (workspace / "data").is_dir()
    assert (workspace / "projects").is_dir()
    for variable in ("dem", "piezometry", "hydrometry"):
        assert (workspace / "data" / variable).is_dir(), f"data/{variable} missing"

    # ----- Step 4a: a request with a box but no CRS is refused ---------------
    refused_out = tmp_path / "refused"
    refused = _run_hmp(
        "data",
        "get",
        "dem",
        "--bbox=-1.17,48.4,-1.0,48.5",
        "--to",
        str(refused_out),
    )
    assert refused.returncode == 14, f"stderr:\n{refused.stderr}"
    assert "crs" in refused.stderr
    assert not refused_out.exists(), "a refused request writes nothing"

    # ----- Step 4b: the supported path - drop zone + hmp data add -----------
    dem_dir = workspace / "data" / "dem"
    assert dem_dir.is_dir(), "hmp workspace init must scaffold data/<variable>/"
    dem_file = dem_dir / "dem_custom_valley.tif"
    shutil.copyfile(_FIXTURE_DEM, dem_file)

    check = _run_hmp("data", "check", "--variable", "dem", "--workspace", str(workspace))
    assert check.returncode == 0, f"`hmp data check` failed.\nstderr:\n{check.stderr}"
    assert "OK" in check.stdout

    added = _run_hmp("data", "add", str(dem_file), "--type", "dem", "--workspace", str(workspace))
    assert added.returncode == 0, f"`hmp data add` failed.\nstderr:\n{added.stderr}"
    blob = workspace / "data" / "blobs" / "dem" / "custom" / dem_file.name
    assert blob.is_file(), "hmp data add must pivot the raster into data/blobs/"

    # ----- Step 4c: a request document serves the DEM cut to its box ---------
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "data": {"dem": {"sources": [{"source": "custom", "path": str(dem_file)}]}},
                "extent": {"bbox": [300000, 6700000, 301250, 6701250], "crs": "EPSG:2154"},
            }
        ),
        encoding="utf-8",
    )
    served_out = tmp_path / "served"
    served = _run_hmp("data", "get", str(request), "--to", str(served_out))
    assert served.returncode == 0, f"`hmp data get` failed.\nstderr:\n{served.stderr}"
    report = json.loads((served_out / "request.json").read_text(encoding="utf-8"))
    (entry,) = report["files"]
    assert entry["kind"] == "raster"
    with rasterio.open(served_out / entry["path"]) as cut:
        assert (cut.width, cut.height) == (50, 50)

    listed = _run_hmp("data", "ls", "--workspace", str(workspace))
    assert listed.returncode == 0, f"`hmp data ls` failed.\nstderr:\n{listed.stderr}"
    assert dem_file.name in listed.stdout

    # ----- Step 5: seed a minimal simulation via the Python API -------------
    # We do not invoke the solver here. A real ``hmp run`` on
    # ``tests/regression/fixtures/projects/simulation_regression/`` is covered
    # by the regression tier; this step only checks that the catalog,
    # Zarr field and Parquet artefacts that ``hmp run`` is supposed to
    # produce can be queried back via the user-facing API.
    import hydromodpy as hmp

    sim_id, project_dir, zarr_path, parquet_dir = _seed_minimal_simulation(workspace, project="foo")

    # ----- Step 6: index + artefacts on disk are visible --------------------
    catalog_db = catalog_path_for(project_dir)
    assert catalog_db.is_file(), f"{CATALOG_FILENAME} must be built in the project"
    assert zarr_path.exists(), f"Zarr store missing at {zarr_path}"
    assert parquet_dir.exists(), f"Parquet directory missing at {parquet_dir}"

    with hmp.open(project_dir).store as catalog:
        sims = catalog.list_simulations()
        assert len(sims) == 1
        assert str(sims.iloc[0]["sim_id"]) == sim_id

    # ----- Step 7: hmp.open(...).store + hmp.read return a real field -------
    with hmp.open(project_dir).store as catalog:
        run = catalog[sim_id]
        data = np.asarray(hmp.read(run, "head", time=0, layer=0))
        assert data.shape[-1] == 4
        assert np.allclose(data, 7.5)


@pytest.mark.e2e
def test_workflow_from_scratch_netcdf_export(tmp_path: Path) -> None:
    """Export a sealed run to NetCDF and check ACDD / CF attrs survive.

    The file lands under ``runs/<run>/exports/`` and carries the id of the run.
    """
    import hydromodpy as hmp

    workspace = tmp_path / "fresh_workspace"
    init = _run_hmp(
        "workspace",
        "init",
        str(workspace),
        "--project-name",
        "foo",
        "--creator-name",
        "Test User",
        "--creator-email",
        "test@example.com",
    )
    assert init.returncode == 0

    sim_id, project_dir, _zarr, _tables = _seed_minimal_simulation(workspace, project="foo")

    from hydromodpy.core.config_kit.export_spec import ExportRequest
    from hydromodpy.results.exporters.request import export_run

    with hmp.open(project_dir).store as catalog:
        written = export_run(catalog, sim_id, ExportRequest(variables="head", file="head.nc"))

    nc_out = project_dir / "runs" / "from_scratch_sim" / "exports" / "head.nc"
    assert written == [nc_out], "NetCDF file should be produced under the run"
    import xarray as xr

    with xr.open_dataset(nc_out) as ds:
        assert "Conventions" in ds.attrs
        assert "ACDD" in ds.attrs["Conventions"] or "CF-" in ds.attrs["Conventions"]
        assert ds.attrs.get("simulation_id") == sim_id


@pytest.mark.e2e
def test_workflow_from_scratch_run_simulation_regression_fixture(tmp_path: Path) -> None:
    """Best-effort: drive ``hmp run`` on the simulation_regression fixture.

    Skipped automatically when the required solver binaries are unavailable
    or when the fixture toml carries data sources that need network access.
    """
    fixture_dir = (
        Path(__file__).resolve().parents[1]
        / "regression"
        / "fixtures"
        / "projects"
        / "simulation_regression"
    )
    run_toml = fixture_dir / "run_fast_nwt.toml"
    if not run_toml.is_file():
        pytest.skip(f"simulation_regression fixture not found at {run_toml}")

    # Solver binary gate: skip rather than fail when binaries are missing.
    from hydromodpy.core.workspace.workspace import resolve_bin_path
    from hydromodpy.solver.modflow_common.binaries import locate_solver_binary

    bin_dir = Path(resolve_bin_path())
    missing = [
        name for name in ("mfnwt", "mp6", "mt3dusgs") if locate_solver_binary(bin_dir, name) is None
    ]
    if missing:
        pytest.skip(
            f"required solver binaries missing: {missing}. Run `hmp install-binaries` first."
        )

    out_path = tmp_path / "run_out"
    out_path.mkdir(parents=True, exist_ok=True)
    env = {
        "HMP_PROJECT_ROOT": str(out_path),
        "MPLBACKEND": "Agg",
    }
    # Filter out any env that would lock to a host-bound output, then merge.
    import os

    merged = os.environ.copy()
    merged.update(env)

    completed = subprocess.run(
        [sys.executable, "-m", "hydromodpy", "run", str(run_toml)],
        cwd=str(out_path),
        env=merged,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
    )
    # The binary gate above already skipped when a solver was missing, and CI
    # installs mfnwt/mp6/mt3dusgs before this tier runs. A non-zero exit past
    # that point is a real pipeline failure, not an environment gap: skipping
    # here turned every `hmp run` crash into a green tick.
    assert completed.returncode == 0, (
        "hmp run on the simulation_regression fixture failed with exit code "
        f"{completed.returncode}.\nStderr tail:\n{completed.stderr[-2000:]}"
    )

    catalog_db = catalog_path_for(out_path)
    assert catalog_db.is_file(), f"{CATALOG_FILENAME} missing after hmp run"

    import hydromodpy as hmp

    with hmp.open(out_path).store as catalog:
        sims = catalog.list_simulations()
        assert not sims.empty, "no simulation row recorded after hmp run"
        sim_id = str(sims.iloc[0]["sim_id"])
        zarr_path = catalog.fields_path_for(sim_id)
        parquet_dir = catalog.tables_dir_for(sim_id)
    assert zarr_path.exists(), "Zarr artefact missing"
    assert parquet_dir.exists(), "Parquet directory missing"
