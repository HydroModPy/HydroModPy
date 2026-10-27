"""The size field around a river, from build_size_field.

Left: the field in plan, a river inside a catchment, coarser cells outside it.
Right: the size against the distance to the river for three river bands. The
shortest band asks for a slope above max_slope, so the code holds it there.
"""

import matplotlib.pyplot as plt
import numpy as np
from shapely.geometry import LineString, Point

from hydromodpy.spatial.mesh.planning.size_field import (
    OutsideCoarsening,
    SizeTerm,
    build_size_field,
)
from hydromodpy.spatial.mesh.request import RasterGridSpec

PIXEL, H0, RIVER, SLOPE = 5.0, 50.0, 10.0, 0.5


def grid(width, height):
    return RasterGridSpec(
        xmin=0.0,
        xmax=width,
        ymin=0.0,
        ymax=height,
        dx=PIXEL,
        dy=PIXEL,
        nrow=int(height / PIXEL),
        ncol=int(width / PIXEL),
        crs_wkt='LOCAL_CS["metres"]',
    )


fig, (plan, profile) = plt.subplots(
    1, 2, figsize=(6.4, 3.4), gridspec_kw={"width_ratios": [1.15, 1]}
)

# Plan: a river inside a round catchment, the background twice as coarse outside.
plan_grid = grid(1000.0, 800.0)
catchment = Point(500.0, 400.0).buffer(330.0)
river = LineString([(230.0, 560.0), (420.0, 450.0), (560.0, 330.0), (760.0, 240.0)])
field = build_size_field(
    plan_grid,
    h0=H0,
    h_floor=PIXEL,
    terms=[SizeTerm(name="rivers", region=river, size_m=RIVER, ramp_m=100.0)],
    outside=OutsideCoarsening(region=catchment, factor=2.0, transition_m=150.0),
    max_slope=SLOPE,
)
image = plan.imshow(
    field.values, extent=(0.0, 1000.0, 0.0, 800.0), cmap="viridis", vmin=0.0, vmax=2 * H0
)
plan.plot(*river.xy, color="w", lw=2.0)
plan.plot(*catchment.exterior.xy, color="C6", lw=1.0, ls="--")
plan.set_xticks([])
plan.set_yticks([])
for side in plan.spines.values():
    side.set_visible(False)
plan.set_title(r"$\ell(\mathbf{x})$ in plan", fontsize=10)
bar = fig.colorbar(image, ax=plan, fraction=0.046, pad=0.03)
bar.set_label("cell size (m)")

# Profile: the size against the distance to a straight river, for three bands.
strip = grid(40.0, 400.0)
line = LineString([(0.0, 397.5), (40.0, 397.5)])
for band, colour, style in ((200.0, "C1", "-"), (100.0, "C2", "--"), (20.0, "C3", "-.")):
    values = build_size_field(
        strip,
        h0=H0,
        h_floor=PIXEL,
        terms=[SizeTerm(name="rivers", region=line, size_m=RIVER, ramp_m=band)],
        outside=None,
        max_slope=SLOPE,
    ).values[:, 4]
    distance = np.arange(values.size) * PIXEL
    wanted = (H0 - RIVER) / band
    note = f"slope {wanted:.1f}" if wanted <= SLOPE else f"slope {wanted:.0f}, held at {SLOPE}"
    profile.plot(
        distance, values, color=colour, ls=style, lw=1.8, label=f"band {band:.0f} m: {note}"
    )
profile.axhline(H0, color="C6", lw=0.8, ls=":")
profile.axhline(PIXEL, color="C6", lw=0.8, ls=":")
profile.text(250.0, H0 + 1.5, r"$\ell_g$", color="C6")
profile.text(200.0, PIXEL + 1.5, r"DEM pixel $\Delta$", color="C6")
profile.set_xlim(0.0, 300.0)
profile.set_ylim(0.0, H0 + 22.0)
profile.set_xlabel(r"distance to the river $\xi$ (m)")
profile.set_ylabel("cell size (m)")
profile.set_title(r"$\ell_s$ = 10 m, $\ell_g$ = 50 m", fontsize=10)
profile.legend(loc="upper left", fontsize=7.5, frameon=False)
fig.tight_layout()
