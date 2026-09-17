"""A published calibration method has to be nameable, not retyped.

The two-stage stream-network calibration was reachable only by hand-writing the
whole assembly: two phases, their engines and budgets, the regime and time-grid
overrides that make one stage steady and the other transient, and the objective
block wiring. A hundred lines of TOML that carry no site information, that every
project copied, and that no file identified as a published method.

The protocol names it. The file states what belongs to the site, the protocol
writes the assembly, and the run records which method produced it and what to
cite.
"""

from __future__ import annotations

import copy
import datetime

import pytest

from hydromodpy.calibration.protocols import (
    available_protocols,
    expand_calibration_protocol,
    get_protocol,
)

_SIMULATION = {
    "time": {
        "start_datetime": "1995-01-01",
        "end_datetime": "2020-12-31",
        "step_value": 1,
        "step_unit": "day",
    }
}


def _doc(**calibration: object) -> dict[str, object]:
    return {
        "simulation": dict(_SIMULATION),
        "calibration": {
            "protocol": "matching_hydrographic_network",
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


class TestTheRegistry:
    def test_the_protocol_is_registered_under_its_own_name(self) -> None:
        assert "matching_hydrographic_network" in available_protocols()

    def test_an_unknown_name_is_refused_with_the_list(self) -> None:
        with pytest.raises(ValueError) as caught:
            get_protocol("abherve")

        assert "matching_hydrographic_network" in str(caught.value)

    def test_the_protocol_names_what_to_cite(self) -> None:
        protocol = get_protocol("matching_hydrographic_network")

        dois = {reference.doi for reference in protocol.references}
        assert "10.5194/hess-27-3221-2023" in dois
        assert all(reference.year >= 2023 for reference in protocol.references)

    def test_the_protocol_says_what_it_does(self) -> None:
        protocol = get_protocol("matching_hydrographic_network")

        assert protocol.summary.strip()
        assert len(protocol.stages) == 2


class TestWhatItWrites:
    def test_it_writes_the_two_stages(self) -> None:
        expanded = expand_calibration_protocol(_doc())

        phases = expanded["calibration"]["phases"]
        assert [phase["name"] for phase in phases] == ["steady_conductivity", "transient_storage"]

    def test_the_first_stage_moves_the_conductivity_alone_in_steady_state(self) -> None:
        phases = expand_calibration_protocol(_doc())["calibration"]["phases"]

        steady = phases[0]
        assert steady["parameters"] == ["K"]
        assert steady["overrides"]["flow.flow_regime"] == "steady"
        assert steady["freeze_on_success"] is True

    def test_the_first_stage_collapses_the_record_into_one_period(self) -> None:
        """A steady regime on an untouched daily grid is 9497 steady solves."""
        steady = expand_calibration_protocol(_doc())["calibration"]["phases"][0]

        assert steady["overrides"]["simulation.time.step_unit"] == "day"
        assert steady["overrides"]["simulation.time.step_value"] == 9497

    def test_the_second_stage_moves_the_storage_on_the_hydrograph(self) -> None:
        transient = expand_calibration_protocol(_doc())["calibration"]["phases"][1]

        assert transient["parameters"] == ["Sy"]
        assert transient["variable"] == "discharge"
        assert transient["objective"] == "nse_log"
        assert transient["depends_on"] == "steady_conductivity"
        assert transient["overrides"]["flow.flow_regime"] == "transient"

    def test_it_wires_the_network_output_into_an_objective_block(self) -> None:
        expanded = expand_calibration_protocol(_doc())["calibration"]

        blocks = expanded["objective_blocks"]
        assert len(blocks) == 1
        assert blocks[0]["metric"] == "distance_gap"
        assert blocks[0]["uses_outputs"] == ["seepage_network"]
        assert expanded["phases"][0]["objective_blocks"] == [blocks[0]["name"]]

    def test_the_published_engine_is_the_default_and_stays_replaceable(self) -> None:
        assert expand_calibration_protocol(_doc())["calibration"]["phases"][0]["method"] == (
            "bisection"
        )

        swapped = expand_calibration_protocol(
            _doc(
                protocol={
                    "name": "matching_hydrographic_network",
                    "steady_method": "optuna",
                    "steady_metric": "distance_mean",
                    "steady_max_iter": 40,
                }
            )
        )
        steady = swapped["calibration"]["phases"][0]
        assert steady["method"] == "optuna"
        assert steady["max_iter"] == 40
        assert swapped["calibration"]["objective_blocks"][0]["metric"] == "distance_mean"


class TestWhatItRefuses:
    def test_a_file_that_writes_its_own_stages_is_refused(self) -> None:
        """The protocol writes the stages; declaring both is a contradiction."""
        with pytest.raises(ValueError, match="phases"):
            expand_calibration_protocol(_doc(phases=[{"name": "mine", "parameters": ["K"]}]))

    def test_a_missing_conductivity_parameter_is_named(self) -> None:
        doc = _doc()
        del doc["calibration"]["parameters"]["K"]

        with pytest.raises(ValueError, match="'K'"):
            expand_calibration_protocol(doc)

    def test_a_missing_network_output_is_named(self) -> None:
        doc = _doc()
        doc["calibration"]["outputs"] = {}

        with pytest.raises(ValueError, match="network"):
            expand_calibration_protocol(doc)

    def test_two_network_outputs_have_to_be_told_apart(self) -> None:
        doc = _doc()
        doc["calibration"]["outputs"]["other_network"] = {
            "support": "network",
            "stream_geometry_path": "other.gpkg",
        }

        with pytest.raises(ValueError, match="network_output"):
            expand_calibration_protocol(doc)

    def test_a_steady_stage_without_a_time_window_is_refused(self) -> None:
        doc = _doc()
        doc["simulation"] = {}

        with pytest.raises(ValueError, match="simulation.time"):
            expand_calibration_protocol(doc)


class TestNamingTheRoles:
    def test_the_parameter_names_are_the_file_s_own(self) -> None:
        doc = _doc(
            protocol={
                "name": "matching_hydrographic_network",
                "conductivity": "hk_bedrock",
                "storage": "sy_bedrock",
            }
        )
        doc["calibration"]["parameters"] = {
            "hk_bedrock": {"bounds": [1e-8, 1e-2], "transform": "log"},
            "sy_bedrock": {"bounds": [1e-4, 0.5], "transform": "log"},
        }

        phases = expand_calibration_protocol(doc)["calibration"]["phases"]

        assert phases[0]["parameters"] == ["hk_bedrock"]
        assert phases[1]["parameters"] == ["sy_bedrock"]

    def test_dropping_the_storage_leaves_the_network_stage_alone(self) -> None:
        """The network criterion is a method in its own right, not half of one."""
        doc = _doc(
            protocol={"name": "matching_hydrographic_network", "storage": None},
        )
        del doc["calibration"]["parameters"]["Sy"]

        phases = expand_calibration_protocol(doc)["calibration"]["phases"]

        assert [phase["name"] for phase in phases] == ["steady_conductivity"]


class TestItLeavesTheRestAlone:
    def test_a_document_without_a_protocol_is_returned_unchanged(self) -> None:
        doc = {"calibration": {"method": "grid", "max_iter": 10}}

        assert expand_calibration_protocol(doc) == doc

    def test_a_document_without_a_calibration_is_returned_unchanged(self) -> None:
        doc = {"simulation": dict(_SIMULATION)}

        assert expand_calibration_protocol(doc) == doc

    def test_the_input_document_is_not_mutated(self) -> None:
        doc = _doc()

        expand_calibration_protocol(doc)

        assert "phases" not in doc["calibration"]


class TestItReadsBackWhatItWrote:
    """A run seals its own configuration and is re-read from it.

    That file carries the ``protocol`` table *and* the stages the table
    produced, on purpose: the run records which method it followed and what that
    method assembled. Reloading it was refused as a contradiction, which made
    every staged project unable to round-trip through its own dumpers.
    """

    def test_the_stages_it_wrote_are_not_a_contradiction(self) -> None:
        once = expand_calibration_protocol(_doc())

        twice = expand_calibration_protocol(once)

        assert twice["calibration"]["phases"] == once["calibration"]["phases"]
        assert twice["calibration"]["objective_blocks"] == once["calibration"]["objective_blocks"]

    def test_stages_carrying_every_default_are_still_its_own(self) -> None:
        """A dumped file carries the validated stages, defaults filled in."""
        from hydromodpy.calibration.config import CalibPhaseDecl

        once = expand_calibration_protocol(_doc())
        validated = [
            CalibPhaseDecl.model_validate(phase).model_dump(mode="json")
            for phase in once["calibration"]["phases"]
        ]
        doc = _doc(phases=validated, objective_blocks=once["calibration"]["objective_blocks"])

        expanded = expand_calibration_protocol(doc)

        assert [phase["name"] for phase in expanded["calibration"]["phases"]] == [
            "steady_conductivity",
            "transient_storage",
        ]

    def test_a_stage_that_is_not_the_one_it_writes_is_still_refused(self) -> None:
        once = expand_calibration_protocol(_doc())
        tampered = copy.deepcopy(once["calibration"]["phases"])
        tampered[0]["max_iter"] = tampered[0]["max_iter"] + 1

        with pytest.raises(ValueError, match="phases"):
            expand_calibration_protocol(_doc(phases=tampered))

    def test_only_the_section_the_file_declares_is_compared(self) -> None:
        """Declaring the phases and not the blocks is not a contradiction."""
        once = expand_calibration_protocol(_doc())

        expanded = expand_calibration_protocol(_doc(phases=once["calibration"]["phases"]))

        assert (
            expanded["calibration"]["objective_blocks"] == (once["calibration"]["objective_blocks"])
        )


class TestOneSpellingOfAnInstant:
    """A TOML file writes a date three legal ways and they have to agree.

    ``start_datetime = 2000-01-01`` parses as a date, ``2000-01-01T00:00:00`` as
    a datetime, a quoted value stays a string. Rendering them straight into the
    stage description and the time overrides made the assembly depend on the
    spelling, so a file re-read from its own dump expanded to different stages.
    """

    @staticmethod
    def _steady(start: object, end: object) -> dict:
        doc = _doc()
        doc["simulation"]["time"]["start_datetime"] = start
        doc["simulation"]["time"]["end_datetime"] = end
        return expand_calibration_protocol(doc)["calibration"]["phases"][0]

    def test_a_date_a_datetime_and_a_string_write_the_same_stage(self) -> None:
        as_date = self._steady(datetime.date(1995, 1, 1), datetime.date(2020, 12, 31))
        as_datetime = self._steady(datetime.datetime(1995, 1, 1), datetime.datetime(2020, 12, 31))
        as_string = self._steady("1995-01-01", "2020-12-31")

        assert as_date == as_datetime == as_string

    def test_a_bound_on_midnight_is_written_as_its_date(self) -> None:
        overrides = self._steady("1995-01-01", "2020-12-31")["overrides"]

        assert overrides["simulation.time.start_datetime"] == "1995-01-01"
        assert overrides["simulation.time.end_datetime"] == "2020-12-31"

    def test_a_bound_that_is_not_midnight_keeps_its_time(self) -> None:
        overrides = self._steady("1995-01-01T06:00:00", "2020-12-31")["overrides"]

        assert overrides["simulation.time.start_datetime"] == "1995-01-01T06:00:00"

    def test_a_span_that_is_not_an_instant_is_named(self) -> None:
        with pytest.raises(ValueError, match="simulation.time.start_datetime"):
            self._steady("not a date", "2020-12-31")
