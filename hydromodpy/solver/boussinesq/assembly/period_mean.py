"""The assembly a stress period exports when its solve takes several steps.

A stamp closes its period: the state it carries is the state at the period
end, and every flux the mean over the period. A runtime that cuts a period
into internal steps (the VI substeps, the PETSc TS steps) returns the
assembly of its last step for the state and the step-length-weighted mean
of its steps for the fluxes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

import numpy as np

from hydromodpy.solver.boussinesq.assembly.types import BoussinesqAssembly

FLUX_FIELDS: tuple[str, ...] = (
    "recharge_rate_m_s",
    "well_flux_m3_s",
    "saturation_excess_rate_m_s",
    "internal_edge_flux_m3_s",
    "prescribed_head_flux_m3_s",
    "boundary_edge_flux_m3_s",
    "drainage_flux_m3_s",
    "flow_residual_m3_s",
    "residual_m3_s",
    "dry_deficit_rate_m_s",
)
"""Assembly fields that are rates over a step; the others are states at its end."""


def period_mean_assembly(
    assemblies: Sequence[BoussinesqAssembly], weights: Sequence[float]
) -> BoussinesqAssembly:
    """Return the last assembly with its fluxes replaced by their weighted mean.

    ``weights`` are the step lengths over the period length. One step of
    weight 1.0 is returned unchanged. A step without a dry deficit counts
    zero for it.
    """
    if len(assemblies) != len(weights) or not assemblies:
        raise ValueError(f"{len(assemblies)} assemblies for {len(weights)} weights.")
    last = assemblies[-1]
    if len(assemblies) == 1 and float(weights[0]) == 1.0:
        return last
    means: dict[str, np.ndarray | None] = {}
    for name in FLUX_FIELDS:
        values = [getattr(assembly, name) for assembly in assemblies]
        if all(value is None for value in values):
            means[name] = None
            continue
        size = next(np.asarray(value).size for value in values if value is not None)
        total = np.zeros(size, dtype=float)
        for weight, value in zip(weights, values, strict=True):
            if value is not None:
                total = total + float(weight) * np.asarray(value, dtype=float).reshape(-1)
        means[name] = total
    return replace(last, **means)


__all__ = ["FLUX_FIELDS", "period_mean_assembly"]
