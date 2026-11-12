"""Lake outlets and per-period lake forcings as MODFLOW 6 LAK reads them, in SI units.

Outlet kinds and destinations are 1-based in the config and 0-based in the package, with -1
for the outside of the model. Forcings are m3/s. A managed transfer (inflow, withdrawal)
is held at zero through a steady spin-up. A SPECIFIED outlet gets its rate from PERIOD rows.
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest
from pydantic import TypeAdapter

from hydromodpy.core.time.window import ResolvedSimulationTimeWindow
from hydromodpy.model.forcing.dated_forcing import VolumeRateForcing
from hydromodpy.model.model import ModelTime
from hydromodpy.solver.modflow6.builders._lake_outlets import (
    _downstream_spillway_ref,
    _emit_forcing_rows,
    _emit_outlet_rate_rows,
    _forcing_si_per_period,
    _lake_id_for_index,
    _outlet_couttype,
    _outlet_geometry,
    _resolve_lakeout,
    _resolve_receiver_lake,
)
from tests._helpers.model_factory import make_model

# Three daily periods, all in January.
WINDOW = ResolvedSimulationTimeWindow(
    start=pd.Timestamp("2000-01-01"),
    end=pd.Timestamp("2000-01-03"),
    step_value=1,
    step_unit="day",
    coverage_policy="ignore",
)
SEASONAL = TypeAdapter(VolumeRateForcing)
WINTER_ONLY = {"DJF": 2.0, "MAM": 9.0, "JJA": 9.0, "SON": 9.0}


def dated_model(steady: tuple[bool, ...] = ()) -> SimpleNamespace:
    time = ModelTime(
        grid=SimpleNamespace(window=WINDOW), regime="transient", first_period_steady=False
    )
    return SimpleNamespace(
        inputs=make_model(time=time), steady=steady, nper=3, perlen=[86400.0] * 3
    )


def test_seasonal_forcing_per_period() -> None:
    forcing = SEASONAL.validate_python(
        {"kind": "seasonal", "by_season": WINTER_ONLY, "units": "m3/s"}
    )

    values = _forcing_si_per_period(
        dated_model(), forcing, volumetric=True, label="lakes.res.inflow", nper=3
    )

    assert values == pytest.approx((2.0, 2.0, 2.0))  # January falls in DJF


def test_no_period_gives_no_value() -> None:
    forcing = SEASONAL.validate_python(
        {"kind": "seasonal", "by_season": WINTER_ONLY, "units": "m3/s"}
    )

    values = _forcing_si_per_period(
        dated_model(), forcing, volumetric=True, label="lakes.res.inflow", nper=0
    )

    assert values == ()


def test_empty_values_forcing_is_refused() -> None:
    forcing = {"kind": "values", "values": []}

    with pytest.raises(ValueError, match="pre-resolved forcing length"):
        _forcing_si_per_period(
            dated_model(), forcing, volumetric=True, label="lakes.res.inflow", nper=3
        )


TWO_LAKES = {"a": 0, "b": 1}
WEIR = {"kind": "weir"}
SPILL_TO_FOOT = {"mover": {"to_downstream_reach": True}}
SPILL_AT_POINT = {"mover": {"to_downstream_reach": True, "discharge_xy": (10, 20)}}

SPILLWAY_REFERENCES = [
    pytest.param([], (5.0, 6.0), None, id="no outlet"),
    pytest.param([WEIR, {"mover": {"to_downstream_reach": False}}], (5.0, 6.0), None, id="no auto"),
    pytest.param([WEIR, SPILL_TO_FOOT], (5.0, 6.0), (5.0, 6.0), id="domain outlet"),
    pytest.param([WEIR, SPILL_AT_POINT], (5.0, 6.0), (10.0, 20.0), id="declared point"),
    pytest.param([SPILL_TO_FOOT], None, None, id="no domain outlet"),
]


@pytest.mark.parametrize(("outlets", "outlet_xy", "reference"), SPILLWAY_REFERENCES)
def test_spillway_reference_point(outlets, outlet_xy, reference) -> None:
    assert _downstream_spillway_ref({"outlets": outlets}, outlet_xy) == reference


OUTLET_REFUSALS = [
    pytest.param(
        _outlet_couttype, ("a", {"kind": "gate"}), "outlet kind must be one of", id="kind"
    ),
    pytest.param(_outlet_couttype, ("a", {}), "got None", id="no kind"),
    pytest.param(
        _resolve_lakeout, ("a", {"lakeout": -1}, TWO_LAKES), r"must be >= 0", id="lakeout < 0"
    ),
    pytest.param(
        _resolve_lakeout,
        ("a", {"lakeout": 3}, TWO_LAKES),
        "no matching downstream lake",
        id="no lake",
    ),
    pytest.param(
        _resolve_lakeout, ("b", {"lakeout": 2}, TWO_LAKES), "routes the lake to itself", id="itself"
    ),
    pytest.param(
        _outlet_geometry, ("a", "WEIR", {"width": 2.0}), "requires an invert", id="weir no invert"
    ),
    pytest.param(
        _outlet_geometry, ("a", "WEIR", {"invert": 1.0}), "requires a width", id="weir no width"
    ),
    pytest.param(
        _outlet_geometry,
        ("a", "MANNING", {"invert": 1.0, "width": 2.0, "slope": 0.01}),
        "positive rough",
        id="manning no rough",
    ),
    pytest.param(
        _outlet_geometry,
        ("a", "MANNING", {"invert": 1.0, "width": 2.0, "rough": 0.03, "slope": 0.0}),
        "positive slope",
        id="manning flat",
    ),
    pytest.param(_resolve_receiver_lake, ("a", {}, 2), "requires a 'lake'", id="mover no lake"),
    pytest.param(_resolve_receiver_lake, ("a", {"lake": 0}, 2), r"must be >= 1", id="mover lake 0"),
    pytest.param(
        _resolve_receiver_lake,
        ("a", {"lake": 3}, 2),
        "no matching downstream lake",
        id="mover lake 3",
    ),
    pytest.param(
        _lake_id_for_index,
        ([{"lake_index": 0, "lake_id": "a"}], 1),
        "No lake registered for lake index 1",
        id="unknown lake index",
    ),
]


@pytest.mark.parametrize(("function", "args", "match"), OUTLET_REFUSALS)
def test_refusals(function, args, match) -> None:
    with pytest.raises(ValueError, match=match):
        function(*args)


def test_lake_id_of_an_index() -> None:
    info = [{"lake_index": 0, "lake_id": "a"}, {"lake_index": 1, "lake_id": "b"}]

    assert _lake_id_for_index(info, 1) == "b"


def test_managed_constant_is_held_at_zero_through_the_spin_up() -> None:
    rows: dict[int, list[list]] = {}

    _emit_forcing_rows(
        dated_model(steady=(True, False, False)),
        lake_index=0,
        lake_id="res",
        keyword="inflow",
        forcing={"kind": "constant", "value": 0.5, "units": "m3/s"},
        volumetric=True,
        mode="inline",
        min_periods=120,
        nper=3,
        period_rows=rows,
        ts_series=[],
    )

    assert rows == {0: [[0, "inflow", 0.0]], 1: [[0, "inflow", pytest.approx(0.5)]]}


def test_specified_outlets_get_their_rate() -> None:
    lakes = {
        "res": {
            "outlets": [
                WEIR,
                {
                    "kind": "specified",
                    "forcing": {"kind": "constant", "value": 0.5, "units": "m3/s"},
                },
                {"kind": "specified", "rate": 0.25},
                {
                    "kind": "specified",
                    "forcing": {"kind": "values", "values": [0.1, 0.1, 0.3], "units": "m3/s"},
                },
            ]
        }
    }
    rows: dict[int, list[list]] = {}

    _emit_outlet_rate_rows(
        dated_model(),
        lakes=lakes,
        mode="inline",
        min_periods=120,
        nper=3,
        period_rows=rows,
        ts_series=[],
    )

    # Outlet numbers count every outlet, the weir included. A repeated value gives no new row.
    assert rows == {
        0: [[1, "rate", pytest.approx(0.5)], [2, "rate", 0.25], [3, "rate", pytest.approx(0.1)]],
        2: [[3, "rate", pytest.approx(0.3)]],
    }
