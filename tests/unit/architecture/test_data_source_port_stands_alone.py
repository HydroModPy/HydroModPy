"""The data-source package must not import a manager, a catalog or a workspace.

The port's docstring promises a third-party source that it needs no import of
HydroModPy beyond the port module and ``data.contracts``. The reconnaissance of
F5 measured what that promise is worth: the fetch functions under
``data/variables/*/apis/`` are already clean, and everything a capability is
forbidden to touch -- the DuckDB catalogue, the project workspace, the lock
file, the ``geographic`` object -- lives in the manager constructors and in
the station cache of ``BaseVariableManager``, which wrap them. An adapter that
reached for a manager to get at its provider would drag all four back in, one
import at a time.

``layer_matrix.yaml`` cannot see that: it declares ``data`` as one layer, so
``data.source -> data.managers`` and ``data.source -> data.registry`` are
intra-layer edges it allows. This module is the gate for the promise instead,
on the pattern D46 set for the terrain port, and it reads the same scanner the
matrix uses -- so an import deferred inside a method is caught like a top-level
one.

The six built-in sources used to be adapters in this package, each allowed one
deferred import of its provider. They now live in the provider's module, so
``data/source`` holds the port and the registry and takes no exception at all;
the provider modules are held to the forbidden list and to deferring their
heavy libraries.
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

FORBIDDEN_NEIGHBOURS = (
    "hydromodpy.data.managers",
    "hydromodpy.data.registry",
    "hydromodpy.data.loading",
    "hydromodpy.catalog",
    "hydromodpy.workflow",
    "hydromodpy.project",
)
"""What the reconnaissance found the forbidden state behind, named one by one.

``data/source`` is held to :data:`ALLOWED_PREFIXES`, which already excludes
them. The six built-in sources live in their provider's module under
``data/variables/<v>/apis/``, which may read the rest of ``data``: this list is
what they may still not reach.
"""

HEAVY_LIBRARIES = frozenset({"geopandas", "pandas", "rasterio", "shapely", "xarray"})
"""What resolving a source by name must not load.

``requests`` is left out because ``import hydromodpy`` already loads it, so a
delta measured after that import cannot see it either way.
"""


def _source_edges() -> list:
    return [
        edge
        for edge in scan_package(PKG_ROOT)
        if pathlib.Path(edge.src_file).is_relative_to(SOURCE_ROOT)
    ]


def _builtin_provider_files() -> set[str]:
    return {m.replace(".", "/") + ".py" for m in _builtin_provider_modules()}


def _relative(edge) -> str:
    return pathlib.Path(edge.src_file).relative_to(REPO_ROOT).as_posix()


def _is_allowed(module: str) -> bool:
    return any(module == prefix or module.startswith(prefix + ".") for prefix in ALLOWED_PREFIXES)


def test_the_scanner_sees_the_data_source_package() -> None:
    """Anti-vacuity: an empty scan would make every assertion below pass."""
    edges = _source_edges()
    files = {_relative(edge) for edge in edges}
    assert "hydromodpy/data/source/port.py" in files
    assert "hydromodpy/data/source/registry.py" in files
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


def _builtin_provider_modules() -> set[str]:
    from hydromodpy.data.source import registry

    return {path.split(":", 1)[0] for path in registry._BUILTIN_PATHS.values()}


def _names_a_builtin_by_text(edge) -> bool:
    """The one exception: the registry and the package table name the six by text.

    A dotted path in a dict literal is imported on first lookup, never at
    import time, and it is how a third-party class joins the same table.
    """
    return edge.kind == "lazy_map" and edge.target_module in _builtin_provider_modules()


def test_a_source_imports_no_manager_no_catalog_no_workspace() -> None:
    """Every edge of the source package stays inside the port, bar the text paths."""
    offenders = [
        f"{_relative(edge)}:{edge.lineno} imports {edge.target_module}"
        for edge in _source_edges()
        if not _is_allowed(edge.target_module) and not _names_a_builtin_by_text(edge)
    ]
    assert not offenders, (
        "the data-source port promises a source needs nothing of HydroModPy beyond "
        "core, the contracts and the port itself; these imports break that promise:\n  "
        + "\n  ".join(offenders)
    )


def test_a_builtin_source_module_opens_no_forbidden_door() -> None:
    """The six provider modules that hold a source reach no manager, catalog or workspace."""
    provider_files = _builtin_provider_files()
    assert len(provider_files) == 6
    edges = [edge for edge in scan_package(PKG_ROOT) if _relative(edge) in provider_files]
    assert {_relative(edge) for edge in edges} == provider_files, "anti-vacuity"
    offenders = [
        f"{_relative(edge)}:{edge.lineno} imports {edge.target_module}"
        for edge in edges
        for prefix in FORBIDDEN_NEIGHBOURS
        if edge.target_module == prefix or edge.target_module.startswith(prefix + ".")
    ]
    assert not offenders, "a built-in source reaches forbidden state:\n  " + "\n  ".join(offenders)


@pytest.mark.allow_subprocess
def test_every_provider_import_stays_deferred() -> None:
    """Resolving a built-in source by name loads none of its provider's libraries.

    The six built-in classes live beside the functions they serve, in modules
    that import geopandas, pandas, shapely, xarray and rasterio inside those
    functions. Measured one source after another in a fresh interpreter, as the
    delta each lookup adds.
    """
    script = (
        "import json, sys\n"
        "import hydromodpy\n"
        "from hydromodpy.data.source import registry\n"
        "report = {}\n"
        "for source_id in registry.builtin_source_ids():\n"
        "    before = set(sys.modules)\n"
        "    cls = registry.get(source_id)\n"
        "    report[source_id] = [cls.__module__, sorted(set(sys.modules) - before)]\n"
        "print(json.dumps(report))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    )
    report = json.loads(completed.stdout.strip().splitlines()[-1])
    assert len(report) == 6, "anti-vacuity: the registry resolved no built-in"
    loaded = {
        source_id: sorted({name.split(".")[0] for name in added} & HEAVY_LIBRARIES)
        for source_id, (_module, added) in report.items()
    }
    assert all(not heavy for heavy in loaded.values()), f"a lookup loaded {loaded}"


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
