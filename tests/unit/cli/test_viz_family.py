"""``hmp show --figure`` draws a figure of a run, ``hmp config figures`` lists the figures."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._helpers.cli_runner import CliRunner
from tests._helpers.one_run_catalog import Figure
from tests._helpers.sealed_runs import make_project, seal_run


def _png(path: Path) -> Path:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (4, 4), "white").save(path)
    return path


class PngFigure(Figure):
    """The figure of the helper, drawing a PNG that reads back."""

    def plot(self, sim, *, save_path: Path, **opts: object) -> str:
        self.saved.append(save_path)
        _png(save_path)
        return "figure"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = make_project(tmp_path / "demo")
    seal_run(root, "alpha")
    return root


def test_show_figure_passes_time_and_name_to_the_verb(monkeypatch, project: Path) -> None:
    seen: dict[str, object] = {}

    def verb(ref, **kwargs):
        seen.update(kwargs, ref=ref)
        return _png(Path(kwargs["save"]))

    monkeypatch.setattr("hydromodpy.project.api.show", verb)

    result = CliRunner().invoke(
        ["show", "alpha", "--figure", "seepage_map", "--time", "2002-10-15", "-w", str(project)]
    )

    assert result.exit_code == 0, result.stderr
    assert seen["what"] == "figure"
    assert seen["name"] == "seepage_map"
    assert seen["time"] == "2002-10-15"
    assert Path(seen["save"]) == project / "runs" / "alpha" / "figures" / "seepage_map.png"


def test_show_figure_names_the_file_it_wrote(monkeypatch, project: Path, tmp_path: Path) -> None:
    figure = PngFigure()
    monkeypatch.setattr("hydromodpy.display.runs._get_figure", lambda name: figure)

    result = CliRunner().invoke(
        [
            "show",
            "alpha",
            "--figure",
            "head_map",
            "--to",
            str(tmp_path / "head"),
            "-w",
            str(project),
        ]
    )

    assert result.exit_code == 0, result.stderr
    assert f"wrote {tmp_path / 'head.png'}" in result.stderr
    assert figure.saved == [tmp_path / "head.png"]


def test_show_figure_refuses_a_figure_the_run_cannot_feed(monkeypatch, project: Path) -> None:
    figure = Figure(reason="missing result field(s): watertable_depth")
    monkeypatch.setattr("hydromodpy.display.runs._get_figure", lambda name: figure)

    result = CliRunner().invoke(["show", "alpha", "--figure", "head_map", "-w", str(project)])

    assert result.exit_code == 1
    assert (
        "figure 'head_map' does not apply to this run: missing result field(s): watertable_depth"
    ) in result.stderr
    assert figure.saved == []


def test_show_figure_refuses_the_project(project: Path) -> None:
    result = CliRunner().invoke(["show", "--figure", "head_map", "-w", str(project)])

    assert result.exit_code == 2
    assert "draws a run or a session" in result.stderr


def _availability(sim_ref: str, *, workspace: object = None):
    from hydromodpy.display.figure import FigureSpec

    return [
        (FigureSpec(name="piezometric_map", title="p", kind="spatial"), None),
        (
            FigureSpec(name="particle_tracks", title="t", kind="particles"),
            "missing result field(s): particles",
        ),
    ]


def test_config_figures_run_says_which_figures_the_run_supports(monkeypatch) -> None:
    monkeypatch.setattr("hydromodpy.display.catalog_figures.figure_availability", _availability)

    result = CliRunner().invoke(["config", "figures", "--run", "abc123"])

    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    assert lines[0].split() == ["piezometric_map", "spatial", "run", "available"]
    assert lines[1].split()[:3] == ["particle_tracks", "particles", "run"]
    assert lines[1].endswith("missing result field(s): particles")
    assert "2 figure(s), 1 available for abc123" in result.stdout


def test_config_figures_run_keeps_the_kind_filter(monkeypatch) -> None:
    monkeypatch.setattr("hydromodpy.display.catalog_figures.figure_availability", _availability)

    result = CliRunner().invoke(["config", "figures", "--run", "abc123", "--kind", "particles"])

    assert "piezometric_map" not in result.stdout
    assert "1 figure(s), 0 available for abc123" in result.stdout


def test_config_figures_run_maps_an_unknown_run_to_not_found(monkeypatch) -> None:
    from hydromodpy.results.catalog.discovery import SimulationNotFoundError

    def unknown(sim_ref: str, *, workspace: object = None):
        raise SimulationNotFoundError(f"Reference {sim_ref!r} not found.")

    monkeypatch.setattr("hydromodpy.display.catalog_figures.figure_availability", unknown)

    result = CliRunner().invoke(["config", "figures", "--run", "nope"])

    assert result.exit_code == 10
    assert "Reference 'nope' not found." in result.stderr


def test_config_figures_lists_the_registered_figures() -> None:
    result = CliRunner().invoke(["config", "figures", "--format", "json"])

    assert result.exit_code == 0
    assert '"schema": "hmp.config.figures.v2"' in result.stdout
