"""Reproducibility of the Whitebox delineation chain.

Whitebox resolves flats and equal-cost ties in worker-completion order, so its
parallel depression removal returns a different corrected DEM on every call.
The catchment area recorded in a run manifest is a cell count on that DEM, and
it converts water depths into discharges, so a drift there silently changes
results. Depression removal therefore runs on a single worker.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.spatial.delineation.whitebox_workflows_backend import (
    WhiteboxWorkflowsBackend,
)
from hydromodpy.spatial.terrain import LN_FLOAT32_COLLISION_COUNT

wbw = pytest.importorskip("whitebox_workflows")
rasterio = pytest.importorskip("rasterio")

REPO_ROOT = Path(__file__).resolve().parents[3]


def _to_numpy(backend, raster) -> np.ndarray:
    """Read a Whitebox raster back as an array, through the file it writes."""
    with tempfile.TemporaryDirectory() as scratch:
        path = Path(scratch) / "raster.tif"
        backend.raster.write_raster(raster, str(path))
        with rasterio.open(str(path)) as src:
            return src.read(1)


@pytest.fixture
def rough_dem(tmp_path):
    """Write a noisy slope DEM quantized to 0.5 m steps.

    Quantization is what makes this a regression test rather than a smoke test:
    equal-elevation plateaus are where the parallel depression removal has ties
    to break, and a continuous surface reproduces at any size. Production DEMs
    ship quantized elevations (BD ALTI stores decimetres), so the flats are the
    realistic case, not the pathological one.
    """
    rng = np.random.default_rng(12345)
    rows, cols = 400, 400
    yy, xx = np.mgrid[0:rows, 0:cols]
    surface = 100.0 + 0.05 * xx + 0.02 * yy + rng.normal(0.0, 0.4, size=(rows, cols))
    surface = np.round(surface * 2.0) / 2.0
    path = tmp_path / "rough_dem.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=rows,
        width=cols,
        count=1,
        dtype="float32",
        crs="EPSG:2154",
        transform=rasterio.transform.from_origin(300000.0, 6800000.0, 25.0, 25.0),
        nodata=-99999.0,
    ) as dst:
        dst.write(surface.astype("float32"), 1)
    return path


def _digest(raster) -> bytes:
    configs = raster.configs
    data = np.empty((configs.rows, configs.columns), dtype="float64")
    for row in range(configs.rows):
        data[row, :] = raster.get_row_data(row)
    return np.ascontiguousarray(data).tobytes()


def test_single_threaded_pins_and_restores_the_worker_count() -> None:
    backend = WhiteboxWorkflowsBackend()
    before = backend.raster._env.max_procs
    with backend.raster.single_threaded():
        assert backend.raster._env.max_procs == 1
    assert backend.raster._env.max_procs == before


def test_single_threaded_restores_the_worker_count_after_a_failure() -> None:
    backend = WhiteboxWorkflowsBackend()
    before = backend.raster._env.max_procs
    with pytest.raises(RuntimeError), backend.raster.single_threaded():
        raise RuntimeError("boom")
    assert backend.raster._env.max_procs == before


@pytest.mark.parametrize("correction", ["breach_depressions_raster", "fill_depressions_raster"])
def test_depression_removal_runs_on_one_worker(monkeypatch, rough_dem, correction) -> None:
    """The DEM correction must see ``max_procs == 1`` while it runs."""
    backend = WhiteboxWorkflowsBackend()
    dem = backend.raster.read_raster(str(rough_dem))
    seen: list[int] = []
    original = backend.raster._run_env_operation

    def spy(operation, *args, **kwargs):
        seen.append(backend.raster._env.max_procs)
        return original(operation, *args, **kwargs)

    monkeypatch.setattr(backend.raster, "_run_env_operation", spy)
    getattr(backend.flow, correction)(dem)

    assert seen == [1]


@pytest.mark.parametrize("correction", ["breach_depressions_raster", "fill_depressions_raster"])
def test_depression_removal_is_reproducible(rough_dem, correction) -> None:
    """Repeating a correction on the same DEM must return the same raster."""
    backend = WhiteboxWorkflowsBackend()
    dem = backend.raster.read_raster(str(rough_dem))
    digests = {_digest(getattr(backend.flow, correction)(dem)) for _ in range(3)}

    assert len(digests) == 1


def test_flow_products_are_reproducible(rough_dem) -> None:
    """Corrected DEM, D8 pointer and accumulation must repeat bit for bit."""
    backend = WhiteboxWorkflowsBackend()
    dem = backend.raster.read_raster(str(rough_dem))
    stacks = []
    for _ in range(3):
        correc = backend.flow.breach_depressions_raster(dem)
        direc = backend.flow.d8_pointer_raster(correc, esri_pntr=False)
        acc = backend.flow.d8_flow_accumulation_raster(correc, log=True)
        stacks.append((_digest(correc), _digest(direc), _digest(acc)))

    assert len(set(stacks)) == 1


COMMITTED_DEMS = [
    "examples/data/dem/DEM_gouville_25m.tif",
    "examples/data/dem/DEM_nancon_50m.tif",
    "examples/data/dem/regional_dem_naizin.tif",
    "tests/data/sfr_cheze/dem_valley.tif",
]


@pytest.mark.parametrize("dem_name", COMMITTED_DEMS)
def test_accumulating_the_pointer_equals_accumulating_the_dem(dem_name) -> None:
    """The equivalence the terrain port stands on, on real committed DEMs.

    ``build_regional_flow_products`` used to accumulate the conditioned DEM
    directly; it now accumulates the D8 pointer the same chain derives, because
    that is what lets ``FlowAccumulation`` declare the pointer it descends. The
    two are equal, and this is where that is checked rather than asserted: the
    rasters ``dem_acc.tif`` carries drive every catchment, every snap and every
    river network downstream, so the two paths have to agree **bit for bit**,
    not within a band.
    """
    dem_path = REPO_ROOT / dem_name
    backend = WhiteboxWorkflowsBackend()
    dem = backend.raster.read_raster(str(dem_path))
    correc = backend.flow.fill_depressions_raster(dem)
    pointer = backend.flow.d8_pointer_raster(correc, esri_pntr=False)

    from_dem = backend.flow.d8_flow_accumulation_raster(correc, log=True)
    from_pointer = backend.flow.d8_flow_accumulation_raster(
        pointer,
        log=True,
        out_type="cells",
        input_is_pointer=True,
    )

    assert _digest(from_pointer) == _digest(from_dem)


@pytest.mark.parametrize("dem_name", COMMITTED_DEMS)
def test_the_natural_logarithm_folds_no_count_of_these_dems(dem_name) -> None:
    """Anti-vacuity for the bound the port enforces on a transformed snap.

    ``LN_FLOAT32_COLLISION_COUNT`` says float32 stops telling neighbouring cell
    counts apart at 1 049 558. That claim is only worth something if the rasters
    this repository actually routes stay under it, so this counts the distinct
    values on both sides and refuses a fold.
    """
    dem_path = REPO_ROOT / dem_name
    backend = WhiteboxWorkflowsBackend()
    dem = backend.raster.read_raster(str(dem_path))
    correc = backend.flow.fill_depressions_raster(dem)
    counts = _to_numpy(backend, backend.flow.d8_flow_accumulation_raster(correc, log=False))
    logged = _to_numpy(backend, backend.flow.d8_flow_accumulation_raster(correc, log=True))

    valid = np.isfinite(counts) & (counts > 0)
    assert float(counts[valid].max()) < LN_FLOAT32_COLLISION_COUNT
    assert np.unique(logged[valid]).size == np.unique(counts[valid]).size
