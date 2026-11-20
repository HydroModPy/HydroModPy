"""A backend writes what its ``writes`` declares, and a simulated series has a descriptor.

The extract step compares the names of the store before and after an
extractor, and refuses an added name that no name or pattern of ``writes``
matches. The store refuses a simulated series whose name neither the series
registry nor the field registry holds.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.results.storage.contract import (
    FIELDS_STORE_NAME,
    PARQUET_FILE_SUFFIX,
    TABLES_DIRNAME,
)
from hydromodpy.results.storage.declared import (
    pattern_regex,
    refuse_undeclared,
    refuse_unknown_series,
    stored_names,
)

WRITES = ("head", "budget/drain", "lake_abacus/*/stage", "budgets")


@pytest.mark.parametrize(
    ("pattern", "name", "matches"),
    [
        ("head", "head", True),
        ("budget/drain", "budget/drain", True),
        ("budget/drain", "budget/drain_to_mover", False),
        ("lake_abacus/*/stage", "lake_abacus/north/stage", True),
        ("lake_abacus/*/stage", "lake_abacus/north/deep/stage", False),
        ("lake_abacus/*/stage", "lake_abacus/north/sim_volume", False),
    ],
)
def test_a_star_stands_for_one_path_segment(pattern: str, name: str, matches: bool) -> None:
    assert bool(pattern_regex(pattern).match(name)) is matches


@pytest.mark.parametrize(
    "added",
    [
        pytest.param({"head", "budgets"}, id="exact-names"),
        pytest.param({"lake_abacus/north/stage"}, id="star-on-one-segment"),
        pytest.param({"mesh/idomain", "time", "geographic_rivers", "timeseries"}, id="pipeline"),
        pytest.param(set(), id="nothing-added"),
    ],
)
def test_a_declared_name_is_accepted(added: set[str]) -> None:
    refuse_undeclared(added, WRITES, backend="modflow6")


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("budget/storage", id="undeclared-field"),
        pytest.param("lake_abacus/north/deep/stage", id="star-over-two-segments"),
        pytest.param("sfr_reaches", id="undeclared-table"),
    ],
)
def test_an_undeclared_name_is_refused(name: str) -> None:
    expected = (
        f"Backend modflow6 wrote {name!r}, which its writes does not declare. "
        f"Add {name!r} or its pattern to writes of the modflow6 adapter."
    )
    with pytest.raises(DataContractViolation) as caught:
        refuse_undeclared({"head", name}, WRITES, backend="modflow6")
    assert str(caught.value) == expected
    assert caught.value.code == "HMPY.E201"


def _array(fields: Path, path: str) -> None:
    folder = fields / path
    folder.mkdir(parents=True)
    (folder / "zarr.json").write_text(json.dumps({"node_type": "array"}), encoding="utf-8")


def _group(fields: Path, path: str) -> None:
    folder = fields / path
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "zarr.json").write_text(json.dumps({"node_type": "group"}), encoding="utf-8")


def test_the_stored_names_leave_out_the_pipeline(tmp_path: Path) -> None:
    fields = tmp_path / FIELDS_STORE_NAME
    _group(fields, ".")
    _group(fields, "budget")
    for path in ("head", "budget/drain", "time", "crs", "mesh/idomain", "forcing/recharge"):
        _array(fields, path)
    tables = tmp_path / TABLES_DIRNAME
    tables.mkdir()
    for name in ("budgets", "timeseries", "simulation", "geographic_rivers"):
        (tables / f"{name}{PARQUET_FILE_SUFFIX}").write_bytes(b"")

    assert stored_names(tmp_path) == frozenset({"head", "budget/drain", "budgets"})


def test_a_run_without_zarr_or_parquet_stores_no_name(tmp_path: Path) -> None:
    assert stored_names(tmp_path) == frozenset()


@pytest.mark.parametrize(
    "variable",
    [
        pytest.param("discharge", id="series-key"),
        pytest.param("lake_storage", id="lake-storage"),
        pytest.param("cutoff_wall_flow", id="wall-flow"),
        pytest.param("groundwater_level", id="piezometer-record"),
        pytest.param("head", id="field-name"),
        # An observation point may sample the storage budget field of its cell.
        # The lake extractor refuses its own old storage quantity instead.
        pytest.param("storage", id="aquifer-storage-field"),
    ],
)
def test_a_described_series_is_accepted(variable: str) -> None:
    refuse_unknown_series([variable])


@pytest.mark.parametrize("variable", ["lake_volume_change", "Discharge", ""])
def test_a_series_without_a_descriptor_is_refused(variable: str) -> None:
    expected = (
        f"A simulated series named {variable!r} has no descriptor. Add it to "
        "TIME_SERIES_REGISTRY in hydromodpy/results/field_registry.py with its unit."
    )
    with pytest.raises(DataContractViolation) as caught:
        refuse_unknown_series(["discharge", variable])
    assert str(caught.value) == expected
