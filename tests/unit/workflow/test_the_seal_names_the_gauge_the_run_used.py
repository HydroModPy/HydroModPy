"""The ``site`` block of the seal names the gauge the run was compared to.

``[site] gauge`` when it is declared; else the single hydrometric station the
run loaded; with none or several, no gauge.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.core.site import SiteConfig
from hydromodpy.workflow.steps.prepare_solver.validate import site_block


def _ctx(site: SiteConfig, stations: tuple[str, ...]) -> SimpleNamespace:
    catchment = SimpleNamespace(kind="from_outlet_coord", x_outlet=1.0, y_outlet=2.0)
    hydrometry = SimpleNamespace(points=[SimpleNamespace(station_id=s) for s in stations])
    return SimpleNamespace(
        cfg=SimpleNamespace(
            site=site,
            geographic=SimpleNamespace(catchment=catchment, crs_project="EPSG:2154"),
        ),
        loaded_data=SimpleNamespace(hydrometry=hydrometry),
    )


@pytest.mark.parametrize(
    ("declared", "stations", "gauge"),
    [
        ("J0014010", ("J0014010", "J0000001"), "J0014010"),
        (None, ("J0014010",), "J0014010"),
        (None, ("J0014010", "J0000001"), None),
        (None, (), None),
    ],
)
def test_the_gauge_is_declared_or_the_single_station_loaded(
    declared: str | None, stations: tuple[str, ...], gauge: str | None
) -> None:
    block = site_block(_ctx(SiteConfig(name="nancon", gauge=declared), stations))

    assert block is not None
    assert block.gauge == gauge
