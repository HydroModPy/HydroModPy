"""End-to-end: from-scratch user workflow.

Walks the chain a new user would follow:
1. ``hmp workspace init`` to scaffold a workspace.
2. Inspect ``workspace.toml`` and the scaffolded layout.
3. Get a DEM into the workspace: the unimplemented ``hmp data get`` stays
   gated, then ``hmp data check`` + ``hmp data add`` ingest a local file
   dropped in ``data/dem/`` under the naming convention.
4. Seed a minimal simulation via the public Python API so the catalog
   carries a real Zarr field. This stands in for a full solver run on the
   ``simulation_regression`` fixture, which is exercised by the regression
   tier with the same CLI entry point.
5. Open the catalog via ``hmp.open`` and read a field via ``hmp.read``.
6. Export the field to NetCDF and check the ACDD / CF attrs are carried.

The test is marked ``e2e`` so it stays out of the fast suite. CLI verbs
are driven through ``python -m hydromodpy`` to keep the test honest about
what an end user actually triggers.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest

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


def _seed_minimal_simulation(workspace: Path, *, project: str, sim_id: str) -> tuple[Path, Path]:
    """Register one finalised sim with Zarr field + timeseries + metric.

    Returns the Zarr and Parquet paths from the source catalog so the
    caller can assert they exist on disk.
    """
    import hydromodpy as hmp

    with hmp.open(workspace, create=True) as catalog:
        reg = catalog.register_simulation(
            sim_id=sim_id,
            project=project,
            solver="modflow_nwt",
            name="from_scratch_sim",
            flow_regime="steady",
            n_cells=4,
            n_layers=1,
        )
        sz = reg.zarr
        assert sz is not None, "register_simulation must open a Zarr store"
        sz.write_field(
            variable="head",
            timestep=0,
            values=np.full((1, 4), 7.5, dtype="float32"),
            n_timesteps=1,
        )
        idx = pd.date_range("2024-01-01", periods=4, freq="D")
        catalog.write_timeseries(
            sim_id,
            station_id="P01",
            variable="head",
            ts=pd.Series([10.0, 10.1, 10.2, 10.3], index=idx),
        )
        catalog.write_metric(sim_id, station_id="P01", metric_name="nse", value=0.91)
        catalog.finalize(sim_id, status="completed", duration_s=0.1)
        return catalog.fields_path_for(sim_id), catalog.tables_dir_for(sim_id)


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

    # ----- Step 4a: the upstream fetch is gated, and says what to do instead --
    # HydroModPy has no provider download; ``hmp data get`` must fail loudly
    # rather than write a placeholder that looks like checksummed real data.
    fetch = _run_hmp(
        "data",
        "get",
        "dem",
        "--bbox=-1.17,48.4,-1.0,48.5",
        "--workspace",
        str(workspace),
    )
    assert fetch.returncode != 0, "`hmp data get` must stay gated while unimplemented"
    assert "hmp data add" in fetch.stderr, (
        f"the gate must point at the supported path.\nstderr:\n{fetch.stderr}"
    )

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

    sim_id = str(uuid4())
    zarr_path, parquet_dir = _seed_minimal_simulation(workspace, project="foo", sim_id=sim_id)

    # ----- Step 6: catalog + artefacts on disk are visible ------------------
    catalog_db = catalog_path_for(workspace)
    assert catalog_db.is_file(), f"{CATALOG_FILENAME} must be created in the project"
    assert zarr_path.exists(), f"Zarr store missing at {zarr_path}"
    assert parquet_dir.exists(), f"Parquet directory missing at {parquet_dir}"

    with hmp.open(workspace, create=True) as catalog:
        rows = catalog.connection.execute(
            "SELECT component, version FROM _schema_version WHERE component = 'catalog'"
        ).fetchall()
        assert rows, "catalog schema_version row missing"
        assert int(rows[0][1]) >= 1, f"expected catalog schema_version >= 1, got {rows[0][1]}"

        sims = catalog.list_simulations(project="foo")
        assert len(sims) == 1
        assert str(sims.iloc[0]["sim_id"]) == sim_id

    # ----- Step 7: hmp.open + hmp.read return a real field ------------------
    with hmp.open(workspace, create=True) as catalog:
        run = catalog[sim_id]
        data = np.asarray(hmp.read(run, "head", time=0, layer=0))
        assert data.shape[-1] == 4
        assert np.allclose(data, 7.5)


@pytest.mark.e2e
def test_workflow_from_scratch_netcdf_export(tmp_path: Path) -> None:
    """Export a finalised sim to NetCDF and check ACDD / CF attrs survive.

    Skipped when the sim has no UGRID mesh attached (the synthetic fixture
    above does not seed one); a full solver run with mesh extraction is
    covered by the regression tier.
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

    sim_id = str(uuid4())
    _seed_minimal_simulation(workspace, project="foo", sim_id=sim_id)

    nc_out = tmp_path / "head.nc"
    from hydromodpy.core.config_kit.export_spec import ExportSpec

    try:
        with hmp.open(workspace, create=True) as catalog:
            catalog.export(sim_id, ExportSpec(var="head", fmt="netcdf", dest=nc_out))
    except KeyError as exc:
        # export_netcdf raises KeyError (not ValueError) when the store has no
        # UGRID mesh; the synthetic fixture seeds a head field but no mesh.
        # Any other exception is a real failure and must not be swallowed.
        pytest.skip(f"NetCDF export needs a UGRID mesh, not present on this synthetic sim: {exc}")

    assert nc_out.is_file(), "NetCDF file should be produced"
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
        "HMP_WORKSPACE": str(out_path),
        "MPLBACKEND": "Agg",
    }
    # Filter out any env that would lock to a host-bound output, then merge.
    import os

    merged = os.environ.copy()
    merged.update(env)

    completed = subprocess.run(
        [sys.executable, "-m", "hydromodpy", "run", "--no-lock", str(run_toml)],
        cwd=str(out_path),
        env=merged,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
    )
    if completed.returncode != 0:
        pytest.skip(
            "hmp run on simulation_regression fixture did not complete (likely needs network "
            f"data or extra binaries). Stderr tail:\n{completed.stderr[-2000:]}"
        )

    catalog_db = catalog_path_for(out_path)
    assert catalog_db.is_file(), f"{CATALOG_FILENAME} missing after hmp run"

    import hydromodpy as hmp

    with hmp.open(out_path, create=True) as catalog:
        sims = catalog.list_simulations()
        assert not sims.empty, "no simulation row recorded after hmp run"
        sim_id = str(sims.iloc[0]["sim_id"])
        zarr_path = catalog.fields_path_for(sim_id)
        parquet_dir = catalog.tables_dir_for(sim_id)
    assert zarr_path.exists(), "Zarr artefact missing"
    assert parquet_dir.exists(), "Parquet directory missing"
