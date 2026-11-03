"""A pair dropped because the simulated value is NaN is counted beside the cost.

A dry cell leaves its simulated head NaN, and the pairing drops that period
from both series. The scored sample then depends on the parameters of the
trial, and nothing said so. The count of such pairs inside the window now
travels with the cost: in the components of the trial, so in its journal
line, and in ``scored`` of ``session.json``. A warning says it the
first time an output loses pairs that way. A period the record leaves empty is
not counted: it does not move with the parameters.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from hydromodpy.calibration.config import CalibObjectiveBlockDecl, validate_calib_output
from hydromodpy.calibration.metrics.observable_scoring import ObservableScorer
from hydromodpy.calibration.metrics.observed_pairing import pair_outputs_with_observations
from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.calibration.persistence import CalibrationPersistence
from hydromodpy.calibration.runners.recap import scored_samples
from hydromodpy.core.contracts.observables import ObservableResult
from hydromodpy.results.session.descriptor import read_session, scored_samples_text
from tests._helpers.session_documents import session_opening

_RECORD_DAYS = pd.date_range("1999-12-01", "2000-02-29", freq="D")
_RECORD = pd.Series(np.linspace(10.0, 12.0, len(_RECORD_DAYS)), index=_RECORD_DAYS).drop(
    pd.Timestamp("2000-01-25")
)
# Daily stamps, each closing the day before it.
_STAMPS = pd.date_range("2000-01-02", "2000-02-01", freq="D")
_BOUNDS = (pd.Timestamp("2000-01-01"), *_STAMPS)
# Three dry periods inside the window, one before it.
_DRY = pd.DatetimeIndex(["2000-01-03", "2000-01-11", "2000-01-16", "2000-01-21"])
_WINDOW = (pd.Timestamp("2000-01-05"), pd.Timestamp("2000-01-31"))


def _simulated() -> pd.Series:
    values = pd.Series(np.linspace(10.0, 11.0, len(_STAMPS)), index=_STAMPS)
    values[_DRY] = np.nan
    return values


def _scorer() -> ObservableScorer:
    outputs = {
        "H": validate_calib_output(
            {"variable": "head", "support": "cell", "row": 0, "col": 0, "layer": 0, "observes": "P"}
        )
    }
    blocks = [CalibObjectiveBlockDecl(name="fit", metric="rmse", uses_outputs=["H"])]
    return ObservableScorer(
        outputs, blocks, observed_records={"H": _RECORD}, scoring_window=_WINDOW
    )


def _answer() -> ObservableResult:
    simulated = _simulated()
    return ObservableResult(
        request_id="H", values=simulated.to_numpy(), units="m", times=simulated.index
    )


def test_the_pairing_counts_the_dry_periods_of_the_window() -> None:
    paired = pair_outputs_with_observations(
        observed={"H": _RECORD},
        simulated={"H": _simulated()},
        scoring_window=_WINDOW,
        time_methods={"H": "point"},
    )

    assert paired.n_simulated_nan == {"H": 3}


def test_the_count_is_a_component_of_the_cost_and_warned_once(caplog) -> None:
    scorer = _scorer()

    with caplog.at_level(logging.WARNING):
        _, first = scorer.score({"H": _answer()}, boundaries=_BOUNDS)
        _, second = scorer.score({"H": _answer()}, boundaries=_BOUNDS)

    assert first["H.n_sim_nan"] == 3.0
    assert second["H.n_sim_nan"] == 3.0
    warned = [r.getMessage() for r in caplog.records if "NaN" in r.getMessage()]
    assert len(warned) == 1 and "H" in warned[0] and "3" in warned[0]


def test_a_wet_trial_writes_zero() -> None:
    simulated = pd.Series(np.linspace(10.0, 11.0, len(_STAMPS)), index=_STAMPS)
    answer = ObservableResult(request_id="H", values=simulated.to_numpy(), units="m", times=_STAMPS)

    _, components = _scorer().score({"H": answer}, boundaries=_BOUNDS)

    assert components["H.n_sim_nan"] == 0.0


def test_the_journal_and_the_session_keep_the_count(tmp_path: Path) -> None:
    _, components = _scorer().score({"H": _answer()}, boundaries=_BOUNDS)
    persistence = CalibrationPersistence(tmp_path / "sessions" / "dry")
    persistence.start_session(**session_opening("dry", cost_name="rmse", bounds={}))
    line = persistence.append_iteration(
        ParamSuggestion(trial_id=1, values={"K": 1.0}),
        EvaluationResult(trial_id=1, sim_id=None, cost=1.0, components=components),
    )
    assert persistence.trials()[0].only_case.components["H.n_sim_nan"] == 3.0

    persistence.finalize_session(
        status="completed",
        best=None,
        scored=scored_samples(line.only_case.components, case_id="dry"),
    )

    samples = read_session(persistence.directory).scored
    assert samples[0].n_sim_nan == 3
    assert "3 lost to a NaN simulated value" in scored_samples_text(samples)
