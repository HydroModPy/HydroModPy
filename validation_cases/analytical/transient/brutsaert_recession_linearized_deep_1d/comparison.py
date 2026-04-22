"""Comparison workflow for the deep-aquifer Brutsaert recession case."""

from __future__ import annotations

from pathlib import Path

from validation_cases.analytical.transient.brutsaert_common import (
    BrutsaertRecessionComparison,
    build_brutsaert_recession_comparison,
)
from validation_cases.shared import (
    load_case_metadata,
    load_case_tolerances,
    run_launcher_validation_case,
)

from .runtime_boussinesq import (
    run_boussinesq_brutsaert_recession_linearized_deep_case,
)


CASE_DIR = Path(__file__).resolve().parent


def build_brutsaert_recession_linearized_deep_comparison(
    *,
    result,
    metadata: dict | None = None,
    tolerances: dict | None = None,
) -> BrutsaertRecessionComparison:
    """Load one completed run and compare it to the linearized Brutsaert recession."""
    return build_brutsaert_recession_comparison(
        case_dir=CASE_DIR,
        result=result,
        metadata=metadata,
        tolerances=tolerances,
    )


def run_brutsaert_recession_linearized_deep_comparison(
    *,
    caller_file: str | Path,
    timeout: int = 1800,
    solver: str | None = None,
) -> BrutsaertRecessionComparison:
    """Run one solver variant and return the Brutsaert recession comparison."""
    normalized_solver = None if solver is None else str(solver).strip().lower()
    metadata = load_case_metadata(CASE_DIR)
    effective_solver = (
        normalized_solver or str(metadata.get("default_solver", "")).strip().lower() or None
    )
    tolerances = load_case_tolerances(CASE_DIR, solver=effective_solver)
    if normalized_solver == "boussinesq":
        result = run_boussinesq_brutsaert_recession_linearized_deep_case(
            caller_file=caller_file,
            timeout=timeout,
        )
    else:
        result = run_launcher_validation_case(
            case_dir=CASE_DIR,
            test_file=caller_file,
            timeout=timeout,
            solver=solver,
        )
    return build_brutsaert_recession_linearized_deep_comparison(
        result=result,
        metadata=metadata,
        tolerances=tolerances,
    )


__all__ = [
    "build_brutsaert_recession_linearized_deep_comparison",
    "run_brutsaert_recession_linearized_deep_comparison",
]
