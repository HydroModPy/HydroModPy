"""The four depth models on one valley profile, drawn by build_domain."""

import matplotlib.pyplot as plt
import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.spatial import RasterSupport, Surface
from hydromodpy.spatial.domain import DomainConfig
from hydromodpy.spatial.domain.build import build_domain

# One row of 25 m cells across a valley. The raster kinds read a raster on the
# same grid, so the reprojection is the identity.
NCOL, DX = 81, 25.0
x = np.arange(NCOL) * DX
support = RasterSupport(
    crs="EPSG:2154",
    dx=DX,
    dy=DX,
    xmin=350_000.0,
    xmax=350_000.0 + NCOL * DX,
    ymin=6_790_000.0,
    ymax=6_790_000.0 + DX,
    nrows=1,
    ncols=NCOL,
    nodata=-9999.0,
)
z_top = 100.0 + 0.03 * np.abs(x - 1000.0) + 4.0 * np.sin(x / 180.0)
top = Surface(name="surface_topo", values=z_top[None, :], support=support)
H_MIN = 8.0
bump = np.exp(-(((x - 1000.0) / 280.0) ** 2))
elevation_raster = 70.0 + 36.0 * bump
thickness_raster = 32.0 - 31.0 * bump
cases = [
    ("constant_thickness", {"thickness": 30.0}, None, None),
    ("flat_substratum", {"substratum_elevation": 60.0}, None, None),
    ("raster_substratum", {"min_thickness": H_MIN}, elevation_raster, elevation_raster),
    ("raster_thickness", {"min_thickness": H_MIN}, thickness_raster, z_top - thickness_raster),
]

# The cap logs a warning that counts the cells; the figure shows them instead.
domain_logger = get_logger("hydromodpy.spatial.domain.domain")
level = domain_logger.level
domain_logger.setLevel("ERROR")
fig, axes = plt.subplots(2, 2, figsize=(6.4, 5.0), sharex=True, sharey=True)
try:
    for ax, (kind, keys, raster, raw_bottom) in zip(axes.flat, cases, strict=True):
        source = None
        if raster is not None:
            source = Surface(name="raw", values=raster[None, :], support=support)
        domain = build_domain(
            DomainConfig.model_validate({"depth_model": {"kind": kind, **keys}}),
            surface_topo=top,
            substratum_source=source,
        )
        z_bot = domain.substratum.as_array()[0]
        ax.fill_between(x, z_bot, z_top, color="C5", alpha=0.35, lw=0)
        ax.plot(x, z_top, color="C6", lw=1.2)
        ax.plot(x, z_bot, color="C1", lw=1.8)
        if raw_bottom is not None:
            capped = raw_bottom > z_top - H_MIN
            ax.plot(x, raw_bottom, color="C6", lw=1.2, ls=":")
            ax.plot(x[capped], z_bot[capped], "o", color="C1", ms=3.5)
        ax.set_title(kind, fontsize=10, family="monospace")
finally:
    domain_logger.setLevel(level)

handles = [
    plt.Line2D([], [], color="C6", lw=1.2),
    plt.Line2D([], [], color="C1", lw=1.8),
    plt.Line2D([], [], color="C6", lw=1.2, ls=":"),
    plt.Line2D([], [], color="C1", ls="", marker="o", ms=3.5),
]
labels = [
    r"top $z_\mathrm{top}$",
    r"bottom $z_\mathrm{bot}$",
    "raster bottom before the cap",
    r"cell lowered to $z_\mathrm{top} - H_\mathrm{min}$",
]
for ax in axes[1]:
    ax.set_xlabel("distance (m)")
for ax in axes[:, 0]:
    ax.set_ylabel("elevation (m)")
axes[0, 0].set_ylim(50, 140)
fig.tight_layout(rect=(0, 0.1, 1, 1))
fig.legend(handles, labels, loc="lower center", ncol=2, fontsize=9, frameon=False)
