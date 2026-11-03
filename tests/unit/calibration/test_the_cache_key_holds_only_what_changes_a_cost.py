"""The cache key is a whitelist: what changes the cost of a trial at given parameters.

The key was the whole ``[calibration]`` table minus a list of runtime keys, so a
new key of the section moved it silently and a change of method, seed, precision
or option re-solved trials whose cost had not changed. Now the same parameter
values hash to one key under two methods, seeds, precisions, budgets, option sets
and phase bounds, and to another under another output, block, window or
evaluator.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.optim.cache import params_hash
from hydromodpy.calibration.runners import state
from hydromodpy.calibration.runners.staged_runner import _phase_config

OUTPUT = {"support": "point", "variable": "head", "observes": "P1"}
BASE: dict[str, Any] = {
    "method": "scipy_nelder_mead",
    "max_trials": 5,
    "precision": 0.01,
    "seed": 3,
    "method_options": {"fatol": 1e-4},
    "parameters": {
        "k": {"path": "flow.properties.k_aquifer", "bounds": [1e-6, 1e-2], "search_space": "log"}
    },
    "objective": "nse",
    "variable": "discharge",
}


def _context(cfg: CalibrationConfig) -> dict[str, object]:
    return state.build_cache_context(
        cfg=cfg,
        trial_ctx=None,
        space=state.space_from_config(cfg),
        override_paths=state.override_paths(cfg),
        objective_entrypoint=None,
    )


def _hash(**changes: Any) -> str:
    cfg = CalibrationConfig.model_validate({**BASE, **changes})
    return params_hash({"k": 1e-4}, context=_context(cfg))


def test_the_schema_of_the_key_is_the_fourth() -> None:
    cfg = CalibrationConfig.model_validate(BASE)

    assert _context(cfg)["schema"] == "hydromodpy.calibration.params_hash.v4"


def test_the_key_is_flat_with_one_member_per_layer_of_code() -> None:
    context = _context(CalibrationConfig.model_validate(BASE))

    assert {
        "metric_rule_version",
        "model",
        "calibration",
        "override_paths",
        "parameter_space",
        "input_files",
        "mesh",
    } <= set(context)
    assert [name for name in context if name.startswith("code.")]
    assert "code_version" not in context, "a release number moves no hash"


def test_the_model_enters_as_written_and_without_its_workspace() -> None:
    class _Config(BaseModel):
        workspace: dict[str, str] = {"root": "/somewhere"}
        flow: dict[str, float] = {"K": 1e-4}
        transport: dict[str, float] = {"alpha": 0.1}

    written = _Config(flow={"K": 1e-4})
    trial_ctx = SimpleNamespace(
        base_cfg=written, ctx=SimpleNamespace(setup=SimpleNamespace(cell_mesh=None))
    )
    cfg = CalibrationConfig.model_validate(BASE)

    context = state.build_cache_context(
        cfg=cfg,
        trial_ctx=trial_ctx,
        space=state.space_from_config(cfg),
        override_paths=state.override_paths(cfg),
        objective_entrypoint=None,
    )

    assert context["model"] == {"flow": {"K": 1e-4}}, "no workspace, and no default written"


@pytest.mark.parametrize(
    "change",
    [
        {"method": "random_search", "precision": None, "method_options": {}},
        {"seed": 4},
        {"precision": 0.1},
        {"max_trials": 500},
        {"method_options": {"fatol": 1e-3}},
        {"batch_size": 4, "parallel": 4},
        {"save_runs": "best_n", "save_best_n": 3},
        {"use_cache": False},
        {"persist_iteration_detail": "none"},
        {"persist_trial_series": True},
        {"materialize_candidates": True},
        {"promote_phases": True},
        {"persistence": {"save_zarr": False}},
        {"uncertainty": {"cost_margin": "10%"}},
        {
            "parameters": {
                "k": {
                    "path": "flow.properties.k_aquifer",
                    "bounds": [1e-5, 1e-3],
                    "search_space": "identity",
                    "sampling": "log_uniform",
                }
            }
        },
    ],
    ids=lambda change: next(iter(change)),
)
def test_what_does_not_change_the_cost_of_a_trial_leaves_the_key_alone(change: dict) -> None:
    assert _hash(**change) == _hash()


@pytest.mark.parametrize(
    "change",
    [
        {"objective": "kge"},
        {"variable": "head"},
        {"scoring_window": {"start": "2001-01-01"}},
        {"warmup_periods": 12},
        {"reject_water_budget_above": 5.0},
        {"observed_station_id": "B2"},
        {"aggregate": {"min_samples": 30}},
        {"outputs": {"gauge": OUTPUT}, "variable": "gauge"},
        {
            "parameters": {
                "k": {
                    "path": "flow.properties.k_aquifer",
                    "bounds": [1e-6, 1e-2],
                    "mode": "scale",
                }
            }
        },
        {
            "parameters": {
                "k": {"path": "flow.properties.sy", "bounds": [1e-6, 1e-2], "search_space": "log"}
            }
        },
    ],
    ids=lambda change: next(iter(change)),
)
def test_what_changes_the_cost_of_a_trial_changes_the_key(change: dict) -> None:
    assert _hash(**change) != _hash()


def test_another_objective_block_changes_the_key() -> None:
    gauge = {"gauge": OUTPUT}
    one = {"name": "q", "metric": "nse", "uses_outputs": ["gauge"]}
    other = {**one, "metric": "kge"}

    assert _hash(outputs=gauge, objective_blocks=[one]) != _hash(
        outputs=gauge, objective_blocks=[other]
    )


def test_a_named_evaluator_changes_the_key_and_the_default_does_not() -> None:
    assert _hash(evaluator="hydromodpy_pipeline") == _hash()


def test_a_phase_narrower_than_its_section_reuses_the_trials_of_a_wider_search() -> None:
    wide = {"name": "wide", "parameters": ["k"], "objective": "nse"}
    narrow = {**wide, "name": "narrow", "bounds": {"k": [1e-5, 1e-3]}}
    cfg = CalibrationConfig.model_validate({**BASE, "phases": [wide, narrow]})
    first, second = (_phase_config(cfg, phase) for phase in cfg.phases)

    assert params_hash({"k": 1e-4}, context=_context(first)) == params_hash(
        {"k": 1e-4}, context=_context(second)
    )
    assert second.parameters["k"].bounds == [1e-5, 1e-3]
