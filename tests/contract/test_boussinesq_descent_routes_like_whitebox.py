"""The descent a Boussinesq run stores routes like the Whitebox D8 mass flux.

Boussinesq used to route its accumulation fluxes once per step with Whitebox:
fill the depressions of the top raster, then ``d8_mass_flux`` with an
efficiency of 1 and no absorption on the valid cells. The extractor now stores
the D8 pointer of that filled raster as the descent D, and the read side routes
on D with :func:`accumulate_on_downhill_graph`. Both must give the same upstream
sum on a grid with a pit and a flat, where the fill decides the routing.

``d8_mass_flux`` writes float32, so the two agree to float32 rounding only:
half an ulp is 6e-8 relative, and ``rtol=1e-6`` leaves room for a float32 sum
along the short chains of this grid. Both sides use the same pointer, so a
routing difference would show as an order-one error, far above it.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest

from hydromodpy.core.config_kit.persistence import PersistenceConfig
from hydromodpy.core.descent import descent_graph
from hydromodpy.core.field_routing import accumulate_on_downhill_graph
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.derive.accumulation import accumulation_flux_rows
from hydromodpy.solver.boussinesq.extractors.flow import BoussinesqOutputAdapter

pytest.importorskip("whitebox_workflows")
rasterio = pytest.importorskip("rasterio")

# Whitebox's native binding is not fork-safe under xdist distribution.
pytestmark = pytest.mark.xdist_group(name="whitebox_backend")

NROW, NCOL = 6, 7
N_CELLS = NROW * NCOL
NODATA = -99999.0
RTOL_FLOAT32 = 1.0e-6


def _top() -> np.ndarray:
    """A plane tilted east and south, with a pit and a flat terrace."""
    rows, cols = np.mgrid[0:NROW, 0:NCOL]
    rng = np.random.default_rng(7)
    top = 30.0 - 1.0 * cols - 0.3 * rows + rng.uniform(0.0, 0.2, (NROW, NCOL))
    top[2, 3] = 18.0
    top[4, 1:4] = 26.0
    return top


def _write_raster(path: Path, data: np.ndarray) -> None:
    from rasterio.crs import CRS
    from rasterio.transform import from_bounds

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=NROW,
        width=NCOL,
        count=1,
        dtype=data.dtype,
        nodata=NODATA,
        transform=from_bounds(0, 0, NCOL, NROW, NCOL, NROW),
        crs=CRS.from_epsg(2154),
    ) as dst:
        dst.write(data, 1)


def _read_raster(path: Path) -> np.ndarray:
    with rasterio.open(path) as src:
        return np.asarray(src.read(1), dtype="float64")


def _whitebox_mass_flux(top: np.ndarray, loads: np.ndarray, tmp: Path) -> np.ndarray:
    """Route each load the way the per-step Whitebox routing did."""
    from hydromodpy.spatial.delineation import get_whitebox_backend

    wb = get_whitebox_backend()
    _write_raster(tmp / "dem.tif", top)
    wb.flow.fill_depressions(str(tmp / "dem.tif"), str(tmp / "fill.tif"))
    filled = _read_raster(tmp / "fill.tif")
    valid = np.isfinite(filled) & (filled > -9000.0)
    _write_raster(tmp / "eff.tif", np.where(valid, 1.0, NODATA))
    _write_raster(tmp / "abs.tif", np.where(valid, 0.0, NODATA))
    out = np.empty(loads.shape, dtype="float64")
    for step, load in enumerate(loads):
        _write_raster(tmp / "load.tif", load.reshape(NROW, NCOL))
        wb.flow.d8_mass_flux(
            str(tmp / "fill.tif"),
            str(tmp / "load.tif"),
            str(tmp / "eff.tif"),
            str(tmp / "abs.tif"),
            str(tmp / "acc.tif"),
        )
        out[step] = _read_raster(tmp / "acc.tif").reshape(-1)
    return out


@pytest.fixture
def extracted(tmp_path: Path):
    top = _top().reshape(-1)
    rng = np.random.default_rng(11)
    # Drain outflow, positive out of the aquifer as the solver signs it.
    drain = np.vstack([np.zeros(N_CELLS), rng.uniform(0.0, 1.0, (2, N_CELLS))])
    output_dir = tmp_path / "solver"
    output_dir.mkdir()
    np.savez(
        output_dir / "_boussinesq_state_history.npz",
        head_history_m=np.vstack([top - 1.0] * 3),
        snapshot_elapsed_seconds=np.asarray([0.0, 86400.0, 172800.0]),
        period_lengths_seconds=np.asarray([86400.0, 86400.0]),
        drainage_flux_history_m3_s=drain,
        z_top_m=top,
        z_bottom_m=top - 20.0,
        cell_area_m2=np.full(N_CELLS, 625.0),
    )
    (output_dir / "_boussinesq_summary.json").write_text(json.dumps({}), encoding="utf-8")

    catalog = Catalog(
        tmp_path / "workspace", persistence=PersistenceConfig(field_precision="exact")
    )
    sim_id = str(uuid4())
    registration = catalog.register_simulation(
        sim_id, project="test", solver="boussinesq", n_cells=N_CELLS, n_layers=1, n_timesteps=2
    )
    if registration.zarr is not None:
        registration.zarr.close()
    catalog.write_geographic_metadata(sim_id, {"nrow": NROW, "ncol": NCOL})
    try:
        BoussinesqOutputAdapter().extract(sim_id, output_dir, catalog)
        yield catalog, sim_id, top, drain[1:]
    finally:
        catalog.close()


def test_the_stored_descent_routes_like_the_whitebox_mass_flux(extracted, tmp_path: Path) -> None:
    catalog, sim_id, top, drain = extracted
    sz = catalog.open_zarr(sim_id)
    try:
        mesh = sz.root["mesh"]
        receiver = np.asarray(mesh["descent_receiver"][:])
        surface = np.asarray(mesh["descent_surface"][:])
        raised = np.asarray(mesh["descent_raised"][:])
        routed_on_read = accumulation_flux_rows(sz.root, 0, 2)
    finally:
        sz.close()

    assert receiver.shape == surface.shape == (N_CELLS,)
    # The pit is filled, so the fill decides the routing of this grid.
    assert raised[2 * NCOL + 3]
    assert np.all(surface >= top)

    loads = np.vstack([np.random.default_rng(3).uniform(0.0, 1.0, N_CELLS), drain])
    whitebox = _whitebox_mass_flux(top.reshape(NROW, NCOL), loads, tmp_path)
    on_graph = accumulate_on_downhill_graph(descent_graph(receiver, surface), loads)

    np.testing.assert_allclose(on_graph, whitebox, rtol=RTOL_FLOAT32)
    # The read side routes the stored drain outflow on the same D.
    np.testing.assert_allclose(routed_on_read, whitebox[1:], rtol=RTOL_FLOAT32)
