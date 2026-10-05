"""The geographic pipeline hands the capped-breach limits down, and retries it as a breach."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.core.exceptions import EmptyCatchmentError
from hydromodpy.spatial.geographic.core import domain_geographic_pipeline as pipeline
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from hydromodpy.spatial.terrain import CappedBreach
from tests._helpers.terrain_doubles import fake_flow_products


def _config(method: str, **overrides) -> GeographicConfig:
    return GeographicConfig.from_outlet(
        x=1.0, y=2.0, dem="dem.tif", dem_correc_type=method, **overrides
    )


@pytest.mark.parametrize(
    ("method", "retries"), [("fill", False), ("breach", True), ("capped_breach", True)]
)
def test_an_empty_catchment_is_retried_with_a_fill_for_the_methods_that_lower_cells(
    method, retries
) -> None:
    assert (
        pipeline._should_retry_with_fill(config=_config(method), error=EmptyCatchmentError("x"))
        is retries
    )


class _Anything:
    """A stand-in for the setup: any attribute is a path string."""

    def __getattr__(self, name: str) -> object:
        if name == "paths":
            return _Anything()
        return {"crs_project": "", "dem_res": 25.0}.get(name, f"/{name}")


def test_delineation_passes_the_limits_then_drops_them_on_the_fill_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def _flow(**kwargs):
        calls.append(kwargs)
        return fake_flow_products(method="fill")

    def _catchment(**kwargs):
        if len(calls) == 1:
            raise EmptyCatchmentError("Outlet 'outlet' delineated an empty catchment.")

    monkeypatch.setattr(pipeline, "build_regional_flow_products", _flow)
    monkeypatch.setattr(pipeline, "build_standard_catchment", _catchment)
    monkeypatch.setattr(pipeline, "build_river_network_products", lambda **kwargs: None)

    config = _config("capped_breach", capped_breach={"max_depth": 0.8, "max_distance": 100.0})
    _flow_products, effective, _network = pipeline._delineate(
        config=config, setup=_Anything(), routing_dem_path="routing.tif"
    )

    assert effective == "fill"
    assert calls[0]["dem_correc_type"] == "capped_breach"
    assert calls[0]["capped_breach"] == CappedBreach(max_depth_m=0.8, max_distance_m=100.0)
    assert calls[1]["dem_correc_type"] == "fill"
    assert "capped_breach" not in calls[1]
