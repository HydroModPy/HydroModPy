"""The new figure path wired into the config, the CLI, the run batch, the hooks and the planner."""

from __future__ import annotations

import subprocess
import sys
from argparse import Namespace
from types import SimpleNamespace

import pytest
from matplotlib.figure import Figure
from pydantic import ValidationError

from hydromodpy.cli.commands import show as cli
from hydromodpy.core.exceptions import CommandUsageError, DisplayError
from hydromodpy.display.config import DisplayConfig
from hydromodpy.results.run.group import RunSet
from hydromodpy.results.session.view import Session
from hydromodpy.solver.base.results_config import ResultsConfig
from hydromodpy.workflow.steps import display as batch
from hydromodpy.workflow.steps import planning

ACCEPTED = [
    {"figure": [{"variable": "recharge"}], "presets": {"mine": {"variable": "recharge"}}},
    {"theme": "default", "figure": [{"variable": "head", "name": "a"}, {"variable": "head"}]},
    {"preset": "dark"},
]
REFUSED = [
    ({"preset": "dark", "theme": "print"}, "display.theme"),
    ({"figure": [{"variable": "recharge"}, {"variable": "recharge"}]}, "recharge"),
    ({"theme": "neon"}, "neon"),
    ({"figure": [{"variable": "heed"}]}, "Did you mean head"),
    ({"figure": [{"preset": "nothing"}]}, "Unknown preset"),
    ({"presets": {"a": {"variable": "head"}, "b": {"preset": "a"}}}, "names another preset"),
    ({"presets": {"a": {"variable": "budget"}}}, "summed over a zone"),
]


@pytest.mark.parametrize("section", ACCEPTED)
def test_config_loads(section):
    assert DisplayConfig.model_validate(section).theme_name in ("default", "dark")


@pytest.mark.parametrize(("section", "named"), REFUSED)
def test_config_refuses_when_the_file_is_read(section, named):
    with pytest.raises((ValidationError, ValueError), match=named):
        DisplayConfig.model_validate(section)


@pytest.mark.allow_subprocess
def test_config_import_keeps_matplotlib_out():
    code = "import sys, hydromodpy.display.config; sys.exit('matplotlib' in sys.modules)"
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0


def test_holes_are_a_field_of_a_panel_and_not_of_a_figure():
    assert "holes" not in DisplayConfig.model_json_schema()["$defs"]["FigureRequest"]["properties"]


def args(**fields):
    base = {"figure": "head", "options": [], "time": None, "engine": None, "data": None, "to": None}
    return Namespace(**{**base, **fields})


def test_the_cli_draws_a_variable_and_writes_its_tables(stored_run, tmp_path, capsys):
    target = SimpleNamespace(directory=stored_run.dir, kind="run")
    cli._request_figure(args(options=["layer=1"], to=str(tmp_path / "h.png")), target, stored_run)
    assert (tmp_path / "h.png").exists()
    cli._request_figure(args(data=str(tmp_path / "d"), options=["time=-1"]), target, stored_run)
    assert [p.name for p in (tmp_path / "d").iterdir()] == ["head_a.csv"]


@pytest.mark.parametrize(
    "options", [["scale=sqrt"], ["nonsense"], ["layer=-1"], ["type=mapp"], ["variable=heed"]]
)
def test_a_bad_option_is_a_usage_error_in_one_line(stored_run, options, capsys):
    target = SimpleNamespace(directory=stored_run.dir, kind="run")
    with pytest.raises(SystemExit) as error:
        cli._request_figure(args(options=options), target, stored_run)
    assert (
        error.value.code == cli.EXIT_USAGE
        and len(capsys.readouterr().err.strip().splitlines()) == 1
    )


def test_a_save_that_is_not_a_figure_format_is_refused(stored_run, tmp_path):
    with pytest.raises(CommandUsageError, match="png"):
        stored_run.figure("head", save=tmp_path / "x.jpg")


BATCH = [
    ({"figure": [{"variable": "head", "name": "a"}]}, ["a.png"]),
    ({"figure": [{"variable": "head", "name": "a"}], "save": False}, []),
    ({"figure": [{"variable": "head", "name": "a", "when": "session"}]}, []),
    ({"figure": [{"variable": "head", "name": "a"}], "dpi": 40}, ["a.png"]),
]


@pytest.mark.parametrize(("section", "files"), BATCH)
def test_the_end_of_run_batch_honours_save_dpi_and_when(stored_run, tmp_path, section, files):
    config = DisplayConfig.model_validate(section)
    batch._render_requests(stored_run, config, output_dir=tmp_path)
    assert sorted(p.name for p in tmp_path.glob("*.png")) == files


def test_the_batch_follows_on_error(stored_run, tmp_path, caplog, monkeypatch):
    def broken(*_args, **_keywords):
        raise RuntimeError("boom")

    monkeypatch.setattr("hydromodpy.display.runs.render", broken)
    figure = [{"variable": "head", "name": "a"}]
    batch._render_requests(stored_run, DisplayConfig(figure=figure), output_dir=tmp_path)
    assert "Figure a failed: boom" in caplog.text
    strict = DisplayConfig(figure=figure, on_error="raise")
    with pytest.raises(DisplayError, match="run r1 is sealed"):
        batch._render_requests(stored_run, strict, output_dir=tmp_path, run_name="r1")
    with pytest.raises(RuntimeError, match="boom"):
        batch._render_requests(stored_run, strict, output_dir=tmp_path)


@pytest.mark.parametrize("kind", [Session, RunSet])
def test_a_session_and_a_set_draw_a_function_on_the_new_path(kind):
    from hydromodpy.project.show import render

    subject = object.__new__(kind)
    subject._render = render
    figure = subject.figure(draw=lambda s, ax, theme: ax.plot([0, 1]))
    assert isinstance(figure, Figure) and figure.axes[0].lines


def test_the_planner_keeps_every_budget_term_of_a_budget_request(monkeypatch):
    monkeypatch.setattr(planning, "_plan_has_surface_excess", lambda plan: False)
    display = DisplayConfig.model_validate(
        {"figure": [{"variable": "budget", "station": "zone:catchment"}]}
    )
    keep = planning.step_configure_results(
        ResultsConfig(keep_per_cell_budget=False),
        None,
        display,
        display_active=True,
        export_requests=[],
        calibration=None,
        observation=None,
    )
    assert keep.keeps("recharge") and keep.keeps("drain")
