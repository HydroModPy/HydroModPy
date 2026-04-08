"""Generic time-series figures.

Each ``render_*`` function draws on an existing Axes.
Each ``plot_*`` wrapper creates a figure, renders, and optionally saves.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    import pandas as pd
    from matplotlib.axes import Axes

    from hydromodpy.analysis.display.display_config import DisplayOptions


# ======================================================================
# Discharge
# ======================================================================

def render_discharge(
    ax: "Axes",
    *,
    observed_df: "pd.DataFrame | pd.Series | None" = None,
    simulated_series: "pd.Series | None" = None,
    recharge_series: "pd.Series | None" = None,
    model_label: str = "",
    ylabel: str = "Discharge (m\u00b3/s)",
) -> None:
    """Discharge time series — observed, simulated, and/or recharge.

    **Overview mode** (only *observed_df*): each column is plotted as a
    separate station.

    **Simulation mode** (*simulated_series* and/or *recharge_series*
    provided): comparison styling with date formatters.
    """
    import matplotlib.dates as mdates
    import pandas as pd

    has_sim = simulated_series is not None or recharge_series is not None

    if observed_df is None and not has_sim:
        ax.text(0.5, 0.5, "No discharge data", ha="center", va="center",
                transform=ax.transAxes, fontsize=10)
        ax.set_axis_off()
        return

    # Observed
    if observed_df is not None:
        if isinstance(observed_df, pd.Series):
            observed_df = observed_df.to_frame("Observed")
        if has_sim:
            # Simulation mode: single observed line (first column)
            col = observed_df.columns[0]
            ax.plot(observed_df.index, observed_df[col], color="k", lw=2,
                    label="Observed")
        else:
            # Overview mode: one line per station
            for col in observed_df.columns:
                ax.plot(observed_df.index, observed_df[col], lw=0.8,
                        label=col, alpha=0.8)

    # Simulated
    if simulated_series is not None:
        label = f"Simulated: {model_label}" if model_label else "Simulated"
        ax.plot(simulated_series.index, simulated_series.values, color="red",
                lw=2, label=label)

    # Recharge overlay
    if recharge_series is not None:
        ax.plot(recharge_series.index, recharge_series.values, color="dodgerblue",
                lw=2, label="Recharge")

    ax.set_ylabel(ylabel)
    ax.set_xlabel("")
    ax.legend(fontsize=7, loc="upper left", framealpha=0.8)
    ax.grid(True, alpha=0.3)

    if has_sim:
        ax.xaxis.set_major_locator(mdates.YearLocator(1))
        ax.xaxis.set_minor_locator(mdates.MonthLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    if model_label:
        ax.set_title(model_label, fontsize=10)
    elif not has_sim:
        ax.set_title("Observed discharge", fontsize=9)


def plot_discharge(
    *,
    observed_df: "pd.DataFrame | pd.Series | None" = None,
    simulated_series: "pd.Series | None" = None,
    recharge_series: "pd.Series | None" = None,
    model_label: str = "",
    ylabel: str = "Discharge (m\u00b3/s)",
    options: "DisplayOptions | None" = None,
    save_path: Path | None = None,
    figsize: tuple[float, float] = (12, 3.5),
    dpi: int = 300,
):
    """Create a discharge figure, render, and optionally save."""
    from hydromodpy.analysis.display.common import finalize_figure, make_figure, _single_axes

    fig, axs = make_figure(figsize=figsize, dpi=dpi)
    ax = _single_axes(axs)
    render_discharge(
        ax,
        observed_df=observed_df,
        simulated_series=simulated_series,
        recharge_series=recharge_series,
        model_label=model_label,
        ylabel=ylabel,
    )
    fig.tight_layout()
    if options is not None:
        finalize_figure(fig, options=options, save_path=save_path)
    return fig, ax


# ======================================================================
# Piezometry
# ======================================================================

def render_piezometry(
    ax: "Axes",
    *,
    observed_df: "pd.DataFrame | None" = None,
    simulated_series: "pd.Series | None" = None,
    recharge_series: "pd.Series | None" = None,
    model_label: str = "",
) -> None:
    """Piezometric levels — observed and/or simulated with recharge.

    **Overview mode** (only *observed_df*): one line per station column.

    **Simulation mode** (*simulated_series* provided): comparison with
    recharge overlay on a twin axis.
    """
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    import pandas as pd

    has_sim = simulated_series is not None

    if observed_df is None and not has_sim:
        ax.text(0.5, 0.5, "No piezometry data", ha="center", va="center",
                transform=ax.transAxes, fontsize=10)
        ax.set_axis_off()
        return

    # Simulated WT depth
    if simulated_series is not None:
        ax.plot(simulated_series.index, simulated_series.values, marker="o",
                color="red", lw=2, label="Simulated: watertable")

    # Observed
    if observed_df is not None:
        if isinstance(observed_df, pd.Series):
            observed_df = observed_df.to_frame("Observed")
        colors = plt.cm.tab10(np.linspace(0, 1, min(len(observed_df.columns), 10)))
        for i, col in enumerate(observed_df.columns):
            ax.plot(observed_df.index, observed_df[col], lw=1.5 if has_sim else 0.8,
                    ls="--" if has_sim else "-",
                    color=colors[i % len(colors)],
                    label=f"Obs: {col}" if has_sim else col, alpha=0.8)

    ax.set_ylabel("Water level (m)" if not has_sim else "WT depth [m]")
    ax.set_xlabel("")
    ax.legend(fontsize=7 if has_sim else 6, loc="upper left", framealpha=0.8)
    ax.grid(True, alpha=0.3)

    if has_sim:
        ax.xaxis.set_major_locator(mdates.YearLocator(1))
        ax.xaxis.set_minor_locator(mdates.MonthLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        ax.invert_yaxis()
        if model_label:
            ax.set_title(model_label, fontsize=10)

        # Recharge overlay on twin axis
        if recharge_series is not None:
            axb = ax.twinx()
            axb.bar(recharge_series.index, recharge_series.values,
                    color="dodgerblue", width=10, edgecolor="None",
                    alpha=1, label="Recharge")
            axb.set_ylim(0, 100)
            axb.invert_yaxis()
            axb.legend(loc="upper right")
    else:
        ax.set_title("Observed piezometric levels", fontsize=9)


def plot_piezometry(
    *,
    observed_df: "pd.DataFrame | None" = None,
    simulated_series: "pd.Series | None" = None,
    recharge_series: "pd.Series | None" = None,
    model_label: str = "",
    options: "DisplayOptions | None" = None,
    save_path: Path | None = None,
    figsize: tuple[float, float] = (12, 3.5),
    dpi: int = 300,
):
    """Create a piezometry figure, render, and optionally save."""
    from hydromodpy.analysis.display.common import finalize_figure, make_figure, _single_axes

    fig, axs = make_figure(figsize=figsize, dpi=dpi)
    ax = _single_axes(axs)
    render_piezometry(
        ax,
        observed_df=observed_df,
        simulated_series=simulated_series,
        recharge_series=recharge_series,
        model_label=model_label,
    )
    fig.tight_layout()
    if options is not None:
        finalize_figure(fig, options=options, save_path=save_path)
    return fig, ax


# ======================================================================
# Climatic summary
# ======================================================================

def render_climatic_summary(
    ax: "Axes",
    *,
    monthly_precip: dict[int, float] | None = None,
    monthly_etp: dict[int, float] | None = None,
) -> None:
    """Monthly-mean bar chart for precipitation and ETP.

    Each argument maps month number (1-12) to a value in mm/month.
    """
    has_data = False
    months = range(1, 13)

    for monthly, label, color, offset in [
        (monthly_precip, "Precipitation", "steelblue", -0.2),
        (monthly_etp, "ETP", "coral", 0.2),
    ]:
        if monthly is None:
            continue
        has_data = True
        values = [monthly.get(m, 0.0) for m in months]
        ax.bar([m + offset for m in months], values, width=0.35,
               label=label, color=color, alpha=0.7)

    if not has_data:
        ax.text(0.5, 0.5, "No climatic data", ha="center", va="center",
                transform=ax.transAxes, fontsize=10)
        ax.set_axis_off()
        return

    ax.set_xticks(range(1, 13))
    ax.set_xticklabels(["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"])
    ax.set_ylabel("mm/month")
    ax.set_title("Mean monthly precipitation & ETP", fontsize=9)
    ax.legend(fontsize=7, framealpha=0.8)
    ax.grid(True, alpha=0.3, axis="y")


def plot_climatic_summary(
    *,
    monthly_precip: dict[int, float] | None = None,
    monthly_etp: dict[int, float] | None = None,
    options: "DisplayOptions | None" = None,
    save_path: Path | None = None,
    figsize: tuple[float, float] = (8, 4),
    dpi: int = 300,
):
    """Create a climatic summary figure, render, and optionally save."""
    from hydromodpy.analysis.display.common import finalize_figure, make_figure, _single_axes

    fig, axs = make_figure(figsize=figsize, dpi=dpi)
    ax = _single_axes(axs)
    render_climatic_summary(ax, monthly_precip=monthly_precip, monthly_etp=monthly_etp)
    fig.tight_layout()
    if options is not None:
        finalize_figure(fig, options=options, save_path=save_path)
    return fig, ax


# ======================================================================
# Intermittency
# ======================================================================

_FLOW_STATE_LABELS = {
    1: "Assec",
    2: "Non visible",
    3: "Faible",
    4: "Acceptable",
    5: "Visible",
}
_FLOW_STATE_COLORS = {
    1: "#c0392b",   # deep red
    2: "#e67e22",   # warm orange
    3: "#f1c40f",   # golden yellow
    4: "#27ae60",   # emerald green
    5: "#2980b9",   # ocean blue
}


def _intermittency_legend_handles():
    """Return legend handles for the 5 ONDE flow states."""
    import matplotlib.lines as mlines

    return [
        mlines.Line2D(
            [], [], color=_FLOW_STATE_COLORS[k], marker="|",
            linestyle="None", markersize=8, markeredgewidth=2.0,
            label=_FLOW_STATE_LABELS[k],
        )
        for k in (1, 2, 3, 4, 5)
    ]


def render_intermittency(
    ax: "Axes",
    *,
    records_df: "pd.DataFrame | None" = None,
    station_id: str | None = None,
    show_legend: bool = False,
) -> None:
    """ONDE flow-state observations as a categorical scatter plot.

    Draws vertical bar markers (``|``) coloured by flow state on a
    categorical y-axis (Assec → Visible).  When *station_id* is given,
    only that station is drawn and used as the axes title.

    Set *show_legend* to ``True`` only on a single axes — the caller
    is expected to place one shared legend on the figure instead.

    *records_df* has columns ``datetime``, ``station_id``, ``value``.
    """
    if records_df is None or records_df.empty:
        ax.text(0.5, 0.5, "No intermittency data", ha="center", va="center",
                transform=ax.transAxes, fontsize=10)
        ax.set_axis_off()
        return

    import matplotlib.dates as mdates

    # Filter to one station if requested
    if station_id is not None:
        records_df = records_df[records_df["station_id"] == station_id]
        if records_df.empty:
            ax.text(0.5, 0.5, "No data", ha="center", va="center",
                    transform=ax.transAxes, fontsize=10)
            ax.set_axis_off()
            return

    sub = records_df.sort_values("datetime")
    values = sub["value"].astype(int).clip(1, 5)

    # Subtle horizontal bands behind the markers
    for yval in (1, 2, 3, 4, 5):
        ax.axhspan(yval - 0.4, yval + 0.4,
                   color=_FLOW_STATE_COLORS[yval], alpha=0.06, zorder=0)

    # Plot each state separately for crisp colours
    for state_val in sorted(_FLOW_STATE_COLORS):
        mask = values == state_val
        if not mask.any():
            continue
        ax.scatter(
            sub["datetime"].values[mask.values],
            values.values[mask.values],
            c=_FLOW_STATE_COLORS[state_val],
            marker="|", s=160, linewidths=2.2, zorder=3,
        )

    # Resolve title
    title = station_id or (
        str(sub["station_id"].unique()[0])
        if sub["station_id"].nunique() == 1
        else "Observations ONDE"
    )

    # Use ultraplot format() when available, fallback to matplotlib
    _fmt = getattr(ax, "format", None)
    if _fmt is not None and callable(_fmt):
        _fmt(
            ylabel="", xlabel="",
            yticks=[1, 2, 3, 4, 5],
            yticklabels=[_FLOW_STATE_LABELS[k] for k in (1, 2, 3, 4, 5)],
            yticklabelsize=7, xticklabelsize=7,
            ylim=(0.4, 5.6),
            xlocator=mdates.YearLocator(2),
            xminorlocator=mdates.YearLocator(),
            xformatter=mdates.DateFormatter("%Y"),
            ygrid=False, xgrid=False,
        )
    else:
        ax.set_yticks([1, 2, 3, 4, 5])
        ax.set_yticklabels(
            [_FLOW_STATE_LABELS[k] for k in (1, 2, 3, 4, 5)], fontsize=7,
        )
        ax.set_ylim(0.4, 5.6)
        ax.set_ylabel("")
        ax.set_xlabel("")
        ax.xaxis.set_major_locator(mdates.YearLocator(2))
        ax.xaxis.set_minor_locator(mdates.YearLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        ax.tick_params(axis="x", labelsize=7)

    # Title above the axes frame (works reliably with both backends)
    ax.set_title(title, fontsize=8, fontweight="bold", loc="left", pad=4)

    if show_legend:
        ax.legend(
            handles=_intermittency_legend_handles(), fontsize=6.5,
            loc="upper right", framealpha=0.9, edgecolor="0.8",
            fancybox=False, ncol=5, handletextpad=0.3,
            columnspacing=0.8, borderpad=0.3,
        )


def plot_intermittency(
    *,
    records_df: "pd.DataFrame | None" = None,
    options: "DisplayOptions | None" = None,
    save_path: Path | None = None,
    figsize: tuple[float, float] | None = None,
    dpi: int = 300,
):
    """Create a compact intermittency figure with one subplot per station.

    A single shared legend is placed below the bottom axes.
    """
    from hydromodpy.analysis.display.common import finalize_figure, make_figure

    n_stations = (
        records_df["station_id"].nunique()
        if records_df is not None and not records_df.empty
        else 1
    )
    if figsize is None:
        figsize = (7, max(1.6, 1.6 * n_stations + 0.4))
    fig, axs = make_figure(
        nrows=max(1, n_stations), ncols=1, figsize=figsize, dpi=dpi,
        sharex=3, hspace=2.0,
    )

    import numpy as np

    axes_flat = list(np.asarray(axs).flat) if n_stations > 1 else [axs]

    if records_df is None or records_df.empty:
        for a in axes_flat:
            render_intermittency(a, records_df=records_df)
    else:
        stations = list(records_df["station_id"].unique())
        for ax, sid in zip(axes_flat, stations):
            render_intermittency(ax, records_df=records_df, station_id=sid)

    # Shared horizontal legend below all subplots
    fig.legend(
        handles=_intermittency_legend_handles(),
        loc="bottom", ncol=5, fontsize=7,
        frameon=False, handletextpad=0.3, columnspacing=1.0,
    )

    if options is not None:
        finalize_figure(fig, options=options, save_path=save_path)
    return fig, axs


# ======================================================================
# Water quality
# ======================================================================

def render_water_quality(
    ax: "Axes",
    *,
    records_df: "pd.DataFrame | None" = None,
) -> None:
    """Water quality parameters over time.

    *records_df* has columns ``datetime``, ``variable``, ``value``,
    and optionally ``unit`` and ``source_unit``.
    """
    if records_df is None or records_df.empty:
        ax.text(0.5, 0.5, "No water quality data", ha="center", va="center",
                transform=ax.transAxes, fontsize=10)
        ax.set_axis_off()
        return

    colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]
    params = list(records_df["variable"].unique())[:6]

    seen_labels: set[str] = set()
    for i, param in enumerate(params):
        sub = records_df[records_df["variable"] == param].sort_values("datetime")
        unit = sub["unit"].iloc[0] if "unit" in sub.columns and not sub["unit"].isna().all() else ""
        source_unit = (
            sub["source_unit"].iloc[0]
            if "source_unit" in sub.columns and not sub["source_unit"].isna().all()
            else ""
        )
        if unit and source_unit and source_unit != unit:
            label = f"{param} ({unit}; src {source_unit})"
        elif unit:
            label = f"{param} ({unit})"
        else:
            label = param
        # Avoid duplicate legend entries
        if label in seen_labels:
            label = None
        else:
            seen_labels.add(label)
        ax.plot(sub["datetime"], sub["value"], lw=0.8, alpha=0.7,
                color=colors[i % len(colors)], label=label)

    ax.set_ylabel("Concentration")
    ax.set_xlabel("")
    ax.legend(fontsize=5.5, loc="upper right", framealpha=0.8, ncol=2)
    ax.set_title("Water quality", fontsize=9)
    ax.grid(True, alpha=0.3)


def plot_water_quality(
    *,
    records_df: "pd.DataFrame | None" = None,
    options: "DisplayOptions | None" = None,
    save_path: Path | None = None,
    figsize: tuple[float, float] = (10, 4),
    dpi: int = 300,
):
    """Create a water quality figure, render, and optionally save."""
    from hydromodpy.analysis.display.common import finalize_figure, make_figure, _single_axes

    fig, axs = make_figure(figsize=figsize, dpi=dpi)
    ax = _single_axes(axs)
    render_water_quality(ax, records_df=records_df)
    fig.tight_layout()
    if options is not None:
        finalize_figure(fig, options=options, save_path=save_path)
    return fig, ax


# ======================================================================
# Concentration panel (temporal — top panel in transport animation)
# ======================================================================

def render_concentration_panel(
    ax: "Axes",
    *,
    box_stats: list[tuple[float, list[dict]]],
    mean_times: list[float],
    mean_vals: list[float],
    recharge_month: "pd.Series",
    xpos: float,
    input_conc: float = 0.0,
    nframes: int | None = None,
) -> None:
    """Temporal evolution of concentration statistics for one animation frame.

    *box_stats* is a cumulative list of ``(xpos, bxp_stats_list)`` tuples
    built across all frames so far.
    """
    import matplotlib.dates as mdates
    import pandas as pd

    axb = ax.twinx()
    ax.zorder, axb.zorder = 1, 0
    ax.patch.set_visible(False)

    # Redraw cumulative box-plots
    for xpos_b, bstat in box_stats:
        ax.bxp(
            bstat,
            positions=[xpos_b],
            widths=5,
            showfliers=False,
            showmeans=True,
            meanline=False,
            boxprops=dict(color="forestgreen"),
            medianprops=dict(color="forestgreen"),
            meanprops=dict(
                marker="o", markerfacecolor="k",
                markeredgecolor="k", markersize=5,
            ),
        )

    ax.axvline(x=xpos, color="black", linestyle="--", lw=0.5, zorder=-1)
    if input_conc > 0:
        ax.axhline(
            y=input_conc, color="darkorange", linestyle="-", lw=1,
            zorder=-1, label=f"Injection: {input_conc:.0f} mg/L",
        )

    ax.set_ylabel("[NO3] mg/L", color="forestgreen")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))

    # Compute x-axis limits from recharge_month
    ax.set_xlim(
        pd.to_datetime(recharge_month.index[0]),
        pd.to_datetime(recharge_month.index[-1]) + pd.Timedelta(days=31),
    )

    ax.plot(mean_times, mean_vals, color="black", lw=2)

    n = nframes if nframes is not None else len(recharge_month)
    axb.step(recharge_month.index[:n], recharge_month.iloc[:n],
             lw=2, color="dodgerblue")
    axb.set_ylabel("Recharge [mm/month]", color="dodgerblue")


def plot_concentration_panel(
    *,
    box_stats: list[tuple[float, list[dict]]],
    mean_times: list[float],
    mean_vals: list[float],
    recharge_month: "pd.Series",
    xpos: float,
    input_conc: float = 0.0,
    nframes: int | None = None,
    options: "DisplayOptions | None" = None,
    save_path: Path | None = None,
    figsize: tuple[float, float] = (8, 4),
    dpi: int = 300,
):
    """Create a concentration panel figure, render, and optionally save."""
    from hydromodpy.analysis.display.common import finalize_figure, make_figure, _single_axes

    fig, axs = make_figure(figsize=figsize, dpi=dpi)
    ax = _single_axes(axs)
    render_concentration_panel(
        ax,
        box_stats=box_stats,
        mean_times=mean_times,
        mean_vals=mean_vals,
        recharge_month=recharge_month,
        xpos=xpos,
        input_conc=input_conc,
        nframes=nframes,
    )
    fig.tight_layout()
    if options is not None:
        finalize_figure(fig, options=options, save_path=save_path)
    return fig, ax


# ======================================================================
# Bridge helpers (PointRecord/FieldRecord → dict[int, float])
# ======================================================================

def _monthly_mean_from_records(records) -> dict[int, float] | None:
    """Average monthly totals across station PointRecords.

    Returns ``{month_number: mm/month}`` or *None* when empty.
    """
    import pandas as pd

    all_monthly: list[pd.Series] = []
    for rec in records:
        df = rec.data.copy()
        df = df.set_index("datetime").sort_index()
        monthly = df["value"].resample("ME").sum()
        all_monthly.append(monthly)
    if not all_monthly:
        return None
    combined = pd.concat(all_monthly, axis=1).mean(axis=1)
    grouped = combined.groupby(combined.index.month).mean()
    return grouped.to_dict()


def _monthly_mean_from_fields(load_result) -> dict[int, float] | None:
    """Compute monthly means from FieldRecords (SIM2-style NetCDF grids).

    Returns ``{month_number: mm/month}`` or *None* when empty.
    """
    import pandas as pd
    import xarray as xr

    fields = getattr(load_result, "fields", None)
    if not fields:
        return None

    all_series: list[pd.Series] = []
    for frec in fields:
        try:
            data = frec.data
            if isinstance(data, (str, Path)):
                ds = xr.open_dataset(str(data))
            else:
                ds = data

            data_vars = [v for v in ds.data_vars
                         if v not in ("x", "y", "lat", "lon", "spatial_ref")]
            if not data_vars:
                continue
            da = ds[data_vars[0]]

            spatial_dims = [d for d in da.dims if d not in ("time",)]
            ts = da.mean(dim=spatial_dims)

            series = ts.to_series()
            if not isinstance(series.index, pd.DatetimeIndex):
                series.index = pd.to_datetime(series.index)

            all_series.append(series)
        except Exception:
            continue

    if not all_series:
        return None

    combined = pd.concat(all_series, axis=1).mean(axis=1)
    monthly_sum = combined.resample("ME").sum()
    grouped = monthly_sum.groupby(monthly_sum.index.month).mean()
    return grouped.to_dict()
