"""One reading of the tree for the architecture gates.

The package is parsed once per session. Each function below is one relevé of
it: imports, calls, attributes, strings, names a module writes at process
level, environment reads. A gate that judges a syntax pattern is a ``Rule``
with a bad example, so a test can show that the rule flags it.
"""

from __future__ import annotations

import ast
import functools
import pathlib
from collections import defaultdict
from collections.abc import Callable
from typing import NamedTuple

from tools.audit import build_graph as graph

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
PKG_ROOT = REPO_ROOT / "hydromodpy"
FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


def rel(path: pathlib.Path | str) -> str:
    """The path of a file relative to the repository, in POSIX form."""
    return pathlib.Path(path).relative_to(REPO_ROOT).as_posix()


@functools.cache
def files(root: pathlib.Path = PKG_ROOT) -> tuple[pathlib.Path, ...]:
    """Every ``.py`` file under ``root``, sorted, or ``root`` itself when it is a file."""
    if root.is_file():
        return (root,)
    found = sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)
    return tuple(found)


@functools.cache
def tree(path: pathlib.Path) -> ast.Module:
    """The syntax tree of one file, parsed once."""
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def parse(source: str) -> ast.Module:
    """The syntax tree of a source text, for the bad example of a rule."""
    return ast.parse(source)


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------


@functools.cache
def package_edges() -> tuple[graph.Edge, ...]:
    """One import edge per import of ``hydromodpy/``, from one slow scan."""
    return tuple(graph.scan_package(PKG_ROOT))


def edges_under(root: pathlib.Path) -> list[graph.Edge]:
    """The edges whose source file sits under ``root``."""
    return [e for e in package_edges() if pathlib.Path(e.src_file).is_relative_to(root)]


def sibling_packages() -> frozenset[str]:
    return graph.sibling_packages(PKG_ROOT)


def sibling_edges(name: str) -> list[graph.Edge]:
    return graph.scan_sibling(name, PKG_ROOT)


def edge(src: str, target: str, **kw) -> graph.Edge:
    """An import edge made by hand, for the bad example of a gate."""
    fields = {
        "src_pkg": "core",
        "src_module": src.removesuffix(".py").replace("/", "."),
        "lineno": 1,
        "kind": "import",
        "tgt_pkg": "core",
        "in_function": False,
        "in_type_checking": False,
        **kw,
    }
    return graph.Edge(src_file=str(REPO_ROOT / src), target_module=target, **fields)


def imported_modules(node: ast.AST) -> list[str]:
    """The dotted module names an import statement names, absolute forms only."""
    if isinstance(node, ast.Import):
        return [str(alias.name) for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.module and not node.level:
        return [str(node.module)]
    return []


# ---------------------------------------------------------------------------
# Calls, assignments, names, strings
# ---------------------------------------------------------------------------


def called_name(node: ast.Call) -> str | None:
    """The last name of a call: ``entry_points`` for ``metadata.entry_points(...)``."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def calls(t: ast.AST, name: str) -> list[ast.Call]:
    return [n for n in ast.walk(t) if isinstance(n, ast.Call) and called_name(n) == name]


def module_assignments(t: ast.Module) -> dict[str, int]:
    """Module-level names bound by an assignment, with their line."""
    names: dict[str, int] = {}
    for node in t.body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        names.update({x.id: node.lineno for x in targets if isinstance(x, ast.Name)})
    return names


def names_in(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def unwrap(node: ast.expr) -> ast.expr:
    """Look through a walrus binding at the expression it carries."""
    return node.value if isinstance(node, ast.NamedExpr) else node


def getattr_read(node: ast.AST) -> tuple[ast.expr, str] | None:
    """``(receiver, name)`` when ``node`` is ``getattr(receiver, "name", ...)``."""
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
        return None
    if node.func.id != "getattr" or len(node.args) < 2:
        return None
    name = node.args[1]
    if not isinstance(name, ast.Constant) or not isinstance(name.value, str):
        return None
    return unwrap(node.args[0]), name.value


def member_read(node: ast.AST) -> tuple[ast.expr, str] | None:
    """``(receiver, member)`` for ``receiver.member`` and ``getattr(receiver, "member")``."""
    if isinstance(node, ast.Attribute):
        return unwrap(node.value), node.attr
    return getattr_read(node)


class Str(NamedTuple):
    line: int
    value: str
    in_table: bool
    """True under a module-level assignment or as the default of a parameter."""


def strings(t: ast.Module) -> list[Str]:
    """The string constants of a module that are not documentation.

    A string that stands alone as a statement is documentation, wherever it is.
    """
    alone = {id(n.value) for n in ast.walk(t) if isinstance(n, ast.Expr)}
    table: set[int] = set()
    for fn in ast.walk(t):
        if isinstance(fn, FunctionNode):
            table |= {id(d) for d in (*fn.args.defaults, *fn.args.kw_defaults) if d is not None}
    for statement in t.body:
        if isinstance(statement, ast.Assign | ast.AnnAssign):
            table |= {id(n) for n in ast.walk(statement)}
    return [
        Str(n.lineno, n.value, id(n) in table)
        for n in ast.walk(t)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in alone
    ]


def private_name(name: str) -> bool:
    return name.startswith("_") and not name.startswith("__")


def private_declared(t: ast.AST) -> set[str]:
    """Private names a module brings into existence, however it does it."""
    declared: set[str] = set()
    for node in ast.walk(t):
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store | ast.Del):
            declared.add(node.attr)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Attribute):
            declared.add(node.target.attr)
        elif isinstance(node, FunctionNode | ast.ClassDef):
            declared.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            declared.add(node.id)
        elif isinstance(node, ast.Import | ast.ImportFrom):
            declared |= {(a.asname or a.name.split(".")[0]) for a in node.names}
        elif (
            isinstance(node, ast.Call)
            and called_name(node) == "setattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        ):
            declared.add(node.args[1].value)
    return {name for name in declared if private_name(name)}


def private_reads(t: ast.AST) -> list[tuple[int, str]]:
    """Private names read off an object that is not the module's own (``self``, ``cls``)."""
    reads: list[tuple[int, str]] = []
    for node in ast.walk(t):
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            own = isinstance(node.value, ast.Name) and node.value.id in {"self", "cls"}
            if private_name(node.attr) and not own:
                reads.append((node.lineno, node.attr))
        else:
            read = getattr_read(node)
            if read is not None and private_name(read[1]):
                reads.append((node.lineno, read[1]))
    return reads


# ---------------------------------------------------------------------------
# What a module writes at process level, and what it reads from the environment
# ---------------------------------------------------------------------------


def _kind_of_call(node: ast.Call) -> str | None:
    function = node.func
    if isinstance(function, ast.Name):
        name, base = function.id, ""
    elif isinstance(function, ast.Attribute):
        name, base = function.attr, ast.unparse(function.value)
    else:
        return None
    if name == "use" and base in ("matplotlib", "mpl"):
        return "matplotlib.use"
    if name == "update" and base.endswith("rcParams"):
        return "rcParams.update"
    if name in ("rc_context", "addHandler", "removeHandler", "catch_warnings", "simplefilter"):
        return name
    if name == "filterwarnings" and base in ("warnings", ""):
        return name
    kinds = {("signal", "signal"): "signal.signal", ("chdir", "os"): "os.chdir"}
    if (name, base) in kinds:
        return kinds[name, base]
    return "sys.path.insert" if (name, base) == ("insert", "sys.path") else None


def globals_written(t: ast.Module, path: str) -> list[tuple[str, str, str]]:
    """Sites that write the state of the whole process, as ``(file, kind, scope)``."""
    found: list[tuple[str, str, str]] = []

    def visit(node: ast.AST, scope: tuple[str, ...]) -> None:
        here = ".".join(scope) or "<module>"
        kind = None
        if isinstance(node, ast.Global):
            kind = "global"
        elif isinstance(node, ast.Call):
            kind = _kind_of_call(node)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Subscript) and ast.unparse(target.value).endswith(
                    "rcParams"
                ):
                    found.append((path, "rcParams[...] =", here))
        if kind:
            found.append((path, kind, here))
        inner = scope + (node.name,) if isinstance(node, FunctionNode | ast.ClassDef) else scope
        for child in ast.iter_child_nodes(node):
            visit(child, inner)

    visit(t, ())
    return found


def env_reads(t: ast.Module) -> list[tuple[str, str]]:
    """The ``(kind, variable)`` pairs a module touches ``os.environ`` with.

    A subscript or attribute read is a read, a subscript store or del and the
    putenv and pop calls are writes, and the whole ``os.environ`` object passed
    somewhere is a pass.
    """
    constants: dict[str, str] = {}
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(t):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str):
                constants.update(
                    {x.id: node.value.value for x in node.targets if isinstance(x, ast.Name)}
                )
        parents.update({child: node for child in ast.iter_child_nodes(node)})

    def is_os(node: ast.AST, attr: str) -> bool:
        return (
            isinstance(node, ast.Attribute)
            and node.attr == attr
            and isinstance(node.value, ast.Name)
            and node.value.id == "os"
        )

    def name_of(node: ast.AST) -> str:
        if isinstance(node, ast.Constant):
            return str(node.value)
        if isinstance(node, ast.Name):
            return constants.get(node.id, f"<{node.id}>")
        return f"<{ast.unparse(node)}>" if isinstance(node, ast.Attribute) else "<expr>"

    sites: list[tuple[str, str]] = []
    for node in ast.walk(t):
        kind = variable = None
        if is_os(node, "environ"):
            parent = parents.get(node)
            if isinstance(parent, ast.Attribute) and parent.attr in ("get", "pop", "setdefault"):
                call = parents.get(parent)
                if isinstance(call, ast.Call) and call.args:
                    variable = name_of(call.args[0])
                    kind = "read" if parent.attr == "get" else "write"
            elif isinstance(parent, ast.Subscript):
                variable = name_of(parent.slice)
                kind = "read" if isinstance(parent.ctx, ast.Load) else "write"
            elif isinstance(parent, ast.Compare):
                kind, variable = "read", name_of(parent.left)
            else:
                kind, variable = "pass", "<whole>"
        elif isinstance(node, ast.Call) and (
            is_os(node.func, "getenv") or is_os(node.func, "putenv")
        ):
            kind = "read" if node.func.attr == "getenv" else "write"  # type: ignore[union-attr]
            variable = name_of(node.args[0]) if node.args else "<expr>"
        if kind and variable:
            sites.append((kind, variable))
    return sites


# ---------------------------------------------------------------------------
# A rule is a pattern of the syntax tree with a bad example
# ---------------------------------------------------------------------------


class Rule(NamedTuple):
    """A pattern of the syntax tree the code must never show.

    ``judge(tree, path)`` returns one text per offence of one module. ``scope``
    lists the path prefixes of the files the rule reads. ``bad`` is a few lines
    of source, and ``bad_at`` the path it pretends to sit at: the rule must flag
    it, which proves the gate is not empty without a mutation run.
    """

    id: str
    scope: tuple[str, ...]
    judge: Callable[[ast.Module, str], list[str]]
    bad: str
    bad_at: str


def scoped_files(scope: tuple[str, ...]) -> list[pathlib.Path]:
    """The Python files of the repository under the path prefixes of ``scope``."""
    found: dict[pathlib.Path, None] = {}
    for prefix in scope:
        target = REPO_ROOT / prefix
        found.update(dict.fromkeys(files(target) if target.exists() else ()))
    return list(found)


def offences(rule: Rule) -> list[str]:
    """Every offence of a rule over its scope, as ``file:what``."""
    out: dict[str, list[str]] = defaultdict(list)
    for path in scoped_files(rule.scope):
        out[rel(path)] = rule.judge(tree(path), rel(path))
    return [f"{path}:{what}" for path, found in out.items() for what in found]
