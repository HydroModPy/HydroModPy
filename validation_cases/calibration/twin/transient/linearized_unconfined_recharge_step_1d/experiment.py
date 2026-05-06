"""Same-solver twin benchmark for transient K+Sy recovery."""

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

CASE_DIR = (
    Path(__file__).resolve().parents[4]
    / "analytical"
    / "transient"
    / "linearized_unconfined_recharge_step_1d"
)


def build_simulation_config(path: Path, project_root: Path) -> None:
    """Write one MODFLOW 6 simulation config for the transient twin benchmark."""
    from validation_cases.shared.runtime import _dump_toml

    payload = _merge_toml_payloads(
        _read_toml(CASE_DIR / "config_modflownwt.toml"),
        _read_toml(CASE_DIR / "config_modflow6.toml"),
    )
    payload.setdefault("workspace", {})["project_root"] = str(project_root)
    payload.setdefault("simulation", {})["run_id"] = "transient_lu_truth"
    path.write_text(_dump_toml(payload), encoding="utf-8", newline="\n")


def _gp_mapping_profile(*, seed: int = 13) -> CalibrationMethodProfile:
    """Return one compact GP-mapping profile suited to transient K+Sy recovery."""
    return CalibrationMethodProfile(
        name="gp_mapping",
        method_kwargs={
            "seed": int(seed),
            "n_init": 10,
            "n_refine": 3,
            "batch_size": 2,
            "n_restarts": 160,
            "kappa": 2.0,
            "alpha": 1.0e-6,
            "jitter": 1.0e-8,
        },
        persist_model_distribution=True,
        success_metric="best_fit_or_distribution",
    )


def _cma_es_profile(*, seed: int = 13) -> CalibrationMethodProfile:
    """Return one compact CMA-ES profile for transient K+Sy recovery."""
    return CalibrationMethodProfile(
        name="cma_es",
        method_kwargs={
            "sigma0": 0.22,
            "popsize": 10,
            "max_evaluations": 40,
            "seed": int(seed),
            "normalize": True,
        },
        persist_model_distribution=False,
    )


_TRANSIENT_PARAMETER_TARGETS = {
    "K_global": TwinParameterTarget(
        target="flow.param.K.field.value",
        mode="replace",
    ),
    "Sy_global": TwinParameterTarget(
        target="flow.param.Sy.field.value",
        mode="replace",
    ),
}
_TRANSIENT_OUTPUT_SPECS = {
    "head_mid": TwinOutputSpec(
        variable="watertable_elevation",
        support="point",
        x=50.0,
        y=5.0,
        time="all",
    ),
    "q_east": TwinOutputSpec(
        variable="outlet_discharge",
        support="boundary",
        boundary_id="east_side",
        time="all",
    ),
}
_TRANSIENT_OBJECTIVE_BLOCK_SPECS = (
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
_TRANSIENT_FLUX_ONLY_OUTPUT_SPECS = {
    "q_east": TwinOutputSpec(
        variable="outlet_discharge",
        support="boundary",
        boundary_id="east_side",
        time="all",
    ),
}
_TRANSIENT_FLUX_ONLY_OBJECTIVE_BLOCK_SPECS = (
    TwinObjectiveBlockSpec(
        name="flux",
        metric="rmse",
        weight=1.0,
        uses_outputs=("q_east",),
        normalize_cost=True,
    ),
)


def _da_mh_gp_profile(*, seed: int = 13) -> CalibrationMethodProfile:
    """Return one compact delayed-acceptance GP-MH profile for transient K+Sy."""
    return CalibrationMethodProfile(
        name="da_mh_gp",
        method_kwargs={
            "sigma_noise": 0.1,
            "n_init": 10,
            "max_iter": 96,
            "burn_in": 24,
            "thin": 2,
            "proposal_sigma": 0.04,
            "retrain_interval": 5,
            "gp_alpha": 1.0e-6,
            "full_mh_prob": 0.05,
            "seed": int(seed),
            "cache_decimals": 10,
        },
        persist_model_distribution=True,
        success_metric="best_fit_or_distribution",
    )


TRANSIENT_RECHARGE_STEP_TWIN_CASE = TwinCalibrationCaseDefinition(
    case_id="calibration_twin_linearized_recharge_step_modflow6",
    solver_name="modflow6",
    regime="transient",
    description=(
        "Same-solver twin benchmark on linearized_unconfined_recharge_step_1d "
        "with K+Sy and multiobservable head/flux blocks."
    ),
    truth_params={"K_global": 1.0e-4, "Sy_global": 0.10},
    bounds={
        "K_global": (5.0e-5, 3.0e-4),
        "Sy_global": (0.04, 0.18),
    },
    parameter_abs_tolerances={
        "K_global": 1.5e-5,
        "Sy_global": 0.04,
    },
    output_names=("head_mid", "q_east"),
    method_profiles=(
        CalibrationMethodProfile(
            name="random_search",
            method_kwargs={"max_iter": 16, "seed": 11},
            persist_model_distribution=True,
        ),
        _cma_es_profile(seed=13),
        CalibrationMethodProfile(
            name="scipy_nelder_mead",
            method_kwargs={"maxiter": 12, "xatol": 1.0e-6, "fatol": 1.0e-6},
            persist_model_distribution=False,
        ),
        _gp_mapping_profile(seed=13),
        _da_mh_gp_profile(seed=13),
    ),
    fast=False,
    reference_objective_sample_count=169,
    reference_objective_sampling="sobol",
    reference_objective_seed=13,
    build_simulation_config=build_simulation_config,
    parameter_targets=_TRANSIENT_PARAMETER_TARGETS,
    output_specs=_TRANSIENT_OUTPUT_SPECS,
    objective_block_specs=_TRANSIENT_OBJECTIVE_BLOCK_SPECS,
)


TRANSIENT_RECHARGE_STEP_NOISY_TWIN_CASE = TwinCalibrationCaseDefinition(
    case_id="calibration_twin_linearized_recharge_step_noisy_modflow6",
    solver_name="modflow6",
    regime="transient",
    description=(
        "Same-solver noisy twin benchmark on linearized_unconfined_recharge_step_1d "
        "with K+Sy, multiobservable head/flux blocks, and repeated "
        "random-search seeds."
    ),
    truth_params={"K_global": 1.0e-4, "Sy_global": 0.10},
    bounds={
        "K_global": (5.0e-5, 3.0e-4),
        "Sy_global": (0.04, 0.18),
    },
    parameter_abs_tolerances={
        "K_global": 1.5e-5,
        "Sy_global": 0.04,
    },
    output_names=("head_mid", "q_east"),
    method_profiles=(
        CalibrationMethodProfile(
            name="random_search",
            method_kwargs={"max_iter": 24},
            persist_model_distribution=True,
            repeat_seeds=(11, 23, 37),
        ),
        _cma_es_profile(seed=13),
        CalibrationMethodProfile(
            name="scipy_nelder_mead",
            method_kwargs={"maxiter": 12, "xatol": 1.0e-6, "fatol": 1.0e-6},
            persist_model_distribution=False,
        ),
        _gp_mapping_profile(seed=13),
    ),
    fast=False,
    reference_objective_sample_count=169,
    reference_objective_sampling="sobol",
    reference_objective_seed=17,
    observation_noise=ObservationNoiseSpec(
        absolute_sigma_by_output={"head_mid": 0.005},
        relative_sigma_by_output={"q_east": 0.02},
        seed=17,
    ),
    build_simulation_config=build_simulation_config,
    parameter_targets=_TRANSIENT_PARAMETER_TARGETS,
    output_specs=_TRANSIENT_OUTPUT_SPECS,
    objective_block_specs=_TRANSIENT_OBJECTIVE_BLOCK_SPECS,
)


TRANSIENT_RECHARGE_STEP_FLUX_ONLY_NOISY_TWIN_CASE = TwinCalibrationCaseDefinition(
    case_id="calibration_twin_linearized_recharge_step_flux_only_noisy_modflow6",
    solver_name="modflow6",
    regime="transient",
    description=(
        "Same-solver noisy twin benchmark on linearized_unconfined_recharge_step_1d "
        "with K+Sy, flux-only outlet observations, and deliberately weak "
        "identifiability."
    ),
    truth_params={"K_global": 1.0e-4, "Sy_global": 0.10},
    bounds={
        "K_global": (5.0e-5, 3.0e-4),
        "Sy_global": (0.04, 0.18),
    },
    parameter_abs_tolerances={
        "K_global": 2.0e-5,
        "Sy_global": 0.05,
    },
    output_names=("q_east",),
    method_profiles=(
        CalibrationMethodProfile(
            name="random_search",
            method_kwargs={"max_iter": 24, "seed": 11},
            persist_model_distribution=True,
            success_metric="best_fit_or_distribution",
        ),
        CalibrationMethodProfile(
            name="cma_es",
            method_kwargs={
                "sigma0": 0.24,
                "popsize": 12,
                "max_evaluations": 56,
                "seed": 13,
                "normalize": True,
            },
            persist_model_distribution=False,
            success_metric="best_fit",
        ),
        CalibrationMethodProfile(
            name="scipy_nelder_mead",
            method_kwargs={"maxiter": 16, "xatol": 1.0e-6, "fatol": 1.0e-6},
            persist_model_distribution=False,
            success_metric="best_fit",
        ),
        CalibrationMethodProfile(
            name="gp_mapping",
            method_kwargs={
                "seed": 13,
                "n_init": 12,
                "n_refine": 4,
                "batch_size": 2,
                "n_restarts": 220,
                "kappa": 2.2,
                "alpha": 1.0e-6,
                "jitter": 1.0e-8,
            },
            persist_model_distribution=True,
            success_metric="best_fit_or_distribution",
        ),
        CalibrationMethodProfile(
            name="da_mh_gp",
            method_kwargs={
                "sigma_noise": 0.1,
                "n_init": 12,
                "max_iter": 128,
                "burn_in": 32,
                "thin": 2,
                "proposal_sigma": 0.05,
                "retrain_interval": 5,
                "gp_alpha": 1.0e-6,
                "full_mh_prob": 0.05,
                "seed": 13,
                "cache_decimals": 10,
            },
            persist_model_distribution=True,
            success_metric="best_fit_or_distribution",
        ),
    ),
    fast=False,
    observation_noise=ObservationNoiseSpec(
        relative_sigma_by_output={"q_east": 0.05},
        seed=31,
    ),
    perturbation_description=(
        "Only the outlet flux time series is observed; no head data are used, "
        "and 5% relative noise is added to strengthen the weakly constrained "
        "inverse setting."
    ),
    reference_objective_sample_count=256,
    reference_objective_sampling="sobol",
    reference_objective_seed=31,
    build_simulation_config=build_simulation_config,
    parameter_targets=_TRANSIENT_PARAMETER_TARGETS,
    output_specs=_TRANSIENT_FLUX_ONLY_OUTPUT_SPECS,
    objective_block_specs=_TRANSIENT_FLUX_ONLY_OBJECTIVE_BLOCK_SPECS,
)
