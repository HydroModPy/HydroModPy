"""CLI entry point for the lumped-reservoir calibration demo."""

from __future__ import annotations

from validation_cases.calibration.reservoir.experiment import (
    ONE_RESERVOIR_CASE,
    TWO_RESERVOIR_CASE,
    build_calibration,
)
from validation_cases.calibration.shared.standalone import run_and_print, standalone_parser


def main(argv: list[str] | None = None) -> None:
    parser = standalone_parser("Run the lumped-reservoir calibration demo.", 120, 13)
    parser.add_argument(
        "--variant",
        default="one",
        choices=("one", "two"),
        help="Single reservoir (default) or two reservoirs in series.",
    )
    args = parser.parse_args(argv)

    case = ONE_RESERVOIR_CASE if args.variant == "one" else TWO_RESERVOIR_CASE
    engine, _ = build_calibration(
        case=case,
        optimizer_name=args.optimizer,
        max_trials=args.max_trials,
        seed=args.seed,
    )
    print(f"variant          : {args.variant}")
    run_and_print(engine, args.optimizer, case.truth)


if __name__ == "__main__":
    main()
