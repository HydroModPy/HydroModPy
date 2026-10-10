"""Default Boussinesq runtime selection for analytical validation cases."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Any

from hydromodpy.physics.flow.flow_runtime_fields import FlowRuntimeFields

ANALYTICAL_STEADY_SURFACE_MODEL = "vi_obstacle"
ANALYTICAL_TRANSIENT_SURFACE_MODEL = "ts_vi_obstacle"
ANALYTICAL_RUNTIME_BACKEND = "petsc"
# The variant a user gets with ``solvers = ["boussinesq"]`` and no runtime key:
# runtime_backend 'auto' (the dense 'local' engine up to 400 cells, 'scipy_sparse'
# above) with the regularized partition surface closure.
DEFAULT_ENGINE_SOLVER = "boussinesq_local"
_RUNTIME_KEYS = frozenset(FlowRuntimeFields.model_fields)


def _normalize_flow_regime(value: object) -> str:
    text = str(value).strip().lower()
    if text in {"steady", "transient"}:
        return text
    raise ValueError("flow.flow_regime must be 'steady' or 'transient'.")


def analytical_boussinesq_runtime_overrides(flow_regime: str | None) -> dict[str, object]:
    """Return the PETSc runtime knobs used by default analytical Boussinesq runs."""
    regime = _normalize_flow_regime(flow_regime or "steady")
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

    Missing runtime keys are filled with the analytical PETSc VI/TS-VI defaults.
    Explicit caller-provided values are kept unless ``force`` is true.
    """
    normalized = dict(flow_section)
    regime = str(flow_regime or normalized.get("flow_regime") or "steady")
    defaults = analytical_boussinesq_runtime_overrides(regime)
    if force:
        normalized.update(defaults)
        return normalized
    for key, value in defaults.items():
        current = normalized.get(key)
        if current is None or (isinstance(current, str) and not current.strip()):
            normalized[key] = value
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


def is_default_engine_solver(solver: str | None) -> bool:
    """Return True for the variant that runs the library default engine."""
    return str(solver or "").strip().lower() == DEFAULT_ENGINE_SOLVER


def boussinesq_variant_config_name(solver: str | None) -> str:
    """Return the case config whose ``[flow]`` a Boussinesq variant merges."""
    if is_default_engine_solver(solver):
        return f"config_{DEFAULT_ENGINE_SOLVER}.toml"
    return "config_boussinesq.toml"


def boussinesq_variant_flow_section(
    flow_section: Mapping[str, Any],
    *,
    flow_regime: str | None = None,
    solver: str | None = "boussinesq",
) -> dict[str, Any]:
    """Return the flow section one Boussinesq validation variant runs with.

    The default-engine variant drops every runtime key, so the FlowConfig
    defaults apply as in a user run. Every other variant gets the analytical
    PETSc defaults.

    A transient section that does not state ``first_period_steady`` gets
    false: a transient case starts from its initial condition, as the
    MODFLOW base config of each case states. A Brutsaert warm-up is a
    separate steady run.
    """
    section = dict(flow_section)
    regime = str(flow_regime or section.get("flow_regime") or "steady").strip().lower()
    if regime == "transient":
        section.setdefault("first_period_steady", False)
    if is_default_engine_solver(solver):
        return {key: value for key, value in section.items() if key not in _RUNTIME_KEYS}
    return apply_analytical_boussinesq_runtime_defaults(section, flow_regime=flow_regime)


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
    "DEFAULT_ENGINE_SOLVER",
    "analytical_boussinesq_runtime_overrides",
    "analytical_boussinesq_solver_label",
    "apply_analytical_boussinesq_runtime_defaults",
    "boussinesq_variant_config_name",
    "boussinesq_variant_flow_section",
    "is_default_engine_solver",
    "set_analytical_boussinesq_runtime_defaults_in_place",
]
