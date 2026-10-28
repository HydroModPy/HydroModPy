"""The overlap fraction of two basins and the overlap threshold."""

from __future__ import annotations

import pytest
from shapely.geometry import LineString, Polygon, box

from hydromodpy.spatial.site_selection.evaluation.spatial_filters import (
    basin_overlap_fraction,
    is_overlap_allowed,
)

pytestmark = pytest.mark.fast

BOWTIE = Polygon([(0.0, 0.0), (2.0, 2.0), (0.0, 2.0), (2.0, 0.0), (0.0, 0.0)])


@pytest.mark.parametrize(
    ("candidate", "selected", "reference", "fraction"),
    [
        (box(0, 0, 10, 10), box(5, 0, 15, 10), "smaller_basin", 0.5),
        (box(0, 0, 20, 10), box(0, 0, 10, 10), "smaller_basin", 1.0),
        (box(0, 0, 20, 10), box(0, 0, 10, 10), "candidate", 0.5),
        (box(0, 0, 10, 10), box(0, 0, 20, 10), "selected", 0.5),
        (box(0, 0, 10, 10), box(20, 0, 30, 10), "smaller_basin", 0.0),
        (None, box(0, 0, 10, 10), "smaller_basin", 0.0),
        (Polygon(), box(0, 0, 10, 10), "smaller_basin", 0.0),
        (LineString([(0, 0), (10, 10)]), box(0, 0, 10, 10), "smaller_basin", 0.0),
        (BOWTIE, box(0, 0, 2, 2), "candidate", 1.0),
    ],
)
def test_the_overlap_is_a_share_of_the_reference_basin(candidate, selected, reference, fraction):
    overlap = basin_overlap_fraction(
        candidate_geometry=candidate, selected_geometry=selected, reference=reference
    )

    assert overlap == pytest.approx(fraction)
    assert 0.0 <= overlap <= 1.0


def test_an_unknown_overlap_reference_is_refused():
    with pytest.raises(ValueError, match="Unsupported overlap reference: 'largest'"):
        basin_overlap_fraction(
            candidate_geometry=box(0, 0, 1, 1),
            selected_geometry=box(0, 0, 1, 1),
            reference="largest",
        )


@pytest.mark.parametrize(
    ("fraction", "threshold", "allowed"),
    [(0.04, 0.05, True), (0.05, 0.05, True), (0.06, 0.05, False), (0.9, None, True)],
)
def test_the_overlap_threshold_is_inclusive_and_optional(fraction, threshold, allowed):
    assert (
        is_overlap_allowed(overlap_fraction=fraction, max_pairwise_basin_overlap_fraction=threshold)
        is allowed
    )


def test_a_negative_overlap_threshold_is_refused():
    with pytest.raises(ValueError, match="must be >= 0"):
        is_overlap_allowed(overlap_fraction=0.0, max_pairwise_basin_overlap_fraction=-0.1)
