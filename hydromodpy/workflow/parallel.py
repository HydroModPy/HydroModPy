"""Sweep orchestration and worker-pool helpers.

Centralizes the parameter-expansion and per-run dispatch logic shared by
``project.sweep`` (and, in the future, ``project.calibrate`` and
``project.batch``). Sequential today; process-pool support lives here so
parallelization is a single-point change.
"""

from __future__ import annotations

import itertools
from typing import Protocol

from hydromodpy.core.exceptions import ConfigError


class SweepRun(Protocol):
    """Minimal run view needed by sweep orchestration."""

    sim_id: str


class SweepProject(Protocol):
    """Minimal project protocol needed by sweep orchestration."""

    def run(self, *, name: str | None = None, **overrides: float) -> SweepRun:
        """Execute one simulation and return its run view."""


def expand_parameters(
    parameters: dict[str, list[float] | dict],
    strategy: str,
) -> list[dict[str, float]]:
    """Return the list of {param: value} dicts that feed one run each."""
    if strategy == "enumerate":
        if len(parameters) != 1:
            raise ConfigError("strategy='enumerate' expects exactly one parameter")
        ((name, values),) = parameters.items()
        if isinstance(values, dict):
            raise ConfigError("strategy='enumerate' expects a list of values, not a spec")
        return [{name: float(v)} for v in values]

    if strategy == "grid":
        axes = []
        for name, values in parameters.items():
            if isinstance(values, dict):
                raise ConfigError("strategy='grid' expects lists of values, not specs")
            axes.append([(name, float(v)) for v in values])
        return [dict(combo) for combo in itertools.product(*axes)]

    raise NotImplementedError(f"strategy '{strategy}' is not supported yet")


def run_sweep(
    project: SweepProject,
    *,
    parameters: dict[str, list[float] | dict],
    strategy: str,
    name_template: str,
) -> list[str]:
    """Execute one run per parameter point sequentially. Returns the sim_ids."""
    sim_ids: list[str] = []
    for point in expand_parameters(parameters, strategy):
        param, value = next(iter(point.items()))
        name = name_template.format(param=param, value=value)
        run = project.run(name=name, **point)
        sim_ids.append(run.sim_id)
    return sim_ids
