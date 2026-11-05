"""Compare the recharge and the runoff of sealed runs, on one interactive page.

The recharge is what MODFLOW 6 received over the catchment. The runoff is what the
simulated discharge holds above the drains, whatever made it: the RUNC of SIM2, or
the curve number of the soil reservoir. Both read the same way on any run, so this
script works on other projects too.

    python compare_recharge.py                         every run of this project
    python compare_recharge.py "nancon-*" "*_month"    the runs these patterns name
    python compare_recharge.py --runs ../other/runs --out other.html

The name of a run is <site>-<recipe>. A word of the recipe in COLOR gives its color and
a word in DASH its line, so sim2_day and grid_soil both read. A recipe with neither
takes the next color, in a solid line. Change these two for another scheme.
"""

from __future__ import annotations

import argparse
from fnmatch import fnmatch
from itertools import cycle
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.colors import qualitative
from plotly.subplots import make_subplots

import hydromodpy as hmp

HERE = Path(__file__).resolve().parent
COLOR = {"sim2": "#2a78d6", "soil": "#d95926"}
DASH = {"month": "solid", "week": "dash", "day": "dot"}
SCORES = ["nse_log", "kge", "nse"]
SUMMER = (7, 8, 9)
SHOWN = ("per month", "per stress period")


def fluxes(run: hmp.Run) -> pd.DataFrame:
    """Recharge and runoff over the catchment in mm/day, one row per stress period."""
    edges = run.periods.edges
    to_mm_per_day = 86400.0 * 1000.0 / hmp.read(run, "watershed").geometry.area.sum()
    recharge = run.budget("recharge", zone_id="catchment").set_index("timestep")["flux_in"]
    drain = run.budget("drain", zone_id="catchment").set_index("timestep")["flux_out"]
    discharge = run.timeseries("discharge", station="catchment").to_numpy()
    frame = pd.DataFrame(
        {
            "recharge": recharge.sort_index().to_numpy(),
            "runoff": (discharge - drain.sort_index().to_numpy()).clip(min=0.0),
        },
        index=edges[:-1],
    )
    return frame * to_mm_per_day


def daily(frame: pd.DataFrame) -> pd.DataFrame:
    """Each stress period spread over its days, so any two runs share one time axis."""
    days = pd.date_range(frame.index[0], frame.index[-1] + (frame.index[-1] - frame.index[-2]))
    return frame.reindex(days[:-1], method="ffill")


def summary_row(name: str, run: hmp.Run, days: pd.DataFrame) -> dict:
    scores = run.metrics.set_index("metric")["value"] if not run.metrics.empty else pd.Series()
    row = {
        "run": name,
        "recharge, mm/year": days["recharge"].mean() * 365.25,
        "runoff, mm/year": days["runoff"].mean() * 365.25,
        "recharge July-September, mm/day": days["recharge"][days.index.month.isin(SUMMER)].mean(),
    }
    return row | {score: scores.get(score) for score in SCORES}


def page(series: dict[str, pd.DataFrame], days: dict[str, pd.DataFrame]) -> go.Figure:
    """One column per site, recharge and runoff above their running totals."""
    sites = sorted({name.partition("-")[0] for name in series})
    rows = ("recharge, mm/day", "runoff, mm/day", "cumulated recharge, mm", "cumulated runoff, mm")
    fig = make_subplots(
        rows=len(rows),
        cols=len(sites),
        shared_xaxes=True,
        column_titles=sites,
        row_titles=rows,
        vertical_spacing=0.04,
        horizontal_spacing=0.05,
    )
    other = cycle(qualitative.Dark24)
    visible: dict[str, list[bool]] = {shown: [] for shown in SHOWN}
    for name, native in series.items():
        site, _, recipe = name.partition("-")
        words = recipe.split("_")
        color = next((COLOR[word] for word in words if word in COLOR), None) or next(other)
        dash = next((DASH[word] for word in words if word in DASH), "solid")
        line = {"color": color, "dash": dash, "width": 1.5}
        col = sites.index(site) + 1
        monthly = days[name].resample("MS").mean()
        total = days[name].cumsum().resample("MS").last()
        curves = [
            (1, "recharge", monthly, SHOWN[0]),
            (1, "recharge", native, SHOWN[1]),
            (2, "runoff", monthly, SHOWN[0]),
            (2, "runoff", native, SHOWN[1]),
            (3, "recharge", total, None),
            (4, "runoff", total, None),
        ]
        for row, term, data, shown in curves:
            fig.add_trace(
                go.Scatter(
                    x=data.index,
                    y=data[term],
                    name=recipe,
                    legendgroup=recipe,
                    showlegend=col == 1 and row == 1 and shown == SHOWN[0],
                    visible=shown in (None, SHOWN[0]),
                    line=line,
                    line_shape="hv" if shown else "linear",
                    hovertemplate=f"{name}<br>%{{x|%Y-%m-%d}}: %{{y:.3f}}<extra></extra>",
                ),
                row=row,
                col=col,
            )
            for key, flags in visible.items():
                flags.append(shown is None or shown == key)
    buttons = [
        {"label": key, "method": "update", "args": [{"visible": flags}]}
        for key, flags in visible.items()
    ]
    fig.update_layout(
        hovermode="closest",
        template="plotly_white",
        updatemenus=[
            {"type": "buttons", "direction": "right", "x": 0.0, "y": 1.06, "buttons": buttons}
        ],
    )
    return fig


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("names", nargs="*", default=["*"], help="run names, shell patterns allowed")
    parser.add_argument("--runs", type=Path, default=HERE / "runs", help="folder of the runs")
    parser.add_argument("--out", type=Path, default=HERE / "comparison.html", help="page to write")
    args = parser.parse_args()

    paths = [
        path
        for path in sorted(args.runs.iterdir())
        if (path / "manifest.json").is_file()
        and any(fnmatch(path.name, name) for name in args.names)
    ]
    opened = {path.name: hmp.open(path) for path in paths}
    series = {name: fluxes(run) for name, run in opened.items()}
    days = {name: daily(frame) for name, frame in series.items()}
    # Runs of different steps can end days apart: the totals read on the dates they share.
    start = max(frame.index[0] for frame in days.values())
    end = min(frame.index[-1] for frame in days.values())
    days = {name: frame[start:end] for name, frame in days.items()}
    rows = [summary_row(name, opened[name], days[name]) for name in opened]
    table = pd.DataFrame(rows).set_index("run").round(3)
    print(table.to_string())
    table.to_csv(args.out.with_suffix(".csv"))

    body = page(series, days).to_html(
        full_html=False, include_plotlyjs=True, default_width="100%", default_height="1000px"
    )
    args.out.write_text(
        f'<!doctype html><meta charset="utf-8"><title>Recharge and runoff</title>{body}{table.to_html()}',
        encoding="utf-8",
    )
    print(f"written: {args.out}")


if __name__ == "__main__":
    main()
