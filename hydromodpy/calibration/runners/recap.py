"""What the end of a calibration tells its reader, read off the run itself.

The console recap of ``hmp calibrate`` names, for each phase, the best value of
each parameter with its unit, the cost it reached, the metric that cost is and
the pairs it was scored on, the run promoted from it and the session folder
that holds its trials. Those
facts are known to the runner and to nobody after it, so the runner records
them in the report and the CLI only formats them.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

from hydromodpy.calibration.config import (
    CalibObjectiveBlockDecl,
    CalibPhaseDecl,
    CalibrationConfig,
)
from hydromodpy.calibration.criteria.registry import NETWORK_ESTIMATORS
from hydromodpy.calibration.criteria.series import HIGHER_IS_BETTER
from hydromodpy.calibration.report import scored_entry
from hydromodpy.results.metric_rule import CALIBRATION_ROLE
from hydromodpy.results.session.descriptor import ScoredSamples
from hydromodpy.results.storage.contract import SESSION_METHODS_FILENAME


def cost_metric_label(cfg: CalibrationConfig, phase: CalibPhaseDecl | None = None) -> str:
    """Name what the cost of a search is, the way a reader reads it.

    A score that rises with agreement (NSE, KGE) is minimised as one minus
    itself, so the label says ``1 - nse_log`` rather than ``nse_log``. A block
    that divides its cost by a reference scale, or transforms it, says so:
    ``log10(rmse / sd(observed))``. A cost of several blocks is their weighted
    sum and names each block. ``phase`` reads the blocks that phase scores;
    ``None`` reads the whole section.
    """
    if phase is not None and phase.is_single_metric:
        return _reading(phase.objective or cfg.objective)
    blocks = [block for block, _weight in cfg.objective_blocks_for(phase)]
    if len(blocks) == 1:
        return _block_reading(blocks[0])
    if blocks:
        parts = ", ".join(f"{block.name} {_block_reading(block)}" for block in blocks)
        return f"weighted sum of {parts}"
    return _reading(cfg.objective)


def _reading(metric: str) -> str:
    """Return how a cost built on ``metric`` reads."""
    return f"1 - {metric}" if str(metric) in HIGHER_IS_BETTER else str(metric)


def _block_reading(block: CalibObjectiveBlockDecl) -> str:
    """Return how the cost of one block reads, scale and cost transform included."""
    text = _reading(block.metric)
    if block.normalize_cost:
        scale = "validity_length" if str(block.metric) in NETWORK_ESTIMATORS else "sd(observed)"
        text = f"{text} / {scale}"
    if block.cost_transform == "log":
        return f"log10({text})"
    if block.cost_transform == "inverse":
        return f"-1 / ({text})"
    return text


def cost_samples(components: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Return, per dated output, the pairs a trial's cost was scored on.

    The block route writes ``<name>.n_paired`` and, as ordinal days,
    ``<name>.date_start`` / ``<name>.date_end`` into the components of every
    trial: the first and last period-end stamp it kept. ``<name>.n_sim_nan``
    counts the pairs a NaN simulated value took out. ``variable`` +
    ``objective`` is scored by that route too, its outputs named
    ``<variable>@<station>``. Empty when no output was paired, as for a
    network distance.
    """
    found = dict(components or {})
    names = sorted({key.rsplit(".", 1)[0] for key in found if key.endswith(".n_paired")})
    samples: dict[str, dict[str, Any]] = {}
    for name in names:
        entry: dict[str, Any] = {"n_paired": int(found[f"{name}.n_paired"])}
        lost = found.get(f"{name}.n_sim_nan")
        if lost is not None:
            entry["n_sim_nan"] = int(lost)
        start = found.get(f"{name}.date_start")
        end = found.get(f"{name}.date_end")
        if start is not None and end is not None:
            entry["start"] = date.fromordinal(int(start)).isoformat()
            entry["end"] = date.fromordinal(int(end)).isoformat()
        samples[name] = entry
    return samples


def scored_samples(
    components: Mapping[str, Any] | None, *, case_id: str, window: str = CALIBRATION_ROLE
) -> list[ScoredSamples]:
    """Return :func:`cost_samples` as the descriptor of a session records it."""
    return [
        scored_entry(name, info, case_id=case_id, window=window)
        for name, info in cost_samples(components).items()
    ]


def parameter_units(cfg: CalibrationConfig) -> dict[str, str]:
    """Return the declared unit of each calibrated parameter, ``-`` when none."""
    return {name: str(param.units or "-") for name, param in cfg.parameters.items()}


def write_methods(session_dir: Path, paragraph: str) -> Path:
    """Write the methods paragraph beside the trials and return its path."""
    path = Path(session_dir) / SESSION_METHODS_FILENAME
    path.write_text(f"# Methods\n\n{paragraph.strip()}\n", encoding="utf-8")
    return path


__all__ = [
    "cost_metric_label",
    "cost_samples",
    "parameter_units",
    "scored_samples",
    "write_methods",
]
