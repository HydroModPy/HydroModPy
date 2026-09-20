"""The residuals a width is taken from come from the scorer the search used.

A first-order width is read off the residual at each observation. Those
residuals used to be aligned by a second reader holding its own copy of the
records, the window and the minimum overlap; now they come from
``ObservableScorer.pair``, one step short of the cost. What this pins is that
the two cannot drift apart, and that a burn-in, which the cost applies and a
residual vector cannot, is refused instead of ignored.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.config import CalibObjectiveBlockDecl, validate_calib_output
from hydromodpy.calibration.metrics import composite
from hydromodpy.calibration.metrics.composite import (
    build_paired_vector_capture,
    refuse_a_burn_in_the_residuals_cannot_honour,
)
from hydromodpy.calibration.metrics.observable_scoring import (
    ObservableScorer,
    select_observable_times,
)
from hydromodpy.calibration.metrics.observed_pairing import (
    observed_series_for_outputs,
    pair_outputs_with_observations,
)
from hydromodpy.calibration.metrics.solver_extract import ExtractedOutputs
from hydromodpy.core.contracts.observables import ObservableResult
from hydromodpy.core.exceptions import UncertaintyNotAvailableError

_INDEX = pd.date_range("2020-01-01", periods=4, freq="D")


def _outputs():
    return {
        "gauge": validate_calib_output(
            {
                "variable": "discharge",
                "support": "boundary",
                "boundary_id": "outlet",
                "observes": "NANCON",
            }
        )
    }


def _block(**extra):
    return CalibObjectiveBlockDecl.model_validate(
        {"name": "b", "metric": "rmse", "uses_outputs": ["gauge"], **extra}
    )


def _ctx():
    frame = pd.DataFrame({"datetime": _INDEX, "value": [1.0, 2.0, 3.0, 4.0]})
    record = SimpleNamespace(station_id="NANCON", variable="discharge", data=frame)
    return SimpleNamespace(
        setup=SimpleNamespace(time_grid=None),
        loaded_data=SimpleNamespace(hydrometry=SimpleNamespace(points=[record])),
    )


def _answer(values):
    return ObservableResult(
        request_id="gauge",
        values=np.asarray(values, dtype=float),
        units="m3 s-1",
        times=_INDEX[: len(values)],
    )


def _extracted(values, *, time="all"):
    """What `extract_outputs` returns: the selection is already applied."""
    result = select_observable_times(_answer(values), time)
    return ExtractedOutputs(
        observables={"gauge": result},
        values={"gauge": [float(v) for v in result.values]},
        series={"gauge": pd.Series(result.values, index=result.times)},
        diagnostics={},
    )


class TestTheCaptureAndTheCostReadTheSamePairing:
    def test_the_captured_vectors_are_what_the_former_reader_produced(self, monkeypatch) -> None:
        """The reference is the reader this replaced, not the one that replaced it."""
        simulated = [1.5, 2.5, 3.5, 4.5]
        extracted = _extracted(simulated)
        monkeypatch.setattr(composite, "extract_outputs", lambda ctx, outputs: extracted)
        capture_fn, captured = build_paired_vector_capture(
            _outputs(), ctx=_ctx(), objective_blocks=[_block()]
        )

        capture_fn(None)

        # What HEAD did: load the records itself, and pair them on the dated
        # series `extract_outputs` had already built.
        former = pair_outputs_with_observations(
            observed=observed_series_for_outputs(_outputs(), _ctx()),
            simulated={"gauge": extracted.series["gauge"]},
            scoring_window=None,
            min_samples=1,
        )

        assert captured["order"] == ("gauge",)
        assert list(captured["simulated"]) == pytest.approx(former.simulated["gauge"])
        assert list(captured["observed"]) == pytest.approx(former.observed["gauge"])

    def test_a_selected_timestep_is_paired_the_way_it_always_was(self, monkeypatch) -> None:
        """`pair` re-selects the times `extract_outputs` had already selected."""
        outputs = {
            "gauge": validate_calib_output(
                {
                    "variable": "discharge",
                    "support": "boundary",
                    "boundary_id": "outlet",
                    "observes": "NANCON",
                    "time": "last",
                }
            )
        }
        extracted = _extracted([1.5, 2.5, 3.5, 4.5], time="last")
        monkeypatch.setattr(composite, "extract_outputs", lambda ctx, outputs_: extracted)
        capture_fn, captured = build_paired_vector_capture(
            outputs, ctx=_ctx(), objective_blocks=[_block()]
        )

        capture_fn(None)

        former = pair_outputs_with_observations(
            observed=observed_series_for_outputs(outputs, _ctx()),
            simulated={"gauge": extracted.series["gauge"]},
            scoring_window=None,
            min_samples=1,
        )
        assert list(captured["simulated"]) == pytest.approx(former.simulated["gauge"])
        assert list(captured["observed"]) == pytest.approx([4.0])

    def test_the_cost_and_the_residuals_pair_the_same_samples(self, monkeypatch) -> None:
        """One reader: what the search scored is what the derivatives are taken on."""
        simulated = [1.5, 2.5, 3.5, 4.5]
        monkeypatch.setattr(
            composite, "extract_outputs", lambda ctx, outputs: _extracted(simulated)
        )
        capture_fn, captured = build_paired_vector_capture(
            _outputs(), ctx=_ctx(), objective_blocks=[_block()]
        )
        capture_fn(None)

        scorer = ObservableScorer(
            _outputs(),
            [_block()],
            observed_records=observed_series_for_outputs(_outputs(), _ctx()),
        )
        _, components = scorer.score({"gauge": _answer(simulated)})

        assert components["gauge.n_paired"] == float(len(captured["simulated"]))
        assert components["b.n_values"] == float(len(captured["observed"]))

    def test_the_window_the_search_used_cuts_the_residuals_too(self, monkeypatch) -> None:
        monkeypatch.setattr(
            composite, "extract_outputs", lambda ctx, outputs: _extracted([1.5, 2.5, 3.5, 4.5])
        )
        capture_fn, captured = build_paired_vector_capture(
            _outputs(),
            ctx=_ctx(),
            objective_blocks=[_block()],
            scoring_window=(pd.Timestamp("2020-01-03"), None),
        )

        capture_fn(None)

        assert list(captured["observed"]) == pytest.approx([3.0, 4.0])

    def test_a_shorter_overlap_than_the_document_asks_for_is_refused(self, monkeypatch) -> None:
        monkeypatch.setattr(
            composite, "extract_outputs", lambda ctx, outputs: _extracted([1.5, 2.5])
        )
        capture_fn, _ = build_paired_vector_capture(
            _outputs(), ctx=_ctx(), objective_blocks=[_block()], min_samples=3
        )

        with pytest.raises(ValueError, match="min_samples"):
            capture_fn(None)


class TestTheScorerRefusesToPairWhatHasNoRecord:
    def test_a_scorer_with_no_observing_output_cannot_pair(self) -> None:
        typed = {
            "typed": validate_calib_output(
                {
                    "variable": "discharge",
                    "support": "boundary",
                    "boundary_id": "outlet",
                    "observed_values": [1.0, 2.0],
                }
            )
        }
        block = CalibObjectiveBlockDecl.model_validate(
            {"name": "b", "metric": "rmse", "uses_outputs": ["typed"]}
        )
        scorer = ObservableScorer(typed, [block])

        with pytest.raises(ValueError, match="no residual to align"):
            scorer.pair({"typed": _answer([1.0, 2.0])})


class TestABurnInHasNoResidualVector:
    def test_a_single_metric_document_hides_its_burn_in_in_no_block(self) -> None:
        """No block declares it, and the criterion drops the samples anyway."""
        with pytest.raises(UncertaintyNotAvailableError, match="warmup_periods drops the first 5"):
            build_paired_vector_capture(
                _outputs(), ctx=_ctx(), objective_blocks=[], warmup_periods=5
            )

    def test_a_block_naming_no_record_truncates_nothing_a_residual_reads(self) -> None:
        """The burn-in that matters is the one applied to the observing outputs."""
        outputs = dict(_outputs())
        outputs["typed"] = validate_calib_output(
            {
                "variable": "discharge",
                "support": "boundary",
                "boundary_id": "other",
                "observed_values": [1.0, 2.0],
            }
        )
        typed_only = CalibObjectiveBlockDecl.model_validate(
            {"name": "typed_only", "metric": "rmse", "uses_outputs": ["typed"]}
        )

        # Nothing scores `gauge`, so nothing drops its leading samples, whatever
        # the calibration-wide burn-in says.
        refuse_a_burn_in_the_residuals_cannot_honour(outputs, [typed_only], 3)

    def test_a_document_with_no_observing_output_is_left_to_its_sibling(self) -> None:
        typed = {
            "typed": validate_calib_output(
                {
                    "variable": "discharge",
                    "support": "boundary",
                    "boundary_id": "outlet",
                    "observed_values": [1.0, 2.0],
                }
            )
        }

        refuse_a_burn_in_the_residuals_cannot_honour(typed, [], 5)

    def test_a_block_that_scores_no_record_does_not_shield_the_burn_in(self) -> None:
        typed_block = CalibObjectiveBlockDecl.model_validate(
            {"name": "typed_only", "metric": "rmse", "uses_outputs": ["gauge"], "warmup": 0}
        )
        outputs = dict(_outputs())
        outputs["other"] = validate_calib_output(
            {
                "variable": "discharge",
                "support": "boundary",
                "boundary_id": "other",
                "observed_values": [1.0, 2.0],
            }
        )
        elsewhere = CalibObjectiveBlockDecl.model_validate(
            {"name": "elsewhere", "metric": "rmse", "uses_outputs": ["other"]}
        )

        # `typed_only` reads the record and switches the burn-in off, so nothing
        # truncates what a residual is taken from, whatever the other block does.
        refuse_a_burn_in_the_residuals_cannot_honour(outputs, [typed_block, elsewhere], 4)

    def test_a_calibration_wide_burn_in_is_refused(self) -> None:
        with pytest.raises(UncertaintyNotAvailableError, match="leading sample"):
            build_paired_vector_capture(
                _outputs(), ctx=_ctx(), objective_blocks=[_block()], warmup_periods=2
            )

    def test_a_block_that_switches_it_off_is_not_refused(self, monkeypatch) -> None:
        monkeypatch.setattr(
            composite, "extract_outputs", lambda ctx, outputs: _extracted([1.5, 2.5, 3.5, 4.5])
        )
        capture_fn, captured = build_paired_vector_capture(
            _outputs(),
            ctx=_ctx(),
            objective_blocks=[_block(warmup=0)],
            warmup_periods=2,
        )

        capture_fn(None)

        assert list(captured["observed"]) == pytest.approx([1.0, 2.0, 3.0, 4.0])

    def test_a_block_raising_its_own_burn_in_is_refused_and_named(self) -> None:
        with pytest.raises(UncertaintyNotAvailableError, match="b drops 3"):
            refuse_a_burn_in_the_residuals_cannot_honour(_outputs(), [_block(warmup=3)], 0)

    def test_a_burn_in_on_a_block_scoring_no_record_says_nothing(self) -> None:
        """Only the outputs a residual is taken against are concerned."""
        outputs = {
            "gauge": _outputs()["gauge"],
            "typed": validate_calib_output(
                {
                    "variable": "discharge",
                    "support": "boundary",
                    "boundary_id": "other",
                    "observed_values": [1.0, 2.0],
                }
            ),
        }
        typed_block = CalibObjectiveBlockDecl.model_validate(
            {"name": "typed_only", "metric": "rmse", "uses_outputs": ["typed"], "warmup": 1}
        )

        refuse_a_burn_in_the_residuals_cannot_honour(outputs, [typed_block, _block()], 0)
