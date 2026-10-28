"""One field parameter, homogeneous or per zone, in SI, :mod:`hydromodpy.spatial.field.core.field_param`."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

import hydromodpy.spatial.field as field_package
from hydromodpy.spatial.field.cases.square.field_mesh_square import FieldMeshSquare
from hydromodpy.spatial.field.core.field_param import FieldParam
from hydromodpy.spatial.field.core.field_spatial_weighted_discretization import (
    WeightedAverageFieldDiscretization,
)
from tests._helpers.field_cases import two_zone_square

GRANITE_SCHIST = {"granite": 10.0, "micaschists": 2.0}


def _homogeneous(value: object = 10.0, **kwargs) -> FieldParam:
    return FieldParam(
        identifier=kwargs.pop("identifier", "K"), kind="homogeneous", value=value, **kwargs
    )


def _per_zone(values=GRANITE_SCHIST, **kwargs) -> FieldParam:
    return FieldParam(
        identifier="K",
        kind="heterogeneous",
        values_by_key=values,
        field_spatial_id="field_square",
        **kwargs,
    )


def _square(n_cells: int = 12, kind: str = "structured"):
    return FieldMeshSquare.from_unit_square(target_n_cells=n_cells, mesh_kind=kind)


@pytest.mark.parametrize(
    ("identifier", "unit", "value", "si_unit", "si_value"),
    [
        ("K", "m/day", 8.64, "m/s", 1e-4),
        ("K", "mm/day", 8640.0, "m/s", 1e-4),
        ("K", None, "8.64 m/day", "m/s", 1e-4),
        ("Ss", "cm-1", 1e-6, "m-1", 1e-4),
        ("Ss", None, "1e-6 cm-1", "m-1", 1e-4),
        ("Sy", None, "0.2 -", "-", 0.2),
        ("porosity", None, 0.3, "-", 0.3),
    ],
    ids=["k-m-day", "k-mm-day", "k-inline", "ss-cm", "ss-inline", "sy-inline", "unknown-id"],
)
def test_a_value_is_stored_in_the_si_unit_of_its_parameter(
    identifier, unit, value, si_unit, si_value
):
    param = _homogeneous(value, identifier=identifier, unit=unit)

    assert param.unit == si_unit
    assert float(param.value) == pytest.approx(si_value)


def test_per_zone_values_take_their_inline_units_and_the_profile():
    profile = {"mode": "tabulated", "depths": [0.0, 20.0, 40.0], "factors": [1.0, 0.5, 0.25]}
    param = _per_zone(
        {"granite": "10.0 m/day", "micaschists": "2.0 m/day"}, vertical_profile=profile
    )
    zones = np.array(["granite", "micaschists", "granite"], dtype=object)

    np.testing.assert_allclose(
        param.to_array(zone_ids=zones), np.array([10.0, 2.0, 10.0]) / 86400.0
    )
    np.testing.assert_allclose(
        param.to_array(zone_ids=zones, depth=10.0), np.array([7.5, 1.5, 7.5]) / 86400.0
    )


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
        (
            {"kind": "heterogeneous", "values_by_key": {"a": "1 m-1"}, "field_spatial_id": "g"},
            ValueError,
            r"K\.values\[a\] unit 'm-1' is inconsistent",
        ),
    ],
    ids=[
        "no-identifier",
        "unknown-kind",
        "blank-unit",
        "unknown-unit",
        "other-quantity",
        "conflicting-inline-unit",
        "no-value",
        "no-zone-values",
        "empty-zone-values",
        "no-support",
        "zone-value-of-another-quantity",
    ],
)
def test_a_parameter_that_cannot_hold_its_values_is_refused(kwargs, error, match):
    with pytest.raises(error, match=match):
        FieldParam(**({"identifier": "K", "kind": "homogeneous", "value": 1.0} | kwargs))


@pytest.mark.parametrize(
    ("profile", "depths", "factors"),
    [
        (None, [0.0, 50.0], [1.0, 1.0]),
        ({"mode": "none"}, [0.0, 50.0], [1.0, 1.0]),
        ({"mode": "exponential", "characteristic_depth": 20.0}, [0.0, 20.0], [1.0, np.exp(-1.0)]),
        ({"mode": "exponential", "characteristic_depth": "0.02 km"}, [10.0], [np.exp(-0.5)]),
        (
            {"mode": "exponential", "characteristic_depth": 5.0, "min_factor": 0.2},
            [0.0, 1000.0],
            [1.0, 0.2],
        ),
        (
            {"mode": "tabulated", "depths": [0.0, 20.0, 40.0], "factors": [1.0, 0.5, 0.25]},
            [10.0, 30.0, 80.0],
            [0.75, 0.375, 0.25],
        ),
        (
            {"mode": "tabulated", "depths": [0, 10], "factors": [1, 0.5], "interpolation": "step"},
            [0.0, 5.0, 10.0, 20.0],
            [1.0, 1.0, 0.5, 0.5],
        ),
    ],
    ids=["no-profile", "none", "exponential", "depth-in-km", "floor", "tabulated", "step"],
)
def test_a_vertical_profile_scales_the_surface_value_with_depth(profile, depths, factors):
    param = _homogeneous(vertical_profile=profile)

    assert param.has_vertical_variation is (profile is not None and profile["mode"] != "none")
    np.testing.assert_allclose(param.vertical_factor(np.array(depths)), factors)
    np.testing.assert_allclose(
        param.to_array(shape=(len(depths),), depth=np.array(depths)), 10.0 * np.array(factors)
    )
    assert float(param.to_array(depth=depths[-1])) == pytest.approx(10.0 * factors[-1])


def _tabulated(**override) -> dict:
    return {"mode": "tabulated", "depths": [0.0, 10.0], "factors": [1.0, 0.5]} | override


@pytest.mark.parametrize(
    ("profile", "error", "match"),
    [
        (["exponential"], TypeError, "must be a mapping"),
        ({"mode": "linear"}, ValueError, "Unsupported vertical profile mode 'linear'"),
        ({"mode": "exponential"}, KeyError, "requires 'characteristic_depth'"),
        ({"mode": "exponential", "characteristic_depth": None}, ValueError, "cannot be None"),
        ({"mode": "exponential", "characteristic_depth": True}, TypeError, "rejects boolean"),
        ({"mode": "exponential", "characteristic_depth": " "}, ValueError, "empty length string"),
        ({"mode": "exponential", "characteristic_depth": [1]}, TypeError, "unsupported length"),
        ({"mode": "exponential", "characteristic_depth": 0.0}, ValueError, "must be > 0"),
        (
            {"mode": "exponential", "characteristic_depth": 9, "min_factor": "nan"},
            ValueError,
            "finite",
        ),
        (
            {"mode": "exponential", "characteristic_depth": 9, "min_factor": 1.2},
            ValueError,
            r"\[0, 1\]",
        ),
        ({"mode": "tabulated", "factors": [1.0]}, KeyError, "requires 'depths'"),
        ({"mode": "tabulated", "depths": [0.0]}, KeyError, "requires 'factors'"),
        (_tabulated(depths=[], factors=[]), ValueError, "cannot be empty"),
        (_tabulated(depths=[0.0]), ValueError, "same length"),
        (_tabulated(factors=[1.0, np.inf]), ValueError, "must be finite"),
        (_tabulated(depths=[-1.0, 10.0]), ValueError, "must be >= 0"),
        (_tabulated(depths=[0.0, 0.0]), ValueError, "strictly increasing"),
        (_tabulated(depths=[1.0, 10.0]), ValueError, "first depth must be 0.0"),
        (_tabulated(factors=[0.9, 0.5]), ValueError, "factor at depth 0.0 must be 1.0"),
        (_tabulated(interpolation="cubic"), ValueError, "interpolation 'cubic'"),
    ],
)
def test_a_vertical_profile_it_cannot_apply_is_refused(profile, error, match):
    with pytest.raises(error, match=match):
        _homogeneous(vertical_profile=profile)


@pytest.mark.parametrize(
    ("depth", "match"),
    [(np.nan, "only finite"), (-1.0, "must be >= 0"), (np.ones(3), "not broadcastable")],
)
def test_a_depth_outside_the_ground_or_of_another_shape_is_refused(depth, match):
    param = _homogeneous(vertical_profile={"mode": "exponential", "characteristic_depth": 9.0})

    with pytest.raises(ValueError, match=match):
        param.to_array(shape=(2,), depth=depth)


def test_a_homogeneous_value_fills_points_zones_and_shapes():
    param = _homogeneous(4.0)
    x = np.zeros((2, 3))

    np.testing.assert_array_equal(param.to_array(x=x, y=x), np.full((2, 3), 4.0))
    np.testing.assert_array_equal(param.to_array(zone_ids=np.array(["a", "b"])), [4.0, 4.0])
    np.testing.assert_array_equal(param.to_array(shape=(2, 3)), np.full((2, 3), 4.0))
    with pytest.raises(ValueError, match="provide both x and y"):
        param.to_array(x=x)
    with pytest.raises(ValueError, match="same shape"):
        param.to_array(x=x, y=np.zeros(3))


def test_zone_keys_read_as_text_whatever_their_number_type():
    param = _per_zone({"1": 1.0, "1.5": 2.0, "a": 3.0})

    np.testing.assert_array_equal(param.map_zone_ids(np.array([1, 1.0, 1.5])), [1.0, 1.0, 2.0])
    np.testing.assert_array_equal(param.map_zone_ids(np.array([1, 1])), [1.0, 1.0])
    np.testing.assert_array_equal(
        param.to_array(zone_field=SimpleNamespace(cell_values=["a"])), [3.0]
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
        (
            lambda p: p.to_mesh_field(SimpleNamespace(mesh=None, aggregation="max", weighted_components=None)),
            ValueError,
            "Unsupported field discretization aggregation 'max'",
        ),
        (
            lambda p: p.to_mesh_field(
                SimpleNamespace(mesh=None, aggregation="weighted_average", weighted_components=lambda: ((), {}))
            ),
            ValueError,
            "did not produce any weighted contribution",
        ),
        (lambda p: _homogeneous().to_mesh_field(), ValueError, "Homogeneous field requires 'mesh'"),
    ],
    ids=["no-zones", "zone-field-without-values", "no-discretization", "not-a-discretization",
         "other-aggregation", "no-zone", "homogeneous-without-mesh"],
)  # fmt: skip
def test_a_parameter_placed_without_its_zones_or_mesh_is_refused(call, error, match):
    with pytest.raises(error, match=match):
        call(_per_zone())


@pytest.mark.parametrize("through", ["mesh", "discretization"])
def test_a_homogeneous_value_on_a_mesh_takes_its_profile(through):
    mesh = _square()
    param = _homogeneous(
        7.25, vertical_profile={"mode": "exponential", "characteristic_depth": 30.0}
    )
    target = (
        {"mesh": mesh}
        if through == "mesh"
        else {"field_discretization": SimpleNamespace(mesh=mesh)}
    )

    at_surface = param.to_mesh_field(**target)
    deep = param.to_mesh_field(**target, depth=np.full(9, 30.0), label="deep")

    assert at_surface.mesh is mesh
    assert at_surface.n_cells == mesh.n_cells == 9
    assert (at_surface.label, deep.label) == ("homogeneous_value", "deep")
    np.testing.assert_allclose(at_surface.cell_values, 7.25)
    np.testing.assert_allclose(deep.cell_values, 7.25 * np.exp(-1.0))


def test_zone_values_on_a_mesh_are_the_area_weighted_mean_of_the_zones():
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
    zones = field.zone_id(
        np.array([[0.25, 0.75], [0.25, 0.75]]), np.array([[0.25, 0.25], [0.75, 0.75]])
    )
    np.testing.assert_allclose(param.to_array(zone_ids=zones), [[10.0, 2.0], [10.0, 10.0]])


def test_a_value_table_that_misses_a_zone_is_refused():
    """A zone of the support without a row in the table names itself."""
    param = _per_zone({"granite": 1e-5})
    discretization = two_zone_square().on_mesh(_square(20, "triangular_structured"))

    with pytest.raises(ValueError, match=r"'K'.*micaschists.*'field_square'.*values_csv_file"):
        param.to_mesh_field(discretization)
    with pytest.raises(ValueError, match=r"'K'.*micaschists"):
        param.to_array(zone_ids=np.array(["granite", "micaschists"], dtype=object))


@pytest.mark.parametrize(
    "param",
    [
        _homogeneous(
            1.0, unit="m/day", vertical_profile={"mode": "exponential", "characteristic_depth": 9.0}
        ),
        _per_zone(),
    ],
    ids=["homogeneous", "per-zone"],
)
def test_a_parameter_comes_back_from_its_mapping(param):
    payload = param.as_dict()
    again = FieldParam.from_dict(payload)

    assert payload["unit"] == again.unit == param.unit
    assert again.value == param.value
    assert again.values_by_key == param.values_by_key
    assert again.vertical_profile == param.vertical_profile
    assert again.field_spatial_id == param.field_spatial_id


@pytest.mark.xfail(
    strict=True, reason="as_dict writes the SI unit, so from_dict loses the unit the user wrote"
)
def test_a_parameter_from_its_mapping_keeps_the_unit_the_user_wrote():
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
        (
            {"id": "K", "kind": "heterogeneous", "values": {"a": 1.0}},
            KeyError,
            "'field_spatial_id'",
        ),
    ],
)
def test_a_mapping_without_its_keys_is_refused(config, error, match):
    with pytest.raises(error, match=match):
        FieldParam.from_dict(config)


@pytest.mark.parametrize("name", field_package.__all__)
def test_the_package_names_load_on_first_use(name):
    assert getattr(field_package, name).__name__ == name
    with pytest.raises(AttributeError, match="no attribute 'Missing'"):
        _ = field_package.Missing
