"""Smoke tests for the public ``hydromodpy`` API surface.

These checks pin down the top-level symbols that the P10 spec promises to
users — ``hmp.open``, ``hmp.Project``, ``hmp.Run``, ``hmp.SimulationCatalog``,
etc. Regressions here usually mean a refactor broke the import contract.
"""

from __future__ import annotations

import tempfile

import pytest

import hydromodpy as hmp

EXPECTED_TOP_LEVEL = [
    # Entry points
    "open",
    "run",
    "calibrate",
    "compare",
    "doctor",
    # Project / run / catalog API
    "Project",
    "Run",
    "SimulationPlan",
    "SimulationCatalog",
    "SimulationGroup",
    "Catalog",
    # Core
    "Workspace",
    "CatchmentDelineation",
    # Solvers
    "Modflow",
    "Boussinesq",
    "Modflow6",
]


@pytest.mark.parametrize("symbol", EXPECTED_TOP_LEVEL)
def test_public_symbol_available(symbol: str) -> None:
    assert hasattr(hmp, symbol), f"hmp.{symbol} missing from public API"


def test_catalog_alias_is_simulation_catalog() -> None:
    assert hmp.Catalog is hmp.SimulationCatalog


def test_open_returns_simulation_catalog() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cat = hmp.open(tmp)
        try:
            assert isinstance(cat, hmp.SimulationCatalog)
        finally:
            cat.close()


def test_simulation_catalog_repr_html() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cat = hmp.open(tmp)
        try:
            html = cat._repr_html_()
            assert "<b>SimulationCatalog</b>" in html
            assert "<table" in html
        finally:
            cat.close()


def test_simulation_group_fluent_methods_present() -> None:
    from hydromodpy.results.simulation_group import SimulationGroup

    assert hasattr(SimulationGroup, "filter")
    assert hasattr(SimulationGroup, "to_dataframe")
    assert hasattr(SimulationGroup, "_repr_html_")


def test_simulation_view_fluent_methods_present() -> None:
    from hydromodpy.results.run import Run

    assert hasattr(Run, "at")
    assert hasattr(Run, "field")
    assert hasattr(Run, "_repr_html_")


def test_catalog_export_import_method_names() -> None:
    """Public catalog API exposes export_package() and import_package() (P10 rename)."""
    with tempfile.TemporaryDirectory() as tmp:
        cat = hmp.open(tmp)
        try:
            assert callable(getattr(cat, "export_package", None))
            assert callable(getattr(cat, "import_package", None))
            assert not hasattr(cat, "export_simulation")
            assert not hasattr(cat, "import_simulation")
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
