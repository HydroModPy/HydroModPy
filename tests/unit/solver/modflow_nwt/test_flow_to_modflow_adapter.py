"""FlowToModflowAdapter, the step that turns a Model into the arrays MODFLOW-NWT reads.

Starting heads (m) and side boundaries, constant-head rows, recharge and evapotranspiration
rates (m/s), wells (m3/s), and the K, Kv, Sy and Ss fields. Each payload is a dict by stress
period, with the rows MODFLOW writes as (layer, row, column, value).
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.optim.parameters import set_by_path
from hydromodpy.core.exceptions import DataContractViolation, SolverInputError
from hydromodpy.core.fields.grid_reference import GridReference
from hydromodpy.core.time.window import ResolvedSimulationTimeWindow
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.model.boundaries.boundary_condition_registry import BoundaryConditionBundle
from hydromodpy.model.boundaries.boundary_conditions import FlowBoundaryConditionConfig
from hydromodpy.model.initial.state import (
    HeadRule,
    InitialState,
    PriorState,
    SolvedState,
    SteadyStart,
)
from hydromodpy.model.model import ModelTime, Properties
from hydromodpy.model.sinks_sources.etp import FlowEtpConfig
from hydromodpy.model.sinks_sources.recharge import FlowRechargeConfig
from hydromodpy.model.sinks_sources.wells import FlowWellConfig
from hydromodpy.solver.modflow_nwt.nwt.flow_to_modflow_adapter import FlowToModflowAdapter
from hydromodpy.solver.modflow_nwt.nwt.payloads.chd import refuse_constant_heads_below_bottom
from tests._helpers.model_factory import make_model
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays


def flat_mesh(nrow=1, ncol=1, nlay=1, dx=1.0, dy=1.0, xoff=0.0, yoff=0.0):
    """A structured mesh with the top at 0 m and every bottom at -10 m."""
    return solver_mesh_from_structured_arrays(
        nrow=nrow,
        ncol=ncol,
        top=np.zeros((nrow, ncol)),
        botm=np.full((nlay, nrow, ncol), -10.0),
        dx=dx,
        dy=dy,
        xoff=xoff,
        yoff=yoff,
    )


def ramp_mesh(dem):
    """Two layers 10 m and 20 m under a DEM of 5 m cells."""
    return solver_mesh_from_structured_arrays(
        nrow=dem.shape[0],
        ncol=dem.shape[1],
        top=dem,
        botm=np.stack([dem - 10.0, dem - 20.0]),
        dx=5.0,
        dy=5.0,
    )


def adapter_of(model, mesh=None, nper=1, **kwargs) -> FlowToModflowAdapter:
    return FlowToModflowAdapter(
        model=model,
        solver_mesh=flat_mesh() if mesh is None else mesh,
        nper=nper,
        sink_fill=False,
        **kwargs,
    )


def bundle(conditions: dict, active=None) -> BoundaryConditionBundle:
    return BoundaryConditionBundle(
        conditions=conditions, active_ids=tuple(conditions if active is None else active)
    )


# K, Kv, Sy and Ss from the properties of the model.

NLAY, NROW, NCOL = 2, 3, 4
SHAPE = (NLAY, NROW, NCOL)
K_M_S = 1e-5
KV_M_S = 2e-6


class Homogeneous:
    """A flow parameter with one value everywhere."""

    is_heterogeneous = False

    def __init__(self, value: float) -> None:
        self.value = value

    def to_mesh_field(self, mesh, label, depth):
        return SimpleNamespace(cell_values=np.full(mesh.n_cells, self.value))


def property_adapter(
    parameters: dict[str, object], steady: tuple[bool, ...] = (True,), **overrides: float
) -> FlowToModflowAdapter:
    model = make_model(
        properties=Properties(profiles=parameters),
        time=ModelTime(
            grid=None, regime="steady" if all(steady) else "transient", first_period_steady=True
        ),
    ).with_properties(**overrides)
    return FlowToModflowAdapter(
        model=model,
        solver_mesh=ramp_mesh(np.full((NROW, NCOL), 20.0)),
        nper=len(steady),
        sink_fill=False,
        steady=np.array(steady),
    )


def test_kv_reaches_solver():
    inputs = property_adapter({"K": Homogeneous(K_M_S), "Kv": Homogeneous(KV_M_S)}).build()

    assert inputs.kv.shape == SHAPE
    np.testing.assert_array_equal(inputs.kv, KV_M_S)


def test_no_kv_is_none():
    assert property_adapter({"K": Homogeneous(K_M_S)}).build().kv is None


@pytest.mark.parametrize(
    ("name", "field", "other_field", "other_value"),
    [("K", "hk", "kv", KV_M_S), ("Kv", "kv", "hk", K_M_S)],
)
def test_override_beats_profile(name, field, other_field, other_value):
    profiles = {"K": Homogeneous(K_M_S), "Kv": Homogeneous(KV_M_S)}

    inputs = property_adapter(profiles, **{name: 3e-5}).build()

    np.testing.assert_array_equal(getattr(inputs, field), 3e-5)
    np.testing.assert_array_equal(getattr(inputs, other_field), other_value)


def test_override_adds_kv():
    inputs = property_adapter({"K": Homogeneous(K_M_S)}, Kv=KV_M_S).build()

    np.testing.assert_array_equal(inputs.kv, KV_M_S)


ZERO_VALUES = [
    pytest.param({"Kv": 0.0}, (True,), "Kv", id="kv zero"),
    pytest.param(
        {"Sy": 0.0, "Ss": 1e-5},
        (True, False),
        r"Sy .* 24 of 24 active convertible .*layer 1: 12, layer 2: 12",
        id="sy zero in a transient run",
    ),
]

HARMLESS_ZEROS = [
    pytest.param({"Sy": 0.0, "Ss": 1e-5}, (True,), id="sy zero in a steady run"),
    pytest.param({"Sy": 0.1, "Ss": 0.0}, (True, False), id="ss zero in a convertible cell"),
]


def zero_adapter(values, steady):
    parameters = {"K": Homogeneous(K_M_S)} | {k: Homogeneous(v) for k, v in values.items()}
    return property_adapter(parameters, steady)


@pytest.mark.parametrize(("values", "steady", "match"), ZERO_VALUES)
def test_zero_refused(values, steady, match):
    with pytest.raises(DataContractViolation, match=match):
        zero_adapter(values, steady).build()


@pytest.mark.parametrize(("values", "steady"), HARMLESS_ZEROS)
def test_harmless_zero(values, steady):
    zero_adapter(values, steady).build()


# Starting heads and side boundaries follow the BAS contract.


def bas_adapter(initial: InitialState = HeadRule("top"), conditions=None) -> FlowToModflowAdapter:
    dem = np.array([[12.0, 14.0, 16.0], [11.0, 13.0, 15.0]])
    model = make_model(initial=initial, boundaries=bundle(conditions or {}))
    return adapter_of(model, ramp_mesh(dem))


def test_initial_heads_and_sides():
    adapter = bas_adapter(conditions={"west_side": SimpleNamespace(value=9.5)})

    ibound, strt, drain_array = adapter._build_initial_heads_and_sides()

    assert ibound.shape == (2, 2, 3)
    assert strt.shape == (2, 2, 3)
    assert drain_array.shape == (2, 3)
    # The west side is a constant head, the interior starts on the top.
    assert np.all(ibound[:, :, 0] < 0)
    assert np.all(strt[:, :, 0] == 9.5)
    np.testing.assert_allclose(strt[0, :, 1:], adapter.dem[:, 1:])
    np.testing.assert_allclose(strt[1, :, 1:], adapter.dem[:, 1:])
    adapter._validate_ibound_strt_contract(ibound=ibound, strt=strt, drain_array=drain_array)


def test_steady_start_on_top():
    adapter = bas_adapter(initial=SteadyStart())

    _, strt, _ = adapter._build_initial_heads_and_sides()

    np.testing.assert_allclose(strt[0], adapter.dem)
    np.testing.assert_allclose(strt[1], adapter.dem)


def test_side_sequence_first_value():
    adapter = bas_adapter(conditions={"west_side": SimpleNamespace(value=[9.5, 8.5])})

    _, strt, _ = adapter._build_initial_heads_and_sides()

    assert np.all(strt[:, :, 0] == 9.5)


PRIOR_AND_SOLVED_STARTS = [
    pytest.param(PriorState(head=np.zeros((2, 6)), lake_stages={}, path="run.zarr"), id="prior"),
    pytest.param(SolvedState(head=np.zeros((2, 6)), solver="modflow6"), id="solved"),
]


@pytest.mark.parametrize("state", PRIOR_AND_SOLVED_STARTS)
def test_head_states_refused(state):
    with pytest.raises(TypeError, match=type(state).__name__):
        bas_adapter(initial=state)._build_initial_heads_and_sides()


def test_refuses_ibound_shape():
    adapter = bas_adapter(initial=HeadRule("custom", 7.0))
    ibound, strt, drain_array = adapter._build_initial_heads_and_sides()

    with pytest.raises(ValueError, match="ibound shape mismatch"):
        adapter._validate_ibound_strt_contract(ibound=ibound[0], strt=strt, drain_array=drain_array)


def test_refuses_non_finite_heads():
    adapter = bas_adapter(initial=HeadRule("bottom"))
    ibound, strt, drain_array = adapter._build_initial_heads_and_sides()
    strt[0, 0, 0] = np.nan

    with pytest.raises(ValueError, match="strt contains non-finite values"):
        adapter._validate_ibound_strt_contract(ibound=ibound, strt=strt, drain_array=drain_array)


def test_refuses_non_binary_drain():
    adapter = bas_adapter(initial=HeadRule("top"))
    ibound, strt, drain_array = adapter._build_initial_heads_and_sides()
    drain_array[0, 0] = 0.5

    with pytest.raises(ValueError, match="drain_array must only contain binary"):
        adapter._validate_ibound_strt_contract(ibound=ibound, strt=strt, drain_array=drain_array)


# Side boundaries on a 3 x 3 grid: the west face is a constant head, active in the IBOUND.


def boundary_adapter(conditions, nper=1, simulation_window=None) -> FlowToModflowAdapter:
    model = make_model(
        boundaries=bundle(conditions),
        initial=HeadRule("custom", 0.0),
        time=ModelTime(grid=None, regime="transient", first_period_steady=True),
    )
    return adapter_of(
        model, flat_mesh(nrow=3, ncol=3), nper=nper, simulation_window=simulation_window
    )


def west_side(units: str, forcing: dict) -> FlowBoundaryConditionConfig:
    return FlowBoundaryConditionConfig(
        id="west_side",
        kind="dirichlet",
        units=units,
        application_domain="west side",
        forcing=forcing,
    )


def test_transient_west_side():
    adapter = boundary_adapter({"west_side": SimpleNamespace(value=[5.0, 6.0])}, nper=2)

    ibound, strt, _ = adapter._build_initial_heads_and_sides()
    chd_spd = adapter._build_side_chd()

    assert np.all(ibound[:, :, 0] == 1.0)
    assert np.all(strt[:, :, 0] == 5.0)
    assert chd_spd[0][0] == [0, 0, 0, pytest.approx(5.0), pytest.approx(5.0)]
    assert chd_spd[1][0] == [0, 0, 0, pytest.approx(6.0), pytest.approx(6.0)]


def test_constant_side_forcing():
    adapter = boundary_adapter(
        {"west_side": west_side("cm", {"kind": "constant", "value": 5.0})}, nper=2
    )

    ibound, strt, _ = adapter._build_initial_heads_and_sides()
    chd_spd = adapter._build_side_chd()

    assert np.all(ibound[:, :, 0] == 1.0)
    assert np.all(strt[:, :, 0] == 0.05)  # 5 cm
    rows = [[0, 0, 0, 0.05, 0.05], [0, 1, 0, 0.05, 0.05], [0, 2, 0, 0.05, 0.05]]
    assert chd_spd == {0: rows, 1: rows}


def test_csv_needs_window():
    adapter = boundary_adapter(
        {"west_side": west_side("m", {"kind": "csv", "path_file": "dummy.csv"})}, nper=2
    )

    with pytest.raises(ValueError, match="simulation.time is required"):
        adapter._build_initial_heads_and_sides()


def test_side_beats_ocean():
    adapter = boundary_adapter({}, nper=2)
    ocean = {0: [[0, 0, 0, 1.0, 1.0]], 1: [[0, 0, 0, 2.0, 2.0]]}
    side = {0: [[0, 0, 0, 5.0, 5.0]], 1: [[0, 0, 0, 6.0, 6.0]]}

    assert adapter._merge_chd_payloads(ocean, side) == side


# A constant head below the bottom of its cell is refused before MODFLOW-NWT runs. NWT does
# not stop on such a head: the cell holds no saturated thickness, the boundary does not act
# there, and the budget drifts.


def head_adapter(conditions: dict[str, object], *, nper: int = 1) -> FlowToModflowAdapter:
    dem = np.full((2, 3), 20.0)
    return adapter_of(make_model(boundaries=bundle(conditions)), ramp_mesh(dem), nper=nper)


def test_head_above_bottom():
    adapter = head_adapter({"west_side": SimpleNamespace(value=15.0)})
    ibound, strt, _ = adapter._build_initial_heads_and_sides()

    refuse_constant_heads_below_bottom(adapter, ibound=ibound, strt=strt, chd_spd=None)


def test_head_below_bottom_names_period():
    adapter = head_adapter({"east_side": SimpleNamespace(value=[15.0, 8.0])}, nper=2)
    ibound, strt, _ = adapter._build_initial_heads_and_sides()
    chd_spd = adapter._build_side_chd()

    with pytest.raises(SolverInputError) as excinfo:
        refuse_constant_heads_below_bottom(adapter, ibound=ibound, strt=strt, chd_spd=chd_spd)

    assert "flow.bc.east_side" in str(excinfo.value)
    assert "column 2 (head 8.00 m, bottom 10.00 m, period 2)" in str(excinfo.value)


def test_build_refuses_low_head():
    adapter = head_adapter({"west_side": SimpleNamespace(value=5.0)})

    with pytest.raises(SolverInputError, match="flow.bc.west_side"):
        adapter.build()


# Recharge and evapotranspiration rates (m/s).


def recharge_adapter(
    recharge, regime, nper, *, simulation_window=None, first_period_steady=True
) -> FlowToModflowAdapter:
    model = make_model(
        recharge=recharge,
        active_sinks_sources=("recharge",),
        time=ModelTime(grid=None, regime=regime, first_period_steady=first_period_steady),
    )
    return adapter_of(model, nper=nper, simulation_window=simulation_window)


def february_window() -> ResolvedSimulationTimeWindow:
    return ResolvedSimulationTimeWindow(
        start=pd.Timestamp("2003-01-01"),
        end=pd.Timestamp("2003-02-28"),
        step_value=1,
        step_unit="month",
        coverage_policy="error",
    )


def point_record(january_mm_day: float, february_mm_day: float) -> PointRecord:
    dates = pd.date_range("2003-01-01", "2003-02-28", freq="D")
    values = np.where(dates.month == 2, february_mm_day, january_mm_day).astype(float)
    return PointRecord(
        station_id="R1",
        variable="recharge",
        source="test",
        unit="mm/day",
        frequency="D",
        data=pd.DataFrame({"datetime": dates, "value": values}),
        date_start=datetime(2003, 1, 1),
        date_end=datetime(2003, 2, 28),
        location=StationLocation(id="R1", x=0.5, y=0.5, crs="EPSG:2154"),
    )


RECHARGE_PAYLOADS = [
    pytest.param(
        FlowRechargeConfig(values={0: 0.2, 1: 0.4}, units="m/s"),
        "steady",
        2,
        {0: pytest.approx(0.3), 1: pytest.approx(0.3)},
        id="steady run takes the mean in every period",
    ),
    pytest.param(
        FlowRechargeConfig(values={0: 0.1, 1: 0.2}, units="m/s"),
        "transient",
        2,
        {0: pytest.approx(0.15), 1: pytest.approx(0.2)},
        id="steady first period takes first_clim",
    ),
    # 0.001 mm/day = 1e-6 m/day, spread over 86400 s.
    pytest.param(
        FlowRechargeConfig(values=0.001, units="mm/day"),
        "transient",
        3,
        {k: pytest.approx(1.0e-6 / 86400.0) for k in range(3)},
        id="scalar goes to every period",
    ),
    pytest.param(None, "transient", 2, None, id="no recharge"),
]


@pytest.mark.parametrize(("recharge", "regime", "nper", "expected"), RECHARGE_PAYLOADS)
def test_recharge_payload(recharge, regime, nper, expected):
    assert recharge_adapter(recharge, regime, nper)._build_recharge_payload() == expected


FIRST_PERIOD_RATES = [
    pytest.param("first", True, 0.5, id="steady period, first"),
    pytest.param(0.0, True, 0.0, id="steady period, numeric"),
    pytest.param("mean", False, 0.5, id="transient period, mean"),
    pytest.param("first", False, 0.5, id="transient period, first"),
    pytest.param(0.0, False, 0.5, id="transient period, numeric"),
]


@pytest.mark.parametrize(("first_clim", "first_period_steady", "rate"), FIRST_PERIOD_RATES)
def test_first_period_rate(first_clim, first_period_steady, rate):
    # A transient first period keeps its own rate whatever first_clim says.
    config = FlowRechargeConfig(
        values=pd.Series([0.5, 0.3, 0.1], dtype=float), first_clim=first_clim, units="m/s"
    )
    adapter = recharge_adapter(config, "transient", 3, first_period_steady=first_period_steady)

    assert adapter._build_recharge_payload()[0] == pytest.approx(rate)


def test_series_short_of_window():
    series = pd.Series(
        [0.1, 0.1], index=pd.DatetimeIndex(["2003-01-01", "2003-01-02"]), dtype=float
    )
    adapter = recharge_adapter(
        FlowRechargeConfig(values=series, units="m/s"),
        "transient",
        2,
        simulation_window=february_window(),
    )

    with pytest.raises(ValueError, match="does not cover stress period"):
        adapter._build_recharge_payload()


def test_negative_recharge_to_evt():
    config = FlowRechargeConfig(
        values=[0.1, -0.2, 0.3], first_clim="first", units="m/s", negative_to_evt=True
    )
    adapter = recharge_adapter(config, "transient", 3)

    rch_data = adapter._build_recharge_payload()
    evt_spd, _, _ = adapter._build_etp_payload()

    np.testing.assert_allclose([rch_data[k] for k in range(3)], [0.1, 0.0, 0.3])
    np.testing.assert_allclose([evt_spd[k] for k in range(3)], [0.0, 0.2, 0.0])


def test_point_source_periods():
    config = FlowRechargeConfig(
        values=0.0,
        first_clim="first",
        heterogeneous_source=LoadResult(points=[point_record(8.0, 4.0)]),
        interpolation_method="nearest",
    )
    adapter = recharge_adapter(config, "transient", 2, simulation_window=february_window())

    rch_data = adapter._build_recharge_payload()

    assert set(rch_data) == {0, 1}
    np.testing.assert_allclose(rch_data[0], np.full((1, 1), 8.0e-3 / 86400.0))  # 8 mm/day
    np.testing.assert_allclose(rch_data[1], np.full((1, 1), 4.0e-3 / 86400.0))  # 4 mm/day


# The extinction depth of a calibration trial reaches the EVT payload. A trial patches the
# typed config with set_by_path, and the Model of the next solve is rebuilt from it.


def etp_depth(trial_m: float) -> float:
    config = FlowEtpConfig(values=0.0, units="m/s", extinction_depth=1.0).model_copy(deep=True)
    set_by_path(config, "extinction_depth", trial_m)
    model = make_model(
        etp=config,
        active_sinks_sources=("etp",),
        time=ModelTime(grid=None, regime="transient", first_period_steady=True),
    )
    return adapter_of(model)._build_etp_payload()[2]


@pytest.mark.parametrize("trial_m", [9.0, 3.0, 15.0])
def test_trial_extinction_depth(trial_m):
    assert etp_depth(trial_m) == pytest.approx(trial_m)


# Wells: location by cell, by absolute x y or by relative x y, and the flux per period.


def well_adapter(wells, mesh=None, grid=None) -> FlowToModflowAdapter:
    model = make_model(wells=wells, active_sinks_sources=("wells",))
    return adapter_of(model, mesh, nper=2, grid=grid)


def well_grid(bounds, size) -> GridReference:
    return GridReference(
        n_cells=20, bounds=bounds, crs=None, structured_shape=(4, 5), cell_size_hint=size
    )


def one_well(flux=None, **config) -> dict:
    return {"W1": FlowWellConfig(**config) if flux is None else FlowWellConfig(flux=flux, **config)}


WELL_ROWS = [
    pytest.param(
        one_well(-1e-4, location={"kind": "absolute_xy", "layer": 1, "x": 125.0, "y": 365.0}),
        flat_mesh(nrow=4, ncol=5, nlay=2, dx=50.0, dy=100.0),
        well_grid((0.0, 0.0, 250.0, 400.0), 50.0),
        {0: [[1, 0, 2, pytest.approx(-1e-4)]], 1: [[1, 0, 2, pytest.approx(-1e-4)]]},
        id="absolute xy",
    ),
    pytest.param(
        one_well(
            [-1e-4, -2e-4],
            location={"kind": "relative_xy", "layer": 0, "x_rel": 0.4, "y_rel": 0.25},
        ),
        flat_mesh(nrow=4, ncol=5, dx=10.0, dy=10.0, xoff=100.0, yoff=200.0),
        well_grid((100.0, 200.0, 150.0, 240.0), 10.0),
        {0: [[0, 3, 2, pytest.approx(-1e-4)]], 1: [[0, 3, 2, pytest.approx(-2e-4)]]},
        id="relative xy",
    ),
    pytest.param(
        one_well(
            location={"kind": "cell", "cell": (0, 0, 0)},
            units="m3/day",
            forcing={"kind": "constant", "value": -86400.0},
        ),
        None,
        None,
        {0: [[0, 0, 0, pytest.approx(-1.0)]], 1: [[0, 0, 0, pytest.approx(-1.0)]]},
        id="constant forcing in m3/day",
    ),
]

WELL_REFUSALS = [
    pytest.param(
        one_well(-1e-4, location={"kind": "absolute_xy", "layer": 0, "x": 1000.0, "y": 1000.0}),
        flat_mesh(nrow=4, ncol=5, dx=50.0, dy=100.0),
        well_grid((0.0, 0.0, 250.0, 400.0), 50.0),
        "outside the structured solver grid extent",
        id="outside the grid",
    ),
    pytest.param(
        one_well([-1e-4, -2e-4, -3e-4], location={"kind": "cell", "cell": (0, 0, 0)}),
        None,
        None,
        "must be 1 or match nper",
        id="flux length differs from nper",
    ),
]


@pytest.mark.parametrize(("wells", "mesh", "grid", "expected"), WELL_ROWS)
def test_well_periods(wells, mesh, grid, expected):
    assert well_adapter(wells, mesh, grid)._build_well_stress_period_data() == expected


@pytest.mark.parametrize(("wells", "mesh", "grid", "match"), WELL_REFUSALS)
def test_well_refusals(wells, mesh, grid, match):
    with pytest.raises(ValueError, match=match):
        well_adapter(wells, mesh, grid)._build_well_stress_period_data()
