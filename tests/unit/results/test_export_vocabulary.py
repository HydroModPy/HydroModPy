"""One namespace for every name a user can export, each with its kind."""

from __future__ import annotations

import pytest

from hydromodpy.core.config_kit.export_spec import ExportKind
from hydromodpy.data.variables.hydrometry.manager import HydrometryManager
from hydromodpy.data.variables.intermittency.manager import IntermittencyManager
from hydromodpy.data.variables.lake_levels.manager import LakeLevelsManager
from hydromodpy.data.variables.piezometry.manager import PiezometryManager
from hydromodpy.results import field_registry
from hydromodpy.results.exporters.vocabulary import (
    OBSERVED_VARIABLES,
    SIMULATED_ACTIVE_NETWORK,
    SIMULATED_SERIES,
    describe_export_names,
    export_kind,
    static_export_names,
)
from hydromodpy.simulation.extraction.derivation.catchment_aggregation import VARIABLE_UNITS


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("head", ExportKind.field),
        ("watertable_depth", ExportKind.field),
        ("seepage_mask", ExportKind.field),
        (SIMULATED_ACTIVE_NETWORK, ExportKind.field),
        ("discharge", ExportKind.series),
        ("discharge_obs", ExportKind.series),
        ("stage", ExportKind.series),
        ("watershed", ExportKind.vector),
        ("watershed_contour", ExportKind.vector),
        ("watershed_box_buff", ExportKind.vector),
        ("hydrographic_network_reference", ExportKind.vector),
        ("hydrographic_network_reference_permanent", ExportKind.vector),
        ("observed_network_snapped", ExportKind.vector),
        ("watershed_dem", ExportKind.raster),
        ("watershed_fill", ExportKind.raster),
        ("budget", ExportKind.table),
    ],
)
def test_each_name_has_its_kind(name: str, kind: ExportKind) -> None:
    assert export_kind(name) is kind


def test_a_name_no_run_holds_has_no_kind() -> None:
    assert export_kind("hed") is None
    assert export_kind("all") is None


def test_every_registered_field_is_exportable() -> None:
    names = static_export_names()
    assert all(names[name] is ExportKind.field for name in field_registry.all_names())


def test_the_catchment_series_are_known() -> None:
    assert set(VARIABLE_UNITS) <= set(SIMULATED_SERIES)


@pytest.mark.parametrize(
    "manager",
    [HydrometryManager, IntermittencyManager, LakeLevelsManager, PiezometryManager],
)
def test_each_observation_family_has_its_observed_series(manager: type) -> None:
    assert manager.RECORD_VARIABLE in OBSERVED_VARIABLES
    assert export_kind(f"{manager.RECORD_VARIABLE}_obs") is ExportKind.series


def test_the_vocabulary_prints_one_line_per_kind() -> None:
    lines = describe_export_names().splitlines()
    assert [line.split(":")[0].strip() for line in lines] == [
        "fields",
        "series",
        "vector layers",
        "raster layers",
        "tables",
    ]
