"""The shared pint registry and the pint-typed fields built on it (conductivity m/s, storage 1/m)."""

from __future__ import annotations

import tomllib

import pytest
from pydantic import BaseModel, ConfigDict

from hydromodpy.core.units.registry import UREG, get_registry
from hydromodpy.core.units.types import HydraulicConductivity, SpecificStorage, SpecificYield
from hydromodpy.model.properties.physical_properties import FlowPhysicalProperties

M_PER_S = UREG.Unit("m/s")
PER_M = UREG.Unit("1/m")


class Aquifer(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    k: HydraulicConductivity
    sy: SpecificYield
    ss: SpecificStorage


def test_the_registry_is_one_object():
    assert get_registry() is get_registry()
    assert UREG is get_registry()


# (quantity, unit, unit to convert to, expected magnitude)
CONVERSIONS = [
    pytest.param(1.0, "m/s", "m/h", 3600.0, id="m/s to m/h"),
    pytest.param(1.0, "m/s", "m/s", 1.0, id="identity"),
    pytest.param(1.0, "m**3/s", "m**3/day", 86400.0, id="flow, 86400 s per day"),
    pytest.param(1e-5, "1/m", "1/cm", 1e-7, id="storage through 1/cm"),
    pytest.param(50.0, "percent", "dimensionless", 0.5, id="percent is 1e-2"),
    pytest.param(10.0, "degC", "degC", 10.0, id="temperature"),
    pytest.param(1e-3, "Pa*s", "Pa*s", 1e-3, id="viscosity"),
]


@pytest.mark.parametrize(("value", "unit", "target", "expected"), CONVERSIONS)
def test_conversions(value, unit, target, expected):
    assert UREG.Quantity(value, unit).to(target).magnitude == pytest.approx(expected)


@pytest.mark.parametrize("unit", ["m/s", "m/day", "cm/s", "mm/day", "m/h"])
def test_conductivity_units_convert_to_m_per_s(unit):
    assert UREG.Quantity(1.0, unit).to("m/s").dimensionality == M_PER_S.dimensionality


def test_a_bare_number_is_read_in_the_canonical_unit():
    model = Aquifer(k=1e-4, sy=0.1, ss=1e-5)
    assert model.k.to(M_PER_S).magnitude == pytest.approx(1e-4)
    assert model.ss.to(PER_M).magnitude == pytest.approx(1e-5)
    assert model.sy == pytest.approx(0.1)


def test_a_unit_string_is_converted_to_the_canonical_unit():
    model = Aquifer(k="0.36 m/h", sy=0.15, ss="1e-3 1/m")  # 0.36 m/h = 1e-4 m/s
    assert model.k.to(M_PER_S).magnitude == pytest.approx(1e-4)
    assert model.ss.to(PER_M).magnitude == pytest.approx(1e-3)


def test_a_boolean_is_refused():
    with pytest.raises(Exception):
        Aquifer(k=True, sy=0.1, ss=1e-5)


def test_a_toml_snippet_round_trips_through_a_dump():
    raw = tomllib.loads('k = "1e-4 m/s"\nsy = 0.12\nss = "1e-5 1/m"\n')
    model = Aquifer(**raw)
    again = Aquifer(**model.model_dump(mode="json"))
    assert again.k.to(M_PER_S).magnitude == pytest.approx(model.k.to(M_PER_S).magnitude)
    assert again.sy == pytest.approx(model.sy)
    assert again.ss.to(PER_M).magnitude == pytest.approx(model.ss.to(PER_M).magnitude)


def test_flow_properties_defaults_and_overrides():
    assert FlowPhysicalProperties().k_aquifer.to(M_PER_S).magnitude == pytest.approx(1e-4)

    bare = FlowPhysicalProperties(k_aquifer=2e-5, specific_yield=0.2)
    assert bare.k_aquifer.to(M_PER_S).magnitude == pytest.approx(2e-5)
    assert bare.specific_yield == pytest.approx(0.2)

    with_unit = FlowPhysicalProperties(k_aquifer="3.6 m/h")
    assert with_unit.k_aquifer.to(M_PER_S).magnitude == pytest.approx(1e-3)
