"""Build the irregular triangle bundle of the MODFLOW 6 unstructured variants.

The bundle is stored next to this case, under ``mesh_bundles``. The transient
interception case reads it too. Rebuild it with
``python -m validation_cases.analytical.steady.boussinesq_hillslope_interception_1d.mesh_bundle``.
"""

from __future__ import annotations

from pathlib import Path

from validation_cases.shared.gmsh_irregular_strip import write_irregular_strip_bundle

BUNDLE_NAME = "boussinesq_hillslope_interception_irregular_tri_400x30"
BUNDLE_DIR = Path(__file__).resolve().parent / "mesh_bundles" / BUNDLE_NAME
SEED = 20261013
LENGTH_X_M = 400.0
WIDTH_Y_M = 30.0
TOE_ELEVATION_M = 5.0
TOPOGRAPHY_SLOPE_M_PER_M = 0.0125


def build_bundle(bundle_dir: Path = BUNDLE_DIR) -> Path:
    """Write the 400 m by 30 m strip of triangles about 10 m across.

    The surface is the plane of the case, 10 m at the divide and 5 m at the toe.
    """
    return write_irregular_strip_bundle(
        bundle_dir,
        nx_seed=40,
        ny_seed=3,
        length_x_m=LENGTH_X_M,
        width_y_m=WIDTH_Y_M,
        z_top_m=lambda x_m: TOE_ELEVATION_M + TOPOGRAPHY_SLOPE_M_PER_M * (LENGTH_X_M - x_m),
        z_bottom_m=0.0,
        hydraulic_conductivity_m_s=1.0e-4,
        storage_coefficient=0.1,
        seed=SEED,
    )


if __name__ == "__main__":
    print(build_bundle())
