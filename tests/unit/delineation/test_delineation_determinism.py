"""Reproducibility of the Whitebox delineation chain.

Whitebox resolves flats and equal-cost ties in worker-completion order, so its
parallel depression removal returns a different corrected DEM on every call.
The catchment area recorded in a run manifest is a cell count on that DEM, and
it converts water depths into discharges, so a drift there silently changes
results. Depression removal therefore runs on a single worker.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.spatial.delineation.whitebox_workflows_backend import (
    WhiteboxWorkflowsBackend,
)

wbw = pytest.importorskip("whitebox_workflows")
rasterio = pytest.importorskip("rasterio")


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
