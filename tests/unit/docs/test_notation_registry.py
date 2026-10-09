"""One symbol, one meaning, across the theory pages.

The notation tables of the theory pages are rendered from one registry,
``docs/source/theory/symbols.yaml``. The build refuses a symbol that carries two
meanings, unless the pair is declared and the two meanings never meet on one
page. These tests pin that rule, and check the registry of the tree against it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[3] / "docs" / "source"
sys.path.insert(0, str(DOCS / "_ext"))

import hmp_notation  # noqa: E402


def _registry(symbols: list[dict], collisions: list[list[str]] | None = None):
    return hmp_notation.parse_registry(
        {"groups": {"g": "G"}, "symbols": symbols, "collisions": collisions or []}
    )


def _entry(sid: str, symbol: str, pages: list[str]) -> dict:
    return {
        "id": sid,
        "symbol": symbol,
        "meaning": sid,
        "unit": "-",
        "group": "g",
        "pages": pages,
    }


def test_the_registry_of_the_tree_has_no_collision() -> None:
    reg = hmp_notation.load_registry(DOCS / hmp_notation.REGISTRY_PATH)
    assert reg.symbols
    assert hmp_notation.find_collisions(reg) == []


def test_every_page_of_the_registry_exists() -> None:
    reg = hmp_notation.load_registry(DOCS / hmp_notation.REGISTRY_PATH)
    missing = {
        page
        for s in reg.symbols
        for page in s.pages
        if not any((DOCS / f"{page}{ext}").exists() for ext in (".md", ".rst"))
    }
    assert missing == set()


def test_one_symbol_with_two_meanings_is_a_collision() -> None:
    reg = _registry([_entry("porosity", r"\theta", ["a"]), _entry("angle", r"\theta", ["b"])])
    problems = hmp_notation.find_collisions(reg)
    assert len(problems) == 1
    assert "porosity" in problems[0] and "angle" in problems[0]


def test_spaces_do_not_hide_a_collision() -> None:
    reg = _registry([_entry("a", r"\Delta t", ["p"]), _entry("b", r"\Delta  t", ["q"])])
    assert len(hmp_notation.find_collisions(reg)) == 1


def test_a_declared_pair_on_separate_pages_is_allowed() -> None:
    reg = _registry(
        [_entry("lag", "L", ["soil"]), _entry("length", "L", ["dupuit"])],
        collisions=[["lag", "length"]],
    )
    assert hmp_notation.find_collisions(reg) == []


def test_a_declared_pair_that_meets_on_one_page_is_refused() -> None:
    reg = _registry(
        [_entry("lag", "L", ["soil", "notation"]), _entry("length", "L", ["notation"])],
        collisions=[["lag", "length"]],
    )
    problems = hmp_notation.find_collisions(reg)
    assert len(problems) == 1
    assert "theory/notation" in problems[0]


def test_a_declared_pair_with_an_unknown_id_is_refused() -> None:
    reg = _registry([_entry("lag", "L", ["soil"])], collisions=[["lag", "gone"]])
    assert any("gone" in p for p in hmp_notation.find_collisions(reg))


def test_different_symbols_never_collide() -> None:
    reg = _registry([_entry("a", r"\varepsilon_s", ["p"]), _entry("b", r"\varepsilon_h", ["p"])])
    assert hmp_notation.find_collisions(reg) == []


def test_a_duplicated_id_is_refused() -> None:
    with pytest.raises(ValueError, match="twice"):
        _registry([_entry("a", "x", ["p"]), _entry("a", "y", ["p"])])


def test_a_page_selects_its_own_entries_in_registry_order() -> None:
    reg = _registry(
        [_entry("a", "x", ["p"]), _entry("b", "y", ["q"]), _entry("c", "z", ["p", "q"])]
    )
    assert [s.id for s in hmp_notation.select(reg, page="theory/p")] == ["a", "c"]


def test_the_solver_matrix_keeps_the_cases_that_run_every_required_solver(tmp_path) -> None:
    case = tmp_path / "case_a"
    case.mkdir()
    (case / "tolerances_modflownwt.toml").write_text("")
    tests = [
        {
            "file": "t_a.py",
            "solvers": ["modflow_nwt", "modflow6"],
            "cases": [{"id": "a", "path": "case_a"}],
        },
        {"file": "t_b.py", "solvers": ["modflow6"], "cases": [{"id": "b", "path": "case_b"}]},
    ]
    solvers = ("modflow_nwt", "modflow6", "boussinesq")
    rows = hmp_notation.solver_matrix_rows(
        tests, tmp_path, solvers=solvers, require=("modflow_nwt", "modflow6")
    )
    assert rows == [("a", ["yes, own threshold", "yes", ""])]
