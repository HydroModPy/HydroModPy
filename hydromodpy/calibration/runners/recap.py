"""What the end of a calibration tells its reader, read off the run itself.

The console recap of ``hmp run`` names, for each phase, the best value of each
parameter with its unit, the cost it reached and the metric that cost is, the
run promoted from it and the session folder that holds its trials. Those facts
are known to the runner and to nobody after it, so the runner records them in
the report and the CLI only formats them.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.criteria.series import HIGHER_IS_BETTER
from hydromodpy.results.session_journal import session_dirs_for

METHODS_FILENAME = "methods.md"
"""The file, in the root session folder, that holds the methods paragraph."""


def cost_metric_label(cfg: CalibrationConfig) -> str:
    """Name the metric the cost of a search is, the way a reader reads it.

    A score that rises with agreement (NSE, KGE) is minimised as one minus
    itself, so the label says ``1 - nse_log`` rather than ``nse_log``. A cost
    of several blocks is their weighted sum and names each block.
    """
    blocks = list(cfg.objective_blocks or ())
    if len(blocks) == 1:
        return _reading(blocks[0].metric)
    if blocks:
        parts = ", ".join(f"{block.name} {_reading(block.metric)}" for block in blocks)
        return f"weighted sum of {parts}"
    return _reading(cfg.objective)


def _reading(metric: str) -> str:
    """Return how a cost built on ``metric`` reads."""
    return f"1 - {metric}" if str(metric) in HIGHER_IS_BETTER else str(metric)


def parameter_units(cfg: CalibrationConfig) -> dict[str, str]:
    """Return the declared unit of each calibrated parameter, ``-`` when none."""
    return {name: str(param.units or "-") for name, param in cfg.parameters.items()}


def session_directory(project_root: Path, session_id: str) -> Path | None:
    """Return the folder a session journals its trials in, or None when none exists.

    A session folder is named ``<date>-<method>-<id8>``; the short id is what
    ties it to the session.
    """
    short = str(session_id).replace("-", "")[:8]
    matches = [path for path in session_dirs_for(project_root) if path.name.endswith(f"-{short}")]
    return matches[-1] if matches else None


def write_methods(session_dir: Path, paragraph: str) -> Path:
    """Write the methods paragraph beside the trials and return its path."""
    path = Path(session_dir) / METHODS_FILENAME
    path.write_text(f"# Methods\n\n{paragraph.strip()}\n", encoding="utf-8")
    return path


__all__ = [
    "METHODS_FILENAME",
    "cost_metric_label",
    "parameter_units",
    "session_directory",
    "write_methods",
]
