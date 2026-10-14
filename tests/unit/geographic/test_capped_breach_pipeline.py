"""The geographic pipeline hands the capped-breach limits down and never retries a failed breach."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.exceptions import EmptyCatchmentError
from hydromodpy.spatial.geographic import pipeline as runtime_pipeline
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from hydromodpy.spatial.terrain import CappedBreach
from tests._helpers import ground_bench as bench
from tests._helpers.terrain_doubles import fake_flow_products


def _config(tmp_path: Path, method: str, **overrides) -> GeographicConfig:
    dem = bench.write_raster(tmp_path / "dem.tif", bench.valley())
    return GeographicConfig.from_outlet(
        x=bench.x_of(bench.AXIS),
        y=bench.y_of(bench.N - 2),
        dem=dem,
        snap_dist="50 m",
        buff_area="10%",
        crs_project=bench.CRS,
        dem_correc_type=method,
        **overrides,
    )


def _delineate(tmp_path: Path, monkeypatch, config: GeographicConfig) -> list[dict[str, object]]:
    """Run the pipeline until the catchment step, which fails as a breach can."""
    flow_calls: list[dict[str, object]] = []

    def _flow(**kwargs):
        flow_calls.append(kwargs)
        return fake_flow_products(method=str(kwargs["dem_correc_type"]))

    def _empty_catchment(**kwargs):
        raise EmptyCatchmentError("Outlet 'outlet' delineated an empty catchment.")

    tool = SimpleNamespace(delineation=SimpleNamespace(polygons_to_lines=lambda *a, **k: None))
    monkeypatch.setattr(runtime_pipeline, "resolve_delineation_backend", lambda backend: tool)
    monkeypatch.setattr(runtime_pipeline, "build_regional_flow_products", _flow)
    monkeypatch.setattr(runtime_pipeline, "build_standard_catchment", _empty_catchment)
    with pytest.raises(EmptyCatchmentError):
        runtime_pipeline.build_geographic_runtime_context(
            config=config, out_dir_path=tmp_path / "results"
        )
    return flow_calls


def test_the_flow_step_is_given_the_capped_breach_limits(tmp_path, monkeypatch) -> None:
    config = _config(
        tmp_path, "capped_breach", capped_breach={"max_depth": 0.8, "max_distance": 100.0}
    )

    (call,) = _delineate(tmp_path, monkeypatch, config)

    assert call["dem_correc_type"] == "capped_breach"
    assert call["capped_breach"] == CappedBreach(max_depth_m=0.8, max_distance_m=100.0)


@pytest.mark.parametrize("method", ["breach", "capped_breach"])
def test_an_empty_catchment_is_raised_and_not_retried_with_a_fill(
    method, tmp_path, monkeypatch
) -> None:
    overrides = {"capped_breach": {"max_depth": 0.8, "max_distance": 100.0}}
    config = _config(tmp_path, method, **(overrides if method == "capped_breach" else {}))

    calls = _delineate(tmp_path, monkeypatch, config)

    assert [call["dem_correc_type"] for call in calls] == [method]
