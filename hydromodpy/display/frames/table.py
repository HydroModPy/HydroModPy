"""Table frame: rows of text, a label and a value for each column a panel names.

It prints the value of each ``table.column`` of the panel for the subject. The label
comes from ``COLUMN_REGISTRY``, and the unit from the schema of the table when it gives
one. It draws no axes, no colour scale and no plot. A column without a registry row is
refused, and so is a column that holds several rows, which is not a table cell.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from hydromodpy.core.units.kinds import kind_row
from hydromodpy.core.units.parse import convert_between_units
from hydromodpy.display import static
from hydromodpy.display.request import (
    COLUMN_SEPARATOR,
    PanelRequest,
    unknown_column,
)
from hydromodpy.display.subject import FigureNotApplicable, read_table, refuse_fields
from hydromodpy.display.theme import Theme, unit_text
from hydromodpy.results.field_registry import COLUMN_REGISTRY
from hydromodpy.results.run.view import Run
from hydromodpy.results.storage.parquet_schemas import column_unit

FIELDS = ("variable",)
TABLE_COLUMNS = ("variable", "label", "value", "text")
DIGITS = 3
"""Significant digits of a printed number."""


@dataclass(frozen=True, slots=True)
class TableData:
    """What a table panel draws.

    ``table`` has the columns of ``TABLE_COLUMNS``, one row per name of the panel,
    in the order of ``variable``. ``variable`` is the ``table.column`` name.
    ``label`` is the registry label, followed by the unit in brackets when the schema
    gives one. ``value`` is a float64 for a number so a test compares it, in the display
    unit when the schema gives a unit, else the stored object (text, date). ``text`` is
    what is printed: a number with ``DIGITS`` significant digits, a whole number as is, a
    date as ISO, any other value as stored.
    """

    table: pd.DataFrame


def _text(value: Any) -> str:
    """Return a float with ``DIGITS`` significant digits, a whole number as is, a date as ISO."""
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if isinstance(value, np.float64):
        return (
            "n/a" if np.isnan(value) else (f"{value:.{DIGITS}g}" if value % 1 else f"{value:.0f}")
        )
    return str(value)


def data(subject: Run, panel: PanelRequest) -> TableData:
    """Read each named column through ``read_table`` and keep its one value.

    Each name of ``variable`` is ``table.column`` and has a row in ``COLUMN_REGISTRY``, else
    it is refused with the place to add one. The table is read once per table name. A
    column the table lacks is refused with the columns it holds. A
    table with more than one row is refused, pointing at a series or a groups
    panel. Any other panel field than ``variable`` is refused.
    """
    refuse_fields("table", panel, FIELDS)
    if not panel.variable:
        raise FigureNotApplicable("A table panel needs variable names written table.column.")
    tables: dict[str, pd.DataFrame] = {}
    rows = []
    for name in panel.variable:
        if name not in COLUMN_REGISTRY:
            raise FigureNotApplicable(unknown_column(name))
        table_name, _, column = name.partition(COLUMN_SEPARATOR)
        if table_name not in tables:
            tables[table_name] = read_table(subject, table_name)
        held = tables[table_name]
        if column not in held.columns:
            raise FigureNotApplicable(
                f"The table {table_name!r} has no column {column!r}. It holds: "
                f"{', '.join(map(str, held.columns))}."
            )
        if len(held) != 1:
            raise FigureNotApplicable(
                f"{name!r} has {len(held)} rows, so it is not one table cell. "
                "Use a series or a groups panel."
            )
        value = held[column].iloc[0]
        if isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool):
            value = np.float64(value)
        label = COLUMN_REGISTRY[name].label
        stored = column_unit(table_name, column)
        if stored and isinstance(value, np.float64):
            kind = kind_row(COLUMN_REGISTRY[name].quantity)
            value = np.float64(
                convert_between_units(float(value), from_unit=stored, to_unit=kind.display_unit)
            )
            unit = unit_text(kind.display_unit)
            label = f"{label} ({unit})" if unit else label
        rows.append((name, label, value, _text(value)))
    return TableData(table=pd.DataFrame(rows, columns=list(TABLE_COLUMNS)))


def draw(ax: Any, data: TableData, theme: Theme) -> None:
    """Draw two columns of text, the labels left aligned and the values right aligned.

    Axes are turned off. Rows are evenly spaced from the top, in the theme text
    size and ink, with a thin rule of the theme line width under each row, the last one
    included.
    Nothing else is drawn.
    """
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    rows = data.table
    step = 1 / max(len(rows), 1)
    for i, (label, text) in enumerate(zip(rows["label"], rows["text"], strict=True)):
        y = 1 - (i + 0.5) * step
        ax.text(0.0, y, label, ha="left", va="center", **static.text_style(theme))
        ax.text(1.0, y, text, ha="right", va="center", **static.text_style(theme))
        ax.plot(
            [0, 1], [1 - (i + 1) * step] * 2,
            color=theme.muted, linewidth=theme.line_width, alpha=0.5, solid_capstyle="butt",
        )  # fmt: skip
