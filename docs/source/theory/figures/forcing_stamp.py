"""A stamp closes its period: a flux is the mean before it, a state the value at it."""

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from hydromodpy.core.time.period_aggregation import period_mean_on_index, period_point_on_index

BLUE, ORANGE = "#0072B2", "#D55E00"
start = pd.Timestamp("2000-01-01")
stamps = pd.date_range("2000-02-01", "2000-05-01", freq="MS")  # end of each monthly period
days = pd.date_range(start, "2000-04-30", freq="D")
phase = np.arange(days.size) / 120.0 * 2.0 * np.pi
discharge = pd.Series(1.0 + 0.6 * np.cos(phase) + 0.25 * np.sin(5.0 * phase), index=days)
head = pd.Series(12.0 + 0.8 * np.cos(phase - 0.6), index=days)
period_mean = period_mean_on_index(discharge, stamps, start=start)
at_stamp = period_point_on_index(head, stamps)

fig, axes = plt.subplots(2, 1, figsize=(6.4, 4.2), sharex=True)
axes[0].plot(days, discharge, color="0.6", lw=0.9, label="daily flux")
edges = [start, *stamps]
for left, right, value in zip(edges[:-1], edges[1:], period_mean, strict=True):
    axes[0].hlines(value, left, right, color=BLUE, lw=2.5)
axes[0].plot(
    stamps, period_mean, "o", color=BLUE, ms=5, label="'mean': the period before the stamp"
)
axes[0].set_ylabel("flux")
axes[1].plot(days, head, color="0.6", lw=0.9, label="daily state")
axes[1].plot(
    stamps,
    at_stamp,
    "s",
    color=ORANGE,
    ms=5,
    label="'point': the state at the stamp, a window centred on it",
)
axes[1].set_ylabel("head (m)")
for ax in axes:
    for edge in edges:
        ax.axvline(edge, color="0.75", lw=0.7)
    ax.legend(fontsize=7, loc="upper right")
axes[0].text(start, axes[0].get_ylim()[1], " $b_0$", va="top", fontsize=8)
axes[0].text(stamps[0], axes[0].get_ylim()[1], " $b_1$: stamp of period 0", va="top", fontsize=8)
axes[1].xaxis.set_major_formatter(plt.matplotlib.dates.DateFormatter("%d %b"))
axes[1].set_xticks(edges)
fig.tight_layout()
