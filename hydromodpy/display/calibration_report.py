"""HTML report rendering for one calibration session.

Consumes the structural payload produced by
:func:`hydromodpy.calibration.report.load_session_report_data` and turns
it into a self-contained HTML report inside the session directory it
describes: ``sessions/<session>/report/index.html``, its figures under
``sessions/<session>/figures/``. Renders the six calibration figures
registered in :mod:`hydromodpy.display.figures` plus the sim-vs-obs figures of
the promoted best run when there is one.

The HTML is static: no JS, no external fonts, no CDN. It opens offline from the
workspace directory. The input is described locally by
:class:`SessionReportPayload`, a structural Protocol, because this module does
not import calibration.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

import pandas as pd

from hydromodpy.core.config_kit.stored import read_stored
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.layout import sessions_dir_for
from hydromodpy.display.figure_registry import get as _get_figure
from hydromodpy.display.figure_registry import names as _figure_names
from hydromodpy.display.report_blocks import (
    ReportBlock,
    ReportFigure,
    ReportTable,
    key_value_table,
    write_report_page,
)
from hydromodpy.display.runs import matplotlib_backend
from hydromodpy.results.checks import stop_line
from hydromodpy.results.run.view import open_run_dir
from hydromodpy.results.session.descriptor import (
    ScoredSamples,
    read_session,
    scored_samples_text,
)
from hydromodpy.results.storage.contract import (
    REPORT_INDEX_FILENAME,
    RUN_FIGURES_DIRNAME,
    RUN_REPORT_DIRNAME,
)

if TYPE_CHECKING:
    from hydromodpy.results.run.view import Run

logger = get_logger(__name__)

PREVIEW_ROWS = 20
"""Trials listed at the end of the page."""


class SessionReportPayload(Protocol):
    """What :func:`render_session` reads of ``calibration.report.SessionReportData``."""

    @property
    def session_id(self) -> str: ...

    @property
    def session_name(self) -> str: ...

    @property
    def session(self) -> dict[str, Any]: ...

    @property
    def iterations(self) -> list[dict[str, Any]]: ...

    @property
    def workspace_root(self) -> Path: ...

    @property
    def best_rel_dir(self) -> str | None: ...

    @property
    def variable(self) -> str: ...


_DEFAULT_FIGURE_NAMES: tuple[str, ...] = (
    "calibration_convergence",
    "calibration_trace",
    "calibration_landscape",
    "calibration_trial_distribution",
    "calibration_objective_surface",
    "calibration_pairplot",
)

_BEST_RUN_FIGURES: dict[str, tuple[str, ...]] = {
    "lake_level": ("lake_stage_sim_obs",),
    "discharge": ("hydrograph_sim_obs", "scatter_one_to_one"),
}
"""Figures of the promoted best run, by calibrated variable."""


def render_session(
    session_data: SessionReportPayload,
    *,
    figure_names: list[str] | tuple[str, ...] | None = None,
    session_dir: Path | None = None,
) -> list[Path]:
    """Render a calibration-session HTML report.

    Parameters
    ----------
    session_data
        Payload produced by
        :func:`hydromodpy.calibration.report.load_session_report_data`,
        accepted structurally as :class:`SessionReportPayload`.
    figure_names
        Iterable of registered figure names to render. Defaults to the
        six built-in ``calibration_*`` figures.
    session_dir
        The session directory the report describes. Defaults to
        ``sessions/<session_name>`` of ``session_data.workspace_root``.

    Returns
    -------
    list[Path]
        Paths of files written: each rendered figure PNG under
        ``figures/`` followed by ``report/index.html``. Empty figure list
        still produces the HTML.
    """
    requested = tuple(figure_names) if figure_names is not None else _DEFAULT_FIGURE_NAMES
    directory = (
        Path(session_dir)
        if session_dir is not None
        else sessions_dir_for(session_data.workspace_root) / session_data.session_name
    )
    figures_dir = directory / RUN_FIGURES_DIRNAME
    figures_dir.mkdir(parents=True, exist_ok=True)

    stub = _SessionRunStub(session_data.iterations, session_data.session_id)
    options = {"session_id": session_data.session_id, "roots": _two_roots(directory)}
    with matplotlib_backend():
        rendered = _render_figures(cast("Run", stub), requested, figures_dir, options)
        if session_data.best_rel_dir is not None:
            names = _BEST_RUN_FIGURES.get(session_data.variable, _BEST_RUN_FIGURES["discharge"])
            best = _open_best_run(session_data.workspace_root / session_data.best_rel_dir)
            rendered += _render_figures(best, names, figures_dir, {})

    html_path = directory / RUN_REPORT_DIRNAME / REPORT_INDEX_FILENAME
    session_id = _bare(session_data.session.get("session_id"))
    write_report_page(
        output_path=html_path,
        title=f"Calibration session {session_id[:8]}",
        subtitle=session_id,
        blocks=_blocks(session_data.session, session_data.iterations, rendered),
    )
    logger.info("calibration report: %d figure(s) under %s", len(rendered), html_path)
    return [*(path for _, path in rendered), html_path]


class _SessionRunStub:
    """Minimal ``Run``-shaped adapter so registered figures can read the trial rows.

    The calibration figures read ``sim.calibration_iterations`` and the cost
    series ``sim.timeseries(name, station=...)``. The rows stay as the journal
    wrote them: flattening here would be a second convention beside the one the
    figures apply, and the cost panel would be labeled differently from a
    promoted run.
    """

    def __init__(self, iterations: list[dict], session_id: str) -> None:
        self.calibration_iterations = list(iterations)
        self.name = f"calibration_{session_id[:8]}"
        self.sim_id = session_id

    def timeseries(self, variable: str, station: str | None = None) -> pd.DataFrame:  # noqa: ARG002
        costs = pd.to_numeric(
            pd.Series([row.get("cost") for row in self.calibration_iterations]), errors="coerce"
        )
        return pd.DataFrame({variable: costs.to_numpy()}, index=pd.RangeIndex(len(costs)))


def _two_roots(session_dir: Path) -> Mapping[str, Any] | None:
    """Return the two roots the session journalled, or None.

    Only ``session.json`` holds them: the trials carry each bound's bracket,
    not ``Delta`` nor the combined value.
    """
    roots = (read_session(session_dir).root_search or {}).get("roots")
    return roots if isinstance(roots, Mapping) else None


def _open_best_run(run_dir: Path) -> Run | None:
    """Open the promoted run, or return None and say why the page goes without it."""
    try:
        return open_run_dir(run_dir)
    except Exception as exc:
        logger.warning("calibration report: best run not opened (%s)", exc)
        return None


def _render_figures(
    run: Run | None,
    names: tuple[str, ...],
    figures_dir: Path,
    options: Mapping[str, Any],
) -> list[tuple[str, Path]]:
    """Draw each registered figure of *names* from *run*; a figure that fails is skipped."""
    if run is None:
        return []
    registered = set(_figure_names())
    rendered: list[tuple[str, Path]] = []
    failures: list[str] = []
    for name in names:
        out_path = figures_dir / f"{name}.png"
        if name not in registered:
            failures.append(f"{name}: figure is not registered")
            continue
        try:
            _get_figure(name).plot(run, save_path=out_path, **options)
        except Exception as exc:
            failures.append(f"{name}: {exc}")
            continue
        if out_path.exists():
            rendered.append((name, out_path))
        else:
            failures.append(f"{name}: no output file was written")
    if failures:
        # A figure that does not fit this session (too few parameters, a
        # degenerate surface, a run with no gauge) is skipped, not fatal: the
        # report still shows every figure that did succeed.
        logger.warning(
            "calibration report: skipped %d figure(s): %s", len(failures), "; ".join(failures)
        )
    return rendered


def _blocks(
    session: dict, iterations: list[dict], rendered: list[tuple[str, Path]]
) -> list[ReportBlock]:
    shown = iterations[:PREVIEW_ROWS]
    trials = ReportTable(
        table_id="trials",
        title="",
        columns=(
            ("trial", "Trial"),
            ("cost", "Cost"),
            ("status", "Status"),
            ("parameters", "Parameters"),
        ),
        rows=tuple(
            {
                "trial": row.get("trial"),
                "cost": f"{row['cost']:.6g}" if row.get("cost") is not None else "nan",
                "status": row.get("status"),
                "parameters": json.dumps(row.get("parameters", {}), default=str, sort_keys=True),
            }
            for row in shown
        ),
        empty_message="No iterations.",
    )
    more = len(iterations) - len(shown)
    return [
        ReportBlock(
            "summary",
            "Summary",
            tables=(key_value_table("session", "", session_summary(session)),),
        ),
        ReportBlock(
            "figures",
            "Figures",
            lead="" if rendered else "No figures rendered.",
            figures=tuple(ReportFigure(name, name, path) for name, path in rendered),
        ),
        ReportBlock(
            "trials",
            f"Iteration trace (first {PREVIEW_ROWS} rows)",
            lead=f"{more} more rows not shown." if more > 0 else "",
            tables=(trials,),
        ),
    ]


def session_summary(session: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Return the label and the text of each summary row of a session."""
    rows: list[tuple[str, str]] = []
    for key in (
        "project",
        "method",
        "cost_name",
        "status",
        "stop_state",
        "stop_note",
        "n_trials",
        "best_cost",
        "best_sim_id",
        "started_at",
        "ended_at",
        "duration_s",
    ):
        value = session.get(key)
        if value is None:
            continue
        if key == "stop_state":
            rows.append(("search stopped", stop_line(value, session.get("stopping_rule"))))
            continue
        if key == "best_sim_id":
            value = _bare(value)
        if key == "best_cost" and session.get("cost_label"):
            # A cost of 0.08 on an NSE reads as a poor score; the label says it is 1 - NSE.
            value = f"{value} ({session['cost_label']})"
        rows.append((key, str(value)))
        if key == "best_cost" and (scored := _scored_on(session)):
            rows.append(("scored on", scored))
    return rows


def _scored_on(session: Mapping[str, Any]) -> str | None:
    """Return the pairs the best cost was scored on, and the window the session declares."""
    windows = session.get("windows") or {}
    window = next(iter(windows.values()), None)
    declared = f"window {window['start']} to {window['end']}" if window else None
    samples = [read_stored(ScoredSamples, payload) for payload in session.get("scored") or ()]
    if samples:
        text = f"{scored_samples_text(samples)}, best trial"
        return text + (f" ({declared})" if declared else "")
    if declared:
        return f"{declared}, pairs not counted"
    return None


def _bare(session_id: Any) -> str:
    """Return an id as bare hex, whichever way the journal wrote it."""
    return "" if session_id is None else str(session_id).replace("-", "")


__all__ = ("SessionReportPayload", "render_session", "session_summary")
