"""The V-valley bench: a catchment with no DEM, no whitebox and no solve.

It separates the four ways of taking the mean behind ``D_so`` and ``D_os``,
which is what decides whether the observed stream network is closed downslope
before the criterion is evaluated. Everything is deterministic numpy.

    z(row, col) = 1000 - row + 2 |col - AXIS_COL|

Water runs south along the axis and diagonally down both hillsides, so every
receiver is known in closed form and the outlet is the single pit. The
simulated network is ``{drained area >= threshold}`` intersected with a
checkerboard, the checkerboard standing in for the discontinuity of a seepage
pattern and the threshold for ``K/R``: a higher threshold means a sparser
network, so the sweep walks the bracket the same way a calibration does.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from hydromodpy.core.field_routing import accumulate_on_downhill_graph
from hydromodpy.core.topographic_distance import (
    DownslopeMetric,
    build_downslope_metric,
    downslope_distance_to_mask,
    mean_downslope_distance,
)
from tests._helpers.ugrid_meshes import quad_mesh

N_ROWS = 61
N_COLS = 41
N_CELLS = N_ROWS * N_COLS
CELL_SIZE = 10.0
AXIS_COL = 20
OUTLET_ROW = 60

# On a uniform grid the median cell area gives back the cell size, so Eq. 3 of
# the paper normalizes by exactly one cell here.
LENGTH_SCALE = CELL_SIZE

# The observed network runs from row 12 down to the outlet.
FIRST_OBSERVED_ROW = 12
HOLE_ROW = 36
TRUNCATED_LAST_ROW = 54

# Thirty-six log-spaced drained-area thresholds, from one cell to the whole
# catchment: the sweep the support study runs.
THRESHOLDS = np.logspace(0.0, np.log10(float(N_CELLS)), 36)

# Half-width, as a threshold factor, of the log window the criterion slope is
# measured over: the root divided by four up to the root times four.
SLOPE_WINDOW_FACTOR = 4.0

ObservedCase = Literal["aligned", "hole", "shifted", "truncated"]


@dataclass(frozen=True)
class VValleyBench:
    """The static half of the bench, built once and read by every sweep."""

    metric: DownslopeMetric
    elevation: np.ndarray
    drained_area: np.ndarray
    checkerboard: np.ndarray
    outlet: int


def cell_id(row: int, col: int) -> int:
    """Row-major cell index, matching :func:`tests._helpers.ugrid_meshes.quad_mesh`."""
    return row * N_COLS + col


def build_bench() -> VValleyBench:
    """Build the surface, its D8 receiver graph and its drained area."""
    rows = np.arange(N_ROWS)[:, None]
    cols = np.arange(N_COLS)[None, :]
    elevation = (1000.0 - rows + 2.0 * np.abs(cols - AXIS_COL)).reshape(-1)
    checkerboard = ((rows + cols) % 2 == 0).reshape(-1)

    vertices, connectivity = quad_mesh(N_ROWS, N_COLS, cell_size=CELL_SIZE)
    metric = build_downslope_metric(
        elevation, connectivity, vertices=vertices, diagonal_neighbors=True
    )
    drained_area = accumulate_on_downhill_graph(metric.graph, np.ones(N_CELLS))
    return VValleyBench(
        metric=metric,
        elevation=elevation,
        drained_area=drained_area,
        checkerboard=checkerboard,
        outlet=cell_id(OUTLET_ROW, AXIS_COL),
    )


def analytic_receiver(row: int, col: int) -> int:
    """Receiver of an interior cell, straight from the geometry of the valley."""
    step = 0 if col == AXIS_COL else (-1 if col > AXIS_COL else 1)
    return cell_id(row + 1, col + step)


def observed_network(case: ObservedCase) -> np.ndarray:
    """Return one of the four observed variants of the support study."""
    rows = range(FIRST_OBSERVED_ROW, N_ROWS)
    if case == "aligned":
        cells = [cell_id(row, AXIS_COL) for row in rows]
    elif case == "hole":
        cells = [cell_id(row, AXIS_COL) for row in rows if row != HOLE_ROW]
    elif case == "shifted":
        cells = [cell_id(row, AXIS_COL + 1) for row in rows]
    elif case == "truncated":
        cells = [
            cell_id(row, AXIS_COL) for row in range(FIRST_OBSERVED_ROW, TRUNCATED_LAST_ROW + 1)
        ]
    else:
        raise ValueError(f"unknown observed case {case!r}.")
    mask = np.zeros(N_CELLS, dtype=bool)
    mask[cells] = True
    return mask


def simulated_network(bench: VValleyBench, threshold: float) -> np.ndarray:
    """Raw simulated pattern at one point of the sweep."""
    return (bench.drained_area >= threshold) & bench.checkerboard & bench.metric.graph.active


def downstream_closure(bench: VValleyBench, mask: np.ndarray) -> np.ndarray:
    """Downslope closure: the cells the water of ``mask`` flows through.

    One accumulation pass is the closure, so no second traversal is written.
    Inactive cells come back as NaN, which is why the test is not ``> 0`` alone.
    """
    accumulated = accumulate_on_downhill_graph(bench.metric.graph, mask.astype(float))
    closed = np.zeros(mask.size, dtype=bool)
    finite = np.isfinite(accumulated)
    closed[finite] = accumulated[finite] > 0.0
    return closed & bench.metric.graph.active


def sweep_distances(
    bench: VValleyBench,
    observed: np.ndarray,
    *,
    close_simulated: bool,
    close_observed: bool,
    seal_outlet: bool,
    saturation_cap_m: float | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Run the whole sweep and return ``(D_so, D_os)`` over :data:`THRESHOLDS`.

    ``close_simulated`` and ``close_observed`` pick one of the four
    combinations: each flag drives both a support and a target, since ``D_so``
    averages over the simulated set toward the observed one and ``D_os`` does
    the reverse. ``seal_outlet`` adds the outlet cell to the target of ``D_so``
    only, never to the support of ``D_os``.
    """
    observed_support = downstream_closure(bench, observed) if close_observed else observed
    observed_target = observed_support.copy()
    if seal_outlet:
        observed_target[bench.outlet] = True

    # The distance to the observed network only depends on the topography, so
    # it is computed once for the whole sweep, exactly as a calibration would.
    to_observed = downslope_distance_to_mask(bench.metric, observed_target)

    d_so = np.empty(THRESHOLDS.size, dtype="float64")
    d_os = np.empty(THRESHOLDS.size, dtype="float64")
    for index, threshold in enumerate(THRESHOLDS):
        raw = simulated_network(bench, float(threshold))
        simulated = downstream_closure(bench, raw) if close_simulated else raw
        to_simulated = downslope_distance_to_mask(bench.metric, simulated)
        d_so[index] = mean_downslope_distance(
            to_observed, simulated, saturation_cap_m=saturation_cap_m
        ).mean_m
        d_os[index] = mean_downslope_distance(
            to_simulated, observed_support, saturation_cap_m=saturation_cap_m
        ).mean_m
    return d_so, d_os


def crossing_thresholds(d_so: np.ndarray, d_os: np.ndarray) -> list[float]:
    """Thresholds where the signed gap changes sign, interpolated in log space."""
    signed_gap = d_so - d_os
    defined = np.flatnonzero(np.isfinite(signed_gap))
    log_thresholds = np.log10(THRESHOLDS)
    roots: list[float] = []
    for before, after in zip(defined[:-1], defined[1:], strict=False):
        if signed_gap[before] * signed_gap[after] >= 0.0:
            continue
        share = signed_gap[before] / (signed_gap[before] - signed_gap[after])
        span = log_thresholds[after] - log_thresholds[before]
        roots.append(float(10.0 ** (log_thresholds[before] + share * span)))
    return roots


def interpolate_at(values: np.ndarray, threshold: float) -> float:
    """Read a swept quantity at an interpolated threshold, in log space."""
    return float(np.interp(np.log10(threshold), np.log10(THRESHOLDS), values))


def criterion_slope(d_so: np.ndarray, d_os: np.ndarray, root: float) -> float:
    """Slope of the signed gap over a fixed log window centred on the root.

    The window has the same width whatever the support, which is what makes two
    supports comparable. A one-interval finite difference across the bracketing
    interval does not: the signed gap is a staircase, so that difference reports
    the height of one step over the width of one grid cell, and it ranks the two
    supports the wrong way round.
    """
    signed_gap = d_so - d_os
    log_thresholds = np.log(THRESHOLDS)
    half_width = np.log(SLOPE_WINDOW_FACTOR)
    inside = (
        np.isfinite(signed_gap)
        & (log_thresholds >= np.log(root) - half_width)
        & (log_thresholds <= np.log(root) + half_width)
    )
    if int(inside.sum()) < 3:
        raise ValueError("the log window around the root holds fewer than three defined points.")
    values = signed_gap[inside]
    span = log_thresholds[inside][-1] - log_thresholds[inside][0]
    return float(abs(values[-1] - values[0]) / span)
