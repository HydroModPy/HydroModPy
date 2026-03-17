"""Backward-compatible shim -- all logic now lives in run_case_3d_fieldparam."""
from __future__ import annotations

from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_3d_fieldparam.run_case_3d_fieldparam import (
    build_reference_3d_postprocess_state_from_toml,
    run_reference_3d_postprocess_from_toml,
)

__all__ = [
    "build_reference_3d_postprocess_state_from_toml",
    "run_reference_3d_postprocess_from_toml",
]

if __name__ == "__main__":
    from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_3d_fieldparam.run_case_3d_fieldparam import main

    raise SystemExit(main(["postprocess"]))
