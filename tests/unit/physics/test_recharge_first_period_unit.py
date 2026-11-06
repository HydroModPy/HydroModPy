"""The first-period recharge override must be read in the unit it was written in.

``[flow.sinks_sources.recharge]`` declares one ``units`` for its payload, and the
flow runtime converts ``values`` to m/s on the way in. ``first_clim`` accepts the
same three shapes as a payload entry, including a bare number, and that number
was carried through untouched: a model written in ``mm/day`` and overriding its
first period with ``2`` started on 2 m/s, eight orders of magnitude out, with
nothing said.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.physics.flow.binders.climate import apply_recharge_load_result_to_flow
from hydromodpy.physics.flow.flow import Flow
from hydromodpy.physics.flow.sinks_sources.recharge import FlowRechargeConfig, recharge_factor_of
from hydromodpy.physics.hydrology.soil_reservoir.config import SoilReservoirConfig
from tests.unit.workflow.steps.prepare_solver.test_forcings import _runoff_field_record

_MM_PER_DAY_IN_M_PER_S = 1e-3 / 86400.0


def _normalized(recharge: FlowRechargeConfig) -> FlowRechargeConfig:
    return Flow._normalize_recharge_config(recharge, location_prefix="flow.sinks_sources.recharge")


def test_a_numeric_first_period_follows_the_payload_unit() -> None:
    normalized = _normalized(FlowRechargeConfig(values=[1.0, 2.0], first_clim=2.0, units="mm/day"))

    assert normalized.units == "m/s"
    assert normalized.first_clim == pytest.approx(2.0 * _MM_PER_DAY_IN_M_PER_S)


def test_a_keyword_first_period_is_left_alone() -> None:
    normalized = _normalized(
        FlowRechargeConfig(values=[1.0, 2.0], first_clim="mean", units="mm/day")
    )

    assert normalized.first_clim == "mean"


def test_a_payload_already_in_si_is_unchanged() -> None:
    normalized = _normalized(
        FlowRechargeConfig(values=[1e-8, 2e-8], first_clim=1.5e-8, units="m/s")
    )

    assert normalized.first_clim == pytest.approx(1.5e-8)


# The factor on the recharge in force, from `values` and from `[data.recharge]`.
_DAYS = pd.date_range("2000-01-01", periods=2)
_RATES = [0.1, 1.0 / 3.0]


def _station() -> LoadResult:
    record = PointRecord(
        station_id="a",
        variable="recharge",
        source="sim2",
        unit="mm/day",
        frequency="D",
        data=pd.DataFrame({"datetime": _DAYS, "value": _RATES}),
        date_start=_DAYS[0].to_pydatetime(),
        date_end=_DAYS[1].to_pydatetime(),
    )
    return LoadResult(points=[record])


def _grid() -> LoadResult:
    frames = np.asarray(_RATES).reshape(2, 1, 1)
    record = _runoff_field_record(np.tile(frames, (1, 2, 2)), _DAYS, variable="recharge")
    record.data.attrs["crs"] = "EPSG:2154"
    return LoadResult(fields=[record])


def _bound(source: LoadResult, factor: float) -> FlowRechargeConfig:
    """Bind a source to a flow that declares ``factor``, and normalize as the flow does."""
    seen: list[FlowRechargeConfig] = []
    recharge = FlowRechargeConfig(factor=factor)
    flow = SimpleNamespace(
        active_sinks_sources=["recharge"],
        sinks_sources={},
        config=SimpleNamespace(sinks_sources=SimpleNamespace(recharge=recharge)),
        set_recharge=lambda config: seen.append(_normalized(config)),
    )
    assert apply_recharge_load_result_to_flow(flow=flow, recharge_result=source)
    return seen[0]


@pytest.mark.parametrize(
    ("values", "scaled"),
    [(1.0, 2.0), ([1.0, 2.0], [2.0, 4.0]), ({0: 1.0, 1: -2.0}, {0: 2.0, 1: -4.0})],
)
def test_the_factor_multiplies_written_rates_once(values, scaled) -> None:
    once = _normalized(FlowRechargeConfig(values=values, factor=2.0, first_clim=3.0, units="m/s"))

    assert (once.values, once.first_clim, once.factor) == (scaled, 6.0, 1.0)
    assert _normalized(once).values == scaled


def test_the_factor_multiplies_a_loaded_source_and_leaves_it_alone() -> None:
    station, grid = _station(), _grid()

    series = _bound(station, 2.0).values
    scaled = _bound(grid, 2.0).heterogeneous_source.fields[0].dataset

    assert series.tolist() == pytest.approx([2.0 * r * _MM_PER_DAY_IN_M_PER_S for r in _RATES])
    assert station.points[0].data["value"].tolist() == _RATES
    assert scaled["recharge"].values[:, 0, 0].tolist() == [0.2, 2.0 / 3.0]
    assert scaled.attrs == {"crs": "EPSG:2154"}
    assert grid.fields[0].dataset["recharge"].values[:, 0, 0].tolist() == _RATES


def test_a_factor_of_one_moves_no_number_on_any_route() -> None:
    rates = {"values": _RATES, "first_clim": 0.7, "units": "mm/day"}
    plain = _normalized(FlowRechargeConfig(**rates))
    unit = _normalized(FlowRechargeConfig(**rates, factor=1.0))
    assert (plain.values, plain.first_clim) == (unit.values, unit.first_clim)

    station = _normalized(FlowRechargeConfig(values=_RATES, units="mm/day")).values
    assert np.asarray(_bound(_station(), 1.0).values).tolist() == station
    grid = _grid()
    assert _bound(grid, 1.0).heterogeneous_source is grid


@pytest.mark.parametrize(
    ("written", "said"),
    [
        ({"factor": 0.0}, "greater than 0"),
        ({"factor": 2.0, "soil": SoilReservoirConfig(ru=100.0)}, "no rate to multiply"),
    ],
)
def test_what_the_factor_refuses(written, said) -> None:
    with pytest.raises(ValidationError, match=said):
        FlowRechargeConfig(**written)


@pytest.mark.parametrize(
    ("written", "peak"),
    [
        ({"factor": 3.0, "values": 2.0}, 6.0),
        ({"factor": 2.0, "values": {0: 1e-8, 1: -3e-8}, "units": "m/s"}, 6e-8 * 86400e3),
    ],
)
def test_the_peak_rate_counts_the_factor_and_the_unit(written, peak) -> None:
    assert FlowRechargeConfig(**written).peak_rate_mm_day() == pytest.approx(peak)


@pytest.mark.parametrize(
    ("flow_config", "factor"),
    [
        (
            SimpleNamespace(sinks_sources=SimpleNamespace(recharge=FlowRechargeConfig(factor=2.5))),
            2.5,
        ),
        (SimpleNamespace(sinks_sources=SimpleNamespace(recharge=None)), 1.0),
        (SimpleNamespace(sinks_sources=None), 1.0),
        (SimpleNamespace(), 1.0),
    ],
)
def test_the_factor_of_a_flow_config_defaults_to_one(flow_config, factor) -> None:
    assert recharge_factor_of(flow_config) == factor
