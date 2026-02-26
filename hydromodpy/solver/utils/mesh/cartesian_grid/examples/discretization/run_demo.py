"""Backward-compatible wrapper for the 2D discretization demo CLI."""

from __future__ import annotations

from pathlib import Path
import sys


def _find_repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "hydromodpy").is_dir():
            return parent
    return current.parents[0]


REPO_ROOT = _find_repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydromodpy.solver.utils.mesh.cartesian_grid.examples.discretization.run_demo_2d import (  # noqa: E402
    main,
)


if __name__ == "__main__":
    raise SystemExit(main())

