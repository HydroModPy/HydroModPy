"""Cyclic spin-up driver: repeat a forcing window until the state stabilises.

Each cycle runs the representative window, then the next cycle restarts from the
previous cycle's Zarr (``[flow] restart_from``). The loop stops when the aquifer
heads and the lake stage stop changing between cycles (L-inf below tolerance) or
``max_cycles`` is reached. The converged state is a reusable antecedent: point a
production run (or every calibration trial) at ``result.restart_from``.

The driver reuses one :class:`~hydromodpy.project.facade.Project`, so the mesh is
built once and is identical across cycles by construction. The mesh cache matters
only for a *later, separate* run that restarts from the converged Zarr.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.physics.flow.initial_conditions import FlowInitialConditions
from hydromodpy.simulation.spinup_config import SpinupConfig
from hydromodpy.solver.modflow6.builders.initial_conditions import (
    read_final_head,
    read_restart_lake_stages,
)

if TYPE_CHECKING:
    from hydromodpy.project.facade import Project

logger = get_logger(__name__)


@dataclass(frozen=True)
class SpinupCycle:
    """One spin-up cycle's run and its change from the previous cycle."""

    index: int
    sim_id: str
    zarr_path: str
    d_head: float | None  # None on cycle 0 (no prior cycle to diff against)
    d_stage: float | None


@dataclass(frozen=True)
class SpinupResult:
    """Outcome of a spin-up loop.

    ``restart_from`` is the converged (or last) cycle's Zarr path, ready to feed a
    production run's ``[flow] restart_from``.
    """

    converged: bool
    cycles: list[SpinupCycle]
    restart_from: str

    @property
    def n_cycles(self) -> int:
        return len(self.cycles)


def cycle_delta(prev_zarr: str, curr_zarr: str) -> tuple[float, float]:
    """Return ``(d_head, d_stage)``, the L-inf change (m) between two cycles.

    ``d_head`` is the largest absolute head change over active cells; ``d_stage``
    the largest absolute lake-stage change over the lakes present in both cycles
    (0.0 when the model has no lake). Raises when the cell count changed between
    cycles, which means the mesh was not stable.
    """
    h_prev = read_final_head(prev_zarr)
    h_curr = read_final_head(curr_zarr)
    if h_prev.shape != h_curr.shape:
        raise ValueError(
            f"spin-up: head shape changed between cycles ({h_prev.shape} -> "
            f"{h_curr.shape}); the mesh is not stable across cycles."
        )
    diff = np.abs(h_curr - h_prev)
    d_head = float(np.nanmax(diff)) if np.isfinite(diff).any() else 0.0

    s_prev = read_restart_lake_stages(prev_zarr)
    s_curr = read_restart_lake_stages(curr_zarr)
    shared = set(s_prev) & set(s_curr)
    d_stage = max((abs(s_curr[key] - s_prev[key]) for key in shared), default=0.0)
    return d_head, d_stage


def run_spinup(
    project: Project,
    *,
    spinup: SpinupConfig | None = None,
    name_prefix: str = "spinup",
) -> SpinupResult:
    """Run the cyclic spin-up loop on ``project`` and return the outcome.

    Cycle 0 keeps the config's initial condition. Cycles >= 1 set
    ``flow.restart_from`` to the previous cycle's Zarr and force a non-steady
    (``top``) IC so the optional steady pre-solve cannot clobber the restarted
    heads. ``spinup`` defaults to the project's ``[spinup]`` section, then to
    :class:`SpinupConfig` defaults.
    """
    cfg = project.config
    settings = spinup or cfg.spinup or SpinupConfig()

    # A dedicated, shorter representative window keeps each cycle cheap. Set it
    # before prepare() so the data step loads forcing for the cycle window.
    if settings.window_start is not None:
        cfg.simulation.time.start_datetime = settings.window_start
    if settings.window_end is not None:
        cfg.simulation.time.end_datetime = settings.window_end

    if cfg.mesh_catchment is None or not cfg.mesh_catchment.cache:
        logger.warning(
            "spin-up reuses one Project, so its mesh is stable across cycles. But a "
            "later production run that restarts from the converged Zarr needs the SAME "
            "mesh: enable [mesh_catchment] cache = true for a gmsh grid, or the restart "
            "shape check will reject it."
        )

    project.prepare()  # build geographic / data / mesh once, reused every cycle

    cycles: list[SpinupCycle] = []
    prev_zarr: str | None = None
    converged = False

    for index in range(settings.max_cycles):
        if prev_zarr is not None:
            cfg.flow.restart_from = prev_zarr
            if cfg.flow.ic.h.type == "steady_state":
                cfg.flow.ic = FlowInitialConditions.model_validate({"type": "top"})

        run = project.simulate(name=f"{name_prefix}_{index}")
        if run is None:
            raise RuntimeError(f"spin-up cycle {index} produced no run")
        zarr_path = str(project._catalog.store.zarr_path_for(run.sim_id))

        d_head: float | None = None
        d_stage: float | None = None
        if prev_zarr is not None:
            d_head, d_stage = cycle_delta(prev_zarr, zarr_path)
            logger.info(
                "spin-up cycle %d: d_head=%.4g m, d_stage=%.4g m (tol %.4g / %.4g)",
                index,
                d_head,
                d_stage,
                settings.tol_head,
                settings.tol_stage,
            )
            converged = d_head < settings.tol_head and d_stage < settings.tol_stage

        cycles.append(SpinupCycle(index, run.sim_id, zarr_path, d_head, d_stage))
        prev_zarr = zarr_path
        if converged:
            logger.info("spin-up converged after %d cycles", index + 1)
            break

    if not converged:
        logger.warning(
            "spin-up did not converge in %d cycles; using the last state as the "
            "antecedent. Raise max_cycles or the tolerances.",
            settings.max_cycles,
        )
    return SpinupResult(converged=converged, cycles=cycles, restart_from=prev_zarr or "")
