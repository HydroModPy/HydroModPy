"""Unit tests for the shared pint registry."""

from __future__ import annotations

import pytest


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
