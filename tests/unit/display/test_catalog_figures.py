"""Redraw the figure of a run found through its project index.

A redraw applies the ``[display]`` block sealed with the run. The command line
(``hmp show REF --figure NAME --opt NAME=VALUE``) gives a figure typed options.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.display import catalog_figures
from tests._helpers.one_run_catalog import Figure, OneRunCatalog, one_run_workspace


class SealedRunCatalog(OneRunCatalog):
    """One run whose sealed ``[display]`` names October and a south-north cut."""

    def __getitem__(self, sid: str) -> SimpleNamespace:
        from hydromodpy.display.config import DisplayConfig

        display = DisplayConfig().model_dump(mode="json")
        display.update(time="2002-10-15", overrides={"cross_section": {"orientation": "sn"}})
        return SimpleNamespace(
            name="sim-a",
            config_snapshot={"display": display},
            periods=SimpleNamespace(step_at=lambda time: {"2002-10-15": 33, "first": 0}[time]),
        )


class InstantFigure:
    """A map that draws one instant and records what it was asked for."""

    def __init__(self) -> None:
        self.drawn: list[dict] = []

    def unavailable_reason(self, sim: SimpleNamespace) -> None:
        return None

    def plot(self, sim, *, save_path: Path, timestep=None, orientation="we", **_) -> str:
        self.drawn.append({"timestep": timestep, "orientation": orientation})
        save_path.write_bytes(b"png")
        return "figure"


@pytest.mark.parametrize(
    ("time", "step"),
    [
        pytest.param(None, 33, id="sealed instant"),
        pytest.param("first", 0, id="time replaces the sealed instant"),
    ],
)
def test_redraw_applies_the_sealed_display(monkeypatch, tmp_path, time, step) -> None:
    figure = InstantFigure()
    one_run_workspace(monkeypatch, tmp_path, figure)
    monkeypatch.setattr("hydromodpy.results.catalog.facade.Catalog", SealedRunCatalog)

    catalog_figures.render_figure("abc123", "cross_section", workspace=tmp_path, time=time)

    assert figure.drawn == [{"timestep": step, "orientation": "sn"}]


def test_output_without_a_suffix_is_named_png(monkeypatch, tmp_path) -> None:
    figure = Figure()
    one_run_workspace(monkeypatch, tmp_path, figure)

    output = catalog_figures.render_figure(
        "abc123", "head_map", workspace=tmp_path, output=tmp_path / "maps" / "head"
    )

    assert output == tmp_path / "maps" / "head.png"
    assert figure.saved == [output]
    assert output.is_file()


OPTIONS = [
    pytest.param(
        ["show_run_name=false", "title=Depth to water", "figsize=[6, 5]", "vmax=30"],
        {"show_run_name": False, "title": "Depth to water", "figsize": (6.0, 5.0), "vmax": 30.0},
        id="typed by the option",
    ),
    pytest.param(['title="true"'], {"title": "true"}, id="quoted text stays text"),
]


@pytest.mark.parametrize(("items", "expected"), OPTIONS)
def test_options_take_the_type_of_the_option(items, expected) -> None:
    assert catalog_figures.parse_figure_options("watertable_depth_map", items) == expected


REFUSALS = [
    pytest.param("watertable_depth_map", "show_run_name=maybe", "valid boolean", id="bad boolean"),
    pytest.param(
        "watertable_depth_map", "color=red", "has no option 'color'; it takes:", id="unknown option"
    ),
    pytest.param("watertable_depth_map", "title", "write NAME=VALUE", id="no value"),
    pytest.param("difference_map", "reference=other_run", "takes a Python object", id="object"),
]


@pytest.mark.parametrize(("figure", "item", "message"), REFUSALS)
def test_refusals(figure, item, message) -> None:
    with pytest.raises(ValueError, match=message):
        catalog_figures.parse_figure_options(figure, [item])


def test_options_reach_the_figure(monkeypatch, tmp_path) -> None:
    drawn: dict = {}
    one_run_workspace(monkeypatch, tmp_path, Figure())
    monkeypatch.setattr(
        "hydromodpy.display.runs.render_figure",
        lambda name, sim, save=None, run_dir=None, **opts: drawn.update(opts),
    )

    catalog_figures.render_figure("abc", "head_map", options={"show_run_name": False})

    assert drawn == {"show_run_name": False}
