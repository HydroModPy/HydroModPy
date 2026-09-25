"""Build the Selune catchment report from catchment_report_selune.toml."""

# ruff: noqa: E402, I001

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydromodpy.cli.main import main  # noqa: E402


if __name__ == "__main__":
    default_config = Path(__file__).with_name("catchment_report_selune.toml")
    main(["report", "catchment", str(default_config), *sys.argv[1:]])
