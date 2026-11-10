"""The frozen Model holds the objects of the bound Flow, and its factories return new models."""

from __future__ import annotations

import dataclasses
import pickle
from types import MappingProxyType, SimpleNamespace

import numpy as np
import pytest

from hydromodpy.model.boundaries.boundary_condition_registry import BoundaryConditionBundle
from hydromodpy.model.domain.geometry import CatchmentGeometry, ChannelRasters, RasterGeometry
from hydromodpy.model.flow import Flow
from hydromodpy.model.flow_config import FlowConfig
from hydromodpy.model.initial.state import (
    INITIAL_STATE_TYPES,
    CyclicSpinupStrategy,
    CyclicStart,
    HeadRule,
    PriorState,
    SolvedState,
    SteadyStart,
    SteadyStateStrategy,
)
from hydromodpy.model.model import (
    Geometry,
    Model,
    ModelOptions,
    ModelTime,
    Properties,
    cycle_variant,
    model_from_flow,
    steady_variant,
)
from hydromodpy.model.sinks_sources.recharge import FlowRechargeConfig
from hydromodpy.solver.boussinesq.options import BoussinesqOptions
from hydromodpy.solver.modflow6.modflow6_config import Modflow6Config
from hydromodpy.solver.modflow_nwt.nwt.nwt_config import ModflowConfig
from tests._helpers.model_factory import default_options, make_model, small_geometry, time_grid

_MM_PER_YEAR_IN_M_PER_S = 1e-3 / (365.25 * 86400.0)


def _bound_flow(**ic: object) -> Flow:
    """A flow as the setup and data steps leave it, with one payload of each family."""
    config: dict[str, object] = {
        "bc": {
            "west_side": {"kind": "dirichlet", "value": "10 m"},
            "drainage": {"kind": "drain", "value": 1.0},
        },
        "sinks_sources": {
            "recharge": {"values": [1.0, 2.0], "units": "mm/day"},
            "etp": {"values": 1.0, "units": "mm/day"},
            "wells": {
                "w1": {
                    "location": {"kind": "cell", "cell": [0, 0, 0]},
                    "flux": -1.0,
                    "units": "m3/day",
                }
            },
        },
    }
    if ic:
        config["ic"] = ic
    flow = Flow(FlowConfig.model_validate(config))
    # The data step binds lakes, networks and barriers as payload dicts, and the
    # setup ingests the parameters; plain objects stand for both here.
    flow.parameters = {"K": object(), "Sy": object()}
    flow.sinks_sources["lakes"] = {"lake": {"bedleak": 0.1}}
    flow.sinks_sources["sfr"] = {"main": {"inflow": {"kind": "constant", "value": 0.0}}}
    flow.sinks_sources["flow_barriers"] = {"wall": {"hydchr": 1e-9}}
    return flow


def _model_of(flow: Flow, **kwargs: object) -> Model:
    return model_from_flow(
        flow,
        geometry=kwargs.pop("geometry", small_geometry()),
        time=kwargs.pop("time", ModelTime.from_flow(flow, time_grid(10.0, 20.0))),
        options=kwargs.pop("options", default_options()),
        **kwargs,
    )


SAME_OBJECT = (
    ("recharge", lambda m: m.recharge, lambda f: f.sinks_sources["recharge"]),
    ("etp", lambda m: m.etp, lambda f: f.sinks_sources["etp"]),
    ("well", lambda m: m.wells["w1"], lambda f: f.sinks_sources["wells"]["w1"]),
    ("lake", lambda m: m.lakes["lake"], lambda f: f.sinks_sources["lakes"]["lake"]),
    ("network", lambda m: m.sfr["main"], lambda f: f.sinks_sources["sfr"]["main"]),
    (
        "barrier",
        lambda m: m.flow_barriers["wall"],
        lambda f: f.sinks_sources["flow_barriers"]["wall"],
    ),
    ("profile K", lambda m: m.properties.profiles["K"], lambda f: f.parameters["K"]),
    ("profile Sy", lambda m: m.properties.profiles["Sy"], lambda f: f.parameters["Sy"]),
    (
        "boundary",
        lambda m: m.boundaries.get("west_side"),
        lambda f: f.boundary_conditions["west_side"],
    ),
)


@pytest.mark.parametrize(
    ("member", "of_model", "of_flow"), SAME_OBJECT, ids=[m for m, _, _ in SAME_OBJECT]
)
def test_each_member_is_the_object_the_flow_held(member, of_model, of_flow) -> None:
    del member
    flow = _bound_flow()

    assert of_model(_model_of(flow)) is of_flow(flow)


def test_the_lists_and_the_given_parts_reach_the_model() -> None:
    flow = _bound_flow()
    geometry, options = small_geometry(), default_options()
    time = ModelTime.from_flow(flow, time_grid(10.0, 20.0))

    model = model_from_flow(flow, geometry=geometry, time=time, options=options)

    assert model.geometry is geometry
    assert model.time is time
    assert model.options is options
    assert model.active_sinks_sources == ("recharge", "wells", "etp")
    assert model.boundaries.active_ids == ("west_side", "drainage")
    assert model.boundaries.active_side_dirichlet_ids() == ("west_side",)
    assert list(model.properties.profiles) == ["K", "Sy"]
    assert model.properties.overrides == {}


def test_the_time_follows_the_flow() -> None:
    flow = _bound_flow()
    grid = time_grid(10.0)

    time = ModelTime.from_flow(flow, grid)

    assert (time.grid, time.regime, time.first_period_steady) == (grid, "transient", True)


def test_a_regime_outside_steady_and_transient_is_refused() -> None:
    with pytest.raises(ValueError, match="steady"):
        ModelTime(grid=None, regime="pseudo", first_period_steady=True)


def test_the_options_read_the_four_solver_settings_by_name() -> None:
    settings = SimpleNamespace(
        sink_fill=1,
        drain_band_depth_m=0.5,
        drain_bed_thickness_m="2",
        drain_conductance_floor_m2_s=1e-10,
    )

    assert ModelOptions.from_settings(settings) == ModelOptions(True, 0.5, 2.0, 1e-10)


INITIAL_FROM_IC = (
    ("default", {}, HeadRule("top")),
    ("bottom", {"kind": "bottom"}, HeadRule("bottom")),
    ("custom", {"kind": "custom", "value": "12 m"}, HeadRule("custom", 12.0)),
    ("steady", {"kind": "steady_state"}, SteadyStart(SteadyStateStrategy())),
    ("cyclic", {"kind": "spinup_cyclic", "max_cycles": 3}, CyclicStart(CyclicSpinupStrategy(3))),
)


@pytest.mark.parametrize(
    ("case", "ic", "expected"), INITIAL_FROM_IC, ids=[c for c, _, _ in INITIAL_FROM_IC]
)
def test_the_start_is_the_one_flow_ic_asks_for(case, ic, expected) -> None:
    del case
    flow = _bound_flow(**ic)

    assert _model_of(flow).initial == expected


def test_a_start_given_to_the_factory_wins_over_flow_ic() -> None:
    prior = PriorState(np.zeros((1, 6)), {}, "prior.zarr")

    assert _model_of(_bound_flow(), initial=prior).initial is prior


READ_ONLY = (
    ("wells", lambda m: m.wells),
    ("lakes", lambda m: m.lakes),
    ("sfr", lambda m: m.sfr),
    ("flow_barriers", lambda m: m.flow_barriers),
    ("profiles", lambda m: m.properties.profiles),
    ("overrides", lambda m: m.properties.overrides),
    ("conditions", lambda m: m.boundaries.conditions),
)


@pytest.mark.parametrize(("member", "mapping"), READ_ONLY, ids=[m for m, _ in READ_ONLY])
def test_a_mapping_of_the_model_takes_no_write(member, mapping) -> None:
    del member
    with pytest.raises(TypeError):
        mapping(_model_of(_bound_flow()))["new"] = object()


def test_a_later_change_to_the_flow_does_not_reach_the_model() -> None:
    flow = _bound_flow()
    model = _model_of(flow)

    flow.sinks_sources["lakes"]["other"] = {}
    flow.parameters["Ss"] = object()
    flow.boundary_conditions["east_side"] = object()

    assert "other" not in model.lakes
    assert "Ss" not in model.properties.profiles
    assert model.boundaries.get("east_side") is None


@pytest.mark.parametrize(
    "member", [field.name for field in dataclasses.fields(Model)], ids=lambda name: name
)
def test_the_model_is_frozen(member: str) -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(make_model(), member, None)


def test_a_pickled_model_keeps_every_member_and_its_mappings_stay_read_only() -> None:
    prior = PriorState(head=np.zeros((1, 6)), lake_stages={"lake": 12.5}, path="run/heads")
    model = make_model(
        properties=Properties(profiles={"K": 1e-5}, overrides={"K": 2e-5}),
        boundaries=BoundaryConditionBundle(conditions={"west_side": 3.0}, active_ids=["west_side"]),
        wells={"well": {"q": -1e-3}},
        lakes={"lake": {"bedleak": 1.0}},
        sfr={"reach": {"streambed_k": 2.0}},
        flow_barriers={"wall": {"hydchr": 3.0}},
        active_sinks_sources=["wells", "lakes"],
        initial=prior,
    )

    copy = pickle.loads(pickle.dumps(model))

    assert copy.properties.profiles == {"K": 1e-5}
    assert copy.properties.overrides == {"K": 2e-5}
    assert copy.boundaries.conditions == {"west_side": 3.0}
    assert copy.boundaries.active_ids == ("west_side",)
    assert copy.wells == {"well": {"q": -1e-3}}
    assert copy.lakes == {"lake": {"bedleak": 1.0}}
    assert copy.sfr == {"reach": {"streambed_k": 2.0}}
    assert copy.flow_barriers == {"wall": {"hydchr": 3.0}}
    assert copy.active_sinks_sources == ("wells", "lakes")
    assert copy.initial.lake_stages == {"lake": 12.5}
    assert copy.initial.path == "run/heads"
    np.testing.assert_array_equal(copy.initial.head, prior.head)
    assert (copy.time.grid, copy.time.regime, copy.time.first_period_steady) == (
        model.time.grid,
        model.time.regime,
        model.time.first_period_steady,
    )
    assert copy.options == model.options
    assert copy.geometry.cells.n_cells == model.geometry.cells.n_cells
    for mapping in (
        copy.properties.profiles,
        copy.properties.overrides,
        copy.boundaries.conditions,
        copy.wells,
        copy.lakes,
        copy.sfr,
        copy.flow_barriers,
        copy.initial.lake_stages,
    ):
        assert isinstance(mapping, MappingProxyType)


def test_a_start_that_is_not_one_of_the_five_states_is_refused() -> None:
    with pytest.raises(TypeError, match="Model.initial is one of"):
        make_model(initial="top")


def test_with_initial_returns_a_new_model_and_leaves_the_old_one() -> None:
    model = make_model()
    prior = PriorState(np.zeros((1, 6)), {"lake": 3.0}, "prior.zarr")

    started = model.with_initial(prior)

    assert started is not model
    assert started.initial is prior
    assert model.initial == HeadRule("top")
    assert started.geometry is model.geometry


def test_with_properties_merges_values_into_a_new_model() -> None:
    model = make_model(properties=Properties(profiles={"K": "profile"}))
    k_cells = np.full(6, 1e-4)

    once = model.with_properties(K=k_cells)
    twice = once.with_properties(Sy=0.2, hk=np.full(6, 2e-4))

    assert model.properties.overrides == {}
    assert once.properties.overrides["K"] is k_cells
    assert set(twice.properties.overrides) == {"K", "Sy", "hk"}
    assert twice.properties.profiles["K"] == "profile"
    assert twice is not once and once is not model


@pytest.mark.parametrize("name", ["porosity", "properties", "k"])
def test_with_properties_refuses_a_name_that_sets_no_property(name: str) -> None:
    with pytest.raises(ValueError, match=f"{name} name no flow property"):
        make_model().with_properties(**{name: 1.0})


def _member_names(cls: type, seen: set[type]) -> set[str]:
    """Every field name of ``cls`` and of the dataclasses its fields hold, recursively."""
    if cls in seen:
        return set()
    seen.add(cls)
    names = set()
    for field in dataclasses.fields(cls):
        names.add(field.name)
    for nested in (
        Geometry,
        Properties,
        ModelTime,
        ModelOptions,
        RasterGeometry,
        ChannelRasters,
        CatchmentGeometry,
        BoundaryConditionBundle,
        SteadyStateStrategy,
        CyclicSpinupStrategy,
        *INITIAL_STATE_TYPES,
    ):
        if nested not in seen:
            names |= _member_names(nested, seen)
    return names


@pytest.mark.parametrize(
    "backend_config", [BoussinesqOptions, Modflow6Config, ModflowConfig], ids=lambda c: c.__name__
)
def test_no_member_of_the_model_is_a_backend_setting(backend_config) -> None:
    clashes = _member_names(Model, set()) & set(backend_config.model_fields)

    assert not clashes, f"The Model carries settings of {backend_config.__name__}: {clashes}"


FLOW_RUNTIME_COPIES = (
    "runtime_backend",
    "surface_interaction_model",
    "partition_release_depth_m",
    "runtime_max_iterations",
    "runtime_tol_residual_inf",
    "runtime_tol_state_update_inf",
    "vi_substeps_per_period",
    "vi_substep_on_failure",
    "vi_max_adaptive_substeps",
    "ts_vi_steps_per_period",
    "ts_vi_adapt",
    "ts_vi_dt_min_fraction",
    "ts_vi_dt_max_fraction",
    "ts_vi_type",
    "ts_vi_snes_type",
    "initial_condition_types",
    "boundary_condition_application_domains",
)


@pytest.mark.parametrize("name", FLOW_RUNTIME_COPIES)
def test_the_flow_keeps_no_backend_setting_and_no_dead_cache(name: str) -> None:
    assert not hasattr(Flow(FlowConfig()), name)


# The steady variant. The expected values are those the MODFLOW 6 steady
# initialization of 2.0.0 returned on this lake and SFR payload, recorded to
# the bit.

_DAY = 86400.0
_A4_LENGTHS_DAYS = (31.0, 28.0, 31.0, 30.0)


def _values(*values: float) -> dict:
    return {"kind": "values", "values": list(values)}


def _a4_lakes() -> dict:
    return {
        "a": {
            "rainfall": _values(1e-8, 2e-8, 3e-8, 5e-8),
            "evaporation": _values(4e-9, 5e-9, 7e-9, 1e-8),
            "runoff": _values(0.0, 10.0, 20.0, 40.0),
            "bedleak": 0.1,
        },
        "b": {
            "rainfall": {"kind": "constant", "value": 2e-8, "units": "m/s"},
            "evaporation": _values(1.0, 2.0),
            "runoff": _values(0.0, 0.0, 0.0, 52.0),
        },
    }


def _a4_sfr() -> dict:
    return {
        "main": {
            "rainfall": _values(1e-8, 1e-8, 2e-8, 2e-8),
            "evaporation": _values(3e-9, 3e-9, 4e-9, 4e-9),
            "runoff": _values(1.0, 2.0, 3.0, 4.0),
            "inflow": _values(0.5, 0.25, 0.125, 0.0625),
        }
    }


A4_LAKES = {
    "a": {
        "bedleak": 0.1,
        "evaporation": {"kind": "values", "values": [6.508333333333333e-09]},
        "rainfall": {"kind": "values", "values": [2.7499999999999998e-08]},
        "runoff": {"kind": "values", "values": [17.5]},
    },
    "b": {
        "evaporation": {"kind": "values", "values": [1.0, 2.0]},
        "rainfall": {"kind": "constant", "units": "m/s", "value": 2e-08},
        "runoff": {"kind": "values", "values": [13.0]},
    },
}
A4_SFR = {
    "main": {
        "evaporation": {"kind": "values", "values": [3.5083333333333333e-09]},
        "inflow": {"kind": "values", "values": [0.23541666666666666]},
        "rainfall": {"kind": "values", "values": [1.5083333333333336e-08]},
        "runoff": {"kind": "values", "values": [2.5]},
    }
}


def test_the_steady_variant_averages_lake_and_sfr_forcings_as_the_base_did() -> None:
    lakes, sfr = _a4_lakes(), _a4_sfr()
    model = make_model(
        lakes=lakes,
        sfr=sfr,
        time=ModelTime(
            grid=time_grid(*_A4_LENGTHS_DAYS), regime="transient", first_period_steady=True
        ),
    )

    steady = steady_variant(model)

    assert dict(steady.lakes) == A4_LAKES
    assert dict(steady.sfr) == A4_SFR
    assert model.lakes["a"]["runoff"]["values"] == [0.0, 10.0, 20.0, 40.0]
    assert lakes == _a4_lakes() and sfr == _a4_sfr()


@pytest.mark.parametrize("grid", [None, time_grid(10.0)], ids=["no grid", "one period"])
def test_the_steady_variant_keeps_forcings_it_has_nothing_to_average_over(grid) -> None:
    model = make_model(
        lakes=_a4_lakes(), time=ModelTime(grid=grid, regime="steady", first_period_steady=True)
    )

    assert dict(steady_variant(model).lakes) == _a4_lakes()


def _recharge(values: object, units: str = "m/s", **extra: object) -> FlowRechargeConfig:
    return FlowRechargeConfig(values=values, units=units, **extra)


def _transient(**members: object) -> Model:
    return make_model(
        time=ModelTime(grid=time_grid(10.0, 30.0), regime="transient", first_period_steady=False),
        **members,
    )


PRESCRIBED = SteadyStateStrategy("prescribed", None, "first_period", 500 * _MM_PER_YEAR_IN_M_PER_S)

RECHARGE_CASES = (
    ("head rule", HeadRule("top"), "same"),
    ("time mean", SteadyStart(), {"first_clim": "mean"}),
    ("prescribed", SteadyStart(PRESCRIBED), "prescribed"),
    ("cycle from steady", CyclicStart(CyclicSpinupStrategy(3, 0.01, "steady_state")), "same"),
)


@pytest.mark.parametrize(
    ("case", "initial", "expected"), RECHARGE_CASES, ids=[c for c, _, _ in RECHARGE_CASES]
)
def test_the_steady_variant_sets_the_recharge_its_start_asks_for(case, initial, expected) -> None:
    del case
    recharge = _recharge([1e-8, 2e-8], first_clim=1e-8)
    model = _transient(recharge=recharge, initial=initial)

    steady = steady_variant(model)

    assert model.recharge is recharge
    if expected == "same":
        assert steady.recharge is recharge
    elif expected == "prescribed":
        rate = 500 * _MM_PER_YEAR_IN_M_PER_S
        assert steady.recharge.values == pytest.approx(rate, rel=1e-12)
        assert steady.recharge.first_clim == pytest.approx(rate, rel=1e-12)
    else:
        assert steady.recharge.first_clim == expected["first_clim"]
        assert list(steady.recharge.values) == [1e-8, 2e-8]


def test_a_steady_start_without_recharge_keeps_none() -> None:
    assert steady_variant(_transient(initial=SteadyStart())).recharge is None


def test_the_steady_variant_is_one_steady_period_starting_from_the_top() -> None:
    model = _transient(initial=SteadyStart())

    steady = steady_variant(model)

    assert steady is not model
    assert steady.time.regime == "steady"
    assert steady.time.first_period_steady is False
    np.testing.assert_array_equal(steady.time.grid.period_lengths_seconds, [40.0 * _DAY])
    np.testing.assert_array_equal(
        steady.time.grid.record_lengths_seconds, [10.0 * _DAY, 30.0 * _DAY]
    )
    assert steady.initial == HeadRule("top")
    assert model.time.regime == "transient"
    assert model.initial == SteadyStart()
    assert steady.geometry is model.geometry
    assert steady.boundaries is model.boundaries


def test_the_steady_variant_starts_where_it_is_told() -> None:
    start = HeadRule("top_offset", 0.01)

    assert steady_variant(_transient(), start=start).initial is start


SEEDS = (
    ("no seed", None, HeadRule("top")),
    ("seed", SolvedState(np.ones((1, 6)), "modflow6"), "seed"),
)


@pytest.mark.parametrize(("case", "seed", "expected"), SEEDS, ids=[c for c, _, _ in SEEDS])
def test_a_cycle_starts_from_its_seed_or_the_top_and_keeps_the_rest(case, seed, expected) -> None:
    del case
    model = _transient(
        recharge=_recharge([1e-8, 2e-8]),
        lakes={"lake": {"bedleak": 0.1}},
        initial=CyclicStart(),
    )

    cycle = cycle_variant(model, seed)

    assert cycle is not model
    assert cycle.initial is seed if expected == "seed" else cycle.initial == expected
    assert cycle.recharge is model.recharge
    assert cycle.lakes["lake"] is model.lakes["lake"]
    assert cycle.time is model.time
    assert model.initial == CyclicStart()


def _whole_and_window() -> tuple[Model, Model]:
    """The model of a whole simulation of three periods and of its first window of one."""
    whole = make_model(
        recharge=_recharge([1e-8, 2e-8, 6e-8], first_clim=1e-8),
        lakes={"lake": {"runoff": {"kind": "values", "values": [0.0, 10.0, 20.0]}}},
        time=ModelTime(
            grid=time_grid(10.0, 30.0, 20.0), regime="transient", first_period_steady=False
        ),
    )
    window = make_model(
        recharge=_recharge([1e-8], first_clim=1e-8),
        lakes={"lake": {"runoff": {"kind": "values", "values": [0.0]}}},
        time=ModelTime(grid=time_grid(10.0), regime="transient", first_period_steady=False),
    )
    return whole, window


def test_the_steady_start_of_a_first_window_is_the_one_of_the_whole_simulation() -> None:
    whole, window = _whole_and_window()
    chained = window.with_initial(SteadyStart(over=whole))
    whole_steady = steady_variant(whole.with_initial(SteadyStart()))

    steady = steady_variant(chained)

    np.testing.assert_array_equal(steady.time.grid.period_lengths_seconds, [60.0 * _DAY])
    np.testing.assert_array_equal(
        steady.time.grid.period_lengths_seconds, whole_steady.time.grid.period_lengths_seconds
    )
    assert dict(steady.lakes) == dict(whole_steady.lakes)
    assert dict(steady.lakes) != dict(steady_variant(window.with_initial(SteadyStart())).lakes)
    assert steady.recharge.first_clim == "mean"
    assert list(steady.recharge.values) == [1e-8, 2e-8, 6e-8]
    assert steady.initial == HeadRule("top")
    np.testing.assert_array_equal(window.time.grid.period_lengths_seconds, [10.0 * _DAY])


def test_the_cycles_of_a_first_window_repeat_the_whole_simulation() -> None:
    whole, window = _whole_and_window()
    chained = window.with_initial(CyclicStart(over=whole)).with_properties(K=1e-5)
    seed = SolvedState(np.ones((1, 6)), "modflow6", {"lake": 12.5})

    cycle = cycle_variant(chained, seed)

    assert cycle.time is whole.time
    assert cycle.recharge is whole.recharge
    assert cycle.initial is seed
    assert cycle.initial.lake_stages == {"lake": 12.5}
    assert cycle.properties is chained.properties
    assert dict(cycle.properties.overrides) == {"K": 1e-5}


def test_a_start_whose_over_is_not_a_model_is_refused() -> None:
    _, window = _whole_and_window()

    with pytest.raises(TypeError, match="over is the Model of the whole simulation"):
        steady_variant(window.with_initial(SteadyStart(over="whole")))


def test_a_model_built_by_hand_freezes_what_it_is_given() -> None:
    conditions = {"west_side": object()}
    model = make_model(
        boundaries=BoundaryConditionBundle(conditions=conditions, active_ids=["west_side"]),
        active_sinks_sources=["recharge"],
    )

    assert isinstance(model.boundaries.conditions, MappingProxyType)
    assert model.boundaries.active_ids == ("west_side",)
    assert model.active_sinks_sources == ("recharge",)
    conditions["east_side"] = object()
    assert model.boundaries.get("east_side") is None
