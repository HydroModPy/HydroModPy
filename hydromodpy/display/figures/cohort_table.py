"""What the cohort figures read: one table, one row per site.

A cohort figure draws ``summary/by_site`` of a project, not a run. It takes
the table as a pandas DataFrame in place of a run, so it refuses a run with a
sentence, as a figure of a run set refuses a single run. A cohort figure lives
in a module ``cohort_<name>.py`` of this package and is registered under the
name ``[sites.summary] figures`` writes (``map``, ``distribution``); the
collect draws only the figures of these modules. The helpers here pick
the column a figure draws and read the outlets, which the collect has put
in one CRS.
"""

from __future__ import annotations

from typing import Any

import numpy as np

COHORT_SITE_COLUMN = "site"
"""Column naming the site of a row."""

COHORT_X_COLUMN = "x_outlet"
COHORT_Y_COLUMN = "y_outlet"
COHORT_CRS_COLUMN = "crs"
"""Columns of the declared outlet and of its CRS."""

LOG_SCALE_SPAN = 10.0
"""Ratio of the largest to the smallest positive value above which a log scale is drawn."""


def cohort_refusal(table: Any) -> str | None:
    """Return why ``table`` is not a cohort table, or ``None`` when it is one."""
    import pandas as pd

    if not isinstance(table, pd.DataFrame):
        return (
            "draws a cohort table (summary/by_site of a project, one row per site), "
            "and a run is one run; run hmp campaign collect"
        )
    if COHORT_SITE_COLUMN not in table.columns:
        return f"the cohort table has no {COHORT_SITE_COLUMN!r} column"
    return None


def column_values(table: Any, variable: str, *, figure: str) -> np.ndarray:
    """Return the finite values of ``variable`` as floats, one per row, NaN where missing.

    Raises
    ------
    ValueError
        When the table has no such column, naming the columns it has.
    """
    import pandas as pd

    if variable not in table.columns:
        listed = ", ".join(str(column) for column in table.columns)
        raise ValueError(f"{figure}: the cohort table has no column {variable!r}; it has {listed}")
    return pd.to_numeric(table[variable], errors="coerce").to_numpy(dtype="float64")


def wants_log(values: np.ndarray, log: bool | None) -> bool:
    """Return whether to draw ``values`` on a log scale.

    ``log`` forces the choice. Left out, a log scale when every finite value is
    positive and they span more than :data:`LOG_SCALE_SPAN`.
    """
    if log is not None:
        return bool(log)
    finite = values[np.isfinite(values)]
    if finite.size < 2 or np.any(finite <= 0.0):
        return False
    return float(finite.max() / finite.min()) > LOG_SCALE_SPAN


def outlets(table: Any, *, figure: str) -> tuple[np.ndarray, np.ndarray, str | None]:
    """Return the outlet coordinates of every row and their CRS; NaN for a row without one.

    Raises
    ------
    ValueError
        When the rows name several CRS: the collect moves them into one first.
    """
    import pandas as pd

    n = len(table)
    if COHORT_X_COLUMN not in table.columns or COHORT_Y_COLUMN not in table.columns:
        empty = np.full(n, np.nan)
        return empty, empty.copy(), None
    xs = pd.to_numeric(table[COHORT_X_COLUMN], errors="coerce").to_numpy(dtype="float64")
    ys = pd.to_numeric(table[COHORT_Y_COLUMN], errors="coerce").to_numpy(dtype="float64")
    known: set[str] = set()
    if COHORT_CRS_COLUMN in table.columns:
        known = {
            str(cell)
            for cell, x in zip(table[COHORT_CRS_COLUMN], xs, strict=True)
            if not pd.isna(cell) and np.isfinite(x)
        }
    if len(known) > 1:
        raise ValueError(
            f"{figure}: the outlets of the cohort table are in {len(known)} CRS "
            f"({', '.join(sorted(known))}); move them into one before drawing"
        )
    return xs, ys, next(iter(known), None)


__all__ = [
    "COHORT_CRS_COLUMN",
    "COHORT_SITE_COLUMN",
    "COHORT_X_COLUMN",
    "COHORT_Y_COLUMN",
    "LOG_SCALE_SPAN",
    "cohort_refusal",
    "column_values",
    "outlets",
    "wants_log",
]
