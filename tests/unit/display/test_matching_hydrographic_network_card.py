"""One-page card of a two-stage downslope-distance calibration.

Stage 1 searches the ratio K/R (-) for a sign change of the signed distance gap
(m) and closes a bracket. Stage 2 fits the storage parameter on its own metric.
Two panels read the diagnostics of the returned trial, the validity of D_optim
against its bound (m) and the counts of valid, excess and missing cells. The
tests read panels, artists, annotations and refusals, never pixels.
"""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from hydromodpy.display.figures.matching_hydrographic_network_card import (
    MatchingHydrographicNetworkCard,
)
from hydromodpy.display.style import HIGH_CONTRAST_TRIPLET
from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.record.checks import CalibratedBy
from hydromodpy.results.run.view import Run
from hydromodpy.results.session.descriptor import ParameterBound
from hydromodpy.results.session.journal import append_trial
from hydromodpy.results.session.phase import PhaseDescriptor, write_phase
from hydromodpy.results.session.view import Session
from hydromodpy.results.storage.contract import (
    RUN_RESOLVED_CONFIG_FILENAME,
    SESSION_CONFIG_FILENAME,
)
from tests._helpers.sealed_runs import make_project, seal_run, sealed_search, write_session_dir
from tests._helpers.session_documents import trial_line

from ._calibration_journal import journal_session
from ._render_helpers import labelled_patch, rgba

OUTPUT = "net"
SESSION_ID = "s-cal"
ROOT_PHASE = "root_search"
STORAGE_PHASE = "storage"

# The sweep of the sibling bracket figure: it changes sign once, then two
# bisection steps close on [3.2e-05, 1e-04]. The end carrying the smaller
# residual is 3.2e-05, and that is the trial every diagnostic is read at.
ROOT_VALUES = [1e-5, 1e-3, 1e-4, 3.2e-5]
ROOT_RESIDUALS = [300.0, -400.0, -120.0, 40.0]
CLOSED_VALUE = 3.2e-5
BRACKET = (3.2e-5, 1e-4)
STORAGE_VALUES = [0.01, 0.05, 0.1]
STORAGE_OBJECTIVES = [0.42, 0.11, 0.30]

# A trial at h_obs = 250 m: D_optim = 0.87 h_obs, bounded by the auto 2 h_obs.
PUBLISHED = {
    "D_optim": 217.5,
    "r_optim": 0.87,
    "r_optim_valid": 1.0,
    "validity_length_m": 500.0,
    "validity_length_provenance": 0.0,
    "n_valid": 120.0,
    "n_excess": 30.0,
    "n_missing": 18.0,
    "h_obs": 250.0,
}


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
    session_id: str | None = SESSION_ID,
) -> list[dict]:
    """Stage one: the root search on the ratio, with its criterion diagnostics.

    Rows of a session name their phase; rows with no session name none.
    """
    published = dict(PUBLISHED)
    if diagnostics is not None:
        published = dict(diagnostics)
    rows = []
    for index, (value, residual) in enumerate(
        zip(values or ROOT_VALUES, residuals or ROOT_RESIDUALS, strict=True)
    ):
        components = {f"{OUTPUT}.{key}": number for key, number in published.items()}
        if residual is None:
            components = {}
        else:
            components[f"{OUTPUT}.J_signed"] = residual
        row = {
            "trial": index + 1,
            "parameters": {"K_over_R": {"value": value}},
            "components": components,
            "cost": abs(residual) if residual is not None else None,
            "status": "completed" if residual is not None else "failed",
        }
        if session_id is not None:
            row["session_id"] = session_id
            row["phase"] = ROOT_PHASE
        rows.append(row)
    return rows


def _storage_rows(
    *,
    objectives: list[float] | None = None,
    session_id: str = SESSION_ID,
    phase: str = STORAGE_PHASE,
    first: int = 5,
) -> list[dict]:
    """Stage two: the storage parameter against the objective of its phase."""
    return [
        {
            "trial": first + index,
            "session_id": session_id,
            "phase": phase,
            "parameters": {"specific_yield": {"value": value}},
            "components": {},
            "cost": objective,
            "status": "completed" if objective is not None else "failed",
        }
        for index, (value, objective) in enumerate(
            zip(STORAGE_VALUES, objectives or STORAGE_OBJECTIVES, strict=True)
        )
    ]


def _sessions(*, staged: bool = True) -> list[dict]:
    """The phases of the chain, in rank order, with the trial each one holds as its best."""
    phases = [{"phase_name": ROOT_PHASE, "best_trial": 4}]
    if staged:
        phases.append({"phase_name": STORAGE_PHASE, "best_trial": 6})
    return phases


def _run(
    project: Path,
    rows: list[dict],
    sessions: list[dict] | None,
    name: str = "cheze",
    *,
    best_trial: int | None = None,
    **kwargs,
) -> Session:
    """Write the session a staged calibration writes: its trials, phases and best trials."""
    first = (sessions or [{"phase_name": ROOT_PHASE}])[0]["phase_name"]
    rows = [{"phase": first, **row} for row in rows]
    return journal_session(
        project / uuid.uuid4().hex,
        rows,
        name=name,
        phases=None if sessions is None else [row["phase_name"] for row in sessions],
        phase_best={
            row["phase_name"]: row["best_trial"] for row in sessions or () if "best_trial" in row
        },
        named_phases=sessions is not None,
        best_trial=best_trial,
        **kwargs,
    )


def _staged_run(project: Path, **kwargs) -> Session:
    return _run(project, _root_rows(**kwargs) + _storage_rows(), _sessions())


def _single_phase_run(project: Path, **kwargs) -> Session:
    return _run(project, _root_rows(**kwargs), _sessions(staged=False))


def _panel(fig, prefix: str):
    return next(ax for ax in fig.axes if str(ax.get_title()).startswith(prefix))


def _texts(ax) -> str:
    return "\n".join(item.get_text() for item in ax.texts)


def _has_patch(ax, prefix: str) -> bool:
    return any(str(item.get_label()).startswith(prefix) for item in ax.patches)


def _line(ax, prefix: str):
    return next(item for item in ax.lines if str(item.get_label()).startswith(prefix))


def test_stage_one_value_and_bracket(mpl, tmp_path) -> None:
    fig = MatchingHydrographicNetworkCard().plot(_staged_run(tmp_path))

    ax = _panel(fig, "Stage 1")
    assert ax.get_xscale() == "log"
    assert ax.get_xlabel() == "K_over_R (-)"
    assert "root search" in ax.get_title()

    marker = _line(ax, "K_over_R =")
    assert marker.get_xdata()[0] == pytest.approx(CLOSED_VALUE)
    bracket = labelled_patch(ax, "bracket")
    assert bracket.get_x() == pytest.approx(BRACKET[0])
    assert bracket.get_x() + bracket.get_width() == pytest.approx(BRACKET[1])

    note = _texts(ax)
    assert f"{CLOSED_VALUE:.4g}" in note
    assert f"[{BRACKET[0]:.4g}, {BRACKET[1]:.4g}]" in note
    assert "factor 3.125" in note


def test_stage_one_without_sign_change(mpl, tmp_path) -> None:
    run = _staged_run(tmp_path, residuals=[300.0, 120.0, 80.0, 40.0])

    fig = MatchingHydrographicNetworkCard().plot(run)

    ax = _panel(fig, "Stage 1")
    assert "no sign change" in _texts(ax)
    assert not _has_patch(ax, "bracket")
    assert not [line for line in ax.lines if str(line.get_label()).startswith("K_over_R =")]


def test_no_root_no_diagnostics(mpl, tmp_path) -> None:
    # Reading the least-bad point as the answer would be a minimized mean
    # distance in disguise, so its r_optim and its counts are not the card's.
    run = _staged_run(tmp_path, residuals=[300.0, 120.0, 80.0, 40.0])

    fig = MatchingHydrographicNetworkCard().plot(run)

    assert "no root was closed" in _texts(_panel(fig, "Validity"))
    assert "no root was closed" in _texts(_panel(fig, "Cells at the calibrated point"))
    assert not _panel(fig, "Cells at the calibrated point").patches


def test_non_positive_ratio_refused(mpl, tmp_path) -> None:
    run = _staged_run(tmp_path, values=[0.0, 1e-3, 1e-4, 3.2e-5])

    with pytest.raises(ValueError, match="non-positive"):
        MatchingHydrographicNetworkCard().plot(run)


def test_stage_two_value_and_metric(mpl, tmp_path) -> None:
    fig = MatchingHydrographicNetworkCard().plot(_staged_run(tmp_path))

    ax = _panel(fig, "Stage 2")
    assert ax.get_xlabel() == "specific_yield (-)"
    assert ax.get_ylabel() == "cost, nse (-)"
    assert "storage" in ax.get_title()

    best = _line(ax, "specific_yield =")
    assert best.get_xdata()[0] == pytest.approx(0.05)
    note = _texts(ax)
    assert "specific_yield = 0.05" in note
    assert "cost (nse) = 0.11" in note


def test_single_phase_session(mpl, tmp_path) -> None:
    fig = MatchingHydrographicNetworkCard().plot(_single_phase_run(tmp_path))

    assert len(fig.axes) == 4
    ax = _panel(fig, "Stage 2")
    assert "not run" in ax.get_title()
    assert "not run" in _texts(ax)
    assert not ax.lines and not ax.collections
    # The first stage is untouched by the absence of the second.
    assert _line(_panel(fig, "Stage 1"), "K_over_R =").get_xdata()[0] == pytest.approx(CLOSED_VALUE)


def test_failed_storage_trial(mpl, tmp_path) -> None:
    run = _run(tmp_path, _root_rows() + _storage_rows(objectives=[0.42, 0.11, None]), _sessions())

    fig = MatchingHydrographicNetworkCard().plot(run)

    ax = _panel(fig, "Stage 2")
    drawn = _line(ax, "trial").get_ydata()
    assert len(drawn) == 3
    assert pd.isna(drawn[2]), "a failed trial keeps its abscissa and carries no objective"
    assert "1 of 3 trials failed" in _texts(ax)


# Each row is what a trial published, the bar and its bound, and what the note says.
VALIDITY = [
    pytest.param(
        PUBLISHED,
        217.5,
        0,
        500.0,
        (
            "D_optim = 217.5 m <= 500 m",
            "within the validity bound",
            "validity length: two cells, 2 h_obs",
            "r_optim = D_optim / h_obs = 0.87, h_obs = 250 m",
        ),
        id="within two cells",
    ),
    pytest.param(
        {
            **PUBLISHED,
            "D_optim": 2360.0,
            "r_optim": 9.44,
            "r_optim_valid": 0.0,
            "n_valid": 4.0,
            "n_excess": 210.0,
            "n_missing": 190.0,
        },
        2360.0,
        2,
        500.0,
        ("2360 m > 500 m", "breached"),
        id="breached, the value stands",
    ),
    pytest.param(
        # r_optim = 2.4 breaks the paper's r_optim <= 2, but a declared positional
        # accuracy of 400 m widened the trial's bound to 800 m. The trial is valid.
        {
            **PUBLISHED,
            "D_optim": 600.0,
            "r_optim": 2.4,
            "validity_length_m": 800.0,
            "validity_length_provenance": 2.0,
        },
        600.0,
        0,
        800.0,
        (
            "600 m <= 800 m: within the validity bound",
            "widened by the declared positional accuracy",
            "r_optim = D_optim / h_obs = 2.4",
        ),
        id="bound widened by the positional accuracy",
    ),
]


@pytest.mark.parametrize(("diagnostics", "width", "color", "bound", "fragments"), VALIDITY)
def test_validity_panel(mpl, tmp_path, diagnostics, width, color, bound, fragments) -> None:
    fig = MatchingHydrographicNetworkCard().plot(_staged_run(tmp_path, diagnostics=diagnostics))

    ax = _panel(fig, "Validity")
    assert ax.get_xlabel() == "D_optim = (D_so + D_os) / 2 (m)"
    bar = labelled_patch(ax, "D_optim")
    assert bar.get_width() == pytest.approx(width)
    assert bar.get_facecolor() == rgba(HIGH_CONTRAST_TRIPLET[color])
    assert _line(ax, "bound").get_xdata()[0] == pytest.approx(bound)
    for fragment in fragments:
        assert fragment in _texts(ax)
    # The calibrated value is never withheld, so stage one reads as before.
    assert _line(_panel(fig, "Stage 1"), "K_over_R =").get_xdata()[0] == pytest.approx(CLOSED_VALUE)


def test_unpublished_validity_length(mpl, tmp_path) -> None:
    published = {key: value for key, value in PUBLISHED.items() if key != "validity_length_m"}

    fig = MatchingHydrographicNetworkCard().plot(_staged_run(tmp_path, diagnostics=published))

    ax = _panel(fig, "Validity")
    assert not ax.patches
    assert "validity length not published" in _texts(ax)


def test_absent_count_has_no_bar(mpl, tmp_path) -> None:
    run = _staged_run(
        tmp_path,
        diagnostics={"r_optim": 0.87, "r_optim_valid": 1.0, "n_valid": 120.0, "n_missing": 18.0},
    )

    fig = MatchingHydrographicNetworkCard().plot(run)

    ax = _panel(fig, "Cells at the calibrated point")
    drawn = {str(patch.get_label()).split(":")[0] for patch in ax.patches}
    assert drawn == {"valid", "missing"}
    assert "excess" in _texts(ax)
    assert "not published" in _texts(ax)


def test_recharge_read_from_trials(mpl, tmp_path) -> None:
    # The trial publishes what the criterion publishes, under the name the
    # criterion gives it, prefixed by the output the way a scored output is.
    published = {**PUBLISHED, **_criterion_diagnostics(4.5e-8)}
    assert 4.5e-8 in published.values()

    fig = MatchingHydrographicNetworkCard().plot(_staged_run(tmp_path, diagnostics=published))

    assert "4.5e-08" in _texts(_panel(fig, "Stage 1"))


def test_trials_without_session_table(mpl, tmp_path) -> None:
    run = _run(tmp_path, _root_rows(session_id=None), None)

    fig = MatchingHydrographicNetworkCard().plot(run)

    assert _line(_panel(fig, "Stage 1"), "K_over_R =").get_xdata()[0] == pytest.approx(CLOSED_VALUE)
    assert "not run" in _panel(fig, "Stage 2").get_title()


def test_session_without_trial(tmp_path) -> None:
    barren = journal_session(tmp_path, [], name="plain")

    reason = MatchingHydrographicNetworkCard().unavailable_reason(barren)

    assert reason is not None
    assert "no trial recorded" in reason
    assert MatchingHydrographicNetworkCard.spec.subject == "session"


# The sweep closes K*_minimal on [3.2e-05, 1e-04] at 3.2e-05 and K*_maximal on
# [3.2e-04, 1e-03] at 3.2e-04. The last trial is the solve at the combined
# value, their geometric mean weighted 0.5 / 0.5: the trial the search
# returns, where the run reads Eq. 4 on each bound.
TWO_VALUES = [1e-5, 1e-4, 1e-3, 3.2e-5, 3.2e-4, 1.0119e-4]
TWO_RESIDUALS = {
    "minimal": [200.0, -50.0, -300.0, 30.0, -120.0, -45.0],
    "maximal": [400.0, 150.0, -80.0, 250.0, 20.0, 140.0],
}
COMBINED_INDEX = 5
COMBINED_TRIAL = COMBINED_INDEX + 1
AT_THE_RETURNED_TRIAL = {
    "minimal": {
        "D_optim": 217.5,
        "r_optim": 0.87,
        "validity_length_m": 500.0,
        "validity_length_provenance": 0.0,
        "h_obs": 250.0,
        "n_valid": 120.0,
        "n_excess": 30.0,
        "n_missing": 18.0,
    },
    "maximal": {
        "D_optim": 820.0,
        "r_optim": 3.28,
        "validity_length_m": 500.0,
        "validity_length_provenance": 0.0,
        "h_obs": 250.0,
        "n_valid": 300.0,
        "n_excess": 90.0,
        "n_missing": 60.0,
    },
}
ROOTS = {
    "parameter": "K_over_R",
    "minimal": {
        "k_star": 3.2e-5,
        "trial_id": 4,
        "residual": 30.0,
        "weight": 0.5,
        "low": 3.2e-5,
        "high": 1e-4,
        "closed": True,
    },
    "maximal": {
        "k_star": 3.2e-4,
        "trial_id": 5,
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


def _two_bound_rows(*, weights: tuple[float, float] = (0.5, 0.5)) -> list[dict]:
    rows = []
    for index, value in enumerate(TWO_VALUES):
        components = {f"{OUTPUT}.n_bounds_scored": 2.0, f"{OUTPUT}.R_mean_m_s": 3.0e-8}
        for bound, weight in zip(("minimal", "maximal"), weights, strict=True):
            components[f"{OUTPUT}.J_signed_{bound}"] = TWO_RESIDUALS[bound][index]
            components[f"{OUTPUT}.weight_{bound}"] = weight
            for key, number in AT_THE_RETURNED_TRIAL[bound].items():
                published = number if index == COMBINED_INDEX else 999.0
                components[f"{OUTPUT}.{key}_{bound}"] = published
        rows.append(
            {
                "trial": index + 1,
                "session_id": SESSION_ID,
                "parameters": {"K_over_R": {"value": value}},
                "components": components,
                "cost": 1.0,
                "status": "completed",
            }
        )
    return rows


def _two_bound_run(project: Path, *, best_trial: int | None = COMBINED_TRIAL, **kwargs) -> Session:
    sessions = [{"phase_name": ROOT_PHASE, "best_trial": best_trial}]
    return _run(project, _two_bound_rows(**kwargs), sessions, best_trial=best_trial)


def test_two_bounds_brackets(mpl, tmp_path) -> None:
    fig = MatchingHydrographicNetworkCard().plot(_two_bound_run(tmp_path))

    ax = _panel(fig, "Stage 1")
    assert "two bounds" in ax.get_title()
    minimal = labelled_patch(ax, "bracket minimal")
    assert minimal.get_x() == pytest.approx(3.2e-5)
    assert minimal.get_x() + minimal.get_width() == pytest.approx(1e-4)
    maximal = labelled_patch(ax, "bracket maximal")
    assert maximal.get_x() == pytest.approx(3.2e-4)
    assert maximal.get_x() + maximal.get_width() == pytest.approx(1e-3)
    assert _line(ax, "K*_minimal").get_xdata()[0] == pytest.approx(3.2e-5)
    assert _line(ax, "K*_maximal").get_xdata()[0] == pytest.approx(3.2e-4)
    note = _texts(ax)
    assert "roots record not passed" in note
    assert "diagnostics read at the returned trial, K_over_R = 0.0001012" in note
    assert "3e-08 m/s" in note


def test_two_bounds_roots_record(mpl, tmp_path) -> None:
    fig = MatchingHydrographicNetworkCard().plot(_two_bound_run(tmp_path), roots=ROOTS)

    ax = _panel(fig, "Stage 1")
    note = _texts(ax)
    assert "K*_minimal = 3.2e-05, bracket [3.2e-05, 0.0001]" in note
    assert "K*_maximal = 0.00032, bracket [0.00032, 0.001]" in note
    assert "Delta = log10(K*_maximal / K*_minimal) = 1 decade(s)" in note
    assert "combined K_over_R = 0.0001012, weighted geometric mean 0.5 / 0.5" in note
    assert _line(ax, "K_over_R =").get_xdata()[0] == pytest.approx(1.0119e-4)
    assert "roots record not passed" not in note


def test_unsolved_combined_value(mpl, tmp_path) -> None:
    roots = {**ROOTS, "value": None, "combined_trial_id": None, "closed": False}

    fig = MatchingHydrographicNetworkCard().plot(_two_bound_run(tmp_path), roots=roots)

    ax = _panel(fig, "Stage 1")
    assert "combined value not solved" in _texts(ax)
    assert not [line for line in ax.lines if str(line.get_label()).startswith("K_over_R =")]
    # The session's best trial still says where the run read Eq. 4.
    assert labelled_patch(_panel(fig, "Validity"), "D_optim minimal").get_width() == pytest.approx(
        217.5
    )


def test_two_bounds_validity(mpl, tmp_path) -> None:
    fig = MatchingHydrographicNetworkCard().plot(_two_bound_run(tmp_path))

    ax = _panel(fig, "Validity")
    assert [tick.get_text() for tick in ax.get_yticklabels()] == ["minimal", "maximal"]
    minimal = labelled_patch(ax, "D_optim minimal")
    maximal = labelled_patch(ax, "D_optim maximal")
    assert minimal.get_width() == pytest.approx(217.5)
    assert maximal.get_width() == pytest.approx(820.0)
    assert minimal.get_facecolor() == rgba(HIGH_CONTRAST_TRIPLET[0])
    assert maximal.get_facecolor() == rgba(HIGH_CONTRAST_TRIPLET[2])
    assert _line(ax, "bound minimal").get_xdata()[0] == pytest.approx(500.0)
    assert _line(ax, "bound maximal").get_xdata()[0] == pytest.approx(500.0)
    note = _texts(ax)
    assert "minimal (weight 0.5): D_optim = 217.5 m <= 500 m, Eq. 4 holds" in note
    assert "maximal (weight 0.5): D_optim = 820 m > 500 m, Eq. 4 fails" in note
    assert "J_signed = -45 m, r_optim = 0.87, h_obs = 250 m, length: two cells, 2 h_obs" in note
    assert "J_signed = 140 m, r_optim = 3.28, h_obs = 250 m" in note
    assert "not published" not in note
    assert "999" not in note


def test_combined_trial_beats_best(mpl, tmp_path) -> None:
    fig = MatchingHydrographicNetworkCard().plot(
        _two_bound_run(tmp_path, best_trial=1), roots=ROOTS
    )

    validity = _panel(fig, "Validity")
    assert labelled_patch(validity, "D_optim minimal").get_width() == pytest.approx(217.5)


def test_roots_read_from_journal(mpl, tmp_path) -> None:
    # The auto-render of [display].figures passes no roots record, and the
    # index keeps no best trial: the card read "roots record not passed" and
    # left both lower panels empty. The session journal holds both.
    run = journal_session(
        tmp_path,
        _two_bound_rows(),
        method="bisection",
        phase="transient_conductivity",
        config={"parameters": {"K_over_R": {"units": "-"}}},
        bounds={"K_over_R": ParameterBound(lower=1e-6, upper=1e-2, search_space="identity")},
        best_trial=COMBINED_TRIAL,
        root_search={"roots": ROOTS},
    )

    fig = MatchingHydrographicNetworkCard().plot(run)

    note = _texts(_panel(fig, "Stage 1"))
    assert "roots record not passed" not in note
    assert "Delta = log10(K*_maximal / K*_minimal) = 1 decade(s)" in note
    assert "combined K_over_R = 0.0001012, weighted geometric mean 0.5 / 0.5" in note
    validity = _panel(fig, "Validity")
    assert labelled_patch(validity, "D_optim minimal").get_width() == pytest.approx(217.5)
    assert labelled_patch(validity, "D_optim maximal").get_width() == pytest.approx(820.0)
    counts = _panel(fig, "Cells at the calibrated point")
    assert counts.patches
    assert "the returned trial is not known" not in _texts(counts)


@pytest.mark.parametrize(
    ("config", "bound_units", "expected"),
    [
        ({}, "m/s", "K_over_R (m/s)"),
        ({"parameters": {"K_over_R": {"units": "-"}}}, "m/s", "K_over_R (m/s)"),
        ({"parameters": {"K_over_R": {"units": "m/d"}}}, None, "K_over_R (m/d)"),
        ({}, None, "K_over_R (-)"),
    ],
    ids=["journal-only", "journal-wins", "config-fallback", "undeclared"],
)
def test_axis_unit(mpl, tmp_path, config, bound_units, expected) -> None:
    run = journal_session(
        tmp_path,
        _two_bound_rows(),
        method="bisection",
        phase="transient_conductivity",
        config=config,
        bounds={
            "K_over_R": ParameterBound(
                lower=1e-6, upper=1e-2, search_space="identity", units=bound_units
            )
        },
        best_trial=COMBINED_TRIAL,
        root_search={"roots": ROOTS},
    )

    fig = MatchingHydrographicNetworkCard().plot(run)

    assert _panel(fig, "Stage 1").get_xlabel() == expected


def test_two_bounds_without_returned_trial(mpl, tmp_path) -> None:
    fig = MatchingHydrographicNetworkCard().plot(_two_bound_run(tmp_path, best_trial=None))

    for title in ("Validity", "Cells at the calibrated point"):
        ax = _panel(fig, title)
        assert "the returned trial is not known" in _texts(ax)
        assert not ax.patches
    # The brackets are still proven by the trials.
    assert _has_patch(_panel(fig, "Stage 1"), "bracket minimal")


VALIDATION = {
    "D_optim": 640.0,
    "r_optim": 2.56,
    "validity_length_m": 500.0,
    "validity_length_provenance": 0.0,
    "h_obs": 250.0,
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


def test_maximal_validation_map(mpl, tmp_path) -> None:
    fig = MatchingHydrographicNetworkCard().plot(
        _staged_run(tmp_path, diagnostics=_with_validation())
    )

    # One bound in the cost: the root search reads as it always did.
    assert _line(_panel(fig, "Stage 1"), "K_over_R =").get_xdata()[0] == pytest.approx(CLOSED_VALUE)
    ax = _panel(fig, "Validity")
    assert labelled_patch(ax, "D_optim minimal").get_width() == pytest.approx(217.5)
    assert labelled_patch(ax, "D_optim maximal").get_width() == pytest.approx(640.0)
    note = _texts(ax)
    assert "minimal (in the cost): D_optim = 217.5 m <= 500 m, Eq. 4 holds" in note
    assert (
        "maximal (validation outside the cost): D_optim = 640 m > 500 m, "
        "beyond the bound, no verdict" in note
    )
    assert "J_signed = -310 m, r_optim = 2.56" in note
    counts = _panel(fig, "Cells at the calibrated point")
    labels = {str(patch.get_label()) for patch in counts.patches}
    assert any(label.endswith("maximal (210 cells)") for label in labels)
    assert any(label.endswith("minimal (120 cells)") for label in labels)


def test_minimal_validation_map(mpl, tmp_path) -> None:
    diagnostics = {
        **PUBLISHED,
        **{f"{key}_maximal": value for key, value in PUBLISHED.items()},
        **{f"{key}_minimal_validation": value for key, value in VALIDATION.items()},
    }
    fig = MatchingHydrographicNetworkCard().plot(_staged_run(tmp_path, diagnostics=diagnostics))

    ax = _panel(fig, "Validity")
    assert labelled_patch(ax, "D_optim maximal").get_width() == pytest.approx(217.5)
    assert labelled_patch(ax, "D_optim minimal").get_width() == pytest.approx(640.0)
    note = _texts(ax)
    assert "maximal (in the cost): D_optim = 217.5 m <= 500 m, Eq. 4 holds" in note
    assert (
        "minimal (validation outside the cost): D_optim = 640 m > 500 m, "
        "beyond the bound, no verdict" in note
    )


def test_suffixes_match_the_criterion() -> None:
    from hydromodpy.calibration.optim.adapters.bisection_adapter import ROOT_BOUNDS
    from hydromodpy.catchment.stream_network.cost import MAXIMAL_SUFFIX, MINIMAL_SUFFIX
    from hydromodpy.catchment.stream_network.cost import (
        VALIDATION_SUFFIX as CRITERION_VALIDATION_SUFFIX,
    )
    from hydromodpy.display.figures.matching_hydrographic_network_card import (
        BOUNDS,
        VALIDATION_SUFFIX,
    )

    assert BOUNDS == ROOT_BOUNDS
    assert tuple(f"_{bound}" for bound in BOUNDS) == (MINIMAL_SUFFIX, MAXIMAL_SUFFIX)
    assert VALIDATION_SUFFIX == CRITERION_VALIDATION_SUFFIX


# A promoted run names its session, phase and trial in its seal. The session
# journals the trials of every phase in ``sessions/<case>/trials.jsonl``. The
# run promoted from the second phase of a protocol used to draw "Stage 1 -
# transient_storage / Stage 2 - not run" and three empty panels. It reads the
# first phase from the same journal and draws stage 1 with its bracket and
# validity. The run promoted from the first phase, drawn before the second one
# starts, names the second phase as the one that comes next.

SESSION = uuid.uuid4().hex
CASE = "nancon"
STEADY, STORAGE = "steady_conductivity", "transient_storage"
STARTED = datetime(2026, 9, 28, tzinfo=UTC)
# The session config freezes both phases, each with the metric it scores on,
# and the units of every parameter it moves.
SESSION_CONFIG = """\
[calibration.parameters.K_over_R]
units = "m/s"

[calibration.parameters.specific_yield]
units = "-"

[[calibration.phases]]
name = "steady_conductivity"
objective_blocks = [{ name = "steady_conductivity", metric = "distance_gap" }]

[[calibration.phases]]
name = "transient_storage"
objective_blocks = [{ name = "transient_storage", metric = "nse_log" }]
"""
SEARCH = {"phases": [{"name": STEADY}, {"name": STORAGE}]}


def _phase(project: Path, name: str, index: int) -> None:
    write_phase(
        project / "sessions" / CASE,
        PhaseDescriptor(
            phase_id=f"{SESSION[:8]}-{index}",
            name=name,
            index=index,
            status="completed",
            frozen={},
            restarts=0,
        ),
    )


def _trials(project: Path, phase: str, rows: list[dict], *, first: int) -> list[int]:
    """Journal *rows* as trials of *phase*, numbered from *first*; return the numbers."""
    numbers = []
    for offset, row in enumerate(rows):
        number = first + offset
        append_trial(
            project / "sessions" / CASE,
            trial_line(
                number,
                cost=row["cost"],
                case=CASE,
                phase=phase,
                status="completed" if row["status"] == "completed" else "crashed",
                params={name: entry["value"] for name, entry in row["parameters"].items()},
                components=row["components"],
                started_at=STARTED,
                ended_at=STARTED,
            ),
        )
        numbers.append(number)
    return numbers


def _promoted_run(project: Path, name: str, *, phase: str, trial: int) -> str:
    """Seal the run promoted from *trial* of *phase*, with the search it came out of."""
    sim_id = seal_run(
        project,
        name,
        project="p",
        calibrated_by=CalibratedBy(
            session_id=SESSION, phase=phase, trial=trial, session_status="completed"
        ),
    )
    shutil.copy(
        sealed_search(SEARCH) / RUN_RESOLVED_CONFIG_FILENAME,
        project / "runs" / name / RUN_RESOLVED_CONFIG_FILENAME,
    )
    return sim_id


def _open(project: Path, sim_id: str) -> tuple[Catalog, Run]:
    rebuild_index(project)
    catalog = Catalog(project)
    return catalog, Run(sim_id, catalog)


@pytest.fixture
def chain(tmp_path: Path) -> tuple[Path, str]:
    """A session whose first phase promoted a run; the second phase not yet run."""
    project = make_project(tmp_path / "p")
    write_session_dir(project, CASE, session_id=SESSION, trials=0, phases=(), status="completed")
    (project / "sessions" / CASE / SESSION_CONFIG_FILENAME).write_text(
        SESSION_CONFIG, encoding="utf-8"
    )
    _phase(project, STEADY, 0)
    numbers = _trials(project, STEADY, _root_rows(session_id=None), first=1)
    # The closed end of the bracket is the fourth trial, the promoted one.
    steady_run = _promoted_run(
        project, "nancon_steady_conductivity", phase=STEADY, trial=numbers[3]
    )
    return project, steady_run


def test_second_phase_run_draws_stage_one(chain, mpl) -> None:
    project, _ = chain
    _phase(project, STORAGE, 1)
    numbers = _trials(project, STORAGE, _storage_rows(session_id=SESSION), first=5)
    storage_run = _promoted_run(
        project, "nancon_transient_storage", phase=STORAGE, trial=numbers[1]
    )
    catalog, run = _open(project, storage_run)

    fig = MatchingHydrographicNetworkCard().plot(Session.of_run(run), promoted=run)

    try:
        stage_one = _panel(fig, "Stage 1")
        assert stage_one.get_title() == "Stage 1 - steady conductivity"
        assert stage_one.get_xlabel() == "K_over_R (m/s)"
        assert "closed on K_over_R = 3.2e-05" in _texts(stage_one)
        stage_two = _panel(fig, "Stage 2")
        assert stage_two.get_title() == "Stage 2 - transient storage"
        assert stage_two.get_ylabel() == "cost, nse_log (-)"
        validity = _panel(fig, "Validity of the agreement")
        assert validity.patches, "the validity of stage 1 is drawn, not left empty"
    finally:
        mpl.close(fig)
        catalog.close()


def test_first_phase_run_names_next_stage(chain, mpl) -> None:
    project, steady_run = chain
    catalog, run = _open(project, steady_run)

    fig = MatchingHydrographicNetworkCard().plot(Session.of_run(run), promoted=run)

    try:
        assert _panel(fig, "Stage 1").get_title() == "Stage 1 - steady conductivity"
        stage_two = _panel(fig, "Stage 2")
        assert stage_two.get_title() == "Stage 2 - transient storage"
        assert "comes next" in _texts(stage_two)
        assert "not run" not in _texts(stage_two)
    finally:
        mpl.close(fig)
        catalog.close()
