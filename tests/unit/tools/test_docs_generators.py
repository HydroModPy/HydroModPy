"""The generators of the documentation read the code, and the page check catches drift.

The reference pages are written at build time from what these generators return,
so a generator that silently returns less makes the site lose pages without a
warning. These tests pin what each one must find in the tree.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.docs import catalogs, check_page, field_registry, tests_index, toml_changelog

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def registry() -> dict:
    payload, _gates = field_registry.build_payload("test")
    return payload


def test_the_registry_holds_every_section_and_the_free_key_of_flow_param(registry: dict) -> None:
    nodes = registry["nodes"]
    assert {"flow", "geographic", "data", "calibration", "simulation"} <= set(
        registry["meta"]["roots"]
    )
    assert "flow.param.<id>" in nodes
    assert nodes["flow.param.<id>"].get("known_keys"), (
        "the named instances of flow.param come from the code"
    )
    assert registry["meta"]["leaves"] > 1000


def test_a_leaf_carries_what_its_card_shows(registry: dict) -> None:
    leaf = registry["nodes"]["simulation.time.start_datetime"]
    assert leaf["kind"] == "leaf"
    assert leaf["profile"] in {"user", "dev", "expert"}
    assert leaf["summary"]


def test_the_changelog_lists_a_table_once_and_a_changed_default() -> None:
    old = {
        "meta": {"label": "a"},
        "nodes": {
            "": {},
            "x": {"kind": "leaf", "default": "1"},
            "gone": {"kind": "table"},
            "gone.k": {"kind": "leaf"},
        },
    }
    new = {
        "meta": {"label": "b"},
        "nodes": {
            "": {},
            "x": {"kind": "leaf", "default": "2"},
            "new": {"kind": "table"},
            "new.k": {"kind": "leaf"},
        },
    }
    diff = toml_changelog.diff(old, new)
    assert diff["added"] == ["new"]
    assert diff["removed"] == ["gone"]
    assert diff["changed"] == [{"path": "x", "changes": {"default": ["1", "2"]}}]


def test_an_empty_value_and_a_missing_one_are_the_same_change() -> None:
    old = {"meta": {}, "nodes": {"x": {"kind": "leaf"}}}
    new = {
        "meta": {},
        "nodes": {"x": {"kind": "leaf", "unit": None, "required": False, "default": ""}},
    }
    assert toml_changelog.diff(old, new)["changed"] == []


def test_the_test_index_finds_the_validation_tier_and_its_cases() -> None:
    index = tests_index.build(ROOT)
    files = {entry["file"] for entry in index["validation"]}
    assert "tests/validation/analytical/steady/test_dupuit_fixed_head_1d.py" in files
    dupuit = next(
        e for e in index["validation"] if e["file"].endswith("test_dupuit_fixed_head_1d.py")
    )
    assert dupuit["cases"] and dupuit["cases"][0]["id"] == "dupuit_fixed_head_1d"
    assert dupuit["launcher"] is True


def test_the_catalogs_read_the_solver_figure_and_source_registries(registry: dict) -> None:
    result = catalogs.build(registry["nodes"])
    pairs = {(row["process"], row["solver"]) for row in result["solvers"]}
    assert ("flow", "modflow6") in pairs
    assert len(result["figures"]) > 20
    dem = next(row for row in result["data_sources"] if row["variable"] == "dem")
    assert {"custom", "ign_geoplateforme_dem"} <= {s["value"] for s in dem["sources"]}


@pytest.fixture()
def page_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, registry: dict):
    """A docs tree with one existing page and the registry the check reads."""
    src = tmp_path / "docs" / "source"
    (src / "_data").mkdir(parents=True)
    (src / "_data" / "registry.json").write_text(json.dumps(registry))
    (src / "guides").mkdir()
    (src / "guides" / "other.md").write_text("# Other\n")
    monkeypatch.setattr(check_page, "SRC", src)
    return src


def test_the_page_check_accepts_a_clean_page(page_env: Path) -> None:
    page = page_env / "guides" / "good.md"
    page.write_text(
        "# Good\n\nSet {toml}`the start|simulation.time.start_datetime` and read {doc}`other`.\n\n"
        "```{hmp-params}\nsimulation.time.start_datetime\n```\n"
    )
    assert check_page.check(page, check_page.Registry(), check_page.docnames()) == []


def test_the_page_check_catches_an_unknown_key_a_dead_link_and_a_bad_block(page_env: Path) -> None:
    page = page_env / "guides" / "bad.md"
    page.write_text(
        "# Bad\n\nSet {toml}`simulation.time.no_such_key` and read {doc}`missing`.\n\n"
        "```toml\n[simulation\n```\n"
    )
    problems = check_page.check(page, check_page.Registry(), check_page.docnames())
    joined = "\n".join(problems)
    assert "unknown TOML path: simulation.time.no_such_key" in joined
    assert "link to a page that does not exist: missing" in joined
    assert "TOML syntax" in joined


def test_a_block_marked_not_checked_is_skipped(page_env: Path) -> None:
    page = page_env / "guides" / "skip.md"
    page.write_text(
        "# Skip\n\n```toml\n# not checked: a mistake on purpose\n[workflow]\nmode = 3\n```\n"
    )
    assert check_page.check(page, check_page.Registry(), check_page.docnames()) == []


def test_k_ss_sy_and_porosity_are_named_nodes_with_unit_and_range(registry: dict) -> None:
    nodes = registry["nodes"]
    for key, unit in (("K", "m/s"), ("Ss", "1/m"), ("Sy", "-"), ("porosity", "-")):
        value = nodes[f"flow.param.{key}.field.value"]
        assert value["pseudo"] and value["unit"] == unit
        assert value["range"]["ge"] < value["range"]["le"]
        assert value["label"]
        assert nodes[f"flow.param.{key}"]["kind"] == "table"
    assert "conductivity" in nodes["flow.param.K.field.value"]["label"]
    # The tree of the file keeps the free name: a pseudo-node is no child.
    assert nodes["flow.param"]["children"] == ["flow.param.<id>"]
    # n is the same bound as porosity: an alias, not a second node.
    assert "flow.param.n" not in nodes
    assert nodes["flow.param.<id>"]["known_keys"]["porosity"]["aliases"] == ["n"]


def test_pseudo_nodes_are_not_fields_for_the_gates_or_the_changelog(registry: dict) -> None:
    payload, gates = field_registry.build_payload("test")
    flat = [p for keys in gates["keys"].values() for paths in keys.values() for p in paths]
    assert not any(p.startswith("flow.param.K.") for p in flat)
    snap = toml_changelog.snapshot(payload)
    assert "flow.param.K.field.value" not in snap["nodes"]
    assert toml_changelog.diff(snap, payload)["added"] == []


def test_a_discriminator_value_is_explained_by_the_docstring_of_its_shape(registry: dict) -> None:
    kinds = [
        n
        for p, n in registry["nodes"].items()
        if p.startswith("flow.sinks_sources.wells.")
        and p.endswith(".kind")
        and n.get("is_tag")
        and "constant" in n["literal"]
    ]
    assert kinds
    docs = kinds[0]["value_docs"]
    assert set(kinds[0]["literal"]) <= set(docs)
    assert docs["constant"].startswith("One constant")


def test_a_value_quoted_in_the_description_counts_as_explained() -> None:
    node = {
        "literal": ["replace", "scale", "other"],
        "value_docs": {},
        "description": "'replace' writes the value; ``scale`` multiplies it.",
    }
    assert field_registry.unexplained_values(node) == ["other"]


def test_connections_read_only_raised_errors_and_warnings(tmp_path: Path) -> None:
    import ast

    source = '''
def rule(cfg):
    """Docstring naming [simulation.time] and [data.recharge]: not a rule."""
    if cfg:
        raise ValueError(f"[simulation.time] needs {cfg} or [data.recharge].")
    log.warning("set [flow.param] first")


def fold_legacy(cfg):
    raise ValueError("[simulation.time] and [calibration.protocol]")
'''
    tree = ast.parse(source)
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    texts = [t for _, t in field_registry._messages(funcs[0])]
    assert texts == ["[simulation.time] needs ... or [data.recharge].", "set [flow.param] first"]
    pkg = tmp_path / "hydromodpy"
    pkg.mkdir()
    (pkg / "mod.py").write_text(source)
    field_registry.build()
    found = field_registry.scan_mentions(pkg, {"simulation", "data", "flow", "calibration"})
    assert [m["other"] for m in found["simulation.time"]] == ["data.recharge"]
    assert found["simulation.time"][0]["text"].startswith("[simulation.time] needs")
    assert "calibration.protocol" not in str(found)


def test_a_declared_rename_is_listed_as_renamed_not_removed() -> None:
    old = {
        "meta": {"label": "a"},
        "nodes": {
            "": {},
            "cal": {"kind": "table"},
            "cal.optimizer_kwargs": {"kind": "leaf"},
            "export": {"kind": "table"},
            "export.geotiff": {"kind": "table"},
            "export.geotiff.enabled": {"kind": "leaf"},
            "gone": {"kind": "leaf"},
        },
    }
    new = {
        "meta": {"label": "b"},
        "nodes": {
            "": {},
            "cal": {"kind": "table"},
            "cal.method_options": {"kind": "leaf", "renamed_from": ["cal.optimizer_kwargs"]},
            "export": {"kind": "array", "renamed_from": ["export.geotiff"]},
            "flow.param.K": {"kind": "table", "pseudo": True},
        },
    }
    out = toml_changelog.diff(old, new)
    assert out["renamed"] == [
        {"from": "cal.optimizer_kwargs", "to": "cal.method_options"},
        {"from": "export.geotiff", "to": "export"},
    ]
    assert out["removed"] == ["gone"]
    assert out["added"] == ["cal.method_options"]


def test_the_history_compares_every_older_version_with_every_newer_one() -> None:
    docs = [{"meta": {"label": v}, "nodes": {"": {}}} for v in ("a", "b", "c")]
    out = toml_changelog.history(docs)
    assert out["versions"] == ["a", "b", "c"]
    assert [(p["from"], p["to"]) for p in out["pairs"]] == [("a", "b"), ("a", "c"), ("b", "c")]


def test_every_snapshot_names_its_version_and_holds_the_root_sections() -> None:
    snaps = sorted((ROOT / "tools" / "docs" / "snapshots").glob("fields-*.json"))
    assert len(snaps) >= 4
    for snap in snaps:
        data = json.loads(snap.read_text())
        assert snap.stem == f"fields-{data['meta']['label']}"
        assert {"workflow", "workspace", "geographic", "flow"} <= set(data["nodes"])


def test_the_report_file_has_its_own_tables_outside_the_project_file(registry: dict) -> None:
    nodes = registry["nodes"]
    info = registry["meta"]["files"]["report-file"]
    assert set(info["roots"]) == {"report", "layout", "context", "pipeline"}
    assert info["page"] == "reference/parameters/report-file"
    assert not set(info["roots"]) & set(registry["meta"]["roots"])
    assert not set(info["roots"]) & set(nodes[""]["children"])
    assert nodes["report.site_label"]["file"] == "report-file"
    assert nodes["context.observed_discharge.path"]["file"] == "report-file"
    assert nodes["pipeline.strict_figure_postflight"]["default"] == "false"
    assert nodes["layout.simulation_name"]["description"]
    assert "file" not in nodes["flow.param.<id>"]


def test_a_key_of_the_report_file_is_not_a_change_of_the_project_file(registry: dict) -> None:
    snap = toml_changelog.snapshot(registry)
    assert "report.site_label" not in snap["nodes"]
    assert "pipeline" not in snap["nodes"]
    old = {"meta": {"label": "a"}, "nodes": {"": {}}}
    assert "report.site_label" not in toml_changelog.diff(old, registry)["added"]


def test_every_key_of_the_report_file_is_described(registry: dict) -> None:
    leaves = [
        n
        for n in registry["nodes"].values()
        if n.get("file") == "report-file" and n.get("kind") == "leaf"
    ]
    assert len(leaves) >= 20
    assert all(len(n["description"].split()) >= 4 for n in leaves)


def test_the_page_check_validates_a_whole_report_file_block(page_env: Path) -> None:
    good = (
        "[report]\nsite_label = 'A'\nstation_label = 'B'\noutput_dir = 'out'\n"
        "[layout]\nwatershed_project_dir = '.'\ncontext_outputs_dir = 'ctx'\n"
    )
    bad = good.replace("[layout]", "[layout]\nsimulation_nam = 'x'")
    page = page_env / "guides" / "report.md"
    page.write_text(f"# Report\n\n```toml\n{good}```\n")
    assert check_page.check(page, check_page.Registry(), check_page.docnames()) == []
    page.write_text(f"# Report\n\n```toml\n{bad}```\n")
    problems = check_page.check(page, check_page.Registry(), check_page.docnames())
    assert any("refused by ReportConfig" in p and "simulation_nam" in p for p in problems)
    page.write_text(f"# Report\n\n```toml\n# not checked: a fragment\n{bad}```\n")
    assert check_page.check(page, check_page.Registry(), check_page.docnames()) == []


def test_the_page_check_reads_a_testbed_file_by_its_own_schema(page_env: Path) -> None:
    good = (
        '[workflow]\nmode = "testbed"\n\n'
        '[testbed]\nid = "t"\nsubject = "flow"\nbase_config = "step1_minimal.toml"\n'
        'output_root = "out"\nexecute = false\n\n'
        '[testbed.runner]\ntype = "simulation"\n\n'
        '[[testbed.case]]\nid = "a"\n'
    )
    page = page_env / "guides" / "tb.md"
    page.write_text(f"# Tb\n\n```toml\n{good}```\n")
    assert check_page.check(page, check_page.Registry(), check_page.docnames()) == []

    bad = good.replace("execute = false", "exceute = false")
    page.write_text(f"# Tb\n\n```toml\n{bad}```\n")
    problems = check_page.check(page, check_page.Registry(), check_page.docnames())
    assert any("refused by hmp config check" in p and "exceute" in p for p in problems)


def test_the_page_check_reads_a_comparison_file_by_its_own_schema(page_env: Path) -> None:
    good = (
        '[workflow]\nmode = "comparison"\n\n'
        '[comparison]\ncomparison_id = "c"\nbase_simulation_config = "step1_minimal.toml"\n'
        'reference_simulation = "a"\n\n'
        '[[comparison.simulation]]\nid = "a"\nsolver = "modflow6"\n\n'
        '[[comparison.observable]]\nname = "h"\nvariable = "watertable_elevation"\n'
        'support = "map"\ntime = "last"\n'
    )
    page = page_env / "guides" / "cmp.md"
    page.write_text(f"# Cmp\n\n```toml\n{good}```\n")
    assert check_page.check(page, check_page.Registry(), check_page.docnames()) == []

    bad = good.replace('support = "map"', 'support = "blob"')
    page.write_text(f"# Cmp\n\n```toml\n{bad}```\n")
    problems = check_page.check(page, check_page.Registry(), check_page.docnames())
    assert any("refused by hmp config check" in p for p in problems)
