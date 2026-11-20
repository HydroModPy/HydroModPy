"""Runtime summary of a Boussinesq solve: rates in mm/day, volumes in m3/day and times in days.

The solver holds a rate in m/s. A rate of 1 m/s is 1000 mm * 86 400 s/day mm/day, and over a
cell of area A it is A m3/s, so A * 86 400 m3/day. A negative rate is no excess and no deficit.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.solver.boussinesq.runtime_summary import (
    elapsed_days_for_snapshots,
    history_or_current,
    record_surface_threshold_summary,
)

_AREA_M2 = 1.0e6


def _solver(excess_m_s: float, deficit_m_s: float, head_m: float = 10.0) -> SimpleNamespace:
    state = SimpleNamespace(
        head_history_m=np.array([[head_m], [head_m]]),
        head_m=np.array([head_m]),
        saturation_excess_history_m_s=np.array([[0.0], [excess_m_s]]),
        saturation_excess_rate_m_s=np.array([0.0]),
        dry_deficit_history_m_s=np.array([[0.0], [deficit_m_s]]),
        dry_deficit_rate_m_s=np.array([0.0]),
        period_lengths_seconds=(86400.0,),
    )
    mesh = SimpleNamespace(
        n_cells=1,
        z_top_m=np.array([9.0]),
        z_bottom_m=np.array([0.0]),
        cell_area_m2=np.array([_AREA_M2]),
        storage_coefficient=np.array([0.1]),
    )
    return SimpleNamespace(
        state=state,
        mesh=mesh,
        runtime_summary={},
        _surface_interaction_model=lambda: "threshold",
    )


# One row per rate in m/s: its value in mm/day and in m3/day over a cell of 1e6 m2, by hand.
_RATES = [
    pytest.param(1.0e-6, 86.4, 86400.0, id="one_micrometer_per_second"),
    pytest.param(1.0e-8, 0.864, 864.0, id="ten_nanometers_per_second"),
    pytest.param(1.0e-3, 86_400.0, 86_400_000.0, id="a_flood"),
    pytest.param(0.0, 0.0, 0.0, id="none"),
    pytest.param(-1.0e-6, 0.0, 0.0, id="a_negative_rate_is_no_excess"),
]


@pytest.mark.parametrize(("rate_m_s", "mm_day", "m3_day"), _RATES)
def test_a_surface_excess_is_reported_in_mm_per_day_and_m3_per_day(
    rate_m_s, mm_day, m3_day
) -> None:
    solver = _solver(rate_m_s, 0.0)

    record_surface_threshold_summary(solver)

    summary = solver.runtime_summary
    assert summary["surface_threshold_peak_cell_rate_mm_day"] == pytest.approx(mm_day, rel=1e-12)
    assert summary["surface_threshold_peak_total_m3_day"] == pytest.approx(m3_day, rel=1e-12)
    assert summary["surface_threshold_final_total_m3_day"] == pytest.approx(m3_day, rel=1e-12)


@pytest.mark.parametrize(("rate_m_s", "mm_day", "m3_day"), _RATES)
def test_a_dry_deficit_is_reported_in_mm_per_day_and_m3_per_day(rate_m_s, mm_day, m3_day) -> None:
    solver = _solver(0.0, rate_m_s)

    record_surface_threshold_summary(solver)

    summary = solver.runtime_summary
    assert summary["bottom_constraint_peak_cell_rate_mm_day"] == pytest.approx(mm_day, rel=1e-12)
    assert summary["bottom_constraint_peak_total_m3_day"] == pytest.approx(m3_day, rel=1e-12)
    # One period of 86 400 s, so the integrated volume in m3 equals the m3/day of the rate.
    assert summary["bottom_constraint_integrated_volume_m3"] == pytest.approx(m3_day, rel=1e-12)


def test_a_state_with_no_mesh_records_nothing() -> None:
    solver = _solver(1.0e-6, 0.0)
    solver.mesh = None

    record_surface_threshold_summary(solver)

    assert solver.runtime_summary == {}


# One row per time axis: the period lengths in seconds, the snapshots asked and the elapsed days.
_ELAPSED = [
    pytest.param((86400.0, 172800.0), 3, [0.0, 1.0, 3.0], id="periods_in_seconds_to_days"),
    pytest.param((86400.0,), 4, [0.0, 1.0, 1.0, 1.0], id="the_last_day_is_held"),
    pytest.param((43200.0,), 2, [0.0, 0.5], id="half_a_day"),
]


@pytest.mark.parametrize(("periods", "count", "days"), _ELAPSED)
def test_the_elapsed_time_of_a_snapshot_is_in_days(periods, count, days) -> None:
    state = SimpleNamespace(period_lengths_seconds=periods)

    np.testing.assert_allclose(elapsed_days_for_snapshots(state, n_snapshots=count), days)


def test_a_missing_state_gives_zero_days() -> None:
    assert elapsed_days_for_snapshots(None, n_snapshots=3).tolist() == [0.0, 0.0, 0.0]


def test_complementarity_overlap_of_excess_and_gap() -> None:
    # Head 8 m under a top of 9 m leaves a gap of 1 m, and an excess of 1e-6 m/s over that gap
    # overlaps by 1e-6 m/s x 1 m = 1e-6 m2/s. The first snapshot is the start and is not scored.
    solver = _solver(1.0e-6, 0.0, head_m=8.0)
    solver._surface_interaction_model = lambda: "complementarity"

    record_surface_threshold_summary(solver)

    summary = solver.runtime_summary
    assert summary["surface_complementarity_min_gap_m"] == pytest.approx(1.0)
    assert summary["surface_complementarity_min_rate_m_s"] == pytest.approx(1.0e-6)
    assert summary["surface_complementarity_peak_overlap_m2_s"] == pytest.approx(1.0e-6)
    assert summary["surface_complementarity_final_overlap_m2_s"] == pytest.approx(1.0e-6)


# One row per pair: the history, the current value and the array that is kept.
_HISTORIES = [
    pytest.param([[1.0, 2.0], [3.0, 4.0]], None, [[1.0, 2.0], [3.0, 4.0]], id="history kept"),
    pytest.param([1.0, 2.0], None, [[1.0, 2.0]], id="one-row history as a vector"),
    pytest.param(None, [5.0, 6.0], [[5.0, 6.0]], id="current when no history"),
    pytest.param(np.empty((0, 2)), [5.0, 6.0], [[5.0, 6.0]], id="current when history empty"),
    pytest.param(None, None, [[7.0, 7.0]], id="default when nothing"),
    pytest.param([], np.array([]), [[7.0, 7.0]], id="default when both empty"),
]


@pytest.mark.parametrize(("history", "current", "expected"), _HISTORIES)
def test_history_or_current(history, current, expected) -> None:
    result = history_or_current(history, current, n_columns=2, default_value=7.0)

    np.testing.assert_array_equal(result, expected)
