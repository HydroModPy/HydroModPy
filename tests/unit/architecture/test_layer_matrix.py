"""Enforce the layer-matrix contract documented in
``docs/developers/architecture.md``.

The layer matrix is a release gate: undocumented cross-layer imports fail
the suite. Documented tolerances live in ``layer_matrix.yaml`` and must carry
an explicit rationale.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
PKG_ROOT = REPO_ROOT / "hydromodpy"
MATRIX_FILE = pathlib.Path(__file__).with_name("layer_matrix.yaml")

_BUILD_GRAPH_PATH = REPO_ROOT / "tools" / "audit" / "build_graph.py"
_BUILD_GRAPH_SPEC = importlib.util.spec_from_file_location(
    "hydromodpy_architecture_build_graph",
    _BUILD_GRAPH_PATH,
)
if _BUILD_GRAPH_SPEC is None or _BUILD_GRAPH_SPEC.loader is None:
    raise RuntimeError(f"Could not load architecture scanner at {_BUILD_GRAPH_PATH}")
_BUILD_GRAPH_MODULE = importlib.util.module_from_spec(_BUILD_GRAPH_SPEC)
_BUILD_GRAPH_SPEC.loader.exec_module(_BUILD_GRAPH_MODULE)

scan_package = _BUILD_GRAPH_MODULE.scan_package


def _load_matrix() -> dict:
    return yaml.safe_load(MATRIX_FILE.read_text(encoding="utf-8"))


def _violations() -> tuple[list, list]:
    matrix = _load_matrix()
    allowed: dict[str, set[str]] = {k: set(v) for k, v in matrix["allowed"].items()}
    tolerances: set[tuple[str, str]] = {
        (entry["src"], entry["tgt"]) for entry in matrix.get("tolerances", [])
    }
    exempt_files: set[str] = set(matrix.get("exempt_files", []))

    edges = scan_package(PKG_ROOT)
    p0: list = []
    annex: list = []
    for edge in edges:
        rel = pathlib.Path(edge.src_file).relative_to(REPO_ROOT).as_posix()
        if rel in exempt_files:
            continue
        if edge.tgt_pkg == "<annex>":
            annex.append(edge)
            continue
        if edge.src_pkg not in allowed:
            continue
        if edge.tgt_pkg in allowed[edge.src_pkg]:
            continue
        if (edge.src_pkg, edge.tgt_pkg) in tolerances:
            continue
        p0.append(edge)
    return p0, annex


def test_layer_matrix() -> None:
    """Reject undocumented forbidden cross-layer imports."""
    p0, _ = _violations()
    if p0:
        from collections import Counter

        per_pair = Counter((e.src_pkg, e.tgt_pkg) for e in p0)
        breakdown = "\n".join(f"  {s:>12} -> {t:<12} {n}" for (s, t), n in per_pair.most_common())
        pytest.fail(f"{len(p0)} layer-matrix violations:\n{breakdown}")


def test_annex_one_way() -> None:
    """``hydromodpy/`` must never import from ``hydromodpy_annex/``."""
    _, annex = _violations()
    assert annex == [], "\n".join(
        f"{e.src_file}:{e.lineno} imports {e.target_module}" for e in annex
    )
