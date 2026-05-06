"""Same-solver twin benchmark for steady scalar K recovery."""

from __future__ import annotations

from pathlib import Path

from validation_cases.calibration.shared.definitions import (
    CalibrationMethodProfile,
    ObservationNoiseSpec,
    TwinCalibrationCaseDefinition,
    TwinObjectiveBlockSpec,
    TwinOutputSpec,
    TwinParameterTarget,
)
from validation_cases.shared.runtime import _merge_toml_payloads, _read_toml

CASE_DIR = Path(__file__).resolve().parents[4] / "analytical" / "steady" / "dupuit_fixed_head_1d"


def _build_modflow6_simulation_config(
    path: Path,
    project_root: Path,
    *,
    run_id: str,
    nx: int,
    ny: int = 5,
) -> None:
    """Write one MODFLOW 6 simulation config with configurable planar resolution."""
    from validation_cases.shared.runtime import _dump_toml

    payload = _merge_toml_payloads(
        _read_toml(CASE_DIR / "config_common.toml"),
        _read_toml(CASE_DIR / "config_modflow6.toml"),
    )
    payload.setdefault("workspace", {})["project_root"] = str(project_root)
    payload.setdefault("simulation", {})["run_id"] = str(run_id)
    planar = (
        payload.setdefault("modflow6", {})
        .setdefault("sgrid", {})
        .setdefault(
            "planar",
            {},
        )
    )
    planar["nx"] = int(nx)
    planar["ny"] = int(ny)
    path.write_text(_dump_toml(payload), encoding="utf-8", newline="\n")


def build_simulation_config(path: Path, project_root: Path) -> None:
    """Write one MODFLOW 6 simulation config for the steady twin benchmark."""
    _build_modflow6_simulation_config(
        path,
        project_root,
        run_id="steady_dupuit_truth",
        nx=40,
    )


def build_truth_simulation_config_refined(path: Path, project_root: Path) -> None:
    """Write one refined MODFLOW 6 truth config used for perturbed twins."""
    _build_modflow6_simulation_config(
        path,
        project_root,
        run_id="steady_dupuit_truth_refined",
        nx=80,
    )


def _gp_mapping_profile(*, seed: int = 7) -> CalibrationMethodProfile:
    """Return one compact GP-mapping profile suited to scalar steady twins."""
    return CalibrationMethodProfile(
        name="gp_mapping",
        method_kwargs={
            "seed": int(seed),
            "n_init": 8,
            "n_refine": 3,
            "batch_size": 2,
            "n_restarts": 140,
            "kappa": 2.0,
            "alpha": 1.0e-6,
            "jitter": 1.0e-8,
        },
        persist_model_distribution=True,
        success_metric="distribution",
    )


def _cma_es_profile(*, seed: int = 7) -> CalibrationMethodProfile:
    """Return one compact CMA-ES profile for scalar steady twins."""
    return CalibrationMethodProfile(
        name="cma_es",
        method_kwargs={
            "sigma0": 0.18,
            "popsize": 8,
            "max_evaluations": 28,
            "seed": int(seed),
            "normalize": True,
        },
        persist_model_distribution=False,
    )


def _da_mh_gp_profile(*, seed: int = 7) -> CalibrationMethodProfile:
    """Return one compact delayed-acceptance MH profile for scalar steady twins."""
    return CalibrationMethodProfile(
        name="da_mh_gp",
        method_kwargs={
            "sigma_noise": 0.1,
            "n_init": 10,
            "max_iter": 96,
            "burn_in": 24,
            "thin": 2,
            "proposal_sigma": 0.05,
            "retrain_interval": 5,
            "gp_alpha": 1.0e-6,
            "full_mh_prob": 0.05,
            "seed": int(seed),
            "cache_decimals": 10,
        },
        persist_model_distribution=True,
        success_metric="distribution",
    )


_STEADY_DUPUIT_PARAMETER_TARGETS = {
    "K_global": TwinParameterTarget(
        target="flow.param.K.field_homogeneous.value",
        mode="replace",
    ),
}
_STEADY_DUPUIT_OUTPUT_SPECS = {
    "q_east": TwinOutputSpec(
        variable="outlet_discharge",
        support="boundary",
        boundary_id="east_side",
        time="all",
    ),
}
_STEADY_DUPUIT_OBJECTIVE_BLOCK_SPECS = (
    TwinObjectiveBlockSpec(
        name="flux",
        metric="rmse",
        weight=1.0,
        uses_outputs=("q_east",),
        normalize_cost=True,
    ),
)


STEADY_DUPUIT_TWIN_CASE = TwinCalibrationCaseDefinition(
    case_id="calibration_twin_dupuit_fixed_head_modflow6",
    solver_name="modflow6",
    regime="steady",
    description=(
        "Same-solver twin benchmark on dupuit_fixed_head_1d with one scalar "
        "K value and one outlet-discharge observable."
    ),
    truth_params={"K_global": 1.0e-4},
    bounds={"K_global": (5.0e-5, 3.0e-4)},
    parameter_abs_tolerances={"K_global": 2.0e-5},
    output_names=("q_east",),
    method_profiles=(
        CalibrationMethodProfile(
            name="grid",
            method_kwargs={"points_per_dim": 11},
            persist_model_distribution=False,
        ),
        CalibrationMethodProfile(
            name="random_search",
            method_kwargs={"max_iter": 24, "seed": 7},
            persist_model_distribution=True,
        ),
        _cma_es_profile(seed=7),
        CalibrationMethodProfile(
            name="scipy_nelder_mead",
            method_kwargs={"maxiter": 30, "xatol": 1.0e-8, "fatol": 1.0e-8},
            persist_model_distribution=False,
        ),
        CalibrationMethodProfile(
            name="scipy_nelder_mead",
            method_kwargs={"maxiter": 32},
            persist_model_distribution=False,
        ),
    ),
    fast=True,
    reference_objective_sample_count=41,
    reference_objective_sampling="sobol",
    reference_objective_seed=7,
    build_simulation_config=build_simulation_config,
    parameter_targets=_STEADY_DUPUIT_PARAMETER_TARGETS,
    output_specs=_STEADY_DUPUIT_OUTPUT_SPECS,
    objective_block_specs=_STEADY_DUPUIT_OBJECTIVE_BLOCK_SPECS,
)


STEADY_DUPUIT_POSTERIOR_TWIN_CASE = TwinCalibrationCaseDefinition(
    case_id="calibration_twin_dupuit_fixed_head_posterior_modflow6",
    solver_name="modflow6",
    regime="steady",
    description=(
        "Same-solver posterior-oriented twin benchmark on dupuit_fixed_head_1d "
        "with one scalar K value and distribution-valued methods."
    ),
    truth_params={"K_global": 1.0e-4},
    bounds={"K_global": (5.0e-5, 3.0e-4)},
    parameter_abs_tolerances={"K_global": 2.0e-5},
    output_names=("q_east",),
    method_profiles=(
        CalibrationMethodProfile(
            name="random_search",
            method_kwargs={"max_iter": 24, "seed": 7},
            persist_model_distribution=True,
            success_metric="distribution",
        ),
        _cma_es_profile(seed=7),
        _gp_mapping_profile(seed=7),
        _da_mh_gp_profile(seed=7),
    ),
    fast=False,
    reference_objective_sample_count=41,
    reference_objective_sampling="sobol",
    reference_objective_seed=7,
    build_simulation_config=build_simulation_config,
    parameter_targets=_STEADY_DUPUIT_PARAMETER_TARGETS,
    output_specs=_STEADY_DUPUIT_OUTPUT_SPECS,
    objective_block_specs=_STEADY_DUPUIT_OBJECTIVE_BLOCK_SPECS,
)


_STEADY_DUPUIT_MESH_PERTURBED_OUTPUT_SPECS = {
    "head_mid": TwinOutputSpec(
        variable="watertable_elevation",
        support="point",
        x=200.0,
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
_STEADY_DUPUIT_MESH_PERTURBED_OBJECTIVE_BLOCK_SPECS = (
    TwinObjectiveBlockSpec(
        name="heads",
        metric="rmse",
        weight=1.0,
        uses_outputs=("head_mid",),
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


STEADY_DUPUIT_MESH_PERTURBED_TWIN_CASE = TwinCalibrationCaseDefinition(
    case_id="calibration_twin_dupuit_fixed_head_mesh_perturbed_modflow6",
    solver_name="modflow6",
    regime="steady",
    description=(
        "Perturbed twin benchmark on dupuit_fixed_head_1d with one scalar K "
        "value, truth generated on a refined mesh, and calibration run "
        "on the standard mesh."
    ),
    truth_params={"K_global": 1.0e-4},
    bounds={"K_global": (5.0e-5, 3.0e-4)},
    parameter_abs_tolerances={"K_global": 2.5e-5},
    output_names=("head_mid", "q_east"),
    method_profiles=(
        CalibrationMethodProfile(
            name="grid",
            method_kwargs={"points_per_dim": 11},
            persist_model_distribution=False,
        ),
        CalibrationMethodProfile(
            name="random_search",
            method_kwargs={"max_iter": 32, "seed": 7},
            persist_model_distribution=True,
            success_metric="best_fit_or_distribution",
        ),
        _cma_es_profile(seed=7),
        CalibrationMethodProfile(
            name="scipy_nelder_mead",
            method_kwargs={"maxiter": 30, "xatol": 1.0e-8, "fatol": 1.0e-8},
            persist_model_distribution=False,
        ),
    ),
    fast=False,
    perturbation_description=(
        "Truth observations come from a refined 80x5 MODFLOW 6 mesh while "
        "calibration candidates run on the default 40x5 mesh."
    ),
    reference_objective_sample_count=49,
    reference_objective_sampling="sobol",
    reference_objective_seed=11,
    build_simulation_config=build_simulation_config,
    build_truth_simulation_config=build_truth_simulation_config_refined,
    parameter_targets=_STEADY_DUPUIT_PARAMETER_TARGETS,
    output_specs=_STEADY_DUPUIT_MESH_PERTURBED_OUTPUT_SPECS,
    objective_block_specs=_STEADY_DUPUIT_MESH_PERTURBED_OBJECTIVE_BLOCK_SPECS,
)


STEADY_DUPUIT_NOISY_TWIN_CASE = TwinCalibrationCaseDefinition(
    case_id="calibration_twin_dupuit_fixed_head_noisy_modflow6",
    solver_name="modflow6",
    regime="steady",
    description=(
        "Same-solver noisy twin benchmark on dupuit_fixed_head_1d with one "
        "scalar K value, one outlet-discharge observable, and repeated "
        "random-search seeds."
    ),
    truth_params={"K_global": 1.0e-4},
    bounds={"K_global": (5.0e-5, 3.0e-4)},
    parameter_abs_tolerances={"K_global": 2.0e-5},
    output_names=("q_east",),
    method_profiles=(
        CalibrationMethodProfile(
            name="grid",
            method_kwargs={"points_per_dim": 11},
            persist_model_distribution=False,
        ),
        CalibrationMethodProfile(
            name="random_search",
            method_kwargs={"max_iter": 24},
            persist_model_distribution=True,
            repeat_seeds=(7, 11, 19),
        ),
        _cma_es_profile(seed=7),
        CalibrationMethodProfile(
            name="scipy_nelder_mead",
            method_kwargs={"maxiter": 30, "xatol": 1.0e-8, "fatol": 1.0e-8},
            persist_model_distribution=False,
        ),
    ),
    fast=False,
    observation_noise=ObservationNoiseSpec(
        relative_sigma_by_output={"q_east": 0.01},
        seed=21,
    ),
    reference_objective_sample_count=41,
    reference_objective_sampling="sobol",
    reference_objective_seed=21,
    build_simulation_config=build_simulation_config,
    parameter_targets=_STEADY_DUPUIT_PARAMETER_TARGETS,
    output_specs=_STEADY_DUPUIT_OUTPUT_SPECS,
    objective_block_specs=_STEADY_DUPUIT_OBJECTIVE_BLOCK_SPECS,
)
