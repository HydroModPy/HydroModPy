"""A number that informed a decision must be replayable with the recipe of its era.

Naming a method is not enough for that. A recipe improves, and a file that ran
version 1.2 and silently gets 1.3 has lost the only guarantee a pin exists to
give. So the version is declared, a file may pin one the table holds, a pin writes
the values of its version for every key the file leaves empty, and any other pin
is refused rather than approximated.

Two more things the record has to carry, for the same reason. Where this
implementation departs from its publication, because a protocol that silently
improves on its paper is no longer that paper's method. And what running it on
each backend is actually worth, in a vocabulary that separates "a case runs this"
from "nothing forbids it and nobody tried".
"""

from __future__ import annotations

import copy

import pytest

from hydromodpy.calibration.config import (
    CalibOutputNetwork,
    CalibrationConfig,
    MatchingHydrographicNetworkOptions,
)
from hydromodpy.calibration.protocols import (
    available_protocols,
    expand_calibration_protocol,
    get_protocol,
    protocol_record,
)
from hydromodpy.calibration.protocols.matching_hydrographic_network import DEFAULTS_BY_VERSION
from hydromodpy.calibration.runners.cli_runner import _protocol_of_session
from hydromodpy.core.stream_criterion_defaults import STREAM_CRITERION_DEFAULTS

NAME = "matching_hydrographic_network"

_SIMULATION = {
    "time": {
        "start_datetime": "1995-01-01",
        "end_datetime": "2020-12-31",
        "step_value": 1,
        "step_unit": "day",
    }
}


def _doc(protocol: object) -> dict[str, object]:
    # deepcopy and not dict(): a shallow copy shares the nested [time] table,
    # so a test writing into ``doc["simulation"]["time"]`` would write into
    # _SIMULATION itself. The sister module lost six tests to that, under an
    # xdist distribution that happened to run the poisoning class first.
    return {
        "simulation": copy.deepcopy(_SIMULATION),
        "data": {"hydrometry": {"sources": [{"station_ids": ["NANCON"]}]}},
        "calibration": {
            "protocol": protocol,
            "parameters": {
                "K": {"bounds": [1e-8, 1e-2], "search_space": "log"},
                "Sy": {"bounds": [1e-4, 0.5], "search_space": "log"},
            },
            "outputs": {
                "seepage_network": {
                    "support": "network",
                    "stream_geometry_path": "nancon.gpkg",
                }
            },
        },
    }


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
        expanded = expand_calibration_protocol(_doc({"name": NAME, "version": version}))

        assert expanded["calibration"]["phases"]

    def test_a_mismatched_pin_is_refused_rather_than_approximated(self) -> None:
        with pytest.raises(ValueError, match="carries 1.2, 1.3.*replayable"):
            expand_calibration_protocol(_doc({"name": NAME, "version": "0.9"}))

    def test_the_released_1_1_is_refused_now_that_its_defaults_moved(self) -> None:
        """v2.0.0a1 shipped 1.1; the fill, the spin-up year and the length bound moved since."""
        with pytest.raises(ValueError, match="replayable"):
            expand_calibration_protocol(
                _doc({"name": "matching_hydrographic_network", "version": "1.1"})
            )

    def test_no_pin_runs_what_is_installed(self) -> None:
        expanded = expand_calibration_protocol(_doc("matching_hydrographic_network"))

        assert expanded["calibration"]["phases"]


def _network_output_of(protocol: object, **written: object) -> dict[str, object]:
    doc = _doc(protocol)
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
        doc = _doc({"name": NAME, "version": "1.2"})

        expand_calibration_protocol(doc)

        assert "observed_rasterization" not in doc["calibration"]["outputs"]["seepage_network"]

    def test_a_dump_of_the_output_reloads_as_it_ran(self) -> None:
        """A sealed run writes every key: the expansion has nothing left to fill."""
        doc = _doc({"name": NAME, "version": "1.2"})
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
        doc = expand_calibration_protocol(_doc(protocol))
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
        assert departures["steady_recharge_window"].always is True
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
        from hydromodpy.calibration.config import MatchingHydrographicNetworkOptions

        declared = get_protocol("matching_hydrographic_network").adjustable
        exposed = set(MatchingHydrographicNetworkOptions.model_fields) - {"name", "version"}

        assert declared == exposed
