"""A number that informed a decision must be replayable with the recipe of its era.

Naming a method is not enough for that. A recipe improves, and a file that ran
version 1.0 and silently gets 1.1 has lost the only guarantee a pin exists to
give. So the version is declared, a file may pin it, and a mismatch is refused
rather than approximated.

Two more things the record has to carry, for the same reason. Where this
implementation departs from its publication, because a protocol that silently
improves on its paper is no longer that paper's method. And what running it on
each backend is actually worth, in a vocabulary that separates "a case runs this"
from "nothing forbids it and nobody tried".
"""

from __future__ import annotations

import copy

import pytest

from hydromodpy.calibration.protocols import (
    available_protocols,
    expand_calibration_protocol,
    get_protocol,
    protocol_record,
)

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
        "calibration": {
            "protocol": protocol,
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
        },
    }


class TestTheVersion:
    def test_every_protocol_declares_one(self) -> None:
        for name in available_protocols():
            assert get_protocol(name).version

    def test_the_record_carries_it(self) -> None:
        assert protocol_record("matching_hydrographic_network")["version"] == "1.0"

    def test_a_matching_pin_runs(self) -> None:
        expanded = expand_calibration_protocol(
            _doc({"name": "matching_hydrographic_network", "version": "1.0"})
        )

        assert expanded["calibration"]["phases"]

    def test_a_mismatched_pin_is_refused_rather_than_approximated(self) -> None:
        with pytest.raises(ValueError, match="replayable"):
            expand_calibration_protocol(
                _doc({"name": "matching_hydrographic_network", "version": "0.9"})
            )

    def test_no_pin_runs_what_is_installed(self) -> None:
        expanded = expand_calibration_protocol(_doc("matching_hydrographic_network"))

        assert expanded["calibration"]["phases"]


class TestTheSupportMatrix:
    def test_it_uses_a_closed_vocabulary(self) -> None:
        support = protocol_record("matching_hydrographic_network")["support"]

        assert set(support.values()) <= {"tested", "expected_untested", "unsupported"}

    def test_it_names_every_flow_backend(self) -> None:
        support = protocol_record("matching_hydrographic_network")["support"]

        assert {"modflow6", "modflow_nwt", "boussinesq"} <= set(support)

    def test_it_separates_a_tested_backend_from_an_untried_one(self) -> None:
        """Publishing "supported" for both would be the dishonest simplification."""
        support = protocol_record("matching_hydrographic_network")["support"]

        assert support["modflow6"] == "tested"
        assert support["modflow_nwt"] == "expected_untested"


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

    def test_the_reference_values_quote_the_publication(self) -> None:
        values = protocol_record("matching_hydrographic_network")["reference_values"]

        assert "roptim_max" in values
        assert "Eq. 4" in values["roptim_max"]


class TestWhatMayBeAdjusted:
    def test_the_whitelist_matches_what_the_options_expose(self) -> None:
        """A setting outside it would be a variant claiming to be the method."""
        from hydromodpy.calibration.protocols.matching_hydrographic_network import (
            MatchingHydrographicNetworkOptions,
        )

        declared = get_protocol("matching_hydrographic_network").adjustable
        exposed = set(MatchingHydrographicNetworkOptions.model_fields) - {"name", "version"}

        assert declared == exposed
