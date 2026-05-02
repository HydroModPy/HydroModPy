"""MF6 solver and NPF option resolution."""

from __future__ import annotations

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)


def xt3d_requested_value(model) -> bool | None:
    """Return the configured XT3D override."""
    runtime = getattr(model.modflow_config, "runtime", None)
    value = getattr(runtime, "mf6_enable_xt3d", None)
    return None if value is None else bool(value)


def xt3d_is_enabled(model, solver_mesh=None) -> bool:
    """Return whether XT3D should be enabled for this MF6 run."""
    requested = xt3d_requested_value(model)
    if requested is not None:
        return requested
    if solver_mesh is None:
        solver_mesh = getattr(getattr(model, "grid_ctx", None), "solver_mesh", None)
    return not bool(getattr(solver_mesh, "is_structured", True))


def xt3d_activation_mode(model, solver_mesh=None) -> str:
    """Return the XT3D activation mode used in logs and diagnostics."""
    requested = xt3d_requested_value(model)
    if requested is True:
        return "explicit_true"
    if requested is False:
        return "explicit_false"
    return "auto_unstructured" if xt3d_is_enabled(model, solver_mesh) else "auto_structured_off"


def resolve_ims_complexity(model, solver_mesh=None) -> str:
    """Return IMS complexity, promoting SIMPLE when XT3D is active."""
    runtime = getattr(model.modflow_config, "runtime", None)
    configured = str(getattr(runtime, "mf6_ims_complexity", "COMPLEX")).strip().upper()
    if xt3d_is_enabled(model, solver_mesh) and configured == "SIMPLE":
        return "COMPLEX"
    return configured or "COMPLEX"


def log_xt3d_resolution(model, solver_mesh=None) -> None:
    """Log the resolved XT3D mode once the solver mesh is known."""
    logger.info(
        "MF6 XT3D resolution: mode=%s enabled=%s structured=%s",
        xt3d_activation_mode(model, solver_mesh),
        xt3d_is_enabled(model, solver_mesh),
        bool(getattr(solver_mesh, "is_structured", True)),
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
