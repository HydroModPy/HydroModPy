"""Scoring a stored run after the fact refuses what a series cannot give, by name."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pandas as pd
import pytest

from hydromodpy.results.score_table import check_metrics, resolve_windows

EMPTY = pd.DataFrame({"time": pd.to_datetime([], utc=True)})

REFUSALS: list[tuple[str, Callable[[], Any], type[Exception], str]] = [
    ("network_gap", lambda: check_metrics(["distance_gap"], None), ValueError, "score_network"),
    ("network_mean", lambda: check_metrics(["distance_mean"], None), ValueError, "score_network"),
    ("unknown", lambda: check_metrics(["nash"], None), ValueError, "unknown metric"),
    ("bfi_gap_masked", lambda: check_metrics(["bfi_gap"], [7]), ValueError, "consecutive days"),
    ("bfi_error_masked", lambda: check_metrics(["bfi_error"], [7]), ValueError, "consecutive days"),
    ("no_window", lambda: resolve_windows({}, EMPTY), ValueError, "windows is empty"),
    (
        "open_window_no_series",
        lambda: resolve_windows({"all": (None, None)}, EMPTY),
        ValueError,
        "holds no series",
    ),
    (
        "reversed_window",
        lambda: resolve_windows({"w": ("2020-01-02", "2020-01-01")}, EMPTY),
        ValueError,
        "before it starts",
    ),
]


@pytest.mark.parametrize(
    ("call", "error", "fragment"),
    [row[1:] for row in REFUSALS],
    ids=[row[0] for row in REFUSALS],
)
def test_refusal(call, error, fragment) -> None:
    with pytest.raises(error, match=fragment):
        call()
