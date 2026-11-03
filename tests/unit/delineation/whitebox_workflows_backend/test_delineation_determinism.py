"""Reproducibility of the Whitebox delineation chain.

Whitebox breaks ties in worker-completion order, so a parallel depression removal
drifts between calls, and with it the catchment area of a run manifest. It runs
on a single worker.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.spatial.delineation.whitebox_workflows_backend import WhiteboxWorkflowsBackend
from hydromodpy.spatial.delineation.whitebox_workflows_backend import component as component_module
from hydromodpy.spatial.terrain import LN_FLOAT32_COLLISION_COUNT
from tests._helpers.geotiffs import write_geotiff

wbw = pytest.importorskip("whitebox_workflows")
rasterio = pytest.importorskip("rasterio")

REPO_ROOT = Path(__file__).resolve().parents[4]

# Depression removal runs in a child interpreter, see whitebox_workflows_backend.isolated.
pytestmark = pytest.mark.allow_subprocess


def _to_numpy(backend, raster) -> np.ndarray:
    """Read a Whitebox raster back as an array, through the file it writes."""
    with tempfile.TemporaryDirectory() as scratch:
        path = Path(scratch) / "raster.tif"
        backend.raster.write_raster(raster, str(path))
        with rasterio.open(str(path)) as src:
            return src.read(1)


def _digest(raster) -> bytes:
    rows = raster.configs.rows
    return np.array([raster.get_row_data(row) for row in range(rows)], dtype="float64").tobytes()


@pytest.fixture
def rough_dem(tmp_path):
    """A noisy slope quantized to 0.5 m, as BD ALTI stores decimeters.

    The plateaus are where the parallel depression removal has ties to break; a
    continuous surface reproduces at any size.
    """
    rng = np.random.default_rng(12345)
    yy, xx = np.mgrid[0:400, 0:400]
    surface = 100.0 + 0.05 * xx + 0.02 * yy + rng.normal(0.0, 0.4, size=(400, 400))
    return write_geotiff(
        tmp_path / "rough_dem.tif", np.round(surface * 2.0) / 2.0, origin=(300000.0, 6800000.0),
        cell=25.0, nodata=-99999.0, dtype="float32",
    )  # fmt: skip


def test_single_threaded_pins_and_restores_the_worker_count_even_after_a_failure() -> None:
    backend = WhiteboxWorkflowsBackend()
    before = backend.raster.env.max_procs
    with backend.raster.single_threaded():
        assert backend.raster.env.max_procs == 1
    assert backend.raster.env.max_procs == before
    with pytest.raises(RuntimeError), backend.raster.single_threaded():
        raise RuntimeError("boom")
    assert backend.raster.env.max_procs == before


@pytest.mark.parametrize("correction", ["breach_depressions_raster", "fill_depressions_raster"])
def test_depression_removal_runs_on_one_worker_and_is_reproducible(
    monkeypatch, rough_dem, correction
) -> None:
    """Each child running the DEM correction is handed one worker, and the raster repeats."""
    backend = WhiteboxWorkflowsBackend()
    dem = backend.raster.read_raster(str(rough_dem))
    seen: list[int] = []
    original = component_module.run_depression_tool

    def spy(env, tool, raster, **kwargs):
        seen.append(kwargs["max_procs"])
        return original(env, tool, raster, **kwargs)

    monkeypatch.setattr(component_module, "run_depression_tool", spy)
    digests = {_digest(getattr(backend.flow, correction)(dem)) for _ in range(3)}

    assert seen == [1, 1, 1]
    assert len(digests) == 1


def test_flow_products_are_reproducible(rough_dem) -> None:
    """Corrected DEM, D8 pointer and accumulation must repeat bit for bit."""
    backend = WhiteboxWorkflowsBackend()
    dem = backend.raster.read_raster(str(rough_dem))
    stacks = set()
    for _ in range(3):
        correc = backend.flow.breach_depressions_raster(dem)
        direc = backend.flow.d8_pointer_raster(correc, esri_pntr=False)
        acc = backend.flow.d8_flow_accumulation_raster(correc, log=True)
        stacks.add((_digest(correc), _digest(direc), _digest(acc)))
    assert len(stacks) == 1


@pytest.mark.parametrize(
    "dem_name",
    [
        "examples/data/dem/DEM_gouville_25m.tif",
        "examples/data/dem/DEM_nancon_50m.tif",
        "examples/data/dem/regional_dem_naizin.tif",
        "tests/data/sfr_cheze/dem_valley.tif",
    ],
)
def test_accumulating_the_pointer_equals_accumulating_the_dem_and_ln_folds_no_count(
    dem_name,
) -> None:
    """Two properties the terrain port stands on, on the committed DEMs.

    ``build_regional_flow_products`` accumulates the D8 pointer rather than the
    conditioned DEM, so both must agree bit for bit. And float32 stops telling
    counts apart at ``LN_FLOAT32_COLLISION_COUNT``: the routed rasters stay under
    it, and their ``ln`` folds no two counts (anti-vacuity of the port's bound).
    """
    backend = WhiteboxWorkflowsBackend()
    correc = backend.flow.fill_depressions_raster(
        backend.raster.read_raster(str(REPO_ROOT / dem_name))
    )
    pointer = backend.flow.d8_pointer_raster(correc, esri_pntr=False)
    from_dem = backend.flow.d8_flow_accumulation_raster(correc, log=True)
    from_pointer = backend.flow.d8_flow_accumulation_raster(
        pointer, log=True, out_type="cells", input_is_pointer=True
    )
    counts = _to_numpy(backend, backend.flow.d8_flow_accumulation_raster(correc, log=False))
    logged = _to_numpy(backend, from_dem)

    assert _digest(from_pointer) == _digest(from_dem)
    valid = np.isfinite(counts) & (counts > 0)
    assert float(counts[valid].max()) < LN_FLOAT32_COLLISION_COUNT
    assert np.unique(logged[valid]).size == np.unique(counts[valid]).size
