"""A flux drawn in mm/period is divided by the area of the zone its rows sum over.

The ``catchment`` row of the budget is the water of the whole faces of the basin
of D. Divided by the whole domain it came out too small by the ratio of the two
areas. The domain row keeps the domain area, and a catchment row on a run that
stores no basin has no area to divide by.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.display.figures.flux_timeseries import FluxTimeseries
from tests._helpers.ugrid_meshes import quad_mesh

CELL = 100.0
NROW, NCOL = 4, 4
BASIN = np.zeros(NROW * NCOL, dtype=bool)
BASIN[[0, 1, 4, 5, 8, 9]] = True
DOMAIN_AREA = NROW * NCOL * CELL**2
BASIN_AREA = int(BASIN.sum()) * CELL**2
EDGES = pd.date_range("2000-01-01", periods=4, freq="D")
DAY = 86400.0
DOMAIN_RECHARGE = np.array([4.0, 3.0, 2.0])
BASIN_RECHARGE = np.array([1.5, 1.0, 0.5])


@pytest.fixture(autouse=True)
def mpl():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


def _budget(zones: tuple[str, ...]) -> pd.DataFrame:
    rows = []
    for zone in zones:
        flux = DOMAIN_RECHARGE if zone == "0" else BASIN_RECHARGE
        rows += [
            {"component": "recharge", "zone_id": zone, "timestep": t, "flux_in": v, "flux_out": 0.0}
            for t, v in enumerate(flux)
        ]
    return pd.DataFrame(rows)


def _run(zones: tuple[str, ...], *, basin: np.ndarray | None = BASIN) -> SimpleNamespace:
    vertices, connectivity = quad_mesh(NROW, NCOL, cell_size=CELL)
    stored = None if basin is None else (basin, {"basin_rule": "near_point"})
    return SimpleNamespace(
        sim_id="sim-zone",
        name="zone",
        periods=SimpleNamespace(edges=EDGES),
        mesh=SimpleNamespace(vertices=vertices, face_node_connectivity=connectivity),
        descent=SimpleNamespace(stored_basin=lambda: stored),
        budget=lambda: _budget(zones),
    )


def _drawn(run, mpl, **options):
    _, ax = mpl.subplots()
    FluxTimeseries().render(run, ax, units="mm/period", **options)
    recharge = next(line for line in ax.lines if line.get_label() == "recharge")
    return ax, np.asarray(recharge.get_ydata())[:-1]


def test_the_catchment_row_is_divided_by_the_area_of_the_basin(mpl) -> None:
    ax, depth = _drawn(_run(("0", "catchment")), mpl)

    np.testing.assert_allclose(depth, 1000.0 * DAY * BASIN_RECHARGE / BASIN_AREA)
    assert "over the delineated catchment" in ax.get_ylabel()


def test_the_old_depth_was_too_small_by_the_ratio_of_the_areas(mpl) -> None:
    _, depth = _drawn(_run(("0", "catchment")), mpl)

    over_the_domain = 1000.0 * DAY * BASIN_RECHARGE / DOMAIN_AREA
    np.testing.assert_allclose(over_the_domain / depth, BASIN_AREA / DOMAIN_AREA * np.ones(3))
    assert BASIN_AREA < DOMAIN_AREA


def test_the_domain_row_is_divided_by_the_area_of_the_domain(mpl) -> None:
    ax, depth = _drawn(_run(("0",)), mpl)

    np.testing.assert_allclose(depth, 1000.0 * DAY * DOMAIN_RECHARGE / DOMAIN_AREA)
    assert "over the model domain" in ax.get_ylabel()


def test_the_domain_row_needs_no_stored_basin(mpl) -> None:
    _, depth = _drawn(_run(("0",), basin=None), mpl)

    np.testing.assert_allclose(depth, 1000.0 * DAY * DOMAIN_RECHARGE / DOMAIN_AREA)


def test_a_catchment_row_without_a_stored_basin_has_no_depth(mpl) -> None:
    with pytest.raises(ValueError, match="stores no basin of D"):
        _drawn(_run(("0", "catchment"), basin=None), mpl)


def test_the_flux_in_m3_s_does_not_read_the_area(mpl) -> None:
    _, ax = mpl.subplots()
    run = _run(("0", "catchment"), basin=None)

    FluxTimeseries().render(run, ax)

    recharge = next(line for line in ax.lines if line.get_label() == "recharge")
    np.testing.assert_allclose(np.asarray(recharge.get_ydata())[:-1], BASIN_RECHARGE)
