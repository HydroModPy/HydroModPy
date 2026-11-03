"""The scaffolded demo answers to K: a higher K gives a lower mound, of the Dupuit size.

Until 2.0.0 the demo had no recharge and no drain, so the head was flat at 22.53 m whatever K
was, and a run proved nothing about a physical effect. It now takes a uniform recharge and
drains it at the land surface. The water balance closes, and on the K range where the water
table stays under the surface the mound is the one Dupuit gives over the sloping base.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import hydromodpy as hmp
from hydromodpy.data.workspace.scaffold import scaffold
from tests._helpers.demo_mound import AREA_M2, RECHARGE_M_S, dupuit_mound_m
from tests._helpers.tolerances import tol

pytestmark = [pytest.mark.integration, pytest.mark.binary, pytest.mark.nwt, pytest.mark.fast]

BUDGET_CLOSURE = tol("global_water_budget_closure")
MOUND_RTOL = tol("scaffolded_demo__mound_against_the_dupuit_integral")
SHAPE = (20, 20)


def _solve(demo: Path, name: str, k_m_s: float) -> hmp.Run:
    with hmp.Project(demo / "run_demo.toml", no_display=True) as opened:
        return opened.simulate(name=name, set={"K": k_m_s})


@pytest.fixture
def demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project = scaffold(tmp_path / "workspace") / "projects" / "example"
    monkeypatch.chdir(project)
    return project


def test_a_higher_k_gives_a_lower_mound_of_the_dupuit_size(demo: Path) -> None:
    mounds = {}
    for name, k_m_s in (("low", 5.0e-5), ("mid", 1.0e-4), ("high", 2.0e-4)):
        run = _solve(demo, name, k_m_s)
        budget = run.budget().set_index("component")
        recharge = budget.loc["recharge", "flux_in"]
        assert recharge == pytest.approx(RECHARGE_M_S * AREA_M2, rel=BUDGET_CLOSURE)
        assert abs(recharge - budget.loc["drain", "flux_out"]) / recharge < BUDGET_CLOSURE

        head = run.field("head")[0].reshape(SHAPE)
        top = run.mesh.topography.reshape(SHAPE)
        # Only the foot of the hillslope seeps, or Dupuit from the foot would not hold.
        assert (run.field("drain")[0].reshape(SHAPE)[:, :-1] == 0.0).all()
        assert (head[:, :-1] < top[:, :-1]).all()

        mounds[name] = head[:, 0].mean() - head[:, -1].mean()
        assert mounds[name] == pytest.approx(dupuit_mound_m(k_m_s), rel=MOUND_RTOL)
    assert mounds["low"] > mounds["mid"] > mounds["high"] > 0.0


def test_a_lower_k_widens_the_seepage_and_the_mound_stays_under_the_surface(demo: Path) -> None:
    """Below the K where the gradient reaches the slope, the surface caps what Dupuit would give."""
    run = _solve(demo, "seeping", 1.0e-5)
    head = run.field("head")[0].reshape(SHAPE)
    top = run.mesh.topography.reshape(SHAPE)
    seeping = run.field("drain")[0].reshape(SHAPE) != 0.0

    assert seeping[:, -5:].all()
    assert not seeping[:, 0].any()
    assert (head - top).max() < 0.01
    assert head[:, 0].mean() - head[:, -1].mean() < dupuit_mound_m(1.0e-5)
