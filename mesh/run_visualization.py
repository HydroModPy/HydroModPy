"""Backward-compatible script entry point for the standalone mesh viewer.

The preferred package entry point is now ``python -m mesh``. This file remains
available so a vendored directory can still be launched directly with
``python mesh/run_visualization.py``.

Treat this module as a compatibility wrapper, not as the main place to extend
the viewer.
"""

from __future__ import annotations

from pathlib import Path
import sys

# When this file is executed directly, Python adds ``mesh/`` to ``sys.path``
# but not necessarily the repository root. Insert the parent explicitly so the
# package import below resolves without installation.
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from mesh.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
