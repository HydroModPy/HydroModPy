"""Lake abacus comparison figure: arrays in, PNG out, storage metrics returned."""

from __future__ import annotations

import numpy as np

from hydromodpy.display.figures.lake_abacus_comparison import (
    lake_abacus_fit_metrics,
    plot_lake_abacus_comparison,
)
from hydromodpy.reporting.lake_abacus_report import plot_lake_abacus_comparison_for_model


def test_metrics_perfect_match_is_nse_one():
    real = [0.0, 100.0, 400.0, 900.0]
    metrics = lake_abacus_fit_metrics(real, real)
    assert metrics["nse"] == 1.0
    assert metrics["rmse"] == 0.0
    assert metrics["max_abs_error"] == 0.0


def test_plot_writes_png_and_returns_metrics(tmp_path):
    stage = [20.0, 30.0, 40.0, 50.0]
    real_vol = [0.0, 1000.0, 4000.0, 9000.0]
    sim_vol = [0.0, 1010.0, 3980.0, 9050.0]
    real_area = [0.0, 100.0, 200.0, 300.0]
    sim_area = [0.0, 100.0, 200.0, 300.0]
    out = tmp_path / "abacus.png"
    metrics = plot_lake_abacus_comparison(
        stage, real_vol, real_area, sim_vol, sim_area, out_path=out, lake_id="lac0"
    )
    assert out.exists()
    assert out.stat().st_size > 0
    assert metrics["nse"] > 0.999


class _Model:
    def __init__(self, recon):
        self._lake_bed_reconstruction = recon


def test_report_for_model_renders_one_png_per_lake(tmp_path):
    stage = np.linspace(20.0, 60.0, 5).tolist()
    real_vol = [0.0, 12500.0, 50000.0, 112500.0, 200000.0]
    real_area = [0.0, 2500.0, 5000.0, 7500.0, 10000.0]
    recon = {
        "lac0": {
            "abacus_stage": stage,
            "abacus_volume": real_vol,
            "abacus_sarea": real_area,
            "sim_volume": real_vol,
            "sim_sarea": real_area,
        }
    }
    model = _Model(recon)
    results = plot_lake_abacus_comparison_for_model(model, figures_dir=tmp_path)
    assert set(results) == {"lac0"}
    assert results["lac0"]["metrics"]["nse"] == 1.0
    assert (tmp_path / "lake_abacus_lac0.png").exists()


def test_report_for_model_empty_without_reconstruction(tmp_path):
    model = _Model({})
    assert plot_lake_abacus_comparison_for_model(model, figures_dir=tmp_path) == {}


class _FakeRun:
    name = "fake"
    sim_id = "0000"


def test_registered_figure_renders_from_run(monkeypatch):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    import hydromodpy.results.lake_abacus_view as view
    from hydromodpy.display.catalog import get

    monkeypatch.setattr(
        view,
        "run_lake_abacus",
        lambda run, lake_id=None: {
            "stage": [20.0, 30.0, 40.0],
            "real_volume": [0.0, 1000.0, 4000.0],
            "sim_volume": [0.0, 1010.0, 3980.0],
            "real_sarea": [0.0, 100.0, 200.0],
            "sim_sarea": [0.0, 100.0, 200.0],
            "stage_unit": "m",
            "volume_unit": "m3",
        },
    )

    fig_obj = get("lake_abacus_comparison")
    assert fig_obj.spec.name == "lake_abacus_comparison"
    fig, ax = plt.subplots()
    fig_obj.render(_FakeRun(), ax)
    # Two curves drawn (reference + simulated).
    assert len(ax.get_lines()) == 2
    plt.close(fig)
