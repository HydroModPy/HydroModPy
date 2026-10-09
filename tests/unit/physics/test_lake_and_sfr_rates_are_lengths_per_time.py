"""Lake and SFR rainfall and evaporation are rates in length per time.

MODFLOW 6 reads them as L/T. They used to share the well forcing, whose value
is a volume per time, so '2 mm/day' was refused and a unit could be applied
twice.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import TypeAdapter, ValidationError

from hydromodpy.physics.flow.sinks_sources.rate_forcing import FlowRateForcingConfig
from hydromodpy.physics.flow.sinks_sources.wells import (
    FlowWellConfig,
    FlowWellForcingConfig,
)
from hydromodpy.solver.modflow6.builders._lake_outlets import _forcing_si_per_period
from hydromodpy.solver.modflow6.builders._sfr_period import _emit_network_forcing

TWO_MM_PER_DAY = 2.0e-3 / 86400.0
RATE = TypeAdapter(FlowRateForcingConfig)
VOLUME = TypeAdapter(FlowWellForcingConfig)


def _lake_si(forcing: object, nper: int = 2) -> tuple[float, ...]:
    model = SimpleNamespace(nper=nper, time_grid=None)
    return _forcing_si_per_period(
        model, forcing, volumetric=False, label="flow.sinks_sources.lakes.lac0.rainfall", nper=nper
    )


def test_two_mm_per_day_written_in_the_value_reaches_lak_in_m_per_s() -> None:
    forcing = RATE.validate_python({"kind": "constant", "value": "2 mm/day"})
    assert forcing.value == pytest.approx(TWO_MM_PER_DAY)
    assert forcing.units == "m/s"
    assert _lake_si(forcing) == pytest.approx((TWO_MM_PER_DAY, TWO_MM_PER_DAY))


def test_two_with_units_mm_per_day_reaches_lak_in_m_per_s() -> None:
    forcing = RATE.validate_python({"kind": "constant", "value": 2.0, "units": "mm/day"})
    assert _lake_si(forcing) == pytest.approx((TWO_MM_PER_DAY, TWO_MM_PER_DAY))


def test_two_mm_per_day_reaches_every_sfr_reach_in_m_per_s() -> None:
    forcing = RATE.validate_python({"kind": "constant", "value": "2 mm/day"})
    rows: dict[int, list[list[object]]] = {}
    _emit_network_forcing(
        SimpleNamespace(nper=1, time_grid=None),
        keyword="rainfall",
        forcing=forcing,
        volumetric=False,
        targets={0: 1.0, 1: 1.0},
        location="flow.sinks_sources.sfr.main.rainfall",
        mode="auto",
        min_periods=120,
        nper=1,
        period_rows=rows,
        ts_series=[],
    )
    assert [row[2] for row in rows[0]] == pytest.approx([TWO_MM_PER_DAY, TWO_MM_PER_DAY])


def test_a_volume_per_time_is_refused_as_a_rate() -> None:
    with pytest.raises(ValidationError, match="not a rate per unit of surface"):
        RATE.validate_python(
            {"kind": "seasonal", "units": "m3/s", "by_month": dict.fromkeys(range(1, 13), 1.0)}
        )
    with pytest.raises(ValidationError, match="Cannot convert"):
        RATE.validate_python({"kind": "constant", "value": "2 m**3/s"})


def test_a_unit_written_twice_is_refused() -> None:
    with pytest.raises(ValidationError, match="Write the unit once"):
        RATE.validate_python({"kind": "constant", "value": "2 mm/day", "units": "mm/day"})


def test_piecewise_segments_give_their_unit_to_the_forcing() -> None:
    forcing = RATE.validate_python(
        {
            "kind": "piecewise",
            "segments": [
                {
                    "start": "2020-01-01",
                    "forcing": {"kind": "constant", "value": 2.0, "units": "mm/day"},
                }
            ],
        }
    )
    assert forcing.units == "mm/day"
    with pytest.raises(ValidationError, match="Write units once"):
        RATE.validate_python(
            {
                "kind": "piecewise",
                "units": "m/s",
                "segments": [
                    {
                        "start": "2020-01-01",
                        "forcing": {"kind": "constant", "value": 2.0, "units": "mm/day"},
                    }
                ],
            }
        )


def test_a_well_value_with_its_unit_is_not_scaled_by_the_well_units_again() -> None:
    with pytest.raises(ValidationError, match="Write the unit once"):
        FlowWellConfig(
            location={"kind": "cell", "cell": [0, 1, 1]},
            units="m3/day",
            forcing={"kind": "constant", "value": "100 m**3/day"},
        )
    well = FlowWellConfig(
        location={"kind": "cell", "cell": [0, 1, 1]},
        forcing={"kind": "constant", "value": "86.4 m**3/day"},
    )
    assert well.forcing.units == "m3/s"
    assert float(well.forcing.value.to("m**3/s").magnitude) == pytest.approx(1.0e-3)


def test_lake_runoff_inflow_and_withdrawal_stay_volumes_per_time() -> None:
    forcing = VOLUME.validate_python({"kind": "constant", "value": 0.01, "units": "m3/s"})
    model = SimpleNamespace(nper=1, time_grid=None)
    assert _forcing_si_per_period(
        model, forcing, volumetric=True, label="withdrawal", nper=1
    ) == pytest.approx((0.01,))
