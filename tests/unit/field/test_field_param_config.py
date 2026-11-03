"""The schema of a field-parameter table, :mod:`hydromodpy.spatial.field.field_param_config`."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path

import pytest

from hydromodpy.spatial.field.field_param import FieldParam
from hydromodpy.spatial.field.field_param_config import (
    load_field_param_toml,
    resolve_field_param_config_payload,
    validate_field_param_toml_data,
    validate_resolved_field_param_data,
)
from tests._helpers.field_cases import write_text

PER_ZONE = dict(id="K", kind="heterogeneous", values={"granite": 10.0}, field_spatial_id="g")
CSV = {"id": "K", "kind": "heterogeneous", "values_source": "csv", "values_csv_file": "map.csv"}


def _k(value: object = 10.0, **field) -> dict:
    return {"id": "K", "kind": "homogeneous", "value": value} | field


def _profile(**profile) -> dict:
    return {"field": _k(), "field_vertical_profile": profile}


def _tabulated(**override) -> dict:
    return _profile(**dict(kind="tabulated", depths=[0.0, 10.0], factors=[1.0, 0.5]) | override)


@pytest.mark.parametrize(
    ("payload", "section", "expected"),
    [
        ({"field": PER_ZONE | {"unit": "m/s"}}, "field",
         {"id": "K", "kind": "heterogeneous", "unit": "m/s", "field_spatial_id": "g"}),
        ({"field": _k(0.2, id="Sy", unit="dimensionless")}, "field", {"unit": "-"}),
        ({"field": _k(0.01, unit="m/h")}, "field", {"unit": "m/h"}),
        ({"field": _k("1e-4")}, "field", {"value": 1e-4}),
        ({"field": _k("1e-4", unit="m/s")}, "field", {"value": 1e-4, "unit": "m/s"}),
        ({"field": _k(None)}, "field", {"id": "K", "kind": "homogeneous"}),
        ({"field": {"kind": "heterogeneous"}}, "field", {"values_source": "inline"}),
        ({"field": PER_ZONE | {"values": {"a": "10 m/day"}}}, "field", {"values": {"a": "10 m/day"}}),
        ({"field": CSV | {"field_spatial_id": "g"}}, "field",
         {"values_source": "csv", "values_csv_file": Path("map.csv"), "field_spatial_id": "g"}),
        (_profile(kind="exponential", characteristic_depth=30.0), "field_vertical_profile",
         {"kind": "exponential", "characteristic_depth": 30.0}),
        (_profile(kind="exponential", characteristic_depth="30.0 m", min_factor=1e-3),
         "field_vertical_profile", {"characteristic_depth": 30.0, "min_factor": 1e-3}),
        (_tabulated(), "field_vertical_profile", {"depths": [0.0, 10.0], "interpolation": "linear"}),
    ],
    ids=["per-zone", "unit-alias", "hourly-k", "bare-number-text", "number-text-and-unit",
         "no-value-yet", "empty-template", "per-zone-inline-units", "csv", "exponential",
         "depth-with-unit-and-floor", "tabulated"],
)  # fmt: skip
def test_a_field_table_is_normalised(payload, section, expected):
    result = validate_field_param_toml_data(payload)[section]
    assert {key: result.get(key) for key in expected} == expected
    if expected.get("value") is None and "value" in expected:
        assert "value" not in result


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        (["field"], "must be a mapping"),
        ({"field": _k(unit="foo/bar")}, "Unsupported field.unit"),
        ({"field": _k(unit=" ")}, "field.unit cannot be empty"),
        ({"field": _k(unexpected=1)}, "unexpected"),
        ({"field": _k(), "field_common": {"id": "K"}}, "field_common"),
        ({"field": _k(True)}, "field.value must be numeric"),
        ({"field": _k(" ")}, "field.value cannot be empty"),
        ({"field": _k([1.0])}, "field.value must be numeric"),
        ({"field": PER_ZONE | {"values": {"a": True}}}, r"field.values\['a'\] must be numeric"),
        ({"field": PER_ZONE | {"values": {"a": " "}}}, r"field.values\['a'\] cannot be empty"),
        ({"field": PER_ZONE | {"values": {"a": [1]}}}, r"field.values\['a'\] must be numeric"),
        ({"field": PER_ZONE | {"values": {}}}, "field.values cannot be empty"),
        ({"field": PER_ZONE | {"values": {" ": 1.0}}}, "cannot contain empty keys"),
        ({"field": {"kind": "heterogeneous", "field_spatial_id": "g"}}, "field.values is required"),
        ({"field": {"kind": "heterogeneous", "values": {"a": 1.0}}}, "field_spatial_id is required"),
        ({"field": CSV | {"values_csv_file": None, "field_spatial_id": "g"}}, "values_csv_file"),
        ({"field": CSV}, "field_spatial_id is required"),
        (_profile(kind="exponential"), "characteristic_depth is required"),
        (_profile(kind="exponential", characteristic_depth=30.0, min_factor=1.2), "min_factor"),
        (_profile(kind="tabulated", factors=[1.0]), "depths is required"),
        (_profile(kind="tabulated", depths=[0.0]), "factors is required"),
        (_tabulated(depths=[0.0]), "must have same length"),
        (_tabulated(depths=[-1.0, 10.0]), "must be >= 0"),
        (_tabulated(depths=[0.0, 0.0]), "strictly increasing"),
        (_tabulated(depths=[1.0, 10.0]), "first depth must be 0.0"),
        (_tabulated(factors=[0.5, 0.5]), "factor at depth 0.0 must be 1.0"),
    ],
)  # fmt: skip
def test_a_field_table_that_says_nothing_usable_is_refused(payload, match):
    with pytest.raises(ValueError, match=match):
        validate_field_param_toml_data(payload)


def test_a_field_file_is_read_and_its_errors_name_it(tmp_path: Path):
    good = write_text(
        tmp_path / "good.toml", '[field]\nid = "K"\nkind = "homogeneous"\nvalue = 12.5'
    )
    bad = write_text(tmp_path / "bad.toml", '[field]\nid = "K"\nkind = "homogeneous"\nunit = "foo"')

    assert load_field_param_toml(good)["field"]["value"] == 12.5
    with pytest.raises(ValueError, match=r"Invalid field parameter configuration in .*bad\.toml"):
        load_field_param_toml(bad)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"id": "K", "kind": "homogeneous", "unit": "m/day", "value": 3.5}, _k(3.5, unit="m/day")),
        (_k("3.5 m/day"), _k(3.5, unit="m/day")),
        (_k(3.5, values={"a": 1.0}, field_spatial_id="g"), _k(3.5)),
        (PER_ZONE | {"value": 1.0, "values": {"a": "10 m/day"}}, PER_ZONE | {"values": {"a": "10 m/day"}}),
        (
            _k(3.5, field_vertical_profile={"kind": "exponential", "characteristic_depth": 50.0, "min_factor": 0.01}),
            _k(3.5) | {"vertical_profile": {"kind": "exponential", "characteristic_depth": 50.0,
                                            "min_factor": 0.01, "interpolation": "linear"}},
        ),
    ],
    ids=["homogeneous", "inline-unit", "drops-zone-keys", "drops-the-scalar", "profile-alias"],
)  # fmt: skip
def test_a_resolved_parameter_keeps_the_keys_of_its_kind(payload, expected):
    assert validate_resolved_field_param_data(payload) == expected


@pytest.mark.parametrize(
    ("payload", "error", "match"),
    [
        (["K"], ValueError, "must be a mapping"),
        ({"kind": "homogeneous", "value": 1.0}, KeyError, "'id'"),
        ({"id": "K", "value": 1.0}, KeyError, "'kind'"),
        ({"id": "K", "kind": "homogeneous"}, KeyError, "requires key 'value'"),
        ({"id": "K", "kind": "heterogeneous", "field_spatial_id": "g"}, KeyError, "mapping key 'values'"),
        ({"id": "K", "kind": "heterogeneous", "values": {"a": 1}}, KeyError, "'field_spatial_id'"),
        (_k(None), ValueError, "Homogeneous field requires 'value'"),
        (_k(True), ValueError, "value must be numeric"),
        (_k(" "), ValueError, "value cannot be empty"),
        (_k([1.0]), ValueError, "value must be numeric"),
        (PER_ZONE | {"values": None}, ValueError, "Heterogeneous field requires 'values'"),
        (PER_ZONE | {"field_spatial_id": None}, ValueError, "requires 'field_spatial_id'"),
        (PER_ZONE | {"values": {"a": True}}, ValueError, r"values\['a'\] must be numeric"),
        (PER_ZONE | {"values": {"a": " "}}, ValueError, r"values\['a'\] cannot be empty"),
        (PER_ZONE | {"values": {"a": [1]}}, ValueError, r"values\['a'\] must be numeric"),
        (PER_ZONE | {"values": {}}, ValueError, "values cannot be empty"),
        (PER_ZONE | {"values": {" ": 1.0}}, ValueError, "cannot contain empty keys"),
    ],
)  # fmt: skip
def test_a_resolved_parameter_without_its_values_is_refused(payload, error, match):
    with pytest.raises(error, match=match):
        validate_resolved_field_param_data(payload)


def test_a_project_section_takes_its_key_as_id_and_its_profile():
    payload = {
        "field": {"kind": "homogeneous", "value": 2.0},
        "field_vertical_profile": {"kind": "exponential", "characteristic_depth": 9.0},
    }

    resolved = resolve_field_param_config_payload(payload, param_id="K", section_label="flow.K")

    assert resolved["id"] == "K"
    assert resolved["vertical_profile"]["characteristic_depth"] == 9.0
    with pytest.raises(ValueError, match="flow.K.field.id must match section key 'Sy', got 'K'"):
        resolve_field_param_config_payload({"field": _k()}, param_id="Sy", section_label="flow.K")
    with pytest.raises(ValueError, match="requires 'base_dir'"):
        resolve_field_param_config_payload({"field": CSV | {"field_spatial_id": "g"}})


def _homogeneous(value: object, unit: str | None) -> object:
    return validate_field_param_toml_data({"field": _k(value) | _unit(unit)})


def _zone(value: object, unit: str | None) -> object:
    return validate_field_param_toml_data({"field": PER_ZONE | {"values": {"granite": value}} | _unit(unit)})  # fmt: skip


def _without_id(value: object, unit: str | None) -> object:
    section = {"kind": "homogeneous", "value": value} | _unit(unit)
    return FieldParam.from_dict(
        resolve_field_param_config_payload({"field": section}, param_id="K")
    )


def _unit(unit: str | None) -> dict:
    return {"unit": unit} if unit else {}


@pytest.mark.parametrize(
    ("enter", "value", "unit", "refused"),
    [(_homogeneous, 150.0, "m/day", None), (_homogeneous, "150 m/day", None, None),
     (_homogeneous, 1e-13, "m/day", "outside"), (_homogeneous, 150.0, "m/s", "outside"),
     (_homogeneous, 1e-5, None, None), (_homogeneous, 1e-5, "m-1", "expects 'm/s' or a unit convertible to it"),
     (_zone, 150.0, "m/day", None), (_zone, 1e3, None, r"in zone 'granite' value 1000.0 outside \[1e-14, 100.0\] m/s"),
     (_zone, "1e9 m/day", None, r"in zone 'granite' value 1000000000.0 m/day \(11574.1 m/s\) outside"),
     (_without_id, 1e-5, None, None), (_without_id, 1e3, None, r"\(id='K'\) value 1000.0 outside"),
     (_without_id, "1e9 m/day", None, r"value 1000000000.0 m/day \(11574.1 m/s\)")],
    ids=["m-day", "inline-m-day", "too-low-m-day", "too-high-m-s", "canonical", "other-quantity",
         "zone-m-day", "zone-too-high", "zone-too-high-inline", "no-id", "no-id-too-high",
         "no-id-too-high-inline"],
)  # fmt: skip
def test_a_value_is_bounded_in_its_declared_unit_wherever_it_enters(enter, value, unit, refused):
    with nullcontext() if refused is None else pytest.raises(ValueError, match=refused):
        enter(value, unit)
