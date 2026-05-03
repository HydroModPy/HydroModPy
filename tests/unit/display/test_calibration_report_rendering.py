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


def test_render_session_raises_when_requested_figure_is_unknown(tmp_path, monkeypatch) -> None:
    import hydromodpy.display.calibration_report as report

    monkeypatch.setattr(report, "_figure_names", lambda: ["calibration_trace"])

    with pytest.raises(RuntimeError, match="missing_figure: figure is not registered"):
        report.render_session(
            _payload(tmp_path),
            figure_names=["missing_figure"],
            output_dir=tmp_path / "report",
        )


def test_render_session_raises_when_registered_figure_fails(tmp_path, monkeypatch) -> None:
    import hydromodpy.display.calibration_report as report

    class _FailingFigure:
        def plot(self, sim, *, save_path: Path, **kwargs) -> None:
            del sim, save_path, kwargs
            raise ValueError("bad inputs")

    monkeypatch.setattr(report, "_figure_names", lambda: ["calibration_trace"])
    monkeypatch.setattr(report, "_get_figure", lambda name: _FailingFigure())

    with pytest.raises(RuntimeError, match="calibration_trace: bad inputs"):
        report.render_session(
            _payload(tmp_path),
            figure_names=["calibration_trace"],
            output_dir=tmp_path / "report",
        )


def test_best_obs_vs_sim_requires_observed_data(tmp_path, monkeypatch) -> None:
    import hydromodpy.display.calibration_report as report

    monkeypatch.setattr(report, "_figure_names", lambda: ["calibration_trace"])
    monkeypatch.setattr(report, "_get_figure", lambda name: _Figure())
    payload = _payload(tmp_path)
    payload.best_sim_id = "1" * 32
    payload.sim_timeseries = pd.DataFrame(
        {"datetime": pd.date_range("2020-01-01", periods=2), "value": [1.0, 2.0]}
    )
    payload.obs_timeseries = pd.DataFrame(columns=["datetime", "value"])

    with pytest.raises(ValueError, match="no observed discharge"):
        report.render_session(
            payload,
            figure_names=["calibration_trace"],
            output_dir=tmp_path / "report",
        )
