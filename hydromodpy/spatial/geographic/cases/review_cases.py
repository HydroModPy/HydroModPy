"""Sequential visual review launcher for geographic case examples.

This launcher executes each selected case runner one after another. It keeps
figure display blocking and waits for the current window(s) to be closed before
moving to the next case.

Run with:
    python -m hydromodpy.spatial.geographic.cases.review_cases
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CASES_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class CaseReviewSpec:
    """Describe one visual geographic case available for manual review."""

    name: str
    description: str
    runner: Callable[[], Any]


def _case_path(*parts: str) -> Path:
    return CASES_DIR.joinpath(*parts).resolve()


def _run_reference_catchment_delineation_case() -> dict[str, dict[str, Any]]:
    from hydromodpy.spatial.geographic.cases.reference_catchment_delineation_case.run_case import (
        run_geographic_cases_from_toml,
    )

    return run_geographic_cases_from_toml(
        _case_path("reference_catchment_delineation_case", "case_config.toml"),
        show_plot=True,
        outputs_root=_case_path("reference_catchment_delineation_case", "outputs"),
    )


def _run_reference_river_network_nancon() -> dict[str, object]:
    from hydromodpy.spatial.geographic.cases.reference_river_network_nancon.run_case_river_network_nancon import (
        run_reference_river_network_nancon_from_toml,
    )

    return run_reference_river_network_nancon_from_toml(
        _case_path(
            "reference_river_network_nancon",
            "case_config_river_network_nancon.toml",
        ),
        output_dir=_case_path("reference_river_network_nancon", "outputs"),
        show_plot=True,
    )


CASE_REVIEW_SPECS: tuple[CaseReviewSpec, ...] = (
    CaseReviewSpec(
        name="reference_catchment_delineation_case",
        description=(
            "Catchment delineation overview (base, Canut, Nancon, Aber) with DEM and watershed figures."
        ),
        runner=_run_reference_catchment_delineation_case,
    ),
    CaseReviewSpec(
        name="reference_river_network_nancon",
        description=(
            "Nancon hydrographic network case with topography + watershed + extracted network overlay."
        ),
        runner=_run_reference_river_network_nancon,
    ),
)


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Run geographic visual example cases sequentially, with blocking "
            "figure display for manual review."
        )
    )
    parser.add_argument(
        "--case",
        dest="case_names",
        action="append",
        default=None,
        help=(
            "Restrict the review to one named case. Repeat the option to keep "
            "multiple cases; execution order stays the built-in review order."
        ),
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List the available review cases and exit.",
    )
    return parser.parse_args(argv)


def available_case_review_names() -> tuple[str, ...]:
    return tuple(spec.name for spec in CASE_REVIEW_SPECS)


def resolve_case_review_specs(
    case_names: Sequence[str] | None = None,
) -> tuple[CaseReviewSpec, ...]:
    if not case_names:
        return CASE_REVIEW_SPECS

    requested = {str(name).strip() for name in case_names if str(name).strip()}
    available = available_case_review_names()
    unknown = sorted(requested.difference(available))
    if unknown:
        raise ValueError(
            "Unknown geographic review case(s): "
            + ", ".join(repr(name) for name in unknown)
            + ". Available cases: "
            + ", ".join(available)
        )
    return tuple(spec for spec in CASE_REVIEW_SPECS if spec.name in requested)


def list_case_reviews(*, printer: Callable[[str], None] = print) -> None:
    for spec in CASE_REVIEW_SPECS:
        printer(f"{spec.name}: {spec.description}")


def run_case_reviews(
    case_names: Sequence[str] | None = None,
    *,
    printer: Callable[[str], None] = print,
) -> tuple[CaseReviewSpec, ...]:
    selected_specs = resolve_case_review_specs(case_names)
    total = len(selected_specs)
    for index, spec in enumerate(selected_specs, start=1):
        printer(f"[{index}/{total}] Running {spec.name}")
        printer(f"  {spec.description}")
        printer("  Close the figure window(s) to continue to the next case.")
        spec.runner()
        printer(f"[{index}/{total}] Completed {spec.name}")
    return selected_specs


def main(argv=None) -> int:
    args = _parse_args(argv)
    if args.list:
        list_case_reviews()
        return 0
    run_case_reviews(args.case_names)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
