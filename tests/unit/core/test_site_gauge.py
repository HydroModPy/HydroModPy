"""[site] gauge is the single source of the station; a conflict is named."""

from __future__ import annotations

import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.site import GaugeConflictError, SiteConfig, resolve_gauge

SITE = SiteConfig(name="nancon", gauge="J0014010")


def test_an_absent_key_takes_the_gauge() -> None:
    assert resolve_gauge(SITE, None, field="calibration.observed_station_id") == "J0014010"
    assert resolve_gauge(SITE, [], field="data.hydrometry.sources.station_ids") == "J0014010"


def test_the_same_station_is_accepted() -> None:
    assert resolve_gauge(SITE, "J0014010", field="calibration.observed_station_id") == "J0014010"


def test_a_list_holding_the_gauge_is_accepted() -> None:
    declared = ["J0010010", "J0014010"]
    assert resolve_gauge(SITE, declared, field="data.hydrometry.sources.station_ids") == "J0014010"


def test_another_station_is_refused_naming_both_keys() -> None:
    with pytest.raises(GaugeConflictError) as caught:
        resolve_gauge(SITE, "J0010010", field="calibration.observed_station_id")
    message = str(caught.value)
    assert "site.gauge = 'J0014010'" in message
    assert "calibration.observed_station_id = 'J0010010'" in message
    assert isinstance(caught.value, ConfigError)


def test_a_list_without_the_gauge_is_refused() -> None:
    with pytest.raises(GaugeConflictError, match="station_ids"):
        resolve_gauge(SITE, ["J0010010"], field="data.hydrometry.sources.station_ids")


def test_without_a_site_gauge_the_declared_value_stands() -> None:
    bare = SiteConfig(name="nancon")
    assert resolve_gauge(bare, "J0010010", field="metrics.station") == "J0010010"
    assert resolve_gauge(None, ["A", "B"], field="data.hydrometry.sources.station_ids") == "A"
    assert resolve_gauge(None, None, field="metrics.station") is None
