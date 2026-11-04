"""CLI entry point for the Brutsaert-Nieber recession calibration demo."""

from __future__ import annotations

from validation_cases.calibration.recession_brutsaert.experiment import (
    BRUTSAERT_RECESSION_CASE,
    build_calibration,
)
from validation_cases.calibration.shared.standalone import run_and_print, standalone_parser


def main(argv: list[str] | None = None) -> None:
    args = standalone_parser(
        "Run the Brutsaert-Nieber recession calibration demo.", 100, 11
    ).parse_args(argv)
    engine, _ = build_calibration(
        case=BRUTSAERT_RECESSION_CASE,
        optimizer_name=args.optimizer,
        max_trials=args.max_trials,
        seed=args.seed,
    )
    run_and_print(engine, args.optimizer, BRUTSAERT_RECESSION_CASE.truth)


if __name__ == "__main__":
    main()
