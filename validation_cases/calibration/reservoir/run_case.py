"""CLI entry point for the lumped-reservoir calibration demo."""

from __future__ import annotations

import argparse

from validation_cases.calibration.reservoir.experiment import (
    ONE_RESERVOIR_CASE,
    TWO_RESERVOIR_CASE,
    build_calibration,
)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run the lumped-reservoir calibration demo.",
    )
    parser.add_argument(
        "--variant",
        default="one",
        choices=("one", "two"),
        help="Single reservoir (default) or two reservoirs in series.",
    )
    parser.add_argument(
        "--optimizer",
        default="scipy_nelder_mead",
        choices=("scipy_nelder_mead", "scipy_de", "grid"),
    )
    parser.add_argument("--max-iter", type=int, default=120)
    parser.add_argument("--seed", type=int, default=13)
    args = parser.parse_args(argv)

    case = ONE_RESERVOIR_CASE if args.variant == "one" else TWO_RESERVOIR_CASE
    engine, _ = build_calibration(
        case=case,
        optimizer_name=args.optimizer,
        max_iter=args.max_iter,
        seed=args.seed,
    )
    session = engine.run()
    completed = [r for r in session.history if r.status == "completed"]
    best = min(completed, key=lambda r: r.objective_value)
    print(f"variant          : {args.variant}")
    print(f"optimizer        : {args.optimizer}")
    print(f"iterations       : {len(completed)}")
    print(f"best objective   : {best.objective_value:.6e}")
    print(f"best values      : {best.metadata.get('values')}")
    print(f"truth values     : {dict(case.truth)}")
    print(f"duration_s       : {session.duration_s:.2f}")


if __name__ == "__main__":
    main()
