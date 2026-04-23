"""HTML report renderer for one calibration session.

Reads every calibration figure registered under
``hydromodpy.display.figures.calibration_*``, renders each one into a
PNG under ``<workspace>/reports/<session_id>/figures/``, and assembles
a self-contained ``report.html`` that embeds the PNGs + the session
metadata table.

The report is intentionally static — no JS, no external fonts, no CDN.
It opens offline from the workspace directory.
"""

from __future__ import annotations

import html
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hydromodpy.results.catalog import SimulationCatalog

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def render_session_report(
    *,
    catalog: SimulationCatalog,
    session_id: str,
    workspace_root: Path,
) -> Path:
    """Render an HTML report summarising one calibration session.

    Returns the path to the generated ``report.html``. Figures that
    fail to render are skipped with a warning so the report always
    produces output even on partial data.
    """
    session_row = _load_session(catalog, session_id)
    iterations = _load_iterations(catalog, session_id)

    out_dir = Path(workspace_root) / "reports" / session_id
    figures_dir = out_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    rendered: list[tuple[str, Path]] = _render_figures(
        catalog=catalog,
        session_id=session_id,
        iterations=iterations,
        figures_dir=figures_dir,
    )

    html_path = out_dir / "report.html"
    html_path.write_text(
        _render_html(session_row, iterations, rendered),
        encoding="utf-8",
    )
    logger.info("calibration report: %d figure(s) under %s", len(rendered), html_path)
    return html_path


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _load_session(catalog: SimulationCatalog, session_id: str) -> dict:
    import uuid

    sid = uuid.UUID(session_id) if len(session_id) == 32 else session_id
    row = catalog.connection.execute(
        """
        SELECT session_id, project, method, objective_name,
               n_iterations, config, started_at, ended_at, status,
               best_sim_id, best_objective, duration_s
          FROM calibration_sessions
         WHERE session_id = ?
        """,
        [sid],
    ).fetchone()
    if row is None:
        raise ValueError(f"Unknown calibration session {session_id!r}")
    keys = (
        "session_id",
        "project",
        "method",
        "objective_name",
        "n_iterations",
        "config",
        "started_at",
        "ended_at",
        "status",
        "best_sim_id",
        "best_objective",
        "duration_s",
    )
    return dict(zip(keys, row, strict=False))


def _load_iterations(catalog: SimulationCatalog, session_id: str) -> list[dict]:
    from hydromodpy.calibration.persistence import CalibrationPersistence

    return CalibrationPersistence(catalog).load_iterations(session_id)


# ---------------------------------------------------------------------------
# Figure rendering
# ---------------------------------------------------------------------------


_CALIBRATION_FIGURES: tuple[str, ...] = (
    "calibration_convergence",
    "calibration_trace",
    "calibration_landscape",
    "calibration_posterior",
    "calibration_objective_surface",
    "calibration_pairplot",
)


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
        self.sim_id = session_id  # used by some figures as an identifier

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
    catalog: SimulationCatalog,  # noqa: ARG001
    session_id: str,
    iterations: list[dict],
    figures_dir: Path,
) -> list[tuple[str, Path]]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from hydromodpy.display import get as get_figure
    from hydromodpy.display import names as figure_names

    registered = set(figure_names())
    run_stub = _SessionRunStub(session_id, iterations)
    rendered: list[tuple[str, Path]] = []
    for figure_name in _CALIBRATION_FIGURES:
        if figure_name not in registered:
            logger.debug("skip %s (not registered)", figure_name)
            continue
        out_path = figures_dir / f"{figure_name}.png"
        try:
            fig_cls = get_figure(figure_name)
            fig_cls.plot(run_stub, save_path=out_path, session_id=session_id)
        except Exception as exc:
            logger.warning("%s failed: %s", figure_name, exc)
            plt.close("all")
            continue
        plt.close("all")
        if out_path.exists():
            rendered.append((figure_name, out_path))
    return rendered


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
    s = str(value).replace("-", "")
    return s


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


__all__ = ("render_session_report",)
