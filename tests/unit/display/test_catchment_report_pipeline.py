from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.core.exceptions import ConfigValidationError
from hydromodpy.core.state.layout import runs_dir_for
from hydromodpy.display.catchment_report.inputs import CatchmentReportInputs
from hydromodpy.display.catchment_report.pipeline import (
    CatchmentReportPipelineResult,
    CatchmentReportPreflightError,
    run_catchment_report_pipeline,
)
from hydromodpy.results.storage.contract import RUN_FIGURES_DIRNAME


def _make_run_figures_dir(workspace: Path, run_name: str) -> Path:
    """Create ``<workspace>/runs/<run>/figures``, where the report reads them."""
    figures = runs_dir_for(workspace) / run_name / RUN_FIGURES_DIRNAME
    figures.mkdir(parents=True, exist_ok=True)
    return figures


class _CompletedRun:
    returncode = 0
    stdout = ""
    stderr = ""

    def check_returncode(self) -> None:
        return None


def _write_report_config(config_path: Path, *, pipeline: str = "") -> None:
    config_path.write_text(
        f"""
[report]
site_label = "Test"
station_label = "Test outlet"

[layout]
watershed_project_dir = "."
simulation_workspace_dir = "sim_workspace"
simulation_name = "test_run"
transient_config_name = "run_test.toml"
{pipeline}
""".lstrip(),
        encoding="utf-8",
    )


def _write_catalog_run(workspace: Path, name: str) -> None:
    """Seal one run with a discharge series, what the report reads, and index it.

    A versioned *name* (``test_run.v2``) is reached the way the disk gives it: the
    bare name is claimed again and takes the next free version, which must be the
    one asked for.
    """
    from hydromodpy.results.catalog.registration import split_stem_version
    from tests._helpers.run_stores import seal_demo_run

    stem, _version = split_stem_version(name)
    run_dir, _sim_id = seal_demo_run(workspace, stem)
    assert run_dir.name == name, f"the disk gave {run_dir.name}, the test asked for {name}"


def _write_transient_config(root: Path) -> None:
    (root / "run_test.toml").write_text("[simulation]\n", encoding="utf-8")


def _write_overview_config(root: Path) -> None:
    (root / "config_overview.toml").write_text(
        '[site]\nname = "test"\n\n[overview]\n', encoding="utf-8"
    )


def test_run_simulation_validates_expected_report_outputs(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "catchment_report.toml"
    _write_report_config(config_path)
    _write_transient_config(tmp_path)
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return _CompletedRun()

    monkeypatch.setattr(
        "hydromodpy.display.catchment_report.pipeline.subprocess.run",
        fake_run,
    )

    with pytest.raises(FileNotFoundError) as exc_info:
        run_catchment_report_pipeline(
            config_path,
            run_simulation=True,
            build_context_artifacts=False,
            build_report_html=False,
        )

    assert calls
    assert calls[0][0][-2:] == ["run", str(tmp_path / "run_test.toml")]
    assert calls[0][1]["capture_output"] is True
    assert calls[0][1]["encoding"] == "utf-8"
    assert calls[0][1]["errors"] == "replace"
    assert calls[0][1]["text"] is True
    message = str(exc_info.value)
    assert "simulation run 'test_run'" in message
    assert "simulation figures directory" in message


def test_run_simulation_accepts_expected_report_outputs(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "catchment_report.toml"
    _write_report_config(config_path)
    _write_transient_config(tmp_path)
    _write_catalog_run(tmp_path / "sim_workspace", "test_run")
    _make_run_figures_dir(tmp_path / "sim_workspace", "test_run")

    monkeypatch.setattr(
        "hydromodpy.display.catchment_report.pipeline.subprocess.run",
        lambda command, **kwargs: _CompletedRun(),
    )

    result = run_catchment_report_pipeline(
        config_path,
        run_simulation=True,
        build_context_artifacts=False,
        build_report_html=False,
    )

    assert result.simulation_config == tmp_path / "run_test.toml"
    assert result.context_summary is None
    assert result.html_report is None


def test_pipeline_toml_can_command_simulation_and_report_steps(
    monkeypatch,
    tmp_path,
) -> None:
    config_path = tmp_path / "catchment_report.toml"
    _write_report_config(
        config_path,
        pipeline="""
[pipeline]
run_simulation = true
build_context_artifacts = false
build_report_html = false
""",
    )
    _write_transient_config(tmp_path)
    _write_catalog_run(tmp_path / "sim_workspace", "test_run")
    _make_run_figures_dir(tmp_path / "sim_workspace", "test_run")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return _CompletedRun()

    monkeypatch.setattr(
        "hydromodpy.display.catchment_report.pipeline.subprocess.run",
        fake_run,
    )

    result = run_catchment_report_pipeline(config_path)

    assert result.simulation_config == tmp_path / "run_test.toml"
    assert result.context_summary is None
    assert result.html_report is None
    assert calls
    assert calls[0][1]["capture_output"] is True


def test_the_retired_no_lock_key_is_refused_with_what_to_do(tmp_path) -> None:
    config_path = tmp_path / "catchment_report.toml"
    _write_report_config(config_path, pipeline="\n[pipeline]\nno_lock = true\n")
    _write_transient_config(tmp_path)

    with pytest.raises(ConfigValidationError, match="no lockfile") as exc_info:
        run_catchment_report_pipeline(config_path)

    assert "Delete the line" in str(exc_info.value)


def test_pipeline_can_stream_run_logs_from_toml(
    monkeypatch,
    tmp_path,
) -> None:
    config_path = tmp_path / "catchment_report.toml"
    _write_report_config(
        config_path,
        pipeline="""
[pipeline]
run_simulation = true
build_context_artifacts = false
build_report_html = false
stream_run_logs = true
""",
    )
    _write_transient_config(tmp_path)
    _write_catalog_run(tmp_path / "sim_workspace", "test_run")
    _make_run_figures_dir(tmp_path / "sim_workspace", "test_run")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return None

    monkeypatch.setattr(
        "hydromodpy.display.catchment_report.pipeline.subprocess.run",
        fake_run,
    )

    result = run_catchment_report_pipeline(config_path)

    assert result.simulation_config == tmp_path / "run_test.toml"
    assert calls
    assert calls[0][1]["check"] is True
    assert "capture_output" not in calls[0][1]


def test_pipeline_runs_overview_before_simulation_from_toml(
    monkeypatch,
    tmp_path,
) -> None:
    config_path = tmp_path / "catchment_report.toml"
    _write_report_config(
        config_path,
        pipeline="""
[pipeline]
run_overview = true
run_simulation = true
build_context_artifacts = false
build_report_html = false
""",
    )
    _write_overview_config(tmp_path)
    _write_transient_config(tmp_path)
    _write_catalog_run(tmp_path / "sim_workspace", "test_run")
    _make_run_figures_dir(tmp_path / "sim_workspace", "test_run")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return _CompletedRun()

    monkeypatch.setattr(
        "hydromodpy.display.catchment_report.pipeline.subprocess.run",
        fake_run,
    )

    result = run_catchment_report_pipeline(config_path)

    assert result.overview_config == tmp_path / "config_overview.toml"
    assert result.simulation_config == tmp_path / "run_test.toml"
    assert [Path(command[4]) for command, _kwargs in calls] == [
        tmp_path / "config_overview.toml",
        tmp_path / "run_test.toml",
    ]


def test_preflight_reports_missing_simulation_config_before_run(
    monkeypatch,
    tmp_path,
) -> None:
    config_path = tmp_path / "catchment_report.toml"
    _write_report_config(config_path)
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return _CompletedRun()

    monkeypatch.setattr(
        "hydromodpy.display.catchment_report.pipeline.subprocess.run",
        fake_run,
    )

    with pytest.raises(CatchmentReportPreflightError) as exc_info:
        run_catchment_report_pipeline(
            config_path,
            run_simulation=True,
            build_context_artifacts=False,
            build_report_html=False,
        )

    assert calls == []
    assert "simulation config" in str(exc_info.value)


def test_preflight_reports_missing_context_for_report_only(tmp_path) -> None:
    config_path = tmp_path / "catchment_report.toml"
    _write_report_config(config_path)
    _write_transient_config(tmp_path)
    _write_overview(tmp_path)
    _make_run_figures_dir(tmp_path / "sim_workspace", "test_run")

    with pytest.raises(CatchmentReportPreflightError) as exc_info:
        run_catchment_report_pipeline(
            config_path,
            run_simulation=False,
            build_context_artifacts=False,
            build_report_html=True,
        )

    message = str(exc_info.value)
    assert "context summary" in message
    assert "simulation run 'test_run'" in message


def test_missing_optional_observed_discharge_does_not_block_context_build(
    monkeypatch,
    tmp_path,
) -> None:
    config_path = tmp_path / "catchment_report.toml"
    config_path.write_text(
        """
[report]
site_label = "Test"
station_label = "Test outlet"

[layout]
watershed_project_dir = "."
simulation_workspace_dir = "sim_workspace"
simulation_name = "test_run"
transient_config_name = "run_test.toml"

[context.observed_discharge]
path = "missing_observed.csv"
""".lstrip(),
        encoding="utf-8",
    )
    _write_transient_config(tmp_path)
    _write_catalog_run(tmp_path / "sim_workspace", "test_run")
    context_summary = (
        runs_dir_for(tmp_path / "sim_workspace")
        / "test_run"
        / "report"
        / "context"
        / "test_gauged_context_summary.json"
    )

    def fake_build_context(inputs, *, root=None):
        assert inputs.context_summary == context_summary
        context_summary.parent.mkdir(parents=True)
        context_summary.write_text("{}\n", encoding="utf-8")
        return context_summary

    monkeypatch.setattr(
        "hydromodpy.display.catchment_report.pipeline.build_context",
        fake_build_context,
    )

    result = run_catchment_report_pipeline(
        config_path,
        run_simulation=False,
        build_context_artifacts=True,
        build_report_html=False,
    )

    assert result.context_summary == context_summary


def test_pipeline_writes_postflight_report_after_html(
    monkeypatch,
    tmp_path,
) -> None:
    config_path = tmp_path / "catchment_report.toml"
    _write_report_config(config_path)
    _write_transient_config(tmp_path)
    _write_catalog_run(tmp_path / "sim_workspace", "test_run")
    report = runs_dir_for(tmp_path / "sim_workspace") / "test_run" / "report"
    (report / "context").mkdir(parents=True)
    (report / "context" / "test_gauged_context_summary.json").write_text(
        "{}\n",
        encoding="utf-8",
    )
    (report / "context" / "web" / "assets").mkdir(parents=True)
    _write_overview(tmp_path)
    _make_run_figures_dir(tmp_path / "sim_workspace", "test_run")
    html_path = report / "index.html"
    postflight_path = report / "block_report_postflight.json"
    captured = {}

    def fake_build(config):
        captured["build_config"] = config
        assert config.output_dir == report
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text("<html></html>\n", encoding="utf-8")
        return html_path

    def fake_postflight(config, *, strict: bool):
        captured["postflight_config"] = config
        captured["strict"] = strict
        postflight_path.parent.mkdir(parents=True, exist_ok=True)
        postflight_path.write_text("{}\n", encoding="utf-8")
        return postflight_path

    monkeypatch.setattr(
        "hydromodpy.display.catchment_report.pipeline.build_catchment_report",
        fake_build,
    )
    monkeypatch.setattr(
        "hydromodpy.display.catchment_report.pipeline.write_figure_postflight_report",
        fake_postflight,
    )

    result = run_catchment_report_pipeline(
        config_path,
        run_simulation=False,
        build_context_artifacts=False,
        build_report_html=True,
        strict_figure_postflight=True,
    )

    assert result.html_report == html_path
    assert result.postflight_report == postflight_path
    assert captured["postflight_config"] is captured["build_config"]
    assert captured["strict"] is True


def test_a_rerun_reads_the_newest_completed_version(
    monkeypatch,
    tmp_path,
) -> None:
    # A completed run keeps its name, so the rerun lands under `test_run.v2`.
    # The report must describe that run, not the first one's figures.
    config_path = tmp_path / "catchment_report.toml"
    _write_report_config(config_path)
    _write_transient_config(tmp_path)
    workspace = tmp_path / "sim_workspace"
    _write_catalog_run(workspace, "test_run")
    _write_catalog_run(workspace, "test_run.v2")
    figures = _make_run_figures_dir(workspace, "test_run.v2")

    monkeypatch.setattr(
        "hydromodpy.display.catchment_report.pipeline.subprocess.run",
        lambda command, **kwargs: _CompletedRun(),
    )

    run_catchment_report_pipeline(
        config_path,
        run_simulation=True,
        build_context_artifacts=False,
        build_report_html=False,
    )

    from hydromodpy.display.catchment_report.inputs import CatchmentReportInputs
    from hydromodpy.display.catchment_report.simulation_source import newest_completed_run_name

    inputs = CatchmentReportInputs.from_toml(config_path)
    name = newest_completed_run_name(inputs)
    assert name == "test_run.v2"
    assert inputs.with_simulation_name(name).simulation_figures == figures


def test_a_name_pinned_to_a_version_is_read_as_written(tmp_path) -> None:
    # Only a bare name follows the newest completed run: `test_run.v2` written
    # in the report config means that run, even when `test_run.v3` is newer.
    from dataclasses import replace

    from hydromodpy.display.catchment_report.inputs import CatchmentReportInputs
    from hydromodpy.display.catchment_report.simulation_source import newest_completed_run_name

    config_path = tmp_path / "catchment_report.toml"
    _write_report_config(config_path)
    _write_transient_config(tmp_path)
    workspace = tmp_path / "sim_workspace"
    for name in ("test_run", "test_run.v2", "test_run.v3"):
        _write_catalog_run(workspace, name)

    inputs = CatchmentReportInputs.from_toml(config_path)
    assert newest_completed_run_name(inputs) == "test_run.v3"
    assert newest_completed_run_name(replace(inputs, simulation_name="test_run.v2")) is None


def _write_overview(root: Path) -> None:
    """Write the overview configuration of the report and the panels folder it names."""
    (root / "config_overview.toml").write_text('[site]\nname = "test"\n', encoding="utf-8")
    (runs_dir_for(root) / "test" / "figures").mkdir(parents=True)


# --------------------------------------------------------------------------- #
# the run figures the report needs are drawn when the run lacks them
# --------------------------------------------------------------------------- #

RUN_FIGURES = (
    "simulated_active_network_reference_overlay",
    "piezometric_map",
    "seepage_map",
    "hydrograph",
    "water_budget",
)


def _report_inputs(tmp_path: Path):
    """Inputs of a report on a freshly sealed run that drew no figure."""
    config_path = tmp_path / "catchment_report.toml"
    _write_report_config(config_path)
    _write_transient_config(tmp_path)
    _write_catalog_run(tmp_path / "sim_workspace", "test_run")
    return CatchmentReportInputs.from_toml(config_path)


def test_the_run_figures_of_the_report_are_the_registered_names_of_its_artifacts() -> None:
    from hydromodpy.display.catchment_report.artifacts import run_figure_names

    assert set(run_figure_names()) == set(RUN_FIGURES)


def test_only_the_figures_the_run_lacks_are_drawn_with_its_sealed_display(
    monkeypatch, tmp_path
) -> None:
    from types import SimpleNamespace

    from hydromodpy.display.catchment_report.artifacts import draw_missing_run_figures
    from hydromodpy.display.runs import FigureRenderReport

    inputs = _report_inputs(tmp_path)
    inputs.simulation_figures.mkdir(parents=True, exist_ok=True)
    (inputs.simulation_figures / "hydrograph.png").write_bytes(b"drawn by the run")
    sealed = {
        "preset": "print",
        "dpi": 90,
        "cmap": "viridis",
        "enabled": False,
        "show": True,
        "on_error": "raise",
        "figures": ["hydrograph"],
    }
    run = SimpleNamespace(config_snapshot={"display": sealed})
    opened = []
    asked = []

    def fake_open(run_dir):
        opened.append(run_dir)
        return run

    def fake_render(sim, display_cfg, *, output_dir, figure_names):
        asked.append((sim, display_cfg, output_dir, list(figure_names)))
        return FigureRenderReport(rendered=tuple(figure_names))

    monkeypatch.setattr("hydromodpy.results.run.view.open_run_dir", fake_open)
    monkeypatch.setattr("hydromodpy.display.runs.render_figures_for_run", fake_render)

    drawn = draw_missing_run_figures(inputs)

    expected = tuple(name for name in RUN_FIGURES if name != "hydrograph")
    assert set(drawn) == set(expected)
    assert opened == [inputs.run_dir]
    ((sim, cfg, output_dir, names),) = asked
    assert sim is run
    assert output_dir == inputs.simulation_figures
    assert set(names) == set(expected)
    # The style of the run is kept, and the report still draws, headless.
    assert (cfg.preset, cfg.dpi) == ("print", 90)
    assert cfg.figures == names
    assert (cfg.enabled, cfg.save, cfg.show, cfg.on_error) == (True, True, False, "warn")
    # A colormap left at its default is not forced on every figure.
    assert "cmap" not in cfg.model_fields_set


def test_a_report_with_every_run_figure_does_not_open_the_run(monkeypatch, tmp_path) -> None:
    from hydromodpy.display.catchment_report.artifacts import draw_missing_run_figures

    inputs = _report_inputs(tmp_path)
    inputs.simulation_figures.mkdir(parents=True, exist_ok=True)
    for name in RUN_FIGURES:
        (inputs.simulation_figures / f"{name}.png").write_bytes(b"png")

    def refuse(run_dir):
        raise AssertionError("the run is not opened when no figure is missing")

    monkeypatch.setattr("hydromodpy.results.run.view.open_run_dir", refuse)

    assert draw_missing_run_figures(inputs) == ()


def test_a_run_that_cannot_be_opened_leaves_its_blocks_empty_and_says_so(
    monkeypatch, tmp_path, hmp_log_records
) -> None:
    from hydromodpy.display.catchment_report.artifacts import draw_missing_run_figures

    inputs = _report_inputs(tmp_path)

    def broken(run_dir):
        raise OSError("seal unreadable")

    monkeypatch.setattr("hydromodpy.results.run.view.open_run_dir", broken)

    assert draw_missing_run_figures(inputs) == ()
    assert any("seal unreadable" in record.getMessage() for record in hmp_log_records)


def test_the_figures_of_a_sealed_run_are_drawn_into_its_figures_folder(tmp_path) -> None:
    from hydromodpy.display.catchment_report.artifacts import draw_missing_run_figures
    from hydromodpy.results.record.manifest import seal_problems

    inputs = _report_inputs(tmp_path)

    drawn = draw_missing_run_figures(inputs)

    assert "hydrograph" in drawn
    for name in drawn:
        assert (inputs.simulation_figures / f"{name}.png").is_file()
    # figures/ is outside the seal: the run still reads as it was sealed.
    assert seal_problems(inputs.run_dir) == []


def test_the_pipeline_draws_the_run_figures_before_it_builds_the_context(
    monkeypatch, tmp_path
) -> None:
    config_path = tmp_path / "catchment_report.toml"
    _write_report_config(config_path)
    _write_transient_config(tmp_path)
    _write_catalog_run(tmp_path / "sim_workspace", "test_run")
    order = []

    def fake_draw(inputs):
        order.append(("draw", inputs.simulation_name))
        return ()

    def fake_build_context(inputs, *, root=None):
        order.append(("context", inputs.simulation_name))
        return inputs.context_summary

    monkeypatch.setattr(
        "hydromodpy.display.catchment_report.pipeline.draw_missing_run_figures", fake_draw
    )
    monkeypatch.setattr(
        "hydromodpy.display.catchment_report.pipeline.build_context", fake_build_context
    )

    run_catchment_report_pipeline(
        config_path,
        run_simulation=False,
        build_context_artifacts=True,
        build_report_html=False,
    )

    assert order == [("draw", "test_run"), ("context", "test_run")]
