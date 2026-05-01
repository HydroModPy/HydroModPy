"""Same-solver twin benchmark for steady piecewise-K recovery."""

from __future__ import annotations

from pathlib import Path

from validation_cases.calibration.shared.definitions import (
    CalibrationMethodProfile,
    TwinCalibrationCaseDefinition,
    TwinObjectiveBlockSpec,
    TwinOutputSpec,
    TwinParameterTarget,
)
from validation_cases.shared.runtime import _merge_toml_payloads, _read_toml

CASE_DIR = (
    Path(__file__).resolve().parents[4]
    / "analytical"
    / "steady"
    / "boussinesq_fixed_head_piecewise_k_1d"
)


def build_simulation_config(path: Path, project_root: Path) -> None:
    """Write one MODFLOW 6 simulation config for the steady piecewise-K benchmark."""
    from validation_cases.shared.runtime import _dump_toml

    payload = _merge_toml_payloads(
        _read_toml(CASE_DIR / "config_modflownwt.toml"),
        _read_toml(CASE_DIR / "config_modflow6.toml"),
    )
    payload.setdefault("workspace", {})["project_root"] = str(project_root)
    payload.setdefault("simulation", {})["run_id"] = "steady_piecewise_k_truth"
    path.write_text(_dump_toml(payload), encoding="utf-8", newline="\n")


def _cma_es_profile(*, seed: int = 17) -> CalibrationMethodProfile:
    """Return one compact CMA-ES profile for piecewise-K recovery."""
    return CalibrationMethodProfile(
        name="cma_es",
        method_kwargs={
            "sigma0": 0.22,
            "popsize": 14,
            "max_evaluations": 126,
            "seed": int(seed),
            "normalize": True,
            "restarts": 1,
        },
        persist_model_distribution=False,
    )


_PIECEWISE_K_PARAMETER_TARGETS = {
    "K_west": TwinParameterTarget(
        target="flow.param.K.values.west_zone",
        mode="replace",
    ),
    "K_middle": TwinParameterTarget(
        target="flow.param.K.values.middle_zone",
        mode="replace",
    ),
    "K_east": TwinParameterTarget(
        target="flow.param.K.values.east_zone",
        mode="replace",
    ),
}
_PIECEWISE_K_OUTPUT_SPECS = {
    "head_west": TwinOutputSpec(
        variable="watertable_elevation",
        support="point",
        x=60.0,
        y=25.0,
        time="all",
    ),
    "head_middle": TwinOutputSpec(
        variable="watertable_elevation",
        support="point",
        x=200.0,
        y=25.0,
        time="all",
    ),
    "head_east": TwinOutputSpec(
        variable="watertable_elevation",
        support="point",
        x=340.0,
        y=25.0,
        time="all",
    ),
    "q_east": TwinOutputSpec(
        variable="outlet_discharge",
        support="boundary",
        boundary_id="east_side",
        time="all",
    ),
}
_PIECEWISE_K_OBJECTIVE_BLOCK_SPECS = (
    TwinObjectiveBlockSpec(
        name="heads",
        metric="rmse",
        weight=1.0,
        uses_outputs=("head_west", "head_middle", "head_east"),
        normalize_cost=True,
    ),
    TwinObjectiveBlockSpec(
        name="flux",
        metric="rmse",
        weight=1.0,
        uses_outputs=("q_east",),
        normalize_cost=True,
    ),
)


PIECEWISE_K_TWIN_CASE = TwinCalibrationCaseDefinition(
    case_id="calibration_twin_boussinesq_fixed_head_piecewise_k_modflow6",
    solver_name="modflow6",
    regime="steady",
    description=(
        "Same-solver twin benchmark on boussinesq_fixed_head_piecewise_k_1d "
        "with three zoned hydraulic-conductivity parameters and head/flux "
        "observables."
    ),
    truth_params={
        "K_west": 2.0e-4,
        "K_middle": 5.0e-5,
        "K_east": 1.0e-4,
    },
    bounds={
        "K_west": (7.5e-5, 3.5e-4),
        "K_middle": (1.5e-5, 1.2e-4),
        "K_east": (3.5e-5, 1.75e-4),
    },
    parameter_abs_tolerances={
        "K_west": 2.5e-5,
        "K_middle": 1.5e-5,
        "K_east": 1.5e-5,
    },
    output_names=("head_west", "head_middle", "head_east", "q_east"),
    method_profiles=(
        CalibrationMethodProfile(
            name="random_search",
            method_kwargs={"max_iter": 96},
            persist_model_distribution=True,
            repeat_seeds=(17, 29),
            success_metric="distribution",
        ),
        _cma_es_profile(seed=17),
        CalibrationMethodProfile(
            name="scipy_nelder_mead",
            method_kwargs={"maxiter": 42, "xatol": 1.0e-8, "fatol": 1.0e-8},
            persist_model_distribution=False,
        ),
    ),
    fast=False,
    reference_objective_sample_count=192,
    reference_objective_sampling="sobol",
    reference_objective_seed=17,
    build_simulation_config=build_simulation_config,
    parameter_targets=_PIECEWISE_K_PARAMETER_TARGETS,
    output_specs=_PIECEWISE_K_OUTPUT_SPECS,
    objective_block_specs=_PIECEWISE_K_OBJECTIVE_BLOCK_SPECS,
)
