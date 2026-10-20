"""What a completed run says about itself, read from its own directory.

A run sealed by :class:`~hydromodpy.results.record.RunRecord` carries its site,
its case, its lineage, its checks, its loaded inputs and its scores in
``manifest.json``, ``inputs.json`` and ``provenance.json``. These facts are
read from the directory, never from the index: a run received alone answers
the same. A run without ``manifest.json`` never completed and has no seal.

The scores of a run are the rows of ``manifest.metrics``. The headline NSE
(``manifest.score``) names the station and variable it was read at; the
metrics of a run, as a reader ranks them, are the rows at that station and on
that variable, each named by its metric alone and carrying the window.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import pandas as pd

from hydromodpy.core.exceptions import DataError
from hydromodpy.results.errors import RunNotSealedError
from hydromodpy.results.manifest import is_sealed
from hydromodpy.results.record import RunRecord
from hydromodpy.results.storage.contract import RUN_MANIFEST_FILENAME, RUN_OUTCOME_FILENAME
from hydromodpy.results.storage.run_store import RunStore

if TYPE_CHECKING:
    from hydromodpy.results.lineage import Lineage
    from hydromodpy.results.manifest import MetricRow
    from hydromodpy.results.run.view import Run

WINDOW_COLUMNS: Final[tuple[str, ...]] = (
    "nse_window_start",
    "nse_window_end",
    "nse_n",
    "metric_rule_version",
)
"""Columns that say how the metrics of a run were computed."""


def read_record(run_dir: Path, sim_id: str) -> RunRecord:
    """Return the seal of the run in *run_dir*.

    Raises :class:`~hydromodpy.results.errors.RunNotSealedError` when the
    directory holds no manifest.
    """
    if not is_sealed(run_dir):
        raise RunNotSealedError(
            f"Run '{sim_id[:8]}' has no {RUN_MANIFEST_FILENAME} in {run_dir}: it never "
            "completed, so its site, checks, label and scores were never sealed. "
            f"Read its {RUN_OUTCOME_FILENAME} for what happened."
        )
    return RunRecord.read(run_dir)


def lineage_of(run: Run) -> Lineage | None:
    """Return where *run* comes from, ``None`` for a run that never completed.

    A run opened on its store reads the lineage from its facts, so a promoted
    run drawn before its seal still names its session; any other run reads
    its seal. A module function rather than a ``Run`` attribute: ``Run`` is
    capped at 50 public attributes (``tests/unit/results/test_run_surface.py``).
    """
    handle = run._catalog_handle  # noqa: SLF001 - same package
    if isinstance(handle, RunStore):
        return handle.facts.lineage
    try:
        return run._record().lineage  # noqa: SLF001 - same package
    except RunNotSealedError:
        return None


def headline_metrics(record: RunRecord) -> dict[str, Any]:
    """Return the metrics of a run at the station of its headline NSE, one key per metric.

    Without a headline score, or without a station, the run has no metric a
    reader can rank and only the rule columns are given, empty.
    """
    headline = record.score
    row: dict[str, Any] = dict.fromkeys(RULE_COLUMNS)
    if headline is None or headline.station is None:
        return row
    row.update(
        station=headline.station,
        variable=headline.variable,
        nse_window_start=headline.nse_window_start,
        nse_window_end=headline.nse_window_end,
        nse_n=headline.nse_n,
        metric_rule_version=headline.metric_rule_version,
    )
    for metric in record.metrics:
        if metric.station == headline.station and metric.variable == headline.variable:
            row[metric.metric] = metric.value
    return row


def metrics_frame(record: RunRecord | None) -> pd.DataFrame:
    """Return every metric row of a run, long form, with its station, variable and window.

    ``None`` stands for a run without a seal, which has no row.
    """
    return _metrics_table([] if record is None else record.metrics)


def metrics_of(run: Run) -> pd.DataFrame:
    """Return every metric row of *run*, long form, as :func:`metrics_frame` does.

    A run opened on its store reads them from its facts, so a figure drawn
    before the seal reads the scores the derive step wrote; any other run
    reads its seal. A module function rather than a ``Run`` attribute, like
    :func:`lineage_of`. A stand-in that carries no metrics has no row.
    """
    handle = getattr(run, "_catalog_handle", None)
    if isinstance(handle, RunStore):
        return _metrics_table(handle.facts.metrics)
    metrics = getattr(run, "metrics", None)
    return metrics if isinstance(metrics, pd.DataFrame) else _metrics_table([])


def _metrics_table(metrics: Sequence[MetricRow]) -> pd.DataFrame:
    columns = ["station", "variable", "metric", "value", *WINDOW_COLUMNS, "n_clipped"]
    return pd.DataFrame([metric.model_dump() for metric in metrics], columns=columns)


@dataclass(frozen=True, slots=True)
class RuleColumns:
    """The columns of a table that say under which rule a score was computed.

    The rule is the station and the variable the score was read at, the window
    and the rule version. The window and the version are named alike in every
    table; the station and the variable are not, hence the two fields. The
    number of samples of the window is not part of the rule.
    """

    station: str = "station"
    variable: str = "variable"

    @property
    def names(self) -> tuple[str, ...]:
        """The five columns of the rule, station first."""
        return (
            self.station,
            self.variable,
            "nse_window_start",
            "nse_window_end",
            "metric_rule_version",
        )


HEADLINE_RULE: Final[RuleColumns] = RuleColumns()
"""The rule columns of the rows of :func:`headline_metrics`."""

RULE_COLUMNS: Final[tuple[str, ...]] = ("station", "variable", *WINDOW_COLUMNS)
"""Columns of :func:`headline_metrics` before the metric columns."""

INDEX_RULE: Final[RuleColumns] = RuleColumns("nse_station", "nse_variable")
"""The rule columns of the index and of the project summary."""

METRICS_RULE: Final[RuleColumns] = RuleColumns("station_id", "variable")
"""The rule columns of the ``metrics`` table of the index."""

FORCE_RANKING: Final[str] = (
    "pass mixed_windows=True (--mixed-windows on the command line) to rank them anyway"
)
"""How to force a ranking, the way ``check_one_rule`` says it by default."""


class MixedWindowsError(DataError):
    """Scores computed under different rules were about to be ranked together."""


def rule_cell(value: Any) -> str | None:
    """Return a cell of a rule column as text, ``None`` for an empty one."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value)
    if text in ("NaT", "nan", "None"):
        return None
    return text[:10] if len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-" else text


def check_one_rule(
    rows: Sequence[Mapping[str, Any]],
    metric: str,
    *,
    names: Sequence[str],
    columns: RuleColumns = HEADLINE_RULE,
    groups: Sequence[Any] | None = None,
    group_name: str = "group",
    force: str = FORCE_RANKING,
) -> None:
    """Refuse to rank ``rows`` whose ``metric`` was scored under different rules.

    Two scores compare only under the same rule: the station, the variable,
    the window and the rule version of ``columns``. ``names`` names each row
    in the message. With ``groups`` (the group of each row, ``group_name``
    its column), the rows are ranked inside their group: the variable, the
    window and the version must still agree across all rows, the station
    only inside each group, since each group has its own gauge. ``force``
    says in the message how to rank them anyway, as the caller can.

    Raises
    ------
    MixedWindowsError
        Naming each rule and the rows under it.
    """
    keys = [tuple(rule_cell(row.get(column)) for column in columns.names) for row in rows]
    cohort = keys if groups is None else [key[1:] for key in keys]
    seen: dict[tuple[str | None, ...], list[str]] = {}
    for key, name in zip(cohort, names, strict=True):
        seen.setdefault(key, []).append(str(name))
    if len(seen) > 1:
        listed = "; ".join(
            f"{_rule_words(key, with_station=groups is None)}: {', '.join(found[:5])}"
            + (f" and {len(found) - 5} more" if len(found) > 5 else "")
            for key, found in sorted(seen.items(), key=lambda item: str(item[0]))
        )
        raise MixedWindowsError(
            f"'{metric}' was scored under {len(seen)} different rules: {listed}. The values "
            "are not comparable; declare one [metrics] window for every case, or "
            f"{force}."
        )
    if groups is None:
        return
    stations: dict[Any, set[str | None]] = {}
    for key, group in zip(keys, groups, strict=True):
        stations.setdefault(group, set()).add(key[0])
    for group, found in stations.items():
        if len(found) > 1:
            raise MixedWindowsError(
                f"the cases of {group_name} {group} score '{metric}' at {len(found)} stations "
                f"({', '.join(sorted(str(s) for s in found))}); {force}."
            )


def _rule_words(key: tuple[str | None, ...], *, with_station: bool) -> str:
    """Say a rule key in words; ``key`` holds the station first when ``with_station``."""
    station, rest = (key[0], key[1:]) if with_station else (None, key)
    variable, start, end, version = rest
    window = f"{start} to {end}" if start and end else (start or "no window")
    where = f" at {station}" if with_station else ""
    return f"{variable or '?'}{where}, {window} (rule {version or '?'})"


__all__ = [
    "FORCE_RANKING",
    "HEADLINE_RULE",
    "INDEX_RULE",
    "METRICS_RULE",
    "RULE_COLUMNS",
    "WINDOW_COLUMNS",
    "MixedWindowsError",
    "RuleColumns",
    "check_one_rule",
    "headline_metrics",
    "lineage_of",
    "metrics_frame",
    "metrics_of",
    "read_record",
    "rule_cell",
]
