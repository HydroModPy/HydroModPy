"""Unit tests for piezometry example runner behavior."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from hydromodpy.data_managers.piezometry import run_piezometry_example as run_module


def test_main_exports_one_plot_per_loaded_station(monkeypatch, tmp_path: Path):
    """Ensure the example exports one figure per station with safe filenames."""
    calls: list[dict] = []

    class _FakePiezometerSet:
        """Minimal stub replacing ``PiezometerSet`` in run module tests."""

        def __init__(self):
            self.piezometers = {
                "06932X0178/P10": object(),
                "06216X0228/P30-10": object(),
            }
            self.measurement = "both"
            self.display = False
            self.date_start = datetime(2024, 1, 1)
            self.date_end = datetime(2025, 12, 31)
            self.output = None

        @classmethod
        def from_toml(cls, _config_path):
            return cls()

        def get_completeness_report(self):
            return None

        def plot_piezometer(self, *, piezometer_id=None, output_path=None, show=True, **_kwargs):
            calls.append(
                {
                    "piezometer_id": str(piezometer_id),
                    "output_path": Path(output_path),
                    "show": bool(show),
                }
            )
            return None

    monkeypatch.setattr(run_module, "PiezometerSet", _FakePiezometerSet)
    monkeypatch.setattr(run_module, "__file__", str(tmp_path / "run_piezometry_example.py"))

    run_module.main_piezometer_set()

    assert len(calls) == 2
    assert [item["piezometer_id"] for item in calls] == [
        "06216X0228/P30-10",
        "06932X0178/P10",
    ]
    assert calls[0]["output_path"] == tmp_path / "outputs" / "piezometer_plot_06216X0228_P30_10.png"
    assert calls[1]["output_path"] == tmp_path / "outputs" / "piezometer_plot_06932X0178_P10.png"
    assert calls[0]["show"] is True
    assert calls[1]["show"] is True
