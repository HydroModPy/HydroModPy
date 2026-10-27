"""The circle geometry of the mirror pairs, on hand-checked numbers."""

from __future__ import annotations

import math

import numpy as np
import pytest

from hydromodpy.spatial.mesh.engines.voronoi.mirror import (
    RADIUS_SHARE,
    circle_segment_crossings,
    enforce_eq1,
    initial_radii,
    pair_seeds,
    seed_angle,
    tip_seeds,
)


def test_initial_radius_follows_the_longer_incident_segment() -> None:
    nodes = np.array([[0, 1], [1, 2]])
    radius = initial_radii(3, nodes, np.array([10.0, 30.0]))
    assert radius == pytest.approx(RADIUS_SHARE * np.array([10.0, 30.0, 30.0]))


def test_eq1_lowers_a_radius_until_the_circles_nest_no_more() -> None:
    nodes = np.array([[0, 1], [1, 2]])
    length = np.array([1.0, 1.0])
    radius, lowered = enforce_eq1(np.array([5.0, 0.6, 0.6]), nodes, length)
    assert radius == pytest.approx([1.6, 0.6, 0.6])
    assert lowered.tolist() == [True, False, False]
    gap = np.abs(radius[nodes[:, 0]] - radius[nodes[:, 1]])
    assert np.all(gap <= length + 1e-12)
    assert np.all(radius[nodes[:, 0]] + radius[nodes[:, 1]] >= length)


def test_pair_lies_on_both_circles_and_mirrors_across_the_segment() -> None:
    start = np.array([[0.0, 0.0], [3.0, 1.0]])
    stop = np.array([[10.0, 0.0], [3.0, 9.0]])
    r_start, r_stop = np.array([5.5, 4.4]), np.array([6.0, 4.4])
    plus, minus, along, ok = pair_seeds(start, stop, r_start, r_stop)
    assert ok.all()
    for seeds in (plus, minus):
        assert np.hypot(*(seeds - start).T) == pytest.approx(r_start)
        assert np.hypot(*(seeds - stop).T) == pytest.approx(r_stop)
    tangent = stop - start
    left = tangent[:, 0] * (plus - start)[:, 1] - tangent[:, 1] * (plus - start)[:, 0]
    assert np.all(left > 0.0)
    unit = tangent / np.hypot(*tangent.T)[:, None]
    assert 0.5 * (plus + minus) == pytest.approx(start + along[:, None] * unit)


def test_circles_apart_give_no_pair() -> None:
    _, _, _, ok = pair_seeds(
        np.array([[0.0, 0.0]]), np.array([[10.0, 0.0]]), np.array([4.0]), np.array([4.0])
    )
    assert not ok[0]


def test_seed_angle_is_the_angle_of_the_pair_seen_from_its_vertex() -> None:
    start, stop = np.array([[0.0, 0.0]]), np.array([[20.0, 0.0]])
    radius = np.array([RADIUS_SHARE * 20.0])
    plus, _, along, _ = pair_seeds(start, stop, radius, radius)
    assert seed_angle(along, radius)[0] == pytest.approx(math.atan2(plus[0, 1], plus[0, 0]))


def test_tip_sits_on_the_end_circle_on_the_outgoing_tangent() -> None:
    tip = tip_seeds(np.array([[10.0, 0.0]]), np.array([[0.0, 0.0]]), np.array([5.5]))
    assert tip[0] == pytest.approx([15.5, 0.0])


def test_circle_cuts_a_polyline_in_order_along_it() -> None:
    coords = np.array([[-10.0, 0.0], [10.0, 0.0], [10.0, 10.0]])
    points, along = circle_segment_crossings(np.array([5.0, 0.0]), 3.0, coords)
    assert points == pytest.approx(np.array([[2.0, 0.0], [8.0, 0.0]]))
    assert along == pytest.approx([12.0, 18.0])
    points, along = circle_segment_crossings(np.array([10.0, 0.0]), 4.0, coords)
    assert points == pytest.approx(np.array([[6.0, 0.0], [10.0, 4.0]]))
    assert along == pytest.approx([16.0, 24.0])
