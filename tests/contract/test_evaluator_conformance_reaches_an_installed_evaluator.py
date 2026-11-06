"""The exit gate of F9b: the conformance suite runs an evaluator it does not name.

``register()`` certifies a candidate on the members it **declares**, and that is
all a registry can do. The real contract of the trial-evaluator port is
behavioral -- what comes back from a call, and what does not come out of it as
an exception -- so a class can pass the registry without a word and still be
something no search can use. Only
``tests/contract/test_trial_evaluator_contract.py`` can see that.

This file proves the suite reaches an evaluator installed beside the build, by
unpacking one on the path and running the suite against it in a subprocess. What
is asserted is the plumbing, and it is stated plainly: the probe delegates the
scoring to ``AnalyticBowlEvaluator`` rather than computing anything of its own,
so what passes here is "an out-of-tree distribution is discovered, built and held
to the port", not "an independent evaluator is correct". The second claim is
F9c's, and it needs a real second implementation to be worth anything.

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

CONFORMANCE_SUITE = "tests/contract/test_trial_evaluator_contract.py"

PROBE_EVALUATOR_ID = "conformance_probe_bowl"
"""The name the installed distribution answers to.

It is written here and in the entry point below, and nowhere else. The suite that
runs it never sees it, which is the assertion of
:func:`test_the_conformance_suite_does_not_name_the_evaluator_it_runs`.
"""

UNUSABLE_EVALUATOR_ID = "conformance_probe_rewards_failure"

PROBE_MODULE = '''\
"""An out-of-tree trial evaluator, as a third party would ship one.

Composition and not inheritance, on purpose: every member the port requires is
spelled out here, so a member added to the Protocol breaks this probe instead of
being inherited in silence. The scoring itself is delegated -- this distribution
exists to be discovered, not to compute anything new.
"""

from __future__ import annotations

from typing import ClassVar

from hydromodpy.calibration.evaluation.analytic_bowl import AnalyticBowlEvaluator


class ProbeTrialEvaluator:
    evaluator_id: ClassVar[str] = "conformance_probe_bowl"
    needs_prepared_model: ClassVar[bool] = False

    def __init__(self, *, space=None) -> None:
        self._inner = AnalyticBowlEvaluator(space=space)

    def evaluate(self, request):
        return self._inner.evaluate(request)
'''

BROKEN_PROBE_TAIL = '''

class RewardsFailureEvaluator(ProbeTrialEvaluator):
    """Passes the registry and poisons any search that uses it. The negative control.

    It declares the three members of the port, so ``register()`` accepts it
    without a word, and it scores every legal sample correctly. What it does with
    a sample it cannot score is return a large finite number instead of ``nan``
    -- the single most common way of writing a failure branch, and the one the
    port forbids by name: a failed trial carrying a number wins a search whose
    other trials were worse, and the search then reports a best candidate that
    was never computed.
    """

    evaluator_id = "conformance_probe_rewards_failure"

    def evaluate(self, request):
        outcome = self._inner.evaluate(request)
        if outcome.status == "completed":
            return outcome
        return type(outcome)(
            cost=1e9,
            status=outcome.status,
            duration_s=outcome.duration_s,
            components=outcome.components,
            error=outcome.error,
        )
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
        tmp_path_factory.mktemp("probe_site_packages"), "hmp_evaluator_probe", PROBE_MODULE,
        "hydromodpy.calibration.evaluator", PROBE_EVALUATOR_ID, "ProbeTrialEvaluator",
    )  # fmt: skip


@pytest.fixture(scope="module")
def installed_broken_probe(tmp_path_factory) -> Path:
    """The same distribution, publishing the evaluator that rewards a failed trial."""
    root = tmp_path_factory.mktemp("broken_probe_site_packages")
    return unpack(
        root,
        "hmp_evaluator_probe",
        PROBE_MODULE + BROKEN_PROBE_TAIL,
        "hydromodpy.calibration.evaluator",
        UNUSABLE_EVALUATOR_ID,
        "RewardsFailureEvaluator",
    )


def test_the_suite_collects_nothing_for_an_evaluator_that_is_not_installed(tmp_path) -> None:
    """The control. Without it, the run below could pass for the wrong reason."""
    result = run_suite(CONFORMANCE_SUITE, tmp_path / "bare", "--collect-only", "-q")

    assert result.returncode == 0, result.stdout[-4000:]
    assert [
        node for node in collected(result.stdout, CONFORMANCE_SUITE) if PROBE_EVALUATOR_ID in node
    ] == []


def test_installing_an_evaluator_adds_it_to_the_suite(installed_probe, tmp_path) -> None:
    """One distribution unpacked on the path, and the suite grows a parameter set."""
    without = run_suite(CONFORMANCE_SUITE, tmp_path / "bare", "--collect-only", "-q")
    with_probe = run_suite(
        CONFORMANCE_SUITE, tmp_path / "probe", "--collect-only", "-q", site_packages=installed_probe
    )

    assert with_probe.returncode == 0, with_probe.stdout[-4000:]
    probe_nodes = [
        node
        for node in collected(with_probe.stdout, CONFORMANCE_SUITE)
        if PROBE_EVALUATOR_ID in node
    ]
    assert probe_nodes, with_probe.stdout[-4000:]
    added = len(collected(with_probe.stdout, CONFORMANCE_SUITE)) - len(
        collected(without.stdout, CONFORMANCE_SUITE)
    )
    assert added == len(probe_nodes), "the probe may only add its own parameter set"


def test_every_conformance_assertion_passes_against_the_installed_evaluator(
    installed_probe, tmp_path
) -> None:
    """The gate itself: the whole parameter set of an evaluator this file never names.

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
        node for node in collected(expected.stdout, CONFORMANCE_SUITE) if PROBE_EVALUATOR_ID in node
    ]
    assert len(probe_nodes) >= 10, expected.stdout[-4000:]

    result = run_suite(
        CONFORMANCE_SUITE,
        tmp_path / "probe",
        "-q",
        "-k",
        PROBE_EVALUATOR_ID,
        site_packages=installed_probe,
    )

    assert result.returncode == 0, result.stdout[-8000:]
    passed = re.search(r"(\d+) passed", result.stdout)
    assert passed is not None, result.stdout[-4000:]
    assert int(passed.group(1)) == len(probe_nodes)
    assert " skipped" not in result.stdout, result.stdout[-4000:]


def test_an_evaluator_the_registry_accepts_and_no_search_can_use_is_caught(
    installed_broken_probe, tmp_path
) -> None:
    """The negative control, and the whole argument of the phase in one run.

    An evaluator that declares the three members of the port, scores every legal
    sample correctly, and answers a sample it cannot score with a large finite
    cost is accepted by ``register()`` without a word -- a registry can only
    certify what a class declares. The suite is the only thing that can see it,
    and here it does: the run fails, and it fails on the outcome of an unscorable
    sample rather than somewhere incidental.

    Without this test the gate above proves only that a *passing* evaluator
    passes, which is compatible with a suite that asserts nothing about an
    outside one.
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
        if UNUSABLE_EVALUATOR_ID in node
    ], "the broken evaluator has to be accepted by the registry, or it proves nothing"

    result = run_suite(
        CONFORMANCE_SUITE,
        tmp_path / "run",
        "-q",
        "-k",
        UNUSABLE_EVALUATOR_ID,
        site_packages=installed_broken_probe,
    )

    assert result.returncode != 0
    assert "test_a_sample_it_cannot_score_comes_back_and_is_not_raised" in result.stdout
    assert "instead of nan" in result.stdout


def test_the_conformance_suite_does_not_name_the_evaluator_it_runs() -> None:
    """The point of the phase, asserted rather than assumed."""
    suite = (REPO_ROOT / CONFORMANCE_SUITE).read_text(encoding="utf-8")

    assert PROBE_EVALUATOR_ID not in suite
    assert UNUSABLE_EVALUATOR_ID not in suite


def test_the_conformance_suite_imports_no_evaluator_class() -> None:
    """A tripwire on the way a hard-coded list would come back, not a proof that it cannot.

    The suite obtains every evaluator from the registry, and the readable way to
    undo that is to import a concrete class and build it. This reads the import
    statements rather than the file text, so an alias, a line break or a space
    before the parenthesis does not walk past it. It stays a tripwire: a helper
    module elsewhere, or ``registry.get(...)()`` spelled by hand, reaches a class
    without an import here.

    ``TrialEvaluator`` itself is excluded: it is the Protocol, and the suite is
    entitled to name it.
    """
    tree = ast.parse((REPO_ROOT / CONFORMANCE_SUITE).read_text(encoding="utf-8"))
    imported = {
        alias.name.rpartition(".")[2]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    }
    evaluators = sorted(
        name
        for name in imported
        if name.endswith(("TrialEvaluator", "Evaluator")) and name != "TrialEvaluator"
    )

    assert evaluators == [], f"the suite imports {evaluators} instead of asking the registry"
