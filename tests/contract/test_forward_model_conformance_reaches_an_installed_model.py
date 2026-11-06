"""The exit gate of F9d: the conformance suite runs a forward model it does not name.

``register()`` certifies a candidate on the members it **declares**, and that is
all a registry can do. The real contract of the forward-model port is
behavioral -- what an answer contains, and what comes out as an exception
instead of being invented -- so a class can pass the registry without a word
and still be something no calibration can trust. Only
``tests/contract/test_forward_model_contract.py`` can see that.

This file proves the suite reaches a model installed beside the build, by
unpacking one on the path and running the suite against it in a subprocess.
What is asserted is the plumbing, and it is stated plainly: the probe delegates
the simulation to ``LinearReservoirForwardModel`` rather than computing anything
of its own, so what passes here is "an out-of-tree distribution is discovered,
built and held to the port", not "an independent forward model is correct".

Deliberately a subprocess. ``importlib.metadata`` reads the entry-point group off
``sys.path`` once and the registry caches what it found, so a plugin installed
inside a running interpreter is a different experiment from a plugin installed
beside the build -- and the second is the one a third party performs.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from ._installed_probe import REPO_ROOT, collected, run_suite, unpack

CONFORMANCE_SUITE = "tests/contract/test_forward_model_contract.py"

PROBE_MODEL_ID = "conformance_probe_reservoir"
"""The name the installed distribution answers to.

It is written here and in the entry point below, and nowhere else. The suite
that runs it never sees it, which is the assertion of
:func:`test_the_conformance_suite_does_not_name_the_model_it_runs`.
"""

UNUSABLE_MODEL_ID = "conformance_probe_drops_a_parameter"

PROBE_MODULE = '''\
"""An out-of-tree forward model, as a third party would ship one.

Composition and not inheritance, on purpose: every member the port requires is
spelled out here, so a member added to the Protocol breaks this probe instead of
being inherited in silence. The simulation itself is delegated -- this
distribution exists to be discovered, not to compute anything new.
"""

from __future__ import annotations

from typing import ClassVar

from hydromodpy.calibration.evaluation.linear_reservoir import LinearReservoirForwardModel


class ProbeForwardModel:
    model_id: ClassVar[str] = "conformance_probe_reservoir"

    def __init__(self) -> None:
        self._inner = LinearReservoirForwardModel()

    def simulate(self, request):
        return self._inner.simulate(request)
'''

BROKEN_PROBE_TAIL = '''

class DropsAParameterModel(ProbeForwardModel):
    """Passes the registry and poisons any search that uses it. The negative control.

    It declares the two members of the port, so ``register()`` accepts it
    without a word, and it answers every batch this suite asks for. What it does
    with a parameter it cannot place is drop it silently instead of refusing --
    the port says a dropped name turns a declared knob into no knob at all: every
    sample of the search would then cost the same, and the report would name a
    best that means nothing.
    """

    model_id = "conformance_probe_drops_a_parameter"

    def simulate(self, request):
        known = {"k", "porosity"}
        cleaned = type(request)(
            trial_id=request.trial_id,
            values={name: value for name, value in request.values.items() if name in known},
            observables=request.observables,
        )
        return self._inner.simulate(cleaned)
'''


@pytest.fixture(scope="module")
def installed_probe(tmp_path_factory) -> Path:
    """A directory that is a site-packages as far as the import system cares.

    A module and a ``.dist-info`` beside it is exactly what a wheel unpacks to,
    and it is what ``importlib.metadata`` scans a path entry for. No build, no
    ``pip install``: the test must not depend on a network or on write access to
    the environment it runs in.
    """
    return unpack(
        tmp_path_factory.mktemp("probe_site_packages"), "hmp_forward_model_probe", PROBE_MODULE,
        "hydromodpy.calibration.forward_model", PROBE_MODEL_ID, "ProbeForwardModel",
    )  # fmt: skip


@pytest.fixture(scope="module")
def installed_broken_probe(tmp_path_factory) -> Path:
    """The same distribution, publishing the model that drops an unplaceable parameter."""
    root = tmp_path_factory.mktemp("broken_probe_site_packages")
    return unpack(
        root,
        "hmp_forward_model_probe",
        PROBE_MODULE + BROKEN_PROBE_TAIL,
        "hydromodpy.calibration.forward_model",
        UNUSABLE_MODEL_ID,
        "DropsAParameterModel",
    )


def test_the_suite_collects_nothing_for_a_model_that_is_not_installed(tmp_path) -> None:
    """The control. Without it, the run below could pass for the wrong reason."""
    result = run_suite(CONFORMANCE_SUITE, tmp_path / "bare", "--collect-only", "-q")

    assert result.returncode == 0, result.stdout[-4000:]
    assert [
        node for node in collected(result.stdout, CONFORMANCE_SUITE) if PROBE_MODEL_ID in node
    ] == []


def test_installing_a_model_adds_it_to_the_suite(installed_probe, tmp_path) -> None:
    """One distribution unpacked on the path, and the suite grows a parameter set."""
    without = run_suite(CONFORMANCE_SUITE, tmp_path / "bare", "--collect-only", "-q")
    with_probe = run_suite(
        CONFORMANCE_SUITE, tmp_path / "probe", "--collect-only", "-q", site_packages=installed_probe
    )

    assert with_probe.returncode == 0, with_probe.stdout[-4000:]
    probe_nodes = [
        node for node in collected(with_probe.stdout, CONFORMANCE_SUITE) if PROBE_MODEL_ID in node
    ]
    assert probe_nodes, with_probe.stdout[-4000:]
    added = len(collected(with_probe.stdout, CONFORMANCE_SUITE)) - len(
        collected(without.stdout, CONFORMANCE_SUITE)
    )
    assert added == len(probe_nodes), "the probe may only add its own parameter set"


def test_every_conformance_assertion_passes_against_the_installed_model(
    installed_probe, tmp_path
) -> None:
    """The gate itself: the whole parameter set of a model this file never names.

    Every node of that set has to **run**. A suite parametrized by what the
    registry resolves grows and shrinks with the installation, so counting what
    passed against what was collected is what separates "the probe was exercised"
    from "the probe was collected and skipped".
    """
    expected = run_suite(
        CONFORMANCE_SUITE,
        tmp_path / "collect",
        "--collect-only",
        "-q",
        site_packages=installed_probe,
    )
    probe_nodes = [
        node for node in collected(expected.stdout, CONFORMANCE_SUITE) if PROBE_MODEL_ID in node
    ]
    assert len(probe_nodes) >= 10, expected.stdout[-4000:]

    result = run_suite(
        CONFORMANCE_SUITE,
        tmp_path / "probe",
        "-q",
        "-k",
        PROBE_MODEL_ID,
        site_packages=installed_probe,
    )

    assert result.returncode == 0, result.stdout[-8000:]
    passed = re.search(r"(\d+) passed", result.stdout)
    assert passed is not None, result.stdout[-4000:]
    assert int(passed.group(1)) == len(probe_nodes)
    assert " skipped" not in result.stdout, result.stdout[-4000:]


def test_a_model_the_registry_accepts_and_the_chain_cannot_use_is_caught(
    installed_broken_probe, tmp_path
) -> None:
    """The negative control, and the whole argument of the phase in one run.

    A model that declares the two members of the port and answers every legal
    sample is accepted by ``register()`` without a word -- a registry can only
    certify what a class declares. The suite is the only thing that can see it,
    and here it does: the run fails, and it fails on the parameter it silently
    dropped rather than somewhere incidental.

    Without this test the gate above proves only that a *passing* model passes,
    which is compatible with a suite that asserts nothing about an outside one.
    """
    registered = run_suite(
        CONFORMANCE_SUITE,
        tmp_path / "collect",
        "--collect-only",
        "-q",
        site_packages=installed_broken_probe,
    )
    assert [
        node
        for node in collected(registered.stdout, CONFORMANCE_SUITE)
        if UNUSABLE_MODEL_ID in node
    ], "the broken model has to be accepted by the registry, or it proves nothing"

    result = run_suite(
        CONFORMANCE_SUITE,
        tmp_path / "run",
        "-q",
        "-k",
        UNUSABLE_MODEL_ID,
        site_packages=installed_broken_probe,
    )

    assert result.returncode != 0
    assert "test_a_parameter_it_cannot_place_is_refused_and_not_ignored" in result.stdout
    assert "DID NOT RAISE" in result.stdout


def test_the_conformance_suite_does_not_name_the_model_it_runs() -> None:
    """The point of the phase, asserted rather than assumed."""
    suite = (REPO_ROOT / CONFORMANCE_SUITE).read_text(encoding="utf-8")

    assert PROBE_MODEL_ID not in suite
    assert UNUSABLE_MODEL_ID not in suite


def test_the_conformance_suite_imports_no_model_class() -> None:
    """A tripwire on the way a hard-coded list would come back, not a proof that it cannot.

    The suite obtains every model from the registry, and the readable way to
    undo that is to import a concrete class and build it. This reads the import
    statements rather than the file text, so an alias, a line break or a space
    before the parenthesis does not walk past it. It stays a tripwire: a helper
    module elsewhere, or ``registry.create(...)`` spelled by hand with an
    imported class, reaches one without an import here.

    ``ForwardModel`` itself is excluded: it is the Protocol, and the suite is
    entitled to name it.
    """
    tree = ast.parse((REPO_ROOT / CONFORMANCE_SUITE).read_text(encoding="utf-8"))
    imported = {
        alias.name.rpartition(".")[2]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    }
    models = sorted(
        name
        for name in imported
        if name.endswith(("ForwardModel", "Model")) and name != "ForwardModel"
    )

    assert models == [], f"the suite imports {models} instead of asking the registry"
