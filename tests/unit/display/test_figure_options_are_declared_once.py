"""Every figure option says what it does, and every figure takes a title.

An option is a keyword parameter of a figure's ``render`` or ``plot``. Its
type, default, description and unit are declared on that parameter, and the
catalog of figures reads them from there. 63 of 70 figures had no word for
their options: this guards that none slips back.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.display import list_figures
from hydromodpy.display.figure import options_of
from hydromodpy.display.figure_options import COMMON_OPTIONS
from hydromodpy.display.figure_registry import figure_option_names, get
from hydromodpy.display.figures.difference_map import DifferenceMap
from hydromodpy.display.figures.piezometric_map import PiezometricMap
from hydromodpy.display.figures.side_by_side_map import SideBySideMapFigure
from hydromodpy.display.runs import render_figure

from .test_standard_figures import _Run


@pytest.fixture
def mpl():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


def _named_run(sim_id: str, name: str, values: list[float]) -> _Run:
    """A run as the catalog serves it: a sim_id and a name, no ``id``."""
    run = _Run(sim_id=sim_id, name=name, values=np.asarray(values))
    del run.id
    return run


@pytest.mark.parametrize("name", [spec.name for spec in list_figures()])
def test_every_option_of_every_figure_is_described(name: str) -> None:
    options = options_of(type(get(name)))

    assert {option.name for option in options} == set(figure_option_names(name))
    undescribed = [option.name for option in options if not option.description.strip()]
    assert not undescribed, f"{name}: options without a description: {undescribed}"
    assert set(COMMON_OPTIONS) <= {option.name for option in options}


def test_type_and_default_come_from_the_signature() -> None:
    options = {option.name: option for option in options_of(DifferenceMap)}

    assert options["cmap"].type == "str"
    assert options["cmap"].default == "'RdBu_r'"
    assert options["reference"].python_only
    assert options["time"].type == 'date, "first" or "last"'
    assert options["figsize"].unit == "in"


def test_the_catalog_reads_the_declared_options() -> None:
    from tools.docs.catalogs import figures

    rows = {row["name"]: row for row in figures()}
    tolerance = {o["name"]: o for o in rows["hydrographic_network_comparison"]["option_details"]}

    assert tolerance["tolerance_m"]["unit"] == "m"
    assert tolerance["tolerance_m"]["default"] == "50.0"
    assert tolerance["tolerance_m"]["doc"]
    assert all(o["doc"] for row in rows.values() for o in row["option_details"])


def test_the_difference_map_names_both_runs_and_never_an_id(mpl) -> None:
    run = _named_run("1f0c", "wet_year", [10.0, 12.0])
    reference = _named_run("9b7e", "dry_year", [9.0, 11.0])
    fig, ax = mpl.subplots()

    DifferenceMap().render(run, ax, reference=reference, field="watertable_elevation")

    title = ax.get_title()
    assert "wet_year" in title
    assert "dry_year" in title
    assert "1f0c" not in title
    assert "9b7e" not in title


def test_a_comparison_without_a_reference_is_skipped_not_failed(mpl) -> None:
    from hydromodpy.display.figure import FigureNotApplicable

    run = _named_run("1f0c", "wet_year", [10.0, 12.0])
    fig, ax = mpl.subplots()

    with pytest.raises(FigureNotApplicable, match="reference"):
        DifferenceMap().render(run, ax)
    with pytest.raises(FigureNotApplicable, match="reference"):
        SideBySideMapFigure().plot(run)


def test_show_run_name_off_keeps_the_run_out_of_every_title(mpl) -> None:
    run = _named_run("1f0c", "wet_year", [10.0, 12.0])
    reference = _named_run("9b7e", "dry_year", [9.0, 11.0])

    shown = PiezometricMap().plot(run)
    hidden = PiezometricMap().plot(run, show_run_name=False)
    pair = SideBySideMapFigure().plot(
        run, reference=reference, field="watertable_elevation", show_run_name=False
    )

    assert "wet_year" in shown.axes[0].get_title()
    assert "wet_year" not in hidden.axes[0].get_title()
    assert "Water-table elevation" in hidden.axes[0].get_title()
    titles = [axis.get_title() for axis in pair.axes if axis.get_title()]
    assert titles == ["Run", "Reference"]


def test_title_replaces_the_main_title_and_an_empty_one_removes_it(mpl) -> None:
    run = _named_run("1f0c", "wet_year", [10.0, 12.0])
    reference = _named_run("9b7e", "dry_year", [9.0, 11.0])

    titled = PiezometricMap().plot(run, title="Water table, October 2002")
    untitled = PiezometricMap().plot(run, title="")
    pair = SideBySideMapFigure().plot(
        run, reference=reference, field="watertable_elevation", title="Two runs"
    )

    assert titled.axes[0].get_title() == "Water table, October 2002"
    assert untitled.axes[0].get_title() == ""
    assert pair.get_suptitle() == "Two runs"


def test_render_figure_accepts_the_common_options(mpl, tmp_path) -> None:
    run = _named_run("1f0c", "wet_year", [10.0, 12.0])

    fig = render_figure("piezometric_map", run, save=tmp_path, title="Heads", show_run_name=False)

    assert fig.axes[0].get_title() == "Heads"
    assert (tmp_path / "piezometric_map.png").is_file()
