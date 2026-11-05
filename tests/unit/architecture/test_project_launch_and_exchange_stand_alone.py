"""``project/launch`` and ``project/exchange`` import no other part of ``project``.

``project_layout.yaml`` cannot describe this package: ``facade.py`` imports
``accessors.py`` and ``accessors.py`` imports ``facade.py`` back, as do ``runner``,
``calibrate``, ``phases`` and ``spinup``, and a layout row may name only rows
above it. The two launcher and exchange sub-packages do stand apart, and this
gate holds that: neither reaches ``Project``, its facade, its runner, or the
other sub-package. Every import counts, deferred ones and ``TYPE_CHECKING`` ones.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

pytestmark = pytest.mark.xdist_group("project_stand_alone_scan")

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
PKG_ROOT = REPO_ROOT / "hydromodpy"
PROJECT = "hydromodpy.project"

_BUILD_GRAPH_PATH = REPO_ROOT / "tools" / "audit" / "build_graph.py"
_BUILD_GRAPH_SPEC = importlib.util.spec_from_file_location(
    "hydromodpy_project_build_graph", _BUILD_GRAPH_PATH
)
if _BUILD_GRAPH_SPEC is None or _BUILD_GRAPH_SPEC.loader is None:
    raise RuntimeError(f"Could not load architecture scanner at {_BUILD_GRAPH_PATH}")
_BUILD_GRAPH_MODULE = importlib.util.module_from_spec(_BUILD_GRAPH_SPEC)
sys.modules[_BUILD_GRAPH_SPEC.name] = _BUILD_GRAPH_MODULE
_BUILD_GRAPH_SPEC.loader.exec_module(_BUILD_GRAPH_MODULE)


@pytest.fixture(scope="module")
def project_edges() -> list:
    """Every import that starts in ``hydromodpy/project``, from one scan (the scan is slow)."""
    root = PKG_ROOT / "project"
    return [
        edge
        for edge in _BUILD_GRAPH_MODULE.scan_package(PKG_ROOT)
        if pathlib.Path(edge.src_file).is_relative_to(root)
    ]


def _in_project(module: str) -> bool:
    return module == PROJECT or module.startswith(PROJECT + ".")


def _in_part(module: str, part: str) -> bool:
    return module == f"{PROJECT}.{part}" or module.startswith(f"{PROJECT}.{part}.")


@pytest.mark.parametrize("part", ["launch", "exchange"])
def test_a_standalone_part_imports_only_itself_inside_project(part: str, project_edges) -> None:
    from_part = [
        edge
        for edge in project_edges
        if pathlib.Path(edge.src_file).is_relative_to(PKG_ROOT / "project" / part)
    ]
    # Anti-vacuity: an empty scan would make the assertion below pass.
    assert len(from_part) > 5
    assert any(edge.target_module.startswith("hydromodpy.core") for edge in from_part)
    offenders = [
        f"{pathlib.Path(edge.src_file).relative_to(REPO_ROOT).as_posix()}:{edge.lineno} "
        f"imports {edge.target_module}"
        for edge in from_part
        if _in_project(edge.target_module) and not _in_part(edge.target_module, part)
    ]
    assert not offenders, (
        f"hydromodpy/project/{part} must not import another part of hydromodpy/project, "
        "least of all the facade or anything that reads Project:\n  " + "\n  ".join(offenders)
    )
