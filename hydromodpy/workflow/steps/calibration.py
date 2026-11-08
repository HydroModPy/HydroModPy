"""Calibration step - report rendering."""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Calibration report
# ---------------------------------------------------------------------------


def step_render_calibration_report(
    *,
    session_dir: Path,
    figure_names: list[str] | tuple[str, ...] | None = None,
) -> Path:
    """Load one calibration session from its directory and render its HTML report.

    Returns ``sessions/<session>/report/index.html``; the figures land in
    ``sessions/<session>/figures/``. Figures that fail to render are skipped
    with a warning so the report always produces output even on partial data.
    """
    from hydromodpy.calibration.report import load_session_report_data
    from hydromodpy.display.calibration_report import render_session

    session_data = load_session_report_data(Path(session_dir))
    written = render_session(
        session_data,
        figure_names=figure_names,
        session_dir=Path(session_dir),
    )
    return written[-1]


__all__ = [
    "step_render_calibration_report",
]
