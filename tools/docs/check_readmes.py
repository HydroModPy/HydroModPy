"""Check the README files of the repository against the README rule.

Usage: python -m tools.docs.check_readmes

A README goes in each package, in each port folder and in the two folders that
sit beside the package. The set is computed from the code and never written
out, so a new port enters without a list to keep:

- ``package``: one row of ``tests/unit/architecture/layer_matrix.yaml`` per
  folder of ``hydromodpy/``;
- ``port``: the folder of each ``PluginRegistry`` instance when it is not a
  package folder, the folder of each solver backend (the sibling folders of the
  ``solvers`` registry that hold a built-in adapter), and the folder of the two
  closed tables, which hold ``MetricSpec`` and ``FlowBoundaryDefinition``;
- ``sibling``: the root of each folder that ``siblings`` of the matrix names.

Any other README under ``hydromodpy/`` is refused. A permitted README is
refused when it is longer than 20 non-empty lines (30 for a port or a sibling),
when it uses a bullet with a bold label, a dash as punctuation, a closing
summary, or French. Exit code 1 when a README is refused.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import NamedTuple

import yaml

from tools.docs.check_page import looks_french

ROOT = Path(__file__).resolve().parents[2]
LAYER_MATRIX = Path("tests/unit/architecture/layer_matrix.yaml")
PACKAGE_LINES = 20
OTHER_LINES = 30
# The two closed tables of ARCH 3: a row is added in the code and the TOML
# ``Literal`` is generated from it. Their folders carry a port contract.
CLOSED_TABLES = ("MetricSpec", "FlowBoundaryDefinition")
# The registry whose built-in members are folders that each carry their own
# contract (ARCH 6): a solver backend is a port. Other registries keep their
# members as modules of the port folder.
BACKEND_REGISTRY = "solvers"

NOT_ALLOWED = (
    "a README goes in a package or a port folder only (rule 17); "
    "move what it says to the package page or to the module docstring"
)
MISSING = "this package or port has no README (rule 17)"
TOO_LONG = "{n} lines, a package README holds about ten and a port README about twenty (rule 17)"
BOLD_BULLET = "a bullet with a bold label (rule 17)"
DASH = "a dash used as punctuation (rule 17)"
SUMMARY = "a closing summary (rule 17)"
FRENCH = "French text, a README is in English (rule 17)"

BOLD_BULLET_LINE = re.compile(r"^\s*[-*]\s+\*\*[^*]+\*\*")
SUMMARY_TITLE = re.compile(r"^#{1,6}\s+(?:Summary|In short|Key takeaways|Conclusion)\s*$", re.I)


class RegistryRef(NamedTuple):
    """A module-level ``PluginRegistry(...)`` found in ``hydromodpy/``."""

    module: str
    name: str
    folder: Path
    builtin_modules: tuple[str, ...]


def _python_files(base: Path) -> list[Path]:
    return sorted(p for p in base.rglob("*.py") if "__pycache__" not in p.parts)


def _dotted(path: Path, repo: Path) -> str:
    parts = list(path.relative_to(repo).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _is_registry_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (isinstance(func, ast.Name) and func.id == "PluginRegistry") or (
        isinstance(func, ast.Attribute) and func.attr == "PluginRegistry"
    )


def _assigned(tree: ast.Module) -> dict[str, ast.expr]:
    """Module-level ``name = value`` and ``name: type = value``."""
    out: dict[str, ast.expr] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and node.value is not None:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            if isinstance(node.target, ast.Name):
                out[node.target.id] = node.value
    return out


def _builtin_modules(call: ast.Call, assigned: dict[str, ast.expr]) -> tuple[str, ...]:
    """The modules of the ``"module:Class"`` values of ``builtin_paths``, when it is a literal."""
    for keyword in call.keywords:
        if keyword.arg != "builtin_paths":
            continue
        value = keyword.value
        if isinstance(value, ast.Name):
            value = assigned.get(value.id, value)
        if not isinstance(value, ast.Dict):
            return ()
        return tuple(
            dict.fromkeys(
                v.value.partition(":")[0]
                for v in value.values
                if isinstance(v, ast.Constant) and isinstance(v.value, str)
            )
        )
    return ()


def plugin_registries(repo: Path = ROOT) -> list[RegistryRef]:
    """Every ``name = PluginRegistry(...)`` at the top of a module of ``hydromodpy/``.

    Found by reading the syntax trees, so nothing is imported.
    """
    found = []
    for path in _python_files(repo / "hydromodpy"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assigned = _assigned(tree)
        for name, value in assigned.items():
            if _is_registry_call(value):
                found.append(
                    RegistryRef(
                        module=_dotted(path, repo),
                        name=name,
                        folder=path.parent.relative_to(repo),
                        builtin_modules=_builtin_modules(value, assigned),
                    )
                )
    return found


def _class_folders(repo: Path, names: tuple[str, ...]) -> list[Path]:
    """The folder of the module that defines each class in *names*."""
    folders = []
    for path in _python_files(repo / "hydromodpy"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(isinstance(n, ast.ClassDef) and n.name in names for n in tree.body):
            folders.append(path.parent.relative_to(repo))
    return folders


def allowed_readmes(repo: Path = ROOT) -> dict[Path, str]:
    """Every permitted README, relative to *repo*, with its kind.

    The kind is ``package``, ``port`` or ``sibling``. A folder that is both a
    package and a port counts as a package.
    """
    matrix = yaml.safe_load((repo / LAYER_MATRIX).read_text(encoding="utf-8"))
    out: dict[Path, str] = {}
    for name in matrix["allowed"]:
        if not name.startswith("<"):
            out[Path("hydromodpy") / name / "README.md"] = "package"
    ports: list[Path] = []
    for ref in plugin_registries(repo):
        ports.append(ref.folder)
        # A backend folder sits beside the folder of the registry and holds an adapter.
        if ref.name == BACKEND_REGISTRY and len(ref.folder.parts) == 3:
            for module in ref.builtin_modules:
                parts = module.split(".")
                backend = Path(*parts[:3])
                if (
                    len(parts) > 3
                    and tuple(parts[:2]) == ref.folder.parts[:2]
                    and parts[2] != ref.folder.parts[2]
                    and (repo / backend).is_dir()
                ):
                    ports.append(backend)
    ports.extend(_class_folders(repo, CLOSED_TABLES))
    for folder in ports:
        out.setdefault(folder / "README.md", "port")
    for name in matrix.get("siblings", {}):
        out[Path(name) / "README.md"] = "sibling"
    return dict(sorted(out.items()))


def _problems_of(text: str, kind: str, label: str) -> list[str]:
    problems = []
    lines = text.splitlines()
    count = sum(1 for line in lines if line.strip())
    if count > (PACKAGE_LINES if kind == "package" else OTHER_LINES):
        problems.append(f"{label}: {TOO_LONG.format(n=count)}")
    fence = None
    for n, line in enumerate(lines, start=1):
        marker = line.strip()[:3]
        if marker in ("```", "~~~"):
            fence = None if fence == marker else (fence or marker)
            continue
        if BOLD_BULLET_LINE.match(line):
            problems.append(f"{label}:{n}: {BOLD_BULLET}")
        if "—" in line or "–" in line:
            problems.append(f"{label}:{n}: {DASH}")
        if SUMMARY_TITLE.match(line):
            problems.append(f"{label}:{n}: {SUMMARY}")
        if fence is None and looks_french(line):
            problems.append(f"{label}:{n}: {FRENCH}")
    return problems


def check(repo: Path = ROOT) -> list[str]:
    """One line per refused README, ``<path>: <sentence>``."""
    allowed = allowed_readmes(repo)
    problems = []
    on_disk = [
        p.relative_to(repo)
        for p in sorted((repo / "hydromodpy").rglob("README.md"))
        if "__pycache__" not in p.parts
    ]
    for path in on_disk:
        if path not in allowed:
            problems.append(f"{path.as_posix()}: {NOT_ALLOWED}")
    for path, kind in allowed.items():
        full = repo / path
        if not full.is_file():
            problems.append(f"{path.as_posix()}: {MISSING}")
            continue
        problems.extend(_problems_of(full.read_text(encoding="utf-8"), kind, path.as_posix()))
    return problems


def main() -> int:
    """Print the refused READMEs and return the exit code."""
    problems = check()
    for problem in problems:
        print(problem)
    print(f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
