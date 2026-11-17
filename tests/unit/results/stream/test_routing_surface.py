"""The routing surface of a run is rebuilt from its mesh and names what it could not use.

The run is the ``5 x 3`` V-valley of ``tests.unit.display._network_comparison_run``:
the outlet is the southern cell of the middle column, and every column is 100 m wide.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import box

from hydromodpy.results.derive.stream_network.routing_surface import (
    routing_surface_from_run,
    unavailable_reason_for_routing,
)
from tests.unit.display._network_comparison_run import (
    AXIS_COLUMN,
    CELL_M,
    CRS,
    NX,
    NY,
    cell,
    comparison_run,
)

OUTLET = cell(AXIS_COLUMN, 0)
LOGGER = "hydromodpy.results.derive.stream_network.routing_surface"


class _MeshlessRun(SimpleNamespace):
    """A run whose mesh read raises, as a lumped run does."""

    @property
    def mesh(self):
        raise RuntimeError("no mesh")


class _HeldRun(SimpleNamespace):
    """A run the memo can hold: hashable by identity."""

    __hash__ = object.__hash__


def _raising(error):
    def read(feature):
        raise error

    return read


def test_a_run_without_a_mesh_says_so() -> None:
    run = _MeshlessRun(**vars(comparison_run()))

    assert unavailable_reason_for_routing(run) == "run carries no mesh to route on (RuntimeError)"


def test_a_mesh_without_a_top_says_so() -> None:
    run = comparison_run()
    run.mesh.topography = None

    assert "no mesh topography" in unavailable_reason_for_routing(run)


def test_a_top_without_a_usable_elevation_says_so() -> None:
    run = comparison_run(topography=np.full(NX * NY, np.nan))

    assert "no cell with a usable elevation" in unavailable_reason_for_routing(run)
    with pytest.raises(ValueError, match="routing surface unavailable for sim-network"):
        routing_surface_from_run(run)


def test_the_surface_of_the_valley_ends_in_the_outlet_of_its_catchment() -> None:
    surface = routing_surface_from_run(comparison_run())

    assert surface.n_cells == NX * NY
    assert surface.outlet == OUTLET
    assert surface.catchment is not None and surface.catchment.all()
    assert surface.support_name == "the delineated catchment"
    assert (
        surface.outlet_note == f"outlet cell {OUTLET} at 0.00 m, lowest of the delineated catchment"
    )
    assert surface.outlet_mask().tolist() == [i == OUTLET for i in range(NX * NY)]


def test_the_edge_of_the_domain_is_every_escape_but_the_outlet_is_not_one() -> None:
    surface = routing_surface_from_run(comparison_run())

    escapes = surface.escape_mask()
    edge_cells = NX * NY - (NX - 2) * (NY - 2)

    assert int(escapes.sum()) == edge_cells
    assert escapes is not surface.domain_edge
    assert f"{edge_cells} cells on the edge of the active mesh" in surface.escape_note


@pytest.mark.parametrize(
    ("diagonals", "fragment", "links"),
    [(True, "shared nodes", 8), (False, "shared edges", 4)],
)
def test_the_neighbour_knob_picks_the_graph_and_names_it(diagonals, fragment, links) -> None:
    surface = routing_surface_from_run(comparison_run(), diagonal_neighbors=diagonals)

    assert fragment in surface.neighbourhood_note
    assert surface.diagonal_neighbors is diagonals
    assert len(surface.adjacency[cell(AXIS_COLUMN, 1)]) == links


def test_a_surface_is_built_once_per_run_and_knob() -> None:
    run = _HeldRun(**vars(comparison_run()))

    first = routing_surface_from_run(run)

    assert routing_surface_from_run(run) is first
    assert routing_surface_from_run(run, diagonal_neighbors=False) is not first


def test_connectivity_of_another_size_than_the_top_is_refused() -> None:
    run = comparison_run()
    run.mesh.topography = run.mesh.topography[:-1]

    with pytest.raises(ValueError, match="the mesh top holds 14 cells and the connectivity 15"):
        routing_surface_from_run(run)


def test_a_run_without_a_watershed_falls_back_to_the_whole_mesh(caplog) -> None:
    run = comparison_run()
    run.geographic = _raising(KeyError("watershed"))

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        surface = routing_surface_from_run(run)

    assert surface.catchment is None
    assert surface.support_name == "the active mesh"
    assert "carries no delineated catchment (KeyError)" in caplog.text


def test_an_empty_watershed_falls_back_to_the_whole_mesh(caplog) -> None:
    run = comparison_run()
    run.geographic = lambda feature: gpd.GeoDataFrame(geometry=[], crs=CRS)

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        surface = routing_surface_from_run(run)

    assert surface.catchment is None
    assert "is an empty feature" in caplog.text


def test_a_watershed_off_the_mesh_falls_back_to_the_whole_mesh(caplog) -> None:
    run = comparison_run()
    far = gpd.GeoDataFrame(geometry=[box(1.0e6, 1.0e6, 1.0e6 + 10, 1.0e6 + 10)], crs=CRS)
    run.geographic = lambda feature: far

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        surface = routing_surface_from_run(run)

    assert surface.catchment is None
    assert "projects onto no active cell" in caplog.text


def test_a_watershed_in_another_crs_is_converted_to_the_mesh_crs() -> None:
    run = comparison_run()
    watershed = gpd.GeoDataFrame(geometry=[box(0, 0, 2 * CELL_M, NY * CELL_M)], crs=CRS)
    foreign = SimpleNamespace(empty=False, crs="EPSG:3857", to_crs=lambda crs: watershed)
    run.geographic = lambda feature: foreign

    surface = routing_surface_from_run(run)

    assert surface.catchment is not None
    assert surface.catchment.reshape(NY, NX)[:, :2].all()
    assert not surface.catchment.reshape(NY, NX)[:, 3:].any()
    assert surface.within_catchment(np.ones(NX * NY, dtype=bool)).tolist() == (
        surface.catchment.tolist()
    )
