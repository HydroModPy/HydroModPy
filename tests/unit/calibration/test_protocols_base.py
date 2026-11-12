"""Tests of `protocols.base`: the contract of a protocol and its support verdict.

From test_the_support_verdict_of_a_protocol.py
The support verdict of a protocol used to be a table the protocol wrote by hand,
keyed by backend name. Such a table could go stale without anything failing, and
a backend that renamed itself left it silent. The verdict is derived now: a
protocol declares the observables its stages read, the tested entries live in a
data file beside the protocols, and a refusal is the backend's own answer.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from hydromodpy.calibration.protocols.base import (
    ProtocolSupport,
    protocol_support,
    support_by_backend,
)
from hydromodpy.calibration.protocols.registry import get_protocol

pytestmark = pytest.mark.fast


@dataclass(frozen=True)
class _ReducedProtocol:
    """A protocol reduced to what the support verdict reads."""

    name: str = "a_protocol_of_the_tests"
    declared_observables: tuple[str, ...] = ("release_flux", "discharge")


@dataclass(frozen=True)
class _DischargeOnlyProtocol:
    """The honest middle: a protocol of one series, on a backend nobody ran it on."""

    name: str = "a_protocol_nobody_ran"
    declared_observables: tuple[str, ...] = ("discharge",)


def test_a_backend_that_serves_every_observable_a_narrow_protocol_needs_is_said_untested() -> None:
    """Nothing forbids it and nobody has run it: the honest middle of the vocabulary."""
    verdict = protocol_support(_DischargeOnlyProtocol(), "boussinesq")

    assert verdict.verdict == "expected_untested"
    assert verdict.reason is None


def test_a_name_nobody_shipped_stays_expected_untested() -> None:
    """A backend the registry cannot build has no refusal of its own to speak."""
    verdict = protocol_support(
        get_protocol("matching_hydrographic_network"), "a_backend_nobody_shipped"
    )

    assert verdict.verdict == "expected_untested"
    assert verdict.reason is None


def test_the_support_of_the_backend_that_ran_is_in_the_record() -> None:
    """A record carries the verdict of a backend that is not one this build ships."""
    protocol = get_protocol("matching_hydrographic_network")

    support = support_by_backend(protocol, ["a_plugin_backend_of_a_session"])

    assert support["a_plugin_backend_of_a_session"] == "expected_untested"
