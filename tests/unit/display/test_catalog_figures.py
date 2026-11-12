"""Draw the figures of a run found through its project index."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.display import catalog_figures
from tests._helpers.one_run_catalog import Figure, OneRunCatalog, one_run_workspace


class _SealedRunCatalog(OneRunCatalog):
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


class _InstantFigure:
    """A map that draws one instant and records what it was asked for."""

    def __init__(self) -> None:
        self.drawn: list[dict] = []

    def unavailable_reason(self, sim: SimpleNamespace) -> None:
        return None

    def plot(self, sim, *, save_path: Path, timestep=None, orientation="we", **_) -> str:
        self.drawn.append({"timestep": timestep, "orientation": orientation})
        save_path.write_bytes(b"png")
        return "figure"


@pytest.mark.parametrize(("time", "step"), [(None, 33), ("first", 0)])
def test_a_redraw_applies_the_display_of_the_run_and_time_replaces_its_instant(
    monkeypatch, tmp_path, time, step
) -> None:
    figure = _InstantFigure()
    one_run_workspace(monkeypatch, tmp_path, figure)
    monkeypatch.setattr("hydromodpy.results.catalog.facade.Catalog", _SealedRunCatalog)

    catalog_figures.render_figure("abc123", "cross_section", workspace=tmp_path, time=time)

    assert figure.drawn == [{"timestep": step, "orientation": "sn"}]


def test_an_output_without_a_suffix_is_written_and_named_as_png(monkeypatch, tmp_path) -> None:
    figure = Figure()
    one_run_workspace(monkeypatch, tmp_path, figure)

    output = catalog_figures.render_figure(
        "abc123", "head_map", workspace=tmp_path, output=tmp_path / "maps" / "head"
    )

    assert output == tmp_path / "maps" / "head.png"
    assert figure.saved == [output]
    assert output.is_file()


class TestFigureOptionsFromTheCommandLine:
    """``hmp show REF --figure NAME --opt NAME=VALUE`` gives a figure its options, typed."""

    def test_values_take_the_type_of_the_option(self) -> None:
        options = catalog_figures.parse_figure_options(
            "watertable_depth_map",
            ["show_run_name=false", "title=Depth to water", "figsize=[6, 5]", "vmax=30"],
        )
        assert options == {
            "show_run_name": False,
            "title": "Depth to water",
            "figsize": (6.0, 5.0),
            "vmax": 30.0,
        }

    def test_a_quoted_text_is_read_as_text(self) -> None:
        options = catalog_figures.parse_figure_options("watertable_depth_map", ['title="true"'])
        assert options == {"title": "true"}

    @pytest.mark.parametrize(
        ("item", "message"),
        [
            ("show_run_name=maybe", "valid boolean"),
            ("color=red", "has no option 'color'; it takes:"),
            ("title", "write NAME=VALUE"),
            ("reference=other_run", "takes a Python object"),
        ],
    )
    def test_a_wrong_item_is_refused_by_name(self, item: str, message: str) -> None:
        figure = "difference_map" if item.startswith("reference") else "watertable_depth_map"
        with pytest.raises(ValueError, match=message):
            catalog_figures.parse_figure_options(figure, [item])

    def test_the_options_reach_the_figure(self, monkeypatch, tmp_path) -> None:
        figure = Figure()
        drawn: dict = {}
        one_run_workspace(monkeypatch, tmp_path, figure)
        monkeypatch.setattr(
            "hydromodpy.display.runs.render_figure",
            lambda name, sim, save=None, run_dir=None, **opts: drawn.update(opts),
        )

        catalog_figures.render_figure("abc", "head_map", options={"show_run_name": False})

        assert drawn == {"show_run_name": False}
