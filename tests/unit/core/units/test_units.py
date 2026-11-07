from __future__ import annotations

import tomllib

import pydantic_pint
import pytest

# Unit tests for the shared pint registry.


def test_get_registry_is_singleton():
    from hydromodpy.core.units.registry import get_registry

    assert get_registry() is get_registry()


def test_ureg_matches_accessor():
    from hydromodpy.core.units.registry import UREG, get_registry

    assert UREG is get_registry()


def test_basic_si_units_round_trip():
    from hydromodpy.core.units.registry import UREG

    q = UREG.Quantity(1.0, "m/s")
    assert q.to("m/h").magnitude == pytest.approx(3600.0)
    assert q.to("m/s").magnitude == pytest.approx(1.0)


def test_hydraulic_conductivity_units_supported():
    """Units we care about for hydrogeology must be parseable."""
    from hydromodpy.core.units.registry import UREG

    for unit in ("m/s", "m/day", "cm/s", "mm/day", "m/h"):
        q = UREG.Quantity(1.0, unit)
        # Each must be convertible to m/s.
        assert q.to("m/s").dimensionality == UREG.Unit("m/s").dimensionality


def test_dimensionless_and_percent_defined():
    from hydromodpy.core.units.registry import UREG

    assert UREG.Quantity(1.0, "dimensionless").magnitude == 1.0
    # The registry registers "percent" as 1e-2.
    assert UREG.Quantity(50.0, "percent").to("dimensionless").magnitude == pytest.approx(0.5)


def test_flow_rate_and_storage_units():
    from hydromodpy.core.units.registry import UREG

    q_flow = UREG.Quantity(1.0, "m**3/s")
    assert q_flow.to("m**3/day").magnitude == pytest.approx(86400.0)

    q_store = UREG.Quantity(1e-5, "1/m")
    # conversion through cm^-1 sanity check
    assert q_store.to("1/cm").magnitude == pytest.approx(1e-7)


def test_temperature_and_viscosity_supported():
    from hydromodpy.core.units.registry import UREG

    # Pint models degC as an offset unit; simple conversion is fine here.
    q_t = UREG.Quantity(10.0, "degC")
    assert q_t.to("degC").magnitude == pytest.approx(10.0)
    q_mu = UREG.Quantity(1e-3, "Pa*s")
    assert q_mu.to("Pa*s").magnitude == pytest.approx(1e-3)


# Round-trip tests for pint-annotated Pydantic types.
#
# Verify that constructing a Pydantic model from a TOML-like payload, dumping
# it, and reloading the dump yields the same quantities.


def _build_model():
    from pydantic import BaseModel, ConfigDict

    from hydromodpy.core.units import (
        HydraulicConductivity,
        SpecificStorage,
        SpecificYield,
    )

    class Aquifer(BaseModel):
        model_config = ConfigDict(arbitrary_types_allowed=True)
        k: HydraulicConductivity
        sy: SpecificYield
        ss: SpecificStorage

    return Aquifer


def test_bare_number_falls_back_to_canonical_unit():
    from hydromodpy.core.units.registry import UREG

    Aquifer = _build_model()
    m = Aquifer(k=1e-4, sy=0.1, ss=1e-5)
    assert m.k.to(UREG.Unit("m/s")).magnitude == pytest.approx(1e-4)
    assert m.ss.to(UREG.Unit("1/m")).magnitude == pytest.approx(1e-5)
    assert m.sy == pytest.approx(0.1)


def test_explicit_unit_string_is_converted_to_canonical():
    from hydromodpy.core.units.registry import UREG

    Aquifer = _build_model()
    m = Aquifer(k="0.36 m/h", sy=0.15, ss="1e-3 1/m")
    # 0.36 m/h = 0.0001 m/s
    assert m.k.to(UREG.Unit("m/s")).magnitude == pytest.approx(1e-4)
    assert m.ss.to(UREG.Unit("1/m")).magnitude == pytest.approx(1e-3)


def test_bool_is_rejected():
    Aquifer = _build_model()
    with pytest.raises(Exception):
        Aquifer(k=True, sy=0.1, ss=1e-5)


def test_specific_yield_range():
    Aquifer = _build_model()
    with pytest.raises(Exception):
        Aquifer(k=1e-4, sy=1.5, ss=1e-5)  # > 1
    with pytest.raises(Exception):
        Aquifer(k=1e-4, sy=-0.1, ss=1e-5)  # < 0


def test_toml_like_round_trip_through_string():
    """Load a TOML snippet, build the model, dump, reload, check invariants."""
    from hydromodpy.core.units.registry import UREG

    toml_text = 'k = "1e-4 m/s"\nsy = 0.12\nss = "1e-5 1/m"\n'
    raw = tomllib.loads(toml_text)
    Aquifer = _build_model()
    m = Aquifer(**raw)
    # Dump in JSON-compatible mode; pint emits a string/dict form pydantic-pint
    # can consume back.
    dumped = m.model_dump(mode="json")
    m2 = Aquifer(**dumped)
    assert m2.k.to(UREG.Unit("m/s")).magnitude == pytest.approx(m.k.to(UREG.Unit("m/s")).magnitude)
    assert m2.sy == pytest.approx(m.sy)
    assert m2.ss.to(UREG.Unit("1/m")).magnitude == pytest.approx(
        m.ss.to(UREG.Unit("1/m")).magnitude
    )


def test_flow_physical_properties_defaults_and_overrides():
    from hydromodpy.core.units.registry import UREG
    from hydromodpy.model.properties.physical_properties import FlowPhysicalProperties

    # defaults are valid
    props = FlowPhysicalProperties()
    assert props.k_aquifer.to(UREG.Unit("m/s")).magnitude == pytest.approx(1e-4)

    # bare number falls back to m/s
    props2 = FlowPhysicalProperties(k_aquifer=2e-5, specific_yield=0.2)
    assert props2.k_aquifer.to(UREG.Unit("m/s")).magnitude == pytest.approx(2e-5)
    assert props2.specific_yield == pytest.approx(0.2)

    # explicit unit converts
    props3 = FlowPhysicalProperties(k_aquifer="3.6 m/h")
    assert props3.k_aquifer.to(UREG.Unit("m/s")).magnitude == pytest.approx(1e-3)
