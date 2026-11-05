"""Rank the rows of sealed runs by one metric, and say why a group has no ranked row.

A row is one sealed run as the index lists it (``v_cases``, ``hmp catalog
ls``): its ``metric`` column, the columns of its score rule
(:data:`~hydromodpy.results.run.sealed.INDEX_RULE`) and, under ``by``, the
column grouping it (``site``). The best value of a metric follows its
direction (:func:`~hydromodpy.results.run.group.rank_key`). Rows scored under
different rules are not ranked together unless asked (``mixed_windows``).

A cell read back from a table may be missing as ``None``, NaN, NaT or NA:
:func:`clean_cell` says ``None`` for all of them.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from hydromodpy.results.run.group import rank_key
from hydromodpy.results.run.sealed import INDEX_RULE, check_one_rule

if TYPE_CHECKING:
    import pandas as pd


def is_finite(value: Any) -> bool:
    """Return whether *value* reads as a finite number; a boolean does not."""
    if value is None or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def clean_cell(value: Any) -> Any:
    """Return ``None`` for a missing cell (NaN, NaT, NA), the value otherwise."""
    if value is None:
        return None
    try:
        import pandas as pd

        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        return value
    return value


def first_present(*values: Any) -> Any:
    """Return the first value that is not a missing cell, ``None`` without one."""
    return next((value for value in values if clean_cell(value) is not None), None)


def rank_rows(
    frame: pd.DataFrame, metric: str, *, by: str | None = None, mixed_windows: bool = False
) -> pd.DataFrame:
    """Return the rows of ``frame`` with a finite ``metric``, best first.

    Under ``by``, only the best row of each group is kept, groups in name
    order. Ties keep the first row of ``frame``. Rows scored under different rules
    are refused (:func:`~hydromodpy.results.run.sealed.check_one_rule`).
    """
    key = rank_key(metric)
    if frame.empty or metric not in frame.columns:
        return frame.iloc[0:0]
    scored = frame[[is_finite(value) for value in frame[metric]]].copy()
    if not mixed_windows:
        check_one_rule(
            scored.to_dict("records"),
            metric,
            names=[
                str(record.get("case_id") or record.get("name"))
                for record in scored.to_dict("records")
            ],
            columns=INDEX_RULE,
            groups=None if by is None else list(scored[by]),
            group_name=by or "group",
        )
    scored["_rank"] = [key(float(value)) for value in scored[metric]]
    scored = scored.sort_values("_rank", kind="stable")
    if by is not None:
        scored = scored.drop_duplicates(subset=[by], keep="first").sort_values(by, kind="stable")
    return scored.drop(columns="_rank")


def unscored_reason(name: str, frame: pd.DataFrame, metric: str) -> str:
    """Say why no sealed run of *name* in *frame* has a finite *metric*.

    A run without a score window carries no score at all: that is the reason
    named first. *frame* holds the ``score_window_start`` column of the index.
    """
    windows = frame["score_window_start"] if "score_window_start" in frame.columns else ()
    if not any(clean_cell(value) is not None for value in windows):
        return f"no sealed run of {name} is scored: declare [metrics] window"
    return f"no sealed run of {name} has a {metric}"


def names_text(names: Sequence[str], shown: int = 5) -> str:
    """Return the first *shown* names of a list, then how many more."""
    more = f" and {len(names) - shown} more" if len(names) > shown else ""
    return ", ".join(names[:shown]) + more


__all__ = [
    "clean_cell",
    "first_present",
    "is_finite",
    "names_text",
    "rank_rows",
    "unscored_reason",
]
