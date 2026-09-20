"""The pipeline and a foreign model share composite scoring."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.config import CalibObjectiveBlockDecl, validate_calib_output
from hydromodpy.calibration.metrics import composite, solver_extract
from hydromodpy.calibration.metrics.observable_scoring import ObservableScorer
from hydromodpy.core.contracts.observables import (
    ObservableRequest,
    ObservableResult,
    select_time_indices,
)


def _wire_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    results: Mapping[str, ObservableResult],
    observed: Mapping[str, pd.Series] | None = None,
) -> None:
    class Adapter:
        def extract_observables(
            self,
            ctx: object,
            store: object,
            requests: Sequence[ObservableRequest],
            *,
            time_index: pd.DatetimeIndex | None = None,
        ) -> dict[str, ObservableResult]:
            served = {}
            for request in requests:
                result = results[request.id]
                selected = select_time_indices(result.values.size, request.times)
                served[request.id] = replace(
                    result,
                    values=result.values[selected],
                    times=result.times[selected] if result.times is not None else None,
                )
            return served

    monkeypatch.setattr(solver_extract, "resolve_flow_adapter", lambda ctx: (Adapter(), None))
    monkeypatch.setattr(solver_extract, "resolve_time_index", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        composite, "observed_series_for_outputs", lambda outputs, ctx: observed or {}
    )


def test_weighted_positional_outputs_keep_reduction_and_components(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outputs = {
        "q": validate_calib_output(
            dict(
                variable="discharge",
                support="boundary",
                boundary_id="outlet",
                observed_values=[1.0, 2.0],
            )
        ),
        "stage": validate_calib_output(
            dict(
                variable="stage",
                support="lake",
                lake_id="lake",
                reducer="mean",
                observed_values=[10.0],
            )
        ),
    }
    blocks = [
        CalibObjectiveBlockDecl(name="flow", metric="rmse", weight=1.0, uses_outputs=["q"]),
        CalibObjectiveBlockDecl(name="lake", metric="mae", weight=3.0, uses_outputs=["stage"]),
    ]
    results = {
        "q": ObservableResult("q", np.array([3.0, 4.0]), "m3/s"),
        "stage": ObservableResult("stage", np.array([13.0, 15.0]), "m"),
    }
    _wire_pipeline(monkeypatch, results)
    pipeline = composite.build_metric_extractor(
        None, None, object(), outputs=outputs, objective_blocks=blocks
    )
    foreign = ObservableScorer(outputs, blocks)

    total, components = foreign.score(results)

    assert total == pytest.approx(3.5)
    assert components["flow.raw_cost"] == pytest.approx(2.0)
    assert components["lake.raw_cost"] == pytest.approx(4.0)
    assert pipeline(object()) == (total, components)


def test_dates_window_then_warmup_are_identical_for_both_producers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    times = pd.date_range("2001-01-01", periods=4)
    outputs = {
        "q": validate_calib_output(
            dict(variable="discharge", support="boundary", boundary_id="outlet", observes="gauge")
        )
    }
    blocks = [CalibObjectiveBlockDecl(name="flow", metric="rmse", uses_outputs=["q"])]
    results = {"q": ObservableResult("q", np.array([101.0, 102.0, 6.0, 7.0]), "m3/s", times)}
    observed = {
        "q": pd.Series([1.0, 2.0, 3.0, 4.0, 999.0], index=pd.date_range("2001-01-01", periods=5))
    }
    options = dict(warmup_periods=1, scoring_window=(times[1], times[-1]), min_samples=3)
    _wire_pipeline(monkeypatch, results, observed)
    pipeline = composite.build_metric_extractor(
        None, None, object(), outputs=outputs, objective_blocks=blocks, **options
    )
    foreign = ObservableScorer(outputs, blocks, observed_records=observed, **options)

    total, components = foreign.score(results)

    assert total == pytest.approx(3.0)
    assert components["flow.n_values"] == 2.0
    assert components["q.n_paired"] == 3.0
    assert pipeline(object()) == (total, components)
    with pytest.raises(ValueError, match="fewer than the 4"):
        ObservableScorer(
            outputs, blocks, observed_records=observed, **{**options, "min_samples": 4}
        ).score(results)


def test_network_distances_and_diagnostics_do_not_masquerade_as_a_release_field() -> None:
    outputs = {
        "net": validate_calib_output(dict(support="network", observed_network="data.hydrography"))
    }
    blocks = [CalibObjectiveBlockDecl(name="network", metric="distance_gap", uses_outputs=["net"])]
    scorer = ObservableScorer(outputs, blocks)

    total, components = scorer.score(
        {}, network_values={"net": [12.0, 20.0]}, diagnostics={"net.roptim": 0.3}
    )

    assert total == pytest.approx(8.0)
    assert components["network.raw_cost"] == pytest.approx(8.0)
    assert components["net.roptim"] == pytest.approx(0.3)
    with pytest.raises(ValueError, match="prepared network distances"):
        scorer.score({"net": ObservableResult("net", np.array([12.0, 20.0]), "m3/s")})


def test_observed_output_without_dates_keeps_the_existing_refusal() -> None:
    outputs = {
        "q": validate_calib_output(
            dict(variable="discharge", support="boundary", boundary_id="outlet", observes="gauge")
        )
    }
    blocks = [CalibObjectiveBlockDecl(name="flow", metric="rmse", uses_outputs=["q"])]
    scorer = ObservableScorer(
        outputs,
        blocks,
        observed_records={"q": pd.Series([1.0], index=pd.date_range("2001-01-01", periods=1))},
    )
    with pytest.raises(ValueError, match="produced no series"):
        scorer.score({"q": ObservableResult("q", np.array([1.0]), "m3/s")})


@pytest.mark.parametrize(
    ("selector", "values", "count"),
    [
        ("first", [1.0, 102.0, 103.0], 1),
        ("last", [101.0, 102.0, 3.0], 1),
    ],
)
def test_time_selection_matches_a_solver_that_honors_requests(
    monkeypatch: pytest.MonkeyPatch, selector: str, values: list[float], count: int
) -> None:
    times = pd.date_range("2001-01-01", periods=3)
    outputs = {
        "q": validate_calib_output(
            dict(
                variable="discharge",
                support="boundary",
                boundary_id="outlet",
                observes="gauge",
                time=selector,
            )
        )
    }
    blocks = [CalibObjectiveBlockDecl(name="flow", metric="rmse", uses_outputs=["q"])]
    results = {"q": ObservableResult("q", np.asarray(values), "m3/s", times)}
    observed = {"q": pd.Series([1.0, 2.0, 3.0], index=times)}
    _wire_pipeline(monkeypatch, results, observed)
    pipeline = composite.build_metric_extractor(
        None,
        None,
        object(),
        outputs=outputs,
        objective_blocks=blocks,
    )
    foreign = ObservableScorer(outputs, blocks, observed_records=observed)

    total, components = foreign.score(results)

    assert total == pytest.approx(0.0)
    assert components["q.n_paired"] == count
    assert pipeline(object()) == (total, components)
