"""A mapped network that is exactly the simulated one scores J = 0.

The criterion's zero is the equality of D_so and D_os. If the map is the
polyline through the centres of a simulated chain, that equality must hold, or
the search moves K on a perfect match. The crossing rule gives the chain back
cell for cell, in D8 along a diagonal talweg. The touch rule adds, at every
diagonal step, the two cells that share the corner: D_so stays at zero, D_os
grows, J_signed turns negative and the search pulls K down. That
counter-example is the reason ``crossing`` is the default.
"""

from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.calibration.metrics.downslope_network import seepage_distance_cost
from hydromodpy.core.stream_geometry import build_network_geometry
from hydromodpy.core.stream_network import SimulatedNetwork, downstream_closure
from hydromodpy.spatial.mesh.ops.vector_cell_mask import (
    cell_polygons,
    line_crossing_cell_mask,
    vector_cell_mask,
)
from tests._helpers.ugrid_meshes import quad_mesh

CRS = "EPSG:2154"
N = 24
CELL = 75.0
FIRST_SEEPING_ROW = 6


def _diagonal_valley():
    """A V valley whose talweg runs down the grid diagonal to cell (0, 0)."""
    vertices, connectivity = quad_mesh(N, N, cell_size=CELL)
    rows, cols = np.meshgrid(np.arange(N), np.arange(N), indexing="ij")
    top = (100.0 + 0.5 * np.abs(rows - cols) + 0.01 * (rows + cols)).reshape(-1)
    centres = np.column_stack([(cols.ravel() + 0.5) * CELL, (rows.ravel() + 0.5) * CELL])
    return vertices, connectivity, top, centres


def _signed_gap(rule: str) -> tuple[np.ndarray, np.ndarray, dict]:
    vertices, connectivity, top, centres = _diagonal_valley()
    n_cells = top.size
    area = np.full(n_cells, CELL * CELL)
    talweg = np.zeros(n_cells, dtype=bool)
    talweg[[k * N + k for k in range(FIRST_SEEPING_ROW, N)]] = True

    def geometry(observed: np.ndarray):
        return build_network_geometry(
            topography=top,
            face_node_connectivity=connectivity,
            vertices=vertices,
            observed=observed,
            cell_area_m2=area,
            cell_centroids=centres,
            mean_recharge_m_s=1.0e-8,
            tau_specific_ratio=0.0,
            diagonal_neighbors=True,
        )

    chain = downstream_closure(geometry(talweg).metric, talweg)
    ordered = sorted(np.flatnonzero(chain), key=lambda cell: divmod(int(cell), N))
    mapped = [LineString(centres[ordered])]
    polygons = cell_polygons(vertices, connectivity)
    if rule == "crossing":
        observed = line_crossing_cell_mask(
            polygons, vertices, connectivity, centres, mapped, mesh_crs=CRS, geometry_crs=CRS
        ).mask
    else:
        observed = vector_cell_mask(polygons, mapped, mesh_crs=CRS, geometry_crs=CRS)

    geo = geometry(observed)
    simulated = SimulatedNetwork(seepage=talweg, network=chain, threshold_m3_s=np.zeros(n_cells))
    result = seepage_distance_cost(
        simulated=simulated,
        observed=geo.observed,
        outlet=geo.outlet,
        catchment=geo.catchment,
        metric=geo.metric,
        distance_to_observed=geo.distance_to_observed,
        distance_to_observed_raw=geo.distance_to_observed_raw,
        cell_area_m2=area,
        length_scale_m=geo.h_obs_m,
        saturation_cap_m=geo.saturation_cap_m,
    )
    return chain, np.asarray(observed, dtype=bool), result.components


def test_the_simulated_chain_follows_the_diagonal() -> None:
    chain, _, _ = _signed_gap("crossing")

    assert np.flatnonzero(chain).tolist() == [k * N + k for k in range(N)]


def test_the_crossing_rule_gives_the_chain_back_and_scores_zero() -> None:
    chain, observed, components = _signed_gap("crossing")

    assert np.array_equal(observed, chain)
    assert components["D_so"] == pytest.approx(0.0, abs=1e-9)
    assert components["D_os"] == pytest.approx(0.0, abs=1e-9)
    assert components["J_signed"] == pytest.approx(0.0, abs=1e-9)


def test_the_touch_rule_turns_a_perfect_match_negative() -> None:
    chain, observed, components = _signed_gap("touch")

    assert int(observed.sum()) == int(chain.sum()) + 2 * (int(chain.sum()) - 1)
    assert components["D_so"] == pytest.approx(0.0, abs=1e-9)
    assert components["D_os"] > 0.0
    assert components["J_signed"] < 0.0
