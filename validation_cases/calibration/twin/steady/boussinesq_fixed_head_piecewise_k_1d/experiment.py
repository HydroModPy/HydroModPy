"""Same-solver twin benchmark for steady piecewise-K recovery."""

from __future__ import annotations

from pathlib import Path
from typing import Any

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


def build_calibration_payload(
    simulation_config_name: str,
    calibration_id: str,
    observed_values: dict[str, tuple[float, ...]],
    method_profile: CalibrationMethodProfile,
) -> dict[str, Any]:
    """Build one calibration payload for the piecewise-K twin benchmark."""
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
                    "name": "K_west",
                    "property": "K",
                    "target": "flow.param.K.values_by_key.west_zone",
                    "mode": "replace",
                    "parameterization": "lithology_value",
                },
                {
                    "name": "K_middle",
                    "property": "K",
                    "target": "flow.param.K.values_by_key.middle_zone",
                    "mode": "replace",
                    "parameterization": "lithology_value",
                },
                {
                    "name": "K_east",
                    "property": "K",
                    "target": "flow.param.K.values_by_key.east_zone",
                    "mode": "replace",
                    "parameterization": "lithology_value",
                },
            ],
            "output": [
                {
                    "name": "head_west",
                    "variable": "watertable_elevation",
                    "source": "runtime",
                    "support": "point",
                    "x": 60.0,
                    "y": 25.0,
                    "time": "all",
                    "observed_values": list(observed_values["head_west"]),
                },
                {
                    "name": "head_middle",
                    "variable": "watertable_elevation",
                    "source": "runtime",
                    "support": "point",
                    "x": 200.0,
                    "y": 25.0,
                    "time": "all",
                    "observed_values": list(observed_values["head_middle"]),
                },
                {
                    "name": "head_east",
                    "variable": "watertable_elevation",
                    "source": "runtime",
                    "support": "point",
                    "x": 340.0,
                    "y": 25.0,
                    "time": "all",
                    "observed_values": list(observed_values["head_east"]),
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
                    "uses_outputs": ["head_west", "head_middle", "head_east"],
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
            "K_west": [7.5e-5, 3.5e-4],
            "K_middle": [1.5e-5, 1.2e-4],
            "K_east": [3.5e-5, 1.75e-4],
        },
    }


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
    # The legacy bridge writes via the unresolved
    # ``flow.param.K.values_by_key.<zone>`` grammar; the v0.6 path forks
    # the validated Pydantic config where the heterogeneous values live
    # at ``flow.param.K.values.<zone>`` (the parent ``K`` entry is a dict
    # produced by ``HydroModPyConfig.from_toml``).
    "K_west": TwinParameterTarget(
        target="flow.param.K.values.west_zone",
        mode="replace",
        property_name="K",
        parameterization="lithology_value",
        lithology_key="west_zone",
    ),
    "K_middle": TwinParameterTarget(
        target="flow.param.K.values.middle_zone",
        mode="replace",
        property_name="K",
        parameterization="lithology_value",
        lithology_key="middle_zone",
    ),
    "K_east": TwinParameterTarget(
        target="flow.param.K.values.east_zone",
        mode="replace",
        property_name="K",
        parameterization="lithology_value",
        lithology_key="east_zone",
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
            method_kwargs={"n_samples": 96},
            persist_model_distribution=True,
            repeat_seeds=(17, 29),
            success_metric="distribution",
        ),
        _cma_es_profile(seed=17),
        CalibrationMethodProfile(
            name="simplex",
            method_kwargs={"max_iter": 42, "xtol": 1.0e-8, "ftol": 1.0e-8},
            persist_model_distribution=False,
        ),
    ),
    fast=False,
    reference_objective_sample_count=192,
    reference_objective_sampling="sobol",
    reference_objective_seed=17,
    build_simulation_config=build_simulation_config,
    build_calibration_payload=build_calibration_payload,
    parameter_targets=_PIECEWISE_K_PARAMETER_TARGETS,
    output_specs=_PIECEWISE_K_OUTPUT_SPECS,
    objective_block_specs=_PIECEWISE_K_OBJECTIVE_BLOCK_SPECS,
)
