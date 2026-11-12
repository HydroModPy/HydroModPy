"""The frozen Model holds the objects of the bound Flow, and its factories return new models."""

from __future__ import annotations

import dataclasses
import pickle
from types import MappingProxyType

import numpy as np
import pytest

from hydromodpy.model.boundaries.boundary_condition_registry import BoundaryConditionBundle
from hydromodpy.model.domain.geometry import CatchmentGeometry, ChannelRasters, RasterGeometry
from hydromodpy.model.flow import Flow, flow_profiles
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


def test_factory_start_wins() -> None:
    prior = PriorState(np.zeros((1, 6)), {}, "prior.zarr")

    assert _model_of(_bound_flow(), initial=prior).initial is prior


def test_pickled_model() -> None:
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


def test_unknown_start_refused() -> None:
    with pytest.raises(TypeError, match="Model.initial is one of"):
        make_model(initial="top")


@pytest.mark.parametrize("name", ["porosity", "properties", "k"])
def test_with_properties_refusal(name: str) -> None:
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
def test_no_backend_setting(backend_config) -> None:
    clashes = _member_names(Model, set()) & set(backend_config.model_fields)

    assert not clashes, f"The Model carries settings of {backend_config.__name__}: {clashes}"


# Expected values: what the MODFLOW 6 steady initialization of a pre-release
# returned on this lake and SFR payload, recorded to the bit.
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


def test_steady_averages_forcings() -> None:
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
def test_steady_keeps_single_forcings(grid) -> None:
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
def test_steady_recharge(case, initial, expected) -> None:
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


def test_steady_without_recharge() -> None:
    assert steady_variant(_transient(initial=SteadyStart())).recharge is None


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


def test_first_window_steady_start() -> None:
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


def test_first_window_cycles() -> None:
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


def test_bad_over_refused() -> None:
    _, window = _whole_and_window()

    with pytest.raises(TypeError, match="over is the Model of the whole simulation"):
        steady_variant(window.with_initial(SteadyStart(over="whole")))


def _field(param_id: str, value: object, **section: object) -> dict[str, object]:
    return {"field": {"id": param_id, "kind": "homogeneous", "value": value}, **section}


def _zones(values: dict[str, float]) -> dict[str, object]:
    return {
        "field": {
            "id": "K",
            "kind": "heterogeneous",
            "values": values,
            "field_spatial_id": "geology",
            "unit": "m/s",
        }
    }


_EXPONENTIAL = {"field_vertical_profile": {"kind": "exponential", "characteristic_depth": 9.0}}
_TWO_LAYERS = {
    "field_vertical_profile": {"kind": "tabulated", "depths": [0.0, 20.0], "factors": [1.0, 0.1]}
}


def _flow_config(**param: dict[str, object]) -> FlowConfig:
    return FlowConfig.model_validate({"param_list": list(param), "param": param})


DERIVED: tuple[tuple[str, FlowConfig, FlowConfig, tuple[str, ...]], ...] = (
    (
        "K replaced",
        _flow_config(K=_field("K", "1e-5 m/s"), Sy=_field("Sy", "0.1 -")),
        _flow_config(K=_field("K", "3e-5 m/s"), Sy=_field("Sy", "0.1 -")),
        ("K",),
    ),
    (
        "K scaled",
        _flow_config(K=_field("K", "1e-5 m/s"), Sy=_field("Sy", "0.1 -")),
        _flow_config(K=_field("K", f"{1e-5 * 2.5!r} m/s"), Sy=_field("Sy", "0.1 -")),
        ("K",),
    ),
    (
        "Sy",
        _flow_config(K=_field("K", "1e-5 m/s"), Sy=_field("Sy", "0.1 -")),
        _flow_config(K=_field("K", "1e-5 m/s"), Sy=_field("Sy", "0.25 -")),
        ("Sy",),
    ),
    (
        "K by zones",
        _flow_config(K=_zones({"granite": 1e-5, "schist": 2e-6})),
        _flow_config(K=_zones({"granite": 4e-5, "schist": 8e-6})),
        ("K",),
    ),
    (
        "K in two layers",
        _flow_config(K=_field("K", "1e-5 m/s", **_TWO_LAYERS)),
        _flow_config(K=_field("K", "2e-5 m/s", **_TWO_LAYERS)),
        ("K",),
    ),
    (
        "K decaying with depth",
        _flow_config(K=_field("K", "1e-5 m/s", **_EXPONENTIAL)),
        _flow_config(K=_field("K", "5e-6 m/s", **_EXPONENTIAL)),
        ("K",),
    ),
    (
        "a free id of a plugin",
        _flow_config(K=_field("K", "1e-5 m/s"), porosity=_field("porosity", 0.3)),
        _flow_config(K=_field("K", "1e-5 m/s"), porosity=_field("porosity", 0.35)),
        ("porosity",),
    ),
)


def _same_objects(left: object, right: object) -> bool:
    """Whether two members hold the same objects, as a backend compares them.

    ``Model`` makes its read-only mappings again on each ``replace`` and keeps
    the values they hold.
    """
    if isinstance(left, MappingProxyType) and isinstance(right, MappingProxyType):
        return left.keys() == right.keys() and all(left[key] is right[key] for key in left)
    if isinstance(left, BoundaryConditionBundle) and isinstance(right, BoundaryConditionBundle):
        return _same_objects(left.conditions, right.conditions) and (
            left.active_ids == right.active_ids
        )
    return left is right


def _built(config: FlowConfig, geometry, time, options) -> Model:
    return model_from_flow(Flow(config), geometry=geometry, time=time, options=options)


@pytest.mark.parametrize(
    ("case", "base", "trial", "moved"), DERIVED, ids=[case for case, *_ in DERIVED]
)
def test_derived_equals_built(
    case: str, base: FlowConfig, trial: FlowConfig, moved: tuple[str, ...]
) -> None:
    del case
    geometry, options = small_geometry(), default_options()
    time = ModelTime(grid=time_grid(10.0), regime="steady", first_period_steady=True)
    prepared = _built(base, geometry, time, options)

    derived = prepared.with_profiles(flow_profiles(trial, ids=moved))
    built = _built(trial, geometry, time, options)

    def contents(model: Model) -> dict[str, object]:
        return {name: profile.as_dict() for name, profile in model.properties.profiles.items()}

    assert contents(derived) == contents(built)
    assert list(derived.properties.profiles) == list(built.properties.profiles)
    for name, profile in derived.properties.profiles.items():
        if name not in moved:
            assert profile is prepared.properties.profiles[name]
    for member in dataclasses.fields(Model):
        if member.name != "properties":
            assert _same_objects(getattr(derived, member.name), getattr(prepared, member.name))
    assert derived.properties.overrides is not None
    assert dict(derived.properties.overrides) == dict(prepared.properties.overrides)


def test_with_profiles_refusal() -> None:
    model = make_model(properties=Properties(profiles={"K": 1e-5}))
    with pytest.raises(ValueError, match="Ss is none of them"):
        model.with_profiles({"Ss": 1e-6})


def test_flow_parameters() -> None:
    config = _flow_config(K=_field("K", "1e-5 m/s"), Sy=_field("Sy", "0.1 -"))
    flow = Flow(config)
    assert {name: param.as_dict() for name, param in flow.parameters.items()} == {
        name: param.as_dict() for name, param in flow_profiles(config).items()
    }
    assert list(flow_profiles(config, ids=["Sy"])) == ["Sy"]
    with pytest.raises(KeyError, match="declares no Ss"):
        flow_profiles(config, ids=["Ss"])
