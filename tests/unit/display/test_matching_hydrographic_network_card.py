"""The one-page card of a two-stage downslope-distance calibration.

The card is driven exactly as a staged session drives it: one row per trial
in ``calibration_iterations``, the phases chained through
``calibration_sessions``. The tests read the panels, the artists, the
annotations and the refusals, never pixels.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pandas as pd
import pytest

from hydromodpy.display.figures.matching_hydrographic_network_card import (
    MatchingHydrographicNetworkCard,
)
from hydromodpy.display.style import HIGH_CONTRAST_TRIPLET

from ._render_helpers import relative_luminance

OUTPUT = "net"
ROOT_ID = "s-root"
STORAGE_ID = "s-storage"

# The sweep of the sibling bracket figure: it changes sign once, then two
# bisection steps close on [3.2e-05, 1e-04]. The end carrying the smaller
# residual is 3.2e-05, and that is the trial every diagnostic is read at.
ROOT_VALUES = [1e-5, 1e-3, 1e-4, 3.2e-5]
ROOT_RESIDUALS = [300.0, -400.0, -120.0, 40.0]
CLOSED_VALUE = 3.2e-5
BRACKET = (3.2e-5, 1e-4)

STORAGE_VALUES = [0.01, 0.05, 0.1]
STORAGE_OBJECTIVES = [0.42, 0.11, 0.30]


@pytest.fixture
def mpl():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


# --------------------------------------------------------------------------- #
# the session a staged calibration writes
# --------------------------------------------------------------------------- #


PUBLISHED = {
    "Doptim": 217.5,
    "roptim": 0.87,
    "roptim_valid": 1.0,
    "validity_length_m": 500.0,
    "validity_length_provenance": 0.0,
    "n_valid": 120.0,
    "n_excess": 30.0,
    "n_missing": 18.0,
    "L_ref": 250.0,
}
"""A trial at h_obs = 250 m: Doptim = 0.87 h_obs, bounded by the auto 2 h_obs."""


def _criterion_diagnostics(mean_recharge: float) -> dict[str, float]:
    """The diagnostics a real trial publishes, asked of their own producer.

    The card cannot import ``calibration``, so it spells the recharge key by
    hand; building the dict here from ``NetworkGeometry`` is what proves the
    two spellings are the same one. Only the fields ``diagnostics`` reads
    carry meaning, the rest of the geometry is filler.
    """
    import numpy as np

    from hydromodpy.calibration.observations.network_geometry import NetworkGeometry

    geometry = NetworkGeometry(
        metric=None,
        observed=np.array([True, False]),
        outlet=0,
        catchment=np.array([True, True]),
        catchment_mismatch=0.0,
        distance_to_observed=np.zeros(2),
        distance_to_observed_raw=np.zeros(2),
        cell_area_m2=np.ones(2),
        threshold_m3_s=np.ones(2),
        mean_recharge_m_s=mean_recharge,
        h_obs_m=250.0,
        saturation_cap_m=1.0,
        excluded=None,
        alpha_obs_closure=1.0,
        alpha_obs_closure_catchment=1.0,
        frac_obs_outside_catchment=0.0,
        frac_reachable_obs_raw=1.0,
    )
    return geometry.diagnostics


def _root_rows(
    *,
    residuals: list[float] | None = None,
    diagnostics: dict[str, float] | None = None,
    values: list[float] | None = None,
    session_id: str | None = ROOT_ID,
) -> list[dict]:
    """Stage one: the root search on the ratio, with its criterion diagnostics."""
    published = dict(PUBLISHED)
    if diagnostics is not None:
        published = dict(diagnostics)
    rows = []
    for index, (value, residual) in enumerate(
        zip(values or ROOT_VALUES, residuals or ROOT_RESIDUALS, strict=True)
    ):
        metrics = {f"{OUTPUT}.{key}": number for key, number in published.items()}
        if residual is None:
            metrics = {}
        else:
            metrics[f"{OUTPUT}.J_signed"] = residual
        row = {
            "iteration": index,
            "parameters": {"K_over_R": {"value": value}},
            "metrics": metrics,
            "objective_value": abs(residual) if residual is not None else None,
            "status": "completed" if residual is not None else "failed",
        }
        if session_id is not None:
            row["session_id"] = session_id
        rows.append(row)
    return rows


def _storage_rows(
    *,
    objectives: list[float] | None = None,
    session_id: str = STORAGE_ID,
) -> list[dict]:
    """Stage two: the storage parameter against the objective of its session."""
    return [
        {
            "iteration": index,
            "session_id": session_id,
            "parameters": {"specific_yield": {"value": value}},
            "metrics": {},
            "objective_value": objective,
            "status": "completed" if objective is not None else "failed",
        }
        for index, (value, objective) in enumerate(
            zip(STORAGE_VALUES, objectives or STORAGE_OBJECTIVES, strict=True)
        )
    ]


def _sessions(*, staged: bool = True) -> pd.DataFrame:
    rows = [
        {
            "session_id": ROOT_ID,
            "phase_name": "root search",
            "phase_index": 0,
            "parent_session_id": None,
            "root_session_id": ROOT_ID,
            "objective_name": "distance_gap",
            "best_trial": 3,
            "best_objective": 40.0,
        }
    ]
    if staged:
        rows.append(
            {
                "session_id": STORAGE_ID,
                "phase_name": "storage",
                "phase_index": 1,
                "parent_session_id": ROOT_ID,
                "root_session_id": ROOT_ID,
                "objective_name": "nse",
                "best_trial": 1,
                "best_objective": 0.11,
            }
        )
    return pd.DataFrame(rows)


def _run(rows: list[dict], sessions: pd.DataFrame | None, name: str = "cheze") -> SimpleNamespace:
    return SimpleNamespace(
        sim_id="sim-cheze",
        name=name,
        calibration_iterations=pd.DataFrame(rows),
        calibration_sessions=sessions,
        has_table=lambda table: table == "calibration_iterations",
    )


def _staged_run(**kwargs) -> SimpleNamespace:
    return _run(_root_rows(**kwargs) + _storage_rows(), _sessions())


def _single_phase_run(**kwargs) -> SimpleNamespace:
    return _run(_root_rows(**kwargs), _sessions(staged=False))


# --------------------------------------------------------------------------- #
# reading the drawn card
# --------------------------------------------------------------------------- #


def _panel(fig, prefix: str):
    return next(ax for ax in fig.axes if str(ax.get_title()).startswith(prefix))


def _texts(ax) -> str:
    return "\n".join(item.get_text() for item in ax.texts)


def _patch(ax, prefix: str):
    return next(item for item in ax.patches if str(item.get_label()).startswith(prefix))


def _has_patch(ax, prefix: str) -> bool:
    return any(str(item.get_label()).startswith(prefix) for item in ax.patches)


def _line(ax, prefix: str):
    return next(item for item in ax.lines if str(item.get_label()).startswith(prefix))


def _rgba(color: str):
    from matplotlib.colors import to_rgba

    return to_rgba(color)


# --------------------------------------------------------------------------- #
# the grid
# --------------------------------------------------------------------------- #


def test_the_card_lays_out_the_four_panels_of_the_method(mpl) -> None:
    fig = MatchingHydrographicNetworkCard().plot(_staged_run())

    try:
        titles = [str(ax.get_title()) for ax in fig.axes]
        assert len(fig.axes) == 4
        assert titles[0].startswith("Stage 1")
        assert titles[1].startswith("Stage 2")
        assert any(title.startswith("Validity") for title in titles)
        assert any(title.startswith("Cells at the calibrated point") for title in titles)
        assert "cheze" in fig.get_suptitle()
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# stage one: the value and the bracket
# --------------------------------------------------------------------------- #


def test_stage_one_reports_the_value_it_closed_on_and_the_bracket(mpl) -> None:
    fig = MatchingHydrographicNetworkCard().plot(_staged_run())

    try:
        ax = _panel(fig, "Stage 1")
        assert ax.get_xscale() == "log"
        assert ax.get_xlabel() == "K_over_R (-)"
        assert "root search" in ax.get_title()

        marker = _line(ax, "K_over_R =")
        assert marker.get_xdata()[0] == pytest.approx(CLOSED_VALUE)
        bracket = _patch(ax, "bracket")
        assert bracket.get_x() == pytest.approx(BRACKET[0])
        assert bracket.get_x() + bracket.get_width() == pytest.approx(BRACKET[1])

        note = _texts(ax)
        assert f"{CLOSED_VALUE:.4g}" in note
        assert f"[{BRACKET[0]:.4g}, {BRACKET[1]:.4g}]" in note
        assert "factor 3.125" in note
    finally:
        mpl.close(fig)


def test_stage_one_keeps_every_evaluation_it_walked(mpl) -> None:
    fig = MatchingHydrographicNetworkCard().plot(_staged_run())

    try:
        ax = _panel(fig, "Stage 1")
        evaluations = _line(ax, "evaluation")
        assert sorted(evaluations.get_xdata()) == sorted(ROOT_VALUES)
    finally:
        mpl.close(fig)


def test_stage_one_says_so_when_no_sign_change_was_sampled(mpl) -> None:
    run = _staged_run(residuals=[300.0, 120.0, 80.0, 40.0])

    fig = MatchingHydrographicNetworkCard().plot(run)

    try:
        ax = _panel(fig, "Stage 1")
        assert "no sign change" in _texts(ax)
        assert not _has_patch(ax, "bracket")
        assert not [line for line in ax.lines if str(line.get_label()).startswith("K_over_R =")]
    finally:
        mpl.close(fig)


def test_a_point_with_no_root_reports_no_calibrated_diagnostics(mpl) -> None:
    # Reading the least-bad point as the answer would be a minimised mean
    # distance in disguise, so its roptim and its counts are not the card's.
    run = _staged_run(residuals=[300.0, 120.0, 80.0, 40.0])

    fig = MatchingHydrographicNetworkCard().plot(run)

    try:
        assert "no root was closed" in _texts(_panel(fig, "Validity"))
        assert "no root was closed" in _texts(_panel(fig, "Cells at the calibrated point"))
        assert not _panel(fig, "Cells at the calibrated point").patches
    finally:
        mpl.close(fig)


def test_stage_one_refuses_a_non_positive_ratio(mpl) -> None:
    run = _staged_run(values=[0.0, 1e-3, 1e-4, 3.2e-5])

    with pytest.raises(ValueError, match="non-positive"):
        MatchingHydrographicNetworkCard().plot(run)


# --------------------------------------------------------------------------- #
# stage two: the storage value and its metric
# --------------------------------------------------------------------------- #


def test_stage_two_reports_the_storage_value_and_its_metric(mpl) -> None:
    fig = MatchingHydrographicNetworkCard().plot(_staged_run())

    try:
        ax = _panel(fig, "Stage 2")
        assert ax.get_xlabel() == "specific_yield (-)"
        assert ax.get_ylabel() == "nse (-)"
        assert "storage" in ax.get_title()

        best = _line(ax, "specific_yield =")
        assert best.get_xdata()[0] == pytest.approx(0.05)
        note = _texts(ax)
        assert "specific_yield = 0.05" in note
        assert "nse = 0.11" in note
    finally:
        mpl.close(fig)


def test_a_single_phase_session_still_draws_with_stage_two_marked_not_run(mpl) -> None:
    fig = MatchingHydrographicNetworkCard().plot(_single_phase_run())

    try:
        assert len(fig.axes) == 4
        ax = _panel(fig, "Stage 2")
        assert "not run" in ax.get_title()
        assert "not run" in _texts(ax)
        assert not ax.lines and not ax.collections
        # The first stage is untouched by the absence of the second.
        assert _line(_panel(fig, "Stage 1"), "K_over_R =").get_xdata()[0] == pytest.approx(
            CLOSED_VALUE
        )
    finally:
        mpl.close(fig)


def test_a_failed_storage_trial_is_counted_and_never_drawn_as_zero(mpl) -> None:
    run = _run(_root_rows() + _storage_rows(objectives=[0.42, 0.11, None]), _sessions())

    fig = MatchingHydrographicNetworkCard().plot(run)

    try:
        ax = _panel(fig, "Stage 2")
        drawn = _line(ax, "trial").get_ydata()
        assert len(drawn) == 3
        assert pd.isna(drawn[2]), "a failed trial keeps its abscissa and carries no objective"
        assert "1 of 3 trials failed" in _texts(ax)
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# the validity indicator
# --------------------------------------------------------------------------- #


def test_the_validity_panel_shows_doptim_against_the_trial_validity_length(mpl) -> None:
    fig = MatchingHydrographicNetworkCard().plot(_staged_run())

    try:
        ax = _panel(fig, "Validity")
        assert ax.get_xlabel() == "Doptim = (D_so + D_os) / 2 (m)"
        bar = _patch(ax, "Doptim")
        assert bar.get_width() == pytest.approx(217.5)
        assert bar.get_facecolor() == _rgba(HIGH_CONTRAST_TRIPLET[0])
        bound = _line(ax, "bound")
        assert bound.get_xdata()[0] == pytest.approx(500.0)
        note = _texts(ax)
        assert "Doptim = 217.5 m <= 500 m" in note
        assert "within the validity bound" in note
        assert "validity length: two cells, 2 h_obs" in note
        assert "roptim = Doptim / h_obs = 0.87, h_obs = 250 m" in note
    finally:
        mpl.close(fig)


def test_a_breach_qualifies_the_value_and_never_withholds_it(mpl) -> None:
    run = _staged_run(
        diagnostics={
            **PUBLISHED,
            "Doptim": 2360.0,
            "roptim": 9.44,
            "roptim_valid": 0.0,
            "n_valid": 4.0,
            "n_excess": 210.0,
            "n_missing": 190.0,
        }
    )

    fig = MatchingHydrographicNetworkCard().plot(run)

    try:
        validity = _panel(fig, "Validity")
        bar = _patch(validity, "Doptim")
        assert bar.get_width() == pytest.approx(2360.0)
        assert bar.get_facecolor() == _rgba(HIGH_CONTRAST_TRIPLET[2])
        note = _texts(validity)
        assert "2360 m > 500 m" in note
        assert "breached" in note
        # The calibrated value stands: stage one is drawn exactly as before.
        assert _line(_panel(fig, "Stage 1"), "K_over_R =").get_xdata()[0] == pytest.approx(
            CLOSED_VALUE
        )
    finally:
        mpl.close(fig)


def test_a_widened_validity_length_is_the_bound_not_two_cells(mpl) -> None:
    # roptim = 2.4 breaks the paper's roptim <= 2, but a declared positional
    # accuracy of 400 m widened the trial's bound to 800 m: the trial is valid,
    # and the card says so with the run's own verdict.
    run = _staged_run(
        diagnostics={
            **PUBLISHED,
            "Doptim": 600.0,
            "roptim": 2.4,
            "validity_length_m": 800.0,
            "validity_length_provenance": 2.0,
        }
    )

    fig = MatchingHydrographicNetworkCard().plot(run)

    try:
        validity = _panel(fig, "Validity")
        assert _patch(validity, "Doptim").get_facecolor() == _rgba(HIGH_CONTRAST_TRIPLET[0])
        assert _line(validity, "bound").get_xdata()[0] == pytest.approx(800.0)
        note = _texts(validity)
        assert "600 m <= 800 m: within the validity bound" in note
        assert "widened by the declared positional accuracy" in note
        assert "roptim = Doptim / h_obs = 2.4" in note
    finally:
        mpl.close(fig)


def test_a_snap_floor_that_sets_the_length_is_named(mpl) -> None:
    run = _staged_run(
        diagnostics={**PUBLISHED, "validity_length_m": 610.0, "validity_length_provenance": 1.0}
    )

    fig = MatchingHydrographicNetworkCard().plot(run)

    try:
        note = _texts(_panel(fig, "Validity"))
        assert "217.5 m <= 610 m" in note
        assert "one cell plus the snap floor F" in note
    finally:
        mpl.close(fig)


def test_an_applied_snap_that_moved_too_far_is_named_beside_the_bar(mpl) -> None:
    snap = {
        "snap_mode": 2.0,
        "snap_displacement_p90_m": 300.0,
        "snap_displacement_bound_m": 250.0,
        "snap_rejected_share": 0.02,
        "snap_rejected_share_max": 0.1,
    }
    run = _staged_run(diagnostics={**PUBLISHED, **snap})

    fig = MatchingHydrographicNetworkCard().plot(run)

    try:
        note = _texts(_panel(fig, "Validity"))
        assert "snapped map breaks Eq. 4: its displacement p90 exceeds its bound" in note
        assert "rejected more cells" not in note
    finally:
        mpl.close(fig)


def test_a_diagnosed_snap_adds_nothing_to_the_verdict(mpl) -> None:
    run = _staged_run(diagnostics={**PUBLISHED, "snap_mode": 1.0, "snap_displacement_p90_m": 900.0})

    fig = MatchingHydrographicNetworkCard().plot(run)

    try:
        assert "snapped map" not in _texts(_panel(fig, "Validity"))
    finally:
        mpl.close(fig)


def test_an_unpublished_doptim_is_drawn_as_absent_never_as_zero(mpl) -> None:
    run = _staged_run(
        diagnostics={"n_valid": 120.0, "n_excess": 30.0, "n_missing": 18.0},
    )

    fig = MatchingHydrographicNetworkCard().plot(run)

    try:
        ax = _panel(fig, "Validity")
        assert not ax.patches
        assert "Doptim not published" in _texts(ax)
    finally:
        mpl.close(fig)


def test_an_unpublished_validity_length_is_never_replaced_by_two_cells(mpl) -> None:
    published = {key: value for key, value in PUBLISHED.items() if key != "validity_length_m"}

    fig = MatchingHydrographicNetworkCard().plot(_staged_run(diagnostics=published))

    try:
        ax = _panel(fig, "Validity")
        assert not ax.patches
        assert "validity length not published" in _texts(ax)
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# the three classes
# --------------------------------------------------------------------------- #


def test_the_three_counts_are_drawn_apart_so_they_cannot_cancel(mpl) -> None:
    fig = MatchingHydrographicNetworkCard().plot(_staged_run())

    try:
        ax = _panel(fig, "Cells at the calibrated point")
        widths = {str(patch.get_label()).split(":")[0]: patch.get_width() for patch in ax.patches}
        assert widths == {"valid": 120.0, "excess": 30.0, "missing": 18.0}
        labels = [str(patch.get_label()) for patch in ax.patches]
        assert any("120" in label for label in labels)
        colors = {
            str(patch.get_label()).split(":")[0]: patch.get_facecolor() for patch in ax.patches
        }
        assert colors["valid"] == _rgba(HIGH_CONTRAST_TRIPLET[0])
        assert colors["excess"] == _rgba(HIGH_CONTRAST_TRIPLET[1])
        assert colors["missing"] == _rgba(HIGH_CONTRAST_TRIPLET[2])
    finally:
        mpl.close(fig)


def test_an_absent_count_is_named_absent_and_gets_no_bar(mpl) -> None:
    run = _staged_run(
        diagnostics={"roptim": 0.87, "roptim_valid": 1.0, "n_valid": 120.0, "n_missing": 18.0},
    )

    fig = MatchingHydrographicNetworkCard().plot(run)

    try:
        ax = _panel(fig, "Cells at the calibrated point")
        drawn = {str(patch.get_label()).split(":")[0] for patch in ax.patches}
        assert drawn == {"valid", "missing"}
        assert "excess" in _texts(ax)
        assert "not published" in _texts(ax)
    finally:
        mpl.close(fig)


def test_the_three_classes_stay_apart_in_greyscale() -> None:
    luminances = sorted(relative_luminance(color) for color in HIGH_CONTRAST_TRIPLET)
    gaps = [high - low for low, high in zip(luminances[:-1], luminances[1:], strict=False)]
    assert min(gaps) > 0.1


# --------------------------------------------------------------------------- #
# the recharge the ratio was measured against
# --------------------------------------------------------------------------- #


def test_the_mean_recharge_is_carried_on_the_card(mpl) -> None:
    fig = MatchingHydrographicNetworkCard().plot(_staged_run(), mean_recharge=3.2e-8)

    try:
        note = _texts(_panel(fig, "Stage 1"))
        assert "3.2e-08" in note
        assert "m/s" in note
    finally:
        mpl.close(fig)


def test_a_recharge_the_session_published_is_read_from_the_trials(mpl) -> None:
    # The trial publishes what the criterion publishes, under the name the
    # criterion gives it, prefixed by the output the way a scored output is.
    published = {**PUBLISHED, **_criterion_diagnostics(4.5e-8)}
    assert 4.5e-8 in published.values()

    fig = MatchingHydrographicNetworkCard().plot(_staged_run(diagnostics=published))

    try:
        assert "4.5e-08" in _texts(_panel(fig, "Stage 1"))
    finally:
        mpl.close(fig)


def test_an_undeclared_recharge_says_the_ratio_is_not_a_conductivity(mpl) -> None:
    fig = MatchingHydrographicNetworkCard().plot(_staged_run())

    try:
        note = _texts(_panel(fig, "Stage 1"))
        assert "mean recharge not declared" in note
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# reaching the two phases
# --------------------------------------------------------------------------- #


def test_the_phases_are_ordered_by_the_chain_not_by_the_table(mpl) -> None:
    # The storage trials come first in the table; the chain still puts the
    # root search on stage one.
    run = _run(_storage_rows() + _root_rows(), _sessions())

    fig = MatchingHydrographicNetworkCard().plot(run)

    try:
        assert "root search" in _panel(fig, "Stage 1").get_title()
        assert "storage" in _panel(fig, "Stage 2").get_title()
    finally:
        mpl.close(fig)


def test_a_run_without_a_session_table_reads_its_trials_as_one_phase(mpl) -> None:
    run = _run(_root_rows(session_id=None), None)

    fig = MatchingHydrographicNetworkCard().plot(run)

    try:
        assert _line(_panel(fig, "Stage 1"), "K_over_R =").get_xdata()[0] == pytest.approx(
            CLOSED_VALUE
        )
        assert "not run" in _panel(fig, "Stage 2").get_title()
    finally:
        mpl.close(fig)


def test_a_chain_longer_than_two_phases_says_which_one_is_drawn(mpl) -> None:
    sessions = _sessions()
    third = sessions.iloc[1].to_dict()
    third.update({"session_id": "s-third", "phase_index": 2, "phase_name": "polish"})
    run = _run(
        _root_rows() + _storage_rows() + _storage_rows(session_id="s-third"),
        pd.concat([sessions, pd.DataFrame([third])], ignore_index=True),
    )

    fig = MatchingHydrographicNetworkCard().plot(run)

    try:
        assert "2 of 3" in _panel(fig, "Stage 2").get_title()
    finally:
        mpl.close(fig)


def test_the_card_reads_the_json_blocks_the_index_hands_back(mpl) -> None:
    run = _staged_run()
    frame = run.calibration_iterations
    frame["parameters"] = [json.dumps(block) for block in frame["parameters"]]
    frame["metrics"] = [json.dumps(block) for block in frame["metrics"]]

    fig = MatchingHydrographicNetworkCard().plot(run)

    try:
        assert _line(_panel(fig, "Stage 1"), "K_over_R =").get_xdata()[0] == pytest.approx(
            CLOSED_VALUE
        )
        assert _patch(_panel(fig, "Validity"), "Doptim").get_width() == pytest.approx(217.5)
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# the gallery
# --------------------------------------------------------------------------- #


def test_a_run_that_never_calibrated_is_skipped_with_its_reason() -> None:
    barren = SimpleNamespace(
        sim_id="sim-plain",
        name="plain",
        has_table=lambda table: False,
    )

    reason = MatchingHydrographicNetworkCard().unavailable_reason(barren)

    assert reason is not None
    assert "calibration_iterations" in reason


# --------------------------------------------------------------------------- #
# two bounds in the cost: the keys the trial publishes are suffixed
# --------------------------------------------------------------------------- #

# The sweep closes K*_minimal on [3.2e-05, 1e-04] at 3.2e-05 and K*_maximal on
# [3.2e-04, 1e-03] at 3.2e-04. The last trial is the solve at the combined
# value, their geometric mean weighted 0.5 / 0.5: the trial the search
# returns, where the run reads Eq. 4 on each bound.
TWO_VALUES = [1e-5, 1e-4, 1e-3, 3.2e-5, 3.2e-4, 1.0119e-4]
TWO_RESIDUALS = {
    "minimal": [200.0, -50.0, -300.0, 30.0, -120.0, -45.0],
    "maximal": [400.0, 150.0, -80.0, 250.0, 20.0, 140.0],
}
COMBINED_TRIAL = 5

AT_THE_RETURNED_TRIAL = {
    "minimal": {
        "Doptim": 217.5,
        "roptim": 0.87,
        "validity_length_m": 500.0,
        "validity_length_provenance": 0.0,
        "L_ref": 250.0,
        "n_valid": 120.0,
        "n_excess": 30.0,
        "n_missing": 18.0,
    },
    "maximal": {
        "Doptim": 820.0,
        "roptim": 3.28,
        "validity_length_m": 500.0,
        "validity_length_provenance": 0.0,
        "L_ref": 250.0,
        "n_valid": 300.0,
        "n_excess": 90.0,
        "n_missing": 60.0,
    },
}
"""What each bound publishes at the combined trial; every other trial carries 999."""

ROOTS = {
    "parameter": "K_over_R",
    "minimal": {
        "k_star": 3.2e-5,
        "trial_id": 3,
        "residual": 30.0,
        "weight": 0.5,
        "low": 3.2e-5,
        "high": 1e-4,
        "closed": True,
    },
    "maximal": {
        "k_star": 3.2e-4,
        "trial_id": 4,
        "residual": 20.0,
        "weight": 0.5,
        "low": 3.2e-4,
        "high": 1e-3,
        "closed": True,
    },
    "delta_log10": 1.0,
    "value": 1.0119e-4,
    "combined_trial_id": COMBINED_TRIAL,
    "closed": True,
}
"""The ``extra["roots"]`` record of the report, as ``roots_record`` writes it."""


def _two_bound_rows(*, weights: tuple[float, float] = (0.5, 0.5)) -> list[dict]:
    rows = []
    for index, value in enumerate(TWO_VALUES):
        metrics = {f"{OUTPUT}.n_bounds_scored": 2.0, f"{OUTPUT}.R_mean_m_s": 3.0e-8}
        for bound, weight in zip(("minimal", "maximal"), weights, strict=True):
            metrics[f"{OUTPUT}.J_signed_{bound}"] = TWO_RESIDUALS[bound][index]
            metrics[f"{OUTPUT}.weight_{bound}"] = weight
            for key, number in AT_THE_RETURNED_TRIAL[bound].items():
                published = number if index == COMBINED_TRIAL else 999.0
                metrics[f"{OUTPUT}.{key}_{bound}"] = published
        rows.append(
            {
                "iteration": index,
                "session_id": ROOT_ID,
                "parameters": {"K_over_R": {"value": value}},
                "metrics": metrics,
                "objective_value": 1.0,
                "status": "completed",
            }
        )
    return rows


def _two_bound_run(*, best_trial: int | None = COMBINED_TRIAL, **kwargs) -> SimpleNamespace:
    sessions = _sessions(staged=False)
    sessions.loc[0, "best_trial"] = best_trial
    return _run(_two_bound_rows(**kwargs), sessions)


def test_two_bounds_draw_one_bracket_per_bound_from_the_trials(mpl) -> None:
    fig = MatchingHydrographicNetworkCard().plot(_two_bound_run())

    try:
        ax = _panel(fig, "Stage 1")
        assert "two bounds" in ax.get_title()
        minimal = _patch(ax, "bracket minimal")
        assert minimal.get_x() == pytest.approx(3.2e-5)
        assert minimal.get_x() + minimal.get_width() == pytest.approx(1e-4)
        maximal = _patch(ax, "bracket maximal")
        assert maximal.get_x() == pytest.approx(3.2e-4)
        assert maximal.get_x() + maximal.get_width() == pytest.approx(1e-3)
        assert _line(ax, "K*_minimal").get_xdata()[0] == pytest.approx(3.2e-5)
        assert _line(ax, "K*_maximal").get_xdata()[0] == pytest.approx(3.2e-4)
        note = _texts(ax)
        assert "roots record not passed" in note
        assert "diagnostics read at the returned trial, K_over_R = 0.0001012" in note
        assert "3e-08 m/s" in note
    finally:
        mpl.close(fig)


def test_two_bounds_write_the_roots_delta_and_the_combined_value_of_the_report(mpl) -> None:
    fig = MatchingHydrographicNetworkCard().plot(_two_bound_run(), roots=ROOTS)

    try:
        ax = _panel(fig, "Stage 1")
        note = _texts(ax)
        assert "K*_minimal = 3.2e-05, bracket [3.2e-05, 0.0001]" in note
        assert "K*_maximal = 0.00032, bracket [0.00032, 0.001]" in note
        assert "Delta = log10(K*_maximal / K*_minimal) = 1 decade(s)" in note
        assert "combined K_over_R = 0.0001012, weighted geometric mean 0.5 / 0.5" in note
        assert _line(ax, "K_over_R =").get_xdata()[0] == pytest.approx(1.0119e-4)
        assert "roots record not passed" not in note
    finally:
        mpl.close(fig)


def test_an_unsolved_combined_value_is_said_not_drawn(mpl) -> None:
    roots = {**ROOTS, "value": None, "combined_trial_id": None, "closed": False}

    fig = MatchingHydrographicNetworkCard().plot(_two_bound_run(), roots=roots)

    try:
        ax = _panel(fig, "Stage 1")
        assert "combined value not solved" in _texts(ax)
        assert not [line for line in ax.lines if str(line.get_label()).startswith("K_over_R =")]
        # The session's best trial still says where the run read Eq. 4.
        assert _patch(_panel(fig, "Validity"), "Doptim minimal").get_width() == pytest.approx(217.5)
    finally:
        mpl.close(fig)


def test_two_bounds_qualify_each_bound_at_the_returned_trial(mpl) -> None:
    fig = MatchingHydrographicNetworkCard().plot(_two_bound_run())

    try:
        ax = _panel(fig, "Validity")
        assert [tick.get_text() for tick in ax.get_yticklabels()] == ["minimal", "maximal"]
        minimal = _patch(ax, "Doptim minimal")
        maximal = _patch(ax, "Doptim maximal")
        assert minimal.get_width() == pytest.approx(217.5)
        assert maximal.get_width() == pytest.approx(820.0)
        assert minimal.get_facecolor() == _rgba(HIGH_CONTRAST_TRIPLET[0])
        assert maximal.get_facecolor() == _rgba(HIGH_CONTRAST_TRIPLET[2])
        assert _line(ax, "bound minimal").get_xdata()[0] == pytest.approx(500.0)
        assert _line(ax, "bound maximal").get_xdata()[0] == pytest.approx(500.0)
        note = _texts(ax)
        assert "minimal (weight 0.5): Doptim = 217.5 m <= 500 m, Eq. 4 holds" in note
        assert "maximal (weight 0.5): Doptim = 820 m > 500 m, Eq. 4 fails" in note
        assert "J_signed = -45 m, roptim = 0.87, h_obs = 250 m, length: two cells, 2 h_obs" in note
        assert "J_signed = 140 m, roptim = 3.28, h_obs = 250 m" in note
        assert "not published" not in note
        assert "999" not in note
    finally:
        mpl.close(fig)


def test_two_bounds_split_the_cells_of_each_bound_side_by_side(mpl) -> None:
    fig = MatchingHydrographicNetworkCard().plot(_two_bound_run())

    try:
        ax = _panel(fig, "Cells at the calibrated point")
        widths = {
            (label.split(":")[0], label.rsplit(", ", 1)[1].split(" ")[0]): patch.get_width()
            for patch in ax.patches
            for label in [str(patch.get_label())]
        }
        assert widths == {
            ("valid", "minimal"): 120.0,
            ("excess", "minimal"): 30.0,
            ("missing", "minimal"): 18.0,
            ("valid", "maximal"): 300.0,
            ("excess", "maximal"): 90.0,
            ("missing", "maximal"): 60.0,
        }
        hatched = {
            str(patch.get_label()).rsplit(", ", 1)[1].split(" ")[0]: bool(patch.get_hatch())
            for patch in ax.patches
        }
        assert hatched == {"minimal": False, "maximal": True}
        assert "not published" not in _texts(ax)
    finally:
        mpl.close(fig)


def test_the_combined_trial_of_the_report_wins_over_the_session_best(mpl) -> None:
    fig = MatchingHydrographicNetworkCard().plot(_two_bound_run(best_trial=0), roots=ROOTS)

    try:
        validity = _panel(fig, "Validity")
        assert _patch(validity, "Doptim minimal").get_width() == pytest.approx(217.5)
    finally:
        mpl.close(fig)


def test_two_bounds_without_a_returned_trial_qualify_nothing(mpl) -> None:
    fig = MatchingHydrographicNetworkCard().plot(_two_bound_run(best_trial=None))

    try:
        for title in ("Validity", "Cells at the calibrated point"):
            ax = _panel(fig, title)
            assert "the returned trial is not known" in _texts(ax)
            assert not ax.patches
        # The brackets are still proven by the trials.
        assert _has_patch(_panel(fig, "Stage 1"), "bracket minimal")
    finally:
        mpl.close(fig)


def test_a_bound_weighted_zero_is_drawn_outside_the_verdict(mpl) -> None:
    fig = MatchingHydrographicNetworkCard().plot(_two_bound_run(weights=(0.0, 1.0)))

    try:
        note = _texts(_panel(fig, "Validity"))
        assert "minimal (weight 0, outside the verdict): " in note
        assert "Doptim = 217.5 m <= 500 m, within the bound, no verdict" in note
        assert "maximal (weight 1): Doptim = 820 m > 500 m, Eq. 4 fails" in note
    finally:
        mpl.close(fig)


def test_an_applied_snap_breaks_the_verdict_of_its_own_bound_only(mpl) -> None:
    rows = _two_bound_rows()
    rows[COMBINED_TRIAL]["metrics"].update(
        {
            f"{OUTPUT}.snap_mode_minimal": 2.0,
            f"{OUTPUT}.snap_displacement_p90_m_minimal": 300.0,
            f"{OUTPUT}.snap_displacement_bound_m_minimal": 250.0,
            f"{OUTPUT}.snap_rejected_share_minimal": 0.02,
            f"{OUTPUT}.snap_rejected_share_max_minimal": 0.1,
        }
    )
    sessions = _sessions(staged=False)
    sessions.loc[0, "best_trial"] = COMBINED_TRIAL

    fig = MatchingHydrographicNetworkCard().plot(_run(rows, sessions))

    try:
        note = _texts(_panel(fig, "Validity"))
        assert "Doptim = 217.5 m <= 500 m, Eq. 4 fails" in note
        assert note.count("snapped map breaks Eq. 4") == 1
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# one state with both maps: the maximal map is a validation
# --------------------------------------------------------------------------- #


VALIDATION = {
    "Doptim": 640.0,
    "roptim": 2.56,
    "validity_length_m": 500.0,
    "validity_length_provenance": 0.0,
    "L_ref": 250.0,
    "n_valid": 210.0,
    "n_excess": 12.0,
    "n_missing": 95.0,
    "J_signed": -310.0,
}


def _with_validation() -> dict[str, float]:
    """The one-state set: the minimal map unsuffixed and ``_minimal``, the maximal validated."""
    return {
        **PUBLISHED,
        **{f"{key}_minimal": value for key, value in PUBLISHED.items()},
        **{f"{key}_maximal_validation": value for key, value in VALIDATION.items()},
    }


def test_a_validation_map_is_drawn_beside_the_scored_map(mpl) -> None:
    fig = MatchingHydrographicNetworkCard().plot(_staged_run(diagnostics=_with_validation()))

    try:
        # One bound in the cost: the root search reads as it always did.
        assert _line(_panel(fig, "Stage 1"), "K_over_R =").get_xdata()[0] == pytest.approx(
            CLOSED_VALUE
        )
        ax = _panel(fig, "Validity")
        assert _patch(ax, "Doptim minimal").get_width() == pytest.approx(217.5)
        assert _patch(ax, "Doptim maximal").get_width() == pytest.approx(640.0)
        note = _texts(ax)
        assert "minimal (in the cost): Doptim = 217.5 m <= 500 m, Eq. 4 holds" in note
        assert (
            "maximal (validation outside the cost): Doptim = 640 m > 500 m, "
            "beyond the bound, no verdict" in note
        )
        assert "J_signed = -310 m, roptim = 2.56" in note
        counts = _panel(fig, "Cells at the calibrated point")
        labels = {str(patch.get_label()) for patch in counts.patches}
        assert any(label.endswith("maximal (210 cells)") for label in labels)
        assert any(label.endswith("minimal (120 cells)") for label in labels)
    finally:
        mpl.close(fig)


def test_one_map_with_its_bound_suffix_reads_as_one_map(mpl) -> None:
    # A one-state output on the maximal map alone publishes its set twice,
    # unsuffixed and _maximal: that is one map, not two.
    published = {**PUBLISHED, **{f"{key}_maximal": value for key, value in PUBLISHED.items()}}

    fig = MatchingHydrographicNetworkCard().plot(_staged_run(diagnostics=published))

    try:
        ax = _panel(fig, "Validity")
        assert [str(patch.get_label()) for patch in ax.patches] == ["Doptim = 217.5 m"]
        assert "roptim = Doptim / h_obs = 0.87, h_obs = 250 m" in _texts(ax)
        counts = _panel(fig, "Cells at the calibrated point")
        assert len(counts.patches) == 3
        assert not any(patch.get_hatch() for patch in counts.patches)
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# the names the card spells by hand, held to their producers
# --------------------------------------------------------------------------- #


def test_the_suffixes_the_card_reads_are_the_ones_the_criterion_writes() -> None:
    from hydromodpy.calibration.metrics.downslope_network import (
        MAXIMAL_SUFFIX,
        MINIMAL_SUFFIX,
    )
    from hydromodpy.calibration.metrics.downslope_network import (
        VALIDATION_SUFFIX as CRITERION_VALIDATION_SUFFIX,
    )
    from hydromodpy.calibration.optim.adapters.bisection_adapter import ROOT_BOUNDS
    from hydromodpy.display.figures.matching_hydrographic_network_card import (
        BOUNDS,
        VALIDATION_SUFFIX,
    )

    assert BOUNDS == ROOT_BOUNDS
    assert tuple(f"_{bound}" for bound in BOUNDS) == (MINIMAL_SUFFIX, MAXIMAL_SUFFIX)
    assert VALIDATION_SUFFIX == CRITERION_VALIDATION_SUFFIX


def test_h_obs_is_read_under_the_key_the_run_verdict_reads() -> None:
    from hydromodpy.calibration.runners.cli_runner import _eq4_verdict
    from hydromodpy.display.figures.matching_hydrographic_network_card import H_OBS_KEY

    found = {
        f"{OUTPUT}.roptim_minimal": 0.87,
        f"{OUTPUT}.Doptim_minimal": 217.5,
        f"{OUTPUT}.validity_length_m_minimal": 500.0,
        f"{OUTPUT}.{H_OBS_KEY}_minimal": 250.0,
    }

    assert _eq4_verdict(OUTPUT, found, suffix="_minimal")["h_obs_m"] == 250.0
