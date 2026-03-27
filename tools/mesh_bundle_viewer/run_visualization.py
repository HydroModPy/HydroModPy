"""Backward-compatible script entry point for the standalone mesh bundle viewer.

Inside this repository, the preferred package entry point is now
``python -m tools.mesh_bundle_viewer``. When the directory is copied as a
standalone package, this file still allows launching it directly with
``python mesh_bundle_viewer/run_visualization.py``.

Treat this module as a compatibility wrapper, not as the main place to extend
the viewer.
"""

from __future__ import annotations

from pathlib import Path
import sys

# When this file is executed directly, Python adds ``mesh_bundle_viewer/`` to
# ``sys.path`` but not necessarily the parent folder. Insert the parent so the
# package import below resolves without installation.
_package_root = Path(__file__).resolve().parent.parent
if str(_package_root) not in sys.path:
    sys.path.insert(0, str(_package_root))

from mesh_bundle_viewer.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
