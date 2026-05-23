"""Compatibility wrapper for regional basin-selection map/HTML reports."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydromodpy.spatial.site_selection.reporting import main  # noqa: E402,I001


if __name__ == "__main__":
    raise SystemExit(main())
