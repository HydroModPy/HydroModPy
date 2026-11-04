"""Tests of `optim.parameters`."""

from __future__ import annotations

import math
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated

import numpy as np
import pytest
from pydantic import BaseModel, Field

from hydromodpy.calibration.optim.engine import CalibrationEngine
from hydromodpy.calibration.optim.optimizer import EvaluationResult, build_optimizer, engine_traits
from hydromodpy.calibration.optim.parameters import (
    CalibParameter,
    ParameterSpace,
    apply_parameter_to_config,
    set_by_path,
)
from hydromodpy.physics.flow.flow_param_config import FlowParam
from hydromodpy.spatial.field.field_param import FieldParam
from tests.unit.calibration._factories_search import make_space, result_of

# From test_a_candidate_meets_the_physical_registry.py
# A candidate the search writes has to face the same ceiling a literal does.
#
# The declared bounds are checked at load time, which refuses the impossible
# region once. That is not enough for ``mode = "scale"``: there the candidate is a
# multiplier, so the value that reaches the configuration is the base times the
# sample, and legal bounds on the multiplier say nothing about where the product
# lands. A scale of 8 on a specific yield of 0.1 writes 0.8, past the physical
# ceiling of 0.5, and only the solver would notice.


class _Field:
    def __init__(self, value: float) -> None:
        self.value = value


class _Param:
    def __init__(self, value: float) -> None:
        self.field = _Field(value)


class _Flow:
    def __init__(self, value: float) -> None:
        self.param = {"Sy": _Param(value)}


class _Cfg:
    def __init__(self, value: float = 0.1) -> None:
        self.flow = _Flow(value)


def _parameter(mode: str, name: str = "Sy") -> CalibParameter:
    return CalibParameter(
        name=name, lower=0.5, upper=8.0, path=f"flow.param.{name}.field.value", mode=mode, units="-"
    )


def test_a_scale_that_lands_past_the_ceiling_is_refused() -> None:
    cfg = _Cfg(0.1)

    with pytest.raises(ValueError, match="Sy"):
        apply_parameter_to_config(cfg, _parameter("scale"), 8.0)


def test_the_refusal_names_the_value_that_would_have_been_written() -> None:
    with pytest.raises(ValueError) as caught:
        apply_parameter_to_config(_Cfg(0.1), _parameter("scale"), 8.0)

    assert "0.8" in str(caught.value)


def test_a_scale_that_stays_inside_is_written() -> None:
    cfg = _Cfg(0.1)

    apply_parameter_to_config(cfg, _parameter("scale"), 4.0)

    assert cfg.flow.param["Sy"].field.value == pytest.approx(0.4)


def test_a_replaced_value_is_checked_too() -> None:
    param = CalibParameter(
        name="Sy", lower=1e-4, upper=0.9, path="flow.param.Sy.field.value", units="-"
    )

    with pytest.raises(ValueError, match="Sy"):
        apply_parameter_to_config(_Cfg(0.1), param, 0.9)


def test_an_id_the_registry_does_not_know_is_left_alone() -> None:
    cfg = _Cfg(0.1)
    param = CalibParameter(
        name="weird", lower=0.0, upper=100.0, path="flow.param.Sy.field.value", units="-"
    )

    apply_parameter_to_config(cfg, param, 99.0)

    assert cfg.flow.param["Sy"].field.value == pytest.approx(99.0)


# From test_a_stage_boundary_is_not_a_dimension.py
# A regime and a time window are stage boundaries, not axes of a search.
#
# ``[calibration.parameters.<name>].path`` takes any dotted path, so nothing
# stopped a file from declaring ``flow.flow_regime`` or ``simulation.time.*`` as a
# calibrated parameter. Both are refused for the same reason, and it is not a
# technical oversight: they say WHICH MODEL a stage runs, and a stage is what a
# phase declares in its own ``overrides``. Searching over one of them asks the
# optimizer to pick between two different models on a cost that only compares
# trials of one.
#
# A regime is also categorical, and every candidate reaches the config through
# ``float(value)``, so the search would write 0.5 into a field whose two legal
# values are two words.


def _space(path: str) -> ParameterSpace:
    return ParameterSpace.from_toml_mapping({"p": {"bounds": [0.0, 1.0], "path": path}})


@pytest.mark.parametrize(
    "path",
    [
        "flow.flow_regime",
        "simulation.time.start_datetime",
        "simulation.time.end_datetime",
        "simulation.time.step_value",
        "simulation.time.step_unit",
    ],
)
def test_a_stage_boundary_is_refused(path: str) -> None:
    with pytest.raises(ValueError, match="stage"):
        _space(path)


def test_the_refusal_points_at_the_phase_overrides() -> None:
    with pytest.raises(ValueError) as caught:
        _space("flow.flow_regime")

    message = str(caught.value)
    assert "flow.flow_regime" in message
    assert "overrides" in message


@pytest.mark.parametrize(
    ("declaration", "name"),
    [
        ({"bounds": [1e-8, 1e-2], "search_space": "log", "path": "flow.param.K.field.value"}, "K"),
        ({"bounds": [1.0, 2.0], "path": "flow.flow_regime_factor"}, "c"),
        ({"bounds": [1.0, 2.0], "path": "simulation.something_else"}, "c"),
        ({"bounds": [1.0, 2.0], "path": "flow.param.mesh_factor.field.value"}, "c"),
    ],
    ids=["hydraulic_property", "prefix_of_the_word", "other_simulation_key", "contains_the_word"],
)
def test_a_path_the_refusals_do_not_name_is_untouched(declaration: dict, name: str) -> None:
    """A refusal is on the field or the section, not on a prefix or a substring."""
    space = ParameterSpace.from_toml_mapping({name: declaration})

    assert [param.name for param in space] == [name]


# From test_a_trial_rebuilds_the_vertical_profile_field.py
# A trial rebuilds the runtime field with its own characteristic_depth.
#
# A trial writes the typed config through ``set_by_path``, the same way
# ``TrialContext.fork`` does (``hydromodpy/calibration/runners/trial.py``: a
# fresh ``model_copy(deep=True)`` of the base config, then one ``set_by_path``
# per sampled parameter). The runtime ``FieldParam`` the solver actually reads
# is then rebuilt from that typed config through ``FlowParam.resolved_payload``
# and the registered ``FieldParamLike`` factory, exactly as
# ``ProcessSpatial.set_parameters_from_config`` does when a trial resets
# ``flow = None`` and the next pipeline step rebuilds it. Each trial forks a
# deep copy, so concurrent trials (``TrialSandbox`` runs them in parallel) never
# share the mutable ``FieldVerticalProfileSection`` instance.


def _base_flow_param() -> FlowParam:
    return FlowParam.model_validate(
        {
            "field": {"id": "K", "kind": "homogeneous", "unit": "m/s", "value": 1e-4},
            "field_vertical_profile": {"kind": "exponential", "characteristic_depth": 10.0},
        }
    )


def _rebuild_for_trial(base: FlowParam, trial_value: float) -> FieldParam:
    """Fork the way a trial does, then rebuild the runtime field from it."""
    trial_cfg = base.model_copy(deep=True)
    set_by_path(trial_cfg, "field_vertical_profile.characteristic_depth", trial_value)
    payload = trial_cfg.resolved_payload(param_id="K")
    return FieldParam.from_dict(payload)


def test_a_trial_value_rebuilds_the_field_without_touching_the_base() -> None:
    base = _base_flow_param()

    field = _rebuild_for_trial(base, 75.0)

    assert field.vertical_profile["characteristic_depth"] == pytest.approx(75.0)
    assert base.field_vertical_profile.characteristic_depth == pytest.approx(10.0)


def test_two_trials_move_the_depth_each_time() -> None:
    base = _base_flow_param()

    depths = [
        _rebuild_for_trial(base, trial_value).vertical_profile["characteristic_depth"]
        for trial_value in (5.0, 40.0)
    ]

    assert depths == [pytest.approx(5.0), pytest.approx(40.0)]


def test_parallel_trials_do_not_cross_contaminate() -> None:
    base = _base_flow_param()
    trial_values = [5.0, 15.0, 30.0, 60.0, 120.0] * 4

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(
                lambda value: _rebuild_for_trial(base, value).vertical_profile[
                    "characteristic_depth"
                ],
                trial_values,
            )
        )

    assert results == pytest.approx(trial_values)
    # The base trial context a concurrent fork started from is never mutated.
    assert base.field_vertical_profile.characteristic_depth == pytest.approx(10.0)


# From test_an_initial_simplex_stays_whole_at_a_bound.py
# A start point on a bound still gets a simplex with distinct vertices.
#
# The vertex of an axis is the start plus 10 % of the range, clipped to the
# bounds. A start on the upper bound clipped back onto itself and duplicated the
# start vertex, so the simplex was flat along that axis.


def _space__initial_simplex() -> ParameterSpace:
    return make_space(("x", 0.0, 1.0), ("y", -2.0, 2.0))


def _vertices(start_at) -> np.ndarray:
    opt = build_optimizer("scipy_nelder_mead", _space__initial_simplex(), seed=0, start_at=start_at)
    return np.array([[s.values["x"], s.values["y"]] for s in opt.ask(3)], dtype=float)


def _rank(vertices: np.ndarray) -> int:
    return int(np.linalg.matrix_rank(vertices[1:] - vertices[0]))


@pytest.mark.parametrize(
    "start_at",
    [[1.0, 0.0], [0.0, 2.0], [1.0, 2.0], [0.95, 1.9]],
    ids=["x_on_upper", "y_on_upper", "corner", "inside_one_step"],
)
def test_a_start_on_the_upper_bound_still_spans_the_space(start_at) -> None:
    vertices = _vertices(start_at)

    assert len({tuple(v) for v in vertices}) == 3
    assert _rank(vertices) == 2


def test_a_start_inside_the_box_steps_up_as_before() -> None:
    vertices = _vertices([0.5, 0.0])

    np.testing.assert_allclose(vertices[0], [0.5, 0.0])
    np.testing.assert_allclose(vertices[1], [0.6, 0.0])
    np.testing.assert_allclose(vertices[2], [0.5, 0.4])


# From test_bounds_meet_the_physical_registry.py
# A declared calibration bound must face the same physical ceiling as a literal.
#
# ``PHYSICAL_BOUNDS`` refuses a specific yield of 0.8 written as a literal in
# ``[flow.param.Sy.field]``, because no rock drains 80 percent of its volume by
# gravity. It never saw ``[calibration.parameters.Sy] bounds``, so the same 0.8
# loaded without a word and the search spent its budget in a region the model
# declares impossible. The ceiling that matters is the one on the path a
# calibration actually takes.
#
# Checked on the bounds rather than on each sampled value: the search never leaves
# its bounds, so refusing the declaration refuses every candidate it could have
# produced, once, before the first solve.


def test_a_bound_above_the_ceiling_is_refused() -> None:
    """0.8 is out of range for a specific yield, declared or written."""
    with pytest.raises(ValueError) as failure:
        ParameterSpace.from_toml_mapping(
            {"Sy": {"bounds": [1e-4, 0.8], "path": "flow.param.Sy.field.value"}}
        )

    message = str(failure.value)
    assert "Sy" in message
    assert "0.8" in message


def test_a_bound_inside_the_ceiling_loads() -> None:
    """The guard only refuses what the registry declares impossible."""
    space = ParameterSpace.from_toml_mapping(
        {"Sy": {"bounds": [1e-4, 0.5], "path": "flow.param.Sy.field.value"}}
    )

    assert space["Sy"].upper == pytest.approx(0.5)


def test_an_uncatalogued_parameter_is_left_alone() -> None:
    """An id the registry does not know keeps working, as it does elsewhere."""
    space = ParameterSpace.from_toml_mapping(
        {"bedleak": {"bounds": [1e-12, 1e-2], "path": "flow.sinks_sources.lakes.a.bedleak"}}
    )

    assert space["bedleak"].upper == pytest.approx(1e-2)


def test_the_name_that_is_checked_is_the_declared_one() -> None:
    """The table key is the parameter id, which is what the registry keys on."""
    with pytest.raises(ValueError, match="Sy"):
        ParameterSpace.from_toml_mapping(
            {"Sy": {"bounds": [0.0, 0.95], "path": "flow.param.Sy.field.value"}}
        )


# From test_calibration_parameters.py
# Unit tests for hydromodpy.calibration.optim.parameters.


class TestCalibParameter:
    def test_identity_transform_roundtrip(self):
        p = CalibParameter(name="x", lower=0.0, upper=10.0, search_space="identity")
        assert p.to_transformed(5.0) == 5.0
        assert p.to_physical(5.0) == 5.0

    def test_log_transform_roundtrip(self):
        p = CalibParameter(name="k", lower=1e-6, upper=1e-3, search_space="log")
        assert math.isclose(p.lower_transformed, -6.0)
        assert math.isclose(p.upper_transformed, -3.0)
        y = p.to_transformed(1e-4)
        assert math.isclose(y, -4.0)
        assert math.isclose(p.to_physical(y), 1e-4)

    def test_log_rejects_nonpositive(self):
        p = CalibParameter(name="k", lower=1e-6, upper=1.0, search_space="log")
        with pytest.raises(ValueError):
            p.to_transformed(0.0)

    def test_logit_transform_roundtrip(self):
        p = CalibParameter(name="s", lower=0.05, upper=0.5, search_space="logit")
        x = 0.2
        y = p.to_transformed(x)
        assert math.isclose(p.to_physical(y), x, rel_tol=1e-9)


class TestParameterSpace:
    def test_dim_and_names(self):
        space = ParameterSpace(
            [
                CalibParameter(name="a", lower=0.0, upper=1.0),
                CalibParameter(name="b", lower=-1.0, upper=1.0),
            ]
        )
        assert space.dim == 2
        assert space.names == ("a", "b")

    def test_duplicate_names_rejected(self):
        with pytest.raises(ValueError, match="Duplicate"):
            ParameterSpace(
                [
                    CalibParameter(name="a", lower=0, upper=1),
                    CalibParameter(name="a", lower=0, upper=2),
                ]
            )

    def test_from_toml_fails_without_bounds(self):
        with pytest.raises(ValueError, match="no bounds"):
            ParameterSpace.from_toml_mapping({"K": {}})

    def test_transformed_bounds(self):
        space = ParameterSpace(
            [CalibParameter(name="k", lower=1e-6, upper=1e-3, search_space="log")]
        )
        tb = space.transformed_bounds
        assert math.isclose(tb["k"][0], -6.0)
        assert math.isclose(tb["k"][1], -3.0)


# From test_da_mh_gp_runs_one_trial_at_a_time.py
# ``da_mh_gp`` evaluates one trial at a time, and a parallel setting does not hang it.
#
# The chain proposes its next point only once the previous one is told. With
# ``parallel > 1`` or ``batch_size > 1`` the engine asked for several points in
# one batch, and the second ``next_point`` waited forever for a tell that comes
# after the batch. The engine claimed ``supports_parallel``, so no check said so.


TIMEOUT_S = 60.0


def _space__da_mh() -> ParameterSpace:
    return make_space(("x", -4.0, 4.0), ("y", -4.0, 4.0))


def _evaluate(suggestion):
    x, y = float(suggestion.values["x"]), float(suggestion.values["y"])
    return result_of(suggestion, float(np.hypot(x - 1.0, y + 2.0)))


def _optimizer():
    return build_optimizer(
        "da_mh_gp",
        _space__da_mh(),
        chain_length=12,
        n_init=4,
        burn_in=2,
        proposal_sigma=0.5,
        seed=3,
        sigma_noise=0.5,
    )


def test_the_engine_says_it_runs_one_trial_at_a_time() -> None:
    assert engine_traits("da_mh_gp").supports_parallel is False


@pytest.mark.parametrize("setting", [{"parallel": 3}, {"batch_size": 4}])
def test_a_parallel_setting_finishes(setting: dict[str, int]) -> None:
    optimizer = _optimizer()
    engine = CalibrationEngine(
        space=_space__da_mh(), optimizer=optimizer, evaluator=_evaluate, max_trials=12, **setting
    )
    outcome: dict[str, object] = {}
    worker = threading.Thread(target=lambda: outcome.update(session=engine.run()), daemon=True)

    worker.start()
    worker.join(TIMEOUT_S)

    assert not worker.is_alive(), "the search waited for a point the chain cannot propose"
    assert outcome["session"].history


# From test_parameter_apply.py
# Tests for parameter mode support and config application helpers.
#
# Covers Phase 2 of the calibration integration:
#
# - CalibParameter gains ``target`` / ``mode``.
# - ParameterSpace.from_toml_mapping hydrates both.
# - apply_parameter_to_config resolves the dotted path and applies the
#   chosen mode ('replace' writes the value as-is, 'scale' multiplies the
#   base value by the candidate).


# ---------------------------------------------------------------------------
# Minimal Pydantic fixture that mirrors a nested config tree
# ---------------------------------------------------------------------------
class _InnerCfg(BaseModel):
    value: float = 1.0


class _MiddleCfg(BaseModel):
    homogeneous: _InnerCfg = Field(default_factory=_InnerCfg)


class _OuterCfg(BaseModel):
    K: _MiddleCfg = Field(default_factory=_MiddleCfg)
    Sy: Annotated[float, Field()] = 0.1


class TestSpaceFromTomlMappingHydratesModeAndTarget:
    def test_mode_defaults_to_replace(self):
        space = ParameterSpace.from_toml_mapping(
            {"K": {"bounds": [1e-6, 1e-3], "path": "K.homogeneous.value"}}
        )
        param = space["K"]
        assert param.mode == "replace"
        assert param.target is None
        assert param.path == "K.homogeneous.value"
        assert param.effective_path == "K.homogeneous.value"

    def test_target_wins_over_path(self):
        space = ParameterSpace.from_toml_mapping(
            {
                "K": {
                    "bounds": [1e-6, 1e-3],
                    "path": "legacy.path",
                    "target": "K.homogeneous.value",
                    "mode": "scale",
                }
            }
        )
        param = space["K"]
        assert param.target == "K.homogeneous.value"
        assert param.mode == "scale"
        assert param.effective_path == "K.homogeneous.value"

    def test_rejects_unknown_mode(self):
        with pytest.raises(ValueError, match="mode must be 'replace' or 'scale'"):
            ParameterSpace.from_toml_mapping(
                {"K": {"bounds": [1e-6, 1e-3], "path": "K.homogeneous.value", "mode": "multiply"}}
            )


class TestApplyParameterToConfig:
    def test_replace_writes_candidate_value(self):
        cfg = _OuterCfg()
        param = CalibParameter(
            name="K", lower=1e-6, upper=1e-3, path="K.homogeneous.value", mode="replace"
        )
        apply_parameter_to_config(cfg, param, 2.5e-4)
        assert cfg.K.homogeneous.value == pytest.approx(2.5e-4)

    def test_scale_multiplies_base_value(self):
        cfg = _OuterCfg()
        cfg.K.homogeneous.value = 4.0
        param = CalibParameter(
            name="K", lower=0.1, upper=10.0, target="K.homogeneous.value", mode="scale"
        )
        apply_parameter_to_config(cfg, param, 3.0)
        assert cfg.K.homogeneous.value == pytest.approx(12.0)

    def test_replace_flat_field(self):
        cfg = _OuterCfg()
        param = CalibParameter(name="Sy", lower=0.02, upper=0.30, path="Sy", mode="replace")
        apply_parameter_to_config(cfg, param, 0.15)
        assert cfg.Sy == pytest.approx(0.15)

    def test_rejects_invalid_path(self):
        cfg = _OuterCfg()
        param = CalibParameter(
            name="K", lower=0.0, upper=1.0, path="K.homogeneous.does_not_exist", mode="replace"
        )
        with pytest.raises(ValueError, match=r"calibration\.parameters\.K") as failure:
            apply_parameter_to_config(cfg, param, 0.5)
        assert "does_not_exist" in str(failure.value)

    def test_rejects_missing_path(self):
        param = CalibParameter(
            name="K", lower=0.0, upper=1.0, path=None, target=None, mode="replace"
        )
        with pytest.raises(ValueError, match="has no target or path"):
            apply_parameter_to_config(_OuterCfg(), param, 0.5)

    def test_scale_requires_numeric_base(self):
        class _StrCfg(BaseModel):
            label: str = "alpha"

        cfg = _StrCfg()
        param = CalibParameter(name="label", lower=0.1, upper=10.0, path="label", mode="scale")
        with pytest.raises(ValueError, match="numeric base"):
            apply_parameter_to_config(cfg, param, 2.0)


class TestWhatTheSpaceRefuses:
    @pytest.mark.parametrize("name", ["transform", "inverse"])
    def test_an_unknown_search_space_is_refused(self, name) -> None:
        param = CalibParameter(name="x", lower=0.0, upper=1.0, search_space="sqrt")

        with pytest.raises(ValueError, match="Unknown search space: 'sqrt'"):
            (param.to_transformed if name == "transform" else param.to_physical)(0.5)

    def test_logit_refuses_a_value_outside_the_open_unit_interval(self) -> None:
        param = CalibParameter(name="s", lower=0.05, upper=0.5, search_space="logit")

        with pytest.raises(ValueError, match="requires 0<x<1, got 1.0"):
            param.to_transformed(1.0)

    @pytest.mark.parametrize(
        ("declaration", "match"),
        [
            ({"bounds": [2.0, 1.0]}, "lower bound must be < upper"),
            ({"bounds": [0.0, 1.0], "search_space": "log"}, "log search space requires lower > 0"),
            ({"bounds": [0.1, 1.0], "search_space": "logit"}, "requires 0 < lower < upper < 1"),
            ({"bounds": [0.1, 0.5], "sampling": "beta"}, "unknown sampling 'beta'"),
            ({"bounds": [0.0, 1.0], "sampling": "log_uniform"}, "log_uniform sampling requires"),
        ],
    )
    def test_a_declaration_that_cannot_be_searched_is_refused(self, declaration, match) -> None:
        with pytest.raises(ValueError, match=match):
            ParameterSpace.from_toml_mapping({"x": declaration})

    def test_a_normal_sampling_gives_a_prior_and_the_others_give_none(self) -> None:
        normal = ParameterSpace([CalibParameter(name="x", lower=0.0, upper=6.0, sampling="normal")])
        uniform = ParameterSpace([CalibParameter(name="x", lower=0.0, upper=6.0)])

        assert normal.default_prior_mean_std() == ([3.0], [1.0])
        assert uniform.default_prior_mean_std() is None

    def test_the_physical_bounds_and_the_description_keep_the_declared_ones(self) -> None:
        space = ParameterSpace(
            [
                CalibParameter(name="a", lower=0.0, upper=1.0),
                CalibParameter(name="b", lower=2.0, upper=3.0),
            ]
        )

        assert space.physical_bounds() == {"a": (0.0, 1.0), "b": (2.0, 3.0)}
        assert set(space.describe_values({"b": 2.5})) == {"b"}


class TestPathsAreWalkedAndRefused:
    def test_a_mapping_config_takes_the_value_at_its_leaf(self) -> None:
        cfg = {"K": {"value": 1.0}}

        set_by_path(cfg, "K.value", 2.0)

        assert cfg == {"K": {"value": 2.0}}

    @pytest.mark.parametrize(
        ("cfg", "path", "match"),
        [
            ({"K": {}}, "K.gone.value", "no 'gone' under K, which holds nothing"),
            ({"K": {}}, "Q.value", "no 'Q' under the configuration root, which holds K"),
        ],
    )
    def test_a_missing_segment_of_a_mapping_lists_what_is_there(self, cfg, path, match) -> None:
        with pytest.raises(ValueError, match=match):
            set_by_path(cfg, path, 1.0)

    def test_a_scale_needs_a_base_value_that_exists(self) -> None:
        param = CalibParameter(name="K", lower=0.1, upper=2.0, path="K", mode="scale")

        with pytest.raises(ValueError, match="resolved to None"):
            apply_parameter_to_config({"K": None}, param, 2.0)

    def test_a_mode_nobody_handles_is_refused_when_written(self) -> None:
        param = CalibParameter(name="K", lower=0.1, upper=2.0, path="K", mode="add")

        with pytest.raises(ValueError, match="unsupported mode 'add'"):
            apply_parameter_to_config({"K": 1.0}, param, 2.0)

    @pytest.mark.parametrize("cfg", [{"K": 1.0}, _OuterCfg()], ids=["mapping", "object"])
    def test_a_scale_over_a_missing_path_is_refused(self, cfg) -> None:
        param = CalibParameter(name="K", lower=0.1, upper=2.0, path="gone", mode="scale")

        with pytest.raises(ValueError, match="Path segment 'gone' not found"):
            apply_parameter_to_config(cfg, param, 2.0)

    def test_a_scale_over_a_path_that_stops_midway_is_refused(self) -> None:
        param = CalibParameter(name="K", lower=0.1, upper=2.0, path="K.gone.value", mode="scale")

        with pytest.raises(ValueError, match="Path segment 'gone' not found on dict"):
            apply_parameter_to_config({"K": {}}, param, 2.0)


# From test_parameter_path_errors_name_the_key.py
# A mistyped calibration path must say which TOML key is wrong.
#
# ``set_by_path`` walks a dotted string with ``getattr`` and, on a miss, named the
# Python class it had reached: ``Path segment 'parem' not found on FlowConfig``.
# That sentence carries no file, no TOML key, no fix, and a noun the person who
# wrote the file has never seen. It is the only calibration failure that reaches
# the CLI's last-resort handler, so it also arrives with no context of its own.


class _Field__parameter_path:
    def __init__(self) -> None:
        self.value = 1.0


class _Flow__parameter_path:
    def __init__(self) -> None:
        self.field = _Field__parameter_path()


class _Config:
    def __init__(self) -> None:
        self.flow = _Flow__parameter_path()


def test_the_message_carries_the_whole_path() -> None:
    """Naming the segment alone leaves the reader guessing where it sits."""
    with pytest.raises(ValueError) as failure:
        set_by_path(_Config(), "flow.parem.value", 2.0)

    message = str(failure.value)
    assert "flow.parem.value" in message
    assert "parem" in message


def test_the_message_names_the_parameter_that_declared_it() -> None:
    """The reader looks for a TOML key, so the error has to name one."""
    param = CalibParameter(name="K", lower=1e-8, upper=1e-2, path="flow.parem.value")

    with pytest.raises(ValueError) as failure:
        apply_parameter_to_config(_Config(), param, 1e-5)

    message = str(failure.value)
    assert "calibration.parameters.K" in message
    assert "flow.parem.value" in message


def test_a_good_path_still_writes() -> None:
    """The guard only shapes the failure."""
    config = _Config()
    set_by_path(config, "flow.field.value", 3.0)
    assert config.flow.field.value == 3.0


# From test_the_mesh_is_not_a_calibrated_parameter.py
# A mesh setting is not a parameter a search may move.
#
# The mesh appears in the configuration next to the hydraulic properties, and a
# calibration parameter takes any dotted path, so nothing stopped a file from
# searching over a mesh resolution. Two reasons it must not:
#
# The criterion moves with the mesh. The validity bound of the stream-network
# method is normalized by cell size precisely because the distances it measures
# shrink as the mesh refines. Optimizing the mesh against that criterion is
# circular: the search improves the number by changing the yardstick.
#
# And a mesh that cannot be rebuilt bit for bit is cached by its request, so each
# value a search tried would leave one more cached mesh in the project and score
# a model nobody can reproduce from the chosen value alone.
#
# The route for a mesh question is a sweep: one run per mesh, compared, and read
# for convergence rather than for a best score.


def _declaration(path: str) -> dict[str, dict[str, object]]:
    return {"m": {"bounds": [50.0, 500.0], "path": path}}


@pytest.mark.parametrize("path", ["mesh.cell_size", "mesh.river_band", "mesh.triangle.path"])
def test_a_mesh_path_is_refused(path: str) -> None:
    with pytest.raises(ValueError, match="mesh"):
        ParameterSpace.from_toml_mapping(_declaration(path))


def test_the_refusal_points_at_the_route_that_works() -> None:
    with pytest.raises(ValueError) as caught:
        ParameterSpace.from_toml_mapping(_declaration("mesh.cell_size"))

    message = str(caught.value)
    assert "mesh.cell_size" in message
    assert "compare" in message


def test_a_target_naming_the_mesh_is_refused_too() -> None:
    with pytest.raises(ValueError, match="mesh"):
        ParameterSpace.from_toml_mapping(
            {"m": {"bounds": [50.0, 500.0], "target": "mesh.cell_size"}}
        )
