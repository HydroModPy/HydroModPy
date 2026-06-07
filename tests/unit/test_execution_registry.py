"""Unit tests for :class:`hydromodpy.core.state.execution.ExecutionRegistry`.

Covers the ``lightweight`` flag added in Phase 1 of the calibration
refactor - the flag is what step 06 / step 07 read to decide whether to
open the store, write provenance, and ingest run results.
"""

from __future__ import annotations

from hydromodpy.core.state.execution import ExecutionRegistry


def test_default_registry_is_heavy() -> None:
    reg = ExecutionRegistry()
    assert reg.lightweight is False


def test_lightweight_flag_is_propagated() -> None:
    reg = ExecutionRegistry(lightweight=True)
    assert reg.lightweight is True


def test_lightweight_flag_does_not_affect_models_registry() -> None:
    reg = ExecutionRegistry(lightweight=True)
    reg.models_by_run_id["x"] = "model"
    assert reg.models_by_run_id == {"x": "model"}
    assert reg.simulation_plan is None
