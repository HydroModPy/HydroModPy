"""Lake and SFR rainfall and evaporation reach the MODFLOW 6 builders in metres per second."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import TypeAdapter

from hydromodpy.model.forcing.dated_forcing import SurfaceRateForcing
from hydromodpy.model.model import ModelTime, steady_variant
from hydromodpy.solver.modflow6.builders._lake_outlets import _forcing_si_per_period
from hydromodpy.solver.modflow6.builders._sfr_period import _emit_network_forcing
from tests._helpers.model_factory import make_model

# Lake and SFR rainfall and evaporation are rates in length per time.
#
# MODFLOW 6 reads them as L/T. They used to share the well forcing, whose value
# is a volume per time, so '2 mm/day' was refused and a unit could be applied
# twice.

TWO_MM_PER_DAY = 2.0e-3 / 86400.0

RATE = TypeAdapter(SurfaceRateForcing)


def _lake_si(forcing: object, nper: int = 2) -> tuple[float, ...]:
    model = SimpleNamespace(nper=nper, inputs=make_model())
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
        SimpleNamespace(nper=1, inputs=make_model()),
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


def test_steady_variant_has_one_period_lake_forcings() -> None:
    model = make_model(
        lakes={"l": {"runoff": {"kind": "values", "values": [0.0] * 51 + [52.0]}}},
        time=ModelTime(
            grid=SimpleNamespace(period_lengths_seconds=np.full(52, 7 * 86400.0)),
            regime="transient",
            first_period_steady=True,
        ),
    )

    steady = steady_variant(model)

    assert steady.lakes["l"]["runoff"]["values"] == [pytest.approx(1.0)]
    assert model.lakes["l"]["runoff"]["values"] == [0.0] * 51 + [52.0]
