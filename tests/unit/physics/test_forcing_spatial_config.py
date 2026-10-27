"""The spatial source of a recharge or ETP forcing: its mode, its interpolation and its record.

``spatial_mode`` and ``interpolation_method`` are read by the forcing path on
cells (``hydromodpy.spatial.mesh.forcing``), ``heterogeneous_source`` holds the
records it reads.
"""

from __future__ import annotations

import numpy as np
import pytest
import xarray as xr
from pydantic import ValidationError

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.physics.flow.sinks_sources import FlowEtpConfig, FlowRechargeConfig

pytestmark = pytest.mark.fast

CONFIGS = pytest.mark.parametrize("config", [FlowRechargeConfig, FlowEtpConfig])


def _one_pixel_source() -> LoadResult:
    grid = xr.Dataset(
        {"recharge": (("y", "x"), np.full((1, 1), 5.0))}, coords={"x": [0.5], "y": [0.5]}
    )
    record = FieldRecord(
        variable="recharge",
        source="test",
        unit="mm/day",
        data=grid,
        bbox=(0, 0, 1, 1),
        crs="EPSG:2154",
    )
    return LoadResult(fields=[record])


def test_the_recharge_keeps_its_heterogeneous_source_as_given():
    source = _one_pixel_source()

    config = FlowRechargeConfig(
        values=0.0, heterogeneous_source=source, first_clim="mean", units="m/s"
    )

    assert config.heterogeneous_source is source


def test_the_recharge_has_no_heterogeneous_source_by_default():
    assert FlowRechargeConfig(values=1.0e-8).heterogeneous_source is None


@CONFIGS
def test_the_forcing_configs_choose_the_spatial_mode_from_the_source_by_default(config):
    assert config().spatial_mode == "auto"


@CONFIGS
def test_the_forcing_configs_keep_nearest_as_default(config):
    assert config().interpolation_method == "nearest"


@CONFIGS
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("spatial_mode", "homogeneous"),
        ("interpolation_method", "idw"),
        ("interpolation_method", "area"),
    ],
)
def test_the_forcing_configs_accept_a_known_spatial_choice(config, field, value):
    assert getattr(config(**{field: value}), field) == value


@CONFIGS
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("spatial_mode", "invalid"),
        ("interpolation_method", "cubic"),
        ("interpolation_method", "bilinear"),
    ],
)
def test_the_forcing_configs_refuse_an_unknown_spatial_choice(config, field, value):
    with pytest.raises(ValidationError, match=field):
        config(**{field: value})
