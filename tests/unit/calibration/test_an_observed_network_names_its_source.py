"""An observed network output must name exactly one source for its geometry."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.calibration.config import CalibOutputNetwork


def _kwargs(**overrides: object) -> dict[object, object]:
    base = {"support": "network"}
    base.update(overrides)
    return base


def test_observed_network_data_hydrography_validates() -> None:
    output = CalibOutputNetwork(**_kwargs(observed_network="data.hydrography"))
    assert output.observed_network == "data.hydrography"
    assert output.stream_geometry_path is None


def test_observed_network_geographic_river_network_validates() -> None:
    output = CalibOutputNetwork(**_kwargs(observed_network="geographic.river_network"))
    assert output.observed_network == "geographic.river_network"
    assert output.stream_geometry_path is None


def test_stream_geometry_path_alone_validates() -> None:
    """Every file in the repository declares only this field today."""
    output = CalibOutputNetwork(**_kwargs(stream_geometry_path="streams.gpkg"))
    assert output.stream_geometry_path == "streams.gpkg"
    assert output.observed_network is None


def test_both_declared_refuses_naming_both_values() -> None:
    with pytest.raises(ValidationError) as excinfo:
        CalibOutputNetwork(
            **_kwargs(
                observed_network="data.hydrography",
                stream_geometry_path="streams.gpkg",
            )
        )
    message = str(excinfo.value)
    assert "data.hydrography" in message
    assert "streams.gpkg" in message


def test_neither_declared_refuses_naming_the_three_routes() -> None:
    with pytest.raises(ValidationError) as excinfo:
        CalibOutputNetwork(**_kwargs())
    message = str(excinfo.value)
    assert "data.hydrography" in message
    assert "geographic.river_network" in message
    assert "stream_geometry_path" in message
