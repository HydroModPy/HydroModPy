"""Validation: completeness diagnostics and column checks."""

from __future__ import annotations

from datetime import datetime

import pandas as pd


def compute_completeness(
    df: pd.DataFrame,
    *,
    date_column: str = "datetime",
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    station_id: str = "",
) -> dict:
    """Compute missing-data stats for one time series."""
    empty = {
        "station_id": str(station_id),
        "expected_days": 0,
        "actual_days": 0,
        "missing_days": 0,
        "completeness_pct": 0.0,
        "first_date": None,
        "last_date": None,
        "gaps_detected": 0,
    }

    if start_date is None or end_date is None:
        return empty

    if df.empty or date_column not in df.columns:
        total = (end_date - start_date).days + 1
        empty["expected_days"] = total
        empty["missing_days"] = total
        return empty

    dates = pd.to_datetime(df[date_column], errors="coerce").dropna()
    if dates.empty:
        total = (end_date - start_date).days + 1
        empty["expected_days"] = total
        empty["missing_days"] = total
        return empty

    expected = pd.date_range(start=start_date, end=end_date, freq="D")
    actual_days = dates.dt.normalize()
    n_duplicates = int(actual_days.duplicated().sum())
    actual = actual_days.unique()
    missing = set(expected) - set(pd.to_datetime(actual))

    gaps = 0
    if missing:
        sorted_missing = sorted(missing)
        gaps = 1
        for i in range(1, len(sorted_missing)):
            if (sorted_missing[i] - sorted_missing[i - 1]).days > 1:
                gaps += 1

    expected_count = len(expected)
    actual_count = len(actual)
    return {
        "station_id": str(station_id),
        "expected_days": expected_count,
        "actual_days": actual_count,
        "missing_days": len(missing),
        "completeness_pct": (actual_count / expected_count) * 100 if expected_count else 0.0,
        "first_date": dates.min(),
        "last_date": dates.max(),
        "gaps_detected": gaps,
        "n_duplicates": n_duplicates,
    }


def check_required_columns(
    df: pd.DataFrame,
    required: tuple[str, ...],
    *,
    context: str = "",
) -> None:
    """Raise ValueError if required columns are missing."""
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(
            f"Missing required columns {missing} in {context or 'DataFrame'}. "
            f"Available: {list(df.columns)}"
        )
