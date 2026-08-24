"""The per-trial table of a calibration session, flattened for plotting.

A session records one row per evaluated trial: the parameters it sampled and
the diagnostics the criterion published. Both arrive nested, and a network
output prefixes every diagnostic it emits with its own name, so ``D_so`` is
stored as ``<output>.D_so``. The figures reading a crossing or a bracket need
those columns flat and reachable by their bare name, and this module is the
one place that flattening happens.

Nothing here drops a trial. A trial that failed keeps its row with an empty
diagnostic, because a distance that was never measured is a gap in a curve and
never a zero.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from hydromodpy.results.calibration_trials import calibration_trials

if TYPE_CHECKING:
    from hydromodpy.results.run import Run

_ORDER_COLUMNS: tuple[str, ...] = ("iteration", "iter", "trial", "i")

_OBJECTIVE_COLUMNS: tuple[str, ...] = ("objective_value", "objective")
"""The cost of a trial, as a session writes it and as a hand-built table names it."""

_META_COLUMNS: frozenset[str] = frozenset(
    {
        "duration_s",
        "from_cache",
        "i",
        "iter",
        "iteration",
        "metrics",
        "objective",
        "objective_value",
        "parameters",
        "params_hash",
        "session_id",
        "sim_id",
        "status",
        "trial",
    }
)


@dataclass(frozen=True, slots=True)
class TrialTable:
    """One row per evaluated trial, in evaluation order.

    ``parameters`` names the columns that came out of the sampled parameter
    block, which is what tells a calibrated parameter apart from a diagnostic
    a criterion happens to publish under a bare name.
    """

    frame: pd.DataFrame
    parameters: tuple[str, ...]

    def parameter_values(self, name: str | None = None) -> tuple[str, np.ndarray]:
        """Return the name and the sampled values of one calibrated parameter."""
        if name is not None:
            if name not in self.frame.columns:
                raise ValueError(
                    f"the session sampled no parameter {name!r}; it sampled "
                    f"{', '.join(self.parameters) or '<none>'}."
                )
            return name, _numeric_column(self.frame, name)
        if not self.parameters:
            raise ValueError("the session recorded no sampled parameter.")
        if len(self.parameters) > 1:
            raise ValueError(
                "this figure reads one calibrated parameter, and the session sampled "
                f"{', '.join(self.parameters)}. Name the one to read."
            )
        only = self.parameters[0]
        return only, _numeric_column(self.frame, only)

    def iterations(self) -> np.ndarray:
        """Return the trial numbers, or their rank when the session recorded none."""
        for column in _ORDER_COLUMNS:
            if column in self.frame.columns:
                return _numeric_column(self.frame, column)
        return np.arange(len(self.frame), dtype="float64")

    def objective_values(self, name: str | None = None) -> tuple[str, np.ndarray]:
        """Return the name and the per-trial values of the objective."""
        column = self.objective_column(name)
        return column, _numeric_column(self.frame, column)

    def has_objective(self) -> bool:
        """Whether an objective is resolvable, so a caller can make its panel optional."""
        try:
            self.objective_column()
        except ValueError:
            return False
        return True

    def objective_column(self, name: str | None = None) -> str:
        """Resolve the column holding the cost of each trial."""
        if name is not None:
            if name not in self.frame.columns:
                raise ValueError(
                    f"the session recorded no objective {name!r}; it recorded "
                    f"{', '.join(sorted(self.frame.columns))}."
                )
            return name
        for candidate in _OBJECTIVE_COLUMNS:
            if candidate in self.frame.columns:
                return candidate
        raise ValueError(
            f"no trial recorded an objective under {' or '.join(_OBJECTIVE_COLUMNS)}; "
            f"the session recorded {', '.join(sorted(self.frame.columns))}."
        )

    def diagnostic(self, name: str, *, output: str | None = None) -> np.ndarray:
        """Return one diagnostic as float, NaN wherever a trial published none."""
        return _numeric_column(self.frame, self.diagnostic_column(name, output=output))

    def has_diagnostic(self, name: str, *, output: str | None = None) -> bool:
        """Whether ``name`` is resolvable, so a caller can make it optional."""
        try:
            self.diagnostic_column(name, output=output)
        except ValueError:
            return False
        return True

    def diagnostic_column(self, name: str, *, output: str | None = None) -> str:
        """Resolve a bare diagnostic name against the ``<output>.<key>`` form."""
        if output is not None:
            column = f"{output}.{name}"
            if column not in self.frame.columns:
                raise ValueError(
                    f"output {output!r} published no {name!r} diagnostic; the session "
                    f"recorded {', '.join(sorted(self.frame.columns))}."
                )
            return column
        if name in self.frame.columns:
            return name
        matches = sorted(column for column in self.frame.columns if column.endswith(f".{name}"))
        if not matches:
            raise ValueError(
                f"no trial published a {name!r} diagnostic; the session recorded "
                f"{', '.join(sorted(self.frame.columns))}."
            )
        if len(matches) > 1:
            raise ValueError(
                f"several outputs publish a {name!r} diagnostic ({', '.join(matches)}); "
                "name the output to read."
            )
        return matches[0]


def trial_table(sim: Run, *, session_id: str | None = None) -> TrialTable:
    """Read the calibration trials of one run into a flat trial table.

    The rows come from :func:`hydromodpy.results.calibration_trials`, which
    reads them on the same key ``Run.has_table`` answers on. Reading them any
    other way makes the availability gate and the render disagree, and the
    figure then reports itself available and raises mid-render.
    """
    frame = calibration_trials(sim, session_id=session_id)

    frame, parameters = _expand_parameters(frame)
    frame = _expand_metrics(frame)
    order = next((column for column in _ORDER_COLUMNS if column in frame.columns), None)
    if order is not None:
        frame = frame.sort_values(order, kind="stable")
    return TrialTable(frame=frame.reset_index(drop=True), parameters=parameters)


def _expand_parameters(frame: pd.DataFrame) -> tuple[pd.DataFrame, tuple[str, ...]]:
    """Flatten ``{"K": {"value": 1e-5}}`` into one column per parameter.

    A table without a ``parameters`` block is read the other way round: every
    column that is not session bookkeeping is a sampled parameter. The block
    wins when both are there, since it is the one the session actually wrote.
    """
    if "parameters" in frame.columns:
        rows = [_mapping(value) for value in frame["parameters"]]
        names = sorted({str(key) for row in rows for key in row})
        for name in names:
            if name not in frame.columns:
                frame[name] = [_parameter_value(row.get(name)) for row in rows]
        return frame, tuple(names)
    flat = tuple(
        str(column)
        for column in frame.columns
        if column not in _META_COLUMNS and "." not in str(column)
    )
    return frame, flat


def _expand_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    """Flatten the metric dict, keeping the keys a figure can draw."""
    if "metrics" not in frame.columns:
        return frame
    rows = [_mapping(value) for value in frame["metrics"]]
    for key in sorted({str(name) for row in rows for name in row}):
        if key in frame.columns:
            continue
        values = [_number_or_nan(row.get(key)) for row in rows]
        if all(not np.isfinite(value) for value in values):
            # A metric no trial expressed as a number (a message, a nested
            # block) is not a curve, and an all-NaN column would only pollute
            # the name resolution of the ones that are.
            continue
        frame[key] = values
    return frame


def _mapping(value: Any) -> Mapping[str, Any]:
    """Read one nested block, which the index hands back as a JSON string.

    The journal keeps it a dict and DuckDB keeps it text, and both are the
    same block; a figure has to read either without knowing which side of the
    storage it came from.
    """
    if isinstance(value, Mapping):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, Mapping) else {}
    return {}


def _parameter_value(value: Any) -> float:
    """Read one sampled parameter, written either bare or under a ``value`` key."""
    if isinstance(value, Mapping):
        return _number_or_nan(value.get("value"))
    return _number_or_nan(value)


def _number_or_nan(value: Any) -> float:
    """Return ``value`` as a float, or NaN when it is not a number."""
    if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
        return float("nan")
    return float(value)


def _numeric_column(frame: pd.DataFrame, column: str) -> np.ndarray:
    """Return one column as float64, with NaN where the value is not a number."""
    return pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype="float64")


__all__ = ["TrialTable", "trial_table"]
