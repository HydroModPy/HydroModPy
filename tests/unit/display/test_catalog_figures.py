"""Draw the figures of a run found through its project index."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.state.layout import RUNS_DIRNAME
from hydromodpy.display import catalog_figures
from hydromodpy.results.storage.contract import RUN_FIGURES_DIRNAME
from tests._helpers.one_run_catalog import Figure, OneRunCatalog, one_run_workspace


def test_render_figure_defaults_to_the_figures_dir_of_the_run(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "workspace"
    catalog_root = tmp_path / "catalog"
    run_dir = catalog_root / RUNS_DIRNAME / "sim_a"
    calls: dict[str, object] = {}

    class FakeCatalog:
        def __init__(self, root: Path) -> None:
            calls["catalog_root"] = root

        def __enter__(self):
            return self

        def __exit__(self, *exc_info: object) -> None:
            calls["closed"] = True

        def resolve(self, sim_ref: str) -> str:
            calls["sim_ref"] = sim_ref
            return "sim-001"

        def run_dir_for(self, sid: str) -> Path:
            calls["run_dir_for"] = sid
            return run_dir

        def __getitem__(self, sid: str) -> SimpleNamespace:
            calls["sim_id"] = sid
            return SimpleNamespace(name="sim-a")

    class FakeFigure:
        def unavailable_reason(self, sim: SimpleNamespace) -> None:
            return None

        def plot(self, sim: SimpleNamespace, *, save_path: Path, **opts: object) -> str:
            calls["plot"] = {"sim": sim.name, "save_path": save_path, "opts": opts}
            save_path.write_bytes(b"png")
            return "figure"

    def fake_resolve_project_root(start: Path) -> Path:
        calls["catalog_search_start"] = start
        return catalog_root

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "hydromodpy.core.state.result_dirs.resolve_project_root", fake_resolve_project_root
    )
    monkeypatch.setattr("hydromodpy.results.catalog.facade.Catalog", FakeCatalog)
    monkeypatch.setattr("hydromodpy.display.runs._get_figure", lambda name: FakeFigure())

    output = catalog_figures.render_figure("abc123", "head_map", workspace=workspace)

    expected_output = run_dir / RUN_FIGURES_DIRNAME / "head_map.png"
    assert output == expected_output
    assert calls == {
        "catalog_search_start": workspace.resolve(),
        "catalog_root": catalog_root,
        "sim_ref": "abc123",
        "run_dir_for": "sim-001",
        "sim_id": "sim-001",
        "plot": {"sim": "sim-a", "save_path": expected_output, "opts": {}},
        "closed": True,
    }
    assert expected_output.is_file()


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

    def test_an_empty_title_removes_it(self) -> None:
        assert catalog_figures.parse_figure_options("watertable_depth_map", ["title="]) == {
            "title": ""
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
