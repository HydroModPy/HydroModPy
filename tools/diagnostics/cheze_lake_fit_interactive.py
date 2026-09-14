"""Interactive observed-vs-simulated lake-level fit (self-contained Plotly HTML).

    python tools/diagnostics/cheze_lake_fit_interactive.py <run_timeseries.csv> \
        <observed.csv> [out.html] [station_substr]

Reads the simulated lake stage from a run's exported long-format timeseries
(datetime, station_id, variable, value) and the observed daily levels, aligns
them on the common days, and writes a zoomable Plotly chart (observed vs
simulated + residuals + KGE/NSE/RMSE) as ONE offline HTML (plotly.js inlined).
"""

import sys

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

TS = sys.argv[1]
OBS = sys.argv[2]
OUT = sys.argv[3] if len(sys.argv) > 3 else "lake_fit_interactive.html"
STATION = sys.argv[4] if len(sys.argv) > 4 else "reserv"
SILL, SPILLWAY, BOTTOM = 86.93, 87.57, 54.45  # reservoir reference levels (m NGF)


def _daily(dates: pd.Series, values: pd.Series) -> pd.Series:
    d = pd.to_datetime(dates, utc=True, errors="coerce").dt.date
    v = pd.to_numeric(values, errors="coerce")
    return pd.DataFrame({"d": d, "v": v}).dropna().groupby("d")["v"].mean()


# simulated stage for the target lake, streamed (the export is large)
rows = []
for chunk in pd.read_csv(TS, chunksize=400000):
    m = chunk[
        chunk["variable"].astype(str).str.contains("stage|lake_level", case=False, na=False)
        & chunk["station_id"].astype(str).str.contains(STATION, case=False, na=False)
    ]
    if len(m):
        rows.append(m[["datetime", "value"]])
if not rows:
    raise SystemExit(f"no simulated stage for station '{STATION}' in {TS}")
sim = _daily(pd.concat(rows)["datetime"], pd.concat(rows)["value"])

obs_df = pd.read_csv(OBS)
date_col = next(c for c in obs_df.columns if "date" in c.lower() or "time" in c.lower())
val_col = next(c for c in obs_df.columns if c != date_col)
obs = _daily(obs_df[date_col], obs_df[val_col])

df = pd.DataFrame({"sim": sim, "obs": obs}).dropna()
df.index = pd.to_datetime(df.index)
s, o = df["sim"].to_numpy(), df["obs"].to_numpy()
r = float(np.corrcoef(s, o)[0, 1])
alpha, beta = float(s.std() / o.std()), float(s.mean() / o.mean())
kge = 1 - float(np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2))
nse = 1 - float(((s - o) ** 2).sum() / ((o - o.mean()) ** 2).sum())
rmse = float(np.sqrt(((s - o) ** 2).mean()))
bias = float((s - o).mean())

fig = make_subplots(
    rows=2,
    cols=1,
    shared_xaxes=True,
    row_heights=[0.72, 0.28],
    vertical_spacing=0.06,
    subplot_titles=("Niveau du reservoir : observe vs simule", "Residu (simule - observe)"),
)
fig.add_trace(
    go.Scatter(
        x=df.index,
        y=o,
        name="observe",
        mode="lines",
        line=dict(color="#111827", width=2),
        hovertemplate="%{x|%Y-%m-%d}<br>obs %{y:.2f} m<extra></extra>",
    ),
    row=1,
    col=1,
)
fig.add_trace(
    go.Scatter(
        x=df.index,
        y=s,
        name="simule",
        mode="lines",
        line=dict(color="#2563eb", width=2),
        hovertemplate="%{x|%Y-%m-%d}<br>sim %{y:.2f} m<extra></extra>",
    ),
    row=1,
    col=1,
)
for lvl, label, dash in [(SPILLWAY, "deversoir 87.57", "dot"), (SILL, "seuil 86.93", "dash")]:
    fig.add_hline(
        y=lvl,
        line=dict(color="#9ca3af", width=1, dash=dash),
        annotation_text=label,
        annotation_position="right",
        row=1,
        col=1,
    )
fig.add_trace(
    go.Scatter(
        x=df.index,
        y=s - o,
        name="residu",
        mode="lines",
        line=dict(color="#dc2626", width=1),
        fill="tozeroy",
        fillcolor="rgba(220,38,38,0.15)",
        hovertemplate="%{x|%Y-%m-%d}<br>residu %{y:+.2f} m<extra></extra>",
    ),
    row=2,
    col=1,
)
fig.add_hline(y=0, line=dict(color="#9ca3af", width=1), row=2, col=1)

title = (
    f"Cheze reservoir - calage niveau (KGE={kge:.3f}, NSE={nse:.3f}, "
    f"RMSE={rmse:.2f} m, biais={bias:+.2f} m)  |  {df.index.min():%Y-%m-%d} -> {df.index.max():%Y-%m-%d}, "
    f"{len(df)} jours"
)
fig.update_layout(
    title=dict(text=title, font=dict(size=15)),
    template="plotly_white",
    hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    margin=dict(l=60, r=90, t=90, b=40),
)
fig.update_yaxes(title_text="niveau (m NGF)", row=1, col=1)
fig.update_yaxes(title_text="sim - obs (m)", row=2, col=1)
fig.update_xaxes(rangeslider=dict(visible=True, thickness=0.05), row=2, col=1)

fig.write_html(OUT, include_plotlyjs="inline", full_html=True)
print(f"KGE={kge:.3f} NSE={nse:.3f} RMSE={rmse:.2f}m bias={bias:+.2f}m on {len(df)} days")
print(f"HTML ecrit : {OUT}")
