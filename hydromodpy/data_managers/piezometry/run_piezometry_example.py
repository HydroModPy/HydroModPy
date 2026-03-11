"""Backward-compatible entrypoint for the piezometry case runner."""

from __future__ import annotations

from pathlib import Path
import sys

repo_root = Path(__file__).resolve().parents[3]
if (repo_root / "hydromodpy").exists() and str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from hydromodpy.data_managers.piezometry.cases.run_piezometry_case import (
    main as _case_main,
    main_piezometer as _case_main_piezometer,
    main_piezometer_set as _case_main_piezometer_set,
)


def main_piezometer_set() -> None:
    """Run legacy piezometer-set workflow via cases runner."""
    _case_main_piezometer_set()


def main_piezometer() -> None:
    """Run legacy single-piezometer workflow via cases runner."""
    _case_main_piezometer()


def main(argv: list[str] | None = None) -> int:
    """Run CLI-compatible case workflow."""
    return _case_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())

