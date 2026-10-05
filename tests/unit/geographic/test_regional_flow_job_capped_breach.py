"""The capped breach joins the regional flow request without moving an old address.

The two digests below were computed at the commit before the capped breach
existed, with a stub engine whose name, version and digest are fixed, over the
bytes ``dem-bytes-for-pinning``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from hydromodpy.spatial.geographic.core.flow_products import (
    CORRECTED_DEM_NAMES,
    conditioning_method,
    corrected_dem_name,
)
from hydromodpy.spatial.geographic.regional_flow_job import (
    RegionalFlowRequest,
    _resolved,
    regional_flow_identity,
)
from hydromodpy.spatial.terrain import CappedBreach

PINNED = {
    "fill": "sha256:ae0b66f1d8395b84fbad6e88bc6d1e34eb30e748590617874873bbde1a870d54",
    "breach": "sha256:ceb76da4c50af4dc16cec6e6e54653d730135226fe57d1bcfb85c0b2f239ab7d",
}


class _StubEngine:
    engine_id = "stub"
    engine_version = "1.0"

    def engine_digest(self) -> str:
        return "d" * 64


@pytest.fixture
def dem(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(
        "hydromodpy.spatial.geographic.regional_flow_job.terrain_registry.create",
        lambda engine_id, backend=None: _StubEngine(),
    )
    path = tmp_path / "dem.bin"
    path.write_bytes(b"dem-bytes-for-pinning")
    return path


def _identity(dem: Path, method: str, capped: CappedBreach | None = None) -> str:
    return regional_flow_identity(
        dem_init_path=dem,
        dem_correc_type=method,
        crs_project="EPSG:2154",
        engine_id="whitebox_workflows",
        capped_breach=capped,
    )


@pytest.mark.parametrize("method", ["fill", "breach"])
def test_a_fill_or_breach_request_keeps_the_address_it_had(dem, method) -> None:
    assert _identity(dem, method) == PINNED[method]


@pytest.mark.parametrize("method", ["fill", "breach"])
def test_a_fill_or_breach_request_hashes_the_same_inputs_as_before(dem, method) -> None:
    request = RegionalFlowRequest(
        dem_init_path=dem, dem_correc_type=method, crs_project="EPSG:2154"
    )
    inputs, _job_id, _size = _resolved(request)

    assert set(inputs) == {"dem_sha256", "dem_correc_type", "crs_project", "engine"}
    assert "capped_breach" not in request.document()


def test_the_limits_enter_the_address_of_the_capped_breach_and_only_it(dem) -> None:
    base = _identity(dem, "capped_breach", CappedBreach(0.5, 200.0))

    assert base not in PINNED.values()
    assert base == _identity(dem, "capped_breach", CappedBreach(0.5, 200.0))
    assert base != _identity(dem, "capped_breach", CappedBreach(0.6, 200.0))
    assert base != _identity(dem, "capped_breach", CappedBreach(0.5, 250.0))


def test_the_limits_are_in_the_resolved_inputs_for_the_capped_breach(dem) -> None:
    request = RegionalFlowRequest(
        dem_init_path=dem,
        dem_correc_type="capped_breach",
        capped_breach={"max_depth_m": 0.5, "max_distance_m": 200.0},
        crs_project="EPSG:2154",
    )
    inputs, _job_id, _size = _resolved(request)

    assert inputs["capped_breach"] == {"max_depth_m": 0.5, "max_distance_m": 200.0}


def test_limits_without_the_method_or_the_method_without_limits_are_refused(dem) -> None:
    with pytest.raises(ValidationError):
        _identity(dem, "fill", CappedBreach(0.5, 200.0))
    with pytest.raises(ValidationError):
        _identity(dem, "capped_breach")


def test_the_method_maps_to_the_port_value_and_a_file_of_its_own() -> None:
    limits = CappedBreach(0.5, 200.0)

    assert conditioning_method("fill") == "fill"
    assert conditioning_method("breach") == "breach"
    assert conditioning_method("capped_breach", limits) is limits
    assert corrected_dem_name("capped_breach") == "dem_capped_breach.tif"
    assert len(set(CORRECTED_DEM_NAMES.values())) == len(CORRECTED_DEM_NAMES)


def test_the_limits_are_required_by_the_capped_breach_and_refused_by_the_others() -> None:
    with pytest.raises(ValueError, match="needs its limits"):
        conditioning_method("capped_breach")
    with pytest.raises(ValueError, match="has none"):
        conditioning_method("fill", CappedBreach(0.5, 200.0))
