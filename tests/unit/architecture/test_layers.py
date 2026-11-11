"""Who reads whom: the layer matrix, the ports that stand alone, the string paths.

The matrix is a release gate, so an undocumented cross-layer import fails the
suite. ``allowed`` holds the target rows. While packages move, ``transitional``
says what holds today, and an entry the tree no longer needs fails too. Below
the matrix sit the ports that promise a third party a short import list
(``PORTS``), the rules written as a syntax-tree pattern (``RULES``, each with
a bad example the rule must flag), the DuckDB boundary, and the module paths
the repository writes as strings.
"""

from __future__ import annotations

import ast
import functools
import glob
import importlib
import json
import pathlib
import re
import subprocess
import sys
import tomllib
from collections import Counter, defaultdict
from collections.abc import Callable
from typing import Any, NamedTuple

import pytest
import yaml

from tests.unit.architecture import _scan
from tests.unit.architecture._scan import (
    PKG_ROOT,
    REPO_ROOT,
    Rule,
    called_name,
    calls,
    module_assignments,
    names_in,
    offences,
    parse,
    rel,
)
from tools.doc_contracts import (
    LAYER_MATRIX_PAGE,
    MAIN_FILE,
    MAIN_KEY,
    ROOT_KEY,
    LayerRows,
    assert_layer_matrix_inputs,
    is_package,
    layer_rows,
    load_layer_matrix,
    present_layers,
    render_layer_matrix,
)

HERE = pathlib.Path(__file__).resolve().parent
PACKAGES_INDEX = REPO_ROOT / "docs/source/contribute/architecture/packages/index.rst"
# Package pages that describe no package of hydromodpy.
PAGES_WITHOUT_A_ROW = {"index", "validity_frame"}

# ---------------------------------------------------------------------------
# The layer matrix
# ---------------------------------------------------------------------------


class Judgement(NamedTuple):
    """What the matrix makes of every edge of the tree."""

    violations: list[tuple[str, str, Any]]
    siblings: list[Any]
    edges_used: dict[int, set[str]]
    reads_used: dict[str, set[str]]


def judge(matrix: dict[str, Any], edges) -> Judgement:
    """Judge each edge in turn.

    An edge inside one package passes. An edge from a leaving package passes
    when its row reads the target. Otherwise the target row of the source
    must grant it, or a transitional edge of the same pair must, and when
    that entry names files the source file must be one of them.
    """
    rows = layer_rows(matrix)
    tolerances = {(t["src"], t["tgt"]) for t in matrix.get("tolerances") or []}
    exempt = set(matrix.get("exempt_files") or [])
    violations: list[tuple[str, str, Any]] = []
    siblings: list[Any] = []
    edges_used: dict[int, set[str]] = defaultdict(set)
    reads_used: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        path = rel(edge.src_file)
        if path in exempt:
            continue
        if edge.tgt_pkg == "<sibling>":
            siblings.append(edge)
            continue
        src = MAIN_KEY if path == MAIN_FILE else edge.src_pkg
        tgt = edge.tgt_pkg
        if src == tgt:
            continue
        if src in rows.leaving:
            if tgt in (rows.leaving[src].get("reads") or []):
                reads_used[src].add(tgt)
            else:
                violations.append((src, tgt, edge))
            continue
        if tgt in rows.target.get(src, []) or (src, tgt) in tolerances:
            continue
        granted = False
        for index, entry in enumerate(rows.edges):
            files = entry.get("files") or []
            if entry["src"] == src and entry["tgt"] == tgt and (not files or path in files):
                edges_used[index].add(path)
                granted = True
        if not granted:
            violations.append((src, tgt, edge))
    return Judgement(violations, siblings, edges_used, reads_used)


@functools.cache
def _judgement() -> Judgement:
    return judge(load_layer_matrix(), _scan.package_edges())


def stale_entries(rows: LayerRows, judgement: Judgement) -> list[str]:
    """The transitional entries the tree no longer needs."""
    stale: list[str] = []
    for layer in rows.leaving:
        if not is_package(layer):
            stale.append(f"leaving {layer!r}: the package is gone")
    for layer in rows.arriving:
        if is_package(layer):
            stale.append(f"arriving {layer!r}: the package exists, its row now holds")
    for index, entry in enumerate(rows.edges):
        src, tgt = entry["src"], entry["tgt"]
        if src in rows.arriving or tgt in rows.arriving:
            continue
        used = judgement.edges_used.get(index, set())
        if not used:
            stale.append(f"edge {src} -> {tgt}: no import makes it any more")
            continue
        for path in entry.get("files") or []:
            if path not in used:
                stale.append(f"edge {src} -> {tgt}: {path} no longer makes it")
    for layer, entry in rows.leaving.items():
        for target in entry.get("reads") or []:
            if target != layer and target not in judgement.reads_used.get(layer, set()):
                stale.append(f"leaving {layer!r} reads {target!r}: no import uses it")
    return stale


def _top_level_packages() -> set[str]:
    return {
        path.name
        for path in PKG_ROOT.iterdir()
        if path.is_dir() and (path / "__init__.py").is_file() and not path.name.startswith("__")
    }


def _package_pages() -> set[str]:
    return {path.stem for path in PACKAGES_INDEX.parent.glob("*.rst")}


def test_layer_matrix() -> None:
    """Reject undocumented forbidden cross-layer imports."""
    violations = _judgement().violations
    if violations:
        per_pair = Counter((s, t, edge.kind) for s, t, edge in violations)
        breakdown = "\n".join(
            f"  {s:>12} -> {t:<12} {n:>4}  via {k}" for (s, t, k), n in per_pair.most_common()
        )
        examples = "\n".join(
            f"  {rel(edge.src_file)}:{edge.lineno} imports {edge.target_module}"
            for _s, _t, edge in violations[:20]
        )
        pytest.fail(f"{len(violations)} layer-matrix violations:\n{breakdown}\n{examples}")


def test_a_transitional_entry_is_still_needed() -> None:
    """A move that empties a package removes its entries in the same change."""
    stale = stale_entries(layer_rows(load_layer_matrix()), _judgement())
    assert stale == [], "remove from transitional in layer_matrix.yaml:\n  " + "\n  ".join(stale)


def test_the_matrix_judges_a_bad_edge() -> None:
    """Anti-vacuity of ``judge``: a core import of ``cli`` is a violation, a cli import of core is not."""
    matrix = {"allowed": {"core": [], "cli": ["core"]}, "transitional": {}}
    bad = _scan.edge("hydromodpy/core/x.py", "hydromodpy.cli.y", src_pkg="core", tgt_pkg="cli")
    good = _scan.edge("hydromodpy/cli/x.py", "hydromodpy.core.y", src_pkg="cli", tgt_pkg="core")
    assert [v[:2] for v in judge(matrix, [bad, good]).violations] == [("core", "cli")]


def test_layer_matrix_declares_every_top_level_package() -> None:
    declared = present_layers(load_layer_matrix()) - {ROOT_KEY}
    actual = _top_level_packages()
    assert sorted(actual - declared) == [], "packages missing from the layer matrix"
    assert sorted(declared - actual) == [], "layer matrix rows without a package"


def test_layer_tolerances_are_declared_and_needed() -> None:
    matrix = load_layer_matrix()
    allowed = {k: set(v) for k, v in matrix["allowed"].items()}
    pairs = [(e["src"], e["tgt"]) for e in matrix.get("tolerances", [])]
    unknown = [p for p in pairs if p[0] not in allowed or p[1] not in allowed]
    redundant = [p for p in pairs if p[1] in allowed.get(p[0], set())]
    assert (unknown, redundant) == ([], [])


def test_a_row_cites_only_rows_above_it() -> None:
    """Rows run lowest first, so the matrix cannot hide a cycle between layers.

    A leaving row comes after every target row, so it may cite any of them,
    and the leaving rows written above it.
    """
    rows = layer_rows(load_layer_matrix())
    order = [*rows.target, *rows.leaving]
    position = {layer: index for index, layer in enumerate(order)}
    cited = [*rows.target.items(), *((k, v.get("reads") or []) for k, v in rows.leaving.items())]
    backward = {
        (layer, target)
        for layer, targets in cited
        for target in targets
        if position.get(target, len(order)) > position[layer]
    }
    assert backward == set(), f"edges pointing down the file: {sorted(backward)}"


def test_architecture_package_pages_match_the_rows() -> None:
    present = present_layers(load_layer_matrix())
    assert sorted((present - {ROOT_KEY}) - _package_pages()) == [], "missing package pages"
    assert sorted(_package_pages() - PAGES_WITHOUT_A_ROW - present) == [], "orphan package pages"


def test_the_layer_contract_is_sound() -> None:
    """Each row matches the tree of today, and every edge names a declared row."""
    problems = assert_layer_matrix_inputs(load_layer_matrix())
    assert problems == [], "layer_matrix.yaml declares something that does not exist:\n  - " + (
        "\n  - ".join(problems)
    )


def test_committed_layer_matrix_page_matches_the_contract() -> None:
    committed = (REPO_ROOT / LAYER_MATRIX_PAGE).read_text(encoding="utf-8")
    assert committed == render_layer_matrix(load_layer_matrix()), (
        f"{LAYER_MATRIX_PAGE.as_posix()} is stale: run `python -m tools.doc_contracts`"
    )


def test_siblings_one_way() -> None:
    """``hydromodpy/`` never imports a folder beside it, such as the annex or the server."""
    siblings = _judgement().siblings
    assert siblings == [], "\n".join(
        f"{e.src_file}:{e.lineno} imports {e.target_module}" for e in siblings
    )


def test_every_sibling_has_a_row() -> None:
    rows = set(load_layer_matrix().get("siblings") or {})
    assert rows == set(_scan.sibling_packages())


def test_a_sibling_reads_only_its_row() -> None:
    """A sibling whose row is a list imports only the packages of that list."""
    outside = [
        f"{rel(edge.src_file)}:{edge.lineno} imports {edge.target_module}"
        for name, row in (load_layer_matrix().get("siblings") or {}).items()
        if row != "*"
        for edge in _scan.sibling_edges(name)
        if edge.target_module.split(".")[0] != name and edge.tgt_pkg not in row
    ]
    assert outside == [], "\n".join(outside)


def test_entry_points_only_target_annex() -> None:
    """The wheel carries no entry point to internal code: only the annex joins by plugin groups."""
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    tables = data.get("project", {}).get("entry-points", {})
    assert tables, "pyproject.toml should declare [project.entry-points]"
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    for group, entries in tables.items():
        assert entries, f"entry-point group {group!r} is empty"
        for name, target in entries.items():
            module_name, _, attr_name = target.partition(":")
            assert module_name.startswith("hydromodpy_annex."), f"{group}: {name} -> {target}"
            assert attr_name, f"{group}: {name} lacks an attribute: {target!r}"
            cls = getattr(importlib.import_module(module_name), attr_name)
            assert isinstance(cls, type), f"{target!r} should resolve to a class"
            assert getattr(cls, "name", None) == name, f"{cls} declares another name than {name!r}"


@pytest.mark.parametrize(
    ("module", "name"),
    [
        ("hydromodpy.catchment.preprocess.geographic_config", "GeographicConfig"),
        ("hydromodpy.catchment.algorithms.hydrographic_network", "HydrographicNetwork"),
        (
            "hydromodpy.catchment.algorithms.hydrographic_network_comparison",
            "compare_hydrographic_networks",
        ),
        ("hydromodpy.catchment.synthetic.catchment", "build_synthetic_geographic"),
    ],
)
def test_a_geographic_name_imports_without_a_cycle(module: str, name: str) -> None:
    assert getattr(importlib.import_module(module), name) is not None


# ---------------------------------------------------------------------------
# Ports that stand alone
# ---------------------------------------------------------------------------


def _under(module: str, prefixes: tuple[str, ...]) -> bool:
    return any(module == p or module.startswith(p + ".") for p in prefixes)


def _builtin_provider_modules() -> set[str]:
    from hydromodpy.data.source import registry

    return {path.split(":", 1)[0] for path in registry._BUILTIN_PATHS.values()}


def _names_a_builtin_by_text(edge) -> bool:
    """The registry names its built-ins by dotted text: imported on first lookup only."""
    return edge.kind == "lazy_map" and edge.target_module in _builtin_provider_modules()


class Port(NamedTuple):
    """One promise about the imports that start under ``root``.

    ``allowed`` is a whitelist of module prefixes. Without it, ``forbidden``
    prefixes are refused except under ``own``. ``excused`` names an edge that
    may stay, and ``seen`` the files a scan must find, so an empty scan fails.
    """

    id: str
    root: str
    allowed: tuple[str, ...] | None
    forbidden: tuple[str, ...] = ()
    own: str = ""
    excused: Callable[[Any], bool] | None = None
    seen: tuple[str, ...] = ()
    skip: tuple[str, ...] = ()


TERRAIN_EXCEPTIONS: dict[tuple[str, str], str] = {
    ("hydromodpy/catchment/terrain/whitebox_engine.py", "hydromodpy.catchment.delineation"): (
        "the injection point stays the Whitebox backend, resolved lazily inside a "
        "method, so a third-party engine never loads this module."
    ),
}
"""Every remaining edge out of ``terrain``, each with the reason that allows it."""

PORTS = (
    Port(
        "data_source",
        "hydromodpy/data/source",
        allowed=(
            "hydromodpy.core",
            "hydromodpy.data.contracts",
            "hydromodpy.data.provenance",
            "hydromodpy.data.source",
            "hydromodpy.schema",
        ),
        excused=_names_a_builtin_by_text,
        seen=("hydromodpy/data/source/port.py", "hydromodpy/data/source/registry.py"),
    ),
    Port(
        "data_source_port_module",
        "hydromodpy/data/source/port.py",
        allowed=("hydromodpy.core", "hydromodpy.data.contracts", "hydromodpy.schema"),
        seen=("hydromodpy/data/source/port.py",),
    ),
    Port(
        "terrain",
        "hydromodpy/catchment/terrain",
        allowed=("hydromodpy.core", "hydromodpy.catchment.terrain"),
        excused=lambda e: (rel(e.src_file), e.target_module) in TERRAIN_EXCEPTIONS,
        seen=tuple(f"hydromodpy/catchment/terrain/{n}.py" for n in ("port", "numpy_engine")),
    ),
    Port(
        "project_launch",
        "hydromodpy/project/launch",
        allowed=None,
        forbidden=("hydromodpy.project",),
        own="hydromodpy.project.launch",
    ),
    Port(
        "project_exchange",
        "hydromodpy/project/exchange",
        allowed=None,
        forbidden=("hydromodpy.project",),
        own="hydromodpy.project.exchange",
    ),
    Port(
        "cli_boundary",
        "hydromodpy",
        allowed=None,
        forbidden=("hydromodpy.cli",),
        skip=("hydromodpy/cli/", "hydromodpy/__main__.py"),
    ),
    Port(
        "builtin_sources_reach_no_state",
        "hydromodpy/data/variables",
        allowed=None,
        forbidden=(
            "hydromodpy.data.families",
            "hydromodpy.data.loading",
            "hydromodpy.workflow",
            "hydromodpy.project",
        ),
    ),
)


def breaks(port: Port, edge) -> bool:
    """Whether one import edge breaks the promise of ``port``."""
    path = rel(edge.src_file)
    if path.startswith(port.skip) if port.skip else False:
        return False
    if port.excused is not None and port.excused(edge):
        return False
    module = edge.target_module
    if port.allowed is not None:
        return not _under(module, port.allowed)
    return _under(module, port.forbidden) and not (port.own and _under(module, (port.own,)))


def _port_edges(port: Port) -> list:
    root = REPO_ROOT / port.root
    edges = _scan.edges_under(root)
    if port.id == "builtin_sources_reach_no_state":
        files = {m.replace(".", "/") + ".py" for m in _builtin_provider_modules()}
        assert len(files) == len(_builtin_provider_modules())
        edges = [e for e in _scan.package_edges() if rel(e.src_file) in files]
        assert {rel(e.src_file) for e in edges} == files, "anti-vacuity"
    return edges


@pytest.mark.parametrize("port", PORTS, ids=lambda p: p.id)
def test_a_port_imports_only_what_it_promises(port: Port) -> None:
    edges = _port_edges(port)
    # Anti-vacuity: an empty scan would make the assertion below pass.
    assert len(edges) > 5 or port.id == "data_source_port_module"
    assert {rel(e.src_file) for e in edges} >= set(port.seen)
    offenders = [
        f"{rel(e.src_file)}:{e.lineno} imports {e.target_module}" for e in edges if breaks(port, e)
    ]
    assert not offenders, f"{port.id} breaks its import promise:\n  " + "\n  ".join(offenders)


@pytest.mark.parametrize("port", PORTS, ids=lambda p: p.id)
def test_a_port_flags_a_bad_import(port: Port) -> None:
    """Each promise flags an import of its own bad example and lets a good one pass."""
    bad_module = (port.forbidden or ("hydromodpy.data.loading",))[0]
    start = port.root if port.root.endswith(".py") else port.root + "/x.py"
    if port.id == "cli_boundary":
        start = "hydromodpy/core/x.py"
    elif port.id == "terrain":
        bad_module = "hydromodpy.catchment.delineation.backend"
    assert breaks(port, _scan.edge(start, bad_module))
    assert not breaks(port, _scan.edge(start, "hydromodpy.core.units"))


def test_a_terrain_exception_is_still_taken_and_deferred() -> None:
    """A stale exception hides the next one, and the Whitebox backend loads inside a method."""
    edges = _scan.edges_under(REPO_ROOT / "hydromodpy/catchment/terrain")
    taken = {(rel(e.src_file), e.target_module) for e in edges}
    assert [k for k in TERRAIN_EXCEPTIONS if k not in taken] == []
    backend = [e for e in edges if e.target_module.startswith("hydromodpy.catchment.delineation")]
    assert backend and all(e.in_function for e in backend)


def test_the_builtin_sources_are_all_in_the_registry() -> None:
    """A one-line subclass joins the registry for each section a built-in serves."""
    from hydromodpy.data.source import registry

    assert len(registry._BUILTIN_PATHS) == 73


@pytest.mark.allow_subprocess
def test_a_source_lookup_and_the_port_load_no_provider_library() -> None:
    """Measured as deltas in a fresh interpreter, after ``import hydromodpy``.

    ``requests`` is left out because ``import hydromodpy`` already loads it.
    """
    script = (
        "import json, sys\n"
        "import hydromodpy\n"
        "before = set(sys.modules)\n"
        "import hydromodpy.data.source.port\n"
        "port_added = sorted(set(sys.modules) - before)\n"
        "from hydromodpy.data.source.registry import data_sources\n"
        "report = {}\n"
        "for key in data_sources.names(shipped_only=True):\n"
        "    before = set(sys.modules)\n"
        "    data_sources.get(key)\n"
        "    report[key] = sorted(set(sys.modules) - before)\n"
        "print(json.dumps([report, port_added]))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True, cwd=REPO_ROOT
    )
    report, port_added = json.loads(out.stdout.strip().splitlines()[-1])
    assert len(report) == 73, "anti-vacuity: the registry resolved no built-in"
    heavy = {"geopandas", "pandas", "rasterio", "shapely", "xarray"}
    loaded = {k: sorted({n.split(".")[0] for n in v} & heavy) for k, v in report.items()}
    assert all(not v for v in loaded.values()), f"a lookup loaded {loaded}"
    pulled = {n.split(".")[0] for n in port_added} & (heavy | {"pydantic"})
    assert not pulled, f"importing the port pulls in {sorted(pulled)}"
    assert "hydromodpy.data.source.port" in port_added, "anti-vacuity"


# ---------------------------------------------------------------------------
# Rules written as a syntax-tree pattern
# ---------------------------------------------------------------------------

ENGINE = "hydromodpy/core/plugin_registry.py"
"""The one module allowed to scan an entry-point group."""
BUILTIN_TABLES = frozenset({"_BUILTIN_PATHS", "_BUILTIN_EXTRACTOR_PATHS"})
OWN_OBJECTS = frozenset({"self", "cls"})


def _tools_imports(tree: ast.Module, path: str) -> list[str]:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules = [node.module]
        elif isinstance(node, ast.Call) and called_name(node) == "import_module" and node.args:
            first = node.args[0]
            modules = [first.value] if isinstance(first, ast.Constant) else []
        else:
            continue
        found += [f"{node.lineno} imports {m}" for m in modules if re.match(r"tools(\.|$)", str(m))]
    return found


def _outside_the_engine_scan(tree: ast.Module, path: str) -> list[str]:
    if path == ENGINE:
        return []
    return [f"{c.lineno} scans an entry-point group" for c in calls(tree, "entry_points")]


def _own_discovery(tree: ast.Module, path: str) -> list[str]:
    found = [f"{c.lineno} walks a package with iter_modules" for c in calls(tree, "iter_modules")]
    found += [
        f"{line} keeps {name}, a dict of loaders"
        for name, line in module_assignments(tree).items()
        if name.endswith("_LOADERS")
    ]
    return found


def _unfed_table(tree: ast.Module, path: str) -> list[str]:
    declared = BUILTIN_TABLES & set(module_assignments(tree))
    fed: set[str] = set()
    for call in calls(tree, "PluginRegistry"):
        fed |= names_in(call)
    return [f"{name} feeds no PluginRegistry of its module" for name in sorted(declared - fed)]


def _duckdb_connects(tree: ast.AST) -> list[ast.Call]:
    return [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "connect"
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "duckdb"
    ]


def _read_only(call: ast.Call) -> bool:
    flags = [k.value for k in call.keywords if k.arg == "read_only"]
    return bool(flags) and isinstance(flags[0], ast.Constant) and flags[0].value is True


def _opens_a_file(call: ast.Call) -> bool:
    database = call.args[0] if call.args else None
    for keyword in call.keywords:
        if keyword.arg == "database":
            database = keyword.value
    return database is not None and not (
        isinstance(database, ast.Constant) and database.value == ":memory:"
    )


def _any_duckdb_connect(tree: ast.Module, path: str) -> list[str]:
    return [f"{c.lineno} calls duckdb.connect" for c in _duckdb_connects(tree)]


def _duckdb_import_or_connect(tree: ast.Module, path: str) -> list[str]:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        found += [f"{node.lineno} imports duckdb" for n in names if n.split(".")[0] == "duckdb"]
    return found + _any_duckdb_connect(tree, path)


def _writable_duckdb_open(tree: ast.Module, path: str) -> list[str]:
    helper = "hydromodpy/core/io/db_retry.py"
    if path == helper:
        return []
    opens = [c for c in _duckdb_connects(tree) if _opens_a_file(c)] + calls(
        tree, "connect_with_retry"
    )
    return [f"{c.lineno} opens a DuckDB file for writing" for c in opens if not _read_only(c)]


def _raw_connect_in_the_catalog(tree: ast.Module, path: str) -> list[str]:
    if path in INDEX_OPENERS or path in WRITE_OWNERS:
        return []
    return [f"{c.lineno} calls connect_with_retry" for c in calls(tree, "connect_with_retry")]


INDEX_OPENERS = {"hydromodpy/results/catalog/index_file.py"}
"""The one module that opens ``.hmp/index.duckdb``, through ``connect_with_retry``."""
WRITE_OWNERS = {
    "hydromodpy/results/catalog/adapters/duckdb.py",
    "hydromodpy/results/catalog/index_file.py",
}
"""The modules that may open a DuckDB file without ``read_only=True``."""
CONNECT_FILES = {"hydromodpy/core/io/db_retry.py"}
"""Every module allowed to call ``duckdb.connect``; a new one is a new scope to justify."""
DIAGNOSTIC_FILES = (
    "hydromodpy/cli/commands/doctor.py",
    "hydromodpy/display/catalog_figures.py",
    "hydromodpy/results/catalog/listing.py",
    "hydromodpy/results/catalog/liveness.py",
    "hydromodpy/results/catalog/privacy.py",
)


def _unless(files: set[str], judge):
    return lambda tree, path: [] if path in files else judge(tree, path)


def _writes_in_diagnostics(tree: ast.Module, path: str) -> list[str]:
    return [
        f"{c.lineno} opens DuckDB without read_only=True"
        for c in _duckdb_connects(tree)
        if not _read_only(c)
    ]


def _private(name: str) -> bool:
    return name.startswith("_") and not name.startswith("__")


def private_names_offences(trees: dict[str, ast.Module], group: Callable[[str], str]) -> list[str]:
    """A private name read inside a group must be declared somewhere in that group.

    Both spellings of a read count, ``obj._name`` and ``getattr(obj, "_name")``.
    ``self`` and ``cls`` are a module's own object, and dunders are Python's own.
    """
    declared: dict[str, set[str]] = defaultdict(set)
    for path, tree in trees.items():
        declared[group(path)] |= _scan.private_declared(tree)
    return sorted(
        f"{path}:{line} reads {name}, which {group(path)} never declares"
        for path, tree in trees.items()
        for line, name in _scan.private_reads(tree)
        if name not in declared[group(path)]
    )


RULES = (
    Rule(
        "the_wheel_imports_no_tools",
        ("hydromodpy/",),
        _tools_imports,
        "import tools.audit\nfrom tools.doc_contracts import x\n",
        "hydromodpy/core/x.py",
    ),
    Rule(
        "only_the_engine_scans_an_entry_point_group",
        ("hydromodpy/",),
        _outside_the_engine_scan,
        "from importlib import metadata\nmetadata.entry_points(group='g')\n",
        "hydromodpy/mesh/x.py",
    ),
    Rule(
        "no_module_discovers_classes_its_own_way",
        ("hydromodpy/",),
        _own_discovery,
        "import pkgutil\nfor m in pkgutil.iter_modules(p):\n    pass\nX_LOADERS = {}\n",
        "hydromodpy/mesh/x.py",
    ),
    Rule(
        "a_table_of_in_tree_classes_feeds_a_registry",
        ("hydromodpy/",),
        _unfed_table,
        "_BUILTIN_PATHS = {'a': 'm:C'}\nreg = PluginRegistry(name='x')\n",
        "hydromodpy/mesh/x.py",
    ),
    Rule(
        "no_open_of_duckdb_in_the_api_or_the_commands",
        ("hydromodpy/project/api.py", "hydromodpy/cli/commands/"),
        _any_duckdb_connect,
        "import duckdb\nduckdb.connect('x.db')\n",
        "hydromodpy/cli/commands/x.py",
    ),
    Rule(
        "the_data_package_knows_no_duckdb",
        ("hydromodpy/data/",),
        _duckdb_import_or_connect,
        "import duckdb\n",
        "hydromodpy/data/x.py",
    ),
    Rule(
        "a_diagnostic_opens_duckdb_read_only",
        DIAGNOSTIC_FILES,
        _writes_in_diagnostics,
        "import duckdb\nduckdb.connect('x.db')\n",
        "hydromodpy/cli/commands/doctor.py",
    ),
    Rule(
        "duckdb_connect_only_where_a_scope_is_declared",
        ("hydromodpy/",),
        _unless(CONNECT_FILES, _any_duckdb_connect),
        "import duckdb\nduckdb.connect(':memory:')\n",
        "hydromodpy/results/x.py",
    ),
    Rule(
        "a_duckdb_file_is_written_by_its_owner_only",
        ("hydromodpy/",),
        _unless(WRITE_OWNERS, _writable_duckdb_open),
        "import duckdb\nduckdb.connect('x.db')\n",
        "hydromodpy/results/x.py",
    ),
    Rule(
        "the_catalog_connects_through_the_index_file",
        ("hydromodpy/results/catalog/",),
        _raw_connect_in_the_catalog,
        "connect_with_retry('x.db')\n",
        "hydromodpy/results/catalog/listing.py",
    ),
)


@pytest.mark.parametrize("rule", RULES, ids=lambda r: r.id)
def test_the_tree_obeys(rule: Rule) -> None:
    assert offences(rule) == []


@pytest.mark.parametrize("rule", RULES, ids=lambda r: r.id)
def test_a_rule_flags_its_bad_example(rule: Rule) -> None:
    assert rule.judge(parse(rule.bad), rule.bad_at), "the rule flags nothing: the gate is empty"


def test_the_registry_engine_still_scans_and_the_tables_exist() -> None:
    assert calls(_scan.tree(REPO_ROOT / ENGINE), "entry_points"), f"{ENGINE} no longer scans"
    found = [
        p
        for p in _scan.files()
        if BUILTIN_TABLES & set(module_assignments(_scan.tree(p)))  # fmt: skip
    ]
    assert found, "no registry table found: the scan reads the wrong tree"


def test_the_index_is_opened_through_the_retry_helper() -> None:
    for path in sorted(INDEX_OPENERS):
        tree = _scan.tree(REPO_ROOT / path)
        assert calls(tree, "connect_with_retry"), path
        assert _duckdb_connects(tree) == [], path


def test_every_duckdb_write_owner_still_writes() -> None:
    """The owner list cannot rot: each declared owner still opens a file for writing."""
    writing = {rel(p) for p in _scan.files() if _writable_duckdb_open(_scan.tree(p), rel(p))}
    assert writing == WRITE_OWNERS


def test_the_catalog_family_names_none_of_the_retired_tables() -> None:
    tokens = ("workflow_events", "workflow_steps", "v_workflow_heartbeats", "audit_log")
    roots = [PKG_ROOT / "cli/commands/catalog", PKG_ROOT / "results/catalog"]
    offenders = [
        f"{rel(p)}:{t}"
        for root in roots
        for p in sorted(root.rglob("*.py"))
        for t in tokens
        if t in p.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_a_solver_package_reads_only_the_private_names_it_declares() -> None:
    """Per solver sub-package, so ``modflow_common`` cannot reach into one backend."""
    trees = {rel(p): _scan.tree(p) for p in _scan.files(PKG_ROOT / "solver")}

    def group(path: str) -> str:
        return path.split("/")[2]

    assert private_names_offences(trees, group) == []


def test_the_private_name_rule_sees_a_dotted_read_and_a_getattr() -> None:
    """A first draft matched only ``getattr(obj, "_name")``: the dotted read walked through."""
    bad = {
        "s/a/x.py": parse("value = model._mask\nother = getattr(m, '_ocean', None)\n"),
        "s/a/y.py": parse("value = self._cache\nvalue = obj.__dict__\n"),
        "s/b/z.py": parse("class K:\n    def f(self):\n        self._mask = 1\n"),
    }
    found = private_names_offences(bad, lambda path: path.split("/")[1])
    assert [f.split(" ")[2].rstrip(",") for f in found] == ["_mask", "_ocean"]


@pytest.fixture
def no_index_opening(monkeypatch):
    """Make any opening of the index fail loudly."""
    from hydromodpy.results.catalog import facade

    def _refuse(self, *_args, **_kwargs):
        raise AssertionError("the index was opened")

    monkeypatch.setattr(facade.Catalog, "__init__", _refuse)


def test_watch_reads_the_outcomes_and_never_the_index(tmp_path, no_index_opening) -> None:
    from hydromodpy.core.state.layout import catalog_path_for
    from hydromodpy.results.catalog.liveness import stale_running_sim_ids, watch_running
    from tests._helpers.sealed_runs import make_project, seal_run, write_attempt

    root = make_project(tmp_path / "demo")
    seal_run(root, "done")
    write_attempt(root, "runs/live", status="running", heartbeat_age_s=2)
    write_attempt(root, "runs/dead", status="running", heartbeat_age_s=3600)
    write_attempt(root, "runs/broken", status="failed")
    catalog_path_for(root).parent.mkdir(parents=True)
    catalog_path_for(root).write_bytes(b"not a database")

    rows = {row["rel_dir"]: row for row in watch_running(root)}

    assert set(rows) == {"runs/live", "runs/dead"}
    assert rows["runs/live"]["stale"] is False
    assert rows["runs/dead"]["stale"] is True
    assert stale_running_sim_ids(root) == ["runs/dead"]


def test_the_doctor_counts_read_the_sessions_and_never_the_index(
    tmp_path, no_index_opening
) -> None:
    from datetime import UTC, datetime, timedelta

    from hydromodpy.results.catalog.liveness import (
        abandoned_calibration_session_count,
        orphan_calibration_session_count,
    )
    from tests._helpers.sealed_runs import make_project, write_session_dir

    root = make_project(tmp_path / "demo")
    write_session_dir(root, "fresh", status="running", started_at=datetime.now(UTC))
    write_session_dir(
        root, "old", status="running", started_at=datetime.now(UTC) - timedelta(days=2)
    )
    write_session_dir(root, "orphan", best_trial=1, best_rel_dir="runs/gone")

    assert abandoned_calibration_session_count(root) == 1
    assert orphan_calibration_session_count(root) == 1


# ---------------------------------------------------------------------------
# Module paths written as strings
# ---------------------------------------------------------------------------
#
# A rename that leaves a string behind fails late, at the first access or run.
# This part reads the places that hold such strings and resolves each one on disk:
# module-level assignments in ``hydromodpy/`` and ``hydromodpy_annex/``, the first
# literal argument of ``import_module`` and the ``"implementation"`` key of a dict;
# the first literal argument of ``setattr``, ``delattr`` and ``patch`` in ``tests/``;
# ``pyproject.toml`` and ``.github/workflows/*.yml``. Nothing is imported. A chain
# resolves when its longest module prefix is a ``.py`` file, a package or a plain
# folder, and the name after it is defined in that module. ``dotted_paths.yaml``
# lists the strings that are not modules and the strings known to be stale.

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


def _load_allowed() -> dict:
    return yaml.safe_load(ALLOWED_FILE.read_text(encoding="utf-8"))


def _module_file(parts: tuple[str, ...]) -> pathlib.Path | None:
    base = REPO_ROOT.joinpath(*parts)
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _is_module(parts: tuple[str, ...]) -> bool:
    folder = REPO_ROOT.joinpath(*parts)
    return _module_file(parts) is not None or (folder.is_dir() and folder.name != "__pycache__")


@functools.cache
def _defined_names(path: pathlib.Path) -> frozenset[str]:
    """Names a module defines, imports, assigns, or quotes as an identifier string."""
    names: set[str] = set()
    for node in ast.walk(_scan.tree(path)):
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
            return f"no module {module}"
        file, name = _module_file(parts[:depth]), parts[depth]
        if file is None:
            return f"{'.'.join(parts[: depth + 1])} is not a module"
        if name not in _defined_names(file):
            return f"{'.'.join(parts[:depth])} has no {name}"
        # The facade is the one module that re-exports names, so a chain written
        # through it stops there instead of being read as a module path.
        if depth == 1 and len(parts) > 2:
            return f"{'.'.join(parts[: depth + 1])} is a name of the facade, no module follows it"
        return None
    if attribute:
        file, name = _module_file(parts), attribute.split(".")[0]
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
    return [o for opt in match.group(1).split(",") for o in _expand_braces(head + opt + tail)]


def resolve_glob(pattern: str) -> str | None:
    for item in _expand_braces(pattern.removeprefix("!")):
        if glob.glob(item, root_dir=REPO_ROOT, recursive=True):
            return None
    return "no path matches"


def _strings(node: ast.AST):
    return (n for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str))


def _python_files(root: str):
    for path in sorted((REPO_ROOT / root).rglob("*.py")):
        relative = path.relative_to(REPO_ROOT)
        if "__pycache__" not in relative.parts and "frozen_runs" not in relative.parts:
            yield path, relative.as_posix()


def _scan_package_code() -> list[Found]:
    found: list[Found] = []
    for root in CODE_ROOTS:
        for path, relative in _python_files(root):
            if not QUOTED_START.search(path.read_text(encoding="utf-8")):
                continue
            tree = _scan.tree(path)
            for statement in tree.body:
                if isinstance(statement, ast.Assign | ast.AnnAssign) and statement.value:
                    found += [
                        Found("package code", relative, c.lineno, c.value)
                        for c in _strings(statement.value)
                        if CHAIN.match(c.value)
                    ]
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and node.args
                    and called_name(node) == "import_module"
                ):
                    first = node.args[0]
                    if isinstance(first, ast.Constant) and CHAIN.match(str(first.value)):
                        found.append(Found("package code", relative, first.lineno, first.value))
                elif isinstance(node, ast.Dict):
                    for key, value in zip(node.keys, node.values, strict=True):
                        if isinstance(key, ast.Constant) and key.value == "implementation":
                            for c in _strings(value):
                                head = c.value.split(":")[0].split(" ")[0]
                                if head.startswith("hydromodpy."):
                                    found.append(Found("package code", relative, c.lineno, head))
    return found


def _scan_test_patches() -> list[Found]:
    found: list[Found] = []
    for path, relative in _python_files("tests"):
        if not PATCH_TEXT.search(path.read_text(encoding="utf-8")):
            continue
        for node in ast.walk(_scan.tree(path)):
            if isinstance(node, ast.Call) and node.args and called_name(node) in PATCH_CALLS:
                first = node.args[0]
                if isinstance(first, ast.Constant) and CHAIN.match(str(first.value)):
                    found.append(Found("test patches", relative, first.lineno, first.value))
    return found


def _walk_toml(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from _walk_toml(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_toml(value)
    elif isinstance(node, str):
        yield node


def _scan_pyproject() -> list[Found]:
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    lines = text.splitlines()

    def line_of(needle: str) -> int:
        return next((i for i, row in enumerate(lines, 1) if needle in row), 0)

    found: list[Found] = []
    for item in _walk_toml(tomllib.loads(text)):
        chain = item.removesuffix(".*")
        if CHAIN.match(chain):
            found.append(Found("pyproject chains", "pyproject.toml", line_of(chain), chain))
        elif item.removeprefix("!").startswith("hydromodpy/"):
            found.append(Found("pyproject globs", "pyproject.toml", line_of(item), item))
    return found


def _scan_workflows() -> list[Found]:
    found: list[Found] = []
    for path in sorted((REPO_ROOT / ".github/workflows").glob("*.yml")):
        for number, row in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for token in (t.rstrip("\\") for t in re.split(r"[\s,\"'=]+", row)):
                if token.startswith("hydromodpy/"):
                    found.append(Found("workflow globs", rel(path), number, token))
                elif CHAIN.match(token):
                    found.append(Found("workflow chains", rel(path), number, token))
    return found


@functools.cache
def scan() -> tuple[Found, ...]:
    """Every string the gate reads, from every known place."""
    return tuple(
        _scan_package_code() + _scan_test_patches() + _scan_pyproject() + _scan_workflows()
    )


def _group_names(allowed: dict) -> set[str]:
    section = allowed["not_modules"]
    return set(section["groups"]) | set(section["groups_that_are_packages"])


def _is_allowed(text: str, allowed: dict) -> bool:
    section = allowed["not_modules"]
    if re.fullmatch(section["documents"], text) or text in _group_names(allowed):
        return True
    return any(
        text == e["text"] or (e.get("prefix") and text.startswith(e["text"]))
        for e in section["names"]
    )


def find_problems() -> list[str]:
    """Strings that do not resolve and that no list explains."""
    allowed = _load_allowed()
    stale = {(e["text"], e["file"]) for e in allowed["known_stale"]}
    problems = []
    for item in scan():
        if item.location.endswith("globs"):
            missing = resolve_glob(item.text)
        elif _is_allowed(item.text, allowed):
            continue
        else:
            missing = resolve_chain(item.text)
        if missing and (item.text, item.file) not in stale:
            problems.append(f"{item.file}:{item.line}  {item.text}  ({missing})")
    return problems


def test_every_dotted_path_resolves() -> None:
    problems = find_problems()
    assert not problems, "Dotted paths that point at nothing:\n  " + "\n  ".join(problems)


def test_the_dotted_path_scan_reads_every_location() -> None:
    seen = {item.location for item in scan()}
    assert set(LOCATIONS) <= seen, f"nothing read from {sorted(set(LOCATIONS) - seen)}"
    lazy = [item for item in scan() if item.file == "hydromodpy/_lazy.py"]
    assert len(lazy) >= MIN_LAZY_CHAINS, f"_lazy.py gave only {len(lazy)} chains"


def test_a_known_stale_entry_is_still_stale() -> None:
    present = {(item.text, item.file) for item in scan()}
    for entry in _load_allowed()["known_stale"]:
        key, text = (entry["text"], entry["file"]), entry["text"]
        assert entry.get("why") and entry.get("lifted_by"), f"{key} needs why and lifted_by"
        assert key in present, f"{key} is gone from its file: remove the entry"
        missing = resolve_glob(text) if text.startswith("hydromodpy/") else resolve_chain(text)
        assert missing, f"{key} resolves now: remove the entry"


def test_an_allowed_name_is_still_used() -> None:
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
            assert any(c.name.startswith(start) for c in folder.iterdir()), (
                f"{text} starts no module"
            )


def test_entry_points_use_declared_groups() -> None:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    groups = data.get("project", {}).get("entry-points", {})
    unknown = sorted(set(groups) - _group_names(_load_allowed()))
    assert not unknown, f"entry-point groups missing from dotted_paths.yaml: {unknown}"


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
def test_the_resolver_tells_a_real_path_from_a_dead_one(chain: str, expected: str | None) -> None:
    assert resolve_chain(chain) == expected
