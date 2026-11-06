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
import re
import subprocess
from pathlib import Path

import pytest

from ._installed_probe import REPO_ROOT, collected, run_suite, unpack

# One worker runs the file, so each collection below runs once.
pytestmark = pytest.mark.xdist_group("terrain_conformance_probe")

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


def _unpack(root: Path, engine_id: str, engine_class: str, *, tail: str = "") -> Path:
    return unpack(
        root, "hmp_conformance_probe", PROBE_MODULE + tail,
        "hydromodpy.terrain.engine", engine_id, engine_class,
    )  # fmt: skip


@pytest.fixture(scope="module")
def installed_probe(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("probe_site_packages")
    return _unpack(root, PROBE_ENGINE_ID, "ProbeTerrainEngine")


@pytest.fixture(scope="module")
def installed_broken_probe(tmp_path_factory) -> Path:
    """The same distribution, publishing the engine that is silently unusable."""
    root = tmp_path_factory.mktemp("broken_probe_site_packages")
    return _unpack(root, BROKEN_ENGINE_ID, "SilentlyUnusableEngine", tail=BROKEN_PROBE_TAIL)


@pytest.fixture(scope="module")
def bare_collection(tmp_path_factory) -> subprocess.CompletedProcess:
    return run_suite(CONFORMANCE_SUITE, tmp_path_factory.mktemp("bare"), "--collect-only", "-q")


@pytest.fixture(scope="module")
def probe_collection(installed_probe, tmp_path_factory) -> subprocess.CompletedProcess:
    session = tmp_path_factory.mktemp("probe_collect")
    return run_suite(
        CONFORMANCE_SUITE, session, "--collect-only", "-q", site_packages=installed_probe
    )


def test_installing_an_engine_adds_it_to_the_suite(bare_collection, probe_collection) -> None:
    """The probe adds its own parameter set and changes no other node (bare is the control)."""
    without, with_probe = bare_collection, probe_collection
    assert without.returncode == 0, without.stdout[-4000:]
    assert collected(without.stdout, CONFORMANCE_SUITE, PROBE_ENGINE_ID) == []
    assert with_probe.returncode == 0, with_probe.stdout[-4000:]
    probe_nodes = collected(with_probe.stdout, CONFORMANCE_SUITE, PROBE_ENGINE_ID)
    assert probe_nodes, with_probe.stdout[-4000:]
    added = len(collected(with_probe.stdout, CONFORMANCE_SUITE)) - len(
        collected(without.stdout, CONFORMANCE_SUITE)
    )
    assert added == len(probe_nodes), "the probe may only add its own parameter set"


def test_every_conformance_assertion_passes_against_the_installed_engine(
    installed_probe, probe_collection, tmp_path
) -> None:
    """The gate: the whole parameter set of an engine this file never names.

    Selected on the probe: two sessions driving Whitebox at once lose one of them
    (the library exits the process), and the parent already runs Whitebox's set.
    """
    probe_nodes = collected(probe_collection.stdout, CONFORMANCE_SUITE, PROBE_ENGINE_ID)
    result = run_suite(
        CONFORMANCE_SUITE,
        tmp_path / "probe",
        "-q",
        "-k",
        PROBE_ENGINE_ID,
        site_packages=installed_probe,
    )
    assert result.returncode == 0, result.stdout[-8000:]
    passed = re.search(r"(\d+) passed", result.stdout)
    assert passed is not None, result.stdout[-4000:]
    assert int(passed.group(1)) == len(probe_nodes)


def test_an_engine_the_registry_accepts_and_the_chain_cannot_use_is_caught(
    installed_broken_probe, tmp_path
) -> None:
    """The negative control: ``register()`` accepts it, and the suite fails it on the artifacts."""
    registered = run_suite(
        CONFORMANCE_SUITE,
        tmp_path / "collect",
        "--collect-only",
        "-q",
        site_packages=installed_broken_probe,
    )
    assert collected(registered.stdout, CONFORMANCE_SUITE, BROKEN_ENGINE_ID), "accepted by the registry, or it proves nothing"  # fmt: skip
    result = run_suite(CONFORMANCE_SUITE, tmp_path / "run", "-q", "-k", BROKEN_ENGINE_ID, site_packages=installed_broken_probe)  # fmt: skip
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
