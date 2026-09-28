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
