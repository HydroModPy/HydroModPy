"""Support verdict of a calibration protocol on a solver backend.

A protocol declares the observables its stages read. The verdict is derived from
what the backend serves and from the tested entries of a data file. A backend the
registry cannot build has no refusal of its own, so its verdict is untested.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from hydromodpy.calibration.protocols.base import protocol_support, support_by_backend
from hydromodpy.calibration.protocols.registry import get_protocol


@dataclass(frozen=True)
class DischargeOnlyProtocol:
    name: str = "a_protocol_nobody_ran"
    declared_observables: tuple[str, ...] = ("discharge",)


UNTESTED = [
    pytest.param(DischargeOnlyProtocol(), "boussinesq", id="narrow protocol on a capable backend"),
    pytest.param(
        get_protocol("matching_hydrographic_network"), "a_backend_nobody_shipped", id="unknown name"
    ),
]


@pytest.mark.parametrize(("protocol", "backend"), UNTESTED)
def test_untested_verdict(protocol, backend) -> None:
    verdict = protocol_support(protocol, backend)

    assert verdict.verdict == "expected_untested"
    assert verdict.reason is None


def test_support_of_a_plugin_backend() -> None:
    protocol = get_protocol("matching_hydrographic_network")

    support = support_by_backend(protocol, ["a_plugin_backend_of_a_session"])

    assert support["a_plugin_backend_of_a_session"] == "expected_untested"
