"""Parse evaluated objective points from calibration iteration histories.

Used by validation benchmark plots (``validation_cases/calibration/plotting.py``)
to render objective surfaces from persisted JSONL traces. Kept deliberately
dependency-light so the same helper reads both legacy launcher histories
and the ones written by :mod:`hydromodpy.calibration.compat` for the new
CLI.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ObjectiveMappingPoint:
    """One evaluated simulation used to map the objective function."""

    iteration_id: str
    params_vector: tuple[float, ...]
    params_named: dict[str, float]
    objective_total: float | None
    block_costs: dict[str, float] = field(default_factory=dict)
    status: str = "unknown"
    failure_reason: str | None = None

    @property
    def finite_objective(self) -> bool:
        return self.objective_total is not None and math.isfinite(float(self.objective_total))


def _objective_from_payload(payload: dict[str, Any]) -> float | None:
    value = payload.get("objective_total")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_objective_mapping_points(history_path: Path) -> list[ObjectiveMappingPoint]:
    """Load evaluated objective points from a calibration JSONL history.

    Each line must be a JSON object with (at least) ``iteration_id``,
    ``params_named``, ``params_vector``, and ``objective_total``. Missing
    keys fall back to neutral defaults so the reader is forgiving to
    evolving schemas.
    """
    history_path = Path(history_path)
    if not history_path.is_file():
        return []
    points: list[ObjectiveMappingPoint] = []
    for raw_line in history_path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        payload = json.loads(raw_line)
        params_named = {
            str(name): float(value) for name, value in dict(payload.get("params_named", {})).items()
        }
        params_vector = tuple(float(value) for value in payload.get("params_vector", ()))
        points.append(
            ObjectiveMappingPoint(
                iteration_id=str(payload.get("iteration_id", "")),
                params_vector=params_vector,
                params_named=params_named,
                objective_total=_objective_from_payload(payload),
                block_costs={
                    str(name): float(value)
                    for name, value in dict(payload.get("block_costs", {})).items()
                },
                status=str(payload.get("status", "unknown")),
                failure_reason=payload.get("failure_reason"),
            )
        )
    return points


__all__ = ("ObjectiveMappingPoint", "load_objective_mapping_points")
