"""The terrain package must not import a sibling of ``spatial``.

The port's docstring promises a third-party engine that it needs no import of
HydroModPy beyond the port module itself. Two imports denied it until F3c:
``numpy_engine`` read the D8 offset table from ``spatial.geographic.core.d8``
and ``whitebox_engine`` read ``ensure_crs`` from ``spatial.geographic``. Both
symbols were misplaced rather than shared, and both moved -- the table to the
port that names its convention, the CRS stamp to ``core.io``.

The layer matrix cannot see that cycle: it declares ``spatial`` as one layer,
so ``terrain -> geographic`` and ``geographic -> terrain`` are both intra-layer
edges it allows. This module is the gate for the promise instead, and it reads
the same scanner the matrix uses, so a deferred import inside a function is
caught like a top-level one.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
PKG_ROOT = REPO_ROOT / "hydromodpy"
TERRAIN_ROOT = PKG_ROOT / "spatial" / "terrain"

_BUILD_GRAPH_PATH = REPO_ROOT / "tools" / "audit" / "build_graph.py"
_BUILD_GRAPH_SPEC = importlib.util.spec_from_file_location(
    "hydromodpy_terrain_build_graph",
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
    "hydromodpy.spatial.terrain",
)
"""``core`` is the kernel leaf every layer may read; the rest is the port itself."""

DECLARED_EXCEPTIONS: dict[tuple[str, str], str] = {
    (
        "hydromodpy/spatial/terrain/whitebox_engine.py",
        "hydromodpy.spatial.delineation",
    ): (
        "D43: the injection point stays the Whitebox backend, which the geographic "
        "pipeline holds and passes to a dozen calls the port does not cover. The "
        "engine resolves it lazily, inside a method, so a third-party engine never "
        "loads this module."
    ),
}
"""Every remaining edge out of ``terrain``, each with the decision that allows it."""


def _terrain_edges() -> list:
    return [
        edge
        for edge in scan_package(PKG_ROOT)
        if pathlib.Path(edge.src_file).is_relative_to(TERRAIN_ROOT)
    ]


def _relative(edge) -> str:
    return pathlib.Path(edge.src_file).relative_to(REPO_ROOT).as_posix()


def _is_allowed(module: str) -> bool:
    return any(module == prefix or module.startswith(prefix + ".") for prefix in ALLOWED_PREFIXES)


def test_the_scanner_sees_the_terrain_package() -> None:
    """Anti-vacuity: an empty scan would make every assertion below pass."""
    edges = _terrain_edges()
    files = {_relative(edge) for edge in edges}
    assert "hydromodpy/spatial/terrain/port.py" in files
    assert "hydromodpy/spatial/terrain/numpy_engine.py" in files
    assert "hydromodpy/spatial/terrain/whitebox_engine.py" in files
    assert any(edge.target_module.startswith("hydromodpy.core.") for edge in edges)


def test_terrain_imports_no_sibling_of_spatial() -> None:
    offenders = [
        f"{_relative(edge)}:{edge.lineno} imports {edge.target_module}"
        for edge in _terrain_edges()
        if not _is_allowed(edge.target_module)
        and (_relative(edge), edge.target_module) not in DECLARED_EXCEPTIONS
    ]
    assert not offenders, (
        "the terrain port promises an engine needs nothing of HydroModPy beyond "
        "core and the port itself; these imports break that promise:\n  " + "\n  ".join(offenders)
    )


def test_every_declared_exception_is_still_taken() -> None:
    """A stale exception protects nothing and hides the next one."""
    taken = {(_relative(edge), edge.target_module) for edge in _terrain_edges()}
    stale = sorted(key for key in DECLARED_EXCEPTIONS if key not in taken)
    assert not stale, f"declared exceptions no edge takes any more: {stale}"


def test_the_whitebox_backend_import_stays_deferred() -> None:
    """A module-level import of the backend would pull Whitebox into the port."""
    backend_edges = [
        edge
        for edge in _terrain_edges()
        if edge.target_module.startswith("hydromodpy.spatial.delineation")
    ]
    assert backend_edges, "the Whitebox engine no longer resolves its backend"
    assert all(edge.in_function for edge in backend_edges), (
        "the Whitebox backend must be resolved inside a method, not at import time"
    )
