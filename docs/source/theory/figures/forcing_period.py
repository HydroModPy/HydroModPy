"""Which samples of a record each stress period takes, and which periods it covers."""

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from hydromodpy.core.time.coverage import record_step, samples_by_period

BLUE, ORANGE, GREEN = "#0072B2", "#D55E00", "#009E73"
edges = pd.date_range("2000-01-01", "2000-07-01", freq="MS")  # six monthly periods
# A weekly record with a gap over March, ending at the start of May.
stamps = pd.DatetimeIndex(
    list(pd.date_range("2000-01-05", "2000-02-16", freq="7D"))
    + list(pd.date_range("2000-04-05", "2000-04-26", freq="7D"))
)
values = 2.0 + 1.5 * np.sin(np.arange(stamps.size) / 2.0)
periods = samples_by_period(stamps, edges)
step = record_step(stamps)

fig, ax = plt.subplots(figsize=(6.4, 3.4))
for i, (left, right) in enumerate(zip(edges[:-1], edges[1:], strict=True)):
    inside = periods.inside[i]
    if inside.size:
        value, colour = values[inside].mean(), BLUE
    else:
        value = values[periods.fill[i]]
        colour = ORANGE if i in periods.uncovered else GREEN
    ax.hlines(value, left, right, color=colour, lw=2.5)
    if i in periods.uncovered:
        ax.axvspan(left, right, color=ORANGE, alpha=0.12, lw=0)
for edge in edges:
    ax.axvline(edge, color="0.6", lw=0.7)
ax.text(edges[0], 4.3, "$b_0$", ha="center", fontsize=8)
ax.text(edges[1], 4.3, "$b_1$", ha="center", fontsize=8)
ends = list(stamps[1:]) + [stamps[-1] + step]
for stamp, end, value in zip(stamps, ends, values, strict=True):
    ax.plot([stamp, end], [value, value], color="0.35", lw=0.8)
ax.plot(stamps, values, "o", color="0.2", ms=3.5, label="sample, with the interval it stands for")
ax.plot([], [], color=BLUE, lw=2.5, label="mean of the samples inside the period")
ax.plot([], [], color=GREEN, lw=2.5, label="no sample inside: the sample in force")
ax.plot([], [], color=ORANGE, lw=2.5, label="not covered: stops the run, or nearest sample")
ax.set_ylim(0.0, 4.6)
ax.set_xlim(edges[0] - pd.Timedelta(days=4), edges[-1] + pd.Timedelta(days=4))
ax.set_ylabel("rate (mm/day)")
ax.legend(fontsize=7, loc="upper left", bbox_to_anchor=(0.0, -0.12), ncol=2, frameon=False)
ax.xaxis.set_major_formatter(plt.matplotlib.dates.DateFormatter("%b"))
fig.tight_layout()
