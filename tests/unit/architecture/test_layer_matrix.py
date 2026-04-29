"""Enforce the layer-matrix contract documented in
``unified_architecture/20_ENCAPSULATION_AND_COUPLING.md`` §2.

Stage 1: ``test_layer_matrix`` is marked ``xfail`` so it reports the
current violation count without breaking CI. Stage 2 will tighten the
quota; stage 3 will require strict zero (with ``tolerances`` documented).
The annex one-way rule is already satisfied and runs strict.
"""

from __future__ import annotations

import pathlib
import sys

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
PKG_ROOT = REPO_ROOT / "hydromodpy"
MATRIX_FILE = pathlib.Path(__file__).with_name("layer_matrix.yaml")

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.audit.build_graph import scan_package  # noqa: E402


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
        if edge.src_pkg == "<root>" or edge.tgt_pkg == "<root>":
            continue
        if edge.src_pkg not in allowed:
            continue
        if edge.tgt_pkg in allowed[edge.src_pkg]:
            continue
        if (edge.src_pkg, edge.tgt_pkg) in tolerances:
            continue
        p0.append(edge)
    return p0, annex


@pytest.mark.xfail(
    strict=False,
    reason="layer-matrix violations being remediated through R0..R4 (see PLAN_ACTION.md)",
)
def test_layer_matrix() -> None:
    """Report the count of forbidden cross-layer imports.

    Marked xfail until R0..R4 land. The assertion message lists the top
    offending edges so reviewers can track progress.
    """
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
