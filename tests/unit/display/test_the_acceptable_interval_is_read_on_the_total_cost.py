"""The interval around a calibrated value is a margin on the TOTAL cost, never on a block.

Audit decision m27: the acceptable set of a calibration is the trials whose
total cost stays within one margin of the best total cost. There is no threshold
per objective block. Two blocks that disagree on their best trial must still
give one interval, the one read on ``objective_value``, and a block cost drawn
on its own gets none.
"""

from __future__ import annotations

import pytest

from hydromodpy.calibration.optim.cost_margin import margin_intervals
from hydromodpy.display.figures.calibration_progress import _read_search
from hydromodpy.display.figures.parameter_cost_profile import ParameterCostProfileFigure

from ._calibration_journal import journal_run

VALUES = [1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1, 1.0]
HYDROGRAPH = [9.0, 4.0, 1.0, 1.5, 2.5, 6.0, 9.0]
"""Best at 1e-4, and within 5 % of its best nowhere else."""
HEADS = [8.0, 6.0, 3.0, 1.5, 0.5, 0.51, 8.0]
"""Best at 1e-2, and within 5 % of its best at 1e-1 as well."""
TOTAL = [h + w for h, w in zip(HYDROGRAPH, HEADS, strict=True)]

CONFIG = {
    "method": "scipy_nelder_mead",
    "parameters": {"K": {"bounds": [1e-7, 10.0], "search_space": "log", "units": "m/s"}},
    "objective_blocks": [
        {"name": "hydrograph", "metric": "rmse", "weight": 1.0, "normalize_cost": False},
        {"name": "heads", "metric": "rmse", "weight": 1.0, "normalize_cost": False},
    ],
    "uncertainty": {"method": "cost_profile", "cost_margin": None},
}


@pytest.fixture
def mpl():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


def _run(tmp_path):
    rows = [
        {
            "trial": trial,
            "status": "completed",
            "objective_value": total,
            "parameters": {"K": {"value": value, "units": "m/s"}},
            "metrics": {"hydrograph.raw_cost": hydrograph, "heads.raw_cost": heads},
        }
        for trial, (value, total, hydrograph, heads) in enumerate(
            zip(VALUES, TOTAL, HYDROGRAPH, HEADS, strict=True), start=1
        )
    ]
    return journal_run(
        tmp_path,
        rows,
        method="scipy_nelder_mead",
        phase="transient_conductivity",
        config=CONFIG,
        search_space={"K": {"bounds": [1e-7, 10.0], "units": "m/s"}},
        best_trial=4,
    )


def _band(ax) -> tuple[float, float] | None:
    for patch in ax.patches:
        if str(patch.get_label()).startswith("within"):
            return float(patch.get_x()), float(patch.get_x() + patch.get_width())
    return None


def test_the_figure_shades_the_margin_on_the_total_cost(mpl, tmp_path) -> None:
    run = _run(tmp_path)
    total = margin_intervals(
        [{"K": v, "objective_value": c} for v, c in zip(VALUES, TOTAL, strict=True)],
        ["K"],
        margin=0.05,
    )[0]
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(run, ax)

    try:
        assert _band(ax) == pytest.approx((total.lower, total.upper))
        assert _read_search(run, session_id=None, output=None).intervals["K"] == pytest.approx(
            (total.lower, total.upper)
        )
    finally:
        mpl.close(fig)


def test_the_blocks_do_not_each_make_their_own_interval(mpl, tmp_path) -> None:
    """Neither block interval, alone or joined, is the interval drawn."""
    per_block = [
        margin_intervals(
            [{"K": v, "objective_value": c} for v, c in zip(VALUES, costs, strict=True)],
            ["K"],
            margin=0.05,
        )[0]
        for costs in (HYDROGRAPH, HEADS)
    ]
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(_run(tmp_path), ax)

    try:
        drawn = _band(ax)
        assert drawn is not None
        for block in per_block:
            assert drawn != pytest.approx((block.lower, block.upper))
        joined = (min(b.lower for b in per_block), max(b.upper for b in per_block))
        assert drawn != pytest.approx(joined)
    finally:
        mpl.close(fig)


def test_a_block_cost_drawn_alone_gets_no_interval(mpl, tmp_path) -> None:
    fig, ax = mpl.subplots()

    ParameterCostProfileFigure().render(_run(tmp_path), ax, objective="heads.raw_cost")

    try:
        assert _band(ax) is None
    finally:
        mpl.close(fig)
