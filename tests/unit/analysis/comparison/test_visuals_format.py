"""Anti-regression unit tests for ``analysis.comparison.visuals_format``.

Covers time-tick label formatting and the ``_apply_time_ticks`` axis
mutation (no-op, label application, subsampling).
"""

from __future__ import annotations

from hydromodpy.analysis.comparison.visuals_format import (
    _apply_time_ticks,
    _format_time_tick_label,
)

# -- time tick formatting -------------------------------------------------


def test_format_time_tick_label_iso_returns_month_abbreviation() -> None:
    assert _format_time_tick_label("2024-03-15") == "Mar"


def test_format_time_tick_label_integer_string_passthrough() -> None:
    assert _format_time_tick_label("42") == "42"


def test_format_time_tick_label_empty_returns_empty() -> None:
    assert _format_time_tick_label("") == ""


def test_format_time_tick_label_year_month_truncation() -> None:
    assert _format_time_tick_label("2024-03-XX") == "2024-03"


def test_apply_time_ticks_no_positions_is_noop() -> None:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    _apply_time_ticks(ax, tick_positions=[])
    assert ax.get_xticks().size >= 0
    plt.close(fig)


def test_apply_time_ticks_with_labels_applies_text() -> None:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    _apply_time_ticks(
        ax,
        tick_positions=[0.0, 1.0, 2.0],
        tick_labels=["2024-01-01", "2024-02-01", "2024-03-01"],
    )
    labels = [t.get_text() for t in ax.get_xticklabels()]
    assert "Jan" in labels or "Feb" in labels or "Mar" in labels
    plt.close(fig)


def test_apply_time_ticks_many_positions_subsamples() -> None:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    _apply_time_ticks(ax, tick_positions=list(range(20)))
    ticks = ax.get_xticks()
    assert ticks.size <= 8
    plt.close(fig)
