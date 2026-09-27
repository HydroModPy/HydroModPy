"""A published calibration method has to be nameable, not retyped.

The two-stage stream-network calibration was reachable only by hand-writing the
whole assembly: two phases, their engines and budgets, the regime and time-grid
overrides that make one stage steady and the other transient, and the objective
block wiring. A hundred lines of TOML that carry no site information, that every
project copied, and that no file identified as a published method.

The protocol names it. The file states what belongs to the site, the protocol
writes the assembly, and the run records which method produced it and what to
cite. It says each stage's regime, and ``runners/phase_regime.py`` writes what
the regime means (``test_phase_regime.py``).
"""

from __future__ import annotations

import copy
import datetime

import pytest

from hydromodpy.calibration.config import CalibPhaseDecl
from hydromodpy.calibration.protocols import (
    available_protocols,
    expand_calibration_protocol,
    get_protocol,
)
from hydromodpy.calibration.runners.phase_regime import phase_overrides

_SIMULATION = {
    "time": {
        "start_datetime": "1995-01-01",
        "end_datetime": "2020-12-31",
        "step_value": 1,
        "step_unit": "day",
    }
}


def _doc(**calibration: object) -> dict[str, object]:
    # deepcopy and not dict(): a shallow copy shares the nested [time] table,
    # so a test that writes into ``doc["simulation"]["time"]`` writes into
    # _SIMULATION itself and poisons every later test of the process.
    # ``_steady(1995, ...)`` below does exactly that, on purpose, to check a
    # refusal. Under xdist the classes of one module land on different workers,
    # so the damage showed up as an intermittent red in unrelated tests.
    return {
        "simulation": copy.deepcopy(_SIMULATION),
        "data": {"hydrometry": {"sources": [{"station_ids": ["NANCON"]}]}},
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
        assert steady["regime"] == "steady"
        assert "overrides" not in steady
        assert steady["freeze_on_success"] is True

    def test_the_first_stage_collapses_the_record_into_one_period(self) -> None:
        """A steady regime on an untouched daily grid is 9497 steady solves."""
        doc = _doc()
        steady = expand_calibration_protocol(doc)["calibration"]["phases"][0]

        overrides = phase_overrides(CalibPhaseDecl.model_validate(steady), doc)

        assert overrides["simulation.time.step_unit"] == "day"
        assert overrides["simulation.time.step_value"] == 9497

    def test_a_steady_window_it_is_given_reaches_the_stage(self) -> None:
        window = {"start": "2001-01-01", "end": "2001-12-31"}
        steady = expand_calibration_protocol(
            _doc(protocol={"name": "matching_hydrographic_network", "steady_window": window})
        )["calibration"]["phases"][0]

        assert steady["steady_window"] == window
        assert "steady_window" in steady["description"]

    def test_the_second_stage_moves_the_storage_on_the_hydrograph(self) -> None:
        transient = expand_calibration_protocol(_doc())["calibration"]["phases"][1]

        assert transient["parameters"] == ["Sy"]
        assert "variable" not in transient
        assert "objective" not in transient
        assert transient["objective_blocks"] == ["hydrograph"]
        assert transient["depends_on"] == "steady_conductivity"
        assert transient["regime"] == "transient"
        assert "overrides" not in transient

    def test_the_second_stage_s_cost_is_a_point_output_that_observes_the_gauge(self) -> None:
        expanded = expand_calibration_protocol(_doc())["calibration"]

        output = expanded["outputs"]["hydrograph"]
        assert output["support"] == "point"
        assert output["variable"] == "discharge"
        assert output["observes"] == "NANCON"

        block = next(b for b in expanded["objective_blocks"] if b["name"] == "hydrograph")
        assert block["metric"] == "nse_log"
        assert block["uses_outputs"] == ["hydrograph"]

    def test_a_sealed_hydrograph_output_with_every_default_filled_in_still_reads_back(
        self,
    ) -> None:
        """A persisted document spells out every default the fresh write leaves out."""
        from hydromodpy.calibration.config import CalibOutputPoint

        once = expand_calibration_protocol(_doc())["calibration"]
        dumped = CalibOutputPoint.model_validate(once["outputs"]["hydrograph"]).model_dump(
            mode="json", exclude_none=True
        )
        assert len(dumped) > 3  # more than variable/support/observes: real defaults filled in

        doc = _doc()
        doc["calibration"]["outputs"]["hydrograph"] = dumped

        expanded = expand_calibration_protocol(doc)["calibration"]

        assert expanded["outputs"]["hydrograph"]["observes"] == "NANCON"

    def test_a_genuinely_different_hydrograph_output_is_still_refused(self) -> None:
        doc = _doc()
        doc["calibration"]["outputs"]["hydrograph"] = {
            "variable": "head",
            "support": "point",
            "x": 1.0,
            "y": 2.0,
        }

        with pytest.raises(ValueError, match="reserved"):
            expand_calibration_protocol(doc)

    def test_it_wires_the_network_output_into_an_objective_block(self) -> None:
        expanded = expand_calibration_protocol(_doc())["calibration"]

        blocks = expanded["objective_blocks"]
        assert len(blocks) == 2
        assert blocks[0]["metric"] == "distance_gap"
        assert blocks[0]["uses_outputs"] == ["seepage_network"]
        assert expanded["phases"][0]["objective_blocks"] == [blocks[0]["name"]]

    def test_no_storage_means_no_hydrograph_output_either(self) -> None:
        doc = _doc(protocol={"name": "matching_hydrographic_network", "storage": None})
        del doc["calibration"]["parameters"]["Sy"]

        expanded = expand_calibration_protocol(doc)["calibration"]

        assert "hydrograph" not in (expanded.get("outputs") or {})
        assert len(expanded["objective_blocks"]) == 1

    def test_an_explicit_station_wins_over_the_loaded_one(self) -> None:
        doc = _doc(
            protocol={"name": "matching_hydrographic_network", "observed_station_id": "OTHER"}
        )
        doc["data"]["hydrometry"]["sources"][0]["station_ids"] = ["NANCON", "OTHER"]

        expanded = expand_calibration_protocol(doc)["calibration"]

        assert expanded["outputs"]["hydrograph"]["observes"] == "OTHER"

    def test_an_ambiguous_station_falls_back_to_the_single_metric_route(self) -> None:
        """Several stations named: not B11's to guess, so it keeps the old route."""
        doc = _doc()
        doc["data"]["hydrometry"]["sources"][0]["station_ids"] = ["NANCON", "OTHER"]

        transient = expand_calibration_protocol(doc)["calibration"]["phases"][1]

        assert transient["variable"] == "discharge"
        assert transient["objective"] == "nse_log"
        assert "objective_blocks" not in transient

    def test_a_source_discovered_at_load_time_falls_back_too(self) -> None:
        """No 'station_ids' at all (an 'extent' or a 'mask_path'): not knowable here."""
        doc = _doc()
        doc["data"]["hydrometry"]["sources"][0] = {"extent": [0, 0, 1, 1]}

        expanded = expand_calibration_protocol(doc)["calibration"]

        transient = expanded["phases"][1]
        assert transient["variable"] == "discharge"
        assert "objective_blocks" not in transient
        assert "hydrograph" not in (expanded.get("outputs") or {})

    def test_no_loaded_station_falls_back_too(self) -> None:
        doc = _doc()
        doc["data"] = {}

        expanded = expand_calibration_protocol(doc)["calibration"]

        transient = expanded["phases"][1]
        assert transient["variable"] == "discharge"
        assert "objective_blocks" not in transient
        assert "hydrograph" not in (expanded.get("outputs") or {})

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

    def test_a_steady_stage_without_a_time_window_is_refused_when_it_runs(self) -> None:
        """The protocol writes the regime; the window is read where the regime is."""
        doc = _doc()
        doc["simulation"] = {}
        steady = expand_calibration_protocol(doc)["calibration"]["phases"][0]

        with pytest.raises(ValueError, match="simulation.time"):
            phase_overrides(CalibPhaseDecl.model_validate(steady), doc)


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
        doc = {"simulation": copy.deepcopy(_SIMULATION)}

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
        tampered[0]["max_iter"] = 21

        with pytest.raises(ValueError, match="phases"):
            expand_calibration_protocol(_doc(phases=tampered))

    def test_a_file_that_is_broken_twice_still_gets_the_actionable_message(self) -> None:
        """Expanding now runs first, and its own failure must not bury the advice."""
        once = expand_calibration_protocol(_doc())
        doc = _doc(phases=once["calibration"]["phases"])
        del doc["calibration"]["parameters"]["K"]

        with pytest.raises(ValueError) as caught:
            expand_calibration_protocol(doc)

        assert "Keep one" in str(caught.value)
        assert "'K'" in str(caught.value)

    def test_only_the_section_the_file_declares_is_compared(self) -> None:
        """Declaring the phases and not the blocks is not a contradiction."""
        once = expand_calibration_protocol(_doc())

        expanded = expand_calibration_protocol(_doc(phases=once["calibration"]["phases"]))

        assert (
            expanded["calibration"]["objective_blocks"] == (once["calibration"]["objective_blocks"])
        )


def _sealed_before_the_regime(start: str = "1995-01-01", end: str = "2020-12-31", days: int = 9497):
    """The stages the protocol wrote for ``_doc()`` before phases said their regime.

    Produced by the expansion at 41c8e07e1 and trimmed to the keys it wrote: the
    regime is five override paths, and the steady description embeds the dates.
    """
    return [
        {
            "name": "steady_conductivity",
            "description": "Match the simulated seepage network to the mapped one by "
            f"moving K, steady state over {start}..{end}.",
            "method": "bisection",
            "max_iter": 20,
            "parameters": ["K"],
            "objective_blocks": ["network_extension"],
            "freeze_on_success": True,
            "overrides": {
                "flow.flow_regime": "steady",
                "simulation.time.start_datetime": start,
                "simulation.time.end_datetime": end,
                "simulation.time.step_unit": "day",
                "simulation.time.step_value": days,
            },
        },
        {
            "name": "transient_storage",
            "description": "Read Sy from the observed hydrograph, K frozen, transient.",
            "method": "scipy_nelder_mead",
            "max_iter": 120,
            "parameters": ["Sy"],
            "variable": "discharge",
            "objective": "nse_log",
            "depends_on": "steady_conductivity",
            "overrides": {"flow.flow_regime": "transient"},
        },
    ]


def _sealed_doc(**calibration: object) -> dict[str, object]:
    """``_doc()`` as a run sealed then dumps it: the protocol table carries its defaults.

    Only the one that has moved since matters here: ``steady_max_iter`` was 20
    when these stages were sealed, and a dumped file says so.
    """
    declared = calibration.pop("protocol", {"name": "matching_hydrographic_network"})
    protocol = {"steady_max_iter": 20, **dict(declared)}
    return _doc(protocol=protocol, **calibration)


class TestItReadsBackARunSealedBeforeTheRegime:
    """A run sealed before phases said their regime has to stay replayable.

    ``hmp run <ref> --resume`` reads the sealed file through
    ``HydroModPyConfig.from_toml``, which compares its stages with what the
    protocol writes today.
    """

    def test_its_stages_are_read_as_the_regimes_they_state(self) -> None:
        expanded = expand_calibration_protocol(_sealed_doc(phases=_sealed_before_the_regime()))

        steady, transient = expanded["calibration"]["phases"]
        assert steady["regime"] == "steady"
        assert transient["regime"] == "transient"
        assert "overrides" not in steady

    def test_it_reloads_with_every_default_filled_in(self) -> None:
        """A dumped file carries the validated stages, defaults filled."""
        dumped = [
            CalibPhaseDecl.model_validate(phase).model_dump(mode="json")
            for phase in _sealed_before_the_regime()
        ]

        expanded = expand_calibration_protocol(_sealed_doc(phases=dumped))

        assert [phase["regime"] for phase in expanded["calibration"]["phases"]] == [
            "steady",
            "transient",
        ]

    def test_a_stage_whose_regime_contradicts_the_protocol_is_refused(self) -> None:
        sealed = _sealed_before_the_regime()
        sealed[0]["overrides"] = {"flow.flow_regime": "transient"}

        with pytest.raises(ValueError, match="phases"):
            expand_calibration_protocol(_sealed_doc(phases=sealed))

    def test_a_window_the_protocol_names_has_to_be_the_sealed_one(self) -> None:
        window = {"start": "2001-01-01", "end": "2001-12-31"}
        protocol = {"name": "matching_hydrographic_network", "steady_window": window}

        same = _sealed_before_the_regime("2001-01-01", "2001-12-31", 365)
        expanded = expand_calibration_protocol(_sealed_doc(protocol=protocol, phases=same))
        assert expanded["calibration"]["phases"][0]["steady_window"] == window

        with pytest.raises(ValueError, match="phases"):
            expand_calibration_protocol(
                _sealed_doc(protocol=protocol, phases=_sealed_before_the_regime())
            )

    def test_a_transient_stage_scored_by_variable_and_objective_still_reads_back(self) -> None:
        """Before B11 the transient stage's cost lived in ``variable`` + ``objective``."""
        sealed = _sealed_before_the_regime()
        assert sealed[1]["variable"] == "discharge"
        assert sealed[1]["objective"] == "nse_log"

        expanded = expand_calibration_protocol(_sealed_doc(phases=sealed))["calibration"]

        assert expanded["phases"][1]["objective_blocks"] == ["hydrograph"]

    def test_a_transient_objective_that_no_longer_matches_is_refused(self) -> None:
        """A real drift in the criterion is not this legacy spelling."""
        sealed = _sealed_before_the_regime()
        sealed[1]["objective"] = "kge"

        with pytest.raises(ValueError, match="phases"):
            expand_calibration_protocol(_sealed_doc(phases=sealed))

    def test_a_sealed_objective_blocks_list_short_one_block_still_reads_back(self) -> None:
        """A run sealed before B11 also declares only the network block.

        The cost span two sections: the phase says ``variable``/``objective``, and
        ``[calibration.objective_blocks]`` never had a hydrograph entry to match.
        Reading the two back together must not refuse the file as a contradiction.
        """
        sealed_blocks = [
            {
                "name": "network_extension",
                "metric": "distance_gap",
                "uses_outputs": ["seepage_network"],
            }
        ]

        expanded = expand_calibration_protocol(
            _sealed_doc(phases=_sealed_before_the_regime(), objective_blocks=sealed_blocks)
        )["calibration"]

        assert [block["name"] for block in expanded["objective_blocks"]] == [
            "network_extension",
            "hydrograph",
        ]

    def test_a_sealed_stage_still_reads_back_when_the_station_is_still_not_known(self) -> None:
        """The other legacy spelling: still single-metric today, so nothing to fold."""
        doc = _sealed_doc(phases=_sealed_before_the_regime())
        doc["data"]["hydrometry"]["sources"][0]["station_ids"] = ["NANCON", "OTHER"]

        expanded = expand_calibration_protocol(doc)["calibration"]

        transient = expanded["phases"][1]
        assert transient["variable"] == "discharge"
        assert "objective_blocks" not in transient


class TestOneSpellingOfAnInstant:
    """A TOML file writes a date three legal ways and they have to agree.

    ``start_datetime = 2000-01-01`` parses as a date, ``2000-01-01T00:00:00`` as
    a datetime, a quoted value stays a string. Rendering them straight into the
    stage description and the time overrides made the assembly depend on the
    spelling, so a file re-read from its own dump expanded to different stages.
    The stages now say the regime and read no date at all; the overrides it
    writes are checked in ``test_phase_regime.py``.
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
