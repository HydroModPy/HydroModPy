"""The exit gate of F10b: the conformance suite runs an engine it does not name.

``register()`` certifies a candidate on the members it declares. The files a
delineation leaves on disk are only seen by
``tests/contract/test_terrain_engine_contract.py``, so this file installs an engine
the suite has never heard of and runs the suite against it in a subprocess. The
probe delegates the routing to ``NumpyTerrainEngine``: what passes here is the
plumbing (discovered, built, held to the port), not an independent D8. A
subprocess, because ``importlib.metadata`` reads the entry points once and the
registry caches them.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

# One worker runs the file, so each collection below runs once.
pytestmark = pytest.mark.xdist_group("terrain_conformance_probe")

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFORMANCE_SUITE = "tests/contract/test_terrain_engine_contract.py"

PROBE_ENGINE_ID = "conformance_probe_d8"
"""The name the installed distribution answers to, written nowhere but here."""

PROBE_MODULE = '''\
"""An out-of-tree engine. Composition, so a member added to the port breaks it."""

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

BROKEN_ENGINE_ID = "conformance_probe_unusable"
BROKEN_PROBE_TAIL = '''

class SilentlyUnusableEngine(ProbeTerrainEngine):
    """Declares the port and drops the two point layers: the defect numpy had until F10a."""

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

METADATA = "Metadata-Version: 2.1\nName: hmp-conformance-probe\nVersion: 0.1.0\n"


def _unpack(root: Path, engine_id: str, engine_class: str, *, tail: str = "") -> Path:
    """A module and its ``.dist-info``, what a wheel unpacks to. No build, no network."""
    (root / "hmp_conformance_probe.py").write_text(PROBE_MODULE + tail, encoding="utf-8")
    dist_info = root / "hmp_conformance_probe-0.1.0.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(METADATA, encoding="utf-8")
    entry_points = (
        f"[hydromodpy.terrain.engine]\n{engine_id} = hmp_conformance_probe:{engine_class}\n"
    )
    (dist_info / "entry_points.txt").write_text(entry_points, encoding="utf-8")
    return root


@pytest.fixture(scope="module")
def installed_probe(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("probe_site_packages")
    return _unpack(root, PROBE_ENGINE_ID, "ProbeTerrainEngine")


@pytest.fixture(scope="module")
def installed_broken_probe(tmp_path_factory) -> Path:
    """The same distribution, publishing the engine that is silently unusable."""
    root = tmp_path_factory.mktemp("broken_probe_site_packages")
    return _unpack(root, BROKEN_ENGINE_ID, "SilentlyUnusableEngine", tail=BROKEN_PROBE_TAIL)


def _pytest(
    session: Path, *arguments: str, site_packages: Path | None = None
) -> subprocess.CompletedProcess:
    """Run pytest in a child interpreter, with or without the probe installed.

    *session* is the child's own unused ``--basetemp``, so parent and child share
    no temp root, and the cache plugin is off so they share no ``.pytest_cache``.
    """
    environment = dict(os.environ)
    # The child is a plain session, not an xdist worker of the parent.
    environment.pop("PYTEST_XDIST_WORKER", None)
    entries = [site_packages, REPO_ROOT, environment.get("PYTHONPATH")]
    environment["PYTHONPATH"] = os.pathsep.join(str(entry) for entry in entries if entry)
    return subprocess.run(
        [sys.executable, "-m", "pytest", CONFORMANCE_SUITE, "-p", "no:randomly",
         "-p", "no:cacheprovider", f"--basetemp={session}", *arguments],
        cwd=str(REPO_ROOT),
        env=environment,
        capture_output=True,
        text=True,
        timeout=900,
    )  # fmt: skip


def _collected(output: str, engine_id: str = "") -> list[str]:
    """The collected node ids, of *engine_id* only when given."""
    lines = output.splitlines()
    return [line for line in lines if line.startswith(CONFORMANCE_SUITE) and engine_id in line]


@pytest.fixture(scope="module")
def bare_collection(tmp_path_factory) -> subprocess.CompletedProcess:
    return _pytest(tmp_path_factory.mktemp("bare"), "--collect-only", "-q")


@pytest.fixture(scope="module")
def probe_collection(installed_probe, tmp_path_factory) -> subprocess.CompletedProcess:
    session = tmp_path_factory.mktemp("probe_collect")
    return _pytest(session, "--collect-only", "-q", site_packages=installed_probe)


def test_installing_an_engine_adds_it_to_the_suite(bare_collection, probe_collection) -> None:
    """The probe adds its own parameter set and changes no other node (bare is the control)."""
    without, with_probe = bare_collection, probe_collection
    assert without.returncode == 0, without.stdout[-4000:]
    assert _collected(without.stdout, PROBE_ENGINE_ID) == []
    assert with_probe.returncode == 0, with_probe.stdout[-4000:]
    probe_nodes = _collected(with_probe.stdout, PROBE_ENGINE_ID)
    assert probe_nodes, with_probe.stdout[-4000:]
    added = len(_collected(with_probe.stdout)) - len(_collected(without.stdout))
    assert added == len(probe_nodes), "the probe may only add its own parameter set"


def test_every_conformance_assertion_passes_against_the_installed_engine(
    installed_probe, probe_collection, tmp_path
) -> None:
    """The gate: the whole parameter set of an engine this file never names.

    Selected on the probe: two sessions driving Whitebox at once lose one of them
    (the library exits the process), and the parent already runs Whitebox's set.
    """
    probe_nodes = _collected(probe_collection.stdout, PROBE_ENGINE_ID)
    result = _pytest(tmp_path / "probe", "-q", "-k", PROBE_ENGINE_ID, site_packages=installed_probe)
    assert result.returncode == 0, result.stdout[-8000:]
    passed = re.search(r"(\d+) passed", result.stdout)
    assert passed is not None, result.stdout[-4000:]
    assert int(passed.group(1)) == len(probe_nodes)


def test_an_engine_the_registry_accepts_and_the_chain_cannot_use_is_caught(
    installed_broken_probe, tmp_path
) -> None:
    """The negative control: ``register()`` accepts it, and the suite fails it on the artefacts."""
    registered = _pytest(
        tmp_path / "collect", "--collect-only", "-q", site_packages=installed_broken_probe
    )
    assert _collected(registered.stdout, BROKEN_ENGINE_ID), "accepted by the registry, or it proves nothing"  # fmt: skip
    result = _pytest(tmp_path / "run", "-q", "-k", BROKEN_ENGINE_ID, site_packages=installed_broken_probe)  # fmt: skip
    assert result.returncode != 0
    assert "test_a_delineation_leaves_the_four_artefacts_the_port_declares" in result.stdout


def test_the_conformance_suite_neither_names_nor_imports_the_engine_it_runs() -> None:
    """The point of the phase. The import check is a tripwire (aliases included), not a proof."""
    suite = (REPO_ROOT / CONFORMANCE_SUITE).read_text(encoding="utf-8")
    imported = {
        alias.name.rpartition(".")[2]
        for node in ast.walk(ast.parse(suite))
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    }
    # ``TerrainEngine`` is the Protocol the suite asserts membership of.
    engines = sorted(
        name for name in imported if name.endswith("TerrainEngine") and name != "TerrainEngine"
    )

    assert PROBE_ENGINE_ID not in suite
    assert "ENGINE_FACTORIES" not in suite, "the hard-coded engine dict is what F10b removed"
    assert engines == [], f"the suite imports {engines} instead of asking the registry"
