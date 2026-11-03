"""Unit tests for private ``hmp viz`` workers and wrappers."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from hydromodpy.cli._workers import viz as viz_worker
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.paths import RUNS_DIRNAME
from hydromodpy.display.runs import FigureRenderReport, SkippedFigure
from hydromodpy.results.storage.contract import RUN_FIGURES_DIRNAME
from tests._helpers.cli_runner import CliRunner


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
        "hydromodpy.core.state.paths.resolve_project_root", fake_resolve_project_root
    )
    monkeypatch.setattr("hydromodpy.results.catalog.Catalog", FakeCatalog)
    monkeypatch.setattr("hydromodpy.display.runs._get_figure", lambda name: FakeFigure())

    output = viz_worker.render_figure("abc123", "head_map", workspace=workspace)

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


class _OneRunCatalog:
    """A read-only catalog holding one run, the way ``hmp viz show`` opens it."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def __enter__(self):
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def resolve(self, sim_ref: str) -> str:
        return "sim-001"

    def run_dir_for(self, sid: str) -> Path:
        return self.root / RUNS_DIRNAME / "sim_a"

    def __getitem__(self, sid: str) -> SimpleNamespace:
        return SimpleNamespace(name="sim-a")


class _Figure:
    def __init__(self, reason: str | None = None) -> None:
        self.reason = reason
        self.saved: list[Path] = []

    def unavailable_reason(self, sim: SimpleNamespace) -> str | None:
        return self.reason

    def plot(self, sim: SimpleNamespace, *, save_path: Path, **opts: object) -> str:
        self.saved.append(save_path)
        save_path.write_bytes(b"png")
        return "figure"


def _one_run_workspace(monkeypatch, tmp_path: Path, figure: _Figure) -> None:
    monkeypatch.setattr("hydromodpy.core.state.paths.resolve_project_root", lambda start: tmp_path)
    monkeypatch.setattr("hydromodpy.results.catalog.Catalog", _OneRunCatalog)
    monkeypatch.setattr("hydromodpy.display.runs._get_figure", lambda name: figure)


class _SealedRunCatalog(_OneRunCatalog):
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
    _one_run_workspace(monkeypatch, tmp_path, figure)
    monkeypatch.setattr("hydromodpy.results.catalog.Catalog", _SealedRunCatalog)

    viz_worker.render_figure("abc123", "cross_section", workspace=tmp_path, time=time)

    assert figure.drawn == [{"timestep": step, "orientation": "sn"}]


def test_viz_show_passes_time_to_the_worker(monkeypatch) -> None:
    from hydromodpy.cli.commands.viz import show

    seen: dict[str, object] = {}

    def _worker(sim_ref, figure, **kwargs):
        seen.update(kwargs, sim_ref=sim_ref, figure=figure)
        return Path("out.png")

    monkeypatch.setattr("hydromodpy.cli._workers.viz.render_figure", _worker)
    parser = argparse.ArgumentParser()
    show.register(parser.add_subparsers())
    args = parser.parse_args(["show", "abc123", "seepage_map", "--time", "2002-10-15"])

    show.run(args)

    assert seen["time"] == "2002-10-15"
    assert seen["figure"] == "seepage_map"


def test_an_output_without_a_suffix_is_written_and_named_as_png(monkeypatch, tmp_path) -> None:
    figure = _Figure()
    _one_run_workspace(monkeypatch, tmp_path, figure)

    output = viz_worker.render_figure(
        "abc123", "head_map", workspace=tmp_path, output=tmp_path / "maps" / "head"
    )

    assert output == tmp_path / "maps" / "head.png"
    assert figure.saved == [output]
    assert output.is_file()


def test_viz_show_names_the_file_it_wrote(monkeypatch, tmp_path) -> None:
    _one_run_workspace(monkeypatch, tmp_path, _Figure())

    result = CliRunner().invoke(
        ["viz", "show", "abc123", "head_map", "--to", str(tmp_path / "head")]
    )

    assert result.exit_code == 0
    assert f"wrote {tmp_path / 'head.png'}" in result.stderr


def test_viz_show_refuses_a_figure_the_run_cannot_feed(monkeypatch, tmp_path) -> None:
    figure = _Figure(reason="missing result field(s): watertable_depth")
    _one_run_workspace(monkeypatch, tmp_path, figure)

    result = CliRunner().invoke(["viz", "show", "abc123", "head_map"])

    assert result.exit_code == 1
    assert (
        "figure 'head_map' does not apply to this run: missing result field(s): watertable_depth"
    ) in result.stderr
    assert figure.saved == []


def _availability(sim_ref: str, *, workspace: object = None):
    from hydromodpy.display.figure import FigureSpec

    return [
        (FigureSpec(name="piezometric_map", title="p", kind="spatial"), None),
        (
            FigureSpec(name="particle_tracks", title="t", kind="particles"),
            "missing result field(s): particles",
        ),
    ]


def test_viz_list_run_says_which_figures_the_run_supports(monkeypatch) -> None:
    monkeypatch.setattr("hydromodpy.cli._workers.viz.figure_availability", _availability)

    result = CliRunner().invoke(["viz", "list", "--run", "abc123"])

    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    assert lines[0].split() == ["piezometric_map", "spatial", "available"]
    assert lines[1].split()[:2] == ["particle_tracks", "particles"]
    assert lines[1].endswith("missing result field(s): particles")
    assert "2 figure(s), 1 available for abc123" in result.stdout


def test_viz_list_run_keeps_the_kind_filter(monkeypatch) -> None:
    monkeypatch.setattr("hydromodpy.cli._workers.viz.figure_availability", _availability)

    result = CliRunner().invoke(["viz", "list", "--run", "abc123", "--kind", "particles"])

    assert "piezometric_map" not in result.stdout
    assert "1 figure(s), 0 available for abc123" in result.stdout


def test_viz_list_run_maps_an_unknown_run_to_not_found(monkeypatch) -> None:
    from hydromodpy.results.catalog import SimulationNotFoundError

    def unknown(sim_ref: str, *, workspace: object = None):
        raise SimulationNotFoundError(f"Reference {sim_ref!r} not found.")

    monkeypatch.setattr("hydromodpy.cli._workers.viz.figure_availability", unknown)

    result = CliRunner().invoke(["viz", "list", "--run", "nope"])

    assert result.exit_code == 10
    assert "Reference 'nope' not found." in result.stderr


class TestFigureOptionsFromTheCommandLine:
    """``hmp viz show --opt NAME=VALUE`` gives a figure its options, typed."""

    def test_values_take_the_type_of_the_option(self) -> None:
        options = viz_worker.parse_figure_options(
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
        assert viz_worker.parse_figure_options("watertable_depth_map", ["title="]) == {"title": ""}

    def test_a_quoted_text_is_read_as_text(self) -> None:
        options = viz_worker.parse_figure_options("watertable_depth_map", ['title="true"'])
        assert options == {"title": "true"}

    @pytest.mark.parametrize(
        ("item", "message"),
        [
            ("show_run_name=maybe", "valid boolean"),
            ("colour=red", "has no option 'colour'; it takes:"),
            ("title", "write NAME=VALUE"),
            ("reference=other_run", "takes a Python object"),
        ],
    )
    def test_a_wrong_item_is_refused_by_name(self, item: str, message: str) -> None:
        figure = "difference_map" if item.startswith("reference") else "watertable_depth_map"
        with pytest.raises(ValueError, match=message):
            viz_worker.parse_figure_options(figure, [item])

    def test_the_options_reach_the_figure(self, monkeypatch, tmp_path) -> None:
        figure = _Figure()
        drawn: dict = {}
        _one_run_workspace(monkeypatch, tmp_path, figure)
        monkeypatch.setattr(
            "hydromodpy.display.runs.render_figure",
            lambda name, sim, save=None, run_dir=None, **opts: drawn.update(opts),
        )

        viz_worker.render_figure("abc", "head_map", options={"show_run_name": False})

        assert drawn == {"show_run_name": False}
