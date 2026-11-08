"""Default Boussinesq runtime selection for analytical validation cases.

The settings of the Boussinesq solve live in ``[solver.boussinesq]``, beside the
flow section and not in it. A case writes its flow section and, apart, the
settings it sets. This module turns them into the ``FlowRuntimeConfig`` a variant
runs with, and into the run state the adapter reads.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from hydromodpy.core.state.run_state import RunState, SetupContext
from hydromodpy.model.flow import Flow
from hydromodpy.model.model import Geometry, Model, ModelOptions, ModelTime, model_from_flow
from hydromodpy.model.runtime_config import FLOW_RUNTIME_KEYS, FlowRuntimeConfig
from hydromodpy.solver.base.solver_config import SolverConfig
from validation_cases.shared.loaders import load_case_config

ANALYTICAL_STEADY_SURFACE_MODEL = "vi_obstacle"
ANALYTICAL_TRANSIENT_SURFACE_MODEL = "ts_vi_obstacle"
ANALYTICAL_RUNTIME_BACKEND = "petsc"
# The variant a user gets with ``solvers = ["boussinesq"]`` and no runtime key:
# runtime_backend 'auto' (the dense 'local' engine up to 400 cells, 'scipy_sparse'
# above) with the regularized partition surface closure.
DEFAULT_ENGINE_SOLVER = "boussinesq_local"
# The keys of a section that never belong to the flow: the flat runtime keys of
# an old file, and the table they moved into.
_RUNTIME_KEYS = frozenset(FLOW_RUNTIME_KEYS) | {"runtime"}


def _normalize_flow_regime(value: object) -> str:
    text = str(value).strip().lower()
    if text in {"steady", "transient"}:
        return text
    raise ValueError("flow.flow_regime must be 'steady' or 'transient'.")


def analytical_boussinesq_runtime_overrides(flow_regime: str | None) -> dict[str, object]:
    """Return the ``[solver.boussinesq]`` knobs used by default analytical Boussinesq runs."""
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
    settings: Mapping[str, Any],
    *,
    flow_regime: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Return the ``[solver.boussinesq]`` ``settings`` with the analytical PETSc defaults applied.

    Missing ones are filled with the analytical PETSc VI/TS-VI defaults of the
    flow regime. Explicit caller-provided values are kept unless ``force`` is true.
    """
    defaults = analytical_boussinesq_runtime_overrides(flow_regime)
    filled = dict(settings)
    if force:
        filled.update(defaults)
    else:
        for key, value in defaults.items():
            current = filled.get(key)
            if current is None or (isinstance(current, str) and not current.strip()):
                filled[key] = value
    return filled


def set_analytical_boussinesq_runtime_defaults_in_place(
    settings: MutableMapping[str, Any],
    *,
    flow_regime: str | None = None,
    force: bool = False,
) -> None:
    """Mutate the ``[solver.boussinesq]`` ``settings`` with the analytical PETSc defaults."""
    filled = apply_analytical_boussinesq_runtime_defaults(
        settings, flow_regime=flow_regime, force=force
    )
    settings.clear()
    settings.update(filled)


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
) -> dict[str, Any]:
    """Return the flow section one Boussinesq validation variant runs with.

    The runtime keys never stay in a flow section: a case that still carries
    them, flat or as a ``runtime`` table, has them dropped here and writes them
    to ``boussinesq_variant_options`` instead.

    A transient section that does not state ``first_period_steady`` gets
    false: a transient case starts from its initial condition, as the
    MODFLOW base config of each case states. A Brutsaert warm-up is a
    separate steady run.
    """
    section = {key: value for key, value in flow_section.items() if key not in _RUNTIME_KEYS}
    regime = str(flow_regime or section.get("flow_regime") or "steady").strip().lower()
    if regime == "transient":
        section.setdefault("first_period_steady", False)
    return section


def boussinesq_variant_options(
    *,
    flow_regime: str | None = None,
    solver: str | None = "boussinesq",
    case_dir: Path | None = None,
    config_name: str | None = None,
    written: Mapping[str, Any] | None = None,
) -> FlowRuntimeConfig:
    """Return the ``[solver.boussinesq]`` settings one Boussinesq validation variant runs with.

    The table of ``config_name`` in ``case_dir`` gives the base. The default-engine
    variant keeps it as it is, so the library defaults apply as in a user run.
    Every other variant gets the analytical PETSc defaults over the base, and the
    values the case ``written`` itself over both.
    """
    table: dict[str, Any] = {}
    if case_dir is not None and config_name is not None:
        if (Path(case_dir) / config_name).exists():
            solver_table = load_case_config(Path(case_dir), config_name).get("solver") or {}
            table = dict(solver_table.get("boussinesq") or {})
    if is_default_engine_solver(solver):
        return FlowRuntimeConfig.model_validate(table)
    chosen = apply_analytical_boussinesq_runtime_defaults(
        dict(written or {}), flow_regime=flow_regime
    )
    return FlowRuntimeConfig.model_validate({**table, **chosen})


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
    options: FlowRuntimeConfig | None = None,
) -> RunState:
    """Return the run state the Boussinesq adapter reads for a run on a mesh bundle.

    The state carries the ``Model`` of ``flow`` and a ``[solver]`` section whose
    ``[solver.boussinesq]`` table is ``options``, the defaults when none is given.
    The scratch folder is ``simulations_folder``.
    """
    solver = SolverConfig() if options is None else SolverConfig(boussinesq=options)
    return RunState(
        cfg=SimpleNamespace(flow=flow.config, solver=solver),
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
    "boussinesq_variant_options",
    "is_default_engine_solver",
    "set_analytical_boussinesq_runtime_defaults_in_place",
]
