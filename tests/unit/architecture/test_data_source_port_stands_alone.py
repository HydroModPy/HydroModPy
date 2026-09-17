"""The data-source package must not import a manager, a catalog or a workspace.

The port's docstring promises a third-party source that it needs no import of
HydroModPy beyond the port module and ``data.contracts``. The reconnaissance of
F5 measured what that promise is worth: the fetch functions under
``data/variables/*/apis/`` are already clean, and everything a capability is
forbidden to touch -- the DuckDB catalogue, the project workspace, the lock
file, the ``geographic`` object -- lives in the manager constructors and in
``fetch_with_smart_cache`` that wrap them. An adapter that reached for a
manager to get at its provider would drag all four back in, one import at a
time.

``layer_matrix.yaml`` cannot see that: it declares ``data`` as one layer, so
``data.source -> data.managers`` and ``data.source -> data.registry`` are
intra-layer edges it allows. This module is the gate for the promise instead,
on the pattern D46 set for the terrain port, and it reads the same scanner the
matrix uses -- so an import deferred inside a method is caught like a top-level
one, and then held to being deferred on purpose.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
PKG_ROOT = REPO_ROOT / "hydromodpy"
SOURCE_ROOT = PKG_ROOT / "data" / "source"

_BUILD_GRAPH_PATH = REPO_ROOT / "tools" / "audit" / "build_graph.py"
_BUILD_GRAPH_SPEC = importlib.util.spec_from_file_location(
    "hydromodpy_data_source_build_graph",
    _BUILD_GRAPH_PATH,
)
if _BUILD_GRAPH_SPEC is None or _BUILD_GRAPH_SPEC.loader is None:
    raise RuntimeError(f"Could not load architecture scanner at {_BUILD_GRAPH_PATH}")
_BUILD_GRAPH_MODULE = importlib.util.module_from_spec(_BUILD_GRAPH_SPEC)
sys.modules[_BUILD_GRAPH_SPEC.name] = _BUILD_GRAPH_MODULE
_BUILD_GRAPH_SPEC.loader.exec_module(_BUILD_GRAPH_MODULE)

scan_package = _BUILD_GRAPH_MODULE.scan_package

ALLOWED_PREFIXES = (
    "hydromodpy.core",
    "hydromodpy.data.contracts",
    "hydromodpy.data.source",
)
"""``core`` is the kernel leaf every layer may read, ``contracts`` holds the
record types a payload is made of, and the rest is the port itself."""

PROVIDER_REASON = (
    "the adapter serves its provider's fetch function, which is the whole point "
    "of the phase. The import is deferred into fetch() so importing the port "
    "pulls in neither the provider's client libraries nor pydantic."
)

DECLARED_EXCEPTIONS: dict[tuple[str, str], str] = {
    (
        "hydromodpy/data/source/bdtopage.py",
        "hydromodpy.data.variables.hydrography.apis.bdtopage",
    ): PROVIDER_REASON,
    (
        "hydromodpy/data/source/bdtopage.py",
        "hydromodpy.data.variables.hydrography.config",
    ): (
        "bdtopage.fetch takes a HydrographySourceConfig and reads two of its nine "
        "fields. The adapter builds one rather than changing the api function, "
        "which keeps its own callers until the capability replaces them."
    ),
    (
        "hydromodpy/data/source/hubeau_piezometry.py",
        "hydromodpy.data.variables.piezometry.apis.hubeau",
    ): PROVIDER_REASON,
    (
        "hydromodpy/data/source/ign_dem.py",
        "hydromodpy.data.variables.dem.apis.ign_dem_fr",
    ): PROVIDER_REASON,
    (
        "hydromodpy/data/source/sim2_precipitation.py",
        "hydromodpy.data.variables.precipitation.apis.sim2",
    ): PROVIDER_REASON,
    (
        "hydromodpy/data/source/sim2_precipitation.py",
        "hydromodpy.data.variables.precipitation.config",
    ): (
        "the nine SIM2 adapters take a per-variable Pydantic config and read at most "
        "one field of it. The adapter builds one rather than changing the api "
        "function, for the reason bdtopage gives above."
    ),
}
"""Every remaining edge out of ``data/source``, each with the reason it is taken.

All four are inside ``fetch``: see
:func:`test_every_provider_import_stays_deferred`.
"""

FORBIDDEN_NEIGHBOURS = (
    "hydromodpy.data.managers",
    "hydromodpy.data.registry",
    "hydromodpy.data.loading",
    "hydromodpy.catalog",
    "hydromodpy.workflow",
    "hydromodpy.project",
)
"""What the reconnaissance found the forbidden state behind, named one by one.

A prefix list on top of :data:`ALLOWED_PREFIXES`, which already excludes them:
this one exists so a future exception added by hand still cannot open one of
these six doors without the test saying which.
"""


def _source_edges() -> list:
    return [
        edge
        for edge in scan_package(PKG_ROOT)
        if pathlib.Path(edge.src_file).is_relative_to(SOURCE_ROOT)
    ]


def _relative(edge) -> str:
    return pathlib.Path(edge.src_file).relative_to(REPO_ROOT).as_posix()


def _is_allowed(module: str) -> bool:
    return any(module == prefix or module.startswith(prefix + ".") for prefix in ALLOWED_PREFIXES)


def test_the_scanner_sees_the_data_source_package() -> None:
    """Anti-vacuity: an empty scan would make every assertion below pass."""
    edges = _source_edges()
    files = {_relative(edge) for edge in edges}
    assert "hydromodpy/data/source/port.py" in files
    assert "hydromodpy/data/source/bdtopage.py" in files
    assert "hydromodpy/data/source/hubeau_piezometry.py" in files
    assert "hydromodpy/data/source/ign_dem.py" in files
    assert "hydromodpy/data/source/sim2_precipitation.py" in files
    assert any(edge.target_module.startswith("hydromodpy.core.") for edge in edges)


def test_the_port_module_itself_imports_only_core() -> None:
    """``port.py`` carries the vocabulary, so it takes no exception at all."""
    offenders = [
        f"{_relative(edge)}:{edge.lineno} imports {edge.target_module}"
        for edge in _source_edges()
        if _relative(edge) == "hydromodpy/data/source/port.py"
        and not edge.target_module.startswith("hydromodpy.core")
        and not edge.target_module.startswith("hydromodpy.data.contracts")
    ]
    assert not offenders, (
        "the port module is what a third-party source imports; these pull more in:\n  "
        + "\n  ".join(offenders)
    )


def test_a_source_imports_no_manager_no_catalog_no_workspace() -> None:
    offenders = [
        f"{_relative(edge)}:{edge.lineno} imports {edge.target_module}"
        for edge in _source_edges()
        if not _is_allowed(edge.target_module)
        and (_relative(edge), edge.target_module) not in DECLARED_EXCEPTIONS
    ]
    assert not offenders, (
        "the data-source port promises a source needs nothing of HydroModPy beyond "
        "core, the contracts and the port itself; these imports break that promise:\n  "
        + "\n  ".join(offenders)
    )


def test_no_declared_exception_opens_a_forbidden_door() -> None:
    """A hand-written exception must not be the way a manager gets back in."""
    offenders = [
        f"{src} imports {module}"
        for (src, module) in DECLARED_EXCEPTIONS
        for prefix in FORBIDDEN_NEIGHBOURS
        if module == prefix or module.startswith(prefix + ".")
    ]
    assert not offenders, f"declared exceptions reaching forbidden state: {offenders}"


def test_every_declared_exception_is_still_taken() -> None:
    """A stale exception protects nothing and hides the next one."""
    taken = {(_relative(edge), edge.target_module) for edge in _source_edges()}
    stale = sorted(key for key in DECLARED_EXCEPTIONS if key not in taken)
    assert not stale, f"declared exceptions no edge takes any more: {stale}"


def test_every_provider_import_stays_deferred() -> None:
    """A module-level provider import would pull its client into the port."""
    provider_edges = [
        edge
        for edge in _source_edges()
        if (_relative(edge), edge.target_module) in DECLARED_EXCEPTIONS
    ]
    assert len(provider_edges) == len(DECLARED_EXCEPTIONS)
    eager = [
        f"{_relative(edge)}:{edge.lineno} imports {edge.target_module} at module level"
        for edge in provider_edges
        if not edge.in_function
    ]
    assert not eager, "\n  ".join(eager)


@pytest.mark.allow_subprocess
def test_importing_the_port_pulls_in_no_provider_library() -> None:
    """Measured as a delta, in a fresh interpreter.

    ``requests`` is already loaded by ``import hydromodpy`` itself, so the
    absolute set says nothing; what this holds is that reaching for the port
    adds none of the six libraries the adapters' providers need.
    """
    script = (
        "import sys, json;"
        "import hydromodpy;"
        "before = set(sys.modules);"
        "import hydromodpy.data.source;"
        "print(json.dumps(sorted(set(sys.modules) - before)))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    )
    added = set(json.loads(completed.stdout.strip().splitlines()[-1]))
    heavy = {"geopandas", "pandas", "xarray", "rasterio", "shapely", "pydantic"}
    assert not (added & heavy), f"importing the port now pulls in {sorted(added & heavy)}"
    assert "hydromodpy.data.source.port" in added, "anti-vacuity: nothing was imported at all"
