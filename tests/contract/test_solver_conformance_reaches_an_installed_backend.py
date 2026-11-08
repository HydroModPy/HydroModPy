"""The solver conformance suite runs a backend it does not name.

``register()`` certifies a backend on the attributes it declares. Whether each
declared name means something to the build (a mesh engine, a stored field, a
trait of the ``Model``, an extractor for its key) is only seen by
``tests/contract/test_solver_backend_contract.py``, so this file installs a
backend the suite has never heard of and runs the suite against it in a
subprocess. The probe solves nothing: what passes here is the plumbing
(discovered under the join of ``process_type`` and ``name``, held to the port),
not a solver. The probe declares a settings class and two traits, so the suite
also shows that the TOML accepts its name, reads its ``[solver.<name>]`` table
by that class, refuses an unknown key of the table, and refuses every trait it
does not list.

Two controls. A probe published under a name that is not that join is ignored,
with a warning naming what the class declares. A probe that declares a stored
name nothing writes passes the registry and fails the suite.

A subprocess, because ``importlib.metadata`` reads the entry points once and the
registries cache them.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from ._installed_probe import REPO_ROOT, collected, run_suite, unpack

# One worker runs the file, so each collection below runs once.
pytestmark = pytest.mark.xdist_group("solver_conformance_probe")

CONFORMANCE_SUITE = "tests/contract/test_solver_backend_contract.py"

PROBE_KEY = "flow_conformance_probe"
"""The key the installed distribution answers to, written nowhere but here."""

BROKEN_KEY = "flow_conformance_probe_unread"

MISNAMED_ENTRY = "flow_conformanceprobe"
"""An entry-point name that drops the underscore of the probe's name."""

PROBE_MODULE = '''\
"""An out-of-tree flow backend and its extractor, as a third party would ship them.

Every attribute of the port is spelled out, so an attribute added to the Protocol
breaks this probe instead of being inherited in silence.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict


class ProbeOptions(BaseModel):
    """The settings of the probe, read from its [solver.conformance_probe] table."""

    model_config = ConfigDict(extra="forbid")

    steps: int = 3


class ProbeFlowAdapter:
    name: ClassVar[str] = "conformance_probe"
    process_type: ClassVar[str] = "flow"
    accepted_meshes: ClassVar[frozenset[str]] = frozenset({"regular"})
    geometry: ClassVar[str] = "cells"
    writes: ClassVar[tuple[str, ...]] = ("head", "budget/recharge", "budgets")
    reads: ClassVar[tuple[str, ...]] = ()
    supports: ClassVar[frozenset[str]] = frozenset({"head_rule", "steady_start"})
    options: ClassVar = ProbeOptions
    category: ClassVar[str] = "distributed"
    native_step: ClassVar = None
    mutable: ClassVar[frozenset[str]] = frozenset()
    requires: ClassVar[tuple[tuple[str, str], ...]] = ()

    def validate(self, ctx):
        raise NotImplementedError

    def execute(self, ctx):
        raise NotImplementedError

    def cleanup(self, ctx):
        raise NotImplementedError

    def extract_observables(self, ctx, store, requests, **kwargs):
        raise NotImplementedError


class ProbeExtractor:
    process_type: ClassVar[str] = "flow"
    solver_name: ClassVar[str] = "conformance_probe"

    def extract(self, *args, **kwargs):
        raise NotImplementedError
'''

BROKEN_PROBE_TAIL = '''

class UnreadFlowAdapter(ProbeFlowAdapter):
    """Passes the registry and declares a field nothing stores. The negative control."""

    name = "conformance_probe_unread"
    writes = ("head", "budget/seepage_to_nowhere")


class UnreadExtractor(ProbeExtractor):
    solver_name = "conformance_probe_unread"
'''


def _publish(root: Path, entry: str, adapter: str, extractor: str, *, tail: str = "") -> Path:
    """Unpack the probe publishing *adapter* under *entry*, and its extractor beside it."""
    unpack(root, "hmp_solver_conformance_probe", PROBE_MODULE + tail, "hydromodpy.solver", entry, adapter)  # fmt: skip
    entry_points = next(root.glob("*.dist-info")) / "entry_points.txt"
    with entry_points.open("a", encoding="utf-8") as stream:
        stream.write(
            f"\n[hydromodpy.solver.extractor]\n{entry} = hmp_solver_conformance_probe:{extractor}\n"
        )
    return root


@pytest.fixture(scope="module")
def installed_probe(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("probe_site_packages")
    return _publish(root, PROBE_KEY, "ProbeFlowAdapter", "ProbeExtractor")


@pytest.fixture(scope="module")
def installed_broken_probe(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("broken_probe_site_packages")
    return _publish(
        root, BROKEN_KEY, "UnreadFlowAdapter", "UnreadExtractor", tail=BROKEN_PROBE_TAIL
    )


@pytest.fixture(scope="module")
def installed_misnamed_probe(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("misnamed_probe_site_packages")
    return _publish(root, MISNAMED_ENTRY, "ProbeFlowAdapter", "ProbeExtractor")


@pytest.fixture(scope="module")
def bare_collection(tmp_path_factory) -> subprocess.CompletedProcess:
    return run_suite(CONFORMANCE_SUITE, tmp_path_factory.mktemp("bare"), "--collect-only", "-q")


@pytest.fixture(scope="module")
def probe_collection(installed_probe, tmp_path_factory) -> subprocess.CompletedProcess:
    session = tmp_path_factory.mktemp("probe_collect")
    return run_suite(
        CONFORMANCE_SUITE, session, "--collect-only", "-q", site_packages=installed_probe
    )


def _names_seen_by_a_child(site_packages: Path) -> subprocess.CompletedProcess:
    """List ``solvers.names("flow")`` and the registry warnings in a child interpreter."""
    script = (
        "import logging, sys\n"
        "from hydromodpy.core import plugin_registry\n"
        "plugin_registry.logger.addHandler(logging.StreamHandler(sys.stdout))\n"
        "from hydromodpy.solver.base.registry import solvers\n"
        "print(' '.join(solvers.names('flow')))\n"
    )
    environment = dict(os.environ)
    entries = [site_packages, REPO_ROOT, environment.get("PYTHONPATH")]
    environment["PYTHONPATH"] = os.pathsep.join(str(entry) for entry in entries if entry)
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(REPO_ROOT),
        env=environment,
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_installing_a_backend_adds_it_to_the_suite(bare_collection, probe_collection) -> None:
    """The probe adds its own parameter set and changes no other node (bare is the control)."""
    without, with_probe = bare_collection, probe_collection
    assert without.returncode == 0, without.stdout[-4000:]
    assert collected(without.stdout, CONFORMANCE_SUITE, PROBE_KEY) == []
    assert with_probe.returncode == 0, with_probe.stdout[-4000:]
    probe_nodes = collected(with_probe.stdout, CONFORMANCE_SUITE, PROBE_KEY)
    assert probe_nodes, with_probe.stdout[-4000:]
    added = len(collected(with_probe.stdout, CONFORMANCE_SUITE)) - len(
        collected(without.stdout, CONFORMANCE_SUITE)
    )
    assert added == len(probe_nodes), "the probe may only add its own parameter set"


PROBE_SETS = (
    "test_the_toml_accepts_the_name_of_each_flow",
    "test_the_settings_of_a_flow_read_back_from_its_own_table",
    "test_an_unknown_key_of_a_flow_table_is_refused",
    "test_a_document_that_uses_a_trait_loads_if_and_only_if_the_flow_lists_it",
    "test_a_transport_loads_if_and_only_if_its_requires_names_the_flow",
)
"""The cases of the suite that read a TOML, which the probe must reach as a flow."""


def test_the_probe_reaches_every_case_that_reads_a_toml(probe_collection) -> None:
    probe_nodes = collected(probe_collection.stdout, CONFORMANCE_SUITE, PROBE_KEY)
    for case in PROBE_SETS:
        assert any(f"::{case}[" in node for node in probe_nodes), case


def test_every_conformance_assertion_passes_against_the_installed_backend(
    installed_probe, probe_collection, tmp_path
) -> None:
    """The gate: the whole parameter set of a backend this file never names."""
    probe_nodes = collected(probe_collection.stdout, CONFORMANCE_SUITE, PROBE_KEY)
    result = run_suite(
        CONFORMANCE_SUITE, tmp_path / "probe", "-q", "-k", PROBE_KEY, site_packages=installed_probe
    )
    assert result.returncode == 0, result.stdout[-8000:]
    passed = re.search(r"(\d+) passed", result.stdout)
    assert passed is not None, result.stdout[-4000:]
    assert int(passed.group(1)) == len(probe_nodes)


def test_a_backend_the_registry_accepts_and_the_store_cannot_read_is_caught(
    installed_broken_probe, tmp_path
) -> None:
    """The negative control: ``register()`` accepts it, and the suite fails it on ``writes``."""
    registered = run_suite(
        CONFORMANCE_SUITE,
        tmp_path / "collect",
        "--collect-only",
        "-q",
        site_packages=installed_broken_probe,
    )
    assert collected(registered.stdout, CONFORMANCE_SUITE, BROKEN_KEY), "accepted by the registry, or it proves nothing"  # fmt: skip
    result = run_suite(CONFORMANCE_SUITE, tmp_path / "run", "-q", "-k", BROKEN_KEY, site_packages=installed_broken_probe)  # fmt: skip
    assert result.returncode != 0
    assert "test_each_written_name_is_known_to_the_store" in result.stdout


def test_an_entry_point_that_does_not_join_the_key_is_ignored_with_its_warning(
    installed_misnamed_probe,
) -> None:
    """``flow_conformanceprobe`` is not ``flow`` joined to ``conformance_probe``: no key is minted."""
    result = _names_seen_by_a_child(installed_misnamed_probe)

    assert result.returncode == 0, result.stderr[-4000:]
    flows = result.stdout.strip().splitlines()[-1].split()
    assert "conformance_probe" not in flows
    assert "conformanceprobe" not in flows
    assert f"the entry-point name is {MISNAMED_ENTRY!r}" in result.stdout
    assert "declares process_type, name = 'flow', 'conformance_probe'" in result.stdout


def test_the_conformance_suite_neither_names_nor_imports_the_backend_it_runs() -> None:
    """The import check is a tripwire (aliases included), not a proof."""
    suite = (REPO_ROOT / CONFORMANCE_SUITE).read_text(encoding="utf-8")
    imported = {
        alias.name.rpartition(".")[2]
        for node in ast.walk(ast.parse(suite))
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    }
    # ``SolverAdapter`` is the Protocol the suite asserts membership of.
    adapters = sorted(
        name for name in imported if name.endswith("Adapter") and name != "SolverAdapter"
    )

    assert "conformance_probe" not in suite
    assert adapters == [], f"the suite imports {adapters} instead of asking the registry"
