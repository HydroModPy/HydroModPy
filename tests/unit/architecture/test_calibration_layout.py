"""Enforce the import rules inside ``hydromodpy/calibration``.

``layer_matrix.yaml`` declares ``calibration`` as one layer, so an import from
``calibration/runners`` into ``calibration/optim`` is an edge it allows. The map
of the package, ``hydromodpy/calibration/README.md``, orders the parts and
states the rules; ``calibration_layout.yaml`` says who may import whom, and
this module checks it with the scanner the layer matrix uses. Every import
counts: at module level, inside a function, under ``TYPE_CHECKING``, or as a
dotted path written in a lazy-attribute table.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import sys

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
PKG_ROOT = REPO_ROOT / "hydromodpy"
CALIBRATION_ROOT = PKG_ROOT / "calibration"
LAYOUT_FILE = pathlib.Path(__file__).with_name("calibration_layout.yaml")
CALIBRATION = "hydromodpy.calibration"

_BUILD_GRAPH_PATH = REPO_ROOT / "tools" / "audit" / "build_graph.py"
_BUILD_GRAPH_SPEC = importlib.util.spec_from_file_location(
    "hydromodpy_calibration_layout_build_graph",
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


def _in_calibration(module: str) -> bool:
    return module == CALIBRATION or module.startswith(CALIBRATION + ".")


def _unit(module: str) -> str:
    """The part of ``hydromodpy.calibration`` a module belongs to.

    A part is a subpackage (``optim``, ``runners``, ...) or a module at the
    root of the package (``config``, ``targets``, ...): both sit at
    ``module.split(".")[2]``. The package facade itself,
    ``hydromodpy.calibration``, has nothing at that index.
    """
    parts = module.split(".")
    return parts[2] if len(parts) > 2 else "<init>"


def _src_module(edge) -> str:
    path = pathlib.Path(edge.src_file).relative_to(REPO_ROOT).with_suffix("")
    parts = list(path.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _calibration_edges() -> list:
    return [
        edge for edge in _edges() if pathlib.Path(edge.src_file).is_relative_to(CALIBRATION_ROOT)
    ]


def _describe(edge) -> str:
    return f"{_relative(edge)}:{edge.lineno} imports {edge.target_module} ({edge.kind})"


def _builtin_source_modules() -> set[str]:
    from hydromodpy.calibration.evaluation import registry

    return {path.split(":", 1)[0] for path in registry._BUILTIN_PATHS.values()}


def test_the_scanner_sees_the_calibration_package() -> None:
    """Anti-vacuity: an empty scan would make every rule below pass."""
    units = {_unit(_src_module(edge)) for edge in _calibration_edges()}
    assert {"optim", "runners", "config", "criteria", "metrics"} <= units


def test_every_part_has_a_row() -> None:
    declared = set(_layout()["allowed"])
    subpackages = {
        path.name
        for path in CALIBRATION_ROOT.iterdir()
        if path.is_dir() and (path / "__init__.py").is_file()
    }
    root_modules = {
        path.stem for path in CALIBRATION_ROOT.glob("*.py") if path.name != "__init__.py"
    }
    actual = subpackages | root_modules | {"<init>"}
    assert sorted(actual - declared) == [], "parts without a row in calibration_layout.yaml"
    assert sorted(declared - actual) == [], "rows of calibration_layout.yaml without a part"


def test_a_row_names_only_rows_above_it() -> None:
    """The table cannot allow a cycle: a row names only rows written above it.

    Enforced on the YAML text itself, not on the edges the scanner finds: this
    catches a row that *would* allow a cycle even before any code uses it.
    """
    allowed = _layout()["allowed"]
    order = list(allowed)
    offenders = [
        f"{unit} -> {target}"
        for i, unit in enumerate(order)
        for target in allowed[unit]
        if target not in order[:i]
    ]
    assert not offenders, (
        "calibration_layout.yaml names a row at or below the row that allows it "
        "(rows must be written lowest first):\n  " + "\n  ".join(offenders)
    )


def test_a_part_imports_only_what_its_row_allows() -> None:
    layout = _layout()
    allowed = {unit: set(targets) for unit, targets in layout["allowed"].items()}
    text_path_files = set(layout["text_paths"])
    builtins = _builtin_source_modules()
    offenders = []
    for edge in _calibration_edges():
        if not _in_calibration(edge.target_module):
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
        "imports that tests/unit/architecture/calibration_layout.yaml forbids:\n  "
        + "\n  ".join(offenders)
    )


def test_config_reads_the_upper_parts_only_inside_its_validators() -> None:
    """``config`` may import criteria, evaluation and optim, but only from
    inside a validator (calibration-README-cible.md, "Import rules": "inside
    validators only"), never at module level, so the schema classes stay
    importable without validating anything.

    The scanner has no notion of "a pydantic validator"; the closest thing it
    can see is whether the import sits inside a function body at all.
    """
    offenders = [
        _describe(edge)
        for edge in _calibration_edges()
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
    (calibration-README-cible.md, "Import rules": "optim (types only)").

    The scanner has no notion of "a type hint"; the closest thing it can see
    is whether the import sits under ``if TYPE_CHECKING:``.
    """
    offenders = [
        _describe(edge)
        for edge in _calibration_edges()
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
    checks (calibration-README-cible.md, "Import rules": "inside its checks"),
    never at module level: ``hmp calibrate --check`` runs every check and
    reports once, and a module-level import would pull in the whole upper half
    of the package before any check runs.

    The scanner has no notion of "a check function"; the closest thing it can
    see is whether the import sits inside a function body at all.
    """
    offenders = [
        _describe(edge)
        for edge in _calibration_edges()
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
    patterns = _layout()["solver_access"]
    offenders = [
        _describe(edge)
        for edge in _calibration_edges()
        if _is_solver_module(edge.target_module) and not _is_public(edge.target_module, patterns)
    ]
    assert not offenders, (
        "calibration imports a solver module that solver_access in "
        "calibration_layout.yaml does not allow:\n  " + "\n  ".join(offenders)
    )


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
        if not pathlib.Path(edge.src_file).is_relative_to(CALIBRATION_ROOT)
        and _in_calibration(edge.target_module)
        and not _is_public(edge.target_module, patterns)
    ]
    assert not offenders, (
        "another layer imports a module of hydromodpy/calibration that the public "
        "list of calibration_layout.yaml does not name:\n  " + "\n  ".join(offenders)
    )


def test_the_public_patterns_name_existing_modules() -> None:
    """A public entry that matches nothing protects nothing."""
    modules = {
        ".".join(path.relative_to(REPO_ROOT).with_suffix("").parts).removesuffix(".__init__")
        for path in CALIBRATION_ROOT.rglob("*.py")
    }
    stale = [
        pattern
        for pattern in _layout()["public"]
        if not any(_is_public(module, [pattern]) for module in modules)
    ]
    assert stale == []
