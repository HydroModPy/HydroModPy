"""The value types and refusals of the terrain port."""

from __future__ import annotations

import math

import pytest

from hydromodpy.catchment.terrain.port import (
    LN_FLOAT32_COLLISION_COUNT,
    ConditioningExtent,
    Outlet,
    require_resolvable_counts,
    snap_window_cells,
)
from hydromodpy.core.exceptions import TerrainProductError, TerrainRequestError


def _accumulation(transform: str):
    return type("Acc", (), {"transform": transform})()


def test_the_float32_guard_refuses_only_a_transformed_value_past_the_bound() -> None:
    """A delineation refuses a log accumulation only where its outlets snap."""
    bound = math.log(LN_FLOAT32_COLLISION_COUNT)
    assert math.log(2.0e6) >= bound  # a basin of two million cells is past it
    require_resolvable_counts(_accumulation("ln"), max_stored_value=bound - 1.0, member="delineate")
    require_resolvable_counts(_accumulation("none"), max_stored_value=1e30, member="delineate")
    with pytest.raises(TerrainProductError, match="cannot rank"):
        require_resolvable_counts(_accumulation("ln"), max_stored_value=bound, member="delineate")


@pytest.mark.parametrize("distance", [0.0, -25.0])
def test_a_snap_window_of_no_width_is_refused(distance) -> None:
    with pytest.raises(TerrainRequestError, match="snap distance"):
        snap_window_cells(distance, dx=25.0, dy=25.0)


def test_a_conditioning_extent_says_what_it_conditions() -> None:
    assert ConditioningExtent.per_outlet_buffer(500.0).buffer_distance_m == 500.0


@pytest.mark.parametrize(
    ("kind", "distance", "match"),
    [
        ("everywhere", None, "Unknown conditioning extent"),
        ("regional", 100.0, "carries no buffer distance"),
        ("per_outlet_buffer", 0.0, "needs a buffer distance"),
    ],
)
def test_a_conditioning_extent_that_contradicts_itself_is_refused(kind, distance, match) -> None:
    with pytest.raises(TerrainRequestError, match=match):
        ConditioningExtent(kind=kind, buffer_distance_m=distance)


@pytest.mark.parametrize(
    ("outlet_id", "match"),
    [("../up", "not usable as a directory name"), ("a" * 65, "over the 64")],
)
def test_an_outlet_id_that_makes_no_directory_name_is_refused(outlet_id, match) -> None:
    with pytest.raises(TerrainRequestError, match=match):
        Outlet(outlet_id=outlet_id, x=0.0, y=0.0)
