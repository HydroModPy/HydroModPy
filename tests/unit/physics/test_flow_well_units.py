"""Unit tests for flow well-unit conversion during runtime loading."""

from __future__ import annotations

import pytest

from hydromodpy.physics.flow.flow import Flow
from hydromodpy.physics.flow.flow_config import FlowConfig
from hydromodpy.physics.flow.sinks_sources import FlowSinksSourcesConfig


def test_flow_converts_well_flux_scalar_from_m3_day_to_m3_s() -> None:
    cfg = FlowConfig(
        sinks_sources=FlowSinksSourcesConfig(
            wells={
                "W1": {
                    "cell": [0, 0, 0],
                    "flux": -86400.0,
                    "units": "m3/day",
                }
            }
        )
    )

    flow = Flow(cfg)
    well = flow.sinks_sources["wells"]["W1"]

    assert well.units == "m3/s"
    assert well.flux == pytest.approx(-1.0)


def test_flow_converts_well_flux_list_from_m3_day_to_m3_s() -> None:
    cfg = FlowConfig(
        sinks_sources=FlowSinksSourcesConfig(
            wells={
                "W1": {
                    "cell": [0, 0, 0],
                    "flux": [-86400.0, -43200.0],
                    "units": "m3/day",
                }
            }
        )
    )

    flow = Flow(cfg)
    well = flow.sinks_sources["wells"]["W1"]

    assert well.units == "m3/s"
    assert isinstance(well.flux, list)
    assert well.flux[0] == pytest.approx(-1.0)
    assert well.flux[1] == pytest.approx(-0.5)


def test_flow_rejects_unsupported_well_units() -> None:
    cfg = FlowConfig(
        sinks_sources=FlowSinksSourcesConfig(
            wells={
                "W1": {
                    "cell": [0, 0, 0],
                    "flux": -100.0,
                    "units": "foo/day",
                }
            }
        )
    )

    with pytest.raises(
        ValueError, match="flow.sinks_sources.wells.W1.units must be compatible with m3/s"
    ):
        _ = Flow(cfg)


def test_flow_accepts_well_forcing_without_flux() -> None:
    cfg = FlowConfig(
        sinks_sources=FlowSinksSourcesConfig(
            wells={
                "W1": {
                    "cell": [0, 0, 0],
                    "units": "m3/day",
                    "forcing": {"mode": "constant", "value": -100.0},
                }
            }
        )
    )

    flow = Flow(cfg)
    well = flow.sinks_sources["wells"]["W1"]

    assert well.flux is None
    assert well.forcing is not None
    assert well.units == "m3/s"
    assert well.forcing.units == "m3/day"


def test_flow_converts_recharge_scalar_from_mm_day_to_m_s() -> None:
    cfg = FlowConfig(
        sinks_sources=FlowSinksSourcesConfig(
            recharge={
                "values": 3.0,
                "units": "mm/day",
            }
        )
    )

    flow = Flow(cfg)
    recharge = flow.sinks_sources["recharge"]

    assert recharge is not None
    assert recharge.units == "m/s"
    assert recharge.values == pytest.approx(3.0e-3 / 86400.0)


def test_flow_converts_recharge_mapping_from_mm_day_to_m_s() -> None:
    cfg = FlowConfig(
        sinks_sources=FlowSinksSourcesConfig(
            recharge={
                "values": {0: 3.0, 1: 6.0},
                "units": "mm/day",
            }
        )
    )

    flow = Flow(cfg)
    recharge = flow.sinks_sources["recharge"]

    assert recharge is not None
    assert recharge.units == "m/s"
    assert recharge.values == {
        0: pytest.approx(3.0e-3 / 86400.0),
        1: pytest.approx(6.0e-3 / 86400.0),
    }
