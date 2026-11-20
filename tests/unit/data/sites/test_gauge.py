"""``[site] gauge`` is the single source of the station of a catchment.

A station source of hydrometry, recharge or runoff with no ``station_ids``
reads the gauge; a list that leaves the gauge out is refused with the name of
the key; a source that reads a grid file is left alone. Without a gauge, a
run that loads exactly one discharge station takes it as its gauge.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.site.config import GaugeConflictError, SiteConfig
from hydromodpy.data.loading.config_schema import DataConfig
from hydromodpy.data.sites.gauge import apply_site_gauge

NANCON = SiteConfig(name="nancon", gauge="NANCON")


def _data(**sources: list[dict]) -> DataConfig:
    return DataConfig.model_validate(
        {variable: {"sources": entries} for variable, entries in sources.items()}
    )


@pytest.mark.fast
def test_a_list_without_the_gauge_is_refused():
    data = _data(
        hydrometry=[{"source": "file", "path": "hydrometry"}],
        recharge=[{"source": "file", "path": "recharge", "station_ids": ["NANCON_REA"]}],
    )

    with pytest.raises(GaugeConflictError) as refused:
        apply_site_gauge(data, NANCON)

    message = str(refused.value)
    assert "site.gauge = 'NANCON'" in message
    assert "data.recharge.sources[0].station_ids = ['NANCON_REA']" in message


@pytest.mark.fast
def test_project_config_takes_the_gauge():
    base = {
        "geographic": {"source_mode": "synthetic"},
        "site": {"name": "nancon", "gauge": "NANCON"},
    }

    config = HydroModPyConfig.model_validate(
        {**base, "data": {"hydrometry": {"sources": [{"source": "file", "path": "h"}]}}}
    )
    assert config.data.hydrometry.sources[0].station_ids == ["NANCON"]

    with pytest.raises(ValidationError, match=r"data\.hydrometry\.sources\[0\]\.station_ids"):
        HydroModPyConfig.model_validate(
            {
                **base,
                "data": {
                    "hydrometry": {
                        "sources": [{"source": "file", "path": "h", "station_ids": ["X"]}]
                    }
                },
            }
        )
