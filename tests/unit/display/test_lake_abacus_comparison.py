"""Lake abacus comparison of a real and a simulated stage-volume curve (stage m, volume m3)."""

from __future__ import annotations

import hydromodpy.results.run.lake_abacus_view as view
from hydromodpy.display.figure import new_subplots
from hydromodpy.display.figure_registry import get
from hydromodpy.display.figures.lake_abacus_comparison import lake_abacus_fit_metrics


class FakeRun:
    name = "fake"
    sim_id = "0000"


def test_perfect_match_is_nse_one() -> None:
    real = [0.0, 100.0, 400.0, 900.0]

    metrics = lake_abacus_fit_metrics(real, real)

    assert metrics["nse"] == 1.0
    assert metrics["rmse"] == 0.0
    assert metrics["max_abs_error"] == 0.0


def test_registered_figure_renders_from_run(monkeypatch) -> None:
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
    figure = get("lake_abacus_comparison")
    fig, ax = new_subplots()

    figure.render(FakeRun(), ax)

    assert figure.spec.name == "lake_abacus_comparison"
    # Two curves drawn, the reference and the simulated one.
    assert len(ax.get_lines()) == 2
