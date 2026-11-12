"""One field parameter, homogeneous or per zone, in SI, :mod:`hydromodpy.model.properties.field_param`."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.core.units.physical_bounds import PhysicalBoundsError
from hydromodpy.model.properties.field_param import FieldParam
from hydromodpy.model.properties.field_spatial import WeightedAverageFieldDiscretization
from hydromodpy.model.properties.unit_square_mesh import FieldMeshSquare
from tests._helpers.field_cases import two_zone_square

GRANITE_SCHIST = {"granite": 10.0, "micaschists": 2.0}


def _homogeneous(value: object = 10.0, **kwargs) -> FieldParam:
    identifier = kwargs.pop("identifier", "K")
    return FieldParam(identifier=identifier, kind="homogeneous", value=value, **kwargs)


def _per_zone(values=GRANITE_SCHIST, **kwargs) -> FieldParam:
    return FieldParam(
        identifier="K", kind="heterogeneous", values_by_key=values, field_spatial_id="field_square", **kwargs
    )  # fmt: skip


def _exponential() -> FieldParam:
    return _homogeneous(vertical_profile={"kind": "exponential", "characteristic_depth": 9.0})


def _square(n_cells: int = 12, kind: str = "structured"):
    return FieldMeshSquare.from_unit_square(target_n_cells=n_cells, mesh_kind=kind)


@pytest.mark.parametrize(
    ("identifier", "unit", "value", "si_unit", "si_value"),
    [("K", "m/day", 8.64, "m/s", 1e-4), ("K", "mm/day", 8640.0, "m/s", 1e-4),
     ("K", None, "8.64 m/day", "m/s", 1e-4), ("Ss", "cm-1", 1e-6, "m-1", 1e-4),
     ("Ss", None, "1e-6 cm-1", "m-1", 1e-4), ("Sy", None, "0.2 -", "-", 0.2),
     ("porosity", None, 0.3, "-", 0.3), ("Kv", None, 1e-5, "-", 1e-5)],
    ids=["k-m-day", "k-mm-day", "k-inline", "ss-cm", "ss-inline", "sy-inline", "unknown-id",
         "kv-without-unit-is-bounded-in-m-s"],
)  # fmt: skip
def test_value_stored_in_si(identifier, unit, value, si_unit, si_value):
    param = _homogeneous(value, identifier=identifier, unit=unit)
    assert param.unit == si_unit
    assert float(param.value) == pytest.approx(si_value)


def test_per_zone_units_and_profile():
    profile = {"kind": "tabulated", "depths": [0.0, 20.0, 40.0], "factors": [1.0, 0.5, 0.25]}
    param = _per_zone({"granite": "10 m/day", "micaschists": "2 m/day"}, vertical_profile=profile)
    zones = np.array(["granite", "micaschists", "granite"], dtype=object)
    np.testing.assert_allclose(param.to_array(zone_ids=zones), np.array([10, 2, 10]) / 86400)
    np.testing.assert_allclose(param.to_array(zone_ids=zones, depth=10.0), np.array([7.5, 1.5, 7.5]) / 86400)  # fmt: skip


@pytest.mark.parametrize(
    ("kwargs", "error", "match"),
    [
        ({"identifier": " "}, ValueError, "non-empty 'identifier'"),
        ({"kind": "layered"}, ValueError, "Unsupported field kind 'layered'"),
        ({"unit": " "}, ValueError, "unit cannot be empty"),
        ({"unit": "furlong"}, ValueError, "Unsupported unit 'furlong'"),
        ({"unit": "m-1"}, ValueError, "Expected SI family"),
        ({"unit": "m/day", "value": "1.0 m/s"}, ValueError, "mixes conflicting units"),
        ({"value": None}, ValueError, "Homogeneous field requires 'value'"),
        ({"kind": "heterogeneous"}, ValueError, "requires 'values_by_key'"),
        ({"kind": "heterogeneous", "values_by_key": {}}, ValueError, "cannot be empty"),
        ({"kind": "heterogeneous", "values_by_key": {"a": 1.0}}, ValueError, "'field_spatial_id'"),
        ({"kind": "heterogeneous", "values_by_key": {"a": "1 m-1"}, "field_spatial_id": "g"},
         ValueError, r"K\.values\[a\] unit 'm-1' is inconsistent"),
        ({"value": 1e3}, PhysicalBoundsError, r"\(id='K'\) value 1000.0 outside \[1e-14, 100.0\] m/s"),
        ({"unit": "m/day", "value": 1e9}, PhysicalBoundsError, r"value 1000000000.0 m/day \(11574.1 m/s\)"),
        ({"identifier": "Kv", "value": 1e3}, PhysicalBoundsError, r"\(id='Kv'\) value 1000.0 outside"),
        ({"kind": "heterogeneous", "values_by_key": {"a": 1e-5, "b": "1e9 m/day"}, "field_spatial_id": "g"},
         PhysicalBoundsError, r"\(id='K'\) in zone 'b' value 1000000000.0 m/day \(11574.1 m/s\)"),
    ],
    ids=["no-identifier", "unknown-kind", "blank-unit", "unknown-unit", "other-quantity",
         "conflicting-inline-unit", "no-value", "no-zone-values", "empty-zone-values", "no-support",
         "zone-value-of-another-quantity", "out-of-bounds", "out-of-bounds-in-its-unit",
         "out-of-bounds-without-a-default-unit", "zone-out-of-bounds"],
)  # fmt: skip
def test_refusals(kwargs, error, match):
    with pytest.raises(error, match=match):
        FieldParam(**({"identifier": "K", "kind": "homogeneous", "value": 1.0} | kwargs))


def test_homogeneous_fill():
    param = _homogeneous(4.0)
    x = np.zeros((2, 3))

    np.testing.assert_array_equal(param.to_array(x=x, y=x), np.full((2, 3), 4.0))
    np.testing.assert_array_equal(param.to_array(zone_ids=np.array(["a", "b"])), [4.0, 4.0])
    np.testing.assert_array_equal(param.to_array(shape=(2, 3)), np.full((2, 3), 4.0))
    with pytest.raises(ValueError, match="provide both x and y"):
        param.to_array(x=x)
    with pytest.raises(ValueError, match="same shape"):
        param.to_array(x=x, y=np.zeros(3))


def test_zone_keys_as_text():
    param = _per_zone({"1": 1.0, "1.5": 2.0, "a": 3.0})

    np.testing.assert_array_equal(param.map_zone_ids(np.array([1, 1.0, 1.5])), [1.0, 1.0, 2.0])
    np.testing.assert_array_equal(param.map_zone_ids(np.array([1, 1])), [1.0, 1.0])
    np.testing.assert_array_equal(
        param.to_array(zone_field=SimpleNamespace(cell_values=["a"])), [3]
    )
    with pytest.raises(ValueError, match="only valid for heterogeneous"):
        _homogeneous().map_zone_ids(["a"])


@pytest.mark.parametrize(
    ("call", "error", "match"),
    [
        (lambda p: p.to_array(), ValueError, "requires 'zone_ids'"),
        (lambda p: p.to_array(zone_field=object()), TypeError, "must expose 'cell_values'"),
        (lambda p: p.to_mesh_field(), ValueError, "field_discretization"),
        (lambda p: p.to_mesh_field(object()), TypeError, "must expose: 'mesh'"),
        (lambda p: p.to_mesh_field(SimpleNamespace(mesh=None, aggregation="max", weighted_components=None)),
         ValueError, "Unsupported field discretization aggregation 'max'"),
        (lambda p: p.to_mesh_field(SimpleNamespace(
            mesh=None, aggregation="weighted_average", weighted_components=lambda: ((), {}))),
         ValueError, "did not produce any weighted contribution"),
        (lambda p: _homogeneous().to_mesh_field(), ValueError, "Homogeneous field requires 'mesh'"),
        (lambda p: _exponential().to_array(shape=(2,), depth=np.nan), ValueError, "only finite"),
        (lambda p: _exponential().to_array(shape=(2,), depth=-1.0), ValueError, "must be >= 0"),
        (lambda p: _exponential().to_array(shape=(2,), depth=np.ones(3)), ValueError, "not broadcastable"),
    ],
    ids=["no-zones", "zone-field-without-values", "no-discretization", "not-a-discretization",
         "other-aggregation", "no-zone", "homogeneous-without-mesh", "depth-not-finite",
         "depth-above-the-ground", "depth-of-another-shape"],
)  # fmt: skip
def test_placement_refusals(call, error, match):
    with pytest.raises(error, match=match):
        call(_per_zone())


@pytest.mark.parametrize("key", ["mesh", "field_discretization"])
def test_homogeneous_on_mesh(key):
    mesh = _square()
    param = _homogeneous(7.25, vertical_profile={"kind": "exponential", "characteristic_depth": 30})
    target = {key: mesh if key == "mesh" else SimpleNamespace(mesh=mesh)}

    at_surface = param.to_mesh_field(**target)
    deep = param.to_mesh_field(**target, depth=np.full(9, 30.0), label="deep")

    assert at_surface.mesh is mesh
    assert at_surface.n_cells == mesh.n_cells == 9
    assert (at_surface.label, deep.label) == ("homogeneous_value", "deep")
    np.testing.assert_allclose(at_surface.cell_values, 7.25)
    np.testing.assert_allclose(deep.cell_values, 7.25 * np.exp(-1.0))


@pytest.mark.parametrize(
    ("param", "match"),
    [(_homogeneous(0.01, identifier="Sy", vertical_profile={"kind": "exponential", "characteristic_depth": 1.0}),
      r"specific yield \(id='Sy'\) in the mesh cells at depth 20.0 m: 9 of 9 value\(s\) outside"),
     (_per_zone({"granite": 1e-12, "micaschists": 1e-5}, vertical_profile={"kind": "exponential", "characteristic_depth": 1.0}),
      r"\(id='K'\) in the mesh cells at depth 20.0 m: [0-9]+ of 9 value\(s\) .* the first at index [0-9]+")],
    ids=["homogeneous-under-its-profile", "zone-under-its-profile"],
)  # fmt: skip
def test_profile_out_of_range(param, match):
    target = two_zone_square().on_mesh(_square()) if param.is_heterogeneous else _square()
    with pytest.raises(PhysicalBoundsError, match=match):
        param.to_mesh_field(target, depth=20.0) if param.is_heterogeneous else param.to_mesh_field(
            mesh=target, depth=20.0
        )


def test_zone_values_area_weighted():
    mesh = _square(20, "triangular_structured")
    field = two_zone_square()
    param = _per_zone()

    discretization = field.on_mesh(mesh)
    values = param.to_mesh_field(discretization, depth=0.0)

    assert isinstance(discretization, WeightedAverageFieldDiscretization)
    assert discretization.aggregation == "weighted_average"
    assert set(discretization.zone_keys) == {"granite", "micaschists"}
    assert discretization.mesh.n_cells == values.n_cells == mesh.n_cells
    fractions = discretization.fractions_by_zone
    np.testing.assert_allclose(np.add(fractions["granite"], fractions["micaschists"]), 1.0)
    assert values.label == "heterogeneous_values"
    assert 2.0 - 1e-12 <= np.min(values.cell_values) <= np.max(values.cell_values) <= 10.0 + 1e-12
    zones = field.zone_id(np.array([[0.25, 0.75]] * 2), np.array([[0.25] * 2, [0.75] * 2]))
    np.testing.assert_allclose(param.to_array(zone_ids=zones), [[10.0, 2.0], [10.0, 10.0]])


def test_missing_zone_refused():
    param = _per_zone({"granite": 1e-5})
    discretization = two_zone_square().on_mesh(_square(20, "triangular_structured"))
    with pytest.raises(ValueError, match=r"'K'.*micaschists.*'field_square'.*values_csv_file"):
        param.to_mesh_field(discretization)
    with pytest.raises(ValueError, match=r"'K'.*micaschists"):
        param.to_array(zone_ids=np.array(["granite", "micaschists"], dtype=object))


@pytest.mark.parametrize(
    "param",
    [_homogeneous(1.0, unit="m/day", vertical_profile={"kind": "exponential", "characteristic_depth": 9.0}),
     _per_zone()],
    ids=["homogeneous", "per-zone"],
)  # fmt: skip
def test_mapping_round_trip(param):
    payload = param.as_dict()
    again = FieldParam.from_dict(payload)

    assert payload["unit"] == again.unit == param.unit
    assert again.value == param.value
    assert again.values_by_key == param.values_by_key
    assert again.vertical_profile == param.vertical_profile
    assert again.field_spatial_id == param.field_spatial_id


@pytest.mark.xfail(strict=True, reason="as_dict writes the SI unit, from_dict loses the user unit")
def test_mapping_keeps_user_unit():
    param = _homogeneous(1.0, unit="m/day")
    assert FieldParam.from_dict(param.as_dict()).original_unit == "m/day"


@pytest.mark.parametrize(
    ("config", "error", "match"),
    [
        (["K"], TypeError, "must be a mapping"),
        ({"kind": "homogeneous"}, KeyError, "'id'"),
        ({"id": "K"}, KeyError, "'kind'"),
        ({"id": "K", "kind": "homogeneous"}, KeyError, "requires key 'value'"),
        ({"id": "K", "kind": "heterogeneous", "values": [1.0]}, KeyError, "mapping key 'values'"),
        ({"id": "K", "kind": "heterogeneous", "values": {"a": 1.0}}, KeyError, "'field_spatial_id'"),
    ],
)  # fmt: skip
def test_mapping_refusals(config, error, match):
    with pytest.raises(error, match=match):
        FieldParam.from_dict(config)
