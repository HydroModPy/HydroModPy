"""Unit-aware config types: a unit written by the user lands in SI (m, m/s, 1/m), errors name the problem.

First the float types on a demo model, then pint quantity types, then the length fields of
real configs, where a bare number is metres and "0.2 km" is 200 m.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from hydromodpy.catchment.algorithms.river_network_config import RiverNetworkConfig
from hydromodpy.catchment.preprocess.catchment_config import OutletCatchDef, TxtCatchDef
from hydromodpy.catchment.synthetic.synthetic_config import (
    RadialIslandTopography,
    SyntheticGridConfig,
)
from hydromodpy.core.units.registry import UREG
from hydromodpy.core.units.types import (
    AreaSquareMeters,
    DurationDays,
    DurationSeconds,
    FluxDensityMPerS,
    HydraulicConductivity,
    HydraulicConductivityMPerS,
    Length,
    LengthMeters,
    LengthMillimeters,
    SpecificYield,
    VolumetricFlowM3PerSecond,
)
from hydromodpy.model.domain.depth_model_config import ConstantThicknessDepthModel
from hydromodpy.model.domain.spatial_support_config import GeneratedRingsSupportConfig
from hydromodpy.solver.modflow_nwt.nwt.nwt_config import ModflowProcessSpecificConfig


class _Floats(BaseModel):
    length: LengthMeters | None = None
    mm: LengthMillimeters | None = None
    area: AreaSquareMeters | None = None
    flow: VolumetricFlowM3PerSecond | None = None
    seconds: DurationSeconds | None = None
    days: DurationDays | None = None
    k: HydraulicConductivityMPerS | None = None
    recharge: FluxDensityMPerS | None = None


@pytest.mark.parametrize(
    ("field", "given", "expected"),
    [
        ("length", 50, 50.0),
        ("length", "1 km", 1000.0),
        ("length", "250 cm", 2.5),
        ("length", " 3 m ", 3.0),
        ("length", {"value": 2, "unit": "km"}, 2000.0),
        ("length", {"value": 7}, 7.0),  # no unit: the canonical one
        ("mm", "12 cm", 120.0),
        ("mm", 120, 120.0),
        ("area", "2 km**2", 2.0e6),
        ("flow", "1 m**3/h", 1 / 3600),
        ("seconds", "1 day", 86400.0),
        ("days", "1 week", 7.0),
        ("k", "0.36 m/h", 1.0e-4),
        ("recharge", "86.4 mm/day", 1.0e-6),
        ("recharge", UREG.Quantity(1.0, "mm/day"), 1.0e-3 / 86400),
    ],
)
def test_stored_in_canonical_unit(field, given, expected):
    assert getattr(_Floats(**{field: given}), field) == pytest.approx(expected)


def test_an_absent_value_is_none():
    assert _Floats(length=None).length is None


@pytest.mark.parametrize(
    ("field", "given", "match"),
    [
        ("length", "50", "dimensionless"),  # a string needs its unit
        ("length", "", "empty string"),
        ("length", "   ", "empty string"),
        ("length", "3 s", "dimension|convert|Cannot"),
        ("length", "banana", "banana|not defined|Cannot"),
        ("length", UREG.Quantity(1.0, "kg"), "dimension|convert|Cannot"),
        ("length", {"value": 1, "unit": "bogus_unit"}, "bogus_unit|not defined"),
        ("length", {"value": 1, "unit": "s"}, "dimension|convert|Cannot"),
        ("k", "1 m", "dimension|convert|Cannot"),
    ],
)
def test_refusals(field, given, match):
    with pytest.raises(ValidationError, match=match):
        _Floats(**{field: given})


@pytest.mark.parametrize(
    "given", [True, {"unit": "km"}, [1, 2]], ids=["boolean", "mapping-without-value", "list"]
)
def test_unreadable_value_refused(given):
    # Pydantic only wraps ValueError, so a TypeError would reach the caller raw.
    with pytest.raises(ValidationError, match="boolean|unsupported value"):
        _Floats(length=given)


class _Quantities(BaseModel):
    length: Length | None = None
    k: HydraulicConductivity | None = None
    sy: SpecificYield = 0.1


def test_a_quantity_converts_on_demand():
    model = _Quantities(length="100 cm", k="0.36 m/h")
    assert model.length.to("m").magnitude == pytest.approx(1.0)
    assert model.k.to("m/s").magnitude == pytest.approx(1.0e-4)


def test_bare_quantity_is_canonical():
    assert _Quantities(length=2.5).length.to("m").magnitude == pytest.approx(2.5)


def test_a_boolean_is_not_one_metre():
    with pytest.raises(ValidationError, match="boolean"):
        _Quantities(length=True)


def test_quantity_round_trip():
    model = _Quantities(length="2 km", k="36 m/h")
    dumped = model.model_dump()
    assert dumped["length"] == pytest.approx(2000.0)
    assert dumped["k"] == pytest.approx(1.0e-2)
    again = _Quantities(**dumped)
    assert again.length.to("m").magnitude == pytest.approx(2000.0)
    assert again.k.to("m/s").magnitude == pytest.approx(1.0e-2)
    assert _Quantities().model_dump()["length"] is None


def test_bare_default_dumps_float():
    class _Defaulted(BaseModel):
        length: Length = 3.0

    assert _Defaulted().model_dump() == {"length": 3.0}


@pytest.mark.parametrize("value", [-0.01, 1.01])
def test_specific_yield_bounds(value):
    with pytest.raises(ValidationError):
        _Quantities(sy=value)


class DemoLength(BaseModel):
    length: LengthMeters


OUTLET = {"kind": "from_outlet_coord", "x_outlet": 0.0, "y_outlet": 0.0, "buff_area": 10.0}
RADIAL_ISLAND = {"kind": "radial_island", "base_elevation": -1.0, "crest_elevation": 10.0}
RINGS = {
    "kind": "generated_rings",
    "coordinate_mode": "absolute",
    "labels": ["inner", "mid", "outer"],
}
GRID = {"nx": 10, "ny": 10}
NO_RIVERS = {"enabled": False}

# (config class, arguments, expected values in metres)
LENGTH_FIELDS = [
    pytest.param(
        ConstantThicknessDepthModel,
        {"thickness": 200.0},
        {"thickness": 200.0},
        id="thickness, bare",
    ),
    pytest.param(
        ConstantThicknessDepthModel, {"thickness": "200 m"}, {"thickness": 200.0}, id="thickness, m"
    ),
    pytest.param(
        ConstantThicknessDepthModel,
        {"thickness": "0.2 km"},
        {"thickness": 200.0},
        id="thickness, km",
    ),
    pytest.param(
        ConstantThicknessDepthModel,
        {"thickness": "20000 cm"},
        {"thickness": 200.0},
        id="thickness, cm",
    ),
    pytest.param(ModflowProcessSpecificConfig, {}, {"exdp": 1.0}, id="extinction depth, default"),
    pytest.param(
        ModflowProcessSpecificConfig, {"exdp": "50 cm"}, {"exdp": 0.5}, id="extinction depth, cm"
    ),
    pytest.param(
        RiverNetworkConfig, NO_RIVERS, {"min_stream_length_m": 0.0}, id="min stream length, zero"
    ),
    pytest.param(
        RiverNetworkConfig,
        NO_RIVERS | {"min_stream_length_m": "0.5 km"},
        {"min_stream_length_m": 500.0},
        id="min stream length, km",
    ),
    pytest.param(
        SyntheticGridConfig,
        GRID | {"length_x": 100.0, "length_y": 100.0},
        {"length_x": 100.0, "length_y": 100.0},
        id="grid, bare",
    ),
    pytest.param(
        SyntheticGridConfig,
        GRID | {"length_x": "0.5 km", "length_y": "0.5 km"},
        {"length_x": 500.0, "length_y": 500.0},
        id="grid, km",
    ),
    pytest.param(
        OutletCatchDef, OUTLET | {"snap_dist": 50}, {"snap_dist": 50.0}, id="snap distance, bare"
    ),
    pytest.param(
        OutletCatchDef,
        OUTLET | {"snap_dist": "0.05 km"},
        {"snap_dist": 50.0},
        id="snap distance, km",
    ),
    pytest.param(
        TxtCatchDef, {"kind": "txt", "cell_size": "0.025 km"}, {"cell_size": 25.0}, id="cell size"
    ),
    pytest.param(
        RadialIslandTopography,
        RADIAL_ISLAND | {"island_radius": "500 m", "center_x": "1 km", "center_y": 200},
        {"island_radius": 500.0, "center_x": 1000.0, "center_y": 200.0},
        id="radial island centre",
    ),
    pytest.param(
        GeneratedRingsSupportConfig,
        RINGS | {"radii": ["50 m", "200 m"], "center_x": "1 km", "center_y": 100},
        {"radii": [50.0, 200.0], "center_x": 1000.0, "center_y": 100.0},
        id="rings centre",
    ),
    pytest.param(DemoLength, {"length": "100 m"}, {"length": 100.0}, id="direct, m"),
    pytest.param(DemoLength, {"length": "1 km"}, {"length": 1000.0}, id="direct, km"),
    pytest.param(DemoLength, {"length": "200 cm"}, {"length": 2.0}, id="direct, cm"),
]


@pytest.mark.parametrize(("config", "arguments", "expected"), LENGTH_FIELDS)
@pytest.mark.fast
def test_length_field_parses(config, arguments, expected):
    built = config(**arguments)
    for name, value in expected.items():
        assert getattr(built, name) == pytest.approx(value)


# (config class, arguments that a length field must refuse)
LENGTH_REFUSED = [
    pytest.param(
        ConstantThicknessDepthModel, {"thickness": "10 kg"}, id="thickness, wrong dimension"
    ),
    pytest.param(ConstantThicknessDepthModel, {"thickness": 0.0}, id="thickness, not positive"),
    pytest.param(
        ModflowProcessSpecificConfig, {"exdp": "5 hour"}, id="extinction depth, wrong dimension"
    ),
    pytest.param(
        RiverNetworkConfig,
        NO_RIVERS | {"min_stream_length_m": "-1 m"},
        id="min stream length, negative",
    ),
    pytest.param(
        SyntheticGridConfig,
        {"length_x": "5 hour", "length_y": "1 m", "nx": 10, "ny": 1},
        id="grid, wrong dimension",
    ),
    pytest.param(DemoLength, {"length": "5 kg"}, id="direct, wrong dimension"),
]


@pytest.mark.parametrize(("config", "arguments"), LENGTH_REFUSED)
@pytest.mark.fast
def test_length_field_refusals(config, arguments):
    with pytest.raises(ValidationError):
        config(**arguments)


@pytest.mark.fast
def test_the_legacy_length_parser_is_gone():
    import hydromodpy.core.units as units_package

    assert not hasattr(units_package, "parse_length_to_m")
