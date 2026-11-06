"""The mesh conformance suite runs an engine it does not name.

``register()`` certifies a candidate on the members it **declares**, and that is
all a registry can do. The invariants a solver relies on (the cell holds its
center, the areas add up, a chain is continuous) live on the mesh, so a class
can pass the registry and still be unusable. Only
``tests/contract/test_mesh_engine_contract.py`` can see that, and it must see it
for an engine it never imported.

This file proves it by installing an engine the suite has never heard of and
running the suite against it in a subprocess. What is asserted is the plumbing:
the probe delegates the meshing to ``RegularMeshEngine``, so what passes here is
"an out-of-tree distribution is discovered, built and held to the port", not
"an independent mesher is correct". The negative control is an engine that
passes the registry and puts its cell centers outside their cells.

Deliberately a subprocess. ``importlib.metadata`` reads the entry-point group off
``sys.path`` once and the registry caches what it found, so a plugin installed
inside a running interpreter is a different experiment from a plugin installed
beside the build, and the second is the one a third party performs.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ._installed_probe import REPO_ROOT, collected, run_suite, unpack

CONFORMANCE_SUITE = "tests/contract/test_mesh_engine_contract.py"

PROBE_ENGINE_ID = "conformance_probe_grid"
"""The name the installed distribution answers to.

It is written here and in the entry point below, and nowhere else. The suite
that runs it never sees it: the control
:func:`test_the_suite_collects_nothing_for_an_engine_that_is_not_installed` finds
no node of that name without the probe.
"""

BROKEN_ENGINE_ID = "conformance_probe_off_center"

PROBE_MODULE = '''\
"""An out-of-tree mesh engine, as a third party would ship one.

Composition and not inheritance, on purpose: every member the port requires is
spelled out here, so a member added to the Protocol breaks this probe instead of
being inherited in silence. The meshing itself is delegated: this distribution
exists to be discovered, not to compute anything new.
"""

from __future__ import annotations

from typing import ClassVar

from hydromodpy.spatial.mesh.engines.regular.engine import RegularMeshEngine
from hydromodpy.spatial.mesh.model.planar_cell_mesh import MeshIdentity


class ProbeMeshEngine:
    engine_id: ClassVar[str] = "conformance_probe_grid"
    engine_version: ClassVar[str] = "0.1.0"
    capabilities: ClassVar = RegularMeshEngine.capabilities

    def __init__(self) -> None:
        self._inner = RegularMeshEngine()

    def build(self, request):
        cell_mesh = self._inner.build(request)
        identity = MeshIdentity(self.engine_id, self.engine_version, request.canonical_hash(), None)
        return _with(cell_mesh, identity=identity)


def _with(cell_mesh, **changes):
    import dataclasses

    return dataclasses.replace(cell_mesh, **changes)
'''

BROKEN_PROBE_TAIL = '''

class OffCenterMeshEngine(ProbeMeshEngine):
    """Passes the registry and cannot be used by a solver. The negative control.

    It declares every member of the port, so ``register()`` accepts it without a
    word, and its cells are the right ones. It just reports cell centers a
    kilometer away from their cells, which every consumer of ``centers`` would
    read as the head location.
    """

    engine_id = "conformance_probe_off_center"

    def build(self, request):
        cell_mesh = super().build(request)
        return _with(cell_mesh, centers=cell_mesh.centers + 1.0e5)
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
        tmp_path_factory.mktemp("probe_site_packages"), "hmp_mesh_conformance_probe", PROBE_MODULE,
        "hydromodpy.mesh.engine", PROBE_ENGINE_ID, "ProbeMeshEngine",
    )  # fmt: skip


@pytest.fixture(scope="module")
def installed_broken_probe(tmp_path_factory) -> Path:
    """The same distribution, publishing the engine that is silently unusable."""
    root = tmp_path_factory.mktemp("broken_probe_site_packages")
    return unpack(
        root,
        "hmp_mesh_conformance_probe",
        PROBE_MODULE + BROKEN_PROBE_TAIL,
        "hydromodpy.mesh.engine",
        BROKEN_ENGINE_ID,
        "OffCenterMeshEngine",
    )


def _count(output: str, word: str) -> int:
    found = re.search(rf"(\d+) {word}", output)
    return int(found.group(1)) if found else 0


def test_the_suite_collects_nothing_for_an_engine_that_is_not_installed(tmp_path) -> None:
    """The control. Without it, the run below could pass for the wrong reason."""
    result = run_suite(CONFORMANCE_SUITE, tmp_path / "bare", "--collect-only", "-q")

    assert result.returncode == 0, result.stdout[-4000:]
    assert [
        node for node in collected(result.stdout, CONFORMANCE_SUITE) if PROBE_ENGINE_ID in node
    ] == []


def test_installing_an_engine_adds_it_to_the_suite(installed_probe, tmp_path) -> None:
    """One distribution unpacked on the path, and the suite grows a parameter set."""
    without = run_suite(CONFORMANCE_SUITE, tmp_path / "bare", "--collect-only", "-q")
    with_probe = run_suite(
        CONFORMANCE_SUITE, tmp_path / "probe", "--collect-only", "-q", site_packages=installed_probe
    )

    assert with_probe.returncode == 0, with_probe.stdout[-4000:]
    probe_nodes = [
        node for node in collected(with_probe.stdout, CONFORMANCE_SUITE) if PROBE_ENGINE_ID in node
    ]
    assert probe_nodes, with_probe.stdout[-4000:]
    added = len(collected(with_probe.stdout, CONFORMANCE_SUITE)) - len(
        collected(without.stdout, CONFORMANCE_SUITE)
    )
    assert added == len(probe_nodes), "the probe may only add its own parameter set"


def test_every_conformance_assertion_passes_against_the_installed_engine(
    installed_probe, tmp_path
) -> None:
    """The gate itself: the whole parameter set of an engine this file never names.

    Selected on the probe rather than run whole: the built-in engines are already
    run by the parent session. A test the probe's capabilities make
    inapplicable (it is not graded) skips, so the count is passed plus skipped,
    and what must not happen is a failure or an empty run.
    """
    expected = run_suite(
        CONFORMANCE_SUITE,
        tmp_path / "collect",
        "--collect-only",
        "-q",
        site_packages=installed_probe,
    )
    probe_nodes = [
        node for node in collected(expected.stdout, CONFORMANCE_SUITE) if PROBE_ENGINE_ID in node
    ]

    result = run_suite(
        CONFORMANCE_SUITE,
        tmp_path / "probe",
        "-q",
        "-k",
        PROBE_ENGINE_ID,
        site_packages=installed_probe,
    )

    assert result.returncode == 0, result.stdout[-8000:]
    assert _count(result.stdout, "failed") == 0
    passed, skipped = _count(result.stdout, "passed"), _count(result.stdout, "skipped")
    assert passed > 0, result.stdout[-4000:]
    assert passed + skipped == len(probe_nodes)


def test_an_engine_the_registry_accepts_and_a_solver_cannot_use_is_caught(
    installed_broken_probe, tmp_path
) -> None:
    """The negative control, and the whole argument of the file in one run.

    An engine that declares the members of the port, returns the right cells and
    reports their centers a kilometer away is accepted by ``register()`` without
    a word: a registry can only certify what a class declares. The suite is the
    only thing that can see it, and here it does: the run fails, and it fails on
    the centers rather than somewhere incidental.

    Without this test the gate above proves only that a *passing* engine passes,
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
        node for node in collected(registered.stdout, CONFORMANCE_SUITE) if BROKEN_ENGINE_ID in node
    ], "the broken engine has to be accepted by the registry, or it proves nothing"

    result = run_suite(
        CONFORMANCE_SUITE,
        tmp_path / "run",
        "-q",
        "-k",
        BROKEN_ENGINE_ID,
        site_packages=installed_broken_probe,
    )

    assert result.returncode != 0
    assert "test_the_center_of_a_cell_lies_in_the_cell" in result.stdout
