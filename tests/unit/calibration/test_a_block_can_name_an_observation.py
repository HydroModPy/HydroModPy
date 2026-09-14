"""A weighted block had no way to score a real observed record.

Two routes to a cost coexisted and excluded each other. ``variable`` +
``objective`` aligns genuine chronicles on their dates, but averages the
stations it scores and cannot weight them. ``outputs`` +
``objective_blocks`` weights, normalises and persists the per-block
diagnostics, but read only ``observed_values``: a vector typed into the TOML
by hand, positional, with no dates. So "the outlet carries 65 % of the cost,
the piezometer 25 %, the lake 10 %" was expressible only against numbers
somebody had transcribed.

``observes`` is the bridge: the output names a station, the loaded record is
aligned on the simulated timestamps, and the block scores that.
"""

from __future__ import annotations

import pandas as pd
import pytest

from hydromodpy.calibration.config import CalibrationConfig, validate_calib_output
from hydromodpy.calibration.metrics.observed_pairing import (
    observed_series_for_outputs,
    pair_outputs_with_observations,
)


class TestTheDeclaration:
    def test_an_output_may_name_a_station(self) -> None:
        output = validate_calib_output(
            {
                "variable": "discharge",
                "support": "boundary",
                "boundary_id": "outlet",
                "observes": "J7branch",
            }
        )

        assert output.observes == "J7branch"

    def test_naming_a_station_and_typing_the_values_is_refused(self) -> None:
        """Two answers to one question; picking one silently would hide it."""
        with pytest.raises(ValueError, match="observes"):
            validate_calib_output(
                {
                    "variable": "discharge",
                    "support": "boundary",
                    "boundary_id": "outlet",
                    "observes": "J7branch",
                    "observed_values": [1.0, 2.0],
                }
            )

    def test_a_network_output_cannot_observe_a_station(self) -> None:
        """Its criterion balances two simulated quantities; there is no record to fit."""
        with pytest.raises(ValueError):
            validate_calib_output(
                {
                    "support": "network",
                    "stream_geometry_path": "streams.gpkg",
                    "observes": "J7branch",
                }
            )

    def test_a_config_declaring_it_loads(self) -> None:
        cfg = CalibrationConfig.model_validate(
            {
                "parameters": {"K": {"bounds": [1e-8, 1e-2]}},
                "outputs": {
                    "outlet": {
                        "variable": "discharge",
                        "support": "boundary",
                        "boundary_id": "outlet",
                        "observes": "J7branch",
                    }
                },
                "objective_blocks": [
                    {"name": "hydrograph", "metric": "nse_log", "uses_outputs": ["outlet"]}
                ],
            }
        )

        assert cfg.outputs["outlet"].observes == "J7branch"


class _Point:
    def __init__(self, station_id: str, variable: str, frame: pd.DataFrame) -> None:
        self.station_id = station_id
        self.variable = variable
        self.data = frame


class _Loaded:
    def __init__(self, **families: object) -> None:
        for name, value in families.items():
            setattr(self, name, value)


class _Family:
    def __init__(self, points: list[_Point]) -> None:
        self.points = points


class _Ctx:
    def __init__(self, loaded_data: _Loaded) -> None:
        self.loaded_data = loaded_data


def _frame(dates: list[str], values: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"datetime": pd.to_datetime(dates), "value": values})


def _ctx() -> _Ctx:
    return _Ctx(
        _Loaded(
            hydrometry=_Family(
                [_Point("J7branch", "discharge", _frame(["2000-01-01", "2000-01-02"], [1.0, 2.0]))]
            ),
            piezometry=_Family(
                [_Point("P1", "head", _frame(["2000-01-01", "2000-01-02"], [40.0, 41.0]))]
            ),
        )
    )


_OUTLET = validate_calib_output(
    {
        "variable": "discharge",
        "support": "boundary",
        "boundary_id": "outlet",
        "observes": "J7branch",
    }
)
_PIEZO = validate_calib_output(
    {"variable": "head", "support": "point", "x": 1.0, "y": 2.0, "observes": "P1"}
)
_TYPED = validate_calib_output(
    {"variable": "head", "support": "point", "x": 1.0, "y": 2.0, "observed_values": [1.0]}
)


class TestLoadingTheRecords:
    def test_it_reads_the_family_the_variable_names(self) -> None:
        loaded = observed_series_for_outputs({"outlet": _OUTLET, "piezo": _PIEZO}, _ctx())

        assert set(loaded) == {"outlet", "piezo"}
        assert list(loaded["outlet"]) == [1.0, 2.0]
        assert list(loaded["piezo"]) == [40.0, 41.0]

    def test_an_output_that_names_nothing_is_left_out(self) -> None:
        assert observed_series_for_outputs({"typed": _TYPED}, _ctx()) == {}

    def test_a_station_the_project_never_loaded_is_named_in_the_refusal(self) -> None:
        missing = validate_calib_output(
            {
                "variable": "discharge",
                "support": "boundary",
                "boundary_id": "outlet",
                "observes": "nowhere",
            }
        )

        with pytest.raises(ValueError, match="nowhere"):
            observed_series_for_outputs({"outlet": missing}, _ctx())


class TestPairing:
    def test_the_record_is_aligned_on_the_simulated_timestamps(self) -> None:
        times = pd.DatetimeIndex(["2000-01-01", "2000-01-02"])
        paired = pair_outputs_with_observations(
            observed={"outlet": pd.Series([1.0, 2.0], index=times)},
            simulated={"outlet": pd.Series([1.1, 2.2], index=times)},
        )

        assert paired.observed["outlet"] == [1.0, 2.0]
        assert paired.simulated["outlet"] == [1.1, 2.2]

    def test_a_simulated_step_the_record_does_not_cover_is_dropped_from_both(self) -> None:
        """The shared aligner matches within one simulated step; beyond it, nothing."""
        paired = pair_outputs_with_observations(
            observed={
                "outlet": pd.Series(
                    [1.0, 2.0, 3.0],
                    index=pd.DatetimeIndex(["2000-01-01", "2000-01-02", "2000-01-03"]),
                )
            },
            simulated={
                "outlet": pd.Series(
                    [1.1, 2.2, 3.3, 4.4, 5.5],
                    index=pd.date_range("2000-01-01", periods=5, freq="D"),
                )
            },
        )

        # 2000-01-05 sits two steps past the end of the record and carries no pair.
        assert paired.n_paired["outlet"] == 4
        assert paired.simulated["outlet"][-1] == 4.4

    def test_a_window_keeps_only_the_dates_inside_it(self) -> None:
        times = pd.DatetimeIndex(["2000-01-01", "2000-01-02", "2000-01-03"])
        paired = pair_outputs_with_observations(
            observed={"outlet": pd.Series([1.0, 2.0, 3.0], index=times)},
            simulated={"outlet": pd.Series([1.1, 2.2, 3.3], index=times)},
            scoring_window=(pd.Timestamp("2000-01-02"), pd.Timestamp("2000-01-03")),
        )

        assert paired.observed["outlet"] == [2.0, 3.0]

    def test_a_pair_with_nothing_in_common_is_refused_by_name(self) -> None:
        with pytest.raises(ValueError, match="outlet"):
            pair_outputs_with_observations(
                observed={"outlet": pd.Series([1.0], index=pd.DatetimeIndex(["1990-01-01"]))},
                simulated={"outlet": pd.Series([1.1], index=pd.DatetimeIndex(["2020-01-01"]))},
            )

    def test_a_simulated_output_with_no_timestamps_is_refused_by_name(self) -> None:
        with pytest.raises(ValueError, match="outlet"):
            pair_outputs_with_observations(
                observed={"outlet": pd.Series([1.0], index=pd.DatetimeIndex(["2000-01-01"]))},
                simulated={"outlet": pd.Series([1.1])},
            )


class TestTheExtractor:
    """The weighted route, end to end, against records rather than typed vectors."""

    @staticmethod
    def _outputs() -> dict[str, object]:
        return {
            "outlet": validate_calib_output(
                {
                    "variable": "discharge",
                    "support": "boundary",
                    "boundary_id": "outlet",
                    "observes": "J7branch",
                }
            ),
            "piezo": validate_calib_output(
                {"variable": "head", "support": "point", "x": 1.0, "y": 2.0, "observes": "P1"}
            ),
        }

    @staticmethod
    def _blocks() -> list[object]:
        from hydromodpy.calibration.config import CalibObjectiveBlockDecl

        return [
            CalibObjectiveBlockDecl(
                name="hydrograph", metric="rmse", weight=0.65, uses_outputs=["outlet"]
            ),
            CalibObjectiveBlockDecl(
                name="piezometry", metric="rmse", weight=0.35, uses_outputs=["piezo"]
            ),
        ]

    @staticmethod
    def _extracted(monkeypatch, *, sim_outlet: list[float], sim_piezo: list[float]) -> None:
        from hydromodpy.calibration.metrics import composite
        from hydromodpy.calibration.metrics.solver_extract import ExtractedOutputs

        times = pd.DatetimeIndex(["2000-01-01", "2000-01-02"])
        monkeypatch.setattr(
            composite,
            "extract_outputs",
            lambda ctx, outputs: ExtractedOutputs(
                values={"outlet": sim_outlet, "piezo": sim_piezo},
                series={
                    "outlet": pd.Series(sim_outlet, index=times),
                    "piezo": pd.Series(sim_piezo, index=times),
                },
                diagnostics={},
            ),
        )

    def test_a_perfect_match_costs_nothing(self, monkeypatch) -> None:
        from hydromodpy.calibration.metrics.composite import build_metric_extractor

        self._extracted(monkeypatch, sim_outlet=[1.0, 2.0], sim_piezo=[40.0, 41.0])
        metric_fn = build_metric_extractor(
            None, None, _ctx(), outputs=self._outputs(), objective_blocks=self._blocks()
        )

        total, components = metric_fn(None)

        assert total == pytest.approx(0.0)
        assert components["outlet.n_paired"] == 2.0
        assert components["piezo.n_paired"] == 2.0

    def test_the_weights_decide_how_much_each_target_carries(self, monkeypatch) -> None:
        """One metre of error on the piezometer, one m3/s on the outlet."""
        from hydromodpy.calibration.metrics.composite import build_metric_extractor

        self._extracted(monkeypatch, sim_outlet=[2.0, 3.0], sim_piezo=[41.0, 42.0])
        metric_fn = build_metric_extractor(
            None, None, _ctx(), outputs=self._outputs(), objective_blocks=self._blocks()
        )

        total, components = metric_fn(None)

        assert components["hydrograph.raw_cost"] == pytest.approx(1.0)
        assert components["piezometry.raw_cost"] == pytest.approx(1.0)
        assert total == pytest.approx(1.0)

    def test_a_window_now_applies_because_the_series_carry_dates(self, monkeypatch) -> None:
        from hydromodpy.calibration.metrics.composite import build_metric_extractor

        self._extracted(monkeypatch, sim_outlet=[9.0, 2.0], sim_piezo=[40.0, 41.0])
        metric_fn = build_metric_extractor(
            None,
            None,
            _ctx(),
            outputs=self._outputs(),
            objective_blocks=self._blocks(),
            scoring_window=(pd.Timestamp("2000-01-02"), None),
        )

        total, components = metric_fn(None)

        # The first day, where the outlet is out by 8, is outside the window.
        assert components["outlet.n_paired"] == 1.0
        assert total == pytest.approx(0.0)

    def test_a_window_is_still_refused_when_an_output_has_no_dates(self) -> None:
        from hydromodpy.calibration.config import CalibObjectiveBlockDecl
        from hydromodpy.calibration.metrics.composite import build_metric_extractor

        outputs = self._outputs()
        outputs["typed"] = _TYPED
        blocks = [
            *self._blocks(),
            CalibObjectiveBlockDecl(name="typed", metric="rmse", uses_outputs=["typed"]),
        ]

        with pytest.raises(ValueError, match="typed"):
            build_metric_extractor(
                None,
                None,
                _ctx(),
                outputs=outputs,
                objective_blocks=blocks,
                scoring_window=(pd.Timestamp("2000-01-02"), None),
            )
