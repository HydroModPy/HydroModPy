"""Layers by surfaces in a cross-section, with the two pinch-out rules.

Three layers: a weathered layer 15 m deep, a fissured layer whose base is read
from a raster that rises to the weathered base in the middle, and a fresh layer
down to the base of the aquifer. The interfaces come from base_interfaces and
the pinch-out from pinch_out, as in a run.
"""

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle

from hydromodpy.spatial.domain.layering import base_interfaces, pinch_out
from hydromodpy.spatial.domain.layers_config import SurfaceLayerConfig

x = np.arange(14, dtype=float)
top = 100.0 - 1.2 * x
bottom = np.full_like(x, 45.0)
raster = top - 15.0 - np.minimum(18.0, 1.6 * np.abs(x - 6.5) ** 1.6) + 1.0
layers = [
    SurfaceLayerConfig(name="weathered", depth=15.0),
    SurfaceLayerConfig(name="fissured", surface="fissured_base", min_thickness=4.0),
    SurfaceLayerConfig(name="fresh"),
]
interfaces = base_interfaces(top=top, bottom=bottom, layers=layers, bases={"fissured_base": raster})

fig, axes = plt.subplots(1, 2, figsize=(6.4, 3.4), sharey=True)
for ax, mode in zip(axes, ("pass_through", "keep_min_thickness"), strict=True):
    stack = pinch_out(interfaces, [layer.min_thickness for layer in layers], mode=mode)
    upper = np.vstack([top, stack.botm[:-1]])
    for k, layer in enumerate(layers):
        for i, xi in enumerate(x):
            height = upper[k, i] - stack.botm[k, i]
            if stack.idomain[k, i] == -1:
                ax.plot([xi, xi + 1.0], [upper[k, i]] * 2, color="C6", lw=2.5)
                continue
            ax.add_patch(
                Rectangle((xi, stack.botm[k, i]), 1.0, height, fc=(f"C{k}", 0.35), ec="C6", lw=0.5)
            )
        ax.plot([], [], "s", color=f"C{k}", alpha=0.5, label=layer.name)
    ax.step(
        np.append(x, x[-1] + 1.0),
        np.append(raster, raster[-1]),
        where="post",
        color="C6",
        ls=":",
        lw=1.0,
    )
    n_pass = int((stack.idomain == -1).sum())
    ax.set_title(f"{mode}\n{n_pass} cells with idomain = -1", fontsize=10)
    ax.set_xlim(0.0, x[-1] + 1.0)
    ax.set_xticks([])
    ax.set_xlabel("columns of cells")
axes[0].set_ylim(40.0, 104.0)
axes[0].set_ylabel("elevation (m)")
axes[0].plot([], [], color="C6", lw=2.5, label="pass-through cell")
axes[0].plot([], [], color="C6", ls=":", lw=1.0, label="raster base")
fig.legend(
    *axes[0].get_legend_handles_labels(), loc="lower center", ncol=5, fontsize=7.5, frameon=False
)
fig.tight_layout(rect=(0.0, 0.07, 1.0, 1.0))
