"""Smoke tests that lock the runner.py decomposition.

The legacy ``hydromodpy.calibration.runner`` god-module has been split into:

- ``cli_runner``     CLI entry + ``run_calibration_core``.
- ``programmatic_runner``  ``Project.calibrate`` entry.
- ``promotion``    top-N promotion and DB back-fills.
- ``state``      cache preload, fingerprinting, store factory.

These tests guarantee each sub-module imports independently and exposes the
expected public callables. The legacy ``runner`` module must be gone so
nothing keeps pointing at the old location.
"""

from __future__ import annotations

import importlib

import pytest


def test_cli_runner_module_exposes_public_callables() -> None:
    cli_runner = importlib.import_module("hydromodpy.calibration.cli_runner")

    assert callable(cli_runner.run_calibration_cli)
    assert callable(cli_runner.run_calibration_core)


def test_programmatic_runner_module_exposes_run_calibration_programmatic() -> None:
    programmatic_runner = importlib.import_module("hydromodpy.calibration.programmatic_runner")

    assert callable(programmatic_runner.run_calibration_programmatic)


def test_promotion_module_exposes_helpers() -> None:
    promotion = importlib.import_module("hydromodpy.calibration.promotion")

    assert callable(promotion.promote_iterations)
    assert callable(promotion.select_iterations_to_promote)
    assert callable(promotion.update_iter_sim_id)
    assert callable(promotion.update_best_sim_id)
    assert callable(promotion.stored_parameter_value)


def test_state_module_exposes_helpers() -> None:
    state = importlib.import_module("hydromodpy.calibration.state")

    assert callable(state.default_store_factory)
    assert callable(state.preload_hash_cache)
    assert callable(state.build_cache_context)
    assert callable(state.override_paths)
    assert callable(state.space_from_config)
    assert callable(state.load_metric_fn_entry_point)


def test_legacy_runner_module_is_gone() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("hydromodpy.calibration.runner")
