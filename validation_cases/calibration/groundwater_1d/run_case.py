"""CLI entry point for the 1D transient groundwater calibration demo."""

from __future__ import annotations

from validation_cases.calibration.groundwater_1d.experiment import (
    GROUNDWATER_1D_CASE,
    build_calibration,
)
from validation_cases.calibration.shared.standalone import run_and_print, standalone_parser


def main(argv: list[str] | None = None) -> None:
    args = standalone_parser(
        "Run the transient 1D groundwater calibration demo.", 60, 7
    ).parse_args(argv)
    engine, _ = build_calibration(
        case=GROUNDWATER_1D_CASE,
        optimizer_name=args.optimizer,
        max_trials=args.max_trials,
        seed=args.seed,
    )
    run_and_print(engine, args.optimizer, GROUNDWATER_1D_CASE.truth)


if __name__ == "__main__":
    main()
