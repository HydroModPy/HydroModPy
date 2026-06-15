from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pytest


@dataclass
class _Payload:
    session_id: str
    session: dict
    iterations: list[dict]
    workspace_root: Path
    best_sim_id: str | None = None
    sim_timeseries: pd.DataFrame | None = None
    obs_timeseries: pd.DataFrame | None = None
    variable: str = "discharge"


class _Figure:
    def plot(self, sim, *, save_path: Path, **kwargs) -> None:
        del sim, kwargs
        Path(save_path).write_bytes(b"png")


def _payload(tmp_path: Path) -> _Payload:
    return _Payload(
        session_id="abcdef123456",
        session={"session_id": "abcdef123456", "method": "grid"},
        iterations=[
            {
                "iteration": 0,
                "objective_value": 1.0,
                "status": "completed",
                "parameters": {},
            }
        ],
        workspace_root=tmp_path,
    )


def test_render_session_skips_unknown_figure_and_still_writes_html(tmp_path, monkeypatch) -> None:
    import hydromodpy.reporting.calibration_report as report

    monkeypatch.setattr(report, "_figure_names", lambda: ["calibration_trace"])

    # An unknown figure is skipped (logged), not fatal: the HTML still renders.
    written = report.render_session(
        _payload(tmp_path),
        figure_names=["missing_figure"],
        output_dir=tmp_path / "report",
    )
    html_path = tmp_path / "report" / "report.html"
    assert html_path in written
    assert html_path.exists()


def test_render_session_skips_failing_figure_and_still_writes_html(tmp_path, monkeypatch) -> None:
    import hydromodpy.reporting.calibration_report as report

    class _FailingFigure:
        def plot(self, sim, *, save_path: Path, **kwargs) -> None:
            del sim, save_path, kwargs
            raise ValueError("bad inputs")

    monkeypatch.setattr(report, "_figure_names", lambda: ["calibration_trace"])
    monkeypatch.setattr(report, "_get_figure", lambda name: _FailingFigure())

    # A registered figure that raises is skipped, not fatal.
    written = report.render_session(
        _payload(tmp_path),
        figure_names=["calibration_trace"],
        output_dir=tmp_path / "report",
    )
    html_path = tmp_path / "report" / "report.html"
    assert html_path in written
    assert html_path.exists()


def test_best_obs_vs_sim_skips_when_observed_data_missing(tmp_path, monkeypatch) -> None:
    import hydromodpy.reporting.calibration_report as report

    monkeypatch.setattr(report, "_figure_names", lambda: ["calibration_trace"])
    monkeypatch.setattr(report, "_get_figure", lambda name: _Figure())
    payload = _payload(tmp_path)
    payload.best_sim_id = "1" * 32
    payload.sim_timeseries = pd.DataFrame(
        {"datetime": pd.date_range("2020-01-01", periods=2), "value": [1.0, 2.0]}
    )
    payload.obs_timeseries = pd.DataFrame(columns=["datetime", "value"])

    # Missing observed series skips the obs-vs-sim panel but still renders the report.
    written = report.render_session(
        payload,
        figure_names=["calibration_trace"],
        output_dir=tmp_path / "report",
    )
    figures_dir = tmp_path / "report" / "figures"
    assert (tmp_path / "report" / "report.html").exists()
    assert not (figures_dir / "best_obs_vs_sim.png").exists()
    assert all(p.name != "best_obs_vs_sim.png" for p in written)


def test_render_session_renders_lake_level_fit_panel(tmp_path, monkeypatch) -> None:
    import hydromodpy.reporting.calibration_report as report

    monkeypatch.setattr(report, "_figure_names", lambda: ["calibration_trace"])
    monkeypatch.setattr(report, "_get_figure", lambda name: _Figure())
    payload = _payload(tmp_path)
    payload.variable = "lake_level"
    payload.best_sim_id = "1" * 32
    dates = pd.date_range("2019-01-01", periods=5)
    payload.sim_timeseries = pd.DataFrame(
        {"datetime": dates, "value": [80.0, 81.0, 82.0, 83.0, 84.0]}
    )
    payload.obs_timeseries = pd.DataFrame(
        {"datetime": dates, "value": [80.1, 81.1, 82.1, 83.1, 84.1]}
    )

    written = report.render_session(
        payload,
        figure_names=["calibration_trace"],
        output_dir=tmp_path / "report",
    )
    fit = tmp_path / "report" / "figures" / "best_lake_level_fit.png"
    assert fit.exists()
    assert fit in written
    assert "best_lake_level_fit.png" in (tmp_path / "report" / "report.html").read_text()


def test_flatten_iterations_lifts_params_into_numeric_columns() -> None:
    import hydromodpy.reporting.calibration_report as report

    rows = [
        {
            "iteration": 0,
            "objective_value": 0.5,
            "status": "completed",
            "sim_id": "deadbeef",
            "parameters": {
                "K": {"value": 1e-4, "transform": "log"},
                "bedleak": {"value": 2e-6},
            },
        },
        # parameters as a JSON string (as persisted in DuckDB)
        {
            "iteration": 1,
            "objective_value": 0.3,
            "parameters": '{"K": {"value": 5e-5}, "bedleak": {"value": 9e-6}}',
        },
    ]
    flat = report._flatten_iterations(rows)
    assert flat[0] == {"iteration": 0, "objective": 0.5, "K": 1e-4, "bedleak": 2e-6}
    assert flat[1]["K"] == 5e-5
    assert flat[1]["bedleak"] == 9e-6
    # No nested dict / non-numeric leaks through (figures float-convert columns).
    assert all(isinstance(v, (int, float)) for v in flat[0].values())


def test_render_html_escapes_session_rows_figures_and_iteration_preview() -> None:
    import hydromodpy.reporting.calibration_report as report

    html = report._render_html(
        {
            "session_id": "abc-def",
            "project": "<Project & Co>",
            "method": 'grid "fast"',
            "status": "<script>alert(1)</script>",
            "best_sim_id": "dead-beef",
        },
        [
            {
                "iteration": 1,
                "objective_value": 0.125,
                "status": "<done>",
                "parameters": {"b": "<tag>", "a": 1},
            }
        ],
        [("<Figure & Name>", Path("unsafe&figure<1>.png"))],
    )

    assert "<Project & Co>" not in html
    assert "<script>alert(1)</script>" not in html
    assert "<Figure & Name>" not in html
    assert "unsafe&figure<1>.png" not in html
    assert "&lt;Project &amp; Co&gt;" in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "figures/unsafe&amp;figure&lt;1&gt;.png" in html
    assert "{&quot;a&quot;: 1, &quot;b&quot;: &quot;&lt;tag&gt;&quot;}" in html
