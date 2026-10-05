"""A network output drawn by its heads scores the trace of those heads.

Under ``observed_rasterization = "heads"`` the calibration projects no cell
from the mapped lines: it keeps their free ends, lands each on a cell draining
enough, and the criterion graph draws the rest. On the V-valley bench the
mapped talweg starts on row 12, which drains 169 cells of 100 m2; the default
0.02 km2 first holds on row 14, so the scored map is the axis from row 14 to
the outlet, and the trial publishes how the head landed.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.calibration.config import validate_calib_output
from hydromodpy.calibration.metrics import solver_extract as _solver_extract
from hydromodpy.calibration.metrics.solver_extract import extract_outputs
from hydromodpy.calibration.observations.network_geometry import network_maps_from_run
from hydromodpy.core.contracts.observables import ObservableResult
from tests._helpers.ugrid_meshes import quad_mesh
from tests._helpers.v_valley import (
    AXIS_COL,
    CELL_SIZE,
    FIRST_OBSERVED_ROW,
    N_CELLS,
    N_COLS,
    N_ROWS,
    build_bench,
    cell_id,
)

gpd = pytest.importorskip("geopandas")

from shapely.geometry import LineString  # noqa: E402

CRS = "EPSG:2154"
LANDING_ROW = 14


def _run_ctx(bench):
    """A trial context exposing what network_maps_from_run reads, the talweg mapped."""
    vertices, connectivity = quad_mesh(N_ROWS, N_COLS, cell_size=CELL_SIZE)
    rows, cols = np.divmod(np.arange(N_CELLS), N_COLS)
    centroids = np.column_stack([(cols + 0.5) * CELL_SIZE, (rows + 0.5) * CELL_SIZE])
    talweg = LineString(
        [
            ((AXIS_COL + 0.5) * CELL_SIZE, (row + 0.5) * CELL_SIZE)
            for row in range(FIRST_OBSERVED_ROW, N_ROWS)
        ]
    )
    lines = gpd.GeoDataFrame(geometry=[talweg], crs=CRS)
    network = SimpleNamespace(vector_path="/fake/streams.gpkg", crs=CRS, read_vector=lambda: lines)
    solver_mesh = SimpleNamespace(
        top=bench.elevation,
        planar_mesh=SimpleNamespace(
            vertices=vertices, flat_connectivity=connectivity, n_cells=N_CELLS
        ),
        n_cells=N_CELLS,
        cell_areas=lambda: np.full(N_CELLS, CELL_SIZE * CELL_SIZE),
        cell_centroids=lambda: centroids,
    )
    return SimpleNamespace(
        run=SimpleNamespace(id="r1", solver="modflow6"),
        state=SimpleNamespace(
            setup=SimpleNamespace(
                geographic=SimpleNamespace(crs_project=CRS),
                geographic_features=SimpleNamespace(
                    hydrographic_networks=SimpleNamespace(reference=network, generated=None)
                ),
            ),
        ),
        model=SimpleNamespace(
            solver_mesh=solver_mesh, recharge=1.0e-8, lake_cell_ids_by_lake={}, dam_foot_cells={}
        ),
    )


def _heads_output():
    return validate_calib_output(
        {
            "support": "network",
            "observed_network": "data.hydrography",
            "diagonal_neighbors": True,
            "tau_specific_ratio": 0.0,
            "observed_rasterization": "heads",
        }
    )


def _trace() -> np.ndarray:
    mask = np.zeros(N_CELLS, dtype=bool)
    mask[[cell_id(row, AXIS_COL) for row in range(LANDING_ROW, N_ROWS)]] = True
    return mask


def test_a_heads_output_scores_the_trace_of_its_heads() -> None:
    maps = network_maps_from_run(_run_ctx(build_bench()), _heads_output())

    np.testing.assert_array_equal(maps.maximal.observed, _trace())
    assert maps.maximal_projection.rasterization == "heads"
    np.testing.assert_array_equal(maps.maximal_projection.mask, _trace())
    assert maps.maximal.heads is not None
    assert maps.maximal.heads.indices["n_heads"] == 1.0
    assert maps.maximal.heads.indices["head_snap_p90_m"] == pytest.approx(
        (LANDING_ROW - FIRST_OBSERVED_ROW) * CELL_SIZE
    )


class _AxisRelease:
    """Releases on the mapped trace, so the trial matches the drawn map exactly."""

    def extract_observables(self, ctx, store, requests, *, time_index=None):
        del ctx, store, time_index
        return {
            request.id: ObservableResult(
                request_id=request.id,
                values=np.where(_trace(), 1.0e-6, 0.0),
                units="m3 s-1",
            )
            for request in requests
        }


def test_the_trial_publishes_how_the_heads_drew_the_map(monkeypatch) -> None:
    run_ctx = _run_ctx(build_bench())
    adapter = _AxisRelease()
    monkeypatch.setattr(_solver_extract, "resolve_flow_adapter", lambda ctx: (adapter, run_ctx))

    diagnostics = extract_outputs(run_ctx, {"net": _heads_output()}).diagnostics

    assert diagnostics["net.n_observed_cells"] == float(N_ROWS - LANDING_ROW)
    assert diagnostics["net.n_heads"] == 1.0
    assert diagnostics["net.n_heads_lost"] == 0.0
    assert diagnostics["net.heads_trace_near_map_share"] == 1.0
