"""Linux-targeted high-K surface-interaction benchmark used by the gallery."""

from __future__ import annotations

import argparse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

import tools.investigate_surface_interaction_hillslope_transient as base

OUTPUT_ROOT_DEFAULT = REPO_ROOT / "out" / "sih_tx_highk_linux_mf6_petsc_comp_20260416"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the Linux PETSc high-conductivity surface-interaction benchmark "
            "used by the capability gallery."
        )
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=OUTPUT_ROOT_DEFAULT,
        help="Directory where the benchmark outputs are written.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=2400,
        help="Per-solver timeout in seconds.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return base.main(
        [
            "--output-root",
            str(Path(args.output_root).expanduser().resolve()),
            "--solvers",
            "modflow6",
            "petsc",
            "--hydraulic-conductivity-scale",
            "1.6",
            "--timeout",
            str(int(args.timeout)),
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
