"""Tests for the ``DelineationBackend`` Protocol.

Exercises the high-level contract defined in
``hydromodpy.spatial.delineation.base`` against each concrete backend
class. Backends that are pure stubs must still satisfy the Protocol
shape (attribute / method names) even if calling them raises
``NotImplementedError``.
"""

from __future__ import annotations

import pytest

from hydromodpy.spatial.delineation import (
    DelineationBackend,
    WhiteboxDelineationBackend,
    WhiteboxFlowBackend,
    WhiteboxRasterBackend,
)
from hydromodpy.spatial.delineation.pysheds_backend import PyshedsBackend
from hydromodpy.spatial.delineation.synthetic_backend import SyntheticBackend
from hydromodpy.spatial.delineation.whitebox_cli_backend import WhiteboxCliBackend


def test_delineation_protocol_has_expected_methods() -> None:
    for name in (
        "flow_accumulation",
        "flow_direction",
        "stream_network",
        "catchment_from_outlet",
    ):
        assert hasattr(DelineationBackend, name)


def test_whitebox_split_backends_expose_thematic_surfaces() -> None:
    for name in ("read_raster", "write_raster", "clip_raster_to_polygon"):
        assert hasattr(WhiteboxRasterBackend, name)
    for name in ("fill_depressions", "breach_depressions", "d8_pointer", "d8_flow_accumulation"):
        assert hasattr(WhiteboxFlowBackend, name)
    for name in ("watershed", "extract_streams", "snap_pour_points"):
        assert hasattr(WhiteboxDelineationBackend, name)


@pytest.mark.parametrize(
    "cls,expected_name",
    [
        (WhiteboxCliBackend, "whitebox_cli"),
        (PyshedsBackend, "pysheds"),
        (SyntheticBackend, "synthetic"),
    ],
)
def test_backend_classes_expose_name(cls: type, expected_name: str) -> None:
    assert cls.name == expected_name


def test_synthetic_backend_instantiates() -> None:
    backend = SyntheticBackend()
    assert backend.name == "synthetic"
    with pytest.raises(NotImplementedError):
        backend.flow_accumulation(dem=None)
    with pytest.raises(NotImplementedError):
        backend.flow_direction(dem=None)
    with pytest.raises(NotImplementedError):
        backend.stream_network(dem=None, threshold=100.0)
    with pytest.raises(NotImplementedError):
        backend.catchment_from_outlet(dem=None, x=0.0, y=0.0)


def test_pysheds_backend_refuses_instantiation() -> None:
    with pytest.raises(NotImplementedError):
        PyshedsBackend()


def test_whitebox_cli_backend_refuses_instantiation() -> None:
    with pytest.raises(NotImplementedError):
        WhiteboxCliBackend()
