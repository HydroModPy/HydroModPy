"""The top of a channel cell: centroid sample against zonal_top."""

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.path import Path

from hydromodpy.spatial.mesh.ops.zonal_stats import zonal_top

# A DEM of 5 m pixels: a V-shaped valley with a channel incised 2 m along it.
PIXEL, N = 5.0, 24
centres = (np.arange(N) + 0.5) * PIXEL
X, Y = np.meshgrid(centres, centres)
across = (X - 0.35 * Y) - 50.0  # distance to the thalweg, along x
dem = 50.0 + 0.12 * np.abs(across) + 0.02 * Y
channel = np.abs(across) < 4.0
dem[channel] -= 2.0

# One hexagonal cell whose centre sits on the bank, 18 m from the thalweg.
centre = np.array([50.0 + 0.35 * 60.0 + 18.0, 60.0])
angles = np.deg2rad(np.arange(0, 360, 60) + 30)
hexagon = centre + 32.0 * np.column_stack((np.cos(angles), np.sin(angles)))
inside = Path(hexagon).contains_points(np.column_stack((X.ravel(), Y.ravel()))).reshape(N, N)
labels = np.where(inside, 0, -1)

# Bilinear sample at the cell centre: the centroid rule.
fx, fy = centre / PIXEL - 0.5
i, j = int(fy), int(fx)
wy, wx = fy - i, fx - j
centroid = (
    dem[i, j] * (1 - wx) * (1 - wy)
    + dem[i, j + 1] * wx * (1 - wy)
    + dem[i + 1, j] * (1 - wx) * wy
    + dem[i + 1, j + 1] * wx * wy
)
common = {
    "labels": labels,
    "dem": dem,
    "transform": None,
    "out_shape": dem.shape,
    "centroid_top": np.array([centroid]),
    "hillslope_stat": "median",
    "channel_stat": "min",
    "spike_guard_tol_m": 0.0,
}
with_channel = zonal_top(channel_mask=channel, **common).top[0]
without_channel = zonal_top(channel_mask=None, **common).top[0]

fig, (plan, values) = plt.subplots(1, 2, figsize=(6.4, 3.4), gridspec_kw={"width_ratios": [1.2, 1]})
image = plan.imshow(
    dem, origin="lower", extent=(0, N * PIXEL, 0, N * PIXEL), cmap="Greys_r", vmin=47, vmax=58
)
plan.contourf(X, Y, channel.astype(float), levels=[0.5, 1.5], colors=["C0"], alpha=0.55)
plan.fill(*hexagon.T, fc="none", ec="C1", lw=2.0)
plan.plot(*centre, "o", color="C1", ms=6)
plan.plot(X[inside], Y[inside], ".", color="C1", ms=2)
plan.set_title("The cell, its pixels, the channel", fontsize=10)
plan.set_xticks([])
plan.set_yticks([])
for side in plan.spines.values():
    side.set_visible(False)

in_cell = dem[inside]
is_channel = channel[inside]
jitter = np.random.default_rng(0).uniform(-0.25, 0.25, in_cell.size)
values.plot(
    jitter[~is_channel], in_cell[~is_channel], ".", color="C6", ms=3, label="hillslope pixel"
)
values.plot(jitter[is_channel], in_cell[is_channel], ".", color="C0", ms=5, label="channel pixel")
for level, text, colour, style in [
    (centroid, "centroid sample", "C1", "-"),
    (without_channel, "zonal median, no stream raster", "C2", "--"),
    (with_channel, "zonal min of the channel pixels", "C0", "-"),
]:
    values.axhline(level, color=colour, ls=style, lw=1.8, label=f"{text}: {level:.1f} m")
values.set_xticks([])
values.set_xlim(-0.6, 0.6)
values.set_ylabel(r"elevation (m)")
values.set_title(r"Three candidate tops $z_{\mathrm{top},c}$", fontsize=10)
values.legend(loc="upper center", bbox_to_anchor=(0.45, -0.04), fontsize=7.5, frameon=False)
fig.tight_layout()
