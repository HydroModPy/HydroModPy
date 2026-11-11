"""The science map joins a theory page to its modules, their tests and the validation cases.

The functions are pure, so each row of a table is a page and a ``tests.json``
written in the test. A last table reads pages written under ``tmp_path`` in
both Markdown and reStructuredText.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.docs import science_map as S

TESTS = {
    "imports": {
        "tests/unit/a/test_kernel.py": {"tier": "unit", "modules": ["hydromodpy.core.alpha.step"]},
        "tests/unit/a/test_other.py": {"tier": "unit", "modules": ["hydromodpy.core.alphabet"]},
        "tests/unit/b/test_beta.py": {"tier": "unit", "modules": ["hydromodpy.core.beta"]},
        "tests/scenarios/test_island.py": {
            "tier": "scenarios",
            "modules": ["hydromodpy.core.alpha"],
        },
        "tests/validation/test_theis.py": {
            "tier": "validation",
            "modules": ["hydromodpy.core.beta.solve"],
        },
        "tests/refusals/test_refuse.py": {"tier": "refusals", "modules": ["hydromodpy.core.alpha"]},
    },
    "validation": [
        {"file": "tests/validation/test_theis.py", "cases": [{"id": "theis_confined"}]},
    ],
}


def test_a_page_with_two_prefixes_gets_a_test_of_each_tier() -> None:
    pages = {"theory/x": ("The x", ["hydromodpy.core.alpha", "hydromodpy.core.beta"])}
    (row,) = S.science_map(pages, TESTS)
    assert row == {
        "page": "theory/x",
        "concept": "The x",
        "modules": ["hydromodpy.core.alpha", "hydromodpy.core.beta"],
        "kernel_tests": [
            "tests/unit/a/test_kernel.py",
            "tests/unit/b/test_beta.py",
        ],
        "scenarios": ["tests/scenarios/test_island.py"],
        "validation": [{"file": "tests/validation/test_theis.py", "cases": ["theis_confined"]}],
    }


def test_a_prefix_matches_a_module_and_its_children_and_never_a_longer_name() -> None:
    pages = {"theory/x": ("The x", ["hydromodpy.core.alpha"])}
    (row,) = S.science_map(pages, TESTS)
    assert "tests/unit/a/test_other.py" not in row["kernel_tests"]
    assert "tests/unit/a/test_kernel.py" in row["kernel_tests"]


def test_a_prefix_without_a_test_renders_an_empty_row() -> None:
    pages = {"theory/y": ("The y", ["hydromodpy.core.gamma"])}
    (row,) = S.science_map(pages, TESTS)
    assert row["kernel_tests"] == row["scenarios"] == row["validation"] == []


def test_a_page_without_a_block_has_no_row_and_a_case_less_file_lists_no_case() -> None:
    pages = {"theory/z": ("The z", []), "theory/x": ("The x", ["hydromodpy.core.beta"])}
    tests = {"imports": TESTS["imports"], "validation": []}
    rows = S.science_map(pages, tests)
    assert [r["page"] for r in rows] == ["theory/x"]
    assert rows[0]["validation"] == [{"file": "tests/validation/test_theis.py", "cases": []}]


PAGES = {
    "theory/index": ("Theory", []),
    "theory/exits": ("Exits", []),
    "theory/notation": ("Notation", []),
    "theory/bibliography": ("Bibliography", []),
    "theory/validation": ("Validation", []),
    "theory/science-map": ("Science map", []),
    "theory/mesh": ("The mesh", ["hydromodpy.mesh"]),
    "theory/calibration/inverse": ("Inverse problem", []),
}


def test_a_page_without_a_block_is_reported_unless_it_is_an_index_or_exempt() -> None:
    warnings = S.missing_blocks(PAGES, {"theory/index", "theory/exits"})
    assert warnings == [
        "theory page theory/calibration/inverse names no module: add a hmp-tested-by block"
    ]


@pytest.mark.parametrize(
    ("known", "expected"),
    [
        pytest.param(
            {"hydromodpy.mesh"},
            [],
            id="every prefix is a module",
        ),
        pytest.param(
            set(),
            ["hydromodpy.mesh in hmp-tested-by of theory/mesh is not a module of hydromodpy"],
            id="a renamed module",
        ),
    ],
)
def test_a_prefix_that_is_not_a_module_is_reported(known: set[str], expected: list[str]) -> None:
    assert S.unknown_prefixes(PAGES, lambda prefix: prefix in known) == expected


def test_the_real_prefixes_resolve_with_python() -> None:
    assert S.is_module("hydromodpy.core.scoring")
    assert not S.is_module("hydromodpy.core.no_such_module")
    assert not S.is_module("no_such_package.child")


MARKDOWN = """\
# The mesh

Text.

```{hmp-tested-by}
hydromodpy.mesh.registry
hydromodpy.mesh.size
```

```{toctree}
other
```
"""

RST = """\
Boussinesq theory
=================

Text.

.. hmp-tested-by::

   hydromodpy.solver.boussinesq.assembly
   hydromodpy.solver.boussinesq.catalog

After the block.
"""


def test_the_pages_are_read_in_markdown_and_in_restructuredtext(tmp_path: Path) -> None:
    theory = tmp_path / "theory"
    (theory / "sub").mkdir(parents=True)
    (theory / "mesh.md").write_text(MARKDOWN, encoding="utf-8")
    (theory / "sub" / "boussinesq.rst").write_text(RST, encoding="utf-8")
    (theory / "empty.md").write_text("# Empty\n\nNothing.\n", encoding="utf-8")
    pages, indexes = S.read_pages(tmp_path)
    assert pages == {
        "theory/empty": ("Empty", []),
        "theory/mesh": ("The mesh", ["hydromodpy.mesh.registry", "hydromodpy.mesh.size"]),
        "theory/sub/boussinesq": (
            "Boussinesq theory",
            ["hydromodpy.solver.boussinesq.assembly", "hydromodpy.solver.boussinesq.catalog"],
        ),
    }
    assert indexes == {"theory/mesh"}


def test_the_real_theory_pages_name_modules_that_exist() -> None:
    root = Path(__file__).resolve().parents[3]
    pages, indexes = S.read_pages(root / "docs" / "source")
    assert S.unknown_prefixes(pages) == []
    assert any(prefixes for _title, prefixes in pages.values())
    assert S.missing_blocks(pages, indexes) == []
