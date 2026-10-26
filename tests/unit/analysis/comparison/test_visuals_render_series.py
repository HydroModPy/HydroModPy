"""Anti-regression rendering smoke tests for ``visuals_render_series``.

Exercises the series figure entry points end-to-end against a
``tmp_path``: timeseries, runtime bar, point dashboard, native flux
panel, flux dashboard, and budget diagnostic.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.analysis.comparison.visuals_render_series import (
    _write_budget_diagnostic_figure,
    _write_flux_dashboard,
    _write_native_flux_panel,
    _write_point_dashboard,
    _write_runtime_bar_figure,
    _write_storage_comparison_dashboard,
    _write_total_input_output_dashboard,
    write_timeseries_figure,
)
from hydromodpy.analysis.comparison.visuals_render_series.aggregation import _budget_zone_suffix


def test_write_timeseries_figure_creates_png(tmp_path: Path) -> None:
    rows = [
        {
            "simulation_id": "ref",
            "simulation_label": "Ref",
            "value_index": 0,
            "value": 1.0 + i * 0.1,
            "elapsed_seconds": float(i),
            "time_index": i,
        }
        for i in range(5)
    ]
    rows.extend(
        {
            "simulation_id": "cand",
            "simulation_label": "Cand",
            "value_index": 0,
            "value": 2.0 + i * 0.2,
            "elapsed_seconds": float(i),
            "time_index": i,
        }
        for i in range(5)
    )
    out = tmp_path / "ts.png"
    ok = write_timeseries_figure(
        path=out, observable_name="hydraulic_head", unit="m", grouped_rows=rows
    )
    assert ok is True
    assert out.exists()


def test_write_timeseries_figure_returns_false_when_too_few_points(
    tmp_path: Path,
) -> None:
    rows = [{"simulation_id": "ref", "value": 1.0, "time_index": 0, "value_index": 0}]
    out = tmp_path / "ts.png"
    assert (
        write_timeseries_figure(path=out, observable_name="head", unit="m", grouped_rows=rows)
        is False
    )


def test_write_runtime_bar_figure_creates_png(tmp_path: Path) -> None:
    rows = [
        {
            "simulation_id": "a",
            "simulation_label": "A",
            "runtime_seconds": 1.0,
            "solver": "modflow6",
        },
        {
            "simulation_id": "b",
            "simulation_label": "B",
            "runtime_seconds": 2.0,
            "solver": "modflow_nwt",
        },
    ]
    out = tmp_path / "rt.png"
    assert (
        _write_runtime_bar_figure(path=out, execution_rows=rows, reference_simulation="a") is True
    )
    assert out.exists()


def test_write_runtime_bar_figure_returns_false_when_below_two(tmp_path: Path) -> None:
    rows = [{"simulation_id": "a", "runtime_seconds": 1.0, "solver": "x"}]
    out = tmp_path / "rt.png"
    assert (
        _write_runtime_bar_figure(path=out, execution_rows=rows, reference_simulation=None) is False
    )


def test_write_point_dashboard_creates_png(tmp_path: Path) -> None:
    rows = []
    for obs in ("head_a", "head_b"):
        for i in range(4):
            rows.append(
                {
                    "support": "point",
                    "observable": obs,
                    "simulation_id": "ref",
                    "simulation_label": "Ref",
                    "value": 1.0 + i,
                    "time_index": i,
                    "unit": "m",
                }
            )
    out = tmp_path / "points.png"
    ok = _write_point_dashboard(path=out, rows=rows)
    assert ok is True
    assert out.exists()


def test_write_point_dashboard_returns_false_with_one_observable(
    tmp_path: Path,
) -> None:
    rows = [
        {
            "support": "point",
            "observable": "head",
            "simulation_id": "ref",
            "value": 1.0,
            "time_index": 0,
        }
    ]
    out = tmp_path / "points.png"
    assert _write_point_dashboard(path=out, rows=rows) is False


def test_write_native_flux_panel_creates_png(tmp_path: Path) -> None:
    long_rows = []
    for simulation in ("ref", "cand"):
        for i in range(4):
            long_rows.append(
                {
                    "variable": "accumulation_flux",
                    "simulation_id": simulation,
                    "simulation_label": simulation.upper(),
                    "value": float(i + (1 if simulation == "cand" else 0)),
                    "time_index": i,
                    "time_label": f"2024-0{i + 1}-01",
                }
            )
    delta_rows = [
        {
            "variable": "accumulation_flux",
            "simulation_id": "cand",
            "signed_error": 0.1 * i,
            "time_index": i,
            "time_label": f"2024-0{i + 1}-01",
        }
        for i in range(4)
    ]
    out = tmp_path / "flux.png"
    ok = _write_native_flux_panel(
        path=out,
        variable="accumulation_flux",
        long_rows=long_rows,
        delta_rows=delta_rows,
    )
    assert ok is True
    assert out.exists()


def test_write_flux_dashboard_creates_png(tmp_path: Path) -> None:
    rows = [
        {
            "observable": "outlet_flux_series",
            "simulation_id": "ref",
            "simulation_label": "Ref",
            "value": float(i),
            "time_index": i,
            "unit": "m3/s",
        }
        for i in range(4)
    ]
    rows.extend(
        {
            "observable": "outlet_flux_series",
            "simulation_id": "cand",
            "simulation_label": "Cand",
            "value": float(i) + 0.5,
            "time_index": i,
            "unit": "m3/s",
        }
        for i in range(4)
    )
    native_rows = []
    for variable in ("accumulation_flux", "outflow_drain"):
        for i in range(4):
            native_rows.append(
                {
                    "variable": variable,
                    "simulation_id": "ref",
                    "simulation_label": "Ref",
                    "value": float(i),
                    "time_index": i,
                    "time_label": f"2024-0{i + 1}-01",
                }
            )
            native_rows.append(
                {
                    "variable": variable,
                    "simulation_id": "cand",
                    "simulation_label": "Cand",
                    "value": float(i) + 0.5,
                    "time_index": i,
                    "time_label": f"2024-0{i + 1}-01",
                }
            )
    out = tmp_path / "dash.png"
    ok = _write_flux_dashboard(path=out, rows=rows, native_long_rows=native_rows)
    assert ok is True
    assert out.exists()


def test_write_budget_diagnostic_figure_creates_png(tmp_path: Path) -> None:
    budget_rows = []
    components = (
        "recharge_total_m3_s",
        "drainage_total_m3_s",
        "storage_change_total_m3_s",
        "closure_residual_m3_s",
    )
    for component in components:
        for i in range(4):
            budget_rows.append(
                {
                    "simulation_id": "ref",
                    "component": component,
                    "value": float(i),
                    "elapsed_seconds": float(i),
                    "time_index": i,
                    "time_label": f"2024-0{i + 1}-01",
                }
            )
    rows = [
        {
            "observable": "outlet_flux_series",
            "simulation_id": "ref",
            "simulation_label": "Ref",
            "value": float(i),
            "time_index": i,
            "elapsed_seconds": float(i),
            "unit": "m3/s",
        }
        for i in range(4)
    ]
    out = tmp_path / "budget.png"
    ok = _write_budget_diagnostic_figure(
        path=out,
        simulation_id="ref",
        simulation_label="Ref",
        budget_rows=budget_rows,
        rows=rows,
    )
    assert ok is True
    assert out.exists()


def test_write_budget_diagnostic_figure_returns_false_for_unknown_simulation(
    tmp_path: Path,
) -> None:
    out = tmp_path / "budget.png"
    ok = _write_budget_diagnostic_figure(
        path=out,
        simulation_id="missing",
        simulation_label="Missing",
        budget_rows=[],
        rows=[],
    )
    assert ok is False


def _budget_rows(zone: str | None) -> list[dict]:
    rows = []
    for component in ("recharge_total_m3_s", "storage_change_total_m3_s"):
        for i in range(3):
            row = {
                "simulation_id": "ref",
                "simulation_label": "Ref",
                "component": component,
                "value": 1.0 + i,
                "time_index": i,
                "elapsed_seconds": 86400.0 * i,
            }
            if zone is not None:
                row["budget_zone"] = zone
            rows.append(row)
    return rows


@pytest.mark.parametrize(
    ("zone", "suffix"),
    [("domain", " (model domain)"), ("catchment", " (delineated catchment)"), (None, "")],
)
def test_the_budget_zone_suffix_names_the_zone_the_rows_sum(zone, suffix) -> None:
    assert _budget_zone_suffix(_budget_rows(zone)) == suffix


def test_the_suffix_stays_silent_when_the_rows_mix_two_zones() -> None:
    assert _budget_zone_suffix(_budget_rows("domain") + _budget_rows("catchment")) == ""


@pytest.mark.parametrize(
    ("write", "title"),
    [
        (_write_storage_comparison_dashboard, "Storage comparison"),
        (_write_total_input_output_dashboard, "Total inputs and outputs"),
    ],
)
def test_the_budget_dashboards_name_their_zone_in_the_title(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write, title: str
) -> None:
    from matplotlib.figure import Figure

    titles: list[str] = []
    suptitle = Figure.suptitle

    def spy(self, text, *args, **kwargs):
        titles.append(text)
        return suptitle(self, text, *args, **kwargs)

    monkeypatch.setattr(Figure, "suptitle", spy)

    assert write(path=tmp_path / "budget.png", budget_rows=_budget_rows("catchment"))
    assert titles == [f"{title} (delineated catchment)"]
