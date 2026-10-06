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
