"""Build the irregular triangle bundle of the boundary-periodic case.

The bundle is stored under ``validation_cases/shared/mesh_bundles``. Rebuild it
with ``python -m validation_cases.analytical.transient.linearized_unconfined_boundary_periodic_1d.mesh_bundle``.
"""

from __future__ import annotations

from pathlib import Path

from validation_cases.shared.gmsh_irregular_strip import write_irregular_strip_bundle

BUNDLE_DIR = (
    Path(__file__).resolve().parents[3]
    / "shared"
    / "mesh_bundles"
    / "linearized_unconfined_tide_irregular_tri_100x10"
)
SEED = 20261010


def build_bundle(bundle_dir: Path = BUNDLE_DIR) -> Path:
    """Write the 100 m x 10 m strip of triangles about 2 m across.

    The damping length of the tide is 11.7 m, so a side of 2 m keeps about six
    cells per damping length, as the 2 m columns of the structured grid do.
    """
    return write_irregular_strip_bundle(
        bundle_dir,
        nx_seed=50,
        ny_seed=5,
        length_x_m=100.0,
        width_y_m=10.0,
        z_top_m=20.0,
        z_bottom_m=0.0,
        hydraulic_conductivity_m_s=1.0e-4,
        storage_coefficient=0.2,
        seed=SEED,
        base_mesh_size_m=2.0,
    )


if __name__ == "__main__":
    print(build_bundle())
