"""The exit gate of F10b: the conformance suite runs an engine it does not name.

``register()`` certifies a candidate on the members it **declares**, and that is
all a registry can do. The real contract of the terrain port includes files on
disk -- the two point layers beside a catchment, the four artefacts a delineation
leaves -- that no declaration mentions, so a class can pass the registry and
still be unusable by the chain. Only
``tests/contract/test_terrain_engine_contract.py`` can see that, and until F10b
it ran against a dict of two classes it imported by name.

This file proves it no longer does, by installing an engine the suite has never
heard of and running the suite against it in a subprocess. What is asserted is
the plumbing, and it is stated plainly: the probe delegates the routing to
``NumpyTerrainEngine`` rather than reimplementing it, so what passes here is
"an out-of-tree distribution is discovered, built and held to the port", not
"an independent D8 implementation is correct". The second claim is F10c's, and
it needs a real second implementation to be worth anything.

Deliberately a subprocess. ``importlib.metadata`` reads the entry-point group
off ``sys.path`` once and the registry caches what it found, so a plugin
installed inside a running interpreter is a different experiment from a plugin
installed beside the build -- and the second is the one a third party performs.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFORMANCE_SUITE = "tests/contract/test_terrain_engine_contract.py"

PROBE_ENGINE_ID = "conformance_probe_d8"
"""The name the installed distribution answers to.

It is written here and in the entry point below, and nowhere else. The suite
that runs it never sees it, which is the assertion of
:func:`test_the_conformance_suite_does_not_name_the_engine_it_runs`.
"""

PROBE_MODULE = '''\
"""An out-of-tree terrain engine, as a third party would ship one.

Composition and not inheritance, on purpose: every member the port requires is
spelled out here, so a member added to the Protocol breaks this probe instead of
being inherited in silence. The routing itself is delegated -- this distribution
exists to be discovered, not to compute anything new.
"""

from __future__ import annotations

import hashlib
from typing import ClassVar

from hydromodpy.spatial.terrain import NumpyTerrainEngine


class ProbeTerrainEngine:
    engine_id: ClassVar[str] = "conformance_probe_d8"
    engine_version: ClassVar[str] = "0.1.0"

    def __init__(self) -> None:
        self._inner = NumpyTerrainEngine()

    def engine_digest(self) -> str:
        payload = "\\n".join((self.engine_id, self.engine_version, "d8_wbt"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def condition_dem(self, dem, **kwargs):
        return self._inner.condition_dem(dem, **kwargs)

    def drainage_directions(self, conditioned, **kwargs):
        return self._inner.drainage_directions(conditioned, **kwargs)

    def flow_accumulation(self, directions, **kwargs):
        return self._inner.flow_accumulation(directions, **kwargs)

    def stream_network(self, accumulation, **kwargs):
        return self._inner.stream_network(accumulation, **kwargs)

    def delineate(self, accumulation, outlets, **kwargs):
        return self._inner.delineate(accumulation, outlets, **kwargs)
'''

BROKEN_PROBE_TAIL = '''

class SilentlyUnusableEngine(ProbeTerrainEngine):
    """Passes the registry and cannot be used by the chain. The negative control.

    It declares all eight members of the port, so ``register()`` accepts it
    without a word, and it computes the catchment correctly. It just does not
    leave the two point layers the geographic chain reads back from disk --
    which is the exact defect ``NumpyTerrainEngine`` shipped with until F10a,
    surfacing as "no catchment, widen your snap distance" on a delineation that
    was numerically right.
    """

    engine_id = "conformance_probe_unusable"

    def delineate(self, accumulation, outlets, **kwargs):
        catchments = super().delineate(accumulation, outlets, **kwargs)
        for catchment in catchments:
            directory = catchment.mask_path.parent
            for layer in ("outlet", "outlet_snap"):
                for companion in directory.glob(layer + ".*"):
                    companion.unlink()
        return catchments
'''

ENTRY_POINTS_TXT = f"""\
[hydromodpy.terrain.engine]
{PROBE_ENGINE_ID} = hmp_conformance_probe:ProbeTerrainEngine
"""

BROKEN_ENTRY_POINTS_TXT = """\
[hydromodpy.terrain.engine]
conformance_probe_unusable = hmp_conformance_probe:SilentlyUnusableEngine
"""

METADATA = """\
Metadata-Version: 2.1
Name: hmp-conformance-probe
Version: 0.1.0
"""


@pytest.fixture(scope="module")
def installed_probe(tmp_path_factory) -> Path:
    """A directory that is a site-packages as far as the import system cares.

    A module and a ``.dist-info`` beside it is exactly what a wheel unpacks to,
    and it is what ``importlib.metadata`` scans a path entry for. No build, no
    ``pip install``: the test must not depend on a network or on write access to
    the environment it runs in.
    """
    return _unpack(tmp_path_factory.mktemp("probe_site_packages"), ENTRY_POINTS_TXT)


@pytest.fixture(scope="module")
def installed_broken_probe(tmp_path_factory) -> Path:
    """The same distribution, publishing the engine that is silently unusable."""
    root = tmp_path_factory.mktemp("broken_probe_site_packages")
    return _unpack(root, BROKEN_ENTRY_POINTS_TXT, tail=BROKEN_PROBE_TAIL)


def _unpack(root: Path, entry_points: str, *, tail: str = "") -> Path:
    (root / "hmp_conformance_probe.py").write_text(PROBE_MODULE + tail, encoding="utf-8")
    dist_info = root / "hmp_conformance_probe-0.1.0.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(METADATA, encoding="utf-8")
    (dist_info / "entry_points.txt").write_text(entry_points, encoding="utf-8")
    return root


def _pytest(
    session: Path, *arguments: str, site_packages: Path | None = None
) -> subprocess.CompletedProcess:
    """Run pytest in a child interpreter, with or without the probe installed.

    *session* is that child's own ``--basetemp`` and has to be unused: the
    conftest exports ``PYTEST_DEBUG_TEMPROOT``, so without it parent and child
    share one numbered-directory root and each other's garbage collection. The
    cache plugin goes for the same reason -- two sessions writing one
    ``.pytest_cache`` under the repository root is a race with nothing to gain.
    """
    environment = dict(os.environ)
    # The child is a plain session, whatever the parent is. Inheriting
    # PYTEST_XDIST_WORKER makes the conftest treat it as a worker and scope its
    # roots per worker, which is a lie about a process xdist never started.
    environment.pop("PYTEST_XDIST_WORKER", None)
    entries = [str(REPO_ROOT)]
    if site_packages is not None:
        entries.insert(0, str(site_packages))
    existing = environment.get("PYTHONPATH")
    if existing:
        entries.append(existing)
    environment["PYTHONPATH"] = os.pathsep.join(entries)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            CONFORMANCE_SUITE,
            "-p",
            "no:randomly",
            "-p",
            "no:cacheprovider",
            f"--basetemp={session}",
            *arguments,
        ],
        cwd=str(REPO_ROOT),
        env=environment,
        capture_output=True,
        text=True,
        timeout=900,
    )


def _collected(output: str) -> list[str]:
    return [line for line in output.splitlines() if line.startswith(CONFORMANCE_SUITE)]


def test_the_suite_collects_nothing_for_an_engine_that_is_not_installed(tmp_path) -> None:
    """The control. Without it, the run below could pass for the wrong reason."""
    result = _pytest(tmp_path / "bare", "--collect-only", "-q")

    assert result.returncode == 0, result.stdout[-4000:]
    assert [node for node in _collected(result.stdout) if PROBE_ENGINE_ID in node] == []


def test_installing_an_engine_adds_it_to_the_suite(installed_probe, tmp_path) -> None:
    """One distribution unpacked on the path, and the suite grows a parameter set."""
    without = _pytest(tmp_path / "bare", "--collect-only", "-q")
    with_probe = _pytest(tmp_path / "probe", "--collect-only", "-q", site_packages=installed_probe)

    assert with_probe.returncode == 0, with_probe.stdout[-4000:]
    probe_nodes = [node for node in _collected(with_probe.stdout) if PROBE_ENGINE_ID in node]
    assert probe_nodes, with_probe.stdout[-4000:]
    added = len(_collected(with_probe.stdout)) - len(_collected(without.stdout))
    assert added == len(probe_nodes), "the probe may only add its own parameter set"


def test_every_conformance_assertion_passes_against_the_installed_engine(
    installed_probe, tmp_path
) -> None:
    """The gate itself: the whole parameter set of an engine this file never names.

    Selected on the probe rather than run whole, and that is not a shortcut.
    Whitebox's own parameter set adds no evidence here -- the parent session is
    already running it -- and two pytest sessions driving the Whitebox backend at
    once is a known way to lose one of them: the library exits the process
    itself, so the child dies mid-progress with no summary and no stderr. It was
    reproduced here before this selection existed. What is left in the child is
    pure numpy and deterministic.

    That the in-tree tests keep passing while a third engine is installed is
    asserted one test above, at collection: the probe adds its own parameter set
    and changes no other node.
    """
    expected = _pytest(tmp_path / "collect", "--collect-only", "-q", site_packages=installed_probe)
    probe_nodes = [node for node in _collected(expected.stdout) if PROBE_ENGINE_ID in node]

    result = _pytest(tmp_path / "probe", "-q", "-k", PROBE_ENGINE_ID, site_packages=installed_probe)

    assert result.returncode == 0, result.stdout[-8000:]
    passed = re.search(r"(\d+) passed", result.stdout)
    assert passed is not None, result.stdout[-4000:]
    assert int(passed.group(1)) == len(probe_nodes)


def test_an_engine_the_registry_accepts_and_the_chain_cannot_use_is_caught(
    installed_broken_probe, tmp_path
) -> None:
    """The negative control, and the whole argument of the phase in one run.

    An engine that declares the eight members of the port, computes the right
    catchment, and leaves no point layer beside it is accepted by ``register()``
    without a word -- a registry can only certify what a class declares. The
    suite is the only thing that can see it, and here it does: the run fails,
    and it fails on the artefacts rather than somewhere incidental.

    Without this test the gate above proves only that a *passing* engine passes,
    which is compatible with a suite that asserts nothing about an outside one.
    """
    registered = _pytest(
        tmp_path / "collect", "--collect-only", "-q", site_packages=installed_broken_probe
    )
    assert [
        node for node in _collected(registered.stdout) if "conformance_probe_unusable" in node
    ], "the broken engine has to be accepted by the registry, or it proves nothing"

    result = _pytest(
        tmp_path / "run",
        "-q",
        "-k",
        "conformance_probe_unusable",
        site_packages=installed_broken_probe,
    )

    assert result.returncode != 0
    assert "test_a_delineation_leaves_the_four_artefacts_the_port_declares" in result.stdout


def test_the_conformance_suite_does_not_name_the_engine_it_runs() -> None:
    """The point of the phase, asserted rather than assumed."""
    suite = (REPO_ROOT / CONFORMANCE_SUITE).read_text(encoding="utf-8")

    assert PROBE_ENGINE_ID not in suite
    assert "ENGINE_FACTORIES" not in suite, "the hard-coded engine dict is what F10b removed"


def test_the_conformance_suite_imports_no_engine_class() -> None:
    """A tripwire on the way the dict would come back, not a proof that it cannot.

    The suite obtains every engine from the registry, and the readable way to
    undo that is to import a concrete class and build it. This reads the import
    statements rather than the file text, so an alias, a line break or a space
    before the parenthesis does not walk past it. It stays a tripwire: a helper
    module elsewhere, or ``registry.get(...)()`` spelled by hand, reaches a class
    without an import here. What proves the phase is the installed engine two
    tests up; this only keeps the obvious regression loud.

    ``TerrainEngine`` itself is excluded: it is the Protocol, and the suite
    asserts membership of it.
    """
    tree = ast.parse((REPO_ROOT / CONFORMANCE_SUITE).read_text(encoding="utf-8"))
    imported = {
        alias.name.rpartition(".")[2]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    }
    engines = sorted(
        name for name in imported if name.endswith("TerrainEngine") and name != "TerrainEngine"
    )

    assert engines == [], f"the suite imports {engines} instead of asking the registry"
