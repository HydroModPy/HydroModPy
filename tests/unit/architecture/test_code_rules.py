"""The code rules of CLAUDE.md that a reader of the tree can check on the syntax alone.

One function per rule, each reading every module of ``hydromodpy/``:

- rule 8, no re-export outside the facade: an ``__init__.py`` imports no name to hand it
  to another module, and it lists in ``__all__`` only what it defines;
- rule 9, no ``Protocol`` or ``ABC`` with one implementation, except a port of ``PORTS``;
- rule 10, the ``if TYPE_CHECKING:`` blocks stay under a ceiling that only goes down;
- rule 12, no ``__getattr__`` on a module outside the root package;
- rule 13, no module named with manager, handler, provider, service or helper;
- rule 16, no ``_private`` name or module imported from another package.

Each rule has a few cases written as source text, so a blind spot of a check shows in the
cases before it shows in the tree.
"""

from __future__ import annotations

import ast
import pathlib
import re
from collections import Counter

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
PACKAGE = REPO_ROOT / "hydromodpy"
ROOT_INIT = PACKAGE / "__init__.py"

# ---------------------------------------------------------------------------
# Rule 9
# ---------------------------------------------------------------------------

PORTS: dict[str, str] = {
    "SolverAdapter": "the contract every solver backend meets, read by the workflow",
    "OutputAdapter": "what a solver gives back from a finished run, with several backends",
    "CellLocator": "finds the cell of a point, one per mesh family",
    "MeshEngine": "builds a mesh, one engine per mesh family",
    "TerrainEngine": "derives the terrain products, one engine per method",
    "DataSource": "reads one variable from a file, a URL or an API, one per source kind",
    "TrialPipeline": "the one global, filled once by project and read by the calibration",
    "TrialEvaluator": "scores a trial, so the calibration does not read the solver",
    "ExportWriter": "writes one export format, one per format",
    "Optimizer": "searches the parameter space, one per algorithm",
    "ProgressReporter": "tells a caller how a search goes, so the engine does not print",
    "LoadResultProto": "what results hands to model without reading its package",
    "FieldRecordProto": "what results hands to model without reading its package",
    "SolverModel": "what core says of a model so a solver need not import model",
    "Objective": "turns a trial into a score, one per objective block",
    "Criterion": "one scoring rule of a phase, registered by name",
    "CalibrationProtocol": "a published calibration method, registered by name",
    "Step": "one step of the pipeline, several steps",
    "CohortExecutor": "runs a cohort of cases, serial or in processes",
    "SpatialSupportProvider": "gives the support of a field, several kinds of support",
}
"""Each ``Protocol`` or ``ABC`` that is a real port, with the reason in one line.

A name leaves the table when its class becomes a concrete class, and the table cannot
list a name that no class bears."""

SHAPES: dict[str, str] = {
    "TrialStep": "the call signature of one step of a trial, which functions fill",
    "TrialPipelineRunner": "the call signature of the runner a pipeline hands the trial",
    "ScoringDeclaration": "the attributes a metric rule reads from a declaration",
    "Resolved": "the attributes a worker reads from a resolved request",
    "_Digest": "what hashlib objects share, so a hash is passed in",
}
"""Protocols that type a call or an attribute set, not a part a class implements.

Nothing declares that it implements them, and standard-library or Pydantic objects meet
them, so no class count applies."""

MIN_IMPLEMENTATIONS = 2
"""An ``ABC`` outside the tables needs this many subclasses in the package."""


def _class_bases(node: ast.ClassDef) -> list[str]:
    names = []
    for base in node.bases:
        target = base.value if isinstance(base, ast.Subscript) else base
        names.append(ast.unparse(target).split(".")[-1])
    for keyword in node.keywords:
        if keyword.arg == "metaclass":
            names.append(ast.unparse(keyword.value).split(".")[-1])
    return names


def contracts_and_subclasses(
    sources: dict[str, str],
) -> tuple[dict[str, str], Counter[str]]:
    """The ``Protocol`` and ``ABC`` classes of the sources, and how often each is subclassed."""
    contracts: dict[str, str] = {}
    subclasses: Counter[str] = Counter()
    for where, text in sources.items():
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = _class_bases(node)
            subclasses.update(bases)
            if {"Protocol", "ABC", "ABCMeta"} & set(bases):
                contracts[node.name] = where
    return contracts, subclasses


def single_implementation_contracts(sources: dict[str, str]) -> list[str]:
    """The contracts of the sources that rule 9 refuses, as ``name (file)``."""
    contracts, subclasses = contracts_and_subclasses(sources)
    return sorted(
        f"{name} ({where})"
        for name, where in contracts.items()
        if name not in PORTS and name not in SHAPES and subclasses[name] < MIN_IMPLEMENTATIONS
    )


# ---------------------------------------------------------------------------
# Rule 10
# ---------------------------------------------------------------------------

TYPE_CHECKING_CEILING = 350
"""The blocks ``if TYPE_CHECKING:`` the package may hold. It goes down and never up.

Turning one into a real import needs the proof that no cycle appears and that the import time
stays the same, module by module, so the number falls as that proof is made."""


def type_checking_blocks(text: str) -> int:
    """How many ``if TYPE_CHECKING:`` blocks the source holds."""
    count = 0
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.If):
            test = node.test
            name = test.attr if isinstance(test, ast.Attribute) else getattr(test, "id", "")
            count += name == "TYPE_CHECKING"
    return count


# ---------------------------------------------------------------------------
# Rule 8
# ---------------------------------------------------------------------------


def reexports_of(text: str, lines: list[str] | None = None) -> list[str]:
    """What an ``__init__.py`` imports to hand over, as ``line: why``.

    An import is allowed when the module reads the name it binds. A ``import a.b.c`` line
    that carries ``noqa: F401`` is the one import kept for its effect, and its comment gives
    the reason. ``__all__`` may list only names the module defines.
    """
    lines = lines if lines is not None else text.splitlines()
    tree = ast.parse(text)
    read: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            read.add(node.id)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            read.update(re.findall(r"[A-Za-z_]\w*", node.value))
    found: list[str] = []
    defined: set[str] = set()
    all_names: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module != "__future__":
            for alias in node.names:
                bound = alias.asname or alias.name
                if alias.name == "*":
                    found.append(f"line {node.lineno}: a star import")
                elif not _read_in_code(bound, tree, node):
                    found.append(f"line {node.lineno}: {bound} is imported and not read")
        elif isinstance(node, ast.Import):
            marked = "noqa: F401" in lines[node.end_lineno - 1]
            for alias in node.names:
                bound = alias.asname or alias.name.split(".")[0]
                if not marked and not _read_in_code(bound, tree, node):
                    found.append(f"line {node.lineno}: {alias.name} is imported and not read")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    defined.add(target.id)
                    if target.id == "__all__" and isinstance(node.value, (ast.List, ast.Tuple)):
                        all_names = [
                            e.value for e in node.value.elts if isinstance(e, ast.Constant)
                        ]
    found.extend(
        f"__all__ lists {name}, which the module does not define"
        for name in all_names
        if name not in defined
    )
    return found


def _read_in_code(name: str, tree: ast.Module, skip: ast.stmt) -> bool:
    """Whether ``name`` is read by a node of the tree other than the import ``skip``."""
    for node in ast.walk(tree):
        if node is skip:
            continue
        if isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, ast.Load):
            return True
        if isinstance(node, (ast.arg,)) and node.annotation is not None:
            if _string_names(node.annotation, name):
                return True
        if isinstance(node, ast.AnnAssign) and _string_names(node.annotation, name):
            return True
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.returns is not None:
            if _string_names(node.returns, name):
                return True
    return False


def _string_names(annotation: ast.AST, name: str) -> bool:
    for node in ast.walk(annotation):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if re.search(rf"\b{re.escape(name)}\b", node.value):
                return True
    return False


# ---------------------------------------------------------------------------
# Rule 12
# ---------------------------------------------------------------------------


def module_getattr(text: str) -> bool:
    """Whether the module defines ``__getattr__`` at its top level."""
    return any(
        isinstance(node, ast.FunctionDef) and node.name == "__getattr__"
        for node in ast.parse(text).body
    )


# ---------------------------------------------------------------------------
# Rule 13
# ---------------------------------------------------------------------------

FORBIDDEN_WORDS = ("manager", "handler", "provider", "service", "helper")
"""A module named with one of these has a job that has no name yet."""


def forbidden_word_in(relative: str) -> str | None:
    """The first word of rule 13 that the path holds, or ``None``."""
    lowered = relative.lower()
    return next((word for word in FORBIDDEN_WORDS if word in lowered), None)


# ---------------------------------------------------------------------------
# Rule 16
# ---------------------------------------------------------------------------


def private_reads(text: str, *, own_package: str) -> list[str]:
    """The imports of a ``_private`` module or name of another top-level package.

    ``own_package`` is the first folder under ``hydromodpy`` that holds the module, or the
    empty string for a module of the root.
    """
    found: list[str] = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            parts = node.module.split(".")
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.Import):
            for alias in node.names:
                found.extend(_private_in(alias.name.split("."), [], own_package, node.lineno))
            continue
        else:
            continue
        found.extend(_private_in(parts, names, own_package, node.lineno))
    return found


def _private_in(parts: list[str], names: list[str], own: str, line: int) -> list[str]:
    if parts[0] != "hydromodpy" or len(parts) < 2:
        return []
    if parts[1] == own or (len(parts) == 2 and parts[1].startswith("_") and not own):
        return []
    modules = [p for p in parts[1:] if p.startswith("_") and not p.startswith("__")]
    hidden = [n for n in names if n.startswith("_") and not n.startswith("__")]
    where = ".".join(parts)
    return [f"line {line}: {where}.{p}" for p in modules] + [
        f"line {line}: {n} from {where}" for n in hidden
    ]


# ---------------------------------------------------------------------------
# The tree
# ---------------------------------------------------------------------------


def _modules() -> dict[str, str]:
    """Every module of the package, as ``relative path -> source``."""
    return {
        path.relative_to(REPO_ROOT).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(PACKAGE.rglob("*.py"))
        if "__pycache__" not in path.parts
    }


MODULES = _modules()
INITS = {where: text for where, text in MODULES.items() if where.endswith("/__init__.py")}
INITS.pop("hydromodpy/__init__.py")


def test_rule_8_no_init_hands_over_a_name_it_imports() -> None:
    offenders = [
        f"{where}: {problem}" for where, text in INITS.items() for problem in reexports_of(text)
    ]
    assert not offenders, (
        "Rule 8 is broken, import a name from the module that defines it:\n" + "\n".join(offenders)
    )


def test_rule_9_every_contract_is_a_port_or_has_two_implementations() -> None:
    offenders = single_implementation_contracts(MODULES)
    assert not offenders, (
        "Rule 9 is broken, a Protocol or an ABC with one implementation is the class itself:\n"
        + "\n".join(offenders)
    )


def test_rule_9_the_tables_list_only_contracts_that_exist() -> None:
    contracts, _ = contracts_and_subclasses(MODULES)
    stale = sorted((set(PORTS) | set(SHAPES)) - set(contracts))
    assert not stale, f"These names bear no Protocol or ABC, delete them: {stale}"
    assert not set(PORTS) & set(SHAPES), "a name sits in both tables"
    assert all(reason.strip() for reason in [*PORTS.values(), *SHAPES.values()])


def test_rule_10_type_checking_blocks_stay_under_the_ceiling() -> None:
    count = sum(type_checking_blocks(text) for text in MODULES.values())
    assert count <= TYPE_CHECKING_CEILING, (
        f"{count} blocks of if TYPE_CHECKING, over the ceiling of {TYPE_CHECKING_CEILING}. "
        "Import for real, or prove the cycle first."
    )


def test_rule_12_no_module_but_the_root_defines_getattr() -> None:
    offenders = [
        where
        for where, text in MODULES.items()
        if where != "hydromodpy/__init__.py" and module_getattr(text)
    ]
    assert not offenders, "Rule 12 is broken, a lazy __getattr__ outside the root: " + ", ".join(
        offenders
    )


def test_rule_13_no_module_is_named_with_a_word_of_the_rule() -> None:
    offenders = [
        f"{where} ({word})"
        for where in MODULES
        if (word := forbidden_word_in(where.removeprefix("hydromodpy/"))) is not None
    ]
    assert not offenders, "Rule 13 is broken, give the module a name for its job:\n" + "\n".join(
        offenders
    )


def test_rule_16_no_package_reads_a_private_name_of_another() -> None:
    offenders = []
    for where, text in MODULES.items():
        parts = where.split("/")
        own = parts[1] if len(parts) > 2 else ""
        offenders.extend(f"{where}: {problem}" for problem in private_reads(text, own_package=own))
    assert not offenders, "Rule 16 is broken, ask the owner for a public name:\n" + "\n".join(
        offenders
    )


# ---------------------------------------------------------------------------
# The cases of each check
# ---------------------------------------------------------------------------

REEXPORT_CASES = (
    ("a name imported and handed over", "from a.b import X\n", 1),
    ("a name imported and read", "from a.b import X\nTABLE = (X,)\n", 0),
    ("a name read in a string annotation", "from a.b import X\ndef f() -> 'X': ...\n", 0),
    ("a star import", "from a.b import *\n", 1),
    ("the future import", "from __future__ import annotations\n", 0),
    ("a marked import for its effect", "import a.b.c  # noqa: F401  # fills the registry\n", 0),
    ("an unmarked import for its effect", "import a.b.c\n", 1),
    ("__all__ of defined names", "NAME = 1\n__all__ = ('NAME',)\n", 0),
    ("__all__ of an imported name", "from a.b import X\nY = X\n__all__ = ('X',)\n", 1),
    ("a docstring alone", '"""The package."""\n', 0),
)


@pytest.mark.parametrize(
    ("case", "source", "expected"), REEXPORT_CASES, ids=[case for case, _, _ in REEXPORT_CASES]
)
def test_rule_8_check_sees_each_kind_of_import(case: str, source: str, expected: int) -> None:
    del case
    assert len(reexports_of(source)) == expected


CONTRACT_CASES = (
    ("a protocol with no class under it", "class P(Protocol):\n    def f(self): ...\n", 1),
    ("an abc with one subclass", "class A(ABC): ...\nclass B(A): ...\n", 1),
    ("an abc with two subclasses", "class A(ABC): ...\nclass B(A): ...\nclass C(A): ...\n", 0),
    ("a generic protocol", "class P(Protocol[T]):\n    def f(self): ...\n", 1),
    ("a port of the table", "class Optimizer(Protocol):\n    def f(self): ...\n", 0),
    ("a shape of the table", "class TrialStep(Protocol):\n    def __call__(self): ...\n", 0),
    ("a plain class", "class C:\n    pass\n", 0),
)


@pytest.mark.parametrize(
    ("case", "source", "expected"), CONTRACT_CASES, ids=[case for case, _, _ in CONTRACT_CASES]
)
def test_rule_9_check_sees_each_kind_of_contract(case: str, source: str, expected: int) -> None:
    del case
    assert len(single_implementation_contracts({"hydromodpy/x.py": source})) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("if TYPE_CHECKING:\n    import a\n", 1),
        ("import typing\nif typing.TYPE_CHECKING:\n    import a\n", 1),
        ("if x:\n    import a\n", 0),
        ("if TYPE_CHECKING:\n    import a\nif TYPE_CHECKING:\n    import b\n", 2),
    ],
)
def test_rule_10_check_counts_the_blocks(source: str, expected: int) -> None:
    assert type_checking_blocks(source) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("def __getattr__(name):\n    raise AttributeError(name)\n", True),
        ("class C:\n    def __getattr__(self, name): ...\n", False),
        ("def other(): ...\n", False),
    ],
)
def test_rule_12_check_reads_only_the_module_level(source: str, expected: bool) -> None:
    assert module_getattr(source) is expected


@pytest.mark.parametrize(
    ("relative", "expected"),
    [
        ("cli/helpers.py", "helper"),
        ("data/provider_registry.py", "provider"),
        ("solver/manager/run.py", "manager"),
        ("core/service.py", "service"),
        ("workflow/handler.py", "handler"),
        ("core/units/quantities.py", None),
    ],
)
def test_rule_13_check_reads_the_whole_path(relative: str, expected: str | None) -> None:
    assert forbidden_word_in(relative) == expected


PRIVATE_CASES = (
    ("a private name of another package", "from hydromodpy.core.x import _y\n", "cli", 1),
    ("a private module of another package", "from hydromodpy.core._x import y\n", "cli", 1),
    ("a private module, plain import", "import hydromodpy.core._x\n", "cli", 1),
    ("a private name of its own package", "from hydromodpy.cli.x import _y\n", "cli", 0),
    ("a public name of another package", "from hydromodpy.core.x import y\n", "cli", 0),
    ("a dunder name", "from hydromodpy.core.x import __version__\n", "cli", 0),
    ("a module of the standard library", "from os.path import _x\n", "cli", 0),
)


@pytest.mark.parametrize(
    ("case", "source", "own", "expected"),
    PRIVATE_CASES,
    ids=[case for case, _, _, _ in PRIVATE_CASES],
)
def test_rule_16_check_sees_each_kind_of_private_read(
    case: str, source: str, own: str, expected: int
) -> None:
    del case
    assert len(private_reads(source, own_package=own)) == expected
