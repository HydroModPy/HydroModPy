"""MF6 solver and NPF option resolution."""

from __future__ import annotations

from dataclasses import dataclass

from hydromodpy.core.logging import get_logger
from hydromodpy.spatial.mesh.mesh_orthogonality import nonorthogonality_summary

logger = get_logger(__name__)

# XT3D advisor triggers. On an isotropic medium the only thing XT3D corrects is
# the grid non-orthogonality, and the conductance-flux error scales like
# sin(non-orthogonality). Below these the two-point flux is accurate and XT3D is
# pure cost; above them XT3D earns its cost. See Provost et al. (2017), TM 6-A56.
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


def _horizontal_anisotropy_present(model) -> bool:
    """True if the horizontal K tensor is anisotropic or angled (XT3D's tensor case).

    HMP's NPF writes only ``k`` (horizontal, isotropic) and ``k33`` (vertical, via
    vka). Vertical anisotropy is grid-aligned and needs no XT3D, and there is no
    k22 / angle1..3 input, so the horizontal plane is isotropic today. This hook
    flips automatically if a horizontal-anisotropy field is ever added.
    """
    process = getattr(model.modflow_config, "process_specific", None)
    for attr in ("k22_over_k", "horizontal_anisotropy", "angle1"):
        value = getattr(process, attr, None)
        try:
            if value is not None and float(value) not in (0.0, 1.0):
                return True
        except (TypeError, ValueError):
            continue
    return False


def _recommend_xt3d(model, solver_mesh) -> tuple[bool, str]:
    """Compute whether XT3D is worth enabling for this model + mesh, with a reason."""
    if solver_mesh is None:
        return False, "grid not resolved yet"
    if solver_mesh.is_structured:
        return False, "structured grid: the conductance two-point flux is exact"
    if _horizontal_anisotropy_present(model):
        return True, "horizontal/angled K anisotropy: XT3D needed for the full tensor"
    m = nonorthogonality_summary(solver_mesh.planar_mesh)
    if m["frac_gt_30"] > _NONORTH_FRAC_GT30_TRIGGER or m["p95"] > _NONORTH_P95_TRIGGER_DEG:
        return True, (
            f"mesh non-orthogonality is high (p95={m['p95']:.0f} deg, "
            f"{100 * m['frac_gt_30']:.1f}% of connections >30 deg): XT3D improves accuracy"
        )
    return False, (
        f"isotropic K and a near-orthogonal mesh (median {m['median']:.1f} deg, "
        f"p95 {m['p95']:.0f} deg): the conductance flux is accurate, XT3D adds cost only"
    )


def resolve_xt3d_decision(model, solver_mesh=None) -> Xt3dDecision:
    """Resolve XT3D once and memoize it on the model.

    Honour an explicit ``mf6_enable_xt3d`` override (and WARN if it disagrees with
    the model checks); otherwise decide automatically from the K field and the
    mesh non-orthogonality, logging the chosen value and the reason at INFO.
    """
    cached = getattr(model, "_xt3d_decision", None)
    if cached is not None:
        return cached
    if solver_mesh is None:
        solver_mesh = getattr(getattr(model, "grid_ctx", None), "solver_mesh", None)
    recommended, reason = _recommend_xt3d(model, solver_mesh)
    requested = xt3d_requested_value(model)
    if requested is not None:
        decision = Xt3dDecision(
            enabled=requested,
            source="explicit_on" if requested else "explicit_off",
            reason=reason,
        )
        if solver_mesh is not None and requested != recommended:
            logger.warning(
                "XT3D is set to %s, but the model checks recommend %s: %s. Keeping "
                "your setting; clear mf6_enable_xt3d (null) to follow the check.",
                "on" if requested else "off",
                "on" if recommended else "off",
                reason,
            )
    else:
        decision = Xt3dDecision(
            enabled=recommended,
            source="auto_on" if recommended else "auto_off",
            reason=reason,
        )
        if solver_mesh is not None:
            logger.info("XT3D auto-%s: %s", "on" if recommended else "off", reason)
    if solver_mesh is not None:
        model._xt3d_decision = decision
    return decision


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
    "log_xt3d_resolution",
    "resolve_ims_complexity",
    "resolve_xt3d_npf_options",
    "xt3d_activation_mode",
    "xt3d_is_enabled",
    "xt3d_requested_value",
]
