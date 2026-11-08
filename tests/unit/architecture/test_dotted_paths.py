"""Check the module paths that the repository writes as strings.

A rename that leaves a string behind fails late, at the first access or the first run.
This gate reads the places that hold such strings and resolves each one on disk:

- module-level assignments in ``hydromodpy/`` and ``hydromodpy_annex/`` (the lazy
  tables, the registries, the group and document constants), the first literal
  argument of ``import_module``, and the ``"implementation"`` key of a dict;
- the first literal argument of ``setattr``, ``delattr`` and ``patch`` in ``tests/``;
- ``pyproject.toml``: dotted names, and the ``hydromodpy/...`` globs;
- ``.github/workflows/*.yml``: dotted names, and the ``hydromodpy/...`` globs.

Nothing is imported. A chain resolves when its longest module prefix is a ``.py``
file, a package or a plain folder, and the name after it is defined in that module.
The ``module:Name`` form needs the whole module to resolve. ``find_spec`` on a dotted
name runs the parent packages, so the same rules are applied on the file system.

``dotted_paths.yaml`` lists the strings that are not modules (document ids, entry-point
groups, file names) and the strings known to be stale, each with the lot that fixes it.
Docs and ``tools/`` are not read. The changes page names modules removed on purpose.
"""

from __future__ import annotations

import ast
import functools
import glob
import pathlib
import re
import tomllib
from typing import NamedTuple

import pytest
import yaml

HERE = pathlib.Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
ALLOWED_FILE = HERE / "dotted_paths.yaml"

CHAIN = re.compile(r"^hydromodpy(\.[A-Za-z_]\w*)+(:[A-Za-z_]\w*(\.[A-Za-z_]\w*)*)?$")
QUOTED_START = re.compile(r"[\"']hydromodpy\.")
PATCH_TEXT = re.compile(r"\b(setattr|delattr|patch)\(")
PATCH_CALLS = frozenset({"setattr", "delattr", "patch"})
CODE_ROOTS = ("hydromodpy", "hydromodpy_annex")
LOCATIONS = (
    "package code",
    "test patches",
    "pyproject chains",
    "pyproject globs",
    "workflow chains",
    "workflow globs",
)
MIN_LAZY_CHAINS = 50


class Found(NamedTuple):
    location: str
    file: str
    line: int
    text: str

    @property
    def where(self) -> str:
        return f"{self.file}:{self.line}"


def _load_allowed() -> dict:
    return yaml.safe_load(ALLOWED_FILE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Resolution on the file system
# ---------------------------------------------------------------------------


def _module_file(parts: tuple[str, ...]) -> pathlib.Path | None:
    base = REPO_ROOT.joinpath(*parts)
    if base.with_suffix(".py").is_file():
        return base.with_suffix(".py")
    if (base / "__init__.py").is_file():
        return base / "__init__.py"
    return None


def _is_module(parts: tuple[str, ...]) -> bool:
    if _module_file(parts) is not None:
        return True
    folder = REPO_ROOT.joinpath(*parts)
    return folder.is_dir() and folder.name != "__pycache__"


@functools.cache
def _defined_names(path: pathlib.Path) -> frozenset[str]:
    """Names a module defines, imports, assigns, or quotes as an identifier string."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.alias):
            names.add((node.asname or node.name).split(".")[0])
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.isidentifier():
                names.add(node.value)
    return frozenset(names)


def resolve_chain(chain: str) -> str | None:
    """Return None when the chain resolves, else the part that is missing."""
    module, _, attribute = chain.partition(":")
    parts = tuple(module.split("."))
    depth = len(parts)
    while depth > 0 and not _is_module(parts[:depth]):
        depth -= 1
    if depth == 0:
        return "no module hydromodpy"
    if depth < len(parts):
        if attribute:
            return f"no module {'.'.join(parts)}"
        file = _module_file(parts[:depth])
        name = parts[depth]
        if file is None:
            return f"{'.'.join(parts[: depth + 1])} is not a module"
        if name not in _defined_names(file):
            return f"{'.'.join(parts[:depth])} has no {name}"
        # The facade ``hydromodpy/__init__.py`` is the one module that
        # re-exports names, so a name defined in it may be an exported CLI
        # verb and no module. A chain written through it stops there: an
        # entry-point group named after a verb, for example, is refused
        # instead of being read as a module path.
        if depth == 1 and len(parts) > 2:
            return (
                f"{'.'.join(parts[: depth + 1])} is a name written in "
                f"hydromodpy/__init__.py, and no module {'.'.join(parts)} follows it"
            )
        return None
    if attribute:
        file = _module_file(parts)
        name = attribute.split(".")[0]
        if file is None:
            return f"{module} is a folder, it has no {name}"
        if name not in _defined_names(file):
            return f"{module} has no {name}"
    return None


def _expand_braces(pattern: str) -> list[str]:
    match = re.search(r"\{([^}]*)\}", pattern)
    if match is None:
        return [pattern]
    head, tail = pattern[: match.start()], pattern[match.end() :]
    return [
        out for option in match.group(1).split(",") for out in _expand_braces(head + option + tail)
    ]


def resolve_glob(pattern: str) -> str | None:
    """Return None when the glob matches at least one path of the repository."""
    for item in _expand_braces(pattern.removeprefix("!")):
        if glob.glob(item, root_dir=REPO_ROOT, recursive=True):
            return None
    return "no path matches"


# ---------------------------------------------------------------------------
# The scan
# ---------------------------------------------------------------------------


def _string_constants(node: ast.AST):
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            yield sub


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _python_files(root: str):
    for path in sorted((REPO_ROOT / root).rglob("*.py")):
        relative = path.relative_to(REPO_ROOT)
        if "__pycache__" in relative.parts or "frozen_runs" in relative.parts:
            continue
        yield path, relative.as_posix()


def _scan_package_code() -> list[Found]:
    found: list[Found] = []
    for root in CODE_ROOTS:
        if not (REPO_ROOT / root).is_dir():
            continue
        for path, relative in _python_files(root):
            source = path.read_text(encoding="utf-8")
            if not QUOTED_START.search(source):
                continue
            tree = ast.parse(source)
            for statement in tree.body:
                if isinstance(statement, ast.Assign | ast.AnnAssign) and statement.value:
                    for const in _string_constants(statement.value):
                        if CHAIN.match(const.value):
                            found.append(Found("package code", relative, const.lineno, const.value))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and node.args and _call_name(node) == "import_module":
                    first = node.args[0]
                    if isinstance(first, ast.Constant) and isinstance(first.value, str):
                        if CHAIN.match(first.value):
                            found.append(Found("package code", relative, first.lineno, first.value))
                elif isinstance(node, ast.Dict):
                    for key, value in zip(node.keys, node.values, strict=True):
                        if isinstance(key, ast.Constant) and key.value == "implementation":
                            for const in _string_constants(value):
                                head = const.value.split(":")[0].split(" ")[0]
                                if head.startswith("hydromodpy."):
                                    found.append(
                                        Found("package code", relative, const.lineno, head)
                                    )
    return found


def _scan_test_patches() -> list[Found]:
    found: list[Found] = []
    for path, relative in _python_files("tests"):
        source = path.read_text(encoding="utf-8")
        if not PATCH_TEXT.search(source):
            continue
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Call) and node.args and _call_name(node) in PATCH_CALLS:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    if CHAIN.match(first.value):
                        found.append(Found("test patches", relative, first.lineno, first.value))
    return found


def _walk_toml(node, path=""):
    if isinstance(node, dict):
        for key, value in node.items():
            yield f"{path}.{key}", key
            yield from _walk_toml(value, f"{path}.{key}")
    elif isinstance(node, list):
        for value in node:
            yield from _walk_toml(value, path)
    elif isinstance(node, str):
        yield path, node


def _scan_pyproject() -> list[Found]:
    lines = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8").splitlines()

    def line_of(text: str) -> int:
        return next((i for i, row in enumerate(lines, 1) if text in row), 0)

    found: list[Found] = []
    data = tomllib.loads("\n".join(lines))
    for _, text in _walk_toml(data):
        chain = text.removesuffix(".*")
        if CHAIN.match(chain):
            found.append(Found("pyproject chains", "pyproject.toml", line_of(chain), chain))
        elif text.removeprefix("!").startswith("hydromodpy/"):
            found.append(Found("pyproject globs", "pyproject.toml", line_of(text), text))
    return found


def _scan_workflows() -> list[Found]:
    found: list[Found] = []
    for path in sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml")):
        relative = path.relative_to(REPO_ROOT).as_posix()
        for number, row in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for token in re.split(r"[\s,\"'=]+", row):
                token = token.rstrip("\\")
                if token.startswith("hydromodpy/"):
                    found.append(Found("workflow globs", relative, number, token))
                elif CHAIN.match(token):
                    found.append(Found("workflow chains", relative, number, token))
    return found


@functools.cache
def scan() -> tuple[Found, ...]:
    """Every string the gate reads, from every known place."""
    return tuple(
        _scan_package_code() + _scan_test_patches() + _scan_pyproject() + _scan_workflows()
    )


# ---------------------------------------------------------------------------
# What is allowed
# ---------------------------------------------------------------------------


def _group_names(allowed: dict) -> set[str]:
    section = allowed["not_modules"]
    return set(section["groups"]) | set(section["groups_that_are_packages"])


def _is_allowed(text: str, allowed: dict) -> bool:
    section = allowed["not_modules"]
    if re.fullmatch(section["documents"], text):
        return True
    if text in _group_names(allowed):
        return True
    for entry in section["names"]:
        if entry.get("prefix") and text.startswith(entry["text"]):
            return True
        if text == entry["text"]:
            return True
    return False


def _stale_keys(allowed: dict) -> set[tuple[str, str]]:
    return {(entry["text"], entry["file"]) for entry in allowed["known_stale"]}


def find_problems() -> list[str]:
    """Strings that do not resolve and that no list explains."""
    allowed = _load_allowed()
    stale = _stale_keys(allowed)
    problems = []
    for item in scan():
        if item.location.endswith("globs"):
            missing = resolve_glob(item.text)
        else:
            if _is_allowed(item.text, allowed):
                continue
            missing = resolve_chain(item.text)
        if missing and (item.text, item.file) not in stale:
            problems.append(f"{item.where}  {item.text}  ({missing})")
    return problems


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_every_dotted_path_resolves():
    problems = find_problems()
    assert not problems, "Dotted paths that point at nothing:\n  " + "\n  ".join(problems)


def test_the_scan_reads_every_location():
    seen = {item.location for item in scan()}
    assert set(LOCATIONS) <= seen, f"Nothing read from {sorted(set(LOCATIONS) - seen)}"
    lazy = [item for item in scan() if item.file == "hydromodpy/_lazy.py"]
    assert len(lazy) >= MIN_LAZY_CHAINS, f"_lazy.py gave only {len(lazy)} chains"


def test_a_known_stale_entry_is_still_stale():
    allowed = _load_allowed()
    present = {(item.text, item.file) for item in scan()}
    for entry in allowed["known_stale"]:
        key = (entry["text"], entry["file"])
        assert entry.get("why") and entry.get("lifted_by"), f"{key} needs why and lifted_by"
        assert key in present, f"{key} is gone from its file: remove the entry"
        text = entry["text"]
        missing = resolve_glob(text) if text.startswith("hydromodpy/") else resolve_chain(text)
        assert missing, f"{key} resolves now: remove the entry"


def test_an_allowed_name_is_still_used():
    allowed = _load_allowed()
    section = allowed["not_modules"]
    texts = [item.text for item in scan() if not item.location.endswith("globs")]
    assert any(re.fullmatch(section["documents"], text) for text in texts), "no document id"
    for group in _group_names(allowed):
        assert group in texts, f"group {group} is not written anywhere"
    for group in section["groups"]:
        assert resolve_chain(group), f"group {group} is a module: it needs no entry"
    for group in section["groups_that_are_packages"]:
        assert resolve_chain(group) is None, f"group {group} is not a package"
    for entry in section["names"]:
        text = entry["text"]
        assert entry.get("why"), f"{text} needs a reason"
        assert text in texts, f"name {text} is not written anywhere"
        assert resolve_chain(text), f"name {text} is a module: it needs no entry"
        if entry.get("prefix"):
            *parent, start = text.split(".")
            folder = REPO_ROOT.joinpath(*parent)
            assert any(child.name.startswith(start) for child in folder.iterdir()), (
                f"prefix {text} starts no module"
            )


def test_entry_points_use_declared_groups():
    allowed = _load_allowed()
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    groups = data.get("project", {}).get("entry-points", {})
    unknown = sorted(set(groups) - _group_names(allowed))
    assert not unknown, f"Entry-point groups missing from dotted_paths.yaml: {unknown}"


@pytest.mark.parametrize(
    ("chain", "expected"),
    [
        ("hydromodpy.core.logging", None),
        ("hydromodpy.core.logging.get_logger", None),
        ("hydromodpy.core.logging.no_such_name", "hydromodpy.core.logging has no no_such_name"),
        ("hydromodpy.no_such_package.mod", "hydromodpy has no no_such_package"),
        ("hydromodpy.core.logging:get_logger", None),
        ("hydromodpy.core.logging:no_such_name", "hydromodpy.core.logging has no no_such_name"),
        ("hydromodpy.no_such_package:Thing", "no module hydromodpy.no_such_package"),
    ],
)
def test_the_resolver_tells_a_real_path_from_a_dead_one(chain, expected):
    assert resolve_chain(chain) == expected
