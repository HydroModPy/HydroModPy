"""Monotone fit of a stream bed elevation (m) on a tree of pixels 25 m apart.

Each node drains to its receiver (-1 for a root). The fit pools rising edges
to their mean, then tilts blocks so every edge drops at least min_slope (m/m).
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.catchment.algorithms.bed_regularization import regularize_bed_on_tree

LENGTH_M = 25.0
MIN_SLOPE = 1.0e-4
DROP_M = MIN_SLOPE * LENGTH_M


def fit_tree(values, receiver, **kwargs):
    values = np.asarray(values, dtype=float)
    return regularize_bed_on_tree(
        values, np.asarray(receiver), np.full(values.size, LENGTH_M), **kwargs
    )


def test_single_rise_on_a_chain():
    # Two values in the wrong order pool to their mean, then tilt about it.
    fit = fit_tree([5.0, 4.0, 3.0, 3.6, 2.0], [1, 2, 3, 4, -1], min_slope=MIN_SLOPE)

    np.testing.assert_allclose(
        fit.values, [5.0, 4.0, 3.3 + DROP_M / 2, 3.3 - DROP_M / 2, 2.0], atol=1e-12
    )
    assert (fit.violations_before, fit.violations_after) == (1, 0)
    assert np.all(fit.values[:-1] - fit.values[1:] >= DROP_M - 1e-12)
    assert (fit.raised, fit.lowered) == (1, 1)
    (block,) = fit.blocks
    np.testing.assert_array_equal(block.nodes, [2, 3])
    assert not block.holds_confluence
    np.testing.assert_allclose([block.max_raise_m, block.max_lowering_m], [0.3 + DROP_M / 2] * 2)


def test_long_flat_keeps_its_mean():
    # 400 pixels at 300 m under one pixel at 300.5 m. The 1e-4 m/m minimum drop
    # over 10 km is 1 m. Centered on the mean it lifts the head by half of it.
    n_flat = 400
    values = np.r_[300.5, np.full(n_flat, 300.0)]
    fit = fit_tree(values, np.r_[np.arange(1, values.size), -1], min_slope=MIN_SLOPE)

    flat = fit.values[1:]
    half_tilt = DROP_M * (n_flat - 1) / 2
    np.testing.assert_allclose(flat.mean(), 300.0, atol=1e-9)
    np.testing.assert_allclose([flat[0], flat[-1]], [300.0 + half_tilt, 300.0 - half_tilt])
    np.testing.assert_allclose(fit.min_drop_max_lift_m, half_tilt)
    assert np.all(-np.diff(fit.values) >= DROP_M - 1e-9)
    assert abs(fit.mean_bias_m) < 0.01


# Main stem 0 -> 1 -> 2 (junction) -> 3 (root). Tributary 4 -> 5 -> 2.
CONFLUENCE_RECEIVER = [1, 2, 3, -1, 5, 2]


def test_tributary_end_pooled_with_junction():
    # The tributary end (10) is below the junction (11), the main stem above stays higher.
    fit = fit_tree([13.0, 12.0, 11.0, 8.0, 14.0, 10.0], CONFLUENCE_RECEIVER)

    (block,) = fit.blocks
    np.testing.assert_array_equal(block.nodes, [2, 5])
    assert block.holds_confluence
    np.testing.assert_allclose([block.max_raise_m, block.max_lowering_m], [0.5, 0.5], atol=2e-3)


def test_tributary_below_junction_shares_block():
    # The junction (11) is above both upstream neighbours (10.4 and 10.0): one block of three.
    values = [13.0, 10.4, 11.0, 8.0, 14.0, 10.0]
    fit = fit_tree(values, CONFLUENCE_RECEIVER, min_slope=MIN_SLOPE)

    mean = (10.4 + 11.0 + 10.0) / 3.0
    head, exit_ = mean + DROP_M / 3.0, mean - 2.0 * DROP_M / 3.0
    np.testing.assert_allclose(fit.values[[1, 2, 5]], [head, exit_, head])
    np.testing.assert_allclose(fit.values[[0, 3, 4]], [13.0, 8.0, 14.0])
    (block,) = fit.blocks
    np.testing.assert_array_equal(block.nodes, [1, 2, 5])
    assert block.holds_confluence
    np.testing.assert_allclose(block.max_raise_m, head - 10.0)
    np.testing.assert_allclose(block.max_lowering_m, 11.0 - exit_)
    assert fit.violations_after == 0


def test_weir_cut():
    # 0 -> 1 -> 2 (weir crest) -> 3 (foot) -> 4 (5 m bump) -> 5 (root).
    # Uncut, the bump pools with the foot above the crest and lifts the reach above.
    values = np.array([12.5, 12.2, 12.0, 10.0, 15.0, 9.0])
    receiver = [1, 2, 3, 4, 5, -1]
    cut = np.arange(6) == 2

    uncut = fit_tree(values, receiver)
    fit = fit_tree(values, receiver, cut=cut)

    assert uncut.values[2] > values[2] + 0.1
    assert uncut.climbs_at_cuts == 0
    np.testing.assert_allclose(fit.values[:3], values[:3])
    np.testing.assert_allclose(fit.values[[3, 4]], [12.5 + DROP_M / 2, 12.5 - DROP_M / 2])
    assert fit.climbs_at_cuts == 1
    assert fit.violations_after == 0


def test_road_embankment_gap():
    # A 3 m embankment on a straight 1 % bed. As a gap it is interpolated.
    n_nodes = 11
    bed = 0.01 * LENGTH_M * np.arange(n_nodes - 1, -1, -1)
    values = bed.copy()
    values[[5, 6]] += 3.0
    receiver = np.r_[np.arange(1, n_nodes), -1]
    gap = np.isin(np.arange(n_nodes), [5, 6])

    as_bump = fit_tree(values, receiver)
    as_gap = fit_tree(values, receiver, gap=gap)

    assert as_bump.values[4] > bed[4] + 1.0
    np.testing.assert_allclose(as_gap.values, bed, atol=1e-9)
    assert (as_gap.raised, as_gap.lowered) == (0, 0)
    assert as_gap.violations_before == 0
    assert as_gap.blocks == ()


def test_forest_is_fitted_tree_by_tree():
    first, second = np.array([6.0, 4.0, 5.0, 1.0]), np.array([3.0, 2.5, 2.9, 2.0, 0.5])
    first_receiver, second_receiver = [1, 2, 3, -1], [1, 2, 3, 4, -1]
    receiver = np.r_[
        first_receiver, np.where(np.array(second_receiver) >= 0, np.array(second_receiver) + 4, -1)
    ]

    forest = fit_tree(np.r_[first, second], receiver)

    alone = [fit_tree(first, first_receiver), fit_tree(second, second_receiver)]
    np.testing.assert_array_equal(forest.values, np.r_[alone[0].values, alone[1].values])
    assert len(forest.blocks) == 2
    for block in forest.blocks:
        assert np.all(block.nodes < 4) or np.all(block.nodes >= 4)
    assert forest.violations_after == 0


def test_random_tree_left_no_short_edge():
    # Seeded noisy bed with gaps and cuts. Without the frontier re-exposure the
    # mean bias is 0.013 m, without pooling 0.24 m.
    n_nodes = 2000
    rng = np.random.default_rng(20261005)
    receiver = np.r_[-1, [rng.integers(max(0, i - 30), i) for i in range(1, n_nodes)]].astype(
        np.int64
    )
    length = rng.choice([25.0, 25.0 * np.sqrt(2.0)], n_nodes)
    distance_to_root = np.zeros(n_nodes)
    for node in range(1, n_nodes):
        distance_to_root[node] = distance_to_root[receiver[node]] + length[node]
    values = 2.0e-3 * distance_to_root + rng.normal(0.0, 0.3, n_nodes)
    gap = rng.random(n_nodes) < 0.02
    values[gap] += 3.0
    cut = rng.random(n_nodes) < 0.01

    fit = regularize_bed_on_tree(values, receiver, length, gap=gap, cut=cut, min_slope=MIN_SLOPE)

    edges = np.flatnonzero((receiver >= 0) & ~cut)
    drop = fit.values[edges] - fit.values[receiver[edges]]
    assert fit.violations_before > 100
    assert fit.rises_after_fit == 0
    assert np.all(drop >= MIN_SLOPE * length[edges] - 1e-9)
    assert abs(fit.mean_bias_m) < 0.01
    assert fit.closing_raised >= fit.violations_after > 0


def test_refusals():
    # 4 -> 1 -> 2 -> 3 -> 1 is a cycle, 0 is a separate root.
    with pytest.raises(ValueError, match=r"cycle through node [123]\b"):
        fit_tree(np.arange(5.0), [-1, 2, 3, 1, 1])


def test_gap_with_no_measured_node_above_or_below():
    # Gaps 0 and 2 sit at the two ends of the main stem, gap 1 is the junction.
    # The only measurement (9 m) is on the tributary 3, so every gap takes it.
    fit = fit_tree(
        [np.nan, np.nan, np.nan, 9.0], [1, 2, -1, 1], gap=[True, True, True, False], min_slope=0.0
    )

    np.testing.assert_allclose(fit.values, [9.0, 9.0, 9.0, 9.0])


def test_isolated_gap_keeps_its_raw_value():
    # A gap with no neighbour has nothing to borrow from.
    fit = fit_tree([7.0], [-1], gap=[True], min_slope=0.0)

    np.testing.assert_allclose(fit.values, [7.0])


def test_empty_tree():
    fit = fit_tree([], np.array([], dtype=int))

    assert fit.values.size == 0
    assert fit.blocks == ()


BED = np.array([5.0, 4.0, 3.0])
CHAIN = np.array([1, 2, -1])
LENGTHS = np.full(3, LENGTH_M)

BAD_INPUTS = [
    pytest.param(
        dict(values=BED.reshape(1, 3), receiver=CHAIN, edge_length=LENGTHS),
        "values must be one-dimensional",
        id="values not one-dimensional",
    ),
    pytest.param(
        dict(values=BED, receiver=CHAIN[:2], edge_length=LENGTHS),
        r"receiver must have shape \(3,\)",
        id="receiver of wrong length",
    ),
    pytest.param(
        dict(values=BED, receiver=CHAIN.astype(float), edge_length=LENGTHS),
        "receiver must hold integer indices",
        id="receiver as floats",
    ),
    pytest.param(
        dict(values=BED, receiver=np.array([1, 3, -1]), edge_length=LENGTHS),
        r"receiver of node 1 is 3, outside \[-1, 2\]",
        id="receiver out of range",
    ),
    pytest.param(
        dict(values=BED, receiver=CHAIN, edge_length=LENGTHS[:2]),
        r"edge_length must have shape \(3,\)",
        id="edge length of wrong length",
    ),
    pytest.param(
        dict(values=BED, receiver=CHAIN, edge_length=np.array([25.0, -1.0, 25.0])),
        "edge length of node 1 must be finite and non-negative",
        id="negative edge length",
    ),
    pytest.param(
        dict(values=np.array([5.0, np.nan, 3.0]), receiver=CHAIN, edge_length=LENGTHS),
        "value of measured node 1 is not finite",
        id="measured value is nan",
    ),
    pytest.param(
        dict(values=BED, receiver=CHAIN, edge_length=LENGTHS, min_slope=-1.0),
        "min_slope must be finite and non-negative",
        id="negative minimum slope",
    ),
    pytest.param(
        dict(values=BED, receiver=CHAIN, edge_length=LENGTHS, gap=np.zeros(2, dtype=bool)),
        r"gap must have shape \(3,\)",
        id="gap mask of wrong length",
    ),
    pytest.param(
        dict(values=BED, receiver=CHAIN, edge_length=LENGTHS, cut=np.zeros(3)),
        "cut must be a boolean mask",
        id="cut mask not boolean",
    ),
    pytest.param(
        dict(
            values=np.array([np.nan]),
            receiver=np.array([-1]),
            edge_length=np.zeros(1),
            gap=np.array([True]),
        ),
        "gap node 0 has no measured node",
        id="isolated gap without raw value",
    ),
]


@pytest.mark.parametrize(("kwargs", "message"), BAD_INPUTS)
def test_bad_inputs_refused(kwargs, message):
    with pytest.raises(ValueError, match=message):
        regularize_bed_on_tree(**kwargs)
