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
NAMES = [
    "simulation.n_cells", "simulation.period_start", "simulation.solver", "simulation.n_layers",
]  # fmt: skip


def data(run, *names, **panel):
    return table.data(run, PanelRequest(type="table", variable=list(names), **panel))


def test_a_row_holds_the_stored_value_and_its_printed_text(stored_run):
    stored = read_table(stored_run, "simulation").iloc[0]
    out = data(stored_run, *NAMES).table
    assert list(out["variable"]) == NAMES and list(out["label"])[:1] == ["Model cells"]
    assert out["value"].iloc[0] == stored["n_cells"] and isinstance(
        out["value"].iloc[0], np.float64
    )
    assert list(out["text"]) == [
        str(int(stored["n_cells"])), stored["period_start"].date().isoformat(), stored["solver"],
        str(int(stored["n_layers"])),
    ]  # fmt: skip


@pytest.mark.parametrize(
    ("names", "panel", "word"),
    [
        (["simulation.nothing"], {}, "Add a row"),  # says where the row goes
        (["simulation.nse"], {}, "COLUMN_REGISTRY"),
        (["budgets.flux_in", "simulation.solver"], {}, "COLUMN_REGISTRY"),
        (["simulation.solver"], {"station": "x"}, "does not take"),
        ([], {}, "needs variable names"),
        (["sfr_reaches.strahler"], {}, "3 rows"),
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


class WithTable:
    """A run whose ``simulation`` table is replaced, every other read going to the run."""

    def __init__(self, run, frame):
        self._run, self._frame = run, frame

    def table(self, name):
        return self._frame if name == "simulation" else self._run.table(name)

    def __getattr__(self, name):
        return getattr(self._run, name)


def test_a_registered_column_the_stored_table_lacks_is_refused_with_what_it_holds(stored_run):
    bare = read_table(stored_run, "simulation").drop(columns="solver")
    with pytest.raises(FigureNotApplicable, match="has no column 'solver'. It holds: "):
        data(WithTable(stored_run, bare), "simulation.solver")
