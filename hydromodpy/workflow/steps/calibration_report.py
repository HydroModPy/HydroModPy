"""Calibration-report step - load session data then render the HTML.

Higher-layer adapter that bridges the data side
(:mod:`hydromodpy.calibration.report`) and the rendering side
(:mod:`hydromodpy.display.sessions`). Calibration owns the data;
display owns the figures and HTML; this step glues them together so
the CLI verb ``hmp report`` and any future workflow pipeline both go
through one entry point.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hydromodpy.results.catalog import SimulationCatalog


def step_render_calibration_report(
    *,
    catalog: SimulationCatalog,
    session_id: str,
    workspace_root: Path,
    figure_names: list[str] | tuple[str, ...] | None = None,
    output_dir: Path | None = None,
) -> Path:
    """Load one calibration session and render its HTML report.

    Returns the path to the generated ``report.html``. Figures that
    fail to render are skipped with a warning so the report always
    produces output even on partial data.
    """
    from hydromodpy.calibration.report import load_session_report_data
    from hydromodpy.display.sessions import render_session

    session_data = load_session_report_data(
        catalog=catalog,
        session_id=session_id,
        workspace_root=workspace_root,
    )
    written = render_session(
        session_data,
        figure_names=figure_names,
        output_dir=output_dir,
    )
    return written[-1]
