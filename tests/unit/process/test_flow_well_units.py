"""Unit tests for flow well-unit conversion during runtime loading."""

from __future__ import annotations

import pytest

from hydromodpy.process.flow.flow import Flow
from hydromodpy.process.flow.flow_config import FlowConfig
from hydromodpy.process.flow.sinks_sources import FlowSinksSourcesConfig


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

    with pytest.raises(ValueError, match="flow.sinks_sources.wells.W1.units must be compatible with m3/s"):
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
    assert well.units == "m3/day"
