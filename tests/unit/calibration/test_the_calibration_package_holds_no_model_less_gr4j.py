"""GR4J never had a model in HydroModPy, so the package that announced it is gone."""

from __future__ import annotations

import dataclasses
import importlib.util

from hydromodpy.core.state.execution import ExecutionRegistry
from hydromodpy.simulation.planning.plan import RunContext


def test_the_lumped_package_is_not_importable() -> None:
    assert importlib.util.find_spec("hydromodpy.calibration.lumped") is None


def test_no_run_carries_a_lumped_ram_cache() -> None:
    assert "lumped_ram_cache" not in {f.name for f in dataclasses.fields(ExecutionRegistry)}
    assert "lumped_cache" not in {f.name for f in dataclasses.fields(RunContext)}
