"""Tests for the canonical CF-1.11 field registry (phase G05)."""

from __future__ import annotations

import pytest

from hydromodpy.core.exceptions import UnknownFieldError
from hydromodpy.results import field_registry
from hydromodpy.results.field_registry import (
    FIELD_REGISTRY,
    FieldDescriptor,
    all_names,
    all_zarr_paths,
    cf_attrs,
    get,
    has,
)


class TestRegistryContents:
    def test_has_eighteen_fields(self):
        assert len(FIELD_REGISTRY) >= 18

    def test_registry_exposes_essential_public_names(self):
        # Hard-required set from the G05 plan (see
        # docs/developers/architecture_conformance_report.md).
        required = {
            "head",
            "concentration",
            "watertable_elevation",
            "watertable_depth",
            "seepage_mask",
            "seepage_rate",
            "storage_change",
            "recharge",
            "drain",
            "river",
            "well",
            "cell_budget",
            "topography",
            "layer_thickness",
            "hydraulic_conductivity",
            "specific_yield",
            "specific_storage",
            "porosity",
        }
        assert required <= set(FIELD_REGISTRY)

    def test_public_name_matches_key(self):
        for key, desc in FIELD_REGISTRY.items():
            assert desc.public_name == key, f"Public name mismatch for {key}: {desc.public_name!r}"

    def test_zarr_paths_are_unique(self):
        paths = [d.zarr_path for d in FIELD_REGISTRY.values()]
        assert len(paths) == len(set(paths)), "duplicate zarr_path detected"

    def test_cf_metadata_is_non_empty(self):
        for name, desc in FIELD_REGISTRY.items():
            assert desc.standard_name, f"{name} missing standard_name"
            assert desc.long_name, f"{name} missing long_name"
            assert desc.units, f"{name} missing units"


class TestFieldDescriptor:
    def test_is_frozen(self):
        desc = get("head")
        with pytest.raises((AttributeError, Exception)):
            desc.public_name = "other"  # type: ignore[misc]

    def test_coordinates_is_derived_from_shape(self):
        head = get("head")
        assert head.shape == field_registry.SHAPE_TIME_LAYER_FACE
        assert head.coordinates == "time layer face"

        wt = get("watertable_depth")
        assert wt.shape == field_registry.SHAPE_TIME_FACE
        assert wt.coordinates == "time face"


class TestPublicAPI:
    def test_get_unknown_raises_unknownfielderror_with_available_names(self):
        with pytest.raises(UnknownFieldError) as exc_info:
            get("unknown_field_xyz")
        err = exc_info.value
        assert err.name == "unknown_field_xyz"
        assert "head" in err.available
        assert "not registered" in err.message

    def test_has(self):
        assert has("head") is True
        assert has("definitely_not_a_field") is False

    def test_all_names_is_sorted(self):
        names = all_names()
        assert names == sorted(names)
        assert "head" in names

    def test_all_zarr_paths_is_sorted(self):
        paths = all_zarr_paths()
        assert paths == sorted(paths)

    def test_cf_attrs_returns_expected_keys(self):
        attrs = cf_attrs("head")
        expected = {
            "standard_name",
            "long_name",
            "units",
            "cell_methods",
            "grid_mapping",
            "coordinates",
        }
        assert set(attrs) == expected
        assert attrs["standard_name"] == "groundwater_head_above_reference_level"
        assert attrs["units"] == "m"
        assert attrs["grid_mapping"] == "crs"
