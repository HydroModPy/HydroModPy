"""Registry of calibration twin benchmarks exposed in the capability gallery."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any

CALIBRATION_BENCHMARK_FAMILIES: dict[str, dict[str, Any]] = {
    "data_rich_no_uncertainty": {
        "key": "data_rich_no_uncertainty",
        "title": "No-Uncertainty, Data-Rich Benchmarks",
        "deck": (
            "Benchmarks with multiple observables, no observation noise, and enough "
            "data to constrain the inverse problem more strongly."
        ),
        "page_slug": "calibration_data_rich_no_uncertainty",
        "page_title": "Calibration Benchmarks: No Uncertainty, More Data",
        "page_intro": (
            "These calibration benchmarks keep observation noise off and rely on richer "
            "data sets, typically multiple observable blocks, so the objective surface is "
            "better constrained."
        ),
        "order": 10,
        "primary": True,
    },
    "uncertain_less_data": {
        "key": "uncertain_less_data",
        "title": "Uncertain, Sparse-Data Benchmarks",
        "deck": (
            "Benchmarks with noisier or sparser observations, meant to expose weak "
            "identifiability and more ambiguous objective landscapes."
        ),
        "page_slug": "calibration_uncertain_less_data",
        "page_title": "Calibration Benchmarks: Uncertainty And Less Data",
        "page_intro": (
            "These calibration benchmarks deliberately reduce information content by "
            "using fewer observations and adding uncertainty, so the methods are tested "
            "on weaker inverse constraints."
        ),
        "order": 20,
        "primary": True,
    },
    "supplementary_scalar_reference": {
        "key": "supplementary_scalar_reference",
        "title": "Supplementary Scalar Reference Cases",
        "deck": (
            "Compact scalar reference problems kept in the gallery for quick reading of "
            "single-parameter and posterior-oriented calibration behaviour."
        ),
        "page_slug": None,
        "page_title": None,
        "page_intro": None,
        "order": 30,
        "primary": False,
    },
}


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
                f"{name}={float(value):g}" for name, value in noise.absolute_sigma_by_output.items()
            )
        )
    if getattr(noise, "relative_sigma_by_output", {}):
        parts.append(
            "relative "
            + ", ".join(
                f"{name}={float(value):g}" for name, value in noise.relative_sigma_by_output.items()
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


def _load_case_definition(import_path: str) -> Any:
    module_name, attribute_name = import_path.split(":", maxsplit=1)
    module = importlib.import_module(module_name)
    return getattr(module, attribute_name)


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
    benchmark_family_key: str,
    gallery_method_names: tuple[str, ...] | None = None,
) -> CalibrationCaseRecord:
    benchmark_family = CALIBRATION_BENCHMARK_FAMILIES[str(benchmark_family_key)]
    source_paths = _dedupe(
        [
            "validation_cases/calibration/README.md",
            "validation_cases/calibration/run_benchmarks.py",
            "validation_cases/calibration/plotting.py",
            "validation_cases/calibration/shared/definitions.py",
            "validation_cases/calibration/shared/runtime.py",
            run_case_file,
            run_case_file.replace("run_case.py", "experiment.py"),
            "hydromodpy/calibration/benchmark.py",
            "hydromodpy/calibration/engine.py",
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
            f"Benchmark family: {benchmark_family['title']}.",
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
                str(name): float(value) for name, value in definition.truth_params.items()
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
            "benchmark_family_key": str(benchmark_family["key"]),
            "benchmark_family_title": str(benchmark_family["title"]),
            "benchmark_family_deck": str(benchmark_family["deck"]),
            "benchmark_family_page_slug": benchmark_family["page_slug"],
            "benchmark_family_page_title": benchmark_family["page_title"],
            "benchmark_family_page_intro": benchmark_family["page_intro"],
            "benchmark_family_order": int(benchmark_family["order"]),
            "benchmark_family_primary": bool(benchmark_family["primary"]),
        },
    )


def build_calibration_case_records() -> tuple[CalibrationCaseRecord, ...]:
    """Return the curated calibration cases published in the capability gallery."""
    steady_dupuit_twin_case = _load_case_definition(
        "validation_cases.calibration.twin.steady.dupuit_fixed_head_1d.experiment:STEADY_DUPUIT_TWIN_CASE"
    )
    steady_dupuit_posterior_twin_case = _load_case_definition(
        "validation_cases.calibration.twin.steady.dupuit_fixed_head_1d.experiment:STEADY_DUPUIT_POSTERIOR_TWIN_CASE"
    )
    transient_recharge_step_twin_case = _load_case_definition(
        "validation_cases.calibration.twin.transient.linearized_unconfined_recharge_step_1d.experiment:TRANSIENT_RECHARGE_STEP_TWIN_CASE"
    )
    transient_recharge_step_flux_only_noisy_twin_case = _load_case_definition(
        "validation_cases.calibration.twin.transient.linearized_unconfined_recharge_step_1d.experiment:TRANSIENT_RECHARGE_STEP_FLUX_ONLY_NOISY_TWIN_CASE"
    )
    piecewise_k_twin_case = _load_case_definition(
        "validation_cases.calibration.twin.steady.boussinesq_fixed_head_piecewise_k_1d.experiment:PIECEWISE_K_TWIN_CASE"
    )
    return (
        _record(
            definition=steady_dupuit_twin_case,
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
            benchmark_family_key="supplementary_scalar_reference",
        ),
        _record(
            definition=steady_dupuit_posterior_twin_case,
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
            benchmark_family_key="supplementary_scalar_reference",
        ),
        _record(
            definition=transient_recharge_step_twin_case,
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
            benchmark_family_key="data_rich_no_uncertainty",
        ),
        _record(
            definition=transient_recharge_step_flux_only_noisy_twin_case,
            definition_import_path=(
                "validation_cases.calibration.twin.transient."
                "linearized_unconfined_recharge_step_1d.experiment:"
                "TRANSIENT_RECHARGE_STEP_FLUX_ONLY_NOISY_TWIN_CASE"
            ),
            title="Calibration Twin: Recharge-Step Flux-Only K+Sy 1D",
            run_case_module="validation_cases.calibration.twin.transient.linearized_unconfined_recharge_step_1d.run_case",
            run_case_file="validation_cases/calibration/twin/transient/linearized_unconfined_recharge_step_1d/run_case.py",
            reproduction_command=(
                "python -m validation_cases.calibration.twin.transient."
                "linearized_unconfined_recharge_step_1d.run_case --case flux_only_noisy"
            ),
            display_method_name="da_mh_gp",
            evaluation_budget=None,
            benchmark_family_key="uncertain_less_data",
        ),
        _record(
            definition=piecewise_k_twin_case,
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
            benchmark_family_key="data_rich_no_uncertainty",
        ),
    )


__all__ = [
    "CALIBRATION_BENCHMARK_FAMILIES",
    "CalibrationCaseRecord",
    "build_calibration_case_records",
]
