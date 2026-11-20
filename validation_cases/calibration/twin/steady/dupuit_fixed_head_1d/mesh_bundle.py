"""Build the refined triangle bundle that holds the truth of the mesh-perturbed twin.

The bundle shares the strip of ``sloping_substratum_irregular_tri_400x50`` (400 m
by 50 m, top 25 m to 20 m, bottom 5 m to 0 m) with about four times its cells,
so the truth run and the calibration runs differ only by the mesh. Rebuild it
with ``python -m validation_cases.calibration.twin.steady.dupuit_fixed_head_1d.mesh_bundle``.
"""

from __future__ import annotations

from pathlib import Path

from validation_cases.shared.gmsh_irregular_strip import write_irregular_strip_bundle

BUNDLE_DIR = (
    Path(__file__).resolve().parent
    / "mesh_bundles"
    / "sloping_substratum_irregular_tri_refined_400x50"
)
SEED = 20261013
SEED_COLUMNS = 20
SEED_ROWS = 6
"""Twice the 10 by 3 seeds of the coarse bundle: cells half as long, 750 against 176."""
LENGTH_X_M = 400.0
WIDTH_Y_M = 50.0
Z_DROP_M = 5.0


def build_bundle(bundle_dir: Path = BUNDLE_DIR) -> Path:
    """Write the refined strip, with the elevation profile of the coarse bundle."""
    return write_irregular_strip_bundle(
        bundle_dir,
        nx_seed=SEED_COLUMNS,
        ny_seed=SEED_ROWS,
        length_x_m=LENGTH_X_M,
        width_y_m=WIDTH_Y_M,
        z_top_m=lambda x_m: 25.0 - Z_DROP_M * x_m / LENGTH_X_M,
        z_bottom_m=lambda x_m: 5.0 - Z_DROP_M * x_m / LENGTH_X_M,
        hydraulic_conductivity_m_s=1.0e-4,
        storage_coefficient=0.1,
        seed=SEED,
    )


if __name__ == "__main__":
    print(build_bundle())
