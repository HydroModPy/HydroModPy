"""MF6 solver and NPF option resolution."""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import NamedTuple

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.mesh_qa import nonorthogonality_summary

logger = get_logger(__name__)

# XT3D advisor triggers. Two of them make XT3D required for a consistent
# result, so automatic mode turns it on with a RuntimeWarning about its cost.
# A tilted K tensor: MODFLOW 6 reads angle2 and angle3 only under XT3D. A
# horizontal anisotropy off the connections: K22 differs from K where angle1 is
# not a multiple of 90 degrees, or anywhere on an unstructured mesh. The
# two-point flux keeps the conductivity along each connection and drops the
# cross terms, so the head error does not shrink with refinement. A steady well
# with K22 = K/10 and angle1 = 30 gave a head RMSE of 2.2 m on a 7 m drawdown at
# 40 m and 20 m cells, 0.04 then 0.01 m under XT3D. XT3D multiplies the MF6 run
# time from about 1.5 times on one layer to about 10 times on ten layers.
# Triangles and grid non-orthogonality turn XT3D on with
# an INFO log, since the conductance-flux error there scales like
# sin(non-orthogonality). Below these limits the two-point flux is accurate and
# XT3D is pure cost. See Provost et al. (2017), TM 6-A56.
_NONORTH_FRAC_GT30_TRIGGER = 0.05
_NONORTH_P95_TRIGGER_DEG = 30.0


@dataclass(frozen=True)
class Xt3dDecision:
    """Resolved XT3D choice with its source and a human-readable reason."""

    enabled: bool
    source: str  # explicit_on | explicit_off | auto_on | auto_off | unknown
    reason: str


def xt3d_requested_value(model) -> bool | None:
    """Return the configured XT3D override (None when unset = automatic)."""
    runtime = getattr(model.modflow_config, "runtime", None)
    value = getattr(runtime, "mf6_enable_xt3d", None)
    return None if value is None else bool(value)


def k_tensor_is_tilted(model) -> bool:
    """Whether angle2 or angle3 is non-zero on a cell: MODFLOW 6 reads them only under XT3D."""
    for name in ("angle2", "angle3"):
        values = getattr(model, name, None)
        if values is not None and np.any(np.asarray(values, dtype=float) != 0.0):
            return True
    return False


def k_tensor_is_off_axis(model, solver_mesh) -> bool:
    """Whether K22 differs from K on a cell whose principal axes leave the connections.

    On a structured grid the connections follow x and y, so a cell is off axis
    when angle1 is not a multiple of 90 degrees. On another mesh any K22 that
    differs from K counts. A K22 the flow leaves out equals K.
    """
    k22 = getattr(model, "k22", None)
    if k22 is None:
        return False
    k22 = np.asarray(k22, dtype=float)
    anisotropic = ~np.isclose(k22, np.asarray(model.hk, dtype=float), rtol=1e-6, atol=0.0)
    if not solver_mesh.is_structured:
        return bool(np.any(anisotropic))
    angle1 = getattr(model, "angle1", None)
    if angle1 is None:
        return False
    offset = np.remainder(np.asarray(angle1, dtype=float), 90.0)
    off_axis = np.minimum(offset, 90.0 - offset) > 1e-6
    return bool(np.any(anisotropic & off_axis))


class _Xt3dAdvice(NamedTuple):
    """What the model checks advise, whether a consistent result needs it, and why."""

    enabled: bool
    required: bool
    reason: str


def _recommend_xt3d(model, solver_mesh) -> _Xt3dAdvice:
    """Compute whether XT3D is worth enabling for this model + mesh, with a reason."""
    if solver_mesh is None:
        return _Xt3dAdvice(False, False, "grid not resolved yet")
    if k_tensor_is_tilted(model):
        return _Xt3dAdvice(
            True,
            True,
            "the K tensor is tilted (angle2 or angle3 is not zero), and MODFLOW 6 "
            "reads these angles only under XT3D",
        )
    if k_tensor_is_off_axis(model, solver_mesh):
        where = (
            "on cells where angle1 is not a multiple of 90 degrees"
            if solver_mesh.is_structured
            else "on an unstructured mesh, whose connections do not all follow the axes of K"
        )
        return _Xt3dAdvice(
            True,
            True,
            f"K22 differs from K {where}, so the two-point flux drops the cross "
            "terms of the K tensor",
        )
    if solver_mesh.is_structured:
        return _Xt3dAdvice(
            False,
            False,
            "structured grid and a K tensor along its axes: the conductance two-point "
            "flux is exact",
        )
    if solver_mesh.cell_mesh.mesh.cell_types[0] is CellType.TRIANGLE:
        return _Xt3dAdvice(
            True,
            False,
            "triangle cells: the two-point flux between the vertex means of two triangles "
            "is not consistent, XT3D restores it",
        )
    m = nonorthogonality_summary(solver_mesh.planar_mesh)
    if m["frac_gt_30"] > _NONORTH_FRAC_GT30_TRIGGER or m["p95"] > _NONORTH_P95_TRIGGER_DEG:
        return _Xt3dAdvice(
            True,
            False,
            f"mesh non-orthogonality is high (p95={m['p95']:.0f} deg, "
            f"{100 * m['frac_gt_30']:.1f}% of connections >30 deg): XT3D improves accuracy",
        )
    return _Xt3dAdvice(
        False,
        False,
        "an untilted K tensor, isotropic in the plane, and a near-orthogonal mesh "
        f"(median {m['median']:.1f} deg, p95 {m['p95']:.0f} deg): the conductance flux "
        "is accurate, XT3D adds cost only",
    )


def _warn_xt3d(message: str) -> None:
    """Log the message at WARNING and raise it as a RuntimeWarning.

    Importing flopy.plot installs a global ignore filter on RuntimeWarning, so a
    run shows the log line only. The warning still reaches a caller that
    records warnings.
    """
    logger.warning(message)
    warnings.warn(message, RuntimeWarning, stacklevel=3)


def resolve_xt3d_decision(model, solver_mesh=None) -> Xt3dDecision:
    """Resolve XT3D once and memoize it on the model.

    Honour an explicit ``mf6_enable_xt3d`` override. A written false against a
    required trigger raises a RuntimeWarning, also logged at WARNING; any other
    disagreement with the model checks logs a warning. Otherwise decide
    automatically from the K tensor, the cell type and the mesh
    non-orthogonality. A required trigger raises a RuntimeWarning on its cost,
    also logged at WARNING; the other choices log at INFO. The tensor arrays
    and K must be on the model before the first call.
    """
    cached = getattr(model, "_xt3d_decision", None)
    if cached is not None:
        return cached
    if solver_mesh is None:
        solver_mesh = getattr(getattr(model, "grid_ctx", None), "solver_mesh", None)
    advice = _recommend_xt3d(model, solver_mesh)
    requested = xt3d_requested_value(model)
    if requested is not None:
        decision = Xt3dDecision(
            enabled=requested,
            source="explicit_on" if requested else "explicit_off",
            reason=advice.reason,
        )
        if advice.required and not requested:
            _warn_xt3d(
                "XT3D is off as modflow6.runtime.mf6_enable_xt3d says, but "
                f"{advice.reason}. The heads are inconsistent: they are off by a share "
                "of the drawdown that grid refinement does not reduce. Clear "
                "mf6_enable_xt3d (null) or set it to true for a consistent result."
            )
        elif solver_mesh is not None and requested != advice.enabled:
            logger.warning(
                "XT3D is set to %s, but the model checks recommend %s: %s. Keeping "
                "your setting; clear mf6_enable_xt3d (null) to follow the check.",
                "on" if requested else "off",
                "on" if advice.enabled else "off",
                advice.reason,
            )
    else:
        decision = Xt3dDecision(
            enabled=advice.enabled,
            source="auto_on" if advice.enabled else "auto_off",
            reason=advice.reason,
        )
        if advice.required:
            _warn_xt3d(
                f"XT3D is on because {advice.reason}. XT3D costs from about 1.5 times the "
                "MODFLOW 6 run time on one layer to about 10 times on ten layers. Without "
                "it the heads would be off by a share of "
                "the drawdown that grid refinement does not reduce. Set "
                "modflow6.runtime.mf6_enable_xt3d = true to keep it on without this warning."
            )
        elif solver_mesh is not None:
            logger.info("XT3D auto-%s: %s", "on" if advice.enabled else "off", advice.reason)
    if decision.enabled and solver_mesh is not None and _newton_on_triangles(model, solver_mesh):
        logger.warning(
            "XT3D on triangle cells under Newton can cycle without converging. MODFLOW 6 "
            "scales the XT3D face area by the upstream saturation, while the cross term "
            "of XT3D stays non-zero at equal heads, so the discrete system can have no "
            "root. If the run stops with E401, mesh with the voronoi engine, which needs "
            "no XT3D, or set modflow6.runtime.mf6_enable_xt3d = false (heads about 0.1 m "
            "RMSE off XT3D on the Nancon)."
        )
    if solver_mesh is not None:
        model._xt3d_decision = decision
    return decision


def _newton_on_triangles(model, solver_mesh) -> bool:
    """Whether the run is Newton on a mesh of triangle cells."""
    runtime = getattr(model.modflow_config, "runtime", None)
    if not bool(getattr(runtime, "mf6_newton", False)) or solver_mesh.is_structured:
        return False
    return solver_mesh.cell_mesh.mesh.cell_types[0] is CellType.TRIANGLE


def xt3d_is_enabled(model, solver_mesh=None) -> bool:
    """Return whether XT3D should be enabled for this MF6 run."""
    return resolve_xt3d_decision(model, solver_mesh).enabled


def xt3d_activation_mode(model, solver_mesh=None) -> str:
    """Return the XT3D activation mode used in logs and diagnostics."""
    return resolve_xt3d_decision(model, solver_mesh).source


def resolve_ims_complexity(model, solver_mesh=None) -> str:
    """Return IMS complexity, promoting SIMPLE under XT3D or Newton.

    SIMPLE assumes a symmetric, well-conditioned matrix. XT3D and the Newton
    formulation both break that assumption, so a configured SIMPLE is promoted:
    to COMPLEX under XT3D, and to at least MODERATE under Newton.
    """
    runtime = getattr(model.modflow_config, "runtime", None)
    configured = str(getattr(runtime, "mf6_ims_complexity", "COMPLEX")).strip().upper()
    if configured != "SIMPLE":
        return configured or "COMPLEX"
    if xt3d_is_enabled(model, solver_mesh):
        return "COMPLEX"
    if bool(getattr(runtime, "mf6_newton", False)):
        return "MODERATE"
    return "SIMPLE"


def log_xt3d_resolution(model, solver_mesh=None) -> None:
    """Log the resolved XT3D mode once the solver mesh is known."""
    logger.debug(
        "MF6 XT3D resolution: mode=%s enabled=%s structured=%s",
        xt3d_activation_mode(model, solver_mesh),
        xt3d_is_enabled(model, solver_mesh),
        bool(solver_mesh is not None and solver_mesh.is_structured),
    )


def resolve_xt3d_npf_options(model, solver_mesh=None) -> list[str] | None:
    """Return FloPy NPF XT3D options."""
    return ["XT3D"] if xt3d_is_enabled(model, solver_mesh) else None


__all__ = [
    "k_tensor_is_off_axis",
    "k_tensor_is_tilted",
    "log_xt3d_resolution",
    "resolve_ims_complexity",
    "resolve_xt3d_npf_options",
    "xt3d_activation_mode",
    "xt3d_is_enabled",
    "xt3d_requested_value",
]
