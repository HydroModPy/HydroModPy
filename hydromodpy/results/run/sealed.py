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

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import pandas as pd

from hydromodpy.results.errors import RunNotSealedError
from hydromodpy.results.manifest import is_sealed
from hydromodpy.results.record import RunRecord
from hydromodpy.results.storage.contract import RUN_MANIFEST_FILENAME, RUN_OUTCOME_FILENAME
from hydromodpy.results.storage.run_store import RunStore

if TYPE_CHECKING:
    from hydromodpy.results.lineage import Lineage
    from hydromodpy.results.run.view import Run

WINDOW_COLUMNS: Final[tuple[str, ...]] = (
    "nse_window_start",
    "nse_window_end",
    "nse_n",
    "metric_rule_version",
)
"""Columns that say how the metrics of a run were computed."""

RULE_COLUMNS: Final[tuple[str, ...]] = ("station", "variable", *WINDOW_COLUMNS)
"""Columns of :func:`headline_metrics` before the metric columns."""


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
    columns = ["station", "variable", "metric", "value", *WINDOW_COLUMNS]
    rows = [] if record is None else [metric.model_dump() for metric in record.metrics]
    return pd.DataFrame(rows, columns=columns)


def rule_of(
    row: dict[str, Any],
) -> tuple[str | None, str | None, date | None, date | None, str | None]:
    """Return the complete rule a metrics row was computed under.

    The rule is the station and the variable the score was read at, the window
    and the rule version. Two rows compare only under the same rule.
    """
    return (
        row.get("station"),
        row.get("variable"),
        row.get("nse_window_start"),
        row.get("nse_window_end"),
        row.get("metric_rule_version"),
    )


__all__ = [
    "RULE_COLUMNS",
    "WINDOW_COLUMNS",
    "headline_metrics",
    "lineage_of",
    "metrics_frame",
    "read_record",
    "rule_of",
]
