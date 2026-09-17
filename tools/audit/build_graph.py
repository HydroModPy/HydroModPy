"""Build the import graph for hydromodpy at top-level package granularity.

Four mechanisms are resolved, each tagged by the ``kind`` field of an Edge:

- ``from`` / ``import``   static ``import`` and ``from ... import`` statements,
  relative imports resolved against the source module.
- ``import_module``       ``import_module("dotted.path")`` with a literal
  argument, called through a name this file bound at module scope with
  ``from importlib import import_module [as X]``, or as an attribute of a name
  it bound to the ``importlib`` module. The runtime form of an import
  statement.
- ``lazy_map``            a string value of a dict literal that names a
  submodule **that exists on disk**, optionally suffixed ``:Attribute``. This
  is the PEP 562 lazy-attribute map (``_LAZY_IMPORTS``, ``_BUILTIN_PATHS``,
  ``_MODULE_EXPORTS``, ...): a real cross-package edge that no import
  statement declares.

Three narrowings keep a string from minting an edge it does not carry. It must
be the *whole* value, it must name a submodule rather than the bare package
(``{"name": "hydromodpy"}`` in a provenance payload is a tool name), and for a
dict value it must resolve to a module file or package directory. String
arguments of arbitrary calls are deliberately **not** scanned: measured against
this package, that rule reported ``getLogger("hydromodpy.warnings")`` and
``os.path.join("hydromodpy.log")`` as ``core -> <root>`` edges.

What remains, and is accepted: a dict value that names a real module of this
package but is never imported -- an ownership table, a documentation index --
is reported as an edge. The scanner cannot tell that dict from a lazy-attribute
map without trusting a variable name, and naming a module of a forbidden layer
is itself the coupling the matrix exists to catch. Three forms stay invisible
because resolving them would mean guessing: a computed module name,
``import_module(".relative", package=...)``, and a binding this file does not
show, such as ``from importlib import *`` or an alias bound inside a function.
Every one of the 24 bindings in this package is a module-level
``from importlib import import_module``.

A file that does not parse raises :class:`UnparsableSource`. A scanner that
silently skips what it cannot read reports zero violations for the wrong reason.

Library entry points:
    scan_package(pkg_root)            -> list[Edge]
    parse_imports(py, pkg_root)       -> list[(lineno, kind, dotted)]
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
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from functools import cache


class UnparsableSource(Exception):
    """Raised when a file under the scanned package cannot be read or parsed."""


#: A dotted module path, optionally suffixed with ``:Attribute``. Anchored on
#: both ends so only a string that is *entirely* a module reference matches.
DYNAMIC_TARGET_RE = re.compile(
    r"^(?P<module>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)"
    r"(?::[A-Za-z_][A-Za-z0-9_]*)?$"
)


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


@cache
def _top_level_packages(pkg_root: pathlib.Path) -> frozenset[str]:
    return frozenset(
        p.name
        for p in pkg_root.iterdir()
        if p.is_dir() and (p / "__init__.py").is_file() and not p.name.startswith("__")
    )


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


def parse_source(py: pathlib.Path) -> ast.Module:
    """Parse *py*, or raise :class:`UnparsableSource` naming the file.

    Failing loudly is the point: a skipped file is a blind spot that reads
    exactly like a clean file in the gate's output.
    """
    try:
        return ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
    except (SyntaxError, UnicodeDecodeError, ValueError, OSError) as exc:
        raise UnparsableSource(f"{py}: {exc}") from exc


def _module_of_literal(
    value: str,
    pkg_name: str,
    annex_name: str,
    *,
    require_submodule: bool = False,
) -> str | None:
    """Return the module a string literal names, or ``None`` when it names none.

    ``require_submodule`` rejects the bare package name. A dict value of
    exactly ``"hydromodpy"`` is a tool name far more often than an import
    target -- ``results/manifest.py`` writes one into every provenance payload --
    whereas ``import_module("hydromodpy")`` is unambiguous.
    """
    matched = DYNAMIC_TARGET_RE.match(value)
    if matched is None:
        return None
    module = matched.group("module")
    for root in (pkg_name, annex_name):
        if module.startswith(f"{root}."):
            return module
        if module == root and not require_submodule:
            return module
    return None


def _module_exists(module: str, pkg_root: pathlib.Path) -> bool:
    """Return whether *module* resolves to a file or a package on disk.

    The scanned package and its annex are siblings, so one base covers both.
    """
    candidate = pkg_root.parent.joinpath(*module.split("."))
    return (candidate / "__init__.py").is_file() or candidate.with_suffix(".py").is_file()


@dataclass(frozen=True)
class _ImportlibNames:
    """The names a module bound to ``import_module`` and to ``importlib`` itself."""

    functions: frozenset[str]
    modules: frozenset[str]


def _importlib_names(tree: ast.Module) -> _ImportlibNames:
    """Return the module-scope names this file bound to importlib.

    Module scope only, and only names the file actually binds. Seeding the set
    with the bare name would mint an edge from any unrelated function called
    ``import_module``, and honouring a binding made inside one function would
    let a parameter of the same name in another function mint one too.
    """
    functions: set[str] = set()
    modules: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "importlib":
            for alias in node.names:
                if alias.name == "import_module":
                    functions.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "importlib" or alias.name.startswith("importlib."):
                    modules.add(alias.asname or alias.name.split(".")[0])
    return _ImportlibNames(frozenset(functions), frozenset(modules))


def _import_module_literal(node: ast.Call, names: _ImportlibNames) -> str | None:
    """Return the literal argument of an ``import_module`` call, if it has one.

    The receiver of an attribute call is checked, not only its name: an
    unrelated ``loader.import_module(...)`` is not an import of this package.
    """
    func = node.func
    if isinstance(func, ast.Attribute):
        if func.attr != "import_module":
            return None
        if not isinstance(func.value, ast.Name) or func.value.id not in names.modules:
            return None
    elif isinstance(func, ast.Name):
        if func.id not in names.functions:
            return None
    else:
        return None
    argument: ast.expr | None = node.args[0] if node.args else None
    if argument is None:
        argument = next((kw.value for kw in node.keywords if kw.arg == "name"), None)
    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
        return argument.value
    return None


def _import_from_target(
    node: ast.ImportFrom,
    pkg_name: str,
    annex_name: str,
    src_parts: list[str],
) -> str | None:
    """Return the module an ``ImportFrom`` targets, relative imports resolved."""
    if node.level > 0:
        base = src_parts[: -node.level]
        if node.module:
            base = [*base, *node.module.split(".")]
        module = ".".join(base)
    else:
        module = node.module or ""
    if module == pkg_name or module.startswith(f"{pkg_name}.") or module.startswith(annex_name):
        return module
    return None


def _targets(
    tree: ast.Module,
    pkg_root: pathlib.Path,
    src_dotted: str,
) -> list[tuple[ast.AST, int, str, str]]:
    """Return ``(node, lineno, kind, module)`` for every import edge in *tree*.

    The node travels with the edge so the caller can judge the scope it sits in
    from its ancestry rather than from its line number.
    """
    pkg_name = pkg_root.name
    annex_name = f"{pkg_name}_annex"
    src_parts = src_dotted.split(".")
    importlib_names = _importlib_names(tree)
    found: dict[tuple[int, str, str], tuple[ast.AST, int, str, str]] = {}

    def keep(node: ast.AST, lineno: int, kind: str, module: str) -> None:
        found.setdefault((lineno, kind, module), (node, lineno, kind, module))

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = _import_from_target(node, pkg_name, annex_name, src_parts)
            if module is not None:
                keep(node, node.lineno, "from", module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if (
                    name == pkg_name
                    or name.startswith(f"{pkg_name}.")
                    or name.startswith(annex_name)
                ):
                    keep(node, node.lineno, "import", name)
        elif isinstance(node, ast.Call):
            literal = _import_module_literal(node, importlib_names)
            if literal is None:
                continue
            module = _module_of_literal(literal, pkg_name, annex_name)
            if module is not None:
                keep(node, node.lineno, "import_module", module)
        elif isinstance(node, ast.Dict):
            for value in node.values:
                if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                    continue
                module = _module_of_literal(
                    value.value, pkg_name, annex_name, require_submodule=True
                )
                if module is not None and _module_exists(module, pkg_root):
                    keep(value, value.lineno, "lazy_map", module)
    return [found[key] for key in sorted(found)]


def parse_imports(py: pathlib.Path, pkg_root: pathlib.Path) -> list[tuple[int, str, str]]:
    """Return (lineno, kind, module_dotted) for each import targeting pkg_root.

    Covers the static statements, ``import_module`` on a literal, and the
    string values of dict literals. Resolves relative imports against the
    source module path. Also matches ``hydromodpy_annex`` so the one-way rule
    can be checked.
    """
    tree = parse_source(py)
    src_dotted = submodule_path(py, pkg_root)
    return [
        (lineno, kind, module) for _, lineno, kind, module in _targets(tree, pkg_root, src_dotted)
    ]


def _parent_map(tree: ast.AST) -> dict[int, ast.AST]:
    """Map each node's id to its parent, in one pass."""
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    return parents


def _is_type_checking_test(test: ast.expr) -> bool:
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def _scope_flags(node: ast.AST, parents: dict[int, ast.AST]) -> tuple[bool, bool]:
    """Return ``(in_function, in_type_checking)`` from the node's ancestry.

    Ancestry, not line number: two edges can share a line, and the ``else``
    branch of ``if TYPE_CHECKING:`` is ordinary runtime code that a line-keyed
    collector flagged as type-checking only.

    Only the *body* of a function defers. A decorator expression and a default
    argument value are evaluated when the ``def`` is executed, so an import
    written there is as eager as one at module scope -- and eagerness is the
    whole reason the flag exists.
    """
    in_function = False
    in_type_checking = False
    child = node
    parent = parents.get(id(node))
    while parent is not None:
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if any(child is statement for statement in parent.body):
                in_function = True
        elif isinstance(parent, ast.Lambda):
            if child is parent.body:
                in_function = True
        elif isinstance(parent, ast.If) and _is_type_checking_test(parent.test):
            if any(child is statement for statement in parent.body):
                in_type_checking = True
        child = parent
        parent = parents.get(id(parent))
    return in_function, in_type_checking


def _target_package(module: str, pkg_name: str, top_level: frozenset[str]) -> str:
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
        tree = parse_source(py)
        src_module = submodule_path(py, pkg_root)
        targets = _targets(tree, pkg_root, src_module)
        if not targets:
            continue
        parents = _parent_map(tree)
        src_file = str(py)
        for node, lineno, kind, module in targets:
            in_function, in_type_checking = _scope_flags(node, parents)
            edges.append(
                Edge(
                    src_file=src_file,
                    src_pkg=src_pkg,
                    src_module=src_module,
                    lineno=lineno,
                    kind=kind,
                    target_module=module,
                    tgt_pkg=_target_package(module, pkg_root.name, top_level),
                    in_function=in_function,
                    in_type_checking=in_type_checking,
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
