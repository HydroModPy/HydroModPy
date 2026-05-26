"""Build the Nancon reference catchment report.

The implementation lives in ``hydromodpy.display.catchment_report`` so the
example remains a thin, stable command-line entry point.
"""

# ruff: noqa: E402, I001

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydromodpy.display.catchment_report.nancon_compat import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
