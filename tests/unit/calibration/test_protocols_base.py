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
    backends_tested_in_this_repository,
    protocol_support,
    support_by_backend,
)
from hydromodpy.calibration.protocols.registry import get_protocol
from hydromodpy.solver.base.registry import solvers

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


def test_the_shipped_protocol_declares_the_observables_its_stages_read() -> None:
    """One declaration, the same names a backend answers in ``declared_observables``."""
    protocol = get_protocol("matching_hydrographic_network")

    assert protocol.declared_observables == ("release_flux", "discharge")


def test_a_backend_that_declares_one_needed_observable_unavailable_is_unsupported() -> None:
    """Boussinesq cannot serve the per-cell release flux, and the verdict says why."""
    verdict = protocol_support(get_protocol("matching_hydrographic_network"), "boussinesq")

    assert verdict.verdict == "unsupported"
    assert verdict.reason is not None
    # The reason is the backend's own: it says which observable it cannot serve
    # and what to use instead, so the sentence never guesses.
    assert "per-cell saturation excess" in verdict.reason
    assert "MODFLOW backend" in verdict.reason


def test_a_backend_the_tested_table_names_is_tested_without_asking_an_adapter() -> None:
    """MODFLOW 6 and MODFLOW-NWT are read from the tested table, and from nothing else."""
    protocol = get_protocol("matching_hydrographic_network")

    for backend in ("modflow6", "modflow_nwt"):
        verdict = protocol_support(protocol, backend)
        assert verdict.verdict == "tested"
        assert verdict.reason is None


def test_a_backend_that_declares_a_condition_only_is_not_refused() -> None:
    """A lake stage one declaration away never makes a protocol unsupported."""
    verdict = protocol_support(
        _ReducedProtocol(name="a_protocol_of_a_lake", declared_observables=("stage",)),
        "modflow6",
        active=frozenset(),
    )

    assert verdict.verdict == "expected_untested"
    assert verdict.reason is None


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


def test_every_name_of_the_tested_table_is_a_shipped_flow_backend() -> None:
    """A backend renamed out of the registry fails here, before a sentence lies."""
    shipped = set(solvers.names("flow", shipped_only=True))

    for name in backends_tested_in_this_repository("matching_hydrographic_network"):
        assert name in shipped


def test_the_support_of_the_shipped_backends_says_the_table_first() -> None:
    """The record's own content: one verdict per shipped backend, table or backend."""
    protocol = get_protocol("matching_hydrographic_network")

    support = support_by_backend(protocol, [])

    assert {name: support[name] for name in ("modflow6", "modflow_nwt")} == {
        "modflow6": "tested",
        "modflow_nwt": "tested",
    }
    assert support["boussinesq"] == "unsupported"


def test_the_support_of_the_backend_that_ran_is_in_the_record() -> None:
    """A record carries the verdict of a backend that is not one this build ships."""
    protocol = get_protocol("matching_hydrographic_network")

    support = support_by_backend(protocol, ["a_plugin_backend_of_a_session"])

    assert support["a_plugin_backend_of_a_session"] == "expected_untested"
