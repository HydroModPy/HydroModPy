"""Same-solver twin benchmark for steady scalar K recovery."""

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
    / "steady"
    / "dupuit_fixed_head_1d"
)


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
    planar = payload.setdefault("modflow6", {}).setdefault("sgrid", {}).setdefault(
        "planar",
        {},
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


def build_calibration_payload(
    simulation_config_name: str,
    calibration_id: str,
    observed_values: dict[str, tuple[float, ...]],
    method_profile: CalibrationMethodProfile,
) -> dict[str, Any]:
    """Build one calibration payload for the steady scalar twin benchmark."""
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
                    "name": "K_global_factor",
                    "property": "K",
                    "target": "flow.param.K.field_homogeneous.value",
                    "mode": "scale",
                    "parameterization": "global_factor",
                }
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
                }
            ],
            "objective_block": [
                {
                    "name": "flux",
                    "metric": "rmse",
                    "weight": 1.0,
                    "uses_outputs": ["q_east"],
                    "normalize_cost": True,
                }
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
            "K_global_factor": [0.8, 1.2],
        },
    }


def build_mesh_perturbed_calibration_payload(
    simulation_config_name: str,
    calibration_id: str,
    observed_values: dict[str, tuple[float, ...]],
    method_profile: CalibrationMethodProfile,
) -> dict[str, Any]:
    """Build one calibration payload for the mesh-perturbed steady twin benchmark."""
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
                    "name": "K_global_factor",
                    "property": "K",
                    "target": "flow.param.K.field_homogeneous.value",
                    "mode": "scale",
                    "parameterization": "global_factor",
                }
            ],
            "output": [
                {
                    "name": "head_mid",
                    "variable": "watertable_elevation",
                    "source": "runtime",
                    "support": "point",
                    "x": 200.0,
                    "y": 25.0,
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
            "K_global_factor": [0.8, 1.2],
        },
    }


def _gp_mapping_profile(*, seed: int = 7) -> CalibrationMethodProfile:
    """Return one compact GP-mapping profile suited to scalar steady twins."""
    return CalibrationMethodProfile(
        name="gp_mapping",
        method_kwargs={
            "seed": int(seed),
            "n_init": 6,
            "n_refine": 2,
            "batch_size": 2,
            "n_candidates": 100,
            "kappa": 2.0,
            "alpha": 1.0e-6,
            "jitter": 1.0e-8,
            "n_posterior_pool": 200,
            "n_posterior_samples": 48,
            "log_transform": True,
        },
        persist_model_distribution=True,
        success_metric="distribution",
    )


def _da_mh_gp_profile(*, seed: int = 7) -> CalibrationMethodProfile:
    """Return one compact delayed-acceptance MH profile for scalar steady twins."""
    return CalibrationMethodProfile(
        name="da_mh_gp",
        method_kwargs={
            "sigma_noise": 0.1,
            "n_init": 8,
            "n_samples": 80,
            "burn_in": 20,
            "thin": 2,
            "proposal_scale": 0.03,
            "retrain_interval": 5,
            "gp_noise": 1.0e-6,
            "full_mh_prob": 0.05,
            "seed": int(seed),
            "cache_decimals": 10,
        },
        persist_model_distribution=True,
        success_metric="distribution",
    )


STEADY_DUPUIT_TWIN_CASE = TwinCalibrationCaseDefinition(
    case_id="calibration_twin_dupuit_fixed_head_modflow6",
    solver_name="modflow6",
    regime="steady",
    description=(
        "Same-solver twin benchmark on dupuit_fixed_head_1d with one scalar "
        "K multiplier and one outlet-discharge observable."
    ),
    truth_params={"K_global_factor": 1.0},
    bounds={"K_global_factor": (0.8, 1.2)},
    parameter_abs_tolerances={"K_global_factor": 0.06},
    output_names=("q_east",),
    method_profiles=(
        CalibrationMethodProfile(
            name="grid_search",
            method_kwargs={"n_per_dim": 9},
            persist_model_distribution=False,
        ),
        CalibrationMethodProfile(
            name="random_search",
            method_kwargs={"n_samples": 16, "seed": 7},
            persist_model_distribution=True,
        ),
        CalibrationMethodProfile(
            name="simplex",
            method_kwargs={"max_iter": 24, "xtol": 1.0e-8, "ftol": 1.0e-8},
            persist_model_distribution=False,
        ),
    ),
    fast=True,
    build_simulation_config=build_simulation_config,
    build_calibration_payload=build_calibration_payload,
)


STEADY_DUPUIT_POSTERIOR_TWIN_CASE = TwinCalibrationCaseDefinition(
    case_id="calibration_twin_dupuit_fixed_head_posterior_modflow6",
    solver_name="modflow6",
    regime="steady",
    description=(
        "Same-solver posterior-oriented twin benchmark on dupuit_fixed_head_1d "
        "with one scalar K multiplier and distribution-valued methods."
    ),
    truth_params={"K_global_factor": 1.0},
    bounds={"K_global_factor": (0.8, 1.2)},
    parameter_abs_tolerances={"K_global_factor": 0.06},
    output_names=("q_east",),
    method_profiles=(
        CalibrationMethodProfile(
            name="random_search",
            method_kwargs={"n_samples": 16, "seed": 7},
            persist_model_distribution=True,
            success_metric="distribution",
        ),
        _gp_mapping_profile(seed=7),
        _da_mh_gp_profile(seed=7),
    ),
    fast=False,
    build_simulation_config=build_simulation_config,
    build_calibration_payload=build_calibration_payload,
)


STEADY_DUPUIT_MESH_PERTURBED_TWIN_CASE = TwinCalibrationCaseDefinition(
    case_id="calibration_twin_dupuit_fixed_head_mesh_perturbed_modflow6",
    solver_name="modflow6",
    regime="steady",
    description=(
        "Perturbed twin benchmark on dupuit_fixed_head_1d with one scalar K "
        "multiplier, truth generated on a refined mesh, and calibration run "
        "on the standard mesh."
    ),
    truth_params={"K_global_factor": 1.0},
    bounds={"K_global_factor": (0.8, 1.2)},
    parameter_abs_tolerances={"K_global_factor": 0.08},
    output_names=("head_mid", "q_east"),
    method_profiles=(
        CalibrationMethodProfile(
            name="grid_search",
            method_kwargs={"n_per_dim": 9},
            persist_model_distribution=False,
        ),
        CalibrationMethodProfile(
            name="random_search",
            method_kwargs={"n_samples": 24, "seed": 7},
            persist_model_distribution=True,
            success_metric="best_fit_or_distribution",
        ),
        CalibrationMethodProfile(
            name="simplex",
            method_kwargs={"max_iter": 24, "xtol": 1.0e-8, "ftol": 1.0e-8},
            persist_model_distribution=False,
        ),
    ),
    fast=False,
    perturbation_description=(
        "Truth observations come from a refined 80x5 MODFLOW 6 mesh while "
        "calibration candidates run on the default 40x5 mesh."
    ),
    build_simulation_config=build_simulation_config,
    build_truth_simulation_config=build_truth_simulation_config_refined,
    build_calibration_payload=build_mesh_perturbed_calibration_payload,
)


STEADY_DUPUIT_NOISY_TWIN_CASE = TwinCalibrationCaseDefinition(
    case_id="calibration_twin_dupuit_fixed_head_noisy_modflow6",
    solver_name="modflow6",
    regime="steady",
    description=(
        "Same-solver noisy twin benchmark on dupuit_fixed_head_1d with one "
        "scalar K multiplier, one outlet-discharge observable, and repeated "
        "random-search seeds."
    ),
    truth_params={"K_global_factor": 1.0},
    bounds={"K_global_factor": (0.8, 1.2)},
    parameter_abs_tolerances={"K_global_factor": 0.06},
    output_names=("q_east",),
    method_profiles=(
        CalibrationMethodProfile(
            name="grid_search",
            method_kwargs={"n_per_dim": 9},
            persist_model_distribution=False,
        ),
        CalibrationMethodProfile(
            name="random_search",
            method_kwargs={"n_samples": 16},
            persist_model_distribution=True,
            repeat_seeds=(7, 11, 19),
        ),
        CalibrationMethodProfile(
            name="simplex",
            method_kwargs={"max_iter": 24, "xtol": 1.0e-8, "ftol": 1.0e-8},
            persist_model_distribution=False,
        ),
    ),
    fast=False,
    observation_noise=ObservationNoiseSpec(
        relative_sigma_by_output={"q_east": 0.01},
        seed=21,
    ),
    build_simulation_config=build_simulation_config,
    build_calibration_payload=build_calibration_payload,
)
