"""The reports of a sealed run and of a calibration session.

What
----
:func:`report_run` writes the report page of a sealed run, and
:func:`report_session` the page of a calibration session. This is the one place
that joins the text (method, label, sheet titles, all read from ``phrases.toml``)
to the page engine of :mod:`hydromodpy.display.report`, which writes no phrase of
its own.

Why
---
A report reads what is on disk. It runs no model: ``hmp run`` does that. A session
report never writes the journal (``session.json``, ``trials.jsonl``,
``trial_series/``), so playing it again does not change what a reference reads.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from hydromodpy.core.exceptions import ConfigError, DisplayError
from hydromodpy.core.logging import get_logger
from hydromodpy.display.figure_registry import get as get_figure
from hydromodpy.display.figure_registry import names as figure_names
from hydromodpy.display.overview.location import overview_run_dir
from hydromodpy.display.report.engine import write_pages
from hydromodpy.display.report.pages import (
    draw_named_figures,
    run_blocks,
    session_blocks,
    sheet_blocks,
)
from hydromodpy.display.report.presets import PRESETS, ReportTexts, preset_figures
from hydromodpy.results.method import label_text, method_text
from hydromodpy.results.record.label import label_of
from hydromodpy.results.record.manifest import is_sealed, read_seal
from hydromodpy.results.run.view import open_run_dir
from hydromodpy.results.session.summary import session_summary, summary_rows
from hydromodpy.results.session.view import Session
from hydromodpy.results.storage.contract import (
    RUN_FIGURES_DIRNAME,
    RUN_REPORT_DIRNAME,
)
from hydromodpy.schema.phrases import Lang, keys, phrase

logger = get_logger(__name__)

SESSION_FIGURES: tuple[str, ...] = (
    "calibration_convergence",
    "calibration_trace",
    "calibration_landscape",
    "calibration_trial_distribution",
    "calibration_objective_surface",
    "calibration_pairplot",
)
"""The figures of the session itself, drawn under ``sessions/<s>/figures/``."""

BEST_RUN_FIGURES: dict[str, tuple[str, ...]] = {
    "lake_level": ("lake_stage_sim_obs",),
    "discharge": ("hydrograph_sim_obs", "scatter_one_to_one"),
}
"""Figures of the promoted best run, by calibrated variable."""


def report_run(
    run_dir: str | Path,
    *,
    preset: str = "research",
    lang: Lang = "en",
    overview_dir: str | Path | None = None,
    station: str | None = None,
    strict: bool = False,
    today: date | None = None,
) -> Path:
    """Write the report of the sealed run at *run_dir* and return its first page.

    ``research`` writes ``report/`` with three levels. ``management`` writes the
    one-page sheet ``report/sheet-<lang>/index.html``. Figures the preset names
    and the run lacks are drawn from the ``[display]`` the run sealed. The view of
    the data is the overview of the same site, looked for next to the run unless
    *overview_dir* names it.

    Raises
    ------
    ConfigError
        When the run is not sealed, the preset is unknown, or *overview_dir* is
        the overview of another site.
    DisplayError
        With ``strict=True``, when a required figure is missing after the pages
        are written.
    """
    directory = Path(run_dir)
    if preset not in PRESETS:
        raise ConfigError(f"preset {preset!r} is not one of {', '.join(sorted(PRESETS))}")
    if not is_sealed(directory):
        raise ConfigError(f"run {directory.name} is not sealed; a report reads a sealed run")
    day = datetime.now(UTC).date() if today is None else today
    chosen = PRESETS[preset]
    run = open_run_dir(directory)
    overview = _overview_of(run, directory, overview_dir)

    label = label_of(read_seal(directory), directory)
    titles = {key: phrase("report", key, lang) for key in keys("report")}
    texts = ReportTexts(
        method=method_text(directory, lang=lang, today=day),
        label=label_text(label, lang=lang, today=day),
        titles=titles,
    )

    # The figures are drawn on the Agg backend of the display renderer, which
    # keeps its own scope; the report itself changes no global matplotlib state.
    draw_named_figures(run, preset_figures(chosen))
    if preset == "management":
        out = directory / RUN_REPORT_DIRNAME / f"sheet-{lang}"
        blocks = sheet_blocks(run, texts=texts, station=station)
    else:
        out = directory / RUN_REPORT_DIRNAME
        blocks = run_blocks(run, overview=overview, texts=texts, station=station, preset=chosen)
    page = write_pages(
        out,
        title=f"{run.name or directory.name}",
        subtitle=str(run.site or ""),
        blocks=blocks,
        levels=chosen.levels,
        lang=lang,
        label=label.label,
        rendered=day,
        preset=preset,
        words={
            "eyebrow": titles["page_eyebrow"],
            "contents": titles["page_contents"],
            "figure_missing": titles["figure_missing"],
        },
    )
    missing = json.loads((out / "report.json").read_text(encoding="utf-8")).get("missing", [])
    if strict and missing:
        raise DisplayError(
            f"report of run {directory.name} misses required figure(s): {', '.join(missing)}"
        )
    return page


def report_session(session_dir: str | Path, *, today: date | None = None) -> Path:
    """Write ``sessions/<s>/report/`` and ``sessions/<s>/figures/``, return the first page.

    The six ``calibration_*`` figures are drawn from the session, and the figures of the
    promoted best run of each case. A figure that does not fit this session (too
    few parameters, a degenerate surface, a run with no gauge) is skipped with its reason
    in the log. A best run that does not open is named in the table of the cases, with
    the reason, and the page is written without its figures. Nothing the journal holds
    is written.
    """
    directory = Path(session_dir)
    day = datetime.now(UTC).date() if today is None else today
    session = Session(directory)
    summary = session_summary(session)
    figures_dir = directory / RUN_FIGURES_DIRNAME
    figures_dir.mkdir(parents=True, exist_ok=True)

    skipped: list[str] = []
    drawn = _draw(session, SESSION_FIGURES, figures_dir, skipped)
    names = BEST_RUN_FIGURES.get(summary.calibrated_variable, BEST_RUN_FIGURES["discharge"])
    cases, best_runs = _cases(session)
    best_figures: list[Path] = []
    for case_id, best in best_runs.items():
        prefix = "" if len(cases) == 1 else f"{case_id}_"
        best_figures += _draw(best, names, figures_dir, skipped, prefix=prefix).values()
    if skipped:
        # A skipped figure is no failure: the page shows every figure that did draw.
        logger.warning("session report: skipped %d figure(s): %s", len(skipped), "; ".join(skipped))
    descriptor = session.descriptor
    return write_pages(
        directory / RUN_REPORT_DIRNAME,
        title=f"Calibration session {session.name}",
        subtitle=descriptor.session_id,
        blocks=session_blocks(
            session,
            summary_rows=summary_rows(summary),
            figures=list(drawn.values()),
            cases=cases,
            best_figures=best_figures,
        ),
        levels=PRESETS["research"].levels,
        lang="en",
        rendered=day,
        preset="research",
    )


def _overview_of(run: object, run_dir: Path, overview_dir: str | Path | None) -> object | None:
    """Return the overview run of the same site, or None when there is none."""
    site = getattr(run, "site", None)
    if overview_dir is None:
        if site is None or run_dir.parent.name != "runs":
            return None
        found = overview_run_dir(run_dir.parent.parent, str(site))
        return open_run_dir(found) if is_sealed(found) else None
    chosen = Path(overview_dir)
    if not is_sealed(chosen):
        raise ConfigError(f"overview {chosen.name} is not sealed; give the run of hmp run")
    overview = open_run_dir(chosen)
    if site is not None and overview.site != site:
        raise ConfigError(
            f"overview {chosen.name} is the overview of site {overview.site}, "
            f"and run {run_dir.name} is of site {site}"
        )
    return overview


def _cases(session: Session) -> tuple[list[dict[str, str]], dict[str, object]]:
    """Return one row per case of the session and the best run of each case that opens.

    A best run that does not open is no failure: its row says why, and the page
    goes on without its figures.
    """
    sites = {case_id: case.site for case_id, case in session.descriptor.cases.items()}
    note = ""
    try:
        runs = session.best_by_case
    except Exception as exc:  # an unreadable best run: the page says why and goes on
        logger.warning("session report: best run of %s not opened (%s)", session.name, exc)
        runs, note = {}, f"best run not opened: {exc}"
    rows = [
        {
            "case": case_id,
            "site": str(site or ""),
            "best_run": "" if runs.get(case_id) is None else str(runs[case_id].name),
            "note": note
            or ("" if runs.get(case_id) is not None else "no best run held for this case"),
        }
        for case_id, site in sites.items()
    ]
    return rows, {case_id: run for case_id, run in runs.items() if run is not None}


def _draw(
    subject: object,
    names: tuple[str, ...],
    figures_dir: Path,
    skipped: list[str],
    *,
    prefix: str = "",
) -> dict[str, Path]:
    """Draw each registered figure of *names* from *subject*; a figure that fails is skipped.

    Each figure is closed once saved, so no figure stays in the pyplot registry.
    """
    import matplotlib.pyplot as plt

    registered = set(figure_names())
    drawn: dict[str, Path] = {}
    for name in names:
        target = figures_dir / f"{prefix}{name}.png"
        if name not in registered:
            skipped.append(f"{name}: figure is not registered")
            continue
        try:
            figure = get_figure(name).plot(subject, save_path=target)
        except Exception as exc:  # the figure says why it does not fit; the report goes on
            skipped.append(f"{name}: {exc}")
            continue
        if figure is not None:
            plt.close(figure)
        if target.exists():
            drawn[name] = target
        else:
            skipped.append(f"{name}: no output file was written")
    return drawn


__all__ = (
    "BEST_RUN_FIGURES",
    "SESSION_FIGURES",
    "report_run",
    "report_session",
)
