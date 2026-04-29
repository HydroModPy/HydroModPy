"""HTML report rendering for one calibration session.

Consumes the data dataclass produced by
:func:`hydromodpy.calibration.report.load_session_report_data` and
turns it into a self-contained HTML report at
``<workspace>/reports/<session_id>/report.html``. Renders the six
calibration figures registered in :mod:`hydromodpy.display.figures`
plus a best-run obs-vs-sim panel when a promoted run is available.

The HTML is intentionally static - no JS, no external fonts, no CDN.
It opens offline from the workspace directory.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.core.logging import get_logger
from hydromodpy.display.catalog import get as _get_figure
from hydromodpy.display.catalog import names as _figure_names

if TYPE_CHECKING:
    import pandas as pd

    from hydromodpy.calibration.report import SessionReportData

logger = get_logger(__name__)


_DEFAULT_FIGURE_NAMES: tuple[str, ...] = (
    "calibration_convergence",
    "calibration_trace",
    "calibration_landscape",
    "calibration_posterior",
    "calibration_objective_surface",
    "calibration_pairplot",
)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def render_session(
    session_data: SessionReportData,
    *,
    figure_names: list[str] | tuple[str, ...] | None = None,
    output_dir: Path | None = None,
) -> list[Path]:
    """Render a calibration-session HTML report.

    Parameters
    ----------
    session_data
        Dataclass produced by
        :func:`hydromodpy.calibration.report.load_session_report_data`.
    figure_names
        Iterable of registered figure names to render. Defaults to the
        six built-in ``calibration_*`` figures.
    output_dir
        Directory the report is written into. Defaults to
        ``<session_data.workspace_root>/reports/<session_id>``.

    Returns
    -------
    list[Path]
        Paths of files written: each rendered figure PNG followed by
        ``report.html``. Empty figure list still produces the HTML.
    """
    requested = tuple(figure_names) if figure_names is not None else _DEFAULT_FIGURE_NAMES
    out_dir = (
        Path(output_dir)
        if output_dir is not None
        else session_data.workspace_root / "reports" / session_data.session_id
    )
    figures_dir = out_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    rendered: list[tuple[str, Path]] = _render_figures(
        session_id=session_data.session_id,
        iterations=session_data.iterations,
        figure_names=requested,
        figures_dir=figures_dir,
    )
    written.extend(path for _, path in rendered)

    if session_data.best_sim_id is not None:
        obs_vs_sim_path = _render_best_obs_vs_sim(
            sim_id=session_data.best_sim_id,
            sim_df=session_data.sim_timeseries,
            obs_df=session_data.obs_timeseries,
            figures_dir=figures_dir,
        )
        if obs_vs_sim_path is not None:
            rendered.append(("best_obs_vs_sim", obs_vs_sim_path))
            written.append(obs_vs_sim_path)

    html_path = out_dir / "report.html"
    html_path.write_text(
        _render_html(session_data.session, session_data.iterations, rendered),
        encoding="utf-8",
    )
    written.append(html_path)
    logger.info("calibration report: %d figure(s) under %s", len(rendered), html_path)
    return written


# ---------------------------------------------------------------------------
# Figure rendering
# ---------------------------------------------------------------------------


class _SessionRunStub:
    """Minimal ``Run``-shaped adapter so registered figures can read iterations.

    The catalog-aware figures in ``hydromodpy/display/figures`` expect a
    ``sim.calibration_iterations`` attribute and optionally a
    ``sim.timeseries(variable, station=...)`` method. This stub supplies
    both from the loaded ``iterations`` list without going through the
    full ``Run`` stack (no Zarr, no sim_id needed).
    """

    def __init__(self, session_id: str, iterations: list[dict]) -> None:
        self.session_id = session_id
        self._iterations = iterations
        self.name = f"calibration_{session_id[:8]}"
        self.sim_id = session_id

    @property
    def calibration_iterations(self) -> list[dict]:
        return self._iterations

    def timeseries(self, variable: str, station: str | None = None):  # noqa: ARG002
        import pandas as pd

        values = [row["objective_value"] for row in self._iterations]
        idx = pd.RangeIndex(len(values), name="iteration")
        return pd.DataFrame({variable: values}, index=idx)


def _render_figures(
    *,
    session_id: str,
    iterations: list[dict],
    figure_names: tuple[str, ...],
    figures_dir: Path,
) -> list[tuple[str, Path]]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    registered = set(_figure_names())
    run_stub = _SessionRunStub(session_id, iterations)
    rendered: list[tuple[str, Path]] = []
    for figure_name in figure_names:
        if figure_name not in registered:
            logger.debug("skip %s (not registered)", figure_name)
            continue
        out_path = figures_dir / f"{figure_name}.png"
        try:
            fig_cls = _get_figure(figure_name)
            fig_cls.plot(run_stub, save_path=out_path, session_id=session_id)
        except Exception as exc:
            logger.warning("%s failed: %s", figure_name, exc)
            plt.close("all")
            continue
        plt.close("all")
        if out_path.exists():
            rendered.append((figure_name, out_path))
    return rendered


def _render_best_obs_vs_sim(
    *,
    sim_id: str,
    sim_df: pd.DataFrame | None,
    obs_df: pd.DataFrame | None,
    figures_dir: Path,
) -> Path | None:
    """Plot observed vs simulated discharge for the best promoted run.

    The simulated column already includes the ``DRN + runoff``
    aggregation. The figure shows a time-series panel and a 1:1 scatter
    side by side, in m³/s, restricted to the simulation window.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    import pandas as pd

    if sim_df is None or sim_df.empty:
        logger.warning("best_obs_vs_sim: no simulated discharge for sim %s", sim_id)
        return None
    if obs_df is None or obs_df.empty:
        logger.warning("best_obs_vs_sim: no observed discharge for sim %s", sim_id)
        return None

    sim = pd.Series(sim_df["value"].values, index=pd.DatetimeIndex(sim_df["datetime"]))
    obs = pd.Series(obs_df["value"].values, index=pd.DatetimeIndex(obs_df["datetime"]))
    if sim.index.tz is not None:
        sim = sim.tz_localize(None)
    if obs.index.tz is not None:
        obs = obs.tz_localize(None)

    sim = sim.sort_index()
    obs = obs.sort_index()
    obs_daily = obs.loc[sim.index.min() : sim.index.max()]

    obs_binned = _bin_obs_to_sim_index(obs_daily, sim.index)

    out_path = figures_dir / "best_obs_vs_sim.png"
    fig, (ax_ts, ax_sc) = plt.subplots(
        1, 2, figsize=(11, 4), dpi=150, gridspec_kw={"width_ratios": [3, 1]}
    )

    if not obs_daily.empty:
        ax_ts.plot(
            obs_daily.index,
            obs_daily.values,
            color="lightgray",
            lw=0.6,
            label="Observed (daily)",
        )
    if not obs_binned.empty:
        ax_ts.plot(
            obs_binned.index,
            obs_binned.values,
            color="black",
            lw=1.6,
            label="Observed (mean over stress period)",
        )
    ax_ts.plot(sim.index, sim.values, color="firebrick", lw=1.6, label="Simulated (DRN+runoff)")
    ax_ts.set_ylabel("Discharge [m³/s]")
    ax_ts.set_title(f"Best run vs observation - sim_id={sim_id[:8]}")
    ax_ts.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax_ts.legend(fontsize=9)
    ax_ts.grid(alpha=0.3)

    paired = pd.concat([obs_binned.rename("obs"), sim.rename("sim")], axis=1).dropna()
    if not paired.empty:
        ax_sc.scatter(
            paired["obs"], paired["sim"], s=18, alpha=0.7, color="forestgreen", edgecolor="none"
        )
        lo = float(min(paired["obs"].min(), paired["sim"].min()))
        hi = float(max(paired["obs"].max(), paired["sim"].max()))
        ax_sc.plot([lo, hi], [lo, hi], color="grey", lw=0.8, zorder=-1)
        ax_sc.set_xlabel("Obs [m³/s]")
        ax_sc.set_ylabel("Sim [m³/s]")
        ax_sc.set_title("1:1 (period-mean obs vs sim)")
        ax_sc.grid(alpha=0.3)
    else:
        ax_sc.set_axis_off()

    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path


def _bin_obs_to_sim_index(obs, sim_index):
    """Average daily observations into bins centered on simulation timestamps.

    Each simulation timestamp ``t`` covers ``[t - dt/2, t + dt/2)`` where
    ``dt`` is the median sim step. Falls back to a nearest-reindex when
    the obs sampling is not finer than the sim sampling.
    """
    import pandas as pd

    if obs.empty or len(sim_index) < 2:
        return obs.copy()

    sim_index = sim_index.sort_values()
    sim_step = pd.Timedelta(sim_index.to_series().diff().dropna().median())
    obs_step = pd.Timedelta(obs.index.to_series().diff().dropna().median())
    if sim_step <= obs_step:
        return obs.reindex(sim_index, method="nearest", tolerance=sim_step)

    half = sim_step / 2
    bin_edges = pd.DatetimeIndex([sim_index[0] - half] + [t + half for t in sim_index])
    binned_keys = pd.cut(obs.index, bins=bin_edges, right=False)
    obs_aligned = obs.groupby(binned_keys, observed=True).mean()
    obs_aligned.index = sim_index[: len(obs_aligned)]
    return obs_aligned


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------


_HTML_TEMPLATE = """\
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Calibration session {session_short}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
            margin: 2rem auto; max-width: 1100px; color: #222; }}
    h1 {{ margin-bottom: 0.2rem; }}
    .meta {{ color: #666; margin-bottom: 2rem; font-size: 0.95em; }}
    table.summary {{ border-collapse: collapse; margin-bottom: 2rem; font-size: 0.9em; }}
    table.summary th, table.summary td {{ padding: 0.3rem 0.8rem; border: 1px solid #ddd;
                                          text-align: left; vertical-align: top; }}
    table.summary th {{ background: #f6f6f6; font-weight: 600; }}
    .figure {{ margin-bottom: 2.5rem; }}
    .figure h2 {{ font-size: 1.1em; margin: 0 0 0.4rem 0; }}
    .figure img {{ max-width: 100%; border: 1px solid #eee; background: white; }}
    .iterations-preview {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
                            font-size: 0.85em; white-space: pre-wrap; background: #fafafa;
                            padding: 1rem; border: 1px solid #eee; overflow-x: auto; }}
  </style>
</head>
<body>
  <h1>Calibration session</h1>
  <div class="meta"><code>{session_id}</code></div>

  <table class="summary">
    <tbody>
      {summary_rows}
    </tbody>
  </table>

  {figures_html}

  <h2>Iteration trace (first 20 rows)</h2>
  <div class="iterations-preview">{iterations_preview}</div>
</body>
</html>
"""


def _render_html(
    session: dict,
    iterations: list[dict],
    rendered_figures: list[tuple[str, Path]],
) -> str:
    session_id = _hex(session.get("session_id"))

    rows_html = []
    for key in (
        "project",
        "method",
        "objective_name",
        "status",
        "n_iterations",
        "best_objective",
        "best_sim_id",
        "started_at",
        "ended_at",
        "duration_s",
    ):
        value = session.get(key)
        if value is None:
            continue
        if key == "best_sim_id":
            value = _hex(value)
        rows_html.append(f"<tr><th>{html.escape(key)}</th><td>{html.escape(str(value))}</td></tr>")
    summary_rows = "\n      ".join(rows_html)

    figure_blocks = []
    for name, path in rendered_figures:
        figure_blocks.append(
            f'<section class="figure">'
            f"<h2>{html.escape(name)}</h2>"
            f'<img src="figures/{path.name}" alt="{html.escape(name)}"></section>'
        )
    figures_html = "\n  ".join(figure_blocks) or "<p><em>No figures rendered.</em></p>"

    preview = _format_iterations_preview(iterations)

    return _HTML_TEMPLATE.format(
        session_id=html.escape(session_id),
        session_short=html.escape(session_id[:8]),
        summary_rows=summary_rows,
        figures_html=figures_html,
        iterations_preview=html.escape(preview),
    )


def _hex(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "hex"):
        return value.hex
    return str(value).replace("-", "")


def _format_iterations_preview(iterations: list[dict], limit: int = 20) -> str:
    lines = []
    for row in iterations[:limit]:
        params = row.get("parameters", {})
        obj = row.get("objective_value")
        obj_str = "nan" if obj is None else f"{obj:.6g}"
        params_str = json.dumps(params, default=str, sort_keys=True)
        lines.append(
            f"iter {row.get('iteration'):>4}  "
            f"obj={obj_str:>12}  "
            f"status={row.get('status'):<10}  "
            f"{params_str}"
        )
    if len(iterations) > limit:
        lines.append(f"... ({len(iterations) - limit} more rows)")
    return "\n".join(lines) or "(no iterations)"


__all__ = ("render_session",)
