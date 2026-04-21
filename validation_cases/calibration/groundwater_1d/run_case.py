"""CLI entry point for the 1D transient groundwater calibration demo."""

from __future__ import annotations

import argparse

from validation_cases.calibration.groundwater_1d.experiment import (
    GROUNDWATER_1D_CASE,
    build_calibration,
)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run the transient 1D groundwater calibration demo.",
    )
    parser.add_argument(
        "--optimizer",
        default="scipy_nelder_mead",
        choices=("scipy_nelder_mead", "scipy_de", "grid"),
    )
    parser.add_argument("--max-iter", type=int, default=60)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)

    engine, _ = build_calibration(
        case=GROUNDWATER_1D_CASE,
        optimizer_name=args.optimizer,
        max_iter=args.max_iter,
        seed=args.seed,
    )
    session = engine.run()
    completed = [r for r in session.history if r.status == "completed"]
    best = min(completed, key=lambda r: r.objective_value)
    truth = GROUNDWATER_1D_CASE.truth
    print(f"optimizer        : {args.optimizer}")
    print(f"iterations       : {len(completed)}")
    print(f"best objective   : {best.objective_value:.6e}")
    print(f"best values      : {best.metadata.get('values')}")
    print(f"truth values     : {dict(truth)}")
    print(f"duration_s       : {session.duration_s:.2f}")


if __name__ == "__main__":
    main()
