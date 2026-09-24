"""Enforce the import rules inside ``hydromodpy/data``.

``layer_matrix.yaml`` declares ``data`` as one layer, so an import from
``data/managers`` into ``data/variables`` is an edge it allows. The map of the
package, ``hydromodpy/data/structure.md``, orders the subpackages and says who
may import whom; ``data_layout.yaml`` is that table, and this module checks it
with the scanner the layer matrix uses. Every import counts: at module level,
inside a function, under ``TYPE_CHECKING``, or as a dotted path written in a
lazy-attribute table.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import sys

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
PKG_ROOT = REPO_ROOT / "hydromodpy"
DATA_ROOT = PKG_ROOT / "data"
LAYOUT_FILE = pathlib.Path(__file__).with_name("data_layout.yaml")
DATA = "hydromodpy.data"

_BUILD_GRAPH_PATH = REPO_ROOT / "tools" / "audit" / "build_graph.py"
_BUILD_GRAPH_SPEC = importlib.util.spec_from_file_location(
    "hydromodpy_data_layout_build_graph",
    _BUILD_GRAPH_PATH,
)
if _BUILD_GRAPH_SPEC is None or _BUILD_GRAPH_SPEC.loader is None:
    raise RuntimeError(f"Could not load architecture scanner at {_BUILD_GRAPH_PATH}")
_BUILD_GRAPH_MODULE = importlib.util.module_from_spec(_BUILD_GRAPH_SPEC)
sys.modules[_BUILD_GRAPH_SPEC.name] = _BUILD_GRAPH_MODULE
_BUILD_GRAPH_SPEC.loader.exec_module(_BUILD_GRAPH_MODULE)

scan_package = _BUILD_GRAPH_MODULE.scan_package


def _layout() -> dict:
    return yaml.safe_load(LAYOUT_FILE.read_text(encoding="utf-8"))


def _edges() -> list:
    return scan_package(PKG_ROOT)


def _relative(edge) -> str:
    return pathlib.Path(edge.src_file).relative_to(REPO_ROOT).as_posix()


def _in_data(module: str) -> bool:
    return module == DATA or module.startswith(DATA + ".")


def _unit(module: str) -> str:
    """The subpackage of ``hydromodpy.data`` a module belongs to."""
    parts = module.split(".")
    return parts[2] if len(parts) > 2 else "<init>"


def _variable(module: str) -> str | None:
    """The variable package a module belongs to, or None outside one."""
    parts = module.split(".")
    if len(parts) > 3 and parts[2] == "variables":
        candidate = DATA_ROOT / "variables" / parts[3]
        return parts[3] if candidate.is_dir() else None
    return None


def _src_module(edge) -> str:
    path = pathlib.Path(edge.src_file).relative_to(REPO_ROOT).with_suffix("")
    parts = list(path.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _data_edges() -> list:
    return [edge for edge in _edges() if pathlib.Path(edge.src_file).is_relative_to(DATA_ROOT)]


def _describe(edge) -> str:
    return f"{_relative(edge)}:{edge.lineno} imports {edge.target_module} ({edge.kind})"


def _builtin_source_modules() -> set[str]:
    from hydromodpy.data.source import registry

    return {path.split(":", 1)[0] for path in registry._BUILTIN_PATHS.values()}


def test_the_scanner_sees_the_data_package() -> None:
    """Anti-vacuity: an empty scan would make every rule below pass."""
    units = {_unit(_src_module(edge)) for edge in _data_edges()}
    assert {"contracts", "managers", "variables", "loading", "registry"} <= units


def test_every_subpackage_has_a_row() -> None:
    declared = set(_layout()["allowed"])
    actual = {
        path.name
        for path in DATA_ROOT.iterdir()
        if path.is_dir() and (path / "__init__.py").is_file()
    } | {"<init>"}
    assert sorted(actual - declared) == [], "subpackages without a row in data_layout.yaml"
    assert sorted(declared - actual) == [], "rows of data_layout.yaml without a subpackage"
    assert sorted(p.name for p in DATA_ROOT.glob("*.py")) == ["__init__.py"], (
        "a module sits at the root of hydromodpy/data; it belongs in a subpackage"
    )


def test_a_subpackage_imports_only_what_its_row_allows() -> None:
    layout = _layout()
    allowed = {unit: set(targets) for unit, targets in layout["allowed"].items()}
    text_path_files = set(layout["text_paths"])
    builtins = _builtin_source_modules()
    offenders = []
    for edge in _data_edges():
        if not _in_data(edge.target_module):
            continue
        src, tgt = _unit(_src_module(edge)), _unit(edge.target_module)
        if src == tgt or tgt in allowed.get(src, set()):
            continue
        if (
            edge.kind == "lazy_map"
            and _relative(edge) in text_path_files
            and edge.target_module in builtins
        ):
            continue
        offenders.append(f"[{src} -> {tgt}] {_describe(edge)}")
    assert not offenders, (
        "imports that hydromodpy/data/structure.md section 2 forbids:\n  " + "\n  ".join(offenders)
    )


def test_a_variable_never_imports_another_variable() -> None:
    offenders = []
    for edge in _data_edges():
        src_var = _variable(_src_module(edge))
        tgt_var = _variable(edge.target_module)
        if src_var and tgt_var and src_var != tgt_var:
            offenders.append(_describe(edge))
    assert not offenders, "one variable imports another:\n  " + "\n  ".join(offenders)


def _pattern_regex(pattern: str) -> re.Pattern[str]:
    """A ``*`` is one dotted name; a trailing ``.*`` also takes the whole subtree."""
    subtree = pattern.endswith(".*")
    base = pattern[:-2] if subtree else pattern
    body = r"\.".join("[^.]+" if part == "*" else re.escape(part) for part in base.split("."))
    return re.compile(body + (r"(\..+)?" if subtree else "") + r"\Z")


def _is_public(module: str, patterns: list[str]) -> bool:
    return any(_pattern_regex(pattern).match(module) for pattern in patterns)


def test_another_layer_imports_only_the_public_modules() -> None:
    patterns = _layout()["public"]
    offenders = [
        _describe(edge)
        for edge in _edges()
        if not pathlib.Path(edge.src_file).is_relative_to(DATA_ROOT)
        and _in_data(edge.target_module)
        and not _is_public(edge.target_module, patterns)
    ]
    assert not offenders, (
        "another layer imports a module of hydromodpy/data that section 8 of "
        "structure.md does not make public:\n  " + "\n  ".join(offenders)
    )


def test_the_public_patterns_name_existing_modules() -> None:
    """A public entry that matches nothing protects nothing."""
    modules = {
        ".".join(path.relative_to(REPO_ROOT).with_suffix("").parts).removesuffix(".__init__")
        for path in DATA_ROOT.rglob("*.py")
    }
    stale = [
        pattern
        for pattern in _layout()["public"]
        if not any(_is_public(module, [pattern]) for module in modules)
    ]
    assert stale == []
