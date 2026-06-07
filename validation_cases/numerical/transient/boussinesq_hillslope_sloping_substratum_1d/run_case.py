"""Run the transient sloping-substratum Boussinesq example."""

from __future__ import annotations

import argparse
from pathlib import Path

from validation_cases.shared.cli import apply_output_root_override

from .runtime_boussinesq import run_boussinesq_hillslope_sloping_substratum_case


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the transient Boussinesq hillslope example with sloping substratum."
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("out") / "boussinesq_hillslope_sloping_substratum_1d",
        help="Output root used for the run artifacts.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=2400,
        help="Timeout passed to the runtime helper.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    apply_output_root_override(Path(args.output_root))
    run_boussinesq_hillslope_sloping_substratum_case(timeout=int(args.timeout))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
