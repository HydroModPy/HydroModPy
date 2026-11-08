"""Default Boussinesq runtime selection for analytical validation cases."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from hydromodpy.core.state.run_state import RunState, SetupContext
from hydromodpy.model.flow import Flow
from hydromodpy.model.model import Geometry, Model, ModelOptions, ModelTime, model_from_flow
from hydromodpy.model.runtime_config import FLOW_RUNTIME_KEYS
from hydromodpy.solver.base.solver_config import SolverConfig

ANALYTICAL_STEADY_SURFACE_MODEL = "vi_obstacle"
ANALYTICAL_TRANSIENT_SURFACE_MODEL = "ts_vi_obstacle"
ANALYTICAL_RUNTIME_BACKEND = "petsc"
# The variant a user gets with ``solvers = ["boussinesq"]`` and no runtime key:
# runtime_backend 'auto' (the dense 'local' engine up to 400 cells, 'scipy_sparse'
# above) with the regularized partition surface closure.
DEFAULT_ENGINE_SOLVER = "boussinesq_local"
# The runtime keys a case may still carry flat in [flow], and the [flow.runtime] table.
_RUNTIME_KEYS = frozenset(FLOW_RUNTIME_KEYS) | {"runtime"}


def _normalize_flow_regime(value: object) -> str:
    text = str(value).strip().lower()
    if text in {"steady", "transient"}:
        return text
    raise ValueError("flow.flow_regime must be 'steady' or 'transient'.")


def analytical_boussinesq_runtime_overrides(flow_regime: str | None) -> dict[str, object]:
    """Return the ``[flow.runtime]`` knobs used by default analytical Boussinesq runs."""
    regime = _normalize_flow_regime(flow_regime or "steady")
    if regime == "transient":
        return {
            "backend": ANALYTICAL_RUNTIME_BACKEND,
            "surface_interaction_model": ANALYTICAL_TRANSIENT_SURFACE_MODEL,
            "ts_vi_steps_per_period": 4,
            "ts_vi_adapt": False,
            "ts_vi_type": "beuler",
            "ts_vi_snes_type": "vinewtonrsls",
        }
    return {
        "backend": ANALYTICAL_RUNTIME_BACKEND,
        "surface_interaction_model": ANALYTICAL_STEADY_SURFACE_MODEL,
    }


def apply_analytical_boussinesq_runtime_defaults(
    flow_section: Mapping[str, Any],
    *,
    flow_regime: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Return ``flow_section`` with the analytical PETSc runtime default applied.

    The knobs are written in the ``runtime`` table of the section. Missing ones are
    filled with the analytical PETSc VI/TS-VI defaults. Explicit caller-provided
    values are kept unless ``force`` is true.
    """
    normalized = dict(flow_section)
    regime = str(flow_regime or normalized.get("flow_regime") or "steady")
    defaults = analytical_boussinesq_runtime_overrides(regime)
    runtime = dict(normalized.get("runtime") or {})
    if force:
        runtime.update(defaults)
    else:
        for key, value in defaults.items():
            current = runtime.get(key)
            if current is None or (isinstance(current, str) and not current.strip()):
                runtime[key] = value
    normalized["runtime"] = runtime
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


def boussinesq_bundle_model(flow: Flow, *, time_grid: object = None) -> Model:
    """Return the ``Model`` of a validation run on a mesh bundle.

    The cells come from the bundle, so the model has no cell mesh, domain, DEM or
    catchment, and the ``[solver]`` options are their defaults. ``time_grid`` is
    ``None`` for a steady run.
    """
    return model_from_flow(
        flow,
        geometry=Geometry(cells=None, domain=None),
        time=ModelTime.from_flow(flow, time_grid),
        options=ModelOptions.from_settings(SolverConfig()),
    )


def boussinesq_run_state(
    *,
    flow: Flow,
    bundle_dir: str | Path,
    simulations_folder: str | Path,
    time_grid: object = None,
) -> RunState:
    """Return the run state the Boussinesq adapter reads for a run on a mesh bundle.

    The state carries the ``Model`` of ``flow`` and the ``[flow]`` section the
    solver options come from. The scratch folder is ``simulations_folder``.
    """
    return RunState(
        cfg=SimpleNamespace(flow=flow.config),
        setup=SetupContext(
            mesh_bundle=None,
            mesh_summary={"output_exchange_bundle_dir": str(bundle_dir)},
            model=boussinesq_bundle_model(flow, time_grid=time_grid),
            workspace=SimpleNamespace(
                simulations_folder=simulations_folder, solver_scratch_folder=simulations_folder
            ),
        ),
    )


__all__ = [
    "ANALYTICAL_RUNTIME_BACKEND",
    "ANALYTICAL_STEADY_SURFACE_MODEL",
    "ANALYTICAL_TRANSIENT_SURFACE_MODEL",
    "DEFAULT_ENGINE_SOLVER",
    "analytical_boussinesq_runtime_overrides",
    "analytical_boussinesq_solver_label",
    "apply_analytical_boussinesq_runtime_defaults",
    "boussinesq_bundle_model",
    "boussinesq_run_state",
    "boussinesq_variant_config_name",
    "boussinesq_variant_flow_section",
    "is_default_engine_solver",
    "set_analytical_boussinesq_runtime_defaults_in_place",
]
