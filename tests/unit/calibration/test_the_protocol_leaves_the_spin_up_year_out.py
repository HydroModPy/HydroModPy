"""The protocol's transient stage does not score the spin-up year by default.

The transient stage runs the project's own time grid, whose first year starts
from an initial condition the run did not produce. The protocol used to write
a scoring window on that stage only when the file declared one, so without it
the hydrograph, and a two-bound network scored in the same phase, read the
spin-up year like any other. It now opens the window one year after
``[simulation.time].start_datetime``. A window or a warm-up the file declares
still wins, and the steady stage is written as before.
"""

from __future__ import annotations

import argparse
import copy
import datetime
import textwrap
import tomllib
from pathlib import Path

import pytest

from hydromodpy.calibration.config import (
    CalibObjectiveBlockDecl,
    CalibPhaseDecl,
    CalibrationConfig,
    scoring_window_bounds,
)
from hydromodpy.calibration.protocols import expand_calibration_protocol, protocol_record
from hydromodpy.calibration.protocols.matching_hydrographic_network import (
    STEADY_STAGE,
    TRANSIENT_STAGE,
)
from hydromodpy.calibration.runners.staged_runner import _phase_config

NAME = "matching_hydrographic_network"


def _doc(start: object = "1995-01-01", end: object = "2020-12-31", **calibration: object):
    return {
        "simulation": {
            "time": {
                "start_datetime": start,
                "end_datetime": end,
                "step_value": 1,
                "step_unit": "day",
            }
        },
        "data": {"hydrometry": {"sources": [{"station_ids": ["NANCON"]}]}},
        "calibration": {
            "protocol": NAME,
            "parameters": {
                "K": {"bounds": [1e-8, 1e-2], "transform": "log"},
                "Sy": {"bounds": [1e-4, 0.5], "transform": "log"},
            },
            "outputs": {
                "seepage_network": {
                    "support": "network",
                    "stream_geometry_path": "nancon.gpkg",
                }
            },
            **calibration,
        },
    }


def _stages(doc) -> tuple[dict, dict]:
    steady, transient = expand_calibration_protocol(doc)["calibration"]["phases"]
    return steady, transient


class TestTheDefaultWindow:
    def test_the_transient_stage_scores_from_one_year_after_the_start(self) -> None:
        _, transient = _stages(_doc())

        assert transient["scoring_window"] == {"start": "1996-01-01"}
        assert "1996-01-01" in transient["description"]
        assert "spin-up" in transient["description"]

    def test_a_start_inside_a_year_leaves_twelve_months_out(self) -> None:
        _, transient = _stages(_doc(start="2011-06-01"))

        assert transient["scoring_window"] == {"start": "2012-06-01"}

    def test_the_steady_stage_is_written_as_before(self) -> None:
        steady, _ = _stages(_doc())

        assert "scoring_window" not in steady
        assert steady["regime"] == "steady"
        assert steady["description"].endswith("steady state over the record.")

    def test_the_single_metric_route_gets_the_same_window(self) -> None:
        doc = _doc()
        doc["data"]["hydrometry"]["sources"][0]["station_ids"] = ["NANCON", "OTHER"]

        _, transient = _stages(doc)

        assert transient["variable"] == "discharge"
        assert transient["scoring_window"] == {"start": "1996-01-01"}

    def test_a_date_a_datetime_and_a_string_write_the_same_stage(self) -> None:
        as_date = _stages(_doc(datetime.date(1995, 1, 1), datetime.date(2020, 12, 31)))
        as_datetime = _stages(_doc(datetime.datetime(1995, 1, 1), datetime.datetime(2020, 12, 31)))
        as_string = _stages(_doc("1995-01-01", "2020-12-31"))

        assert as_date == as_datetime == as_string

    def test_a_run_of_one_year_has_nothing_past_its_spin_up_and_is_scored_whole(self) -> None:
        _, transient = _stages(_doc(start="2000-01-01", end="2000-12-31"))

        assert "scoring_window" not in transient
        assert "spin-up" not in transient["description"]

    def test_a_run_ending_on_its_first_anniversary_is_scored_whole(self) -> None:
        """A window opening on the run's last instant would leave nothing to score."""
        _, transient = _stages(_doc(start="2000-01-01", end="2001-01-01"))

        assert "scoring_window" not in transient
        assert "spin-up" not in transient["description"]

    def test_a_run_one_day_past_its_first_year_gets_the_window(self) -> None:
        _, transient = _stages(_doc(start="2000-01-01", end="2001-01-02"))

        assert transient["scoring_window"] == {"start": "2001-01-01"}

    def test_no_storage_stage_means_no_window_at_all(self) -> None:
        phases = expand_calibration_protocol(_doc(protocol={"name": NAME, "storage": None}))[
            "calibration"
        ]["phases"]

        assert [phase["name"] for phase in phases] == [STEADY_STAGE]
        assert "scoring_window" not in phases[0]

    def test_the_window_validates_as_a_phase_window(self) -> None:
        _, transient = _stages(_doc())

        decl = CalibPhaseDecl.model_validate(transient)

        assert decl.scoring_window is not None
        assert decl.scoring_window.start == "1996-01-01"
        assert decl.scoring_window.end is None


class TestADeclarationWins:
    def test_a_window_on_the_protocol_is_the_one_written(self) -> None:
        window = {"start": "2001-01-01", "end": "2002-12-31"}

        _, transient = _stages(_doc(protocol={"name": NAME, "scoring_window": window}))

        assert transient["scoring_window"] == window
        assert "spin-up" not in transient["description"]

    def test_a_window_starting_on_the_run_s_first_day_scores_the_spin_up_year(self) -> None:
        window = {"start": "1995-01-01"}

        _, transient = _stages(_doc(protocol={"name": NAME, "scoring_window": window}))

        assert transient["scoring_window"] == window

    def test_a_window_on_the_calibration_leaves_the_phase_to_inherit_it(self) -> None:
        window = {"start": "1997-01-01", "end": "2020-12-31"}

        _, transient = _stages(_doc(scoring_window=window))

        assert "scoring_window" not in transient

    def test_a_warm_up_in_samples_is_not_contradicted_by_a_window(self) -> None:
        doc = _doc(warmup_periods=12)

        _, transient = _stages(doc)
        assert "scoring_window" not in transient

        # Both conventions at once are refused; the default must not create that case.
        calibration = expand_calibration_protocol(doc)["calibration"]
        CalibrationConfig.model_validate(calibration)


class TestASealedRunReplaysItsOwnWindow:
    def test_a_stage_sealed_without_a_window_reads_back_without_one(self) -> None:
        """A run sealed before this default replays what it ran."""
        fresh = expand_calibration_protocol(_doc())["calibration"]
        sealed_phases = copy.deepcopy(fresh["phases"])
        del sealed_phases[1]["scoring_window"]
        sealed_phases[1]["description"] = (
            "Read Sy from the observed hydrograph, K frozen, transient."
        )

        doc = _doc(phases=sealed_phases, objective_blocks=fresh["objective_blocks"])
        _, transient = _stages(doc)

        assert "scoring_window" not in transient

    def test_a_stage_sealed_with_the_default_window_reads_back(self) -> None:
        fresh = expand_calibration_protocol(_doc())["calibration"]
        dumped = [
            CalibPhaseDecl.model_validate(phase).model_dump(mode="json")
            for phase in fresh["phases"]
        ]

        doc = _doc(phases=dumped, objective_blocks=fresh["objective_blocks"])
        _, transient = _stages(doc)

        assert transient["scoring_window"] == {"start": "1996-01-01"}

    def test_a_stage_sealed_with_another_window_is_refused(self) -> None:
        fresh = expand_calibration_protocol(_doc())["calibration"]
        sealed_phases = copy.deepcopy(fresh["phases"])
        sealed_phases[1]["scoring_window"] = {"start": "1999-01-01"}

        with pytest.raises(ValueError, match="phases"):
            expand_calibration_protocol(
                _doc(phases=sealed_phases, objective_blocks=fresh["objective_blocks"])
            )


class TestTheWindowReachesWhatThePhaseScores:
    def test_the_transient_sub_run_carries_the_window(self) -> None:
        cfg = CalibrationConfig.model_validate(expand_calibration_protocol(_doc())["calibration"])
        steady_decl, transient_decl = cfg.phases

        transient = _phase_config(cfg, transient_decl)
        steady = _phase_config(cfg, steady_decl)

        assert transient.scoring_window is not None
        assert transient.scoring_window.start == "1996-01-01"
        assert steady.scoring_window is None


class TestWhatTheRecordAndExpandSay:
    def test_the_record_declares_the_spin_up_rule(self) -> None:
        record = protocol_record(NAME)

        deviations = {item["key"]: item for item in record["deviations"]}
        entry = deviations["spin_up_year"]
        assert "June to October" in entry["paper"]
        assert "first year" in entry["here"]
        assert entry["why"].strip()
        assert "spin-up" in record["stages"][1]
        assert "spin-up" not in record["stages"][0]

    def test_a_declared_window_is_recorded_as_an_option_that_moved(self) -> None:
        from hydromodpy.calibration.config import MatchingHydrographicNetworkOptions

        declared = MatchingHydrographicNetworkOptions.model_validate(
            {"name": NAME, "scoring_window": {"start": "1995-01-01"}}
        )

        moved = protocol_record(NAME, declared)["options_away_from_the_recipe"]

        assert {"key": "scoring_window", "here": {"start": "1995-01-01"}, "recipe": None} in moved

    def test_expand_prints_the_window_on_the_transient_stage_only(self, tmp_path, capsys) -> None:
        from hydromodpy.cli.commands import calibrate as calibrate_cmd

        path = Path(tmp_path) / "calib.toml"
        path.write_text(
            textwrap.dedent(
                """
                [simulation.time]
                start_datetime = 1995-01-01
                end_datetime = 2020-12-31
                step_value = 1
                step_unit = "day"

                [calibration]
                protocol = "matching_hydrographic_network"

                [calibration.parameters.K]

                [calibration.parameters.Sy]

                [calibration.outputs.streams]
                support = "network"
                stream_geometry_path = "streams.gpkg"

                [[data.hydrometry.sources]]
                station_ids = ["G1"]
                """
            ),
            encoding="utf-8",
        )

        calibrate_cmd.run(
            argparse.Namespace(config=path, check=False, list_phases=False, phase=None, expand=True)
        )

        printed = capsys.readouterr().out
        body = "\n".join(line for line in printed.splitlines() if not line.startswith("#"))
        steady, transient = tomllib.loads(body)["calibration"]["phases"]
        assert transient["name"] == TRANSIENT_STAGE
        assert transient["scoring_window"] == {"start": "1996-01-01"}
        assert "scoring_window" not in steady


class TestTheCheckSaysWhenTheWindowCannotApply:
    """The expansion drops the window silently; ``--check`` prints why."""

    def _why(self, doc) -> str | None:
        from types import SimpleNamespace

        from hydromodpy.calibration.protocols import why_the_spin_up_year_is_scored

        calibration = CalibrationConfig.model_validate(
            expand_calibration_protocol(doc)["calibration"]
        )
        time = doc["simulation"]["time"]
        return why_the_spin_up_year_is_scored(
            calibration,
            SimpleNamespace(
                start_datetime=datetime.datetime.fromisoformat(time["start_datetime"]),
                end_datetime=datetime.datetime.fromisoformat(time["end_datetime"]),
            ),
        )

    def test_a_run_of_exactly_one_calendar_year_is_told(self) -> None:
        why = self._why(_doc(start="2000-01-01", end="2000-12-31"))

        assert why is not None
        assert "ends on 2000-12-31, within one year of its start 2000-01-01" in why
        assert "[calibration.protocol].scoring_window" in why

    def test_a_run_ending_on_its_anniversary_is_told(self) -> None:
        assert self._why(_doc(start="2000-01-01", end="2001-01-01")) is not None

    def test_a_run_the_window_reached_says_nothing(self) -> None:
        assert self._why(_doc()) is None

    def test_a_declared_window_or_warm_up_says_nothing(self) -> None:
        window = {"start": "2000-01-01"}
        short = {"start": "2000-01-01", "end": "2000-12-31"}

        assert self._why(_doc(**short, protocol={"name": NAME, "scoring_window": window})) is None
        assert self._why(_doc(**short, warmup_periods=30)) is None

    def test_no_storage_stage_says_nothing(self) -> None:
        doc = _doc(start="2000-01-01", end="2000-12-31", protocol={"name": NAME, "storage": None})

        assert self._why(doc) is None

    def test_a_sealed_stage_without_a_window_is_named(self) -> None:
        fresh = expand_calibration_protocol(_doc())["calibration"]
        sealed_phases = copy.deepcopy(fresh["phases"])
        del sealed_phases[1]["scoring_window"]
        sealed_phases[1]["description"] = (
            "Read Sy from the observed hydrograph, K frozen, transient."
        )

        why = self._why(_doc(phases=sealed_phases, objective_blocks=fresh["objective_blocks"]))

        assert why is not None
        assert f"the {TRANSIENT_STAGE} phase this file writes has no scoring_window" in why
