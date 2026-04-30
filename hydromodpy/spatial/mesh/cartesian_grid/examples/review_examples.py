"""Iteratively run the visual cartesian-grid demos for manual review.

Run with:
    python -m hydromodpy.spatial.mesh.cartesian_grid.examples.review_examples
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ExampleReviewSpec:
    """Describe one visual cartesian-grid example available for review."""

    name: str
    description: str
    runner: Callable[[], Any]


def _run_generation_demo() -> int:
    from hydromodpy.spatial.mesh.cartesian_grid.examples.generation.run_grid_demo import (
        main,
    )

    return int(main([]))


def _run_discretization_2d_demo() -> int:
    from hydromodpy.spatial.mesh.cartesian_grid.examples.discretization.run_demo_2d import (
        main,
    )

    return int(main([]))


def _run_discretization_3d_demo() -> int:
    from hydromodpy.spatial.mesh.cartesian_grid.examples.discretization.run_demo_3d import (
        main,
    )

    return int(main([]))


EXAMPLE_REVIEW_SPECS: tuple[ExampleReviewSpec, ...] = (
    ExampleReviewSpec(
        name="generation",
        description="Structured-grid generation scenarios from explicit surfaces.",
        runner=_run_generation_demo,
    ),
    ExampleReviewSpec(
        name="discretization_2d",
        description="2D FieldParam discretization demo on SGrid.",
        runner=_run_discretization_2d_demo,
    ),
    ExampleReviewSpec(
        name="discretization_3d",
        description="3D FieldParam extrusion and visualization demo on SGrid.",
        runner=_run_discretization_3d_demo,
    ),
)


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Run the visual cartesian_grid demos sequentially, with blocking "
            "figure display for manual review."
        )
    )
    parser.add_argument(
        "--example",
        dest="example_names",
        action="append",
        default=None,
        help=(
            "Restrict the review to one named example. Repeat the option to "
            "keep multiple examples; execution order stays the built-in order."
        ),
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List the available review examples and exit.",
    )
    return parser.parse_args(argv)


def available_example_review_names() -> tuple[str, ...]:
    return tuple(spec.name for spec in EXAMPLE_REVIEW_SPECS)


def resolve_example_review_specs(
    example_names: Sequence[str] | None = None,
) -> tuple[ExampleReviewSpec, ...]:
    if not example_names:
        return EXAMPLE_REVIEW_SPECS

    requested = {str(name).strip() for name in example_names if str(name).strip()}
    available = available_example_review_names()
    unknown = sorted(requested.difference(available))
    if unknown:
        raise ValueError(
            "Unknown cartesian_grid review example(s): "
            + ", ".join(repr(name) for name in unknown)
            + ". Available examples: "
            + ", ".join(available)
        )
    return tuple(spec for spec in EXAMPLE_REVIEW_SPECS if spec.name in requested)


def list_example_reviews(*, printer: Callable[[str], None] = print) -> None:
    for spec in EXAMPLE_REVIEW_SPECS:
        printer(f"{spec.name}: {spec.description}")


def run_example_reviews(
    example_names: Sequence[str] | None = None,
    *,
    printer: Callable[[str], None] = print,
) -> tuple[ExampleReviewSpec, ...]:
    selected_specs = resolve_example_review_specs(example_names)
    total = len(selected_specs)
    for index, spec in enumerate(selected_specs, start=1):
        printer(f"[{index}/{total}] Running {spec.name}")
        printer(f"  {spec.description}")
        printer("  Close the figure window(s) to continue to the next example.")
        spec.runner()
        printer(f"[{index}/{total}] Completed {spec.name}")
    return selected_specs


def main(argv=None) -> int:
    args = _parse_args(argv)
    if args.list:
        list_example_reviews()
        return 0
    run_example_reviews(args.example_names)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
