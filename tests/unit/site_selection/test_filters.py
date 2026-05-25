from __future__ import annotations

import pytest
from shapely.geometry import Polygon, box

from hydromodpy.spatial.site_selection.filters import (
    basin_overlap_fraction,
    is_overlap_allowed,
)


@pytest.mark.fast
def test_basin_overlap_fraction_uses_smaller_basin_by_default():
    candidate = box(0.0, 0.0, 10.0, 10.0)
    selected = box(5.0, 0.0, 15.0, 10.0)

    fraction = basin_overlap_fraction(
        candidate_geometry=candidate,
        selected_geometry=selected,
    )

    assert fraction == pytest.approx(0.5)


@pytest.mark.fast
def test_basin_overlap_fraction_can_use_candidate_reference():
    candidate = box(0.0, 0.0, 20.0, 10.0)
    selected = box(0.0, 0.0, 10.0, 10.0)

    fraction = basin_overlap_fraction(
        candidate_geometry=candidate,
        selected_geometry=selected,
        reference="candidate",
    )

    assert fraction == pytest.approx(0.5)


@pytest.mark.fast
def test_basin_overlap_fraction_repairs_invalid_geometry():
    candidate = Polygon(
        [
            (0.0, 0.0),
            (2.0, 2.0),
            (0.0, 2.0),
            (2.0, 0.0),
            (0.0, 0.0),
        ]
    )
    selected = box(0.0, 0.0, 2.0, 2.0)

    fraction = basin_overlap_fraction(
        candidate_geometry=candidate,
        selected_geometry=selected,
    )

    assert 0.0 < fraction <= 1.0


@pytest.mark.fast
def test_is_overlap_allowed_applies_threshold():
    assert is_overlap_allowed(
        overlap_fraction=0.04,
        max_pairwise_basin_overlap_fraction=0.05,
    )
    assert not is_overlap_allowed(
        overlap_fraction=0.06,
        max_pairwise_basin_overlap_fraction=0.05,
    )
