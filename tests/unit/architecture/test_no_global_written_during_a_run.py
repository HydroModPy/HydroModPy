"""No run writes the state of the whole process.

Two runs in two threads of one process share the environment, the working
directory, the matplotlib backend and ``rcParams``, the handlers of the
``hydromodpy`` logger, the warning filters and the signal handlers. A run that
writes one of them changes the other run (rule 15). ``process_state.yaml``
carries one row per site of ``hydromodpy/`` that can write such a state, each
with its class: set at import, once per process, by the command line, by the
one trial pipeline, under a lock, or a flag that keeps a warning quiet. A site
without a row and a row without a site both fail, so the table only shrinks.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

import yaml

HERE = Path(__file__).parent
REPO = HERE.parents[2]
PACKAGE = REPO / "hydromodpy"
TABLE = yaml.safe_load((HERE / "process_state.yaml").read_text(encoding="utf-8"))

CLASSES = ("import", "process", "cli", "trial_pipeline", "lock", "once", "transitional")
NEVER = ("matplotlib.use", "rcParams[...] =", "rcParams.update", "os.chdir", "sys.path.insert")
"""Kinds no row may carry: a render never switches the backend or leaves a style behind."""

WARNING_KINDS = frozenset({"catch_warnings", "simplefilter"})
HANDLER_KINDS = frozenset({"addHandler", "removeHandler"})


def _text(node: ast.AST) -> str:
    return ast.unparse(node)


def _kind_of_call(node: ast.Call) -> str | None:
    function = node.func
    if isinstance(function, ast.Name):
        name, base = function.id, ""
    elif isinstance(function, ast.Attribute):
        name, base = function.attr, _text(function.value)
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
    if name == "signal" and base == "signal":
        return "signal.signal"
    if name == "chdir" and base == "os":
        return "os.chdir"
    if name == "insert" and base == "sys.path":
        return "sys.path.insert"
    return None


class _Sites(ast.NodeVisitor):
    """Collect the sites of one file as ``(file, kind, scope)``."""

    def __init__(self, relative: str) -> None:
        self.relative = relative
        self.scope: list[str] = []
        self.found: list[tuple[str, str, str]] = []

    def _add(self, kind: str) -> None:
        self.found.append((self.relative, kind, ".".join(self.scope) or "<module>"))

    def _enter(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_FunctionDef = _enter
    visit_AsyncFunctionDef = _enter
    visit_ClassDef = _enter

    def visit_Global(self, node: ast.Global) -> None:
        self._add("global")
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Subscript) and _text(target.value).endswith("rcParams"):
                self._add("rcParams[...] =")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        kind = _kind_of_call(node)
        if kind is not None:
            self._add(kind)
        self.generic_visit(node)


def _scan_package() -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    for path in sorted(PACKAGE.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        relative = path.relative_to(REPO).as_posix()
        visitor = _Sites(relative)
        visitor.visit(ast.parse(path.read_text(encoding="utf-8"), filename=relative))
        found += visitor.found
    return found


def test_every_site_has_its_row_and_every_row_its_site() -> None:
    carried = [(row["file"], row["site"], row["scope"]) for row in TABLE["rows"]]
    found = _scan_package()
    unexpected = sorted(Counter(found) - Counter(carried))
    stale = sorted(Counter(carried) - Counter(found))
    assert not unexpected and not stale, (
        "The sites of hydromodpy/ that write the state of the process and "
        f"process_state.yaml disagree. Sites without a row: {unexpected}. Rows "
        f"without a site: {stale}. A row leaves only with its code, and a new site "
        "needs its row, its class and its why."
    )


def test_rows_carry_a_known_class_and_transitional_ones_name_the_lot() -> None:
    for row in TABLE["rows"]:
        assert row["class"] in CLASSES, f"{row} is not in {CLASSES}"
        if row["class"] == "transitional":
            assert row.get("lifted_by"), f"a transitional row without lifted_by: {row}"
        else:
            assert not row.get("lifted_by"), f"{row['file']} is not transitional: {row}"
        assert len(row["why"].split()) >= 4, f"the why of {row} is too short"


def test_no_render_switches_the_backend_or_writes_rcparams() -> None:
    kinds = {row["site"] for row in TABLE["rows"]}
    assert not kinds & set(NEVER), f"{sorted(kinds & set(NEVER))} write the state of every render"


def test_the_warning_filters_are_set_at_import_or_by_the_command_line() -> None:
    wrong = [
        row
        for row in TABLE["rows"]
        if row["site"] in WARNING_KINDS and row["class"] not in ("cli", "transitional")
    ]
    wrong += [
        row
        for row in TABLE["rows"]
        if row["site"] == "filterwarnings" and row["scope"] != "<module>"
    ]
    assert not wrong, f"{wrong}: a library filter is bounded and set once, at import"


def test_only_the_logging_module_touches_the_handlers() -> None:
    files = {row["file"] for row in TABLE["rows"] if row["site"] in HANDLER_KINDS}
    assert files <= {"hydromodpy/core/logging.py"}, files


def test_no_transitional_row_is_left() -> None:
    left = [(row["file"], row["site"]) for row in TABLE["rows"] if row["class"] == "transitional"]
    assert not left, f"{left}: the warnings of a check go to a sink, no row waits for a later lot"
