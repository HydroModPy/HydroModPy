"""Enforce the machine-readable layer-matrix contract.

The layer matrix is a release gate: undocumented cross-layer imports fail
the suite. ``allowed`` holds the target rows. While packages move,
``transitional`` says what holds today: the rows of packages that leave, the
rows of packages to come, and the imports granted until they move. An entry
the tree no longer needs fails too, so the transitional part only shrinks.
"""

from __future__ import annotations

import ast
import functools
import importlib.util
import pathlib
import sys
from collections import Counter, defaultdict
from typing import Any, NamedTuple

import pytest

from tools.doc_contracts import (
    MAIN_FILE,
    MAIN_KEY,
    ROOT_KEY,
    LayerRows,
    is_package,
    layer_rows,
    load_layer_matrix,
    present_layers,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
PKG_ROOT = REPO_ROOT / "hydromodpy"
ARCHITECTURE_PACKAGES_INDEX = (
    REPO_ROOT / "docs" / "source" / "contribute" / "architecture" / "packages" / "index.rst"
)
# Package pages that describe no package of hydromodpy.
PAGES_WITHOUT_A_ROW = {"index", "validity_frame"}

_BUILD_GRAPH_PATH = REPO_ROOT / "tools" / "audit" / "build_graph.py"
_BUILD_GRAPH_SPEC = importlib.util.spec_from_file_location(
    "hydromodpy_architecture_build_graph",
    _BUILD_GRAPH_PATH,
)
if _BUILD_GRAPH_SPEC is None or _BUILD_GRAPH_SPEC.loader is None:
    raise RuntimeError(f"Could not load architecture scanner at {_BUILD_GRAPH_PATH}")
_BUILD_GRAPH_MODULE = importlib.util.module_from_spec(_BUILD_GRAPH_SPEC)
sys.modules[_BUILD_GRAPH_SPEC.name] = _BUILD_GRAPH_MODULE
_BUILD_GRAPH_SPEC.loader.exec_module(_BUILD_GRAPH_MODULE)

scan_package = _BUILD_GRAPH_MODULE.scan_package
scan_sibling = _BUILD_GRAPH_MODULE.scan_sibling
sibling_packages = _BUILD_GRAPH_MODULE.sibling_packages


class Judgement(NamedTuple):
    """What the matrix makes of every edge of the tree."""

    violations: list[tuple[str, str, Any]]
    siblings: list[Any]
    edges_used: dict[int, set[str]]
    reads_used: dict[str, set[str]]


def _top_level_packages() -> set[str]:
    return {
        path.name
        for path in PKG_ROOT.iterdir()
        if path.is_dir() and (path / "__init__.py").is_file() and not path.name.startswith("__")
    }


def _relative(edge) -> str:
    return pathlib.Path(edge.src_file).relative_to(REPO_ROOT).as_posix()


def judge(matrix: dict[str, Any], edges) -> Judgement:
    """Judge each edge in turn.

    An edge inside one package passes. An edge from a leaving package passes
    when its row reads the target. Otherwise the target row of the source
    must grant it, or a transitional edge of the same pair must, and when
    that entry names files the source file must be one of them.
    """
    rows = layer_rows(matrix)
    tolerances = {(t["src"], t["tgt"]) for t in matrix.get("tolerances") or []}
    exempt = set(matrix.get("exempt_files") or [])
    violations: list[tuple[str, str, Any]] = []
    siblings: list[Any] = []
    edges_used: dict[int, set[str]] = defaultdict(set)
    reads_used: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        rel = _relative(edge)
        if rel in exempt:
            continue
        if edge.tgt_pkg == "<sibling>":
            siblings.append(edge)
            continue
        src = MAIN_KEY if rel == MAIN_FILE else edge.src_pkg
        tgt = edge.tgt_pkg
        if src == tgt:
            continue
        if src in rows.leaving:
            if tgt in (rows.leaving[src].get("reads") or []):
                reads_used[src].add(tgt)
            else:
                violations.append((src, tgt, edge))
            continue
        if tgt in rows.target.get(src, []) or (src, tgt) in tolerances:
            continue
        granted = False
        for index, entry in enumerate(rows.edges):
            files = entry.get("files") or []
            if entry["src"] == src and entry["tgt"] == tgt and (not files or rel in files):
                edges_used[index].add(rel)
                granted = True
        if not granted:
            violations.append((src, tgt, edge))
    return Judgement(violations, siblings, edges_used, reads_used)


@functools.cache
def _judgement() -> Judgement:
    return judge(load_layer_matrix(), scan_package(PKG_ROOT))


def stale_entries(rows: LayerRows, judgement: Judgement) -> list[str]:
    """The transitional entries the tree no longer needs."""
    stale: list[str] = []
    for layer in rows.leaving:
        if not is_package(layer):
            stale.append(f"leaving {layer!r}: the package is gone")
    for layer in rows.arriving:
        if is_package(layer):
            stale.append(f"arriving {layer!r}: the package exists, its row now holds")
    for index, entry in enumerate(rows.edges):
        src, tgt = entry["src"], entry["tgt"]
        if src in rows.arriving or tgt in rows.arriving:
            continue
        used = judgement.edges_used.get(index, set())
        if not used:
            stale.append(f"edge {src} -> {tgt}: no import makes it any more")
            continue
        for rel in entry.get("files") or []:
            if rel not in used:
                stale.append(f"edge {src} -> {tgt}: {rel} no longer makes it")
    for layer, entry in rows.leaving.items():
        for target in entry.get("reads") or []:
            if target != layer and target not in judgement.reads_used.get(layer, set()):
                stale.append(f"leaving {layer!r} reads {target!r}: no import uses it")
    return stale


def test_layer_matrix() -> None:
    """Reject undocumented forbidden cross-layer imports."""
    violations = _judgement().violations
    if violations:
        per_pair = Counter((s, t, edge.kind) for s, t, edge in violations)
        breakdown = "\n".join(
            f"  {s:>12} -> {t:<12} {n:>4}  via {k}" for (s, t, k), n in per_pair.most_common()
        )
        examples = "\n".join(
            f"  {_relative(edge)}:{edge.lineno} imports {edge.target_module}"
            for _s, _t, edge in violations[:20]
        )
        pytest.fail(f"{len(violations)} layer-matrix violations:\n{breakdown}\n{examples}")


def test_a_transitional_entry_is_still_needed() -> None:
    """A move that empties a package removes its entries in the same change."""
    stale = stale_entries(layer_rows(load_layer_matrix()), _judgement())
    assert stale == [], (
        "remove these entries from transitional in layer_matrix.yaml:\n  " + "\n  ".join(stale)
    )


def test_layer_matrix_declares_every_top_level_package() -> None:
    """Reject stale or missing rows in the machine-readable layer matrix."""
    declared = present_layers(load_layer_matrix()) - {ROOT_KEY}
    actual = _top_level_packages()
    missing = sorted(actual - declared)
    stale = sorted(declared - actual)
    assert missing == [], f"Top-level packages missing from layer matrix: {missing}"
    assert stale == [], f"Layer matrix rows without a package: {stale}"


def test_layer_tolerances_reference_declared_layers() -> None:
    """Reject tolerance entries for unknown layers."""
    matrix = load_layer_matrix()
    declared = set(matrix["allowed"])
    unknown: list[tuple[str, str]] = []
    for entry in matrix.get("tolerances", []):
        pair = (entry["src"], entry["tgt"])
        if pair[0] not in declared or pair[1] not in declared:
            unknown.append(pair)
    assert unknown == []


def test_layer_tolerances_are_not_redundant() -> None:
    """Reject tolerances for edges already allowed by the matrix."""
    matrix = load_layer_matrix()
    allowed: dict[str, set[str]] = {k: set(v) for k, v in matrix["allowed"].items()}
    redundant = sorted(
        (entry["src"], entry["tgt"])
        for entry in matrix.get("tolerances", [])
        if entry["tgt"] in allowed.get(entry["src"], set())
    )
    assert redundant == []


def test_a_row_cites_only_rows_above_it() -> None:
    """Rows run lowest first, so the matrix cannot hide a cycle between layers.

    A leaving row comes after every target row, so it may cite any of them,
    and the leaving rows written above it.
    """
    rows = layer_rows(load_layer_matrix())
    order = [*rows.target, *rows.leaving]
    position = {layer: index for index, layer in enumerate(order)}
    cited = [*rows.target.items(), *((k, v.get("reads") or []) for k, v in rows.leaving.items())]
    backward = {
        (layer, target)
        for layer, targets in cited
        for target in targets
        if position.get(target, len(order)) > position[layer]
    }
    assert backward == set(), f"edges pointing down the file: {sorted(backward)}"


def _package_pages() -> set[str]:
    return {path.stem for path in ARCHITECTURE_PACKAGES_INDEX.parent.glob("*.rst")}


def test_architecture_package_docs_cover_declared_layers() -> None:
    """Reject missing per-package architecture pages."""
    declared = present_layers(load_layer_matrix()) - {ROOT_KEY}
    missing = sorted(declared - _package_pages())
    assert missing == [], f"Missing architecture package pages: {missing}"


def test_every_package_page_has_a_row() -> None:
    """A package that leaves takes its page with it."""
    present = present_layers(load_layer_matrix())
    orphans = sorted(_package_pages() - PAGES_WITHOUT_A_ROW - present)
    assert orphans == [], f"Architecture package pages without a package: {orphans}"


def test_siblings_one_way() -> None:
    """``hydromodpy/`` never imports a folder beside it, such as the annex or the server."""
    siblings = _judgement().siblings
    assert siblings == [], "\n".join(
        f"{e.src_file}:{e.lineno} imports {e.target_module}" for e in siblings
    )


def test_every_sibling_has_a_row() -> None:
    """Each ``hydromodpy_*`` folder on disk has its row in ``siblings``, and each row a folder."""
    rows = set(load_layer_matrix().get("siblings") or {})
    assert rows == set(sibling_packages(PKG_ROOT))


def test_a_sibling_reads_only_its_row() -> None:
    """A sibling whose row is a list imports only the packages of that list."""
    outside = [
        f"{_relative(edge)}:{edge.lineno} imports {edge.target_module}"
        for name, row in (load_layer_matrix().get("siblings") or {}).items()
        if row != "*"
        for edge in scan_sibling(name, PKG_ROOT)
        if edge.target_module.split(".")[0] != name and edge.tgt_pkg not in row
    ]
    assert outside == [], "\n".join(outside)


def _imports_of_tools(path: pathlib.Path) -> list[str]:
    """Return ``line: module`` for each import of ``tools`` written in ``path``."""
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules = [node.module]
        elif (
            isinstance(node, ast.Call)
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and getattr(node.func, "attr", getattr(node.func, "id", None)) == "import_module"
        ):
            modules = [node.args[0].value]
        else:
            continue
        found += [f"{node.lineno}: {m}" for m in modules if m == "tools" or m.startswith("tools.")]
    return found


def test_the_wheel_never_imports_tools() -> None:
    """``tools/`` reads ``hydromodpy/``, never the reverse: the wheel does not ship it."""
    offenders = [
        f"{path.relative_to(REPO_ROOT).as_posix()}:{hit}"
        for path in sorted(PKG_ROOT.rglob("*.py"))
        for hit in _imports_of_tools(path)
    ]
    assert offenders == [], "\n".join(offenders)
