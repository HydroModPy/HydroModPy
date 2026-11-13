"""The registries name a quantity kind and a label, and store nothing of either."""

from __future__ import annotations

import pytest

from hydromodpy.core.units.kinds import QUANTITY_KINDS, SCALES, SIGNS, QuantityKind, scale_of
from hydromodpy.core.units.parse import convert_between_units
from hydromodpy.results import field_registry as registry
from hydromodpy.results.derive.mesh_quality import MESH_QUALITY_DESCRIPTORS
from hydromodpy.results.exporters.vocabulary import OBSERVED_VARIABLES
from hydromodpy.results.storage.parquet_schemas import TABLE_SCHEMAS, column_unit

DESCRIPTORS = {
    **registry.FIELD_REGISTRY,
    **registry.TIME_SERIES_REGISTRY,
    **MESH_QUALITY_DESCRIPTORS,
    **registry.REBUILT_FIELDS,
}
CF_ATTRIBUTE_KEYS = {
    "long_name",
    "units",
    "cell_methods",
    "grid_mapping",
    "coordinates",
    "standard_name",
    "csdms_standard_name",
    "valid_min",
    "valid_max",
    "sign_convention",
    "mesh",
    "location",
}


def test_kind_names():
    assert set(QUANTITY_KINDS) == {
        "head", "elevation", "depth", "thickness", "cell_flow", "flux_per_area", "flow",
        "conductivity", "fraction", "ratio", "specific_storage", "angle", "azimuth",
        "concentration", "mass_flux", "volume", "area", "category", "index",
        "distance", "score", "percent",
    }  # fmt: skip
    cumulated = {kind.cumulates_to for kind in QUANTITY_KINDS.values()} - {None}
    assert cumulated <= set(QUANTITY_KINDS)


@pytest.mark.parametrize("name", sorted(DESCRIPTORS))
def test_descriptor_matches_its_kind(name):
    descriptor = DESCRIPTORS[name]
    kind = QUANTITY_KINDS[descriptor.quantity]
    assert descriptor.units == kind.stored_unit
    assert 0 < len(descriptor.label) <= 40
    assert descriptor.sign is None or descriptor.sign in SIGNS
    assert descriptor.observed is None or descriptor.observed in OBSERVED_VARIABLES
    assert bool(descriptor.classes) == kind.categorical
    if name in registry.REBUILT_FIELDS:
        assert name not in registry.FIELD_REGISTRY
    if name in registry.FIELD_REGISTRY or name in registry.TIME_SERIES_REGISTRY:
        assert registry.kind_of(name) is kind
        assert registry.label_of(name) == descriptor.label


@pytest.mark.parametrize("name", sorted(QUANTITY_KINDS))
def test_display_unit_is_reached(name):
    kind = QUANTITY_KINDS[name]
    source = "m s-1" if kind.per_area else kind.stored_unit
    assert convert_between_units(1.0, from_unit=source, to_unit=kind.display_unit) > 0


@pytest.mark.parametrize(
    ("name", "sign", "expected"),
    [
        ("category", None, "categorical"),
        ("azimuth", None, "cyclic"),
        ("cell_flow", None, "diverging"),
        ("cell_flow", "negative", "sequential"),
    ],
)
def test_scale_of(name, sign, expected):
    assert scale_of(QUANTITY_KINDS[name], sign) == expected


@pytest.mark.parametrize(
    ("name", "source", "factor"),
    [("cell_flow", "m s-1", 8.64e7), ("concentration", "kg m-3", 1000.0)],
)
def test_conversion_factor(name, source, factor):
    kind = QUANTITY_KINDS[name]
    value = convert_between_units(1.0, from_unit=source, to_unit=kind.display_unit)
    assert value == pytest.approx(factor)


def test_scale_of_returns_known_scales():
    assert {scale_of(kind) for kind in QUANTITY_KINDS.values()} <= set(SCALES)


def test_kind_refuses_an_unknown_sign():
    with pytest.raises(ValueError, match="sign"):
        QuantityKind("m", "m", sign="up")


@pytest.mark.parametrize("name", sorted(registry.FIELD_REGISTRY))
def test_cf_attrs_stay_unchanged(name):
    assert set(registry.cf_attrs(name)) <= CF_ATTRIBUTE_KEYS


def test_descriptor_refuses_an_unknown_sign():
    with pytest.raises(ValueError, match="sign"):
        registry.TimeSeriesDescriptor("x", "X", "m", quantity="flow", label="X", sign="up")


@pytest.mark.parametrize("key", sorted(registry.COLUMN_REGISTRY))
def test_column_row_names_a_schema_column(key):
    table, column = key.split(".")
    row = registry.COLUMN_REGISTRY[key]
    assert column in TABLE_SCHEMAS[table].names
    assert row.quantity in QUANTITY_KINDS
    assert 0 < len(row.label) <= 40
    assert registry.kind_of(key) is QUANTITY_KINDS[row.quantity]
    assert registry.label_of(key) == row.label
    kind = QUANTITY_KINDS[row.quantity]
    source = column_unit(table, column) or kind.stored_unit
    assert convert_between_units(1.0, from_unit=source, to_unit=kind.display_unit) > 0


def test_rebuilt_fields_stay_out_of_the_stored_registry():
    assert set(registry.REBUILT_FIELDS) == {
        "simulated_active_network", "network_agreement", "downslope_distance",
        "depression_fill_depth", "package_cells",
    }  # fmt: skip
    assert not set(registry.REBUILT_FIELDS) & set(registry.FIELD_REGISTRY)
    assert registry.kind_of("network_agreement").categorical
    assert registry.label_of("downslope_distance") == "Downslope distance"
    assert column_unit("mass_balance", "percent_error") == "percent"
