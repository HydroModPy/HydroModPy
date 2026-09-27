"""Enforce the import rules inside the packages that carry a ``<package>_layout.yaml``.

``layer_matrix.yaml`` declares each layer as one block, so an import between two
parts of the same layer is an edge it allows. A package whose map
(``hydromodpy/<package>/README.md``) orders its parts gets a
``<package>_layout.yaml`` beside this module, which says who may import whom,
and one set of rules checks it with the scanner the layer matrix uses. Every
import counts: at module level, inside a function, under ``TYPE_CHECKING``, as
an ``import_module`` on a literal, or as a dotted path written in a
lazy-attribute table.

A part is a subpackage or a module at the root of the package; ``"<init>"`` is
the package facade. Keys of a layout file:

- ``allowed``: the parts each part may import, lowest row first;
- ``text_paths``: the only files that may name a module of the package as text;
- ``public``: what another layer may import from the package;
- ``tolerated`` (optional): a layer that ``layer_matrix.yaml`` tolerates, with
  the only modules it may import;
- ``solver_access`` (calibration): the solver modules the package may import.

The rules shared by every layout come first, parametrized over the files. The
rules proper to one package follow, each in its own function. The shared rules
exempt what a ``text_paths`` file names as text; a package that declares one
also gets a function below saying which modules that file may name.
"""

from __future__ import annotations

import functools
import importlib.util
import pathlib
import re
import sys

import pytest
import yaml

HERE = pathlib.Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
PKG_ROOT = REPO_ROOT / "hydromodpy"
LAYOUT_FILES = sorted(HERE.glob("*_layout.yaml"))
PACKAGES = [path.name.removesuffix("_layout.yaml") for path in LAYOUT_FILES]
TEXT_KINDS = frozenset({"import_module", "lazy_map"})

# Parts the scanner must see in each package. An empty scan would make every
# rule below pass.
SEEN_PARTS = {
    "data": {"contracts", "managers", "variables", "loading", "registry"},
    "calibration": {"optim", "runners", "config", "criteria", "metrics"},
    "display": {"figures", "figure", "figure_registry", "maps", "runs", "catchment_report"},
}

_BUILD_GRAPH_PATH = REPO_ROOT / "tools" / "audit" / "build_graph.py"
_BUILD_GRAPH_SPEC = importlib.util.spec_from_file_location(
    "hydromodpy_package_layouts_build_graph",
    _BUILD_GRAPH_PATH,
)
if _BUILD_GRAPH_SPEC is None or _BUILD_GRAPH_SPEC.loader is None:
    raise RuntimeError(f"Could not load architecture scanner at {_BUILD_GRAPH_PATH}")
_BUILD_GRAPH_MODULE = importlib.util.module_from_spec(_BUILD_GRAPH_SPEC)
sys.modules[_BUILD_GRAPH_SPEC.name] = _BUILD_GRAPH_MODULE
_BUILD_GRAPH_SPEC.loader.exec_module(_BUILD_GRAPH_MODULE)

scan_package = _BUILD_GRAPH_MODULE.scan_package


@functools.cache
def _edges() -> tuple:
    return tuple(scan_package(PKG_ROOT))


def _layout(package: str) -> dict:
    path = HERE / f"{package}_layout.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _root(package: str) -> pathlib.Path:
    return PKG_ROOT / package


def _dotted(package: str) -> str:
    return f"hydromodpy.{package}"


def _in_package(module: str, package: str) -> bool:
    dotted = _dotted(package)
    return module == dotted or module.startswith(dotted + ".")


def _unit(module: str) -> str:
    """The part of a package a module belongs to: ``module.split(".")[2]``."""
    parts = module.split(".")
    return parts[2] if len(parts) > 2 else "<init>"


def _relative(edge) -> str:
    return pathlib.Path(edge.src_file).relative_to(REPO_ROOT).as_posix()


def _src_module(edge) -> str:
    path = pathlib.Path(edge.src_file).relative_to(REPO_ROOT).with_suffix("")
    parts = list(path.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _layer(edge) -> str:
    """The layer of hydromodpy an edge starts from, ``"<root>"`` for a root module."""
    parts = pathlib.Path(edge.src_file).relative_to(PKG_ROOT).parts
    return parts[0] if len(parts) > 1 else "<root>"


def _package_edges(package: str) -> list:
    root = _root(package)
    return [edge for edge in _edges() if pathlib.Path(edge.src_file).is_relative_to(root)]


def _describe(edge) -> str:
    return f"{_relative(edge)}:{edge.lineno} imports {edge.target_module} ({edge.kind})"


def _pattern_regex(pattern: str) -> re.Pattern[str]:
    """A ``*`` is one dotted name; a trailing ``.*`` also takes the whole subtree."""
    subtree = pattern.endswith(".*")
    base = pattern[:-2] if subtree else pattern
    body = r"\.".join("[^.]+" if part == "*" else re.escape(part) for part in base.split("."))
    return re.compile(body + (r"(\..+)?" if subtree else "") + r"\Z")


def _is_public(module: str, patterns: list[str]) -> bool:
    return any(_pattern_regex(pattern).match(module) for pattern in patterns)


def _modules(package: str) -> set[str]:
    return {
        ".".join(path.relative_to(REPO_ROOT).with_suffix("").parts).removesuffix(".__init__")
        for path in _root(package).rglob("*.py")
    }


def _text_edges(package: str) -> list:
    """Edges the package writes as text, from the files its layout allows to."""
    text_path_files = set(_layout(package)["text_paths"])
    return [
        edge
        for edge in _package_edges(package)
        if edge.kind in TEXT_KINDS
        and _relative(edge) in text_path_files
        and _in_package(edge.target_module, package)
    ]


# -- rules of every layout -----------------------------------------------------


def test_every_package_with_a_layout_is_seen() -> None:
    assert sorted(SEEN_PARTS) == sorted(PACKAGES), (
        "a *_layout.yaml without its entry in SEEN_PARTS, or the reverse"
    )


@pytest.mark.parametrize("package", PACKAGES)
def test_the_scanner_sees_the_package(package: str) -> None:
    """Anti-vacuity: an empty scan would make every rule below pass."""
    parts = {_unit(_src_module(edge)) for edge in _package_edges(package)}
    assert SEEN_PARTS[package] <= parts


@pytest.mark.parametrize("package", PACKAGES)
def test_every_part_has_a_row(package: str) -> None:
    root = _root(package)
    declared = set(_layout(package)["allowed"])
    subpackages = {
        path.name for path in root.iterdir() if path.is_dir() and (path / "__init__.py").is_file()
    }
    root_modules = {path.stem for path in root.glob("*.py") if path.name != "__init__.py"}
    actual = subpackages | root_modules | {"<init>"}
    assert sorted(actual - declared) == [], f"parts without a row in {package}_layout.yaml"
    assert sorted(declared - actual) == [], f"rows of {package}_layout.yaml without a part"


@pytest.mark.parametrize("package", PACKAGES)
def test_a_row_names_only_rows_above_it(package: str) -> None:
    """The table cannot allow a cycle: a row names only rows written above it.

    Enforced on the YAML text itself, not on the edges the scanner finds: this
    catches a row that *would* allow a cycle even before any code uses it.
    """
    allowed = _layout(package)["allowed"]
    order = list(allowed)
    offenders = [
        f"{unit} -> {target}"
        for i, unit in enumerate(order)
        for target in allowed[unit]
        if target not in order[:i]
    ]
    assert not offenders, (
        f"{package}_layout.yaml names a row at or below the row that allows it "
        "(rows must be written lowest first):\n  " + "\n  ".join(offenders)
    )


@pytest.mark.parametrize("package", PACKAGES)
def test_a_part_imports_only_what_its_row_allows(package: str) -> None:
    allowed = {unit: set(targets) for unit, targets in _layout(package)["allowed"].items()}
    text = {id(edge) for edge in _text_edges(package)}
    offenders = []
    for edge in _package_edges(package):
        if not _in_package(edge.target_module, package) or id(edge) in text:
            continue
        src, tgt = _unit(_src_module(edge)), _unit(edge.target_module)
        if src == tgt or tgt in allowed.get(src, set()):
            continue
        offenders.append(f"[{src} -> {tgt}] {_describe(edge)}")
    assert not offenders, (
        f"imports that tests/unit/architecture/{package}_layout.yaml forbids:\n  "
        + "\n  ".join(offenders)
    )


@pytest.mark.parametrize("package", PACKAGES)
def test_another_layer_imports_only_the_public_modules(package: str) -> None:
    patterns = _layout(package)["public"]
    root = _root(package)
    offenders = [
        _describe(edge)
        for edge in _edges()
        if not pathlib.Path(edge.src_file).is_relative_to(root)
        and _in_package(edge.target_module, package)
        and not _is_public(edge.target_module, patterns)
    ]
    assert not offenders, (
        f"another layer imports a module of hydromodpy/{package} that the public "
        f"list of {package}_layout.yaml does not name:\n  " + "\n  ".join(offenders)
    )


@pytest.mark.parametrize("package", PACKAGES)
def test_a_tolerated_layer_imports_only_its_line(package: str) -> None:
    """``layer_matrix.yaml`` tolerates a whole layer; the layout narrows it."""
    tolerated = _layout(package).get("tolerated", {})
    offenders = [
        _describe(edge)
        for edge in _edges()
        if _layer(edge) in tolerated
        and _in_package(edge.target_module, package)
        and not _is_public(edge.target_module, tolerated[_layer(edge)])
    ]
    assert not offenders, (
        f"a layer tolerated by layer_matrix.yaml imports a module of hydromodpy/{package} "
        f"that its line under tolerated in {package}_layout.yaml does not name:\n  "
        + "\n  ".join(offenders)
    )


@pytest.mark.parametrize("package", PACKAGES)
def test_the_public_patterns_name_existing_modules(package: str) -> None:
    """A public entry that matches nothing protects nothing."""
    layout = _layout(package)
    modules = _modules(package)
    patterns = list(layout["public"])
    for targets in layout.get("tolerated", {}).values():
        patterns.extend(targets)
    stale = [
        pattern
        for pattern in patterns
        if not any(_is_public(module, [pattern]) for module in modules)
    ]
    assert stale == []


@pytest.mark.parametrize("package", PACKAGES)
def test_the_text_path_files_exist(package: str) -> None:
    missing = [path for path in _layout(package)["text_paths"] if not (REPO_ROOT / path).is_file()]
    assert missing == []


# -- hydromodpy/data -------------------------------------------------------------


def test_no_module_sits_at_the_root_of_data() -> None:
    assert sorted(p.name for p in _root("data").glob("*.py")) == ["__init__.py"], (
        "a module sits at the root of hydromodpy/data; it belongs in a subpackage"
    )


def _data_variable(module: str) -> str | None:
    """The variable package a module belongs to, or None outside one."""
    parts = module.split(".")
    if len(parts) > 3 and parts[2] == "variables":
        candidate = _root("data") / "variables" / parts[3]
        return parts[3] if candidate.is_dir() else None
    return None


def test_a_variable_never_imports_another_variable() -> None:
    offenders = []
    for edge in _package_edges("data"):
        src_var = _data_variable(_src_module(edge))
        tgt_var = _data_variable(edge.target_module)
        if src_var and tgt_var and src_var != tgt_var:
            offenders.append(_describe(edge))
    assert not offenders, "one variable imports another:\n  " + "\n  ".join(offenders)


def _builtin_targets(registry_module) -> set[str]:
    return {path.split(":", 1)[0] for path in registry_module._BUILTIN_PATHS.values()}


def _text_edges_outside_the_builtins(package: str, builtins: set[str]) -> list[str]:
    return [
        _describe(edge)
        for edge in _text_edges(package)
        if _unit(_src_module(edge)) != _unit(edge.target_module)
        and edge.target_module not in builtins
    ]


def test_the_data_source_registry_names_only_its_builtin_sources() -> None:
    """Rule 6: the dotted paths written as text are the built-in sources."""
    from hydromodpy.data.source import registry

    offenders = _text_edges_outside_the_builtins("data", _builtin_targets(registry))
    assert not offenders, "a text path names a module that is not a built-in source:\n  " + (
        "\n  ".join(offenders)
    )


# -- hydromodpy/calibration --------------------------------------------------------


def test_the_calibration_evaluator_registry_names_only_its_builtin_evaluators() -> None:
    """Rule 5: the dotted paths written as text are the built-in evaluators."""
    from hydromodpy.calibration.evaluation import registry

    offenders = _text_edges_outside_the_builtins("calibration", _builtin_targets(registry))
    assert not offenders, (
        "a text path names a module that is not a built-in evaluator:\n  " + "\n  ".join(offenders)
    )


def test_config_reads_the_upper_parts_only_inside_its_validators() -> None:
    """``config`` may import criteria, evaluation and optim, but only from
    inside a validator (hydromodpy/calibration/README.md, "Import rules":
    "inside validators only"), never at module level, so the schema classes
    stay importable without validating anything.

    The scanner has no notion of "a pydantic validator"; the closest thing it
    can see is whether the import sits inside a function body at all.
    """
    offenders = [
        _describe(edge)
        for edge in _package_edges("calibration")
        if _unit(_src_module(edge)) == "config"
        and _unit(edge.target_module) in {"criteria", "evaluation", "optim"}
        and not edge.in_function
    ]
    assert not offenders, (
        "config.py imports criteria, evaluation or optim outside a function "
        "(so outside a validator):\n  " + "\n  ".join(offenders)
    )


def test_evaluation_reads_optim_only_for_types() -> None:
    """``evaluation`` may import optim, but only for type hints
    (hydromodpy/calibration/README.md, "Import rules": "optim (types only)").

    The scanner has no notion of "a type hint"; the closest thing it can see
    is whether the import sits under ``if TYPE_CHECKING:``.
    """
    offenders = [
        _describe(edge)
        for edge in _package_edges("calibration")
        if _unit(_src_module(edge)) == "evaluation"
        and _unit(edge.target_module) == "optim"
        and not edge.in_type_checking
    ]
    assert not offenders, "evaluation imports optim outside TYPE_CHECKING:\n  " + "\n  ".join(
        offenders
    )


def test_preflight_reads_the_other_parts_only_inside_its_checks() -> None:
    """``preflight`` may import criteria, metrics, observations, optim,
    parameter_resolution, runners and targets, but only from inside one of its
    checks (hydromodpy/calibration/README.md, "Import rules": "inside its
    checks"), never at module level: ``hmp calibrate --check`` runs every check
    and reports once, and a module-level import would pull in the whole upper
    half of the package before any check runs.

    The scanner has no notion of "a check function"; the closest thing it can
    see is whether the import sits inside a function body at all.
    """
    offenders = [
        _describe(edge)
        for edge in _package_edges("calibration")
        if _unit(_src_module(edge)) == "preflight"
        and _unit(edge.target_module)
        in {
            "criteria",
            "metrics",
            "observations",
            "optim",
            "parameter_resolution",
            "runners",
            "targets",
        }
        and not edge.in_function
    ]
    assert not offenders, (
        "preflight.py imports another part outside a function (so outside a "
        "check):\n  " + "\n  ".join(offenders)
    )


def _is_solver_module(module: str) -> bool:
    return module == "hydromodpy.solver" or module.startswith("hydromodpy.solver.")


def test_calibration_reaches_solver_only_through_generic_ports() -> None:
    """Rule 4: calibration reaches a solver only through the generic ports of
    ``hydromodpy.solver.base``, never a backend package (``modflow6``,
    ``modflow_nwt``, ``modflow_common``, ``boussinesq``), so a backend can be
    added or replaced without touching calibration.
    """
    patterns = _layout("calibration")["solver_access"]
    offenders = [
        _describe(edge)
        for edge in _package_edges("calibration")
        if _is_solver_module(edge.target_module) and not _is_public(edge.target_module, patterns)
    ]
    assert not offenders, (
        "calibration imports a solver module that solver_access in "
        "calibration_layout.yaml does not allow:\n  " + "\n  ".join(offenders)
    )


# -- hydromodpy/display -----------------------------------------------------------


def test_the_display_registry_names_only_the_figures_package() -> None:
    """The registry imports ``hydromodpy.display.figures`` by name on first
    lookup, so that importing the registry stays light. That is the one module
    it may name as text."""
    named = {edge.target_module for edge in _text_edges("display")}
    assert named <= {"hydromodpy.display.figures"}, sorted(named)
