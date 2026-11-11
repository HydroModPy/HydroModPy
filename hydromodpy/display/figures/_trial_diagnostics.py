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

``trial_table(session, *, phase=None)`` gives one row per trial and case. A network
output prefixes its diagnostics with its own name (``<output>.D_so``), so a diagnostic
is read by its bare name or under ``output=``. A trial that failed keeps its row with an
empty diagnostic, because a distance never measured is a gap in a curve, never a zero.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from hydromodpy.display.figure import FigureNotApplicable

if TYPE_CHECKING:
    from hydromodpy.results.session.view import Session

_ORDER_COLUMNS: tuple[str, ...] = ("trial", "iteration", "iter", "i")

_OBJECTIVE_COLUMNS: tuple[str, ...] = ("cost", "objective")
"""The cost of a trial, as a session writes it and as a hand-built table names it."""

_META_COLUMNS: frozenset[str] = frozenset(
    {
        "case_cost",
        "case_id",
        "case_status",
        "components",
        "duration_s",
        "from_cache",
        "i",
        "iter",
        "iteration",
        "objective",
        "cost",
        "parameters",
        "params_hash",
        "phase",
        "rel_dir",
        "restart",
        "session_id",
        "site",
        "speculative_unused",
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
            raise FigureNotApplicable("the session recorded no sampled parameter.")
        if len(self.parameters) > 1:
            raise FigureNotApplicable(
                "this figure reads one calibrated parameter, and the session sampled "
                f"{', '.join(self.parameters)} together. Name the one to read with "
                "parameter = ..."
            )
        only = self.parameters[0]
        return only, _numeric_column(self.frame, only)

    def iterations(self) -> np.ndarray:
        """Return the trial numbers, or their rank when the session recorded none."""
        for column in _ORDER_COLUMNS:
            if column in self.frame.columns:
                return _numeric_column(self.frame, column)
        return np.arange(len(self.frame), dtype="float64")

    def row_of_trial(self, trial: int) -> int | None:
        """Return the row of one trial number, None when no row carries it.

        A table that recorded no trial number has only ranks, and a rank is
        not the number a session declares, so it matches nothing.
        """
        column = next((name for name in _ORDER_COLUMNS if name in self.frame.columns), None)
        if column is None:
            return None
        matches = np.flatnonzero(_numeric_column(self.frame, column) == float(trial))
        return int(matches[0]) if matches.size else None

    def cost_values(self, name: str | None = None) -> tuple[str, np.ndarray]:
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
                    f"{', '.join(sorted(map(str, self.frame.columns)))}."
                )
            return name
        for candidate in _OBJECTIVE_COLUMNS:
            if candidate in self.frame.columns:
                return candidate
        raise ValueError(
            f"no trial recorded an objective under {' or '.join(_OBJECTIVE_COLUMNS)}; "
            f"the session recorded {', '.join(sorted(map(str, self.frame.columns)))}."
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
                    f"recorded {', '.join(sorted(map(str, self.frame.columns)))}."
                )
            return column
        if name in self.frame.columns:
            return name
        matches = sorted(column for column in self.frame.columns if column.endswith(f".{name}"))
        if not matches:
            raise ValueError(
                f"no trial published a {name!r} diagnostic; the session recorded "
                f"{', '.join(sorted(map(str, self.frame.columns)))}."
            )
        if len(matches) > 1:
            raise ValueError(
                f"several outputs publish a {name!r} diagnostic ({', '.join(matches)}); "
                "name the output to read."
            )
        return matches[0]


def trial_table(session: Session, *, phase: str | None = None) -> TrialTable:
    """Read the trials of one calibration session into a flat trial table.

    The rows come from ``Session.trials``, the journal of the session, one row
    per trial and case. ``phase`` keeps the trials of that phase only. A
    session with no trial, or none in the phase, is an error that says which.
    """
    frame = session.trials
    if phase is not None:
        frame = frame[frame["phase"] == phase]
    if frame.empty:
        scope = "" if phase is None else f" in phase {phase!r}"
        raise ValueError(f"no trial recorded{scope} by session {session.name!r}.")
    frame, parameters = _expand_parameters(frame.reset_index(drop=True))
    frame = _expand_components(frame)
    order = next((column for column in _ORDER_COLUMNS if column in frame.columns), None)
    if order is not None:
        frame = frame.sort_values(order, kind="stable")
    return TrialTable(frame=frame.reset_index(drop=True), parameters=parameters)


def no_trial_reason(session: Session) -> str | None:
    """Return why ``session`` holds no trial to draw, or None when it holds some."""
    try:
        trial_table(session)
    except ValueError as exc:
        return str(exc)
    return None


def _expand_parameters(frame: pd.DataFrame) -> tuple[pd.DataFrame, tuple[str, ...]]:
    """Flatten ``{"K": {"value": 1e-5}}`` into one column per parameter.

    A table without a ``parameters`` block is read the other way round: every
    column that is not session bookkeeping is a sampled parameter. The block
    wins when both are there, since it is the one the session actually wrote.
    """
    if "parameters" in frame.columns:
        rows = [_mapping(value) for value in frame["parameters"]]
        names = sorted({str(key) for row in rows for key in row})
        columns = {
            name: [_parameter_value(row.get(name)) for row in rows]
            for name in names
            if name not in frame.columns
        }
        return _joined(frame, columns), tuple(names)
    flat = tuple(
        str(column)
        for column in frame.columns
        if column not in _META_COLUMNS and "." not in str(column)
    )
    return frame, flat


def _expand_components(frame: pd.DataFrame) -> pd.DataFrame:
    """Flatten the metric dict, keeping the keys a figure can draw."""
    if "components" not in frame.columns:
        return frame
    rows = [_mapping(value) for value in frame["components"]]
    columns: dict[str, list[float]] = {}
    for key in sorted({str(name) for row in rows for name in row}):
        if key in frame.columns:
            continue
        values = [_number_or_nan(row.get(key)) for row in rows]
        if all(not np.isfinite(value) for value in values):
            # A metric no trial expressed as a number (a message, a nested
            # block) is not a curve, and an all-NaN column would only pollute
            # the name resolution of the ones that are.
            continue
        columns[key] = values
    return _joined(frame, columns)


def _joined(frame: pd.DataFrame, columns: Mapping[str, list[float]]) -> pd.DataFrame:
    """Return ``frame`` with ``columns`` appended in one concatenation.

    A network criterion publishes about a hundred diagnostics per trial.
    Inserting them one by one fragments the frame, and pandas then warns on
    the console of every promoted run.
    """
    if not columns:
        return frame
    added = pd.DataFrame(dict(columns), index=frame.index)
    return pd.concat([frame, added], axis=1)


def _mapping(value: Any) -> Mapping[str, Any]:
    """Read one nested block of the journal, empty when it is not a mapping."""
    return value if isinstance(value, Mapping) else {}


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
