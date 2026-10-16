"""Smoke tests for the public ``hydromodpy`` API surface.

These checks pin down the top-level symbols that the P10 spec promises to
users - ``hmp.open``, ``hmp.Project``, ``hmp.Run``, ``hmp.Catalog``,
etc. Regressions here usually mean a refactor broke the import contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import hydromodpy as hmp
from hydromodpy.results.catalog.indexer import rebuild_index
from tests._helpers.sealed_runs import make_project

EXPECTED_TOP_LEVEL = [
    # Entry points
    "open",
    "run",
    "calibrate",
    "compare_pair",
    "doctor",
    # Project / run / catalog API
    "Project",
    "Run",
    "SimulationPlan",
    "Catalog",
    "RunSet",
    # Core
    "Workspace",
    "CatchmentDelineation",
    # Solvers
    "ModflowNwt",
    "Boussinesq",
    "Modflow6",
]


@pytest.mark.parametrize("symbol", EXPECTED_TOP_LEVEL)
def test_public_symbol_available(symbol: str) -> None:
    assert hasattr(hmp, symbol), f"hmp.{symbol} missing from public API"


def test_old_simulation_catalog_name_is_not_exposed() -> None:
    # Clean break: the V1 facade is ``Catalog`` / ``RunSet``; the old
    # ``SimulationCatalog`` / ``SimulationGroup`` names are gone (no alias).
    with pytest.raises(AttributeError):
        hmp.SimulationCatalog  # noqa: B018
    with pytest.raises(AttributeError):
        hmp.SimulationGroup  # noqa: B018


def test_removed_batch_api_is_not_exposed() -> None:
    with pytest.raises(AttributeError):
        hmp.batch  # noqa: B018


def _empty_index(tmp_path: Path) -> Path:
    project = make_project(tmp_path / "p")
    rebuild_index(project)
    return project


def test_open_returns_simulation_catalog(tmp_path: Path) -> None:
    cat = hmp.open(_empty_index(tmp_path))
    try:
        assert isinstance(cat, hmp.Catalog)
    finally:
        cat.close()


def test_simulation_catalog_repr_html(tmp_path: Path) -> None:
    cat = hmp.open(_empty_index(tmp_path))
    try:
        html = cat._repr_html_()
        assert "<b>Catalog</b>" in html
        assert "<table" in html
    finally:
        cat.close()


def test_simulation_group_fluent_methods_present() -> None:
    from hydromodpy.results.run.group import RunSet

    assert hasattr(RunSet, "filter")
    assert hasattr(RunSet, "to_dataframe")
    assert hasattr(RunSet, "_repr_html_")


def test_simulation_view_fluent_methods_present() -> None:
    from hydromodpy.results.run import Run

    assert hasattr(Run, "field")
    assert hasattr(Run, "summary")
    assert hasattr(Run, "metrics")
    assert hasattr(Run, "_repr_html_")


def test_the_catalog_is_a_reader(tmp_path: Path) -> None:
    """The index is written by the indexer alone: the handle carries no writer."""
    cat = hmp.open(_empty_index(tmp_path))
    try:
        for name in ("register_simulation", "export_package", "import_package", "delete"):
            assert not hasattr(cat, name), name
    finally:
        cat.close()


def test_doctor_returns_dict() -> None:
    report = hmp.doctor()
    assert isinstance(report, dict)
    for key in ("python", "hydromodpy", "solvers", "optional"):
        assert key in report


def test_unknown_attribute_raises() -> None:
    with pytest.raises(AttributeError):
        hmp.NotARealThing  # noqa: B018
