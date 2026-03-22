"""Iteratively run the visual Gmsh example cases for manual review.

Each selected case is executed via its Python entrypoint with blocking figure
display enabled. The script waits for the user to close the current figure
window(s) before moving to the next case, which makes a visual walkthrough of
the examples straightforward.
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
    """Describe one visual example case available for manual review."""

    name: str
    description: str
    runner: Callable[[], Any]


def _case_path(*parts: str) -> Path:
    return CASES_DIR.joinpath(*parts).resolve()


def _run_reference_2d_geology_base() -> dict[str, Any]:
    from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_base.run_case_gmsh import (
        run_reference_case_from_toml,
    )

    return run_reference_case_from_toml(
        _case_path("reference_2d_geology_base", "case_config_gmsh.toml"),
        show_plot=True,
    )


def _run_comparison_cartesian_vs_gmsh_2d() -> dict[str, Any]:
    from hydromodpy.solver.utils.mesh.gmsh_grid.cases.comparison_cartesian_vs_gmsh_2d.run_compare import (
        run_comparison_case,
    )

    return run_comparison_case(
        cartesian_config_toml=_case_path(
            "comparison_cartesian_vs_gmsh_2d",
            "case_config_cartesian.toml",
        ),
        gmsh_config_toml=_case_path(
            "comparison_cartesian_vs_gmsh_2d",
            "case_config_gmsh.toml",
        ),
        show_plot=True,
    )


def _run_reference_3d_fieldparam() -> dict[str, Any]:
    from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_3d_fieldparam.run_case_3d_fieldparam import (
        run_reference_3d_fieldparam_case_from_toml,
    )

    return run_reference_3d_fieldparam_case_from_toml(
        _case_path("reference_3d_fieldparam", "case_config_3d_fieldparam.toml"),
        show_plot=True,
    )


def _run_reference_3d_visualization() -> dict[str, Any]:
    from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_3d_fieldparam.run_case_3d_fieldparam import (
        run_reference_3d_visualization_from_toml,
    )

    return run_reference_3d_visualization_from_toml(
        _case_path("reference_3d_fieldparam", "case_visualization_3d.toml"),
        show_plot=True,
    )


def _run_comparison_cartesian_vs_gmsh_3d() -> dict[str, Any]:
    from hydromodpy.solver.utils.mesh.gmsh_grid.cases.comparison_cartesian_vs_gmsh_3d.run_compare import (
        run_comparison_case,
    )

    return run_comparison_case(
        cartesian_config_toml=_case_path(
            "comparison_cartesian_vs_gmsh_3d",
            "case_config_cartesian.toml",
        ),
        gmsh_config_toml=_case_path(
            "comparison_cartesian_vs_gmsh_3d",
            "case_config_gmsh.toml",
        ),
        show_plot=True,
    )


CASE_REVIEW_SPECS: tuple[CaseReviewSpec, ...] = (
    CaseReviewSpec(
        name="reference_2d_geology_base",
        description="Baseline 2D geology-driven Gmsh workflow.",
        runner=_run_reference_2d_geology_base,
    ),
    CaseReviewSpec(
        name="comparison_cartesian_vs_gmsh_2d",
        description="2D cartesian vs Gmsh comparison figures.",
        runner=_run_comparison_cartesian_vs_gmsh_2d,
    ),
    CaseReviewSpec(
        name="reference_3d_fieldparam",
        description="Reference 3D FieldParam discretization overview.",
        runner=_run_reference_3d_fieldparam,
    ),
    CaseReviewSpec(
        name="reference_3d_visualization",
        description="Layer maps and vertical profiles from the 3D reference case.",
        runner=_run_reference_3d_visualization,
    ),
    CaseReviewSpec(
        name="comparison_cartesian_vs_gmsh_3d",
        description="3D cartesian vs Gmsh comparison figures.",
        runner=_run_comparison_cartesian_vs_gmsh_3d,
    ),
)


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Run the visual gmsh_grid example cases sequentially, with "
            "blocking figure display for manual review."
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
            "Unknown gmsh_grid review case(s): "
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
