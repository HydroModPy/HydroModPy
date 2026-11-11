"""``hmp viz show`` and ``hmp viz list`` draw and list the figures of a run."""

from __future__ import annotations

import argparse
from pathlib import Path

from tests._helpers.cli_runner import CliRunner
from tests._helpers.one_run_catalog import Figure, one_run_workspace


def test_viz_show_passes_time_to_the_worker(monkeypatch) -> None:
    from hydromodpy.cli.commands.viz import show

    seen: dict[str, object] = {}

    def _worker(sim_ref, figure, **kwargs):
        seen.update(kwargs, sim_ref=sim_ref, figure=figure)
        return Path("out.png")

    monkeypatch.setattr("hydromodpy.display.catalog_figures.render_figure", _worker)
    parser = argparse.ArgumentParser()
    show.register(parser.add_subparsers())
    args = parser.parse_args(["show", "abc123", "seepage_map", "--time", "2002-10-15"])

    show.run(args)

    assert seen["time"] == "2002-10-15"
    assert seen["figure"] == "seepage_map"


def test_viz_show_names_the_file_it_wrote(monkeypatch, tmp_path) -> None:
    one_run_workspace(monkeypatch, tmp_path, Figure())

    result = CliRunner().invoke(
        ["viz", "show", "abc123", "head_map", "--to", str(tmp_path / "head")]
    )

    assert result.exit_code == 0
    assert f"wrote {tmp_path / 'head.png'}" in result.stderr


def test_viz_show_refuses_a_figure_the_run_cannot_feed(monkeypatch, tmp_path) -> None:
    figure = Figure(reason="missing result field(s): watertable_depth")
    one_run_workspace(monkeypatch, tmp_path, figure)

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
    monkeypatch.setattr("hydromodpy.display.catalog_figures.figure_availability", _availability)

    result = CliRunner().invoke(["viz", "list", "--run", "abc123"])

    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    assert lines[0].split() == ["piezometric_map", "spatial", "run", "available"]
    assert lines[1].split()[:3] == ["particle_tracks", "particles", "run"]
    assert lines[1].endswith("missing result field(s): particles")
    assert "2 figure(s), 1 available for abc123" in result.stdout


def test_viz_list_run_keeps_the_kind_filter(monkeypatch) -> None:
    monkeypatch.setattr("hydromodpy.display.catalog_figures.figure_availability", _availability)

    result = CliRunner().invoke(["viz", "list", "--run", "abc123", "--kind", "particles"])

    assert "piezometric_map" not in result.stdout
    assert "1 figure(s), 0 available for abc123" in result.stdout


def test_viz_list_run_maps_an_unknown_run_to_not_found(monkeypatch) -> None:
    from hydromodpy.results.catalog import SimulationNotFoundError

    def unknown(sim_ref: str, *, workspace: object = None):
        raise SimulationNotFoundError(f"Reference {sim_ref!r} not found.")

    monkeypatch.setattr("hydromodpy.display.catalog_figures.figure_availability", unknown)

    result = CliRunner().invoke(["viz", "list", "--run", "nope"])

    assert result.exit_code == 10
    assert "Reference 'nope' not found." in result.stderr
