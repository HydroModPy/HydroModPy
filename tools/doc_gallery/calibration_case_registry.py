"""Registry of calibration twin benchmarks exposed in the capability gallery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from validation_cases.calibration.twin.steady.boussinesq_fixed_head_piecewise_k_1d.experiment import (
    PIECEWISE_K_TWIN_CASE,
)
from validation_cases.calibration.twin.steady.dupuit_fixed_head_1d.experiment import (
    STEADY_DUPUIT_POSTERIOR_TWIN_CASE,
    STEADY_DUPUIT_TWIN_CASE,
)
from validation_cases.calibration.twin.transient.linearized_unconfined_recharge_step_1d.experiment import (
    TRANSIENT_RECHARGE_STEP_TWIN_CASE,
)

@dataclass(frozen=True, slots=True)
class CalibrationCaseRecord:
    """Gallery-facing description of one calibration twin benchmark."""

    slug: str
    title: str
    deck: str
    summary: str
    reproduction_command: str
    source_paths: tuple[str, ...]
    case_setup: tuple[str, ...]
    what_it_shows: tuple[str, ...]
    key_parameters: tuple[str, ...]
    how_to_read: tuple[str, ...]
    next_steps: tuple[str, ...]
    metadata: dict[str, Any]


def _noise_summary(definition: Any) -> str:
    noise = getattr(definition, "observation_noise", None)
    if noise is None:
        return "none"
    parts: list[str] = []
    if getattr(noise, "absolute_sigma_by_output", {}):
        parts.append(
            "absolute "
            + ", ".join(
                f"{name}={float(value):g}"
                for name, value in noise.absolute_sigma_by_output.items()
            )
        )
    if getattr(noise, "relative_sigma_by_output", {}):
        parts.append(
            "relative "
            + ", ".join(
                f"{name}={float(value):g}"
                for name, value in noise.relative_sigma_by_output.items()
            )
        )
    rendered = "; ".join(parts)
    if rendered == "":
        rendered = "configured"
    return f"{rendered}; seed={int(noise.seed)}"


def _parameter_labels(definition: Any) -> str:
    return ", ".join(str(name) for name in definition.truth_params.keys())


def _output_labels(definition: Any) -> str:
    return ", ".join(str(name) for name in definition.output_names)


def _method_labels(definition: Any) -> str:
    return ", ".join(str(profile.name) for profile in definition.method_profiles)


def _bounds_summary(definition: Any) -> str:
    return ", ".join(
        f"{name}=[{float(bounds[0]):.6g}, {float(bounds[1]):.6g}]"
        for name, bounds in definition.bounds.items()
    )


def _dedupe(items: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        clean = str(item).strip()
        if clean == "" or clean in seen:
            continue
        seen.add(clean)
        ordered.append(clean)
    return tuple(ordered)


def _record(
    *,
    definition: Any,
    definition_import_path: str,
    title: str,
    run_case_module: str,
    run_case_file: str,
    reproduction_command: str,
    display_method_name: str,
    evaluation_budget: int | None,
    gallery_method_names: tuple[str, ...] | None = None,
) -> CalibrationCaseRecord:
    source_paths = _dedupe(
        [
            "validation_cases/calibration/README.md",
            "validation_cases/calibration/run_benchmarks.py",
            "validation_cases/calibration/plotting.py",
            "validation_cases/calibration/shared/definitions.py",
            "validation_cases/calibration/shared/runtime.py",
            run_case_file,
            run_case_file.replace("run_case.py", "experiment.py"),
            "launchers/model_calibration/launcher.py",
            "launchers/model_calibration/runtime.py",
        ]
    )
    return CalibrationCaseRecord(
        slug=str(definition.case_id),
        title=title,
        deck=(
            f"{str(definition.regime).capitalize()} {definition.solver_name} "
            f"twin calibration benchmark with {_parameter_labels(definition)}."
        ),
        summary=str(definition.description),
        reproduction_command=reproduction_command,
        source_paths=source_paths,
        case_setup=(
            f"Solver: `{definition.solver_name}` in `{definition.regime}` regime.",
            f"Truth parameters: {_parameter_labels(definition)}.",
            f"Observed outputs: {_output_labels(definition)}.",
            f"Benchmarked methods: {_method_labels(definition)}.",
            f"Initial bounds widened to: {_bounds_summary(definition)}.",
        ),
        what_it_shows=(
            "A same-solver twin experiment where synthetic observations are generated first, then recovered through calibration on the same physics stack.",
            "A case-level configuration figure, an objective trace, and an objective landscape or pairwise projection for the selected display method.",
            "Per-method timing diagnostics with total calibration time plus average per-model preparation, simulation, and objective-evaluation costs.",
        ),
        key_parameters=(
            f"Calibrated parameters: {_parameter_labels(definition)}.",
            f"Outputs used in the composite objective: {_output_labels(definition)}.",
            f"Observation noise: {_noise_summary(definition)}.",
            (
                f"Perturbation: {definition.perturbation_description}."
                if definition.perturbation_description
                else "Perturbation: none."
            ),
        ),
        how_to_read=(
            "Open `case_configuration.png` first to understand the parameter block, outputs, and weighting before reading the optimization figures.",
            "Use `objective_trace` to judge convergence speed and `objective_landscape` to see where the evaluated candidates concentrate relative to the truth and the selected solution(s).",
            "Read timing metrics as benchmark diagnostics, not as universal solver performance numbers: they depend on the chosen method, case size, and evaluation budget.",
        ),
        next_steps=(
            "Compare this case with the other calibration gallery pages to see how deterministic and distribution-valued methods behave under different inverse problems.",
            "Use the full benchmark suite in `validation_cases/calibration` when you need multi-seed comparisons or noisy variants beyond the curated gallery subset.",
        ),
        metadata={
            "definition_import_path": definition_import_path,
            "run_case_module": run_case_module,
            "run_case_file": run_case_file,
            "display_method_name": str(display_method_name),
            "evaluation_budget": evaluation_budget,
            "gallery_method_names": (
                None
                if gallery_method_names is None
                else [str(name) for name in gallery_method_names]
            ),
            "solver_name": str(definition.solver_name),
            "regime": str(definition.regime),
            "truth_params": {
                str(name): float(value)
                for name, value in definition.truth_params.items()
            },
            "bounds": {
                str(name): [float(item) for item in values]
                for name, values in definition.bounds.items()
            },
            "parameter_abs_tolerances": {
                str(name): float(value)
                for name, value in definition.parameter_abs_tolerances.items()
            },
            "output_names": [str(name) for name in definition.output_names],
            "method_names": [str(profile.name) for profile in definition.method_profiles],
            "observation_noise": _noise_summary(definition),
            "perturbation_description": definition.perturbation_description,
            "fast": bool(definition.fast),
        },
    )


def build_calibration_case_records() -> tuple[CalibrationCaseRecord, ...]:
    """Return the curated calibration cases published in the capability gallery."""
    return (
        _record(
            definition=STEADY_DUPUIT_TWIN_CASE,
            definition_import_path=(
                "validation_cases.calibration.twin.steady."
                "dupuit_fixed_head_1d.experiment:STEADY_DUPUIT_TWIN_CASE"
            ),
            title="Calibration Twin: Dupuit Fixed-Head 1D",
            run_case_module="validation_cases.calibration.twin.steady.dupuit_fixed_head_1d.run_case",
            run_case_file="validation_cases/calibration/twin/steady/dupuit_fixed_head_1d/run_case.py",
            reproduction_command=(
                "python -m validation_cases.calibration.twin.steady."
                "dupuit_fixed_head_1d.run_case --case standard"
            ),
            display_method_name="random_search",
            evaluation_budget=None,
        ),
        _record(
            definition=STEADY_DUPUIT_POSTERIOR_TWIN_CASE,
            definition_import_path=(
                "validation_cases.calibration.twin.steady."
                "dupuit_fixed_head_1d.experiment:STEADY_DUPUIT_POSTERIOR_TWIN_CASE"
            ),
            title="Calibration Twin: Dupuit Posterior 1D",
            run_case_module="validation_cases.calibration.twin.steady.dupuit_fixed_head_1d.run_case",
            run_case_file="validation_cases/calibration/twin/steady/dupuit_fixed_head_1d/run_case.py",
            reproduction_command=(
                "python -m validation_cases.calibration.twin.steady."
                "dupuit_fixed_head_1d.run_case --case posterior"
            ),
            display_method_name="da_mh_gp",
            evaluation_budget=18,
        ),
        _record(
            definition=TRANSIENT_RECHARGE_STEP_TWIN_CASE,
            definition_import_path=(
                "validation_cases.calibration.twin.transient."
                "linearized_unconfined_recharge_step_1d.experiment:"
                "TRANSIENT_RECHARGE_STEP_TWIN_CASE"
            ),
            title="Calibration Twin: Recharge-Step K+Sy 1D",
            run_case_module="validation_cases.calibration.twin.transient.linearized_unconfined_recharge_step_1d.run_case",
            run_case_file="validation_cases/calibration/twin/transient/linearized_unconfined_recharge_step_1d/run_case.py",
            reproduction_command=(
                "python -m validation_cases.calibration.twin.transient."
                "linearized_unconfined_recharge_step_1d.run_case"
            ),
            display_method_name="gp_mapping",
            evaluation_budget=None,
        ),
        _record(
            definition=PIECEWISE_K_TWIN_CASE,
            definition_import_path=(
                "validation_cases.calibration.twin.steady."
                "boussinesq_fixed_head_piecewise_k_1d.experiment:"
                "PIECEWISE_K_TWIN_CASE"
            ),
            title="Calibration Twin: Piecewise-K 1D",
            run_case_module="validation_cases.calibration.twin.steady.boussinesq_fixed_head_piecewise_k_1d.run_case",
            run_case_file="validation_cases/calibration/twin/steady/boussinesq_fixed_head_piecewise_k_1d/run_case.py",
            reproduction_command=(
                "python -m validation_cases.calibration.twin.steady."
                "boussinesq_fixed_head_piecewise_k_1d.run_case"
            ),
            display_method_name="random_search",
            evaluation_budget=48,
        ),
    )


__all__ = [
    "CalibrationCaseRecord",
    "build_calibration_case_records",
]
