"""The table frame on the small stored run: the rows of ``data`` and what ``draw`` writes."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.display import static
from hydromodpy.display.frames import table
from hydromodpy.display.request import PanelRequest
from hydromodpy.display.subject import FigureNotApplicable, read_table
from hydromodpy.display.theme import THEMES

THEME = THEMES["default"]
NAMES = ["simulation.n_cells", "simulation.period_start", "simulation.solver", "simulation.nse"]


def data(run, *names, **panel):
    return table.data(run, PanelRequest(type="table", variable=list(names), **panel))


def test_a_row_holds_the_stored_value_and_its_printed_text(stored_run):
    stored = read_table(stored_run, "simulation").iloc[0]
    out = data(stored_run, *NAMES).table
    assert list(out["variable"]) == NAMES and list(out["label"])[:1] == ["N cells"]
    assert out["value"].iloc[0] == stored["n_cells"] and isinstance(
        out["value"].iloc[0], np.float64
    )
    nse = stored["nse"]
    assert list(out["text"]) == [
        str(int(stored["n_cells"])), stored["period_start"].date().isoformat(), stored["solver"],
        "n/a" if np.isnan(nse) else f"{nse:.3g}",
    ]  # fmt: skip


@pytest.mark.parametrize(
    ("names", "panel", "word"),
    [
        (["simulation.nothing"], {}, "n_cells"),  # names the columns the table holds
        (["nothing.solver"], {}, ""),
        (["budgets.flux_in", "simulation.solver"], {}, "rows"),
        (["simulation.solver"], {"station": "x"}, "does not take"),
    ],
)
def test_a_column_the_table_cannot_give_is_refused(stored_run, names, panel, word):
    with pytest.raises(FigureNotApplicable, match=word):
        data(stored_run, *names, **panel)


def test_draw_adds_one_text_per_cell(stored_run):
    ax = static.new_figure(THEME).axes[0]
    out = data(stored_run, *NAMES)
    table.draw(ax, out, THEME)
    assert len(ax.texts) == 2 * len(NAMES) and len(ax.lines) == len(NAMES)
    assert not ax.axison
