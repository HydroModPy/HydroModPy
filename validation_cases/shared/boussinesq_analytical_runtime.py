"""Default Boussinesq runtime selection for analytical validation cases."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Any

from hydromodpy.physics.flow.regime import normalize_flow_regime

ANALYTICAL_STEADY_SURFACE_MODEL = "vi_obstacle"
ANALYTICAL_TRANSIENT_SURFACE_MODEL = "ts_vi_obstacle"
ANALYTICAL_RUNTIME_BACKEND = "petsc"
LEGACY_RUNTIME_BACKENDS = {"", "local", "scipy", "scipy_sparse"}
LEGACY_SURFACE_MODELS = {"", "auto", "regularized_partition"}


def analytical_boussinesq_runtime_overrides(flow_regime: str | None) -> dict[str, object]:
    """Return the PETSc runtime knobs used by default analytical Boussinesq runs."""
    regime = normalize_flow_regime(flow_regime or "steady")
    if regime == "transient":
        return {
            "runtime_backend": ANALYTICAL_RUNTIME_BACKEND,
            "surface_interaction_model": ANALYTICAL_TRANSIENT_SURFACE_MODEL,
            "ts_vi_steps_per_period": 4,
            "ts_vi_adapt": False,
            "ts_vi_type": "beuler",
            "ts_vi_snes_type": "vinewtonrsls",
        }
    return {
        "runtime_backend": ANALYTICAL_RUNTIME_BACKEND,
        "surface_interaction_model": ANALYTICAL_STEADY_SURFACE_MODEL,
    }


def apply_analytical_boussinesq_runtime_defaults(
    flow_section: Mapping[str, Any],
    *,
    flow_regime: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Return ``flow_section`` with the analytical PETSc runtime default applied.

    The validation modules historically hard-coded ``scipy_sparse`` and the
    regularized partition closure. Those values now mean "legacy default" and
    are upgraded unless the caller explicitly requested a non-legacy PETSc
    surface model, or ``force`` is true.
    """
    normalized = dict(flow_section)
    regime = str(flow_regime or normalized.get("flow_regime") or "steady")
    backend = str(normalized.get("runtime_backend", "") or "").strip().lower()
    surface_model = str(normalized.get("surface_interaction_model", "") or "").strip().lower()
    should_upgrade = force or (
        backend in LEGACY_RUNTIME_BACKENDS and surface_model in LEGACY_SURFACE_MODELS
    )
    if should_upgrade:
        normalized.update(analytical_boussinesq_runtime_overrides(regime))
    return normalized


def set_analytical_boussinesq_runtime_defaults_in_place(
    flow_section: MutableMapping[str, Any],
    *,
    flow_regime: str | None = None,
    force: bool = False,
) -> None:
    """Mutate ``flow_section`` with the analytical PETSc runtime default."""
    current = dict(flow_section)
    flow_section.clear()
    flow_section.update(
        apply_analytical_boussinesq_runtime_defaults(
            current,
            flow_regime=flow_regime,
            force=force,
        )
    )


def analytical_boussinesq_solver_label(
    flow_section: Mapping[str, Any],
    *,
    public_solver: str = "boussinesq",
) -> str:
    """Return the public solver label for a validation result.

    ``solver='boussinesq'`` is intentionally kept as the public validation label
    after the default runtime switches to PETSc VI/TS VI. Explicit PETSc aliases
    can still pass their own public label from comparison modules.
    """
    return str(public_solver or "boussinesq")


__all__ = [
    "ANALYTICAL_RUNTIME_BACKEND",
    "ANALYTICAL_STEADY_SURFACE_MODEL",
    "ANALYTICAL_TRANSIENT_SURFACE_MODEL",
    "analytical_boussinesq_runtime_overrides",
    "analytical_boussinesq_solver_label",
    "apply_analytical_boussinesq_runtime_defaults",
    "set_analytical_boussinesq_runtime_defaults_in_place",
]
