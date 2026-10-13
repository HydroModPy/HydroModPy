"""Build the irregular triangle bundle of the unstructured MODFLOW 6 variants.

The bundle is stored next to this case, under ``mesh_bundles``. Rebuild it with
``python -m validation_cases.analytical.steady.dupuit_seepage_limit_1d.mesh_bundle``.
"""

from __future__ import annotations

from pathlib import Path

from validation_cases.shared.gmsh_irregular_strip import write_irregular_strip_bundle

BUNDLE_NAME = "dupuit_seepage_limit_irregular_tri_400x25"
BUNDLE_DIR = Path(__file__).resolve().parent / "mesh_bundles" / BUNDLE_NAME
SEED = 20261013
LENGTH_X_M = 400.0
WIDTH_Y_M = 25.0
SLOPE = 0.02


def build_bundle(bundle_dir: Path = BUNDLE_DIR) -> Path:
    """Write the 400 m by 25 m strip of triangles about 6 m across.

    The surface is the plane of the case, ``slope * (L - x)``: the toe is the
    east face, where it meets the flat substratum at 0 m. The writer wants the
    top strictly above the bottom, so the profile sits 1 micrometre higher. A
    run does not read it: it samples its cell tops from the raster of its config.
    """
    return write_irregular_strip_bundle(
        bundle_dir,
        nx_seed=40,
        ny_seed=3,
        length_x_m=LENGTH_X_M,
        width_y_m=WIDTH_Y_M,
        z_top_m=lambda x_m: SLOPE * (LENGTH_X_M - x_m) + 1e-6,
        z_bottom_m=0.0,
        hydraulic_conductivity_m_s=2.5e-4,
        storage_coefficient=0.1,
        seed=SEED,
    )


if __name__ == "__main__":
    print(build_bundle())
