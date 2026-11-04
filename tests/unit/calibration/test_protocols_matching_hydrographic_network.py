"""Tests of `protocols.matching_hydrographic_network`."""

from __future__ import annotations

import argparse
import copy
import datetime
import math
import textwrap
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.calibration.config import (
    CalibOutputNetwork,
    CalibPhaseDecl,
    CalibrationConfig,
    MatchingHydrographicNetworkOptions,
)
from hydromodpy.calibration.optim.adapters.scipy_adapter import ScipyNelderMead
from hydromodpy.calibration.optim.engine import CalibrationEngine
from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.protocols import (
    available_protocols,
    deviations_in_force,
    expand_calibration_protocol,
    get_protocol,
    protocol_options_away_from_the_recipe,
    protocol_record,
    why_the_spin_up_year_is_scored,
)
from hydromodpy.calibration.protocols import matching_hydrographic_network as module
from hydromodpy.calibration.protocols.matching_hydrographic_network import (
    DEFAULTS_BY_VERSION,
    HYDROGRAPH_BLOCK,
    HYDROGRAPH_OUTPUT,
    NETWORK_BLOCK,
    STEADY_STAGE,
    TRANSIENT_STAGE,
    _write_hydrograph_output,
)
from hydromodpy.calibration.runners.cli_runner import _protocol_of_session
from hydromodpy.calibration.runners.phase_regime import phase_overrides
from hydromodpy.calibration.runners.staged_runner import _phase_config
from hydromodpy.cli.commands import calibrate as calibrate_cmd
from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.stream_criterion_defaults import STREAM_CRITERION_DEFAULTS
from hydromodpy.core.toml_io.loader import load_toml_with_base_config
from tests.unit.calibration._factories_scoring import make_document

# From test_a_removed_key_on_the_hydrograph_output_is_named.py
# A sealed run whose hydrograph output still carries a removed key is refused for that key.
#
# The protocol compares the point output it writes with the one a sealed run
# spelled out. An output that no longer validates is not another output under
# the same name: the refusal names the key, here the per-output
# ``diagonal_neighbors`` the descent D made obsolete.


def _sealed(**extra: object) -> dict[str, object]:
    return {
        HYDROGRAPH_OUTPUT: {
            "variable": "discharge",
            "support": "point",
            "observes": "NANCON",
            **extra,
        }
    }


def test_a_removed_key_is_named_and_not_read_as_a_collision() -> None:
    outputs = _sealed(diagonal_neighbors=False)

    with pytest.raises(
        ValueError, match="'diagonal_neighbors', which this output does not"
    ) as info:
        _write_hydrograph_output(
            outputs,
            MatchingHydrographicNetworkOptions(name="matching_hydrographic_network"),
            "NANCON",
        )

    assert "Rename it" not in str(info.value)


def test_the_same_output_without_the_key_is_accepted() -> None:
    outputs = _sealed()

    _write_hydrograph_output(
        outputs, MatchingHydrographicNetworkOptions(name="matching_hydrographic_network"), "NANCON"
    )

    assert outputs[HYDROGRAPH_OUTPUT]["observes"] == "NANCON"


def test_another_output_under_the_name_is_still_a_collision() -> None:
    outputs = _sealed(observes="OTHER")

    with pytest.raises(ValueError, match="Rename it"):
        _write_hydrograph_output(
            outputs,
            MatchingHydrographicNetworkOptions(name="matching_hydrographic_network"),
            "NANCON",
        )


# From test_the_protocol_is_versioned.py
# A number that informed a decision must be replayable with the recipe of its era.
#
# Naming a method is not enough for that. A recipe improves, and a file that ran
# version 1.2 and silently gets 1.3 has lost the only guarantee a pin exists to
# give. So the version is declared, a file may pin one the table holds, a pin writes
# the values of its version for every key the file leaves empty, and any other pin
# is refused rather than approximated.
#
# Two more things the record has to carry, for the same reason. Where this
# implementation departs from its publication, because a protocol that silently
# improves on its paper is no longer that paper's method. And what running it on
# each backend is actually worth, in a vocabulary that separates "a case runs this"
# from "nothing forbids it and nobody tried".


NAME = "matching_hydrographic_network"


class TestTheVersion:
    def test_every_protocol_declares_one(self) -> None:
        for name in available_protocols():
            assert get_protocol(name).version

    def test_the_record_carries_it(self) -> None:
        assert protocol_record(NAME)["version"] == "1.3"

    def test_the_record_of_a_pinned_file_says_the_pin(self) -> None:
        declared = MatchingHydrographicNetworkOptions(name=NAME, version="1.2")

        assert protocol_record(NAME, declared)["version"] == "1.2"

    @pytest.mark.parametrize("version", sorted(DEFAULTS_BY_VERSION))
    def test_a_pin_on_a_version_of_the_table_runs(self, version: str) -> None:
        expanded = expand_calibration_protocol(
            make_document(protocol={"name": NAME, "version": version})
        )

        assert expanded["calibration"]["phases"]

    def test_a_pin_on_1_2_says_what_a5_ran_under_that_number(self, caplog) -> None:
        module._TOLD.clear()
        with caplog.at_level("WARNING"):
            expand_calibration_protocol(make_document(protocol={"name": NAME, "version": "1.2"}))

        assert "v2.0.0a5" in caplog.text and "observed_rasterization = 'heads'" in caplog.text

    def test_the_heads_keys_are_declared_departures_with_their_value(self) -> None:
        doc = expand_calibration_protocol(make_document(protocol={"name": NAME}))
        section = CalibrationConfig.model_validate(doc["calibration"])

        told = {item.key: item for item in deviations_in_force(section)}

        assert told["heads_snap_radius"].state == "departs"
        assert told["heads_min_drained_area_km2"].value == 0.02

    def test_a_mismatched_pin_is_refused_rather_than_approximated(self) -> None:
        with pytest.raises(ValueError, match="carries 1.2, 1.3.*replayable"):
            expand_calibration_protocol(make_document(protocol={"name": NAME, "version": "0.9"}))

    def test_the_released_1_1_is_refused_now_that_its_defaults_moved(self) -> None:
        """v2.0.0a1 shipped 1.1; the fill, the spin-up year and the length bound moved since."""
        with pytest.raises(ValueError, match="replayable"):
            expand_calibration_protocol(
                make_document(protocol={"name": "matching_hydrographic_network", "version": "1.1"})
            )

    def test_no_pin_runs_what_is_installed(self) -> None:
        expanded = expand_calibration_protocol(
            make_document(protocol="matching_hydrographic_network")
        )

        assert expanded["calibration"]["phases"]


def _network_output_of(protocol: object, **written: object) -> dict[str, object]:
    doc = make_document(protocol=protocol)
    doc["calibration"]["outputs"]["seepage_network"].update(written)
    return expand_calibration_protocol(doc)["calibration"]["outputs"]["seepage_network"]


class TestTheDefaultsOfAVersion:
    def test_the_last_line_of_the_table_is_what_the_model_defaults_to(self) -> None:
        """A default that moves without a new line here would move a file with no pin."""
        (*_, latest) = DEFAULTS_BY_VERSION.values()
        model = CalibOutputNetwork(stream_geometry_path="map.gpkg")

        for key, value in latest.items():
            if key == "verdict":
                assert model.verdict.max_catchment_mismatch == value["max_catchment_mismatch"]
            elif key == "heads_snap_radius":
                assert float(model.heads_snap_radius.to("m").magnitude) == value
            else:
                assert getattr(model, key) == value, key
        assert latest["verdict"]["max_catchment_mismatch"] == (
            STREAM_CRITERION_DEFAULTS.max_catchment_mismatch
        )

    def test_1_2_runs_the_crossing_rule_on_the_whole_file_with_no_veto(self) -> None:
        written = _network_output_of({"name": NAME, "version": "1.2"})

        assert written["observed_rasterization"] == "crossing"
        assert written["clip_map_to_catchment"] is False
        assert written["verdict"] == {"max_catchment_mismatch": False}
        assert "heads_snap_radius" not in written

    @pytest.mark.parametrize("protocol", [NAME, {"name": NAME, "version": "1.3"}])
    def test_1_3_draws_the_heads_of_the_cut_map_under_the_veto(self, protocol) -> None:
        written = _network_output_of(protocol)

        assert written["observed_rasterization"] == "heads"
        assert written["clip_map_to_catchment"] is True
        assert written["heads_snap_radius"] == 100.0
        assert written["verdict"] == {"max_catchment_mismatch": 0.05}

    def test_a_key_the_file_writes_wins_over_its_version(self) -> None:
        written = _network_output_of(
            {"name": NAME, "version": "1.2"},
            observed_rasterization="heads",
            verdict={"max_catchment_mismatch": 0.2},
        )

        assert written["observed_rasterization"] == "heads"
        assert written["heads_min_drained_area_km2"] == 0.02
        assert written["verdict"] == {"max_catchment_mismatch": 0.2}
        assert written["clip_map_to_catchment"] is False

    def test_the_document_given_is_not_written_into(self) -> None:
        doc = make_document(protocol={"name": NAME, "version": "1.2"})

        expand_calibration_protocol(doc)

        assert "observed_rasterization" not in doc["calibration"]["outputs"]["seepage_network"]

    def test_a_dump_of_the_output_reloads_as_it_ran(self) -> None:
        """A sealed run writes every key: the expansion has nothing left to fill."""
        doc = make_document(protocol={"name": NAME, "version": "1.2"})
        output = CalibOutputNetwork.model_validate(
            expand_calibration_protocol(doc)["calibration"]["outputs"]["seepage_network"]
        )
        doc["calibration"]["protocol"] = NAME
        doc["calibration"]["outputs"]["seepage_network"] = output.model_dump(mode="json")

        written = expand_calibration_protocol(doc)["calibration"]["outputs"]["seepage_network"]

        assert written["observed_rasterization"] == "crossing"
        assert written["verdict"]["max_catchment_mismatch"] is False


class TestTheSessionWritesItsDepartures:
    def _session_protocol(self, protocol: object):
        doc = expand_calibration_protocol(make_document(protocol=protocol))
        cfg = CalibrationConfig.model_validate(doc["calibration"])
        return _protocol_of_session(cfg, None)

    def test_a_file_without_a_pin_writes_every_default_that_departs(self) -> None:
        record = self._session_protocol(NAME)

        assert record.version == "1.3"
        departures = {item.key: item for item in record.departures}
        assert departures["observed_rasterization"].value == "heads"
        assert departures["observed_rasterization"].written is False
        assert departures["max_catchment_mismatch"].value == "0.05"
        assert departures["tau_specific_ratio"].always is False
        assert departures["steady_recharge_window"].always is False
        assert "steady_recharge_window" in departures
        assert "dem_correc_type" not in departures

    def test_a_pin_on_1_2_writes_its_own_defaults(self) -> None:
        record = self._session_protocol({"name": NAME, "version": "1.2"})

        assert record.version == "1.2"
        departures = {item.key for item in record.departures}
        assert "observed_rasterization" not in departures
        assert "max_catchment_mismatch" not in departures

    def test_a_search_with_no_protocol_writes_none(self) -> None:
        cfg = CalibrationConfig.model_validate(
            {
                "parameters": {"K": {"bounds": [1e-7, 1e-3], "path": "flow.param.K.field.value"}},
                "outputs": {"q": {"support": "point", "variable": "discharge", "observes": "S"}},
                "objective_blocks": [{"name": "q", "metric": "nse", "uses_outputs": ["q"]}],
            }
        )

        assert _protocol_of_session(cfg, None) is None


class TestTheSupportMatrix:
    def test_it_uses_a_closed_vocabulary(self) -> None:
        support = protocol_record("matching_hydrographic_network")["support"]

        assert set(support.values()) <= {"tested", "expected_untested", "unsupported"}

    def test_it_names_every_flow_backend(self) -> None:
        support = protocol_record("matching_hydrographic_network")["support"]

        assert {"modflow6", "modflow_nwt", "boussinesq"} <= set(support)

    def test_it_separates_a_tested_backend_from_one_that_cannot_serve_it(self) -> None:
        """Publishing "supported" for all three would be the dishonest simplification."""
        support = protocol_record("matching_hydrographic_network")["support"]

        assert support["modflow6"] == "tested"
        assert support["modflow_nwt"] == "tested"
        assert support["boussinesq"] == "unsupported"


class TestTheDeviations:
    def test_the_threshold_that_is_not_the_paper_s_is_declared(self) -> None:
        keys = {
            item["key"] for item in protocol_record("matching_hydrographic_network")["deviations"]
        }

        assert "tau_specific_ratio" in keys

    def test_each_departure_says_what_the_paper_does_and_why_this_differs(self) -> None:
        for item in protocol_record("matching_hydrographic_network")["deviations"]:
            assert item["paper"].strip(), item["key"]
            assert item["here"].strip(), item["key"]
            assert item["why"].strip(), item["key"]


class TestWhatMayBeAdjusted:
    def test_the_whitelist_matches_what_the_options_expose(self) -> None:
        """A setting outside it would be a variant claiming to be the method."""

        declared = get_protocol("matching_hydrographic_network").adjustable
        exposed = set(MatchingHydrographicNetworkOptions.model_fields) - {"name", "version"}

        assert declared == exposed


# From test_the_protocol_leaves_the_spin_up_year_out.py
# The protocol's transient stage does not score the spin-up year by default.
#
# The transient stage runs the project's own time grid, whose first year starts
# from an initial condition the run did not produce. The protocol used to write
# a scoring window on that stage only when the file declared one, so without it
# the hydrograph, and a two-bound network scored in the same phase, read the
# spin-up year like any other. It now opens the window one year after
# ``[simulation.time].start_datetime``. A window or a warm-up the file declares
# still wins, and the steady stage is written as before.


def _stages(doc) -> tuple[dict, dict]:
    steady, transient = expand_calibration_protocol(doc)["calibration"]["phases"]
    return steady, transient


class TestTheDefaultWindow:
    def test_the_transient_stage_scores_from_one_year_after_the_start(self) -> None:
        _, transient = _stages(make_document())

        assert transient["scoring_window"] == {"start": "1996-01-01"}
        assert "1996-01-01" in transient["description"]
        assert "spin-up" in transient["description"]

    def test_a_start_inside_a_year_leaves_twelve_months_out(self) -> None:
        _, transient = _stages(make_document(start="2011-06-01"))

        assert transient["scoring_window"] == {"start": "2012-06-01"}

    def test_the_steady_stage_is_written_as_before(self) -> None:
        steady, _ = _stages(make_document())

        assert "scoring_window" not in steady
        assert steady["regime"] == "steady"
        assert steady["description"].endswith("steady state over the record.")

    def test_the_single_metric_route_gets_the_same_window(self) -> None:
        doc = make_document()
        doc["data"]["hydrometry"]["sources"][0]["station_ids"] = ["NANCON", "OTHER"]

        _, transient = _stages(doc)

        assert transient["variable"] == "discharge"
        assert transient["scoring_window"] == {"start": "1996-01-01"}

    def test_a_date_a_datetime_and_a_string_write_the_same_stage(self) -> None:
        as_date = _stages(make_document(datetime.date(1995, 1, 1), datetime.date(2020, 12, 31)))
        as_datetime = _stages(
            make_document(datetime.datetime(1995, 1, 1), datetime.datetime(2020, 12, 31))
        )
        as_string = _stages(make_document("1995-01-01", "2020-12-31"))

        assert as_date == as_datetime == as_string

    def test_a_run_of_one_year_has_nothing_past_its_spin_up_and_is_scored_whole(self) -> None:
        _, transient = _stages(make_document(start="2000-01-01", end="2000-12-31"))

        assert "scoring_window" not in transient
        assert "spin-up" not in transient["description"]

    def test_a_run_ending_on_its_first_anniversary_is_scored_whole(self) -> None:
        """A window opening on the run's last instant would leave nothing to score."""
        _, transient = _stages(make_document(start="2000-01-01", end="2001-01-01"))

        assert "scoring_window" not in transient
        assert "spin-up" not in transient["description"]

    def test_a_run_one_day_past_its_first_year_gets_the_window(self) -> None:
        _, transient = _stages(make_document(start="2000-01-01", end="2001-01-02"))

        assert transient["scoring_window"] == {"start": "2001-01-01"}

    def test_no_storage_stage_means_no_window_at_all(self) -> None:
        phases = expand_calibration_protocol(
            make_document(protocol={"name": NAME, "storage": None})
        )["calibration"]["phases"]

        assert [phase["name"] for phase in phases] == [STEADY_STAGE]
        assert "scoring_window" not in phases[0]

    def test_the_window_validates_as_a_phase_window(self) -> None:
        _, transient = _stages(make_document())

        decl = CalibPhaseDecl.model_validate(transient)

        assert decl.scoring_window is not None
        assert decl.scoring_window.start == "1996-01-01"
        assert decl.scoring_window.end is None


class TestADeclarationWins:
    def test_a_window_on_the_protocol_is_the_one_written(self) -> None:
        window = {"start": "2001-01-01", "end": "2002-12-31"}

        _, transient = _stages(make_document(protocol={"name": NAME, "scoring_window": window}))

        assert transient["scoring_window"] == window
        assert "spin-up" not in transient["description"]

    def test_a_window_starting_on_the_run_s_first_day_scores_the_spin_up_year(self) -> None:
        window = {"start": "1995-01-01"}

        _, transient = _stages(make_document(protocol={"name": NAME, "scoring_window": window}))

        assert transient["scoring_window"] == window

    def test_a_window_on_the_calibration_leaves_the_phase_to_inherit_it(self) -> None:
        window = {"start": "1997-01-01", "end": "2020-12-31"}

        _, transient = _stages(make_document(scoring_window=window))

        assert "scoring_window" not in transient

    def test_a_warm_up_in_samples_is_not_contradicted_by_a_window(self) -> None:
        doc = make_document(warmup_periods=12)

        _, transient = _stages(doc)
        assert "scoring_window" not in transient

        # Both conventions at once are refused; the default must not create that case.
        calibration = expand_calibration_protocol(doc)["calibration"]
        CalibrationConfig.model_validate(calibration)


class TestASealedRunReplaysItsOwnWindow:
    def test_a_stage_sealed_without_a_window_reads_back_without_one(self) -> None:
        """A run sealed before this default replays what it ran."""
        fresh = expand_calibration_protocol(make_document())["calibration"]
        sealed_phases = copy.deepcopy(fresh["phases"])
        del sealed_phases[1]["scoring_window"]
        sealed_phases[1]["description"] = (
            "Read Sy from the observed hydrograph, K frozen, transient."
        )

        doc = make_document(phases=sealed_phases, objective_blocks=fresh["objective_blocks"])
        _, transient = _stages(doc)

        assert "scoring_window" not in transient

    def test_a_stage_sealed_with_the_default_window_reads_back(self) -> None:
        fresh = expand_calibration_protocol(make_document())["calibration"]
        dumped = [
            CalibPhaseDecl.model_validate(phase).model_dump(mode="json")
            for phase in fresh["phases"]
        ]

        doc = make_document(phases=dumped, objective_blocks=fresh["objective_blocks"])
        _, transient = _stages(doc)

        assert transient["scoring_window"] == {"start": "1996-01-01"}

    def test_a_stage_sealed_with_another_window_is_refused(self) -> None:
        fresh = expand_calibration_protocol(make_document())["calibration"]
        sealed_phases = copy.deepcopy(fresh["phases"])
        sealed_phases[1]["scoring_window"] = {"start": "1999-01-01"}

        with pytest.raises(ValueError, match="phases"):
            expand_calibration_protocol(
                make_document(phases=sealed_phases, objective_blocks=fresh["objective_blocks"])
            )


class TestTheWindowReachesWhatThePhaseScores:
    def test_the_transient_sub_run_carries_the_window(self) -> None:
        cfg = CalibrationConfig.model_validate(
            expand_calibration_protocol(make_document())["calibration"]
        )
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
        declared = MatchingHydrographicNetworkOptions.model_validate(
            {"name": NAME, "scoring_window": {"start": "1995-01-01"}}
        )

        moved = protocol_record(NAME, declared)["options_away_from_the_recipe"]

        assert {"key": "scoring_window", "here": {"start": "1995-01-01"}, "recipe": None} in moved

    def test_expand_prints_the_window_on_the_transient_stage_only(self, tmp_path, capsys) -> None:
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
        why = self._why(make_document(start="2000-01-01", end="2000-12-31"))

        assert why is not None
        assert "ends on 2000-12-31, within one year of its start 2000-01-01" in why
        assert "[calibration.protocol].scoring_window" in why

    def test_a_run_ending_on_its_anniversary_is_told(self) -> None:
        assert self._why(make_document(start="2000-01-01", end="2001-01-01")) is not None

    def test_a_run_the_window_reached_says_nothing(self) -> None:
        assert self._why(make_document()) is None

    def test_a_declared_window_or_warm_up_says_nothing(self) -> None:
        window = {"start": "2000-01-01"}
        short = {"start": "2000-01-01", "end": "2000-12-31"}

        assert (
            self._why(make_document(**short, protocol={"name": NAME, "scoring_window": window}))
            is None
        )
        assert self._why(make_document(**short, warmup_periods=30)) is None

    def test_no_storage_stage_says_nothing(self) -> None:
        doc = make_document(
            start="2000-01-01", end="2000-12-31", protocol={"name": NAME, "storage": None}
        )

        assert self._why(doc) is None

    def test_a_sealed_stage_without_a_window_is_named(self) -> None:
        fresh = expand_calibration_protocol(make_document())["calibration"]
        sealed_phases = copy.deepcopy(fresh["phases"])
        del sealed_phases[1]["scoring_window"]
        sealed_phases[1]["description"] = (
            "Read Sy from the observed hydrograph, K frozen, transient."
        )

        why = self._why(
            make_document(phases=sealed_phases, objective_blocks=fresh["objective_blocks"])
        )

        assert why is not None
        assert f"the {TRANSIENT_STAGE} phase this file writes has no scoring_window" in why


# From test_the_reference_replication_keeps_its_estimator.py
# The MODFLOW 6 replication of the reference script must not drift to the recipe.
#
# ``ref_example04.toml`` exists to be read beside ``example_04_calibration.py``: it
# measures what changes when the published estimator is replaced by the script's
# own mean offset. Someone tidying it toward the protocol's published defaults
# would delete the only thing it is for, and the file would still validate. So the
# values it departs on are gated, not commented.


REFERENCE = (
    Path(__file__).resolve().parents[3]
    / "examples"
    / "projects"
    / "21_nancon_network_calibration"
    / "ref_example04.toml"
)


@pytest.fixture(scope="module")
def calibration__reference_replication():
    return HydroModPyConfig.from_toml(REFERENCE).calibration


def test_the_two_stages_come_from_the_named_protocol(calibration__reference_replication) -> None:
    assert calibration__reference_replication.protocol is not None
    assert calibration__reference_replication.protocol.name == "matching_hydrographic_network"
    # Pinned, so the comparison cannot silently move with the recipe.
    assert calibration__reference_replication.protocol.version == "1.2"
    assert [phase.name for phase in calibration__reference_replication.phases] == [
        STEADY_STAGE,
        TRANSIENT_STAGE,
    ]
    assert [block.name for block in calibration__reference_replication.objective_blocks] == [
        NETWORK_BLOCK,
        HYDROGRAPH_BLOCK,
    ]


def test_stage_one_keeps_the_scripts_mean_offset_and_nelder_mead(
    calibration__reference_replication,
) -> None:
    assert calibration__reference_replication.objective_blocks[0].metric == "distance_mean"
    steady = calibration__reference_replication.phases[0]
    assert steady.method == "scipy_nelder_mead"
    assert steady.max_trials == 60
    assert steady.method_options == {"xatol": 0.30, "fatol": 0.05}


# The steady trace of a Nancon session run with these options on 2026-09-08:
# log10 K against the mean offset, in meters. Nine solves, one of them a repeat.
_NANCON_STEADY_TRACE = {
    -5.0: 287.3839080695424,
    -4.4: 186.641131046373,
    -3.8: 300.1191516816517,
    -4.55: 214.26321839924782,
    -4.25: 185.7234104098768,
    -3.95: 232.09030552780553,
    -4.1: 208.383141357349,
    -4.2875: 192.34474990832632,
}


def _replay(sugg: ParamSuggestion) -> EvaluationResult:
    point = round(math.log10(float(sugg.values["K"])), 6)
    return EvaluationResult(
        trial_id=sugg.trial_id,
        sim_id=None,
        cost=_NANCON_STEADY_TRACE[point],
        status="completed",
    )


def test_stage_one_meets_its_own_tolerance_well_inside_its_budget(
    calibration__reference_replication,
) -> None:
    # A simplex that runs out of its max_trials = 60 reports not converged. On
    # the recorded Nancon trace the simplex meets xatol and fatol after 9
    # solves, so the steady stage converges and freezes K for the transient one.
    steady = calibration__reference_replication.phases[0]
    lower, upper = calibration__reference_replication.parameters["K"].bounds
    space = ParameterSpace([CalibParameter(name="K", lower=lower, upper=upper, search_space="log")])
    optimizer = ScipyNelderMead(space, **steady.method_options)
    engine = CalibrationEngine(
        space=space, optimizer=optimizer, evaluator=_replay, max_trials=steady.max_trials
    )

    session = engine.run()

    assert session.converged
    assert session.extension == 0
    assert len(session.history) == 9


def test_stage_one_collapses_the_record_into_one_steady_period(
    calibration__reference_replication,
) -> None:
    # 1995-01-01 to 2020-12-31 inclusive, the window the REA recharge stops at.
    # The protocol writes the regime; the paths are what the trials run with.
    assert calibration__reference_replication.phases[0].regime == "steady"
    assert phase_overrides(
        calibration__reference_replication.phases[0], load_toml_with_base_config(REFERENCE)
    ) == {
        "flow.flow_regime": "steady",
        "simulation.time.start_datetime": "1995-01-01",
        "simulation.time.end_datetime": "2020-12-31",
        "simulation.time.step_unit": "day",
        "simulation.time.step_value": 9497,
    }


def test_stage_two_reads_storage_from_the_hydrograph_with_conductivity_frozen(
    calibration__reference_replication,
) -> None:
    assert calibration__reference_replication.phases[0].freeze_on_success is True
    storage = calibration__reference_replication.phases[1]
    assert storage.depends_on == STEADY_STAGE
    assert storage.parameters == ["Sy"]
    assert storage.objective_blocks == [HYDROGRAPH_BLOCK]
    assert storage.max_trials == 120
    assert storage.method_options["xatol"] == pytest.approx(3.7e-5)
    # The reference scores the whole calibration window, with no spin-up year cut.
    # The protocol leaves the first year out by default, so the file says so.
    assert storage.scoring_window is not None
    assert (storage.scoring_window.start, storage.scoring_window.end) == ("1995-01-01", None)

    hydrograph = next(
        block
        for block in calibration__reference_replication.objective_blocks
        if block.name == HYDROGRAPH_BLOCK
    )
    assert hydrograph.metric == "nse_log"
    assert hydrograph.uses_outputs == [HYDROGRAPH_OUTPUT]
    output = calibration__reference_replication.outputs[HYDROGRAPH_OUTPUT]
    assert output.observes == "NANCON"
    assert output.variable == "discharge"


def test_the_file_departs_from_the_recipe_on_the_estimator_and_the_engine(
    calibration__reference_replication,
) -> None:
    moved = {
        item["key"]: item["here"]
        for item in protocol_options_away_from_the_recipe(
            "matching_hydrographic_network", calibration__reference_replication.protocol
        )
    }
    assert moved["steady_metric"] == "distance_mean"
    assert moved["steady_method"] == "scipy_nelder_mead"


def test_the_uncertainty_interval_costs_no_extra_run(calibration__reference_replication) -> None:
    assert calibration__reference_replication.uncertainty is not None
    assert calibration__reference_replication.uncertainty.method == "cost_profile"


def test_the_two_stage_card_is_asked_for_by_its_current_name() -> None:
    text = REFERENCE.read_text(encoding="utf-8")
    assert "matching_hydrographic_network_card" in text
    assert "abherve_two_stage_card" not in text
