"""Same-solver twin benchmark for transient K+Sy recovery."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from validation_cases.calibration.shared.definitions import (
    CalibrationMethodProfile,
    ObservationNoiseSpec,
    TwinCalibrationCaseDefinition,
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


def build_calibration_payload(
    simulation_config_name: str,
    calibration_id: str,
    observed_values: dict[str, tuple[float, ...]],
    method_profile: CalibrationMethodProfile,
) -> dict[str, Any]:
    """Build one calibration payload for the transient multiobservable twin benchmark."""
    return {
        "model_calibration": {
            "simulation_config": simulation_config_name,
            "calibration_id": calibration_id,
            "disable_display": True,
            "disable_postprocess": True,
            "rerun_best_with_outputs": False,
            "persist_model_distribution": bool(method_profile.persist_model_distribution),
            "rerun_model_distribution_with_outputs": False,
            "persist_iteration_history": True,
            "persist_iteration_detail_level": "minimal",
            "persist_calibration_report": True,
            "resume_existing_session": False,
            "reuse_persisted_iterations": False,
            "parameter": [
                {
                    "name": "K_global",
                    "property": "K",
                    "target": "flow.param.K.field_homogeneous.value",
                    "mode": "replace",
                    "parameterization": "global_value",
                },
                {
                    "name": "Sy_global",
                    "property": "Sy",
                    "target": "flow.param.Sy.field_homogeneous.value",
                    "mode": "replace",
                    "parameterization": "global_value",
                },
            ],
            "output": [
                {
                    "name": "head_mid",
                    "variable": "watertable_elevation",
                    "source": "runtime",
                    "support": "point",
                    "x": 50.0,
                    "y": 5.0,
                    "time": "all",
                    "observed_values": list(observed_values["head_mid"]),
                },
                {
                    "name": "q_east",
                    "variable": "outlet_discharge",
                    "source": "runtime",
                    "support": "boundary",
                    "boundary_id": "east_side",
                    "time": "all",
                    "observed_values": list(observed_values["q_east"]),
                },
            ],
            "objective_block": [
                {
                    "name": "heads",
                    "metric": "rmse",
                    "weight": 1.0,
                    "uses_outputs": ["head_mid"],
                    "normalize_cost": True,
                },
                {
                    "name": "flux",
                    "metric": "rmse",
                    "weight": 1.0,
                    "uses_outputs": ["q_east"],
                    "normalize_cost": True,
                },
            ],
        },
        "calibration": {
            "objective_metric": "rmse",
            "global_method": method_profile.name,
        },
        "objective": {
            "transform": "identity",
        },
        "calibration_method": {
            method_profile.name: dict(method_profile.method_kwargs),
        },
        "bounds": {
            "K_global": [5.0e-5, 3.0e-4],
            "Sy_global": [0.04, 0.18],
        },
    }


def build_flux_only_calibration_payload(
    simulation_config_name: str,
    calibration_id: str,
    observed_values: dict[str, tuple[float, ...]],
    method_profile: CalibrationMethodProfile,
) -> dict[str, Any]:
    """Build one flux-only calibration payload for the ill-conditioned K+Sy twin benchmark."""
    return {
        "model_calibration": {
            "simulation_config": simulation_config_name,
            "calibration_id": calibration_id,
            "disable_display": True,
            "disable_postprocess": True,
            "rerun_best_with_outputs": False,
            "persist_model_distribution": bool(method_profile.persist_model_distribution),
            "rerun_model_distribution_with_outputs": False,
            "persist_iteration_history": True,
            "persist_iteration_detail_level": "minimal",
            "persist_calibration_report": True,
            "resume_existing_session": False,
            "reuse_persisted_iterations": False,
            "parameter": [
                {
                    "name": "K_global",
                    "property": "K",
                    "target": "flow.param.K.field_homogeneous.value",
                    "mode": "replace",
                    "parameterization": "global_value",
                },
                {
                    "name": "Sy_global",
                    "property": "Sy",
                    "target": "flow.param.Sy.field_homogeneous.value",
                    "mode": "replace",
                    "parameterization": "global_value",
                },
            ],
            "output": [
                {
                    "name": "q_east",
                    "variable": "outlet_discharge",
                    "source": "runtime",
                    "support": "boundary",
                    "boundary_id": "east_side",
                    "time": "all",
                    "observed_values": list(observed_values["q_east"]),
                },
            ],
            "objective_block": [
                {
                    "name": "flux",
                    "metric": "rmse",
                    "weight": 1.0,
                    "uses_outputs": ["q_east"],
                    "normalize_cost": True,
                },
            ],
        },
        "calibration": {
            "objective_metric": "rmse",
            "global_method": method_profile.name,
        },
        "objective": {
            "transform": "identity",
        },
        "calibration_method": {
            method_profile.name: dict(method_profile.method_kwargs),
        },
        "bounds": {
            "K_global": [5.0e-5, 3.0e-4],
            "Sy_global": [0.04, 0.18],
        },
    }


def _gp_mapping_profile(*, seed: int = 13) -> CalibrationMethodProfile:
    """Return one compact GP-mapping profile suited to transient K+Sy recovery."""
    return CalibrationMethodProfile(
        name="gp_mapping",
        method_kwargs={
            "seed": int(seed),
            "n_init": 10,
            "n_refine": 3,
            "batch_size": 2,
            "n_candidates": 160,
            "kappa": 2.0,
            "alpha": 1.0e-6,
            "jitter": 1.0e-8,
            "n_posterior_pool": 280,
            "n_posterior_samples": 64,
            "log_transform": False,
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


def _da_mh_gp_profile(*, seed: int = 13) -> CalibrationMethodProfile:
    """Return one compact delayed-acceptance GP-MH profile for transient K+Sy."""
    return CalibrationMethodProfile(
        name="da_mh_gp",
        method_kwargs={
            "sigma_noise": 0.1,
            "n_init": 10,
            "n_samples": 96,
            "burn_in": 24,
            "thin": 2,
            "proposal_scale": 0.04,
            "retrain_interval": 5,
            "gp_noise": 1.0e-6,
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
            method_kwargs={"n_samples": 16, "seed": 11},
            persist_model_distribution=True,
        ),
        _cma_es_profile(seed=13),
        CalibrationMethodProfile(
            name="simplex",
            method_kwargs={"max_iter": 12, "xtol": 1.0e-6, "ftol": 1.0e-6},
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
    build_calibration_payload=build_calibration_payload,
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
            method_kwargs={"n_samples": 24},
            persist_model_distribution=True,
            repeat_seeds=(11, 23, 37),
        ),
        _cma_es_profile(seed=13),
        CalibrationMethodProfile(
            name="simplex",
            method_kwargs={"max_iter": 12, "xtol": 1.0e-6, "ftol": 1.0e-6},
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
    build_calibration_payload=build_calibration_payload,
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
            method_kwargs={"n_samples": 24, "seed": 11},
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
            name="simplex",
            method_kwargs={"max_iter": 16, "xtol": 1.0e-6, "ftol": 1.0e-6},
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
                "n_candidates": 220,
                "kappa": 2.2,
                "alpha": 1.0e-6,
                "jitter": 1.0e-8,
                "n_posterior_pool": 320,
                "n_posterior_samples": 96,
                "log_transform": False,
            },
            persist_model_distribution=True,
            success_metric="best_fit_or_distribution",
        ),
        CalibrationMethodProfile(
            name="da_mh_gp",
            method_kwargs={
                "sigma_noise": 0.1,
                "n_init": 12,
                "n_samples": 128,
                "burn_in": 32,
                "thin": 2,
                "proposal_scale": 0.05,
                "retrain_interval": 5,
                "gp_noise": 1.0e-6,
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
    build_calibration_payload=build_flux_only_calibration_payload,
)
