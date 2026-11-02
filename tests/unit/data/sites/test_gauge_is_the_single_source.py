"""``[site] gauge`` is the single source of the station of a catchment.

A station source of hydrometry, recharge or runoff with no ``station_ids``
reads the gauge; a list that leaves the gauge out is refused with the name of
the key; a source that reads a grid file is left alone. Without a gauge, a
run that loads exactly one discharge station takes it as its gauge.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.site import GaugeConflictError, SiteConfig
from hydromodpy.data import DataManagersConfig
from hydromodpy.data.sites.gauge import apply_site_gauge, gauge_of_run

NANCON = SiteConfig(name="nancon", gauge="NANCON")


def _data(**sources: list[dict]) -> DataManagersConfig:
    return DataManagersConfig.model_validate(
        {variable: {"sources": entries} for variable, entries in sources.items()}
    )


@pytest.mark.fast
def test_a_station_source_without_station_ids_reads_the_gauge():
    data = _data(
        hydrometry=[{"source": "custom", "path": "hydrometry"}],
        recharge=[{"source": "custom", "path": "recharge"}],
        runoff=[{"source": "custom", "path": "runoff"}],
    )

    apply_site_gauge(data, NANCON)

    assert data.hydrometry.sources[0].station_ids == ["NANCON"]
    assert data.recharge.sources[0].station_ids == ["NANCON"]
    assert data.runoff.sources[0].station_ids == ["NANCON"]


@pytest.mark.fast
def test_a_hubeau_source_without_station_ids_fetches_the_gauge():
    data = _data(hydrometry=[{"source": "hubeau", "product": "QmnJ"}])

    apply_site_gauge(data, SiteConfig(name="nancon", gauge="J001401001"))

    assert data.hydrometry.sources[0].station_ids == ["J001401001"]


@pytest.mark.fast
def test_a_station_list_that_leaves_the_gauge_out_is_refused_by_name():
    data = _data(
        hydrometry=[{"source": "custom", "path": "hydrometry"}],
        recharge=[{"source": "custom", "path": "recharge", "station_ids": ["NANCON_REA"]}],
    )

    with pytest.raises(GaugeConflictError) as refused:
        apply_site_gauge(data, NANCON)

    message = str(refused.value)
    assert "site.gauge = 'NANCON'" in message
    assert "data.recharge.sources[0].station_ids = ['NANCON_REA']" in message


@pytest.mark.fast
def test_a_station_list_that_holds_the_gauge_is_kept_whole():
    data = _data(
        hydrometry=[{"source": "custom", "path": "hydrometry", "station_ids": ["UP", "NANCON"]}]
    )

    apply_site_gauge(data, NANCON)

    assert data.hydrometry.sources[0].station_ids == ["UP", "NANCON"]


@pytest.mark.fast
def test_a_grid_source_and_a_variable_outside_the_list_are_left_alone():
    data = _data(
        recharge=[{"source": "custom", "path": "recharge.nc"}],
        runoff=[{"source": "sim2"}],
        piezometry=[{"source": "custom", "path": "piezometry"}],
    )

    apply_site_gauge(data, NANCON)

    assert data.recharge.sources[0].station_ids is None
    assert data.runoff.sources[0].station_ids is None
    assert data.piezometry.sources[0].station_ids is None


@pytest.mark.fast
def test_without_a_gauge_the_declared_stations_stay_as_written():
    data = _data(
        hydrometry=[{"source": "custom", "path": "hydrometry"}],
        recharge=[{"source": "custom", "path": "recharge", "station_ids": ["A", "B"]}],
    )

    apply_site_gauge(data, SiteConfig(name="nancon"))
    apply_site_gauge(data, None)

    assert data.hydrometry.sources[0].station_ids is None
    assert data.recharge.sources[0].station_ids == ["A", "B"]


@pytest.mark.fast
def test_the_gauge_of_a_run_is_the_declared_one_else_its_single_station():
    class Loaded:
        def __init__(self, *station_ids: str) -> None:
            self.points = [SimpleNamespace(station_id=sid) for sid in station_ids]

    assert gauge_of_run(NANCON, Loaded("OTHER")) == "NANCON"
    assert gauge_of_run(SiteConfig(name="nancon"), Loaded("J001401001")) == "J001401001"
    assert gauge_of_run(None, Loaded("J001401001")) == "J001401001"
    assert gauge_of_run(SiteConfig(name="nancon"), Loaded("A", "B")) is None
    assert gauge_of_run(SiteConfig(name="nancon"), None) is None


@pytest.mark.fast
def test_the_project_config_takes_the_gauge_and_refuses_a_conflict():
    base = {
        "geographic": {"source_mode": "synthetic"},
        "site": {"name": "nancon", "gauge": "NANCON"},
    }

    config = HydroModPyConfig.model_validate(
        {**base, "data": {"hydrometry": {"sources": [{"source": "custom", "path": "h"}]}}}
    )
    assert config.data.hydrometry.sources[0].station_ids == ["NANCON"]

    with pytest.raises(ValidationError, match=r"data\.hydrometry\.sources\[0\]\.station_ids"):
        HydroModPyConfig.model_validate(
            {
                **base,
                "data": {
                    "hydrometry": {
                        "sources": [{"source": "custom", "path": "h", "station_ids": ["X"]}]
                    }
                },
            }
        )
