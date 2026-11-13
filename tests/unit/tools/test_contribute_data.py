"""The generators of the contributor pages read their sources whole.

Each page under ``contribute/architecture/generated/`` is built from what these
functions return. A function that silently returns less makes a page lose rows
without a warning, so these tests compare each result with its source.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

from tools.docs import contribute_data as C

ROOT = Path(__file__).resolve().parents[3]


# -- layer graph ---------------------------------------------------------------


def _reachable(start: str, edges: list[tuple[str, str]]) -> set[str]:
    seen, stack = set(), [start]
    while stack:
        node = stack.pop()
        for u, v in edges:
            if u == node and v not in seen:
                seen.add(v)
                stack.append(v)
    return seen


def test_the_reduction_drops_a_shortcut_and_keeps_a_cycle_apart() -> None:
    matrix = {
        "allowed": {
            "top": ["top", "mid", "low"],
            "mid": ["mid", "low"],
            "low": ["low", "mid"],
        },
        "tolerances": [{"src": "low", "tgt": "top", "reason": "test"}],
    }
    graph = C.layer_graph(matrix)
    assert graph["granted"] == 4
    assert ("top", "low") not in graph["reduced"]
    assert len(graph["upward"]) == 1
    assert set(graph["upward"]) <= {("mid", "low"), ("low", "mid")}
    assert graph["tolerated"] == [("low", "top", "test")]


def test_the_layer_graph_keeps_every_grant_reachable() -> None:
    matrix = C.load_layer_matrix()
    graph = C.layer_graph(matrix)
    assert set(graph["layers"]) == set(matrix["allowed"])
    granted = {(u, v) for u, vs in matrix["allowed"].items() for v in vs if u != v}
    assert set(graph["reduced"]) <= granted
    assert set(graph["upward"]) <= granted
    rank = {name: i for i, name in enumerate(graph["layers"])}
    for u, v in granted:
        if rank[u] < rank[v]:
            assert v in _reachable(u, graph["reduced"]), f"{u} -> {v} lost by the reduction"
    dot = C.layer_dot(graph)
    for name in matrix["allowed"]:
        assert f'label="{C.layer_label(name)}"' in dot


# -- gates, CI, tests ----------------------------------------------------------


def test_every_architecture_gate_has_a_rule_and_a_check() -> None:
    gates = C.architecture_gates()
    files = sorted((ROOT / "tests/unit/architecture").glob("test_*.py"))
    assert [g["file"] for g in gates] == [p.relative_to(ROOT).as_posix() for p in files]
    for gate in gates:
        assert gate["rule"], f"{gate['file']} has no module docstring"
        assert gate["tests"], f"{gate['file']} has no test function"
    layouts = C.layout_contracts()
    assert {row["package"] for row in layouts} >= {"calibration", "data", "display"}
    assert all(row["parts"] for row in layouts)


def test_every_workflow_file_is_read_with_its_jobs() -> None:
    workflows = C.ci_workflows()
    files = sorted((ROOT / ".github/workflows").glob("*.yml"))
    assert len(workflows) == len(files)
    for wf in workflows:
        assert wf["triggers"], f"{wf['file']} has no trigger"
        assert wf["jobs"], f"{wf['file']} has no job"
        for job in wf["jobs"]:
            assert job["steps"] or job["uses"], f"{wf['file']}:{job['id']} runs nothing"


def test_the_inventory_counts_every_test_file_once() -> None:
    inv = C.suite_inventory()
    tiers = {t["tier"]: t for t in inv["tiers"]}
    assert {"unit", "integration", "regression", "validation"} <= set(tiers)
    on_disk = [
        p
        for p in (ROOT / "tests").rglob("test_*.py")
        if len(p.relative_to(ROOT / "tests").parts) >= 2 and "__pycache__" not in p.parts
    ]
    assert sum(t["files"] for t in inv["tiers"]) == len(on_disk)
    for name, tier in tiers.items():
        folders = inv["folders"][name]
        assert sum(f["files"] for f in folders) == tier["files"]
        assert sum(f["functions"] for f in folders) == tier["functions"]
    assert {m["name"] for m in inv["markers"]} == set(C.pytest_markers())
    assert [t["tier"] for t in inv["tiers"]][0] == "unit"
    assert set(tiers) <= set(C.TIER_ORDER)


# -- module tables and ports ---------------------------------------------------


def write_package(tmp_path: Path, files: dict[str, str | None]) -> None:
    for name, doc in files.items():
        path = tmp_path / "hydromodpy" / "pkg" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        body = "x = 1\n"
        path.write_text(f'"""{doc}"""\n{body}' if doc is not None else body, encoding="utf-8")


def test_the_module_table_is_sorted_and_reads_the_first_docstring_line(tmp_path: Path) -> None:
    write_package(
        tmp_path,
        {
            "__init__.py": "The package.",
            "zeta.py": "Last module.\n\nMore words that the row leaves out.",
            "alpha.py": "First module.",
            "port/impl.py": "A member of the port.",
        },
    )
    (tmp_path / "hydromodpy" / "pkg" / "port" / "README.md").write_text("# port\n\nText.\n")
    rows = C.module_table("pkg", tmp_path)
    assert rows == [
        {"path": "alpha.py", "summary": "First module.", "lines": 2, "readme": None},
        {
            "path": "port/impl.py",
            "summary": "A member of the port.",
            "lines": 2,
            "readme": "hydromodpy/pkg/port/README.md",
        },
        {"path": "zeta.py", "summary": "Last module.", "lines": 4, "readme": None},
    ]


@pytest.mark.parametrize("doc", [None, "", "   "])
def test_a_module_without_a_docstring_fails_the_table(tmp_path: Path, doc: str | None) -> None:
    write_package(tmp_path, {"bare.py": doc})
    with pytest.raises(ValueError, match="has no docstring; its first line is the row"):
        C.module_table("pkg", tmp_path)


def test_every_module_of_hydromodpy_has_a_first_docstring_line() -> None:
    packages = [p.name for p in (ROOT / "hydromodpy").iterdir() if (p / "__init__.py").exists()]
    assert packages
    for package in packages:
        for row in C.module_table(package):
            assert row["summary"], f"{package}/{row['path']}"


def test_the_port_table_holds_the_eight_registries_of_the_code() -> None:
    rows = C.port_table(ROOT, imports={})
    assert len(rows) == 8
    assert len({r["registry"] for r in rows}) == 8
    for row in rows:
        assert row["kind"], row["registry"]
        assert row["names"], row["registry"]
        assert row["members"], row["registry"]
    solvers = next(r for r in rows if r["registry"].endswith(".registry.solvers"))
    assert {"flow_modflow6", "flow_boussinesq"} <= set(solvers["names"])
    assert solvers["group"] == "hydromodpy.solver"
    evaluators = next(r for r in rows if r["registry"].endswith(".evaluators"))
    assert evaluators["names"]


def test_the_port_table_finds_the_readme_of_the_port_and_the_tests_that_import_it() -> None:
    imports = {
        "tests/ports/test_x.py": {"modules": ["hydromodpy.mesh.registry"]},
        "tests/unit/test_y.py": {"modules": ["hydromodpy.mesh.registry_other"]},
        "tests/unit/test_z.py": {"modules": ["hydromodpy.core.time"]},
    }
    rows = {r["registry"]: r for r in C.port_table(ROOT, imports=imports)}
    mesh = rows["hydromodpy.mesh.registry.mesh_engines"]
    assert mesh["tests"] == ["tests/ports/test_x.py"]
    assert mesh["readme"]["path"] == "hydromodpy/mesh/README.md"
    assert mesh["readme"]["summary"]
    # A registry in a folder of its own finds the README of that folder first.
    solvers = rows["hydromodpy.solver.base.registry.solvers"]
    assert solvers["readme"]["path"] == "hydromodpy/solver/base/README.md"


# -- packages, storage, environment, extras ------------------------------------


def test_every_package_with_a_map_gets_its_summary() -> None:
    rows = {r["package"]: r for r in C.package_map()}
    assert {"core", "solver", "workflow"} <= set(rows)
    for name, row in rows.items():
        if row["readme"]:
            assert row["summary"], f"hydromodpy/{name}/README.md has no first paragraph"


def test_the_registry_counts_come_from_the_code() -> None:
    rows = {r["what"]: r["names"] for r in C.registry_counts()}
    assert len(rows["Layers of the import matrix"]) == len(C.load_layer_matrix()["allowed"])
    for what, names in rows.items():
        assert names, f"{what}: the registry returned nothing"


def test_every_run_entry_of_the_contract_is_in_the_tree() -> None:
    from hydromodpy.results.storage.contract import ALLOWED_RUN_ENTRIES

    tree = C.storage_tree()
    under_run = [r["path"].rstrip("/") for r in tree["project"] if r["depth"] == 3]
    for entry in ALLOWED_RUN_ENTRIES:
        assert under_run.count(entry) == 1, entry
    for row in tree["project"] + tree["workspace"] + tree["machine"]:
        assert row["doc"], f"{row['path']} has no meaning"
    assert tree["layers"]


def test_the_env_scan_skips_names_in_all() -> None:
    refs = C.env_var_references()
    assert "hydromodpy/core/state/portable.py" in refs["HMP_CACHE_HOME"]
    # Built, not written: a whole literal here would count as a reference.
    exported_only = "HMP_" + "FORMAT_VERSION"
    assert exported_only not in refs, "a name exported in __all__ is not a variable"
    rows = C.environment_rows()
    assert all(r["read_in"] for r in rows)


def test_every_extra_of_pyproject_has_a_row() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = data["project"]["optional-dependencies"]
    rows = C.extras()
    assert [r["extra"] for r in rows] == list(declared)
    assert not [r["extra"] for r in rows if r["already_required"]], (
        "an extra repeats a base dependency"
    )


# -- extension -----------------------------------------------------------------


@pytest.fixture(scope="module")
def ext():
    sys.path.insert(0, str(ROOT / "docs" / "source" / "_ext"))
    try:
        import hmp_contribute
    finally:
        sys.path.pop(0)
    return hmp_contribute


def test_inline_markup_becomes_nodes_and_leaves_no_marker(ext) -> None:
    from docutils import nodes

    parts = ext.inline("Use ``HMP_BIN`` or :data:`~a.B` and `x` with **care**.")
    literals = [p.astext() for p in parts if isinstance(p, nodes.literal)]
    assert literals == ["HMP_BIN", "a.B", "x"]
    text = "".join(p.astext() for p in parts)
    assert "`" not in text and "**" not in text
