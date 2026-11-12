"""Calibration parameters, their search space and how a candidate reaches the config.

A parameter has bounds in physical units and a search transform (identity, log
or logit). A candidate is written into the config by a dotted path, either
replacing the value or scaling it (a dimensionless multiplier).
"""

from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import BaseModel, Field

from hydromodpy.calibration.optim.parameters import (
    CalibParameter,
    ParameterSpace,
    apply_parameter_to_config,
    set_by_path,
)
from hydromodpy.model.flow_config import FlowParam
from hydromodpy.model.properties.field_param import FieldParam


class FieldValue:
    def __init__(self, value):
        self.value = value


class SyParam:
    def __init__(self, value):
        self.field = FieldValue(value)


class SyFlow:
    def __init__(self, value):
        self.param = {"Sy": SyParam(value)}


class SyConfig:
    # Plain objects, with the specific yield at flow.param.Sy.field.value.
    def __init__(self, value=0.1):
        self.flow = SyFlow(value)


class NestedK(BaseModel):
    value: float = 1.0


class KGroup(BaseModel):
    homogeneous: NestedK = Field(default_factory=NestedK)


class OuterConfig(BaseModel):
    K: KGroup = Field(default_factory=KGroup)
    Sy: float = 0.1


class LabelConfig(BaseModel):
    label: str = "alpha"


def outer_config(k=1.0):
    cfg = OuterConfig()
    cfg.K.homogeneous.value = k
    return cfg


def read(cfg, path):
    for part in path.split("."):
        cfg = cfg[part] if isinstance(cfg, dict) else getattr(cfg, part)
    return cfg


SY_PATH = "flow.param.Sy.field.value"
K_PATH = "K.homogeneous.value"

APPLIED = [
    pytest.param(
        SyConfig(0.1),
        CalibParameter(name="Sy", lower=0.5, upper=8.0, path=SY_PATH, mode="scale", units="-"),
        4.0,
        SY_PATH,
        0.4,
        id="scale inside the ceiling",
    ),
    pytest.param(
        SyConfig(0.1),
        CalibParameter(name="weird", lower=0.0, upper=100.0, path=SY_PATH, units="-"),
        99.0,
        SY_PATH,
        99.0,
        id="id unknown to the registry",
    ),
    pytest.param(
        outer_config(),
        CalibParameter(name="K", lower=1e-6, upper=1e-3, path=K_PATH, mode="replace"),
        2.5e-4,
        K_PATH,
        2.5e-4,
        id="replace",
    ),
    pytest.param(
        outer_config(k=4.0),
        CalibParameter(name="K", lower=0.1, upper=10.0, target=K_PATH, mode="scale"),
        3.0,
        K_PATH,
        12.0,
        id="scale the base value",
    ),
    pytest.param(
        outer_config(),
        CalibParameter(name="Sy", lower=0.02, upper=0.30, path="Sy", mode="replace"),
        0.15,
        "Sy",
        0.15,
        id="replace a flat field",
    ),
]


@pytest.mark.parametrize(("cfg", "parameter", "candidate", "path", "expected"), APPLIED)
def test_candidate_written_to_config(cfg, parameter, candidate, path, expected):
    apply_parameter_to_config(cfg, parameter, candidate)

    assert read(cfg, path) == pytest.approx(expected)


def scaled(path, mode="scale"):
    return CalibParameter(name="K", lower=0.1, upper=2.0, path=path, mode=mode)


# A declared name is also what the message gives back, so (?=...) checks two words in any order.
APPLY_REFUSALS = [
    pytest.param(
        SyConfig(0.1),
        CalibParameter(name="Sy", lower=1e-4, upper=0.9, path=SY_PATH, units="-"),
        0.9,
        "Sy",
        id="replaced value past the ceiling",
    ),
    pytest.param(
        outer_config(),
        CalibParameter(name="K", lower=0.0, upper=1.0, path="K.homogeneous.does_not_exist"),
        0.5,
        r"(?s)(?=.*calibration\.parameters\.K)(?=.*does_not_exist)",
        id="invalid path",
    ),
    pytest.param(
        SyConfig(),
        CalibParameter(name="K", lower=1e-8, upper=1e-2, path="flow.parem.value"),
        1e-5,
        r"(?s)(?=.*calibration\.parameters\.K)(?=.*flow\.parem\.value)",
        id="mistyped path names the key",
    ),
    pytest.param(
        outer_config(),
        CalibParameter(name="K", lower=0.0, upper=1.0, path=None, target=None),
        0.5,
        "has no target or path",
        id="no path",
    ),
    pytest.param(
        LabelConfig(),
        CalibParameter(name="label", lower=0.1, upper=10.0, path="label", mode="scale"),
        2.0,
        "numeric base",
        id="scale a string",
    ),
    pytest.param({"K": None}, scaled("K"), 2.0, "resolved to None", id="scale a missing base"),
    pytest.param({"K": 1.0}, scaled("K", "add"), 2.0, "unsupported mode 'add'", id="unknown mode"),
    pytest.param(
        {"K": 1.0}, scaled("gone"), 2.0, "Path segment 'gone' not found", id="scale, mapping"
    ),
    pytest.param(
        outer_config(), scaled("gone"), 2.0, "Path segment 'gone' not found", id="scale, object"
    ),
    pytest.param(
        {"K": {}},
        scaled("K.gone.value"),
        2.0,
        "Path segment 'gone' not found on dict",
        id="scale, path stops midway",
    ),
]


@pytest.mark.parametrize(("cfg", "parameter", "candidate", "match"), APPLY_REFUSALS)
def test_apply_refusals(cfg, parameter, candidate, match):
    with pytest.raises(ValueError, match=match):
        apply_parameter_to_config(cfg, parameter, candidate)


def test_set_by_path_on_a_mapping():
    cfg = {"K": {"value": 1.0}}

    set_by_path(cfg, "K.value", 2.0)

    assert cfg == {"K": {"value": 2.0}}


SET_BY_PATH_REFUSALS = [
    pytest.param({"K": {}}, "K.gone.value", "no 'gone' under K, which holds nothing", id="under K"),
    pytest.param(
        {"K": {}}, "Q.value", "no 'Q' under the configuration root, which holds K", id="at root"
    ),
]


@pytest.mark.parametrize(("cfg", "path", "match"), SET_BY_PATH_REFUSALS)
def test_set_by_path_refusals(cfg, path, match):
    with pytest.raises(ValueError, match=match):
        set_by_path(cfg, path, 1.0)


def declared(path=None, **fields):
    return {"x": {"bounds": [0.0, 1.0], **({"path": path} if path else {}), **fields}}


# Stage boundaries (a regime, a time window) say which model a stage runs. They belong to a
# phase's overrides, never to a search. A mesh setting would move the yardstick of the criterion.
SPACE_REFUSALS = [
    pytest.param(declared(p), "stage", id=p)
    for p in [
        "flow.flow_regime",
        "simulation.time.start_datetime",
        "simulation.time.end_datetime",
        "simulation.time.step_value",
        "simulation.time.step_unit",
    ]
] + [
    pytest.param(
        declared("flow.flow_regime"),
        r"(?s)(?=.*flow\.flow_regime)(?=.*overrides)",
        id="stage refusal points at overrides",
    ),
    pytest.param(declared("mesh.cell_size"), "mesh", id="mesh.cell_size"),
    pytest.param(declared("mesh.river_band"), "mesh", id="mesh.river_band"),
    pytest.param(declared("mesh.triangle.path"), "mesh", id="mesh.triangle.path"),
    pytest.param(
        {"m": {"bounds": [50.0, 500.0], "path": "mesh.cell_size"}},
        r"(?s)(?=.*mesh\.cell_size)(?=.*compare)",
        id="mesh refusal points at a sweep",
    ),
    pytest.param(
        {"m": {"bounds": [50.0, 500.0], "target": "mesh.cell_size"}}, "mesh", id="mesh target"
    ),
    pytest.param(
        {"K": {"bounds": [1e-6, 1e-3], "path": K_PATH, "mode": "multiply"}},
        "mode must be 'replace' or 'scale'",
        id="unknown mode",
    ),
    pytest.param({"K": {}}, "no bounds", id="no bounds"),
    pytest.param(
        {"x": {"bounds": [2.0, 1.0]}}, "lower bound must be < upper", id="reversed bounds"
    ),
    pytest.param(
        {"x": {"bounds": [0.0, 1.0], "search_space": "log"}},
        "log search space requires lower > 0",
        id="log from zero",
    ),
    pytest.param(
        {"x": {"bounds": [0.1, 1.0], "search_space": "logit"}},
        "requires 0 < lower < upper < 1",
        id="logit past one",
    ),
    pytest.param(
        {"x": {"bounds": [0.1, 0.5], "sampling": "beta"}}, "unknown sampling 'beta'", id="sampling"
    ),
    pytest.param(
        {"x": {"bounds": [0.0, 1.0], "sampling": "log_uniform"}},
        "log_uniform sampling requires",
        id="log uniform from zero",
    ),
]


@pytest.mark.parametrize(("mapping", "match"), SPACE_REFUSALS)
def test_space_refusals(mapping, match):
    with pytest.raises(ValueError, match=match):
        ParameterSpace.from_toml_mapping(mapping)


def test_duplicate_names_refused():
    with pytest.raises(ValueError, match="Duplicate"):
        ParameterSpace(
            [CalibParameter(name="a", lower=0, upper=1), CalibParameter(name="a", lower=0, upper=2)]
        )


ALLOWED = [
    pytest.param(
        {"Sy": {"bounds": [1e-4, 0.5], "path": SY_PATH}}, "Sy", 0.5, id="inside the ceiling"
    ),
    pytest.param(
        {"bedleak": {"bounds": [1e-12, 1e-2], "path": "flow.sinks_sources.lakes.a.bedleak"}},
        "bedleak",
        1e-2,
        id="id unknown to the registry",
    ),
]


@pytest.mark.parametrize(("mapping", "name", "upper"), ALLOWED)
def test_bounds_the_registry_allows(mapping, name, upper):
    assert ParameterSpace.from_toml_mapping(mapping)[name].upper == pytest.approx(upper)


def test_log_transform_roundtrip():
    p = CalibParameter(name="k", lower=1e-6, upper=1e-3, search_space="log")
    assert math.isclose(p.lower_transformed, -6.0)
    assert math.isclose(p.upper_transformed, -3.0)
    y = p.to_transformed(1e-4)
    assert math.isclose(y, -4.0)
    assert math.isclose(p.to_physical(y), 1e-4)


def test_logit_transform_roundtrip():
    p = CalibParameter(name="s", lower=0.05, upper=0.5, search_space="logit")
    y = p.to_transformed(0.2)
    assert math.isclose(p.to_physical(y), 0.2, rel_tol=1e-9)


def test_transformed_bounds():
    space = ParameterSpace([CalibParameter(name="k", lower=1e-6, upper=1e-3, search_space="log")])
    tb = space.transformed_bounds
    assert math.isclose(tb["k"][0], -6.0)
    assert math.isclose(tb["k"][1], -3.0)


@pytest.mark.parametrize("convert", [CalibParameter.to_transformed, CalibParameter.to_physical])
def test_unknown_search_space_refused(convert):
    param = CalibParameter(name="x", lower=0.0, upper=1.0, search_space="sqrt")

    with pytest.raises(ValueError, match="Unknown search space: 'sqrt'"):
        convert(param, 0.5)


def test_logit_refuses_unit_bounds():
    param = CalibParameter(name="s", lower=0.05, upper=0.5, search_space="logit")

    with pytest.raises(ValueError, match="requires 0<x<1, got 1.0"):
        param.to_transformed(1.0)


def test_prior_only_for_normal_sampling():
    normal = ParameterSpace([CalibParameter(name="x", lower=0.0, upper=6.0, sampling="normal")])
    uniform = ParameterSpace([CalibParameter(name="x", lower=0.0, upper=6.0)])

    assert normal.default_prior_mean_std() == ([3.0], [1.0])
    assert uniform.default_prior_mean_std() is None


def test_physical_bounds_and_description():
    space = ParameterSpace(
        [
            CalibParameter(name="a", lower=0.0, upper=1.0),
            CalibParameter(name="b", lower=2.0, upper=3.0),
        ]
    )

    assert space.physical_bounds() == {"a": (0.0, 1.0), "b": (2.0, 3.0)}
    assert set(space.describe_values({"b": 2.5})) == {"b"}


# A trial forks a deep copy of the config, sets its value by path, then rebuilds the runtime
# field from the typed config. Trials run in parallel, so they must never share state.
def base_flow_param() -> FlowParam:
    return FlowParam.model_validate(
        {
            "field": {"id": "K", "kind": "homogeneous", "unit": "m/s", "value": 1e-4},
            "field_vertical_profile": {"kind": "exponential", "characteristic_depth": 10.0},
        }
    )


def depth_after_trial(base: FlowParam, trial_value: float) -> float:
    trial_cfg = base.model_copy(deep=True)
    set_by_path(trial_cfg, "field_vertical_profile.characteristic_depth", trial_value)
    field = FieldParam.from_dict(trial_cfg.resolved_payload(param_id="K"))
    return field.vertical_profile["characteristic_depth"]


def test_trial_spares_the_base():
    base = base_flow_param()

    assert depth_after_trial(base, 75.0) == pytest.approx(75.0)
    assert base.field_vertical_profile.characteristic_depth == pytest.approx(10.0)


def test_trials_move_the_depth():
    base = base_flow_param()

    depths = [depth_after_trial(base, value) for value in (5.0, 40.0)]

    assert depths == [pytest.approx(5.0), pytest.approx(40.0)]


def test_parallel_trials_do_not_contaminate():
    base = base_flow_param()
    trial_values = [5.0, 15.0, 30.0, 60.0, 120.0] * 4

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda value: depth_after_trial(base, value), trial_values))

    assert results == pytest.approx(trial_values)
    assert base.field_vertical_profile.characteristic_depth == pytest.approx(10.0)
