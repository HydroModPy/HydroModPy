"""Build the import graph for hydromodpy at top-level package granularity.

Library entry points:
    scan_package(pkg_root)            -> list[Edge]
    parse_imports(py)                 -> list[(lineno, kind, dotted)]
    package_of(py, pkg_root)          -> str | None
    submodule_path(py, pkg_root)      -> str

CLI entry point (kept for ad-hoc audits):
    python -m tools.audit.build_graph [pkg_root [out_dir]]

Outputs (CLI mode only):
- 06_import_graph.json: full edge list with file:line, source/target package.
- 06_summary.md: human-readable counts.
"""

from __future__ import annotations

import ast
import json
import pathlib
import sys
from collections import Counter
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Edge:
    """One import edge, keyed by source file and target dotted module."""

    src_file: str
    src_pkg: str
    src_module: str
    lineno: int
    kind: str
    target_module: str
    tgt_pkg: str
    in_function: bool
    in_type_checking: bool


def _top_level_packages(pkg_root: pathlib.Path) -> set[str]:
    return {
        p.name
        for p in pkg_root.iterdir()
        if p.is_dir() and (p / "__init__.py").is_file() and not p.name.startswith("__")
    }


def package_of(path: pathlib.Path, pkg_root: pathlib.Path) -> str | None:
    """Return the top-level package this .py file belongs to.

    Files directly under pkg_root (e.g. project.py, __init__.py) are
    treated as belonging to '<root>'.
    """
    rel = path.relative_to(pkg_root)
    parts = rel.parts
    if len(parts) == 1:
        return "<root>"
    head = parts[0]
    if head in _top_level_packages(pkg_root):
        return head
    return None


def submodule_path(path: pathlib.Path, pkg_root: pathlib.Path) -> str:
    return ".".join([pkg_root.name, *path.relative_to(pkg_root).with_suffix("").parts])


def parse_imports(py: pathlib.Path, pkg_root: pathlib.Path) -> list[tuple[int, str, str]]:
    """Return (lineno, kind, module_dotted) for each absolute import targeting pkg_root.

    Resolves relative imports against the source module path. Also matches
    ``hydromodpy_annex`` so the one-way rule can be checked.
    """
    pkg_name = pkg_root.name
    annex_name = f"{pkg_name}_annex"
    edges: list[tuple[int, str, str]] = []
    try:
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
    except (SyntaxError, UnicodeDecodeError):
        return edges

    src_dotted = submodule_path(py, pkg_root)
    src_parts = src_dotted.split(".")

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level > 0:
                base = src_parts[: -node.level]
                if node.module:
                    base = [*base, *node.module.split(".")]
                module = ".".join(base)
            else:
                module = node.module or ""
            if module.startswith(f"{pkg_name}.") or module == pkg_name:
                edges.append((node.lineno, "from", module))
            elif module.startswith(annex_name):
                edges.append((node.lineno, "from", module))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if name.startswith(f"{pkg_name}.") or name == pkg_name:
                    edges.append((node.lineno, "import", name))
                elif name.startswith(annex_name):
                    edges.append((node.lineno, "import", name))
    return edges


def _collect_in_function_lines(tree: ast.AST) -> set[int]:
    in_func: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(node):
                if isinstance(child, (ast.Import, ast.ImportFrom)):
                    in_func.add(child.lineno)
    return in_func


def _collect_type_checking_lines(tree: ast.AST) -> set[int]:
    in_tc: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test = node.test
            is_tc = False
            if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
                is_tc = True
            elif isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING":
                is_tc = True
            if is_tc:
                for child in ast.walk(node):
                    if isinstance(child, (ast.Import, ast.ImportFrom)):
                        in_tc.add(child.lineno)
    return in_tc


def _target_package(module: str, pkg_name: str, top_level: set[str]) -> str:
    if module == pkg_name:
        return "<root>"
    if module.startswith(f"{pkg_name}_annex"):
        return "<annex>"
    parts = module.split(".")
    if len(parts) < 2:
        return "<root>"
    head = parts[1]
    return head if head in top_level else "<root>"


def scan_package(pkg_root: pathlib.Path) -> list[Edge]:
    """Scan every .py file under ``pkg_root`` and return one Edge per import."""
    top_level = _top_level_packages(pkg_root)
    edges: list[Edge] = []
    for py in sorted(pkg_root.rglob("*.py")):
        if "__pycache__" in py.parts:
            continue
        src_pkg = package_of(py, pkg_root)
        if src_pkg is None:
            continue
        raw = parse_imports(py, pkg_root)
        if not raw:
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        except (SyntaxError, UnicodeDecodeError):
            continue
        in_func = _collect_in_function_lines(tree)
        in_tc = _collect_type_checking_lines(tree)
        src_module = submodule_path(py, pkg_root)
        src_file = str(py)
        for lineno, kind, module in raw:
            edges.append(
                Edge(
                    src_file=src_file,
                    src_pkg=src_pkg,
                    src_module=src_module,
                    lineno=lineno,
                    kind=kind,
                    target_module=module,
                    tgt_pkg=_target_package(module, pkg_root.name, top_level),
                    in_function=lineno in in_func,
                    in_type_checking=lineno in in_tc,
                )
            )
    return edges


def _main(argv: list[str]) -> None:
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    pkg_root = pathlib.Path(argv[1]) if len(argv) > 1 else repo_root / "hydromodpy"
    out_dir = pathlib.Path(argv[2]) if len(argv) > 2 else repo_root / "meta_review_output"
    out_dir.mkdir(parents=True, exist_ok=True)

    edges = scan_package(pkg_root)
    counts: Counter[tuple[str, str]] = Counter((e.src_pkg, e.tgt_pkg) for e in edges)

    (out_dir / "06_import_graph.json").write_text(
        json.dumps(
            {
                "edges": [asdict(e) for e in edges],
                "counts": [
                    {"src": s, "tgt": t, "count": n}
                    for (s, t), n in sorted(counts.items(), key=lambda kv: -kv[1])
                ],
            },
            indent=2,
        )
    )
    print(f"Files scanned (package): {pkg_root}")
    print(f"Edges: {len(edges)}")
    for (s, t), n in counts.most_common(20):
        print(f"  {s:>14} -> {t:<14} {n}")


if __name__ == "__main__":
    _main(sys.argv)
